"""提取结果的通用校验：与场景无关的确定性检查，先做后置报告，不拦截流程。

每类检查对应评估报告中已证实的问题类。输入解析后的提取结果与原文材料，
输出违规清单；全部为纯函数，不调用模型。
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from typing import Any, get_args

from research_agent.schemas.typed import _DATA_BY_TYPE
from research_agent.schemas.vocabulary import BusinessType, ControlType, RealizationType, VisibilityType

# 规范来源：基础资料/设计模型/设计模型.md 的对象目录（39 种）
VALID_OBJECT_TYPES = set(_DATA_BY_TYPE)

ID_PREFIXES = (
    "attr_", "entity_", "rel_", "page_", "pg_", "blk_", "fv_", "act_",
    "optsrc_", "opt_", "rule_", "svc_", "db_", "actor_", "mod_", "feat_",
    "perm_", "app_", "proj_", "ext_", "auto_", "nav_", "ds_", "xds_",
    "sys_", "int_", "dsv_", "proc_", "step_", "art_", "req_",
)

# 词表来源：字段总表的明确取值列；不再将旧 Skill 的示例子集当成全集。
VOCAB = {
    "control": set(get_args(ControlType)),
    "kind": {"reference", "fixed"},          # 仅限 OptionSource/Option
    "visibility": set(get_args(VisibilityType)),
    "realization": set(get_args(RealizationType)),
    "bizType": set(get_args(BusinessType)),
}

# 值为对象 ID 的字段名；嵌套结构（如 Relation.from/to）里的同名键同样生效
REFERENCE_KEYS = {
    "dataObject", "sourcedataObject", "targetdataObject", "bind", "block",
    "page", "pageGroup", "optionSource", "relation", "valueAttribute",
    "displayAttribute", "actor", "actors", "primaryActors", "authority",
    "feature", "primarydataObject", "menu", "database", "module", "parent",
    "application", "project", "attribute", "coveredBy", "writes", "inputs",
    "outputs", "serves", "homepage", "entry", "embeddedPage", "systems",
    "dataSources", "services", "defaultOptionSource", "system",
    "dataSet", "process", "action", "statedataObject", "reads",
}

OMISSION_SUSPECT = re.compile(r"原文没有|材料未|原文未|未给出|未说明")
OMISSION_TEXT_CLAIM = re.compile(
    r"已[^。；;]{0,60}(?:保留|承接|写入)|(?:仅|只)[^。；;]{0,60}(?:保留|承接)|"
    r"(?<!未)(?<!不)(?<!没有)(?:保存在|保留在|存于|写在)[^。；;]{0,80}(?:note|备注|说明|logic|queryNote)|"
    r"(?:note|备注|logic|queryNote)[^。；;]{0,30}(?:保留|承接)", re.I
)


def _norm(text: str) -> str:
    """归一化：去反斜杠转义与所有空白，用于证据降级判定。"""
    return re.sub(r"\s+", "", text.replace("\\", ""))


def _walk(value: Any, fn, path: tuple = ()) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = path + (key,)
            fn(key, item, child_path)
            _walk(item, fn, child_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, fn, path + (index,))


# 相似度低于该阈值时认为材料里没有可指认的原文，不附（避免误导模型）
CLOSEST_RATIO = 0.5


def find_evidence_spans(evidence: str, material: str, limit: int = 3) -> list[dict]:
    """只返回真实连续的原文窗口；相似度用于定位，不作为事实支持的证明。"""
    norm_ev = _norm(evidence)
    if not norm_ev:
        return []
    lines = material.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    widths = {1, 2, min(max(len(evidence.splitlines()), 1), 6)}
    matches = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        for width in widths:
            stop = min(index + width, len(lines))
            start, end = offsets[index], offsets[stop]
            fragment = material[start:end]
            norm_fragment = _norm(fragment)
            if not norm_fragment or not 0.4 <= len(norm_fragment) / len(norm_ev) <= 2.5:
                continue
            score = difflib.SequenceMatcher(None, norm_ev, norm_fragment).ratio()
            if score >= CLOSEST_RATIO:
                matches.append({"start": start, "end": end, "line_start": index + 1,
                                "line_end": stop, "text": fragment, "score": score})
    matches.sort(key=lambda item: (-item["score"], item["start"], item["end"]))
    selected, seen = [], set()
    for item in matches:
        location = (item["start"], item["end"])
        if location not in seen:
            seen.add(location)
            selected.append(item)
            if len(selected) == limit:
                break
    return selected


def check_evidence_verbatim(objects: list[dict], material: str) -> list[dict]:
    out: list[dict] = []
    norm_material = _norm(material)
    for obj in objects:
        evidence = obj.get("evidence", [])
        if not evidence:
            out.append({"check": "evidence", "severity": "error",
                        "object_id": obj.get("data", {}).get("id"),
                        "rule_code": "evidence.missing", "field": "evidence", "locator": {},
                        "message": "缺少支持对象的原文证据"})
        for ev in evidence:
            location = {"value": ev}
            if not isinstance(ev, str) or not ev.strip():
                out.append({"check": "evidence", "severity": "error",
                            "object_id": obj.get("data", {}).get("id"),
                            "rule_code": "evidence.blank", "field": "evidence", "locator": location,
                            "message": "证据不能为空或只有空白"})
                continue
            if ev in material:
                continue
            oid = obj.get("data", {}).get("id")
            if _norm(ev) in norm_material:
                out.append({"check": "evidence", "severity": "warning",
                            "object_id": oid,
                            "rule_code": "evidence.format", "field": "evidence", "locator": location,
                            "source_candidates": find_evidence_spans(ev, material),
                            "message": f"证据与原文存在转义/空白差异：{ev[:50]}…"})
            else:
                out.append({"check": "evidence", "severity": "error",
                            "object_id": oid,
                            "rule_code": "evidence.not_found", "field": "evidence", "locator": location,
                            "source_candidates": find_evidence_spans(ev, material),
                            "message": f"证据在原文中逐字找不到：{ev[:50]}…；连续原文及位置见 source_candidates"})
    return out


def check_object_type(objects: list[dict]) -> list[dict]:
    return [{"check": "object_type", "severity": "error",
             "object_id": obj.get("data", {}).get("id"),
             "rule_code": "object_type.invalid", "field": "object_type",
             "locator": {"value": obj.get("object_type")},
             "message": f"非法对象类型：{obj.get('object_type')}"}
            for obj in objects if obj.get("object_type") not in VALID_OBJECT_TYPES]


def check_id_integrity(objects: list[dict]) -> list[dict]:
    out: list[dict] = []
    ids = [o["data"].get("id") for o in objects if o["data"].get("id")]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        out.append({"check": "id", "severity": "error", "object_id": dup,
                    "rule_code": "id.duplicate", "field": "data.id", "locator": {},
                    "message": f"ID 重复：{dup}"})
    id_set = set(ids)
    for obj in objects:
        oid = obj["data"].get("id")
        if not isinstance(oid, str) or not oid.strip():
            out.append({"check": "id", "severity": "error", "object_id": oid,
                        "rule_code": "id.missing", "field": "data.id", "locator": {},
                        "message": "对象必须有非空技术 ID"})

        def on_kv(key: str, value: Any, path: tuple, oid: Any = oid) -> None:
            if key in REFERENCE_KEYS or (obj["object_type"] == "Action" and key == "target") \
                    or (obj["object_type"] == "Automation" and key == "actions") \
                    or (obj["object_type"] == "ProcessStep" and key == "next") \
                    or (obj["object_type"] == "DataSet" and key in {"source", "columns", "dimensions"}) \
                    or (obj["object_type"] == "DataView" and key == "columns"):
                for target in value if isinstance(value, list) else [value]:
                    if isinstance(target, str) and target not in id_set:
                        out.append({"check": "id", "severity": "error", "object_id": oid,
                                    "rule_code": "id.dangling", "field": "data." + ".".join(map(str, path)),
                                    "locator": {"target": target},
                                    "message": f"引用断链：{key} -> {target}"})

        _walk(obj["data"], on_kv)
    return out


def check_option_source_dedup(objects: list[dict]) -> list[dict]:
    seen: dict[tuple, list[str]] = {}
    for obj in objects:
        if obj.get("object_type") != "OptionSource":
            continue
        data = obj["data"]
        value_attr = data.get("valueAttribute")
        if value_attr:
            signature = tuple(json.dumps(data.get(key), ensure_ascii=False, sort_keys=True)
                              for key in ("kind", "relation", "valueAttribute", "displayAttribute", "filterNote"))
            seen.setdefault(signature, []).append(data.get("id"))
    return [{"check": "option_source", "severity": "warning", "object_id": oid,
             "rule_code": "option_source.duplicate", "field": "data.valueAttribute",
             "locator": {"objects": sorted(names, key=str)},
             "message": f"取值来源配置相同，可复核是否合并；不同场景过滤不得强制共用：{names}"}
            for names in seen.values() if len(names) > 1 for oid in names]


def check_model_relations(objects: list[dict]) -> list[dict]:
    """检查当前设计定义中的引用目标、页面归属、关系端点与包含环。"""
    by_id = {o["data"].get("id"): o for o in objects}
    out = []
    targets = {
        "application": {"Application"}, "project": {"Project"},
        "module": {"Module"}, "feature": {"Feature"}, "pageGroup": {"PageGroup"},
        "page": {"Page"}, "homepage": {"Page"}, "entry": {"Page"},
        "embeddedPage": {"Page"}, "block": {"Block"}, "bind": {"Attribute"},
        "attribute": {"Attribute"}, "valueAttribute": {"Attribute"},
        "displayAttribute": {"Attribute"}, "optionSource": {"OptionSource"},
        "defaultOptionSource": {"OptionSource"}, "relation": {"Relation"},
        "database": {"Database"}, "actor": {"Actor"}, "actors": {"Actor"},
        "primaryActors": {"Actor"}, "authority": {"Actor"}, "serves": {"Feature"},
        "dataObject": {"dataObject"}, "primarydataObject": {"dataObject"},
        "sourcedataObject": {"dataObject"}, "targetdataObject": {"dataObject"},
        "statedataObject": {"dataObject"}, "systems": {"ExistingSystem"},
        "system": {"ExistingSystem"}, "menu": {"Navigation"},
        "dataSources": {"ExternalDataSource"}, "services": {"ExternalService"},
        "dataSet": {"DataSet"}, "process": {"Process"}, "action": {"Action"},
    }

    def error(oid, message, rule, field, locator=None):
        out.append({"check": "model_relation", "severity": "error",
                    "object_id": oid, "rule_code": "model_relation." + rule,
                    "field": field, "locator": locator if locator is not None else {}, "message": message})

    for obj in objects:
        data, kind = obj["data"], obj["object_type"]
        oid = data.get("id")

        def target_type(key, value, path):
            allowed = targets.get(key)
            if key == "target" and kind == "Action":
                allowed = {"Page"}
            if key == "parent" and kind in {"Block", "Navigation"}:
                allowed = {kind}
            if key == "source" and kind == "DataSet":
                allowed = {"dataObject"}
            if key in {"columns", "dimensions"} and kind in {"DataSet", "DataView"}:
                allowed = {"Attribute"}
            if key == "actions" and kind == "Automation":
                allowed = {"Action"}
            if key == "next" and kind == "ProcessStep":
                allowed = {"ProcessStep"}
            if not allowed:
                return
            for ref in value if isinstance(value, list) else [value]:
                target = by_id.get(ref) if isinstance(ref, str) else None
                if target and target["object_type"] not in allowed:
                    error(oid, f"引用类型错误：{key} -> {ref}，应指向 {sorted(allowed)}",
                          "target_type", "data." + ".".join(map(str, path)), {"target": ref})

        _walk(data, target_type)
        if kind == "Page":
            if not data.get("pageGroup"):
                out.append({"check": "model_relation", "severity": "warning", "object_id": oid,
                            "rule_code": "page.missing_group", "field": "data.pageGroup", "locator": {},
                            "message": "Page 未承接 pageGroup 归属；若材料不足请保留具体缺口"})
            if not any(o["object_type"] == "Block" and o["data"].get("page") == oid
                       for o in objects):
                out.append({"check": "model_relation", "severity": "warning", "object_id": oid,
                            "rule_code": "page.missing_block", "field": "data.id", "locator": {},
                            "message": "Page 尚无 Block；区分材料未给细节与提取遗漏"})
        if kind == "Relation":
            for end_name in ("from", "to"):
                end = data.get(end_name) or {}
                if not end.get("dataObject"):
                    error(oid, f"Relation.{end_name} 缺少 dataObject 端点",
                          "missing_endpoint", f"data.{end_name}.dataObject")
                attr = by_id.get(end.get("attribute"), {}).get("data")
                if attr and attr.get("dataObject") != end.get("dataObject"):
                    error(oid, f"Relation.{end_name}.attribute 不属于端点 dataObject",
                          "attribute_owner", f"data.{end_name}.attribute",
                          {"attribute": end.get("attribute"), "dataObject": end.get("dataObject")})
        if kind == "Block" and isinstance(data.get("parent"), str) and data["parent"] in by_id:
            parent = by_id[data["parent"]]["data"]
            if parent.get("page") != data.get("page"):
                error(oid, "父子 Block 必须归属同一个 Page", "block_page", "data.parent",
                      {"parent": data["parent"], "page": data.get("page")})
        if kind == "Action" and data.get("block") in by_id:
            block = by_id[data["block"]]["data"]
            if data.get("page") and block.get("page") != data["page"]:
                error(oid, "Action.page 与所属 Block.page 不一致", "action_page", "data.page",
                      {"block": data["block"], "page": data["page"]})
        if kind == "Database":
            for index in data.get("indexing") or []:
                for ref in index.get("fields") or []:
                    attribute = by_id.get(ref) if isinstance(ref, str) else None
                    if not attribute or attribute["object_type"] != "Attribute":
                        error(oid, f"索引字段必须指向存在的 Attribute：{ref}",
                              "index_field", "data.indexing", {"dataObject": index.get("dataObject"), "field": ref})
                    elif attribute["data"].get("dataObject") != index.get("dataObject"):
                        error(oid, f"索引字段不属于指定 dataObject：{ref}",
                              "index_owner", "data.indexing", {"dataObject": index.get("dataObject"), "field": ref})
        if kind in {"Block", "Navigation"}:
            seen, cursor = {oid}, data.get("parent")
            while isinstance(cursor, str) and cursor in by_id:
                if cursor in seen:
                    error(oid, "parent 包含关系成环", "parent_cycle", "data.parent")
                    break
                seen.add(cursor)
                cursor = by_id[cursor]["data"].get("parent")
    return out


def check_vocabulary(objects: list[dict]) -> list[dict]:
    out: list[dict] = []

    def on_kv(key: str, value: Any, path: tuple, oid: Any = None) -> None:
        if not isinstance(value, str):
            return
        if key == "kind" and not str(oid).startswith(("optsrc_", "opt_")):
            return                      # Block/Action 等的 kind 不在本闭集内
        if key in VOCAB and value not in VOCAB[key]:
            out.append({"check": "vocab", "severity": "error", "object_id": oid,
                        "rule_code": "vocab.invalid", "field": "data." + ".".join(map(str, path)),
                        "locator": {"value": value},
                        "message": f"词表外取值：{key}={value}"})

    for obj in objects:
        _walk(obj["data"], lambda k, v, path, oid=obj["data"].get("id"): on_kv(k, v, path, oid))
    return out


def review_report_entries(extraction: dict) -> list[dict]:
    """仅分类模型的报告声明，不自动搬移条目或认定事实已经覆盖、遗漏。"""
    entries = []
    for category in ("omissions", "unknowns", "conflicts"):
        for index, entry in enumerate(extraction.get(category, [])):
            if category == "omissions":
                unknown = bool(OMISSION_SUSPECT.search(entry))
                retained = bool(OMISSION_TEXT_CLAIM.search(entry))
                classification = ("mixed_claim" if unknown and retained else
                                  "text_coverage_claim" if retained else
                                  "unknown_claim" if unknown else "omission_claim")
            else:
                classification = "unknown_claim" if category == "unknowns" else "conflict_claim"
            entries.append({"category": category, "index": index, "text": entry,
                            "classification": classification, "verified": False})
    return entries


def check_omissions_phrasing(omissions: list[str]) -> list[dict]:
    messages = {
        "mixed_claim": "条目混合文字承接和未明确的信息，需拆分核对；不直接视为事实遗漏",
        "text_coverage_claim": "条目声称已在文字中承接，需核对结构化缺口；不因未独立建对象而判漏提",
        "unknown_claim": "条目含未明确表述，需核对材料未知或模型表达缺口；不直接视为事实遗漏",
    }
    return [{"check": "omissions", "severity": "warning", "object_id": None,
             "rule_code": "omissions." + item["classification"], "field": "omissions",
             "locator": {"report": "omissions", "index": item["index"]},
             "blocking": False, "classification": item["classification"], "verified": False,
             "message": messages[item["classification"]] + "：" + item["text"][:60] + "…"}
            for item in review_report_entries({"omissions": omissions})
            if item["classification"] in messages]


def check_blockrule_condition(objects: list[dict]) -> list[dict]:
    return [{"check": "blockrule", "severity": "warning",
             "object_id": obj.get("data", {}).get("id"),
             "rule_code": "blockrule.missing_condition", "field": "data.condition", "locator": {},
             "message": "BlockRule 缺 condition 字段，条件疑似只留在 effect 文本里"}
            for obj in objects
            if obj.get("object_type") == "BlockRule"
            and not obj.get("data", {}).get("condition")]


def check_partial_open_items(objects: list[dict]) -> list[dict]:
    """部分设计或意图必须把具体缺口留在自身，不能只标状态或散落全局未知。"""
    return [{"check": "open_item", "severity": "warning",
             "object_id": obj["data"].get("id"),
             "rule_code": "open_item.missing", "field": "data.openItem", "locator": {},
             "message": "partial/intent 对象缺少包含具体问题的 openItem"}
            for obj in objects if obj["data"].get("realization") in {"partial", "intent"}
            and not any(isinstance(item, dict) and isinstance(item.get("statement"), str)
                        and item["statement"].strip()
                        for key in ("openItem", "note") for item in obj["data"].get(key) or [])]


def check_status_assertions(objects: list[dict]) -> list[dict]:
    return [{"check": "status", "severity": "warning",
             "object_id": obj["data"].get("id"),
             "rule_code": "status.unconfirmed", "field": "data.status", "locator": {},
             "message": "Artifact.status=confirmed 需要对应确认依据，不能由工具自动确认"}
            for obj in objects
            if obj.get("object_type") == "Artifact"
            and obj.get("data", {}).get("status") == "confirmed"
            and not any(re.search(r"已确认|已审核|已批准|confirmed|approved", ev, re.I)
                        for ev in obj.get("evidence", []))]


def check_primary_inference(objects: list[dict]) -> list[dict]:
    """primary=true 但证据里没有任何'主键'表述，视为推断（评估报告 #5）。"""
    out: list[dict] = []
    for obj in objects:
        if obj.get("object_type") != "Attribute":
            continue
        d = obj["data"]
        if d.get("primary") is not True:
            continue
        if any("主键" in ev for ev in obj.get("evidence", [])):
            continue
        out.append({"check": "primary", "severity": "warning",
                    "object_id": d.get("id"),
                    "rule_code": "primary.unsupported", "field": "data.primary", "locator": {},
                    "message": "primary=true 缺乏材料依据（证据中无'主键'表述），属推断"})
    return out


