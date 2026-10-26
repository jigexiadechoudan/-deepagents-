# -*- coding: utf-8 -*-
"""重新生成 schemas/typed.py（修正：挂载内容字段、Literal 原名、label 兼容）。"""
import json
import re
from pathlib import Path

base = Path("F:/sde/调研助手/code")
doc = (base.parent / "基础资料/设计模型/设计模型.md").read_text(encoding="utf-8")
TYPES = ["Project", "ExistingSystem", "ExternalDataSource", "ExternalService", "Application", "Actor",
         "dataObject", "Attribute", "Relation", "DataSet", "DataView", "DataService", "Integration",
         "Automation", "Database", "Module", "Navigation", "Feature", "Process", "ProcessStep",
         "Permission", "PageGroup", "Page", "Block", "BlockRule", "FieldView", "OptionSource",
         "Option", "Action", "Artifact", "ChangeIntent", "ChangeSet", "Deliverable", "Proposal",
         "Requirement", "ResearchStep", "Role", "Validation", "Version"]

doc_fields = {}
for m in re.finditer(r"^### (.+)$", doc, re.M):
    heading = m.group(1)
    next_h = doc.find("\n### ", m.end())
    section = doc[m.end(): next_h if next_h != -1 else len(doc)]
    jm = re.search(r"```JSON\n(.*?)```", section, re.S)
    if not jm:
        continue
    try:
        data = json.loads(jm.group(1))
    except Exception:
        continue
    if not isinstance(data, dict):
        continue
    for t in TYPES:
        if re.search(rf"\b{t}\b", heading) and t not in doc_fields:
            doc_fields[t] = sorted(set(data.keys()) - {"id"})

BIZ = 'BusinessType'
CONTROL = 'ControlType'
VIS = 'VisibilityType'

ATTACHED = {
    "note": "list[NoteItem] | None",
    "constraint": "list[ConstraintItem] | None",
    "openItem": "list[OpenItemItem] | None",
    "assumption": "list[AssumptionItem] | None",
    "quality": "list[QualityItem] | None",
}

OVERRIDES = {
    "OptionSource": {"kind": 'Literal["fixed", "reference"]'},
    "Attribute": {"bizType": f"{BIZ} | None", "capacity": "dict[str, Any] | None",
                  "suggestedControl": f"{CONTROL} | None"},
    "FieldView": {"control": f"{CONTROL} | None", "visibility": f"{VIS} | None",
                  "displayStyle": "dict[str, Any] | None",
                  "defaultValue": "str | int | float | bool | None"},
    "Option": {"value": "str | int | float | None", "semanticColor": "str | None"},
    "Block": {"chart": "dict[str, Any] | None", "content": "Any", "geometry": "Any",
              "openLogic": "list[Any] | None", "saveLogic": "list[Any] | None",
              "createLogic": "list[Any] | None", "columnCount": "int | None"},
    "Page": {"openLogic": "list[Any] | None", "serves": "list[str] | None"},
    "Action": {"params": "list[str | dict[str, Any]] | None", "icon": "str | None",
               "systemKind": "str | None"},
    "Database": {"indexing": "list[dict[str, Any]] | None", "softDelete": "Any",
                 "auditFields": "list[str] | None"},
    "Relation": {"from": "RelationEnd | None", "to": "RelationEnd | None"},
    "Application": {"theme": "dict[str, Any] | None", "label": "list[str] | None",
                    "conventions": "list[str] | None", "systems": "list[str] | None",
                    "dataSources": "list[str] | None", "services": "list[str] | None",
                    "actors": "list[str] | None"},
    "Project": {"label": "list[str] | None", "systems": "list[str] | None",
                "dataSources": "list[str] | None", "services": "list[str] | None"},
    "Module": {"label": "list[str] | None", "primaryActors": "list[str] | None",
               "order": "int | None"},
    "Navigation": {"order": "int | None"},
    "Feature": {"label": "list[str] | None", "preconditions": "list[str] | None",
                "mainFlow": "list[str] | None", "exceptionPaths": "list[str] | None",
                "acceptance": "list[str] | None", "inputs": "list[str] | None",
                "outputs": "list[str] | None", "actors": "list[str] | None",
                "businessScenarios": "list[str] | None"},
    "Automation": {"actions": "list[str] | None", "targetdataObject": "list[str] | None"},
    "DataService": {"sourcedataObject": "list[str] | None", "inputs": "list[str] | None",
                    "outputs": "list[str] | None"},
    "Requirement": {"coveredBy": "list[str] | None"},
    "DataSet": {"columns": "list[str] | None", "dimensions": "list[str] | None",
                "summaries": "list[SummaryItem] | None", "joins": "list[Any] | None"},
    "Artifact": {"status": "str | None"},
    "ExternalService": {"inputs": "list[str] | None", "outputs": "list[str] | None"},
}

REQUIRED_EXTRA = {
    "Attribute": ["dataObject", "label"],
    "FieldView": ["block", "bind", "label"],
    "Option": ["label", "value"],
    "OptionSource": ["kind"],
    "dataObject": ["label"],
    "Page": ["label"],
    "Block": ["page"],
    "Action": ["label"],
    "Relation": ["from", "to"],
    "BlockRule": ["block"],
    "Permission": ["feature"],
    "Actor": ["name"],
}


def cls_name(t):
    return {"dataObject": "DataObject"}.get(t, t)


