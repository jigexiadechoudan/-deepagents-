"""材料事实的来源核验与上下文匹配；只对可确定的矛盾签发错误。"""

import json
import re
from collections import Counter

from research_agent.schemas.baseline import MaterialFact, MaterialManifest, SourceSpan


def normalize(value) -> str:
    text = str(value) if value is not None else ""
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!>~|])", r"\1", text)
    return re.sub(r"\s+", "", text)


def canonical_page_kind(value):
    name = normalize(value).casefold()
    return {"列表": "list", "列表页": "list", "列表页面": "list",
            "表单": "form", "表单页": "form", "表单页面": "form",
            "详情": "detail", "详情页": "detail", "详情页面": "detail"}.get(name, name)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in {"evidence", "assumption", "openItem"}:
                yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def text(value):
    return "\n".join(strings(value))


def narrative_text(data):
    """覆盖只查本对象的实际描述与逻辑，不用名称、技术 ID 或待确认内容充数。"""
    fields = ("note", "constraint", "description", "purpose", "boundary", "caliber", "queryNote",
              "openLogic", "saveLogic", "createLogic", "logic", "condition", "effect", "mainFlow",
              "exceptionPaths", "preconditions", "outcomes", "filterNote", "scope", "acceptance")
    return "\n".join(text(data.get(field)) for field in fields if data.get(field) is not None)


def source_support(fact: MaterialFact, material: str) -> str:
    """保守的字面支持检查，不用证据存在冒充语义蕴含。"""
    if not fact.evidence or any(not ev.strip() or ev not in material for ev in fact.evidence):
        return "review"
    quote = normalize("\n".join(fact.evidence))
    if not normalize(fact.subject) or normalize(fact.subject) not in quote:
        return "review"
    if fact.state != "explicit":
        return "review"
    if fact.property == "exists":
        subject = re.escape(normalize(fact.subject))
        if re.search(rf"(?:无|没有|不建|不生成|不提供|无需).{{0,6}}{subject}|{subject}[:：]?(?:无|没有|不建)", quote):
            return "review"
        return "literal"
    value = fact.expected
    if value is None:
        return "review"
    if isinstance(value, bool):
        anchored = "".join(normalize(line) for ev in fact.evidence for line in ev.splitlines()
                           if normalize(fact.subject) in normalize(line))
        words = {
            "primary": (("主键", "PRIMARYKEY"), ("非主键", "不是主键", "非主键字段")),
            "required": (("必填", "必输", "不能为空"), ("非必填", "选填", "可空", "可以不填")),
            "readonly": (("只读", "禁用", "不可编辑"), ("可编辑", "允许修改")),
        }
        yes, no = words.get(fact.property, ((), ()))
        if value and any(word in anchored for word in no):
            return "review"
        if fact.property == "readonly" and re.search(r"编辑态|新增态|如果|当.+时|仅.+时", anchored):
            return "review"
        return "normalized" if any(word in anchored for word in (yes if value else no)) else "review"
    if fact.property == "cardinality":
        cardinalities = {"manyToOne": ("N:1", "n:1", "多对一"),
                         "oneToMany": ("1:N", "1:n", "一对多"),
                         "oneToOne": ("1:1", "一对一"),
                         "manyToMany": ("N:N", "n:n", "多对多")}
        return "normalized" if any(v in quote for v in cardinalities.get(str(value), ())) else "review"
    if isinstance(value, list):
        return "literal" if value and all(normalize(v) in quote for v in value) else "review"
    if fact.property == "defaultValue" and not re.search(r"默认|default", quote, re.I):
        return "review"
    if isinstance(value, int):
        return "literal" if re.search(rf"(?<!\d){value}(?!\d)", quote) else "review"
    return "literal" if normalize(value) and normalize(value) in quote else "review"


def verify_manifest(manifest: MaterialManifest, material: str):
    facts, pending = [], []
    for number, original in enumerate(manifest.facts):
        fact = original.model_copy(deep=True)
        fact.verification = source_support(fact, material)
        locations = []
        for evidence in fact.evidence:
            if not evidence.strip():
                continue
            start = material.find(evidence)
            while start >= 0:
                locations.append({"start": start, "end": start + len(evidence),
                                  "line": material.count("\n", 0, start) + 1})
                start = material.find(evidence, start + len(evidence))
        fact.locations = [SourceSpan.model_validate(span) for span in locations]
        if fact.verification == "review":
            pending.append(f"facts:{number}:{fact.subject}:{fact.property}: 来源或要求需复核")
        facts.append(fact)
    clean = manifest.model_copy(update={"facts": facts})
    if not facts:
        pending.append("未生成检查事实，本轮覆盖范围未检查")
    return clean, {"dropped": [], "warnings": pending, "review_required": len(pending)}


