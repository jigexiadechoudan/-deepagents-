"""独立请求修复少量对象；事务式合并，重新检查完整候选并拒绝校验回退。"""

import json
from dataclasses import dataclass, field
from time import perf_counter

from langchain_deepseek import ChatDeepSeek

from audit.baseline_engine import run_baseline_engine
from research_agent.agent.prompts import build_repair_messages
from research_agent.config import Settings
from research_agent.schemas.repair import ExtractionRepair
from research_agent.schemas.typed import ExtractionResult
from research_agent.services.checks import run_checks


@dataclass
class RepairExecution:
    extraction: ExtractionResult
    records: list[dict] = field(default_factory=list)
    elapsed_seconds: float = 0.0


def _payload(extraction):
    return extraction.model_dump(by_alias=True, exclude_none=True)


def _issues(extraction, material, manifest):
    payload = _payload(extraction)
    checks = run_checks(payload, material)
    baseline = run_baseline_engine(payload, manifest, material) if manifest is not None else None
    return {
        "errors": [v for v in checks if v["severity"] == "error"],
        "warnings": [v for v in checks if v["severity"] == "warning"],
        "baseline": [v for v in (baseline or {}).get("items", []) if v["status"] != "pass"],
    }


def _failures(issues):
    return {
        ("check", v["check"], v.get("object_id"), v["message"])
        for v in issues["errors"]
    } | {
        ("baseline", v["check"]) for v in issues["baseline"]
        if v["status"] == "fail" and v.get("coverage") == "conflict"
    }


def _require_evidence(evidence, material):
    if not evidence or any(not ev.strip() or ev not in material for ev in evidence):
        raise ValueError("修复依据必须是非空白且逐字命中材料的原文片段")


def merge_repair(candidate: ExtractionResult, repair: ExtractionRepair, material: str) -> ExtractionResult:
    """不删除或重命名对象；所有改动必须逐字段声明且有原文依据。"""
    payload = _payload(candidate)
    ids = [obj["data"]["id"] for obj in payload["objects"]]
    if len(ids) != len(set(ids)):
        raise ValueError("候选存在重复 ID，无法安全定位局部替换；保留原候选供人工核对")
    positions = {oid: index for index, oid in enumerate(ids)}
    changed_ids = set()
    for revision in repair.replacements:
        oid = revision.target_id
        if oid not in positions or oid in changed_ids:
            raise ValueError(f"修复目标不存在或重复：{oid}")
        before = payload["objects"][positions[oid]]
        after = revision.replacement.model_dump(by_alias=True, exclude_none=True)
        if after["data"]["id"] != oid or after["object_type"] != before["object_type"]:
            raise ValueError(f"局部修复不得改变对象 ID 或类型：{oid}")
        actual = set()
        for key in set(before["data"]) | set(after["data"]):
            a = json.dumps(before["data"].get(key), ensure_ascii=False, sort_keys=True)
            b = json.dumps(after["data"].get(key), ensure_ascii=False, sort_keys=True)
            if a != b:
                actual.add(f"data.{key}")
        if before["evidence"] != after["evidence"]:
            actual.add("evidence")
        if actual != set(revision.changed_fields) or not actual:
            raise ValueError(f"对象 {oid} 的实际变更必须与 changed_fields 完全一致：{sorted(actual)}")
        if not revision.reason.strip():
            raise ValueError(f"对象 {oid} 的修复理由不能为空白")
        _require_evidence(revision.evidence, material)
        _require_evidence(after["evidence"], material)
        payload["objects"][positions[oid]] = after
        changed_ids.add(oid)
    for obj in repair.additions:
        addition = obj.model_dump(by_alias=True, exclude_none=True)
        oid = addition["data"]["id"]
        if oid in positions:
            raise ValueError(f"新增对象 ID 已存在：{oid}")
        _require_evidence(addition["evidence"], material)
        positions[oid] = len(payload["objects"])
        payload["objects"].append(addition)
    for revision in repair.report_changes:
        if not revision.reason.strip():
            raise ValueError("报告条目修复理由不能为空白")
        _require_evidence(revision.evidence, material)
        items = payload[revision.category]
        if revision.previous is not None:
            if items.count(revision.previous) != 1:
                raise ValueError("报告条目的旧值不存在或不唯一，不能静默覆盖")
            index = items.index(revision.previous)
            if revision.revised is None:
                items.pop(index)
            else:
                items[index] = revision.revised
        elif revision.revised and revision.revised not in items:
            items.append(revision.revised)
        else:
            raise ValueError("报告条目修正没有有效改动")
    if not repair.replacements and not repair.additions and not repair.report_changes:
        raise ValueError("未提供任何局部修复")
    return ExtractionResult.model_validate(payload)


