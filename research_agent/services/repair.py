"""独立请求修复少量对象；事务式合并，重新检查完整候选并拒绝校验回退。"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from time import perf_counter

from langchain_deepseek import ChatDeepSeek
from pydantic import ValidationError

from audit.baseline_engine import run_baseline_engine
from research_agent.agent.prompts import build_repair_messages
from research_agent.config import Settings
from research_agent.schemas.repair import ExtractionRepair
from research_agent.schemas.typed import ExtractionResult
from research_agent.services.checks import REFERENCE_KEYS, run_checks


@dataclass
class RepairExecution:
    extraction: ExtractionResult
    checks: list[dict]
    baseline: dict | None
    records: list[dict] = field(default_factory=list)
    elapsed_seconds: float = 0.0


def _payload(extraction):
    return extraction.model_dump(by_alias=True, exclude_none=True)


def _check_candidate(extraction, material, manifest):
    payload = _payload(extraction)
    checks = run_checks(payload, material)
    baseline = run_baseline_engine(payload, manifest, material) if manifest is not None else None
    return checks, baseline


def _issues(checks, baseline):
    return {
        "errors": [v for v in checks if v["severity"] == "error"],
        "warnings": [v for v in checks if v["severity"] == "warning"],
        "baseline": [v for v in (baseline or {}).get("items", []) if v["status"] != "pass"],
    }


def _issue_key(issue, report_lineage=None):
    """有定位信息时按规则和位置识别问题，不以解释文案充当身份。"""
    if "rule_code" not in issue or "locator" not in issue:
        # 历史或外部诊断缺少定位信息时，保留原先的保守比较，避免合并不同问题。
        return ("check", issue["check"], issue.get("object_id"), issue["message"])
    locator = issue["locator"]
    if isinstance(locator, dict) and "report" in locator and "index" in locator:
        category, index = locator["report"], locator["index"]
        origin = report_lineage[category][index] if report_lineage is not None else ("existing", index)
        locator = {"report": category, "origin": origin}
    return ("check", issue["rule_code"], issue.get("object_id"), issue.get("field"),
            json.dumps(locator, ensure_ascii=False, sort_keys=True))


def _issue_counts(items, report_lineage=None):
    return Counter(_issue_key(item, report_lineage) for item in items)


def _failures(issues, report_lineage=None):
    return _issue_counts(issues["errors"], report_lineage) + Counter(
        ("baseline", v["check"]) for v in issues["baseline"]
        if v["status"] == "fail" and v.get("coverage") == "conflict"
    )


def _coverage_changes(previous, current):
    """分别检查已保留事实丢失、核验退步和结构化变化，不把待复核状态排成质量分数。"""
    before = {item["check"]: item for item in (previous or {}).get("items", [])}
    after = {item["check"]: item for item in (current or {}).get("items", [])}
    regressions, structure_notes = set(), []

    def content(item):
        return item.get("content_coverage") or {
            "structured": "covered", "text": "covered", "partial": "partial",
            "uncovered": "not_found", "conflict": "conflict", "review": "unverified",
            "not_checked": "unknown",
        }.get(item.get("coverage"), "unverified")

    for key, old in before.items():
        new = after.get(key)
        if content(old) not in {"covered", "partial"}:
            continue
        if new is None:
            regressions.add(("coverage_check_missing", key))
        elif content(new) in {"not_found", "conflict"} or (content(old) == "covered" and content(new) == "partial"):
            regressions.add(("content_coverage_lost", key))
        elif content(new) in {"unverified", "unknown"}:
            regressions.add(("coverage_verification_lost", key))
        elif old.get("coverage") == "structured" and new.get("coverage") == "text":
            structure_notes.append({"check": key, "kind": "structure_downgrade",
                                    "message": "事实仍有文字承接，结构化程度下降，需复核具体落点"})
    for key, new in after.items():
        old = before.get(key, {})
        if new.get("reason_code") == "value_without_source" and old.get("reason_code") != "value_without_source":
            regressions.add(("new_unverified_assertion", key))
        if "coverage" not in new and new["status"] == "fail" and old.get("status") != "fail":
            regressions.add(("legacy_check_failed", key))
    return regressions, structure_notes


def _report_lineage(candidate, repair):
    """按已经通过合并校验的 previous/revised 跟踪报告条目，避免改写或删除造成身份漂移。"""
    entries = {name: list(getattr(candidate, name)) for name in ("omissions", "conflicts", "unknowns")}
    origins = {name: [("existing", index) for index in range(len(items))]
               for name, items in entries.items()}
    for number, revision in enumerate(repair.report_changes):
        items, identities = entries[revision.category], origins[revision.category]
        if revision.previous is not None:
            index = items.index(revision.previous)
            if revision.revised is None:
                items.pop(index)
                identities.pop(index)
            else:
                items[index] = revision.revised
        else:
            items.append(revision.revised)
            identities.append(("new", number))
    return origins


def _require_evidence(evidence, material):
    if not evidence or any(not ev.strip() or ev not in material for ev in evidence):
        raise ValueError("修复依据必须是非空白且逐字命中材料的原文片段")


def _repair_scope(candidate, issues):
    """由确定错误产生白名单；与 changed_fields 一致，限制到对象的顶层字段。"""
    objects = {obj.data.id for obj in candidate.objects}
    fields, additions, report_objects = {}, set(), set()
    addition_links = []
    targets = issues["errors"] + [item for item in issues["baseline"]
                                   if item["status"] == "fail" and item.get("coverage") == "conflict"]
    for item in targets:
        oid = item.get("object_id")
        if oid not in objects:
            continue
        field_path = item.get("field")
        if item.get("check") == "evidence":
            field_path = "evidence"
        elif item.get("coverage") == "conflict" and item.get("property"):
            field_path = "data." + item["property"]
        if field_path == "evidence":
            fields.setdefault(oid, set()).add("evidence")
        elif isinstance(field_path, str) and field_path.startswith("data."):
            field_path = ".".join(field_path.split(".")[:2])
            if field_path in {"data.id", "data.object_type"}:
                continue
            fields.setdefault(oid, set()).update({field_path, "evidence"})
            report_objects.add(oid)
        else:
            continue
        if item.get("rule_code") in {"id.dangling", "model_relation.index_field",
                                     "model_relation.missing_endpoint"}:
            # 引用补齐后，原先描述该缺口的备注与待确认项需要同步更新。
            fields[oid].update({"data.note", "data.openItem"})
        if item.get("rule_code") == "id.dangling":
            target = (item.get("locator") or {}).get("target")
            if isinstance(target, str) and target not in objects:
                additions.add(target)
                addition_links.append({"object_id": oid, "field": field_path})
        elif item.get("rule_code") == "model_relation.index_field":
            target = (item.get("locator") or {}).get("field")
            if isinstance(target, str) and target not in objects:
                additions.add(target)
                addition_links.append({"object_id": oid, "field": field_path})
        elif item.get("rule_code") == "model_relation.missing_endpoint":
            addition_links.append({"object_id": oid, "field": field_path})
    reports = []
    for category in ("omissions", "conflicts", "unknowns"):
        for entry in getattr(candidate, category):
            if any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(oid)}(?![A-Za-z0-9_])", entry)
                   for oid in report_objects):
                reports.append({"category": category, "previous": entry})
    return {"replacements": {oid: sorted(paths) for oid, paths in sorted(fields.items())},
            "additions": sorted(additions), "addition_links": addition_links,
            "report_changes": reports}


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _check_addition_links(payload, repair, scope):
    """新增 ID 可修正坏引用，但必须由本轮报错字段实际引用，不能扩展到无关对象。"""
    by_id = {obj["data"]["id"]: obj for obj in payload["objects"]}
    pending = {obj.data.id: obj for obj in repair.additions}
    reachable = set()
    for link in scope.get("addition_links", []):
        value = by_id[link["object_id"]]
        for key in link["field"].split("."):
            value = value.get(key, {}) if isinstance(value, dict) else {}
        reachable.update(_strings(value))
    # 兼容仅列出既定缺失 ID 的调用者；错误文本不再限制新 ID 的命名。
    reachable.update(scope.get("additions", []))
    while pending:
        accepted = set(pending) & reachable
        if not accepted:
            raise ValueError(f"新增对象未被本轮断链字段或必要依赖引用：{sorted(pending)}")
        for oid in accepted:
            obj = pending.pop(oid)
            data = by_id[oid]["data"]
            for name, definition in type(obj.data).model_fields.items():
                if definition.is_required() and (definition.alias or name) in REFERENCE_KEYS:
                    reachable.update(_strings(data.get(definition.alias or name)))


def _repair_error_feedback(error):
    """原始响应另存；反馈优先提供字段路径和错误类型，避免重复塞入整份坏 JSON。"""
    if error is None:
        return "没有取得结构化修复对象；请按所附 ExtractionRepair Schema 返回完整 JSON 对象"
    current, seen = error, set()
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ValidationError):
            details = [{"path": ".".join(map(str, item["loc"])),
                        "type": item["type"], "message": item["msg"]}
                       for item in current.errors(include_url=False, include_input=False)]
            return "ExtractionRepair 字段校验失败：" + json.dumps(details, ensure_ascii=False)
        if isinstance(current, json.JSONDecodeError):
            return f"ExtractionRepair JSON 解析失败：{current.msg}；行 {current.lineno}，列 {current.colno}"
        current = current.__cause__ or current.__context__
    return str(error).split("Got:", 1)[-1][:4000]


def merge_repair(candidate: ExtractionResult, repair: ExtractionRepair, material: str,
                 scope: dict | None = None) -> ExtractionResult:
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
        if scope is not None:
            allowed = set(scope["replacements"].get(oid, []))
            if not actual <= allowed:
                raise ValueError(f"对象 {oid} 超出本轮修复范围：{sorted(actual - allowed)}；允许 {sorted(allowed)}")
        if not revision.reason.strip():
            raise ValueError(f"对象 {oid} 的修复理由不能为空白")
        _require_evidence(revision.evidence, material)
        new_evidence = [ev for ev in after["evidence"] if ev not in before["evidence"]]
        if new_evidence:
            _require_evidence(new_evidence, material)
        # 未改证据仍由全量检查验收；原有格式告警不能变成整轮拒绝的硬错误。
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
    if scope is not None and repair.additions:
        _check_addition_links(payload, repair, scope)
    for revision in repair.report_changes:
        if scope is not None and {"category": revision.category, "previous": revision.previous} not in scope["report_changes"]:
            raise ValueError(f"报告变更与本轮错误无直接定位关系，不能顺带整理：{revision.category}")
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
    """返回最终候选及对应完整检查；仅检查初始候选和每份合并后的候选。"""
    started = perf_counter()
    checks, baseline = _check_candidate(candidate, material, manifest)
    execution = RepairExecution(extraction=candidate, checks=checks, baseline=baseline)
    issues = _issues(checks, baseline)
    feedback = None
    model = None
    for round_number in range(1, settings.max_check_rounds + 1):
        if not _failures(issues):
            break
        record = {"round": round_number, "issues_before": issues, "accepted": False}
        round_started = perf_counter()
        scope = _repair_scope(execution.extraction, issues)
        record["scope"] = scope
        if not scope["replacements"] and not scope["additions"]:
            record["error"] = "确定问题缺少可安全修改的对象和字段定位，保留候选供人工核对"
            record["elapsed_seconds"] = round(perf_counter() - round_started, 3)
            execution.records.append(record)
            break
        print(f"[局部修复] 第 {round_number} 轮：仅返回问题对象及必要的关联修正", flush=True)
        try:
            if model is None:
                model = ChatDeepSeek(**settings.model_params).with_structured_output(
                    ExtractionRepair, method="json_mode", include_raw=True
                )
            response = model.invoke(
                build_repair_messages(material, reference, skill_references,
                                      _payload(execution.extraction), {
                                          "errors": issues["errors"],
                                          "baseline": [item for item in issues["baseline"]
                                                       if item["status"] == "fail" and item.get("coverage") == "conflict"],
                                      }, feedback, scope)
            )
            raw = response.get("raw")
            usage = getattr(raw, "usage_metadata", None) or {}
            record["input_tokens"] = usage.get("input_tokens", 0)
            record["output_tokens"] = usage.get("output_tokens", 0)
            record["raw_response"] = raw.model_dump(mode="json") if raw else None
            if response.get("parsing_error") or response.get("parsed") is None:
                error = response.get("parsing_error")
                record["parsing_error"] = str(error)
                raise ValueError("内部修复协议解析失败：" + _repair_error_feedback(error))
            repair = response["parsed"]
            record["patch"] = repair.model_dump(mode="json", by_alias=True)
            merged = merge_repair(execution.extraction, repair, material, scope)
            merged_checks, merged_baseline = _check_candidate(merged, material, manifest)
            after = _issues(merged_checks, merged_baseline)
            record["issues_after"] = after
            lineage = _report_lineage(execution.extraction, repair)
            new_failures = _failures(after, lineage) - _failures(issues)
            resolved_errors = _issue_counts(issues["errors"]) - _issue_counts(after["errors"], lineage)
            old_warnings = _issue_counts([item for item in issues["warnings"] if item.get("blocking", True)])
            new_warnings = _issue_counts(
                [item for item in after["warnings"] if item.get("blocking", True)], lineage
            ) - (old_warnings + resolved_errors)
            new_coverage_gaps, structure_notes = _coverage_changes(execution.baseline, merged_baseline)
            record["structure_advisories"] = structure_notes
            if new_failures or new_warnings or new_coverage_gaps:
                raise ValueError(
                    "合并引入新的校验失败、告警或覆盖缺口，整轮回滚："
                    f"{sorted(map(str, set(new_failures) | set(new_warnings) | new_coverage_gaps))}"
                )
            execution.extraction = merged
            execution.checks = merged_checks
            execution.baseline = merged_baseline
            issues = after
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