class CandidateIndex:
    def __init__(self, extraction):
        self.objects = extraction.get("objects", [])
        self.by_id = {o["data"].get("id"): o for o in self.objects}

    @staticmethod
    def named(data, name):
        if name is None:
            return True
        labels = [data.get("name"), data.get("physicalName"), data.get("label"), data.get("value")]
        labels = [v for item in labels for v in (item if isinstance(item, list) else [item])]
        return any(normalize(name) == normalize(label) for label in labels if label is not None)

    def page(self, data):
        if data.get("object_type") == "Page":
            return data
        if data.get("page"):
            return self.by_id.get(data["page"], {}).get("data", {})
        block = self.by_id.get(data.get("block"), {}).get("data", {})
        return self.page(block) if block else {}

    def owner(self, data):
        ref = data.get("dataObject") or data.get("primarydataObject")
        if data.get("object_type") in {"Option", "OptionSource"}:
            source = data if data.get("object_type") == "OptionSource" else self.by_id.get(data.get("optionSource"), {}).get("data", {})
            relation = self.by_id.get(source.get("relation"), {}).get("data", {})
            ref = (relation.get("from") or {}).get("dataObject")
            if not ref:
                users = [o["data"] for o in self.objects if o["object_type"] == "FieldView"
                         and o["data"].get("optionSource") == source.get("id")]
                owners = {self.owner(user).get("id") for user in users}
                if len(owners) == 1:
                    ref = next(iter(owners))
        if data.get("bind"):
            ref = self.by_id.get(data["bind"], {}).get("data", {}).get("dataObject")
        if not ref and data.get("block"):
            ref = self.by_id.get(data["block"], {}).get("data", {}).get("dataObject")
        if not ref:
            ref = self.page(data).get("primarydataObject")
        return self.by_id.get(ref, {}).get("data", {})

    def field(self, data):
        if data.get("object_type") == "Attribute":
            return data
        if data.get("bind"):
            return self.by_id.get(data["bind"], {}).get("data", {})
        source = data if data.get("object_type") == "OptionSource" else self.by_id.get(data.get("optionSource"), {}).get("data", {})
        relation = self.by_id.get(source.get("relation"), {}).get("data", {})
        ref = (relation.get("from") or {}).get("attribute")
        return self.by_id.get(ref, {}).get("data", {})

    def scoped(self, obj, scope):
        data = obj["data"]
        if obj["object_type"] in {"Option", "OptionSource"} and (scope.page or scope.pageKind or scope.block):
            source_id = data.get("id") if obj["object_type"] == "OptionSource" else data.get("optionSource")
            users = [user for user in self.objects if user["object_type"] == "FieldView"
                     and user["data"].get("optionSource") == source_id]
            return any(self.scoped(user, scope) for user in users)
        if scope.object and not self.named(self.owner(data), scope.object):
            if not (obj["object_type"] == "dataObject" and self.named(data, scope.object)):
                return False
        page = self.page(data)
        if scope.page and not self.named(page, scope.page):
            return False
        if scope.pageKind and canonical_page_kind(page.get("kind")) != canonical_page_kind(scope.pageKind):
            return False
        if scope.block:
            block = data if obj["object_type"] == "Block" else self.by_id.get(data.get("block"), {}).get("data", {})
            if not self.named(block, scope.block):
                return False
        if scope.field:
            if not self.named(self.field(data), scope.field) and not self.named(data, scope.field):
                source_id = data.get("optionSource")
                users = [o["data"] for o in self.objects if o["object_type"] == "FieldView"
                         and o["data"].get("optionSource") == source_id]
                if not source_id or not any(self.named(self.field(user), scope.field) for user in users):
                    return False
        return True

    def candidates(self, fact, match_subject=True):
        kinds = {
            "object": set(),
            "attribute": {"Attribute"}, "field_view": {"FieldView"},
            "action": {"Action"}, "option": {"Option"}, "relation": {"Relation"},
            "service": {"DataService", "ExternalService"},
            "lifecycle": {"Page", "Block", "BlockRule", "Action", "FieldView"},
            "rule": {"BlockRule"}, "constraint": set(),
        }
        out = []
        for obj in self.objects:
            data = obj["data"]
            if kinds[fact.kind] and obj["object_type"] not in kinds[fact.kind]:
                continue
            if fact.kind == "relation":
                frm = self.by_id.get((data.get("from") or {}).get("dataObject"), {}).get("data", {})
                to = self.by_id.get((data.get("to") or {}).get("dataObject"), {}).get("data", {})
                if fact.scope.object and not self.named(frm, fact.scope.object):
                    continue
                if fact.scope.targetObject and not self.named(to, fact.scope.targetObject):
                    continue
                if fact.scope.field and not self.named(self.by_id.get((data.get("from") or {}).get("attribute"), {}).get("data", {}), fact.scope.field):
                    continue
                if fact.scope.targetField and not self.named(self.by_id.get((data.get("to") or {}).get("attribute"), {}).get("data", {}), fact.scope.targetField):
                    continue
                anchor = fact.scope.object and fact.scope.targetObject
                if match_subject and not anchor and not self.named(data, fact.subject):
                    continue
            elif not self.scoped(obj, fact.scope):
                continue
            if not match_subject:
                out.append(obj)
                continue
            if fact.kind in {"lifecycle", "constraint"}:
                if normalize(fact.subject) not in normalize(text(data)):
                    continue
            elif fact.kind != "relation":
                attr = self.field(data)
                if not self.named(data, fact.subject) and not self.named(attr, fact.subject):
                    continue
            out.append(obj)
        return out

    def locate(self, fact):
        """放宽条件仅用于解释失败，不把诊断候选当作已匹配对象。"""
        matches = self.candidates(fact)
        if matches:
            return matches, {"reason_code": "matched" if len(matches) == 1 else "ambiguous_match",
                             "candidate_ids": [obj["data"].get("id") for obj in matches]}
        unscoped = fact.model_copy(update={"scope": fact.scope.model_copy(update={
            name: None for name in type(fact.scope).model_fields})})
        named = self.candidates(unscoped)
        if named:
            return [], {"reason_code": "scope_mismatch",
                        "candidate_ids": [obj["data"].get("id") for obj in named][:5]}
        scoped = self.candidates(fact, match_subject=False)
        if scoped:
            return [], {"reason_code": "name_unresolved",
                        "candidate_ids": [obj["data"].get("id") for obj in scoped][:5]}
        pool = self.candidates(unscoped, match_subject=False)
        return [], {"reason_code": "scope_mismatch" if pool else "no_candidate",
                    "candidate_ids": [obj["data"].get("id") for obj in pool][:5]}


