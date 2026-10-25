"""提取结果的通用校验：与场景无关的确定性检查，先做后置报告，不拦截流程。

每类检查对应评估报告中已证实的问题类。输入解析后的提取结果与原文材料，
输出违规清单；全部为纯函数，不调用模型。
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from typing import Any

# 规范来源：基础资料/设计模型/设计模型.md 的对象目录（39 种）
VALID_OBJECT_TYPES = {
    "Project", "ExistingSystem", "ExternalDataSource", "ExternalService",
    "Application", "Actor", "dataObject", "Attribute", "Relation", "DataSet",
    "DataView", "DataService", "Integration", "Automation", "Database",
    "Module", "Navigation", "Feature", "Process", "ProcessStep", "Permission",
    "PageGroup", "Page", "Block", "BlockRule", "FieldView", "OptionSource",
    "Option", "Action", "Artifact", "ChangeIntent", "ChangeSet", "Deliverable",
    "Proposal", "Requirement", "ResearchStep", "Role", "Validation", "Version",
}

ID_PREFIXES = (
    "attr_", "entity_", "rel_", "page_", "pg_", "blk_", "fv_", "act_",
    "optsrc_", "opt_", "rule_", "svc_", "db_", "actor_", "mod_", "feat_",
    "perm_", "app_", "proj_", "ext_", "auto_", "nav_", "ds_", "xds_",
    "sys_", "int_", "dsv_", "proc_", "step_", "art_", "req_",
)

# 词表来源：Skill v2.3.x 术语闭集（设计模型示例 + 采购库存 demo 实值）
VOCAB = {
    "control": {"text", "number", "amount", "date", "choice", "reference",
                "switch", "person"},
    "kind": {"reference", "fixed"},          # 仅限 OptionSource/Option
    "visibility": {"always", "conditional"},
    "realization": {"structured", "partial"},
    "bizType": {"text", "number", "integer", "amount", "date", "choice",
                "reference", "boolean", "person", "datetime"},
}

# 值为对象 ID 的字段名；嵌套结构（如 Relation.from/to）里的同名键同样生效
REFERENCE_KEYS = {
    "dataObject", "sourcedataObject", "targetdataObject", "bind", "block",
    "page", "pageGroup", "optionSource", "relation", "valueAttribute",
    "displayAttribute", "actor", "actors", "primaryActors", "authority",
    "feature", "primarydataObject", "menu", "database", "module", "parent",
    "application", "project", "attribute", "coveredBy", "writes", "inputs",
    "outputs", "serves", "homepage",
}

OMISSION_SUSPECT = re.compile(r"原文没有|材料未|原文未|未给出|未说明")


def _norm(text: str) -> str:
    """归一化：去反斜杠转义与所有空白，用于证据降级判定。"""
    return re.sub(r"\s+", "", text.replace("\\", ""))


def _walk(value: Any, fn) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            fn(key, item)
            _walk(item, fn)
    elif isinstance(value, list):
        for item in value:
            _walk(item, fn)


# 相似度低于该阈值时认为材料里没有可指认的原文，不附（避免误导模型）
CLOSEST_RATIO = 0.5


def _closest_material_text(evidence: str, candidates: list[str]) -> str:
    """材料中与证据最接近的行或相邻两行（归一化后相似度最高者），供打回消息引用。"""
    norm_ev = _norm(evidence)
    if not norm_ev:
        return ""
    best_text, best_ratio = "", 0.0
    for cand in candidates:
        norm_cand = _norm(cand)
        if not norm_cand or not 0.4 <= len(norm_cand) / len(norm_ev) <= 2.5:
            continue
        ratio = difflib.SequenceMatcher(None, norm_ev, norm_cand).ratio()
        if ratio > best_ratio:
            best_text, best_ratio = cand, ratio
    # 原样返回不做 strip：模型要逐字复制，去掉列表符号/缩进会导致再次对不上
    return best_text if best_ratio >= CLOSEST_RATIO else ""


def check_evidence_verbatim(objects: list[dict], material: str) -> list[dict]:
    out: list[dict] = []
    norm_material = _norm(material)
    lines = [ln for ln in material.splitlines() if ln.strip()]
    candidates = lines + [f"{a}\n{b}" for a, b in zip(lines, lines[1:])]
    for obj in objects:
        for ev in obj.get("evidence", []):
            if ev in material:
                continue
            oid = obj.get("data", {}).get("id")
            if _norm(ev) in norm_material:
                out.append({"check": "evidence", "severity": "warning",
                            "object_id": oid,
                            "message": f"证据与原文存在转义/空白差异：{ev[:50]}…"})
            else:
                closest = _closest_material_text(ev, candidates)
                hint = f"｜原文最接近的表述：{closest[:80]}" if closest else ""
                out.append({"check": "evidence", "severity": "error",
                            "object_id": oid,
                            "message": f"证据在原文中逐字找不到：{ev[:50]}…{hint}"})
    return out


def check_object_type(objects: list[dict]) -> list[dict]:
    return [{"check": "object_type", "severity": "error",
             "object_id": obj.get("data", {}).get("id"),
             "message": f"非法对象类型：{obj.get('object_type')}"}
            for obj in objects if obj.get("object_type") not in VALID_OBJECT_TYPES]


def check_id_integrity(objects: list[dict]) -> list[dict]:
    out: list[dict] = []
    ids = [o["data"].get("id") for o in objects if o["data"].get("id")]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        out.append({"check": "id", "severity": "error", "object_id": dup,
                    "message": f"ID 重复：{dup}"})
    id_set = set(ids)
    for obj in objects:
        oid = obj["data"].get("id")
        if oid and not str(oid).startswith(ID_PREFIXES):
            out.append({"check": "id", "severity": "error", "object_id": oid,
                        "message": f"ID 前缀不在约定表：{oid}"})

        def on_kv(key: str, value: Any, oid: Any = oid) -> None:
            if key in REFERENCE_KEYS and isinstance(value, str) and value not in id_set:
                out.append({"check": "id", "severity": "error", "object_id": oid,
                            "message": f"引用断链：{key} -> {value}"})

        _walk(obj["data"], on_kv)
    return out


def check_option_source_dedup(objects: list[dict]) -> list[dict]:
    seen: dict[str, list[str]] = {}
    for obj in objects:
        if obj.get("object_type") != "OptionSource":
            continue
        value_attr = obj["data"].get("valueAttribute")
        if value_attr:
            seen.setdefault(value_attr, []).append(obj["data"].get("id"))
    return [{"check": "option_source", "severity": "error", "object_id": None,
             "message": f"取值来源按 {va} 重复建模：{names}"}
            for va, names in seen.items() if len(names) > 1]


def check_vocabulary(objects: list[dict]) -> list[dict]:
    out: list[dict] = []

    def on_kv(key: str, value: Any, oid: Any = None) -> None:
        if not isinstance(value, str):
            return
        if key == "kind" and not str(oid).startswith(("optsrc_", "opt_")):
            return                      # Block/Action 等的 kind 不在本闭集内
        if key in VOCAB and value not in VOCAB[key]:
            out.append({"check": "vocab", "severity": "error", "object_id": oid,
                        "message": f"词表外取值：{key}={value}"})

    for obj in objects:
        _walk(obj["data"], lambda k, v, oid=obj["data"].get("id"): on_kv(k, v, oid))
    return out


def check_omissions_phrasing(omissions: list[str]) -> list[dict]:
    return [{"check": "omissions", "severity": "warning", "object_id": None,
             "message": f"疑似'材料未明确'类条目，应归入 unknowns：{x[:60]}…"}
            for x in omissions if OMISSION_SUSPECT.search(x)]


def check_blockrule_condition(objects: list[dict]) -> list[dict]:
    return [{"check": "blockrule", "severity": "warning",
             "object_id": obj.get("data", {}).get("id"),
             "message": "BlockRule 缺 condition 字段，条件疑似只留在 effect 文本里"}
            for obj in objects
            if obj.get("object_type") == "BlockRule"
            and not obj.get("data", {}).get("condition")]


def check_status_assertions(objects: list[dict]) -> list[dict]:
    return [{"check": "status", "severity": "error",
             "object_id": obj["data"].get("id"),
             "message": "Artifact.status=confirmed 无材料依据（调用方材料是待分析输入）"}
            for obj in objects
            if obj.get("object_type") == "Artifact"
            and obj.get("data", {}).get("status") == "confirmed"]


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
                    "message": "primary=true 缺乏材料依据（证据中无'主键'表述），属推断"})
    return out


def run_checks(extraction: dict, material: str) -> list[dict]:
    """总入口：返回违规清单（error / warning）。"""
    objects = extraction.get("objects", [])
    violations: list[dict] = []
    violations += check_evidence_verbatim(objects, material)
    violations += check_object_type(objects)
    violations += check_id_integrity(objects)
    violations += check_option_source_dedup(objects)
    violations += check_vocabulary(objects)
    violations += check_omissions_phrasing(extraction.get("omissions", []))
    violations += check_blockrule_condition(objects)
    violations += check_status_assertions(objects)
    violations += check_primary_inference(objects)
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
