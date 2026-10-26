"""材料事实的来源核验与上下文匹配；只对可确定的矛盾签发错误。"""

import json
import re
from collections import Counter

from research_agent.schemas.baseline import MaterialFact, MaterialManifest, SourceSpan


def normalize(value) -> str:
    text = str(value) if value is not None else ""
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!>~|])", r"\1", text)
    return re.sub(r"\s+", "", text)


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
        if scope.pageKind and page.get("kind") != scope.pageKind:
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

    def candidates(self, fact):
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
                if not anchor and not self.named(data, fact.subject):
                    continue
            elif not self.scoped(obj, fact.scope):
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

        def result(coverage, detail, status="warn"):
            items.append({**row, "coverage": coverage, "detail": detail, "status": status})

        if fact.state == "unknown":
            candidates = index.candidates(fact)
            if len(candidates) == 1 and get_path(candidates[0]["data"], fact.property) is not None:
                result("review", "材料未明确，候选却填写了该属性；需核对推断依据")
            else:
                result("not_checked", "材料未明确，不产生取值断言", "skip")
            continue
        if fact.state == "conflict" or fact.verification == "review":
            result("review", "检查要求的来源或语义待复核，不用于强制修复")
            continue
        candidates = index.candidates(fact)
        if not candidates:
            result("uncovered", "未定位承接对象；可能遗漏或命名映射不同，需要核对")
            continue
        if len(candidates) != 1:
            result("review", "同名或上下文不唯一，不能任取第一项判定")
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
                result("review", "当前对象已找到检查片段，条件与顺序仍需语义复核")
            else:
                result("structured", "属性已匹配", "pass")
            continue
        expected_parts = fact.expected if isinstance(fact.expected, list) else [fact.expected]
        notes = normalize(text(data))
        in_text = all(v is not None and normalize(v) and normalize(v) in notes for v in expected_parts)
        if actual is None and in_text:
            result("text", "已在本对象文字中承接，专门属性未填写")
        elif actual is None:
            result("partial" if any(normalize(v) in notes for v in expected_parts if v is not None) else "uncovered",
                   "当前对象的承接不完整，或措辞不同需复核")
        elif isinstance(fact.expected, (bool, int)) or fact.property in {"cardinality", "defaultValue", "value", "capacity.maxLength"}:
            result("conflict", f"当前属性 {actual!r} 与有据期望 {fact.expected!r} 不一致", "fail")
        else:
            result("review", "属性表述不同，需要语义复核，不能只按关键词判错")
    counts = Counter(i["coverage"] for i in items)
    return {
        "protocol_version": 2, "passed": sum(i["status"] == "pass" for i in items),
        "warnings": sum(i["status"] == "warn" for i in items),
        "failures": sum(i["status"] == "fail" for i in items),
        "coverage": dict(counts), "source_review": source_report,
        "coverage_scope": "generated_facts_only", "business_completeness": "not_proven",
        "items": items,
    }