def get_path(data, path):
    value = data
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def equivalent(actual, expected, data, index):
    if actual == expected and type(actual) is type(expected):
        return True
    if isinstance(expected, list):
        # 只查当前对象内的全部要求，不跨对象拼接；顺序/逻辑蕴含仍需复核。
        return bool(expected) and all(normalize(v) in normalize(text(actual)) for v in expected)
    if isinstance(actual, (str, int)) and not isinstance(actual, bool):
        if normalize(actual) == normalize(expected):
            return True
        source = data.get("optionSource")
        for obj in index.objects:
            option = obj["data"]
            if obj["object_type"] == "Option" and option.get("optionSource") == source and source:
                if str(actual) == str(option.get("value")) and index.named(option, expected):
                    return True
    return False


def review_facts(extraction, manifest, material):
    current = MaterialManifest(materialName=manifest.get("materialName"), facts=manifest.get("facts", []))
    checked, source_report = verify_manifest(current, material)
    index = CandidateIndex(extraction)
    items = []
    for number, fact in enumerate(checked.facts):
        row = {"check": f"fact:{number}:{fact.subject}:{fact.property}",
               "subject": fact.subject, "property": fact.property,
               "scope": fact.scope.model_dump(exclude_none=True),
               "evidence": fact.evidence,
               "locations": [s.model_dump() if hasattr(s, "model_dump") else s for s in fact.locations]}

        def result(coverage, detail, status="warn", reason_code=None, literal_covered=False):
            content = {"structured": "covered", "text": "covered", "partial": "partial",
                       "uncovered": "not_found", "conflict": "conflict", "review": "unverified",
                       "not_checked": "unknown"}[coverage]
            structure = {"structured": "structured", "text": "text_only"}.get(coverage, "unverified")
            if literal_covered:
                content, structure = "covered", "structured"
            items.append({**row, "coverage": coverage, "detail": detail, "status": status,
                          "reason_code": reason_code or coverage, "content_coverage": content,
                          "structure_coverage": structure,
                          "semantic_review": coverage == "review" or fact.kind in {"lifecycle", "constraint", "rule"}
                                             or isinstance(fact.expected, list),
                          "omission_confirmed": False})

        if fact.state == "unknown":
            candidates = index.candidates(fact)
            if len(candidates) == 1 and get_path(candidates[0]["data"], fact.property) is not None:
                result("review", "材料未明确，候选却填写了该属性；需核对推断依据",
                       reason_code="value_without_source")
            else:
                result("not_checked", "材料未明确，不产生取值断言", "skip", "material_unknown")
            continue
        if fact.state == "conflict" or fact.verification == "review":
            result("review", "检查要求的来源或语义待复核，不用于强制修复", reason_code="source_review")
            continue
        candidates, matching = index.locate(fact)
        row["matching"] = matching
        if not candidates:
            reason = matching["reason_code"]
            detail = {"scope_mismatch": "未在指定作用域定位对象；名称或同类候选出现在其他上下文，需核对作用域",
                      "name_unresolved": "作用域内有同类对象，但名称未匹配；需核对名称映射或漏提",
                      "no_candidate": "未找到同类候选；需人工核对是否漏提，不能仅凭自动匹配确认遗漏"}[reason]
            result("review", detail, reason_code=reason)
            continue
        if len(candidates) != 1:
            result("review", "同名或上下文不唯一，不能任取第一项判定", reason_code="ambiguous_match")
            continue
        data = candidates[0]["data"]
        row["object_id"] = data.get("id")
        if fact.property == "exists":
            result("structured", "已定位有据对象", "pass")
            continue
        actual = get_path(data, fact.property)
        if actual is not None and equivalent(actual, fact.expected, data, index):
            # 自由文本只确认字面承接，不能证明条件、顺序和否定都正确。
            if isinstance(fact.expected, list) or fact.kind in {"lifecycle", "constraint", "rule"}:
                result("review", "当前对象已找到检查片段，条件与顺序仍需语义复核",
                       reason_code="logic_review", literal_covered=True)
            else:
                result("structured", "属性已匹配", "pass")
            continue
        expected_parts = fact.expected if isinstance(fact.expected, list) else [fact.expected]
        notes = normalize(narrative_text(data))
        in_text = all(v is not None and normalize(v) and normalize(v) in notes for v in expected_parts)
        if actual is None and in_text:
            if isinstance(fact.expected, (bool, int, float)):
                result("review", "文字中出现相同值，但尚不能证明对应此属性", reason_code="literal_value_ambiguous")
            else:
                result("text", "已在本对象文字中承接，专门属性未填写", reason_code="text_coverage")
        elif actual is None:
            result("partial" if any(normalize(v) in notes for v in expected_parts if v is not None) else "uncovered",
                   "当前属性及文字未完整匹配要求；需核对同义表达或实际遗漏", reason_code="property_not_matched")
        elif isinstance(fact.expected, (bool, int)) or fact.property in {"cardinality", "defaultValue", "value", "capacity.maxLength"}:
            result("conflict", f"当前属性 {actual!r} 与有据期望 {fact.expected!r} 不一致", "fail")
        else:
            result("review", "属性表述不同，需要语义复核，不能只按关键词判错", reason_code="expression_review")
    counts = Counter(i["coverage"] for i in items)
    return {
        "protocol_version": 2, "passed": sum(i["status"] == "pass" for i in items),
        "warnings": sum(i["status"] == "warn" for i in items),
        "failures": sum(i["status"] == "fail" for i in items),
        "coverage": dict(counts), "source_review": source_report,
        "coverage_dimensions": {
            "content": dict(Counter(i["content_coverage"] for i in items)),
            "structure": dict(Counter(i["structure_coverage"] for i in items)),
        },
        "diagnostic_counts": dict(Counter(i["reason_code"] for i in items)),
        "omission_confirmation": "requires_independent_review",
        "coverage_scope": "generated_facts_only", "business_completeness": "not_proven",
        "items": items,
    }