def check_conditional_readonly(objects: list[dict]) -> list[dict]:
    out = []
    for obj in objects:
        data = obj["data"]
        if obj["object_type"] != "FieldView" or data.get("readonly") is not True:
            continue
        notes = " ".join(str(item.get("statement", "")) for item in data.get("note") or [])
        if "新增态可填" in notes and re.search(r"编辑态.{0,10}禁用", notes):
            out.append({"check": "conditional_readonly", "severity": "error", "object_id": data.get("id"),
                        "field": "data.readonly", "rule_code": "readonly.condition_conflict", "locator": {},
                        "message": "readonly=true 与对象自身明确的新增态可填、编辑态禁用相冲突；保留条件逻辑，不能声明始终只读"})
    return out


def check_delete_policy_support(objects: list[dict]) -> list[dict]:
    return [{"check": "source_support", "severity": "warning",
             "object_id": obj["data"].get("id"), "field": "data.onDelete",
             "rule_code": "delete_policy.unsupported", "locator": {"value": obj["data"].get("onDelete")},
             "message": "关系填写了删除策略，但对象证据未提及删除；需复核，不能由只读引用或示例推出"}
            for obj in objects if obj["object_type"] == "Relation" and obj["data"].get("onDelete") is not None
            and not any(re.search(r"删除|级联|delete|cascade", ev, re.I) for ev in obj.get("evidence", []))]