L = []
L.append('"""按设计模型逐类型定义的强类型数据载荷。')
L.append('')
L.append('由 audit/generate_typed_schema.py 生成：每个类型的字段 = 设计模型.md 示例字段')
L.append('+ 五种挂载内容；extra=forbid 拒绝清单外键；值字段一律 Optional（配合省略')
L.append('null 规则）；身份字段（id 与各类型的核心引用）必填。改字段清单请改生成器。')
L.append('"""')
L.append('')
L.append('from typing import Annotated, Any, Literal, Union')
L.append('')
L.append('from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator')
L.append('from research_agent.schemas.vocabulary import BusinessType, ControlType, RealizationType, VisibilityType')
L.append('')
L.append('')
L.append('class NoteItem(BaseModel):')
L.append('    model_config = ConfigDict(extra="forbid")')
L.append('    statement: str')
L.append('')
for name, fields in [("ConstraintItem", ["statement", "severity", "verification", "blocking"]),
                     ("OpenItemItem", ["statement", "blocking"]),
                     ("AssumptionItem", ["statement", "agreed"]),
                     ("QualityItem", ["statement", "verification"])]:
    L.append(f"class {name}(BaseModel):")
    L.append('    model_config = ConfigDict(extra="forbid")')
    for f in fields:
        ann = "bool | None" if f in ("blocking", "agreed") else "str | None"
        L.append(f"    {f}: {ann} = None")
    L.append('')
L.append('')
L.append('class RelationEnd(BaseModel):')
L.append('    model_config = ConfigDict(extra="forbid")')
L.append('    dataObject: str')
L.append('    attribute: str | None = None')
L.append('')
L.append('class SummaryItem(BaseModel):')
L.append('    """DataSet 内嵌汇总项，字段来自设计模型.md 的 DataSet 示例。"""')
L.append('    model_config = ConfigDict(extra="forbid")')
L.append('    key: str')
for f in ('label', 'valueAttribute', 'aggregation', 'caliber'):
    L.append(f'    {f}: str | None = None')
L.append('    calculation: Any = None')
for f, ann in ATTACHED.items():
    L.append(f'    {f}: {ann} = None')
L.append('')

union_members = []
for t in TYPES:
    fields = doc_fields.get(t)
    if fields is None:
        continue
    union_members.append(t)
    ov = OVERRIDES.get(t, {})
    req = set(REQUIRED_EXTRA.get(t, []))
    all_fields = sorted(set(fields) | set(ATTACHED))
    cn = cls_name(t)
    L.append(f"class {cn}Data(BaseModel):")
    L.append(f'    """{t} 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""')
    L.append('    model_config = ConfigDict(extra="forbid")')
    L.append('')
    L.append(f'    object_type: Literal["{t}"]')
    L.append("    id: str")
    for f in all_fields:
        if f == "from":
            L.append('    from_: Annotated[RelationEnd, Field(alias="from")]')
            continue
        ann = ov.get(f) or ATTACHED.get(f) or (
            "RealizationType | None" if f == "realization" else
            "str | list[str] | None" if f == "label" else "Any"
        )
        if f in req:
            L.append(f"    {f}: {ann}")
        else:
            L.append(f"    {f}: {ann} = None")
    L.append('')

L.append('_DATA_BY_TYPE = {')
for t in union_members:
    L.append(f'    "{t}": {cls_name(t)}Data,')
L.append('}')
L.append('')
L.append('class DesignObject(BaseModel):')
L.append('    model_config = ConfigDict(extra="forbid")')
L.append('')
L.append('    object_type: Literal[' + ", ".join(f'"{t}"' for t in union_members) + '] = Field(')
L.append('        description="设计对象类型（判别标签，与 data.object_type 一致）")')
L.append("    data: Annotated[")
L.append("        " + " | ".join(f"{cls_name(m)}Data" for m in union_members) + ",")
L.append('        Field(discriminator="object_type"),')
L.append('    ] = Field(description="设计文档中定义的对象字段，按类型强校验")')
L.append('    evidence: list[str] = Field(min_length=1, description="支持这个对象的测试材料原文片段")')
L.append('')
L.append('    @field_validator("evidence")')
L.append('    @classmethod')
L.append('    def _nonblank_evidence(cls, value):')
L.append('        if any(not item.strip() for item in value):')
L.append('            raise ValueError("每条 evidence 必须是非空白原文片段")')
L.append('        return value')
L.append('')
L.append('    @model_validator(mode="after")')
L.append('    def _data_matches_object_type(self):')
L.append('        # 无判别标签的联合可能被宽松成员吞掉最小载荷，这里强制对号入座。')
L.append('        expected = _DATA_BY_TYPE[self.object_type]')
L.append('        if not self.data.id.strip():')
L.append('            raise ValueError("设计对象技术 id 不能为空白")')
L.append('        if type(self.data) is not expected:')
L.append('            raise ValueError(')
L.append('                f"data 应为 {expected.__name__}，实际 {type(self.data).__name__}"')
L.append('            )')
L.append('        return self')
L.append('')
L.append('')
L.append('class ExtractionResult(BaseModel):')
L.append('    model_config = ConfigDict(extra="forbid")')
L.append('')
L.append('    objects: list[DesignObject] = Field(description="从材料中提取的设计对象")')
L.append('    omissions: list[str] = Field(description="尚未完整提取的内容")')
L.append('    conflicts: list[str] = Field(description="材料中互相矛盾的内容")')
L.append('    unknowns: list[str] = Field(description="材料没有明确说明的信息")')
L.append('')

out = base / "research_agent/schemas/typed.py"
out.write_text("\n".join(L) + "\n", encoding="utf-8")
print("已重新生成:", out)