def repair_extraction(candidate, settings: Settings, material: str, reference: str,
                      skill_references: dict[str, str], manifest: dict | None) -> RepairExecution:
    """语法合格后执行有限局部修复；失败保留上一份候选和诊断。"""
    execution = RepairExecution(extraction=candidate)
    started = perf_counter()
    feedback = None
    model = None
    for round_number in range(1, settings.max_check_rounds + 1):
        issues = _issues(execution.extraction, material, manifest)
        if not _failures(issues):
            break
        record = {"round": round_number, "issues_before": issues, "accepted": False}
        round_started = perf_counter()
        print(f"[局部修复] 第 {round_number} 轮：仅返回问题对象及必要的关联修正", flush=True)
        try:
            if model is None:
                model = ChatDeepSeek(**settings.model_params).with_structured_output(
                    ExtractionRepair, method="json_mode", include_raw=True
                )
            response = model.invoke(
                build_repair_messages(material, reference, skill_references,
                                      _payload(execution.extraction), issues, feedback)
            )
            raw = response.get("raw")
            usage = getattr(raw, "usage_metadata", None) or {}
            record["input_tokens"] = usage.get("input_tokens", 0)
            record["output_tokens"] = usage.get("output_tokens", 0)
            record["raw_response"] = raw.model_dump(mode="json") if raw else None
            if response.get("parsing_error") or response.get("parsed") is None:
                raise ValueError(f"内部修复协议解析失败：{response.get('parsing_error')}")
            repair = response["parsed"]
            record["patch"] = repair.model_dump(mode="json", by_alias=True)
            merged = merge_repair(execution.extraction, repair, material)
            after = _issues(merged, material, manifest)
            record["issues_after"] = after
            new_failures = _failures(after) - _failures(issues)
            old_warnings = {(v["check"], v.get("object_id"), v["message"]) for v in issues["warnings"]}
            new_warnings = {(v["check"], v.get("object_id"), v["message"]) for v in after["warnings"]} - old_warnings
            ranks = {"structured": 0, "not_checked": 0, "text": 1,
                     "partial": 2, "review": 2, "uncovered": 3, "conflict": 4}
            def rank(item):
                return ranks.get(item.get("coverage"), 4 if item["status"] == "fail" else 1)
            old_baseline = {v["check"]: rank(v) for v in issues["baseline"]}
            new_coverage_gaps = {v["check"] for v in after["baseline"]
                                 if rank(v) > old_baseline.get(v["check"], 0)}
            if new_failures or new_warnings or new_coverage_gaps:
                raise ValueError(
                    "合并引入新的校验失败、告警或覆盖缺口，整轮回滚："
                    f"{sorted(map(str, new_failures | new_warnings | new_coverage_gaps))}"
                )
            execution.extraction = merged
            record["accepted"] = True
            feedback = None
        except Exception as error:
            feedback = str(error)
            record["error"] = feedback
            print(f"[局部修复] 未采纳本轮修正，保留上一份候选：{error}", flush=True)
        record["elapsed_seconds"] = round(perf_counter() - round_started, 3)
        execution.records.append(record)
    execution.elapsed_seconds = round(perf_counter() - started, 3)
    return execution