def run_checks(extraction: dict, material: str) -> list[dict]:
    """总入口：返回违规清单（error / warning）。"""
    objects = extraction.get("objects", [])
    violations: list[dict] = []
    violations += check_evidence_verbatim(objects, material)
    violations += check_object_type(objects)
    violations += check_id_integrity(objects)
    violations += check_model_relations(objects)
    violations += check_option_source_dedup(objects)
    violations += check_vocabulary(objects)
    violations += check_omissions_phrasing(extraction.get("omissions", []))
    violations += check_blockrule_condition(objects)
    violations += check_partial_open_items(objects)
    violations += check_status_assertions(objects)
    violations += check_primary_inference(objects)
    violations += check_conditional_readonly(objects)
    violations += check_delete_policy_support(objects)
    return violations


if __name__ == "__main__":
    from pathlib import Path

    from research_agent.config import MATERIAL_PATH, PROJECT_DIR

    material_text = MATERIAL_PATH.read_text(encoding="utf-8")
    pattern = sys.argv[1] if len(sys.argv) > 1 else "outputs/extraction_*.json"
    for path in sorted(PROJECT_DIR.glob(pattern)):
        data = json.loads(path.read_text(encoding="utf-8"))
        items = run_checks(data, material_text)
        errors = [v for v in items if v["severity"] == "error"]
        print(f"\n== {path.name}: {len(errors)} 错误 / {len(items) - len(errors)} 警告")
        for v in items:
            print(f"  [{v['severity']}] {v['check']} | {v['object_id']} | {v['message']}")
