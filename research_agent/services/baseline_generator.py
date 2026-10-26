"""前置读取材料生成通用事实清单，不把生成器当作事实正确性的裁判。

v2 逐条核验证据、计算位置；无法证明的要求留待复核，不进入强制修复。
单条格式错误保留原始诊断，不连带丢弃其余事实；v1 自检仅兼容历史清单。
清单生成失败会如实报告覆盖未检查，不能因为主提取成功而宣称核对完成。
"""

from dataclasses import dataclass
from copy import deepcopy
import json
from time import perf_counter
from typing import Any

from langchain_deepseek import ChatDeepSeek

from research_agent.config import Settings
from research_agent.schemas.baseline import BaselineManifest, MaterialManifest, MaterialFact
from research_agent.services.fact_review import verify_manifest

GENERATOR_SYSTEM = """你读取本轮材料，枚举用于复核的原子事实，不设计业务、不签发最终正确性结论。
输出 MaterialManifest v2。所有检查都来自当前材料，不设固定对象、字段或按钮数量。
逐章覆盖应用/角色、数据字段/索引/关系、页面/组件、查询/选项、动作、条件/时点、服务、异常与限制。
每条 fact 保留 subject、scope、property、expected、state、evidence：
1. subject 照抄该事实主体在证据中的名称或物理名；scope.object/page/block/field 按材料名称区分上下文。
   多张表、多个表单、同名按钮分别列事实，不假定存在唯一主表或唯一某种页面。
2. kind 可用 object、attribute、field_view、action、option、relation、service、lifecycle、rule、constraint。
   仅做事实分类；不要为了分类创造原文没有的对象。技术 ID 由后续提取生成，此处不猜 ID。
3. 只枚举原文明示事实；存在性 property=exists，expected 留空。
   已有属性事实可用 primary、capacity.maxLength、defaultValue、required、readonly、value、cardinality、condition、logic 等。
   SQL varchar 容量可无歧义转换为 capacity.maxLength；N:1 可转换为 manyToOne。
4. primary 未说明就不产生 primary=false。基数未说明，cardinality 的 expected=null、state=unknown；
   禁止用多个候选值冒充未知。不从存储字段推出主键，不从按钮显示推出正式授权。
5. 页面事实的 scope.page 必须写页面名；有同名控件/展示与查询时用 scope.block 区分，未知名称不编造。
   关系写 scope.object/targetObject，已知字段可加 field/targetField，保留方向。
6. 固定选项逐项列 value 与 label，保留所属字段和页面上下文；值不能与标签拼接。
   默认值原文只给标签就保留标签，值标签映射交给核对器按对应选项集检查。
7. 对事件、条件、异常、顺序，每条事实保留一个完整含义；expected 可用连续原文或完整要素列表，
   不只用一个宽泛关键词代表完整规则。区分触发主体与步骤中被读取的其他字段。
8. evidence 为逐字连续片段的数组，每一条都要能在材料找到；需要时增加相邻片段补足作用域。
   不改变标点和 Markdown 转义，不为了缩短证据丢掉否定、条件或否则分支。
9. state=explicit/unknown/conflict；冲突保留双方证据，不替用户裁定。
   locations 和 verification 由程序计算，省略或使用默认值；模型不能自称已核验。
10. 不凭与本材料无关的固定检查清单补事实，不将示例值或平台惯例写成材料要求。
顶层 JSON 形状为 {"protocol_version":2,"materialName":null,"facts":[]}。
每个 fact 的 property 与 scope 同层；scope 内只允许 object/page/pageKind/block/field/targetObject/targetField。
"""

GENERATOR_USER = """请从以下完整材料中生成基准清单：

<material>
{material}
</material>"""


@dataclass
class BaselineGeneration:
    manifest: dict[str, Any]
    meta: dict[str, Any]


def parse_manifest_response(response: dict) -> tuple[MaterialManifest, list[dict]]:
    if response.get("parsed") is not None:
        return response["parsed"], []
    raw = response.get("raw")
    calls = getattr(raw, "tool_calls", []) or []
    if len(calls) == 1:
        payload = deepcopy(calls[0].get("args"))
    else:
        content = getattr(raw, "content", "")
        payload = json.loads(content) if isinstance(content, str) and content.strip() else None
    if not isinstance(payload, dict):
        raise ValueError(f"基准清单结构化解析失败：{response.get('parsing_error')}")
    events, facts = [], []
    if not isinstance(payload.get("facts", []), list):
        raise ValueError("facts 必须是数组，不能猜测其他根结构")
    for index, fact in enumerate(payload.get("facts", [])):
        if not isinstance(fact, dict):
            events.append({"kind": "review", "path": f"facts.{index}", "fact": fact,
                           "reason": "事实不是对象，未纳入自动核对"})
            continue
        scope = fact.get("scope")
        if isinstance(scope, dict) and "property" in scope:
            value = scope["property"]
            if "property" in fact and fact["property"] != value:
                events.append({"kind": "review", "path": f"facts.{index}", "fact": fact,
                               "reason": "事实与 scope.property 冲突，不能自动选择"})
                continue
            fact["property"] = scope.pop("property")
            events.append({"kind": "normalized", "path": f"facts.{index}",
                           "reason": "scope.property 移至 fact.property；未更改业务值"})
        try:
            facts.append(MaterialFact.model_validate(fact))
        except ValueError as error:
            events.append({"kind": "review", "path": f"facts.{index}", "fact": fact,
                           "reason": str(error)})
    return MaterialManifest.model_validate({**payload, "facts": facts}), events


def self_check_manifest(
    manifest: BaselineManifest | MaterialManifest, material: str
) -> tuple[BaselineManifest | MaterialManifest, dict[str, Any]]:
    """证据自检门：每条证据逐字回链原文。带证据但任一回链失败的条目剔除；
    无证据的条目保留并告警；最后做数量合理性检查。"""
    if manifest.protocol_version == 2:
        current = MaterialManifest(materialName=manifest.materialName, facts=manifest.facts)
        return verify_manifest(current, material)
    dropped: list[str] = []
    warnings: list[str] = []

    def ok(loc: str, evidence: list[str]) -> bool:
        if not evidence:
            warnings.append(f"{loc}: 无证据，保留待人工确认")
            return True
        if all(ev.strip() and ev in material for ev in evidence):
            return True
        dropped.append(f"{loc}: 证据回链失败，已剔除（幻觉嫌疑）")
        return False

    def keep_section(section) -> bool:
        if section is None:
            return False
        if not section.evidence:
            warnings.append("整段清单无证据，保留待人工确认")
            return True
        return all(ev.strip() and ev in material for ev in section.evidence) or (
            dropped.append("整段清单证据回链失败，已剔除（幻觉嫌疑）") or False
        )

    clean = BaselineManifest(
        materialName=manifest.materialName,
        names=manifest.names,
        mainObject=manifest.mainObject if keep_section(manifest.mainObject) else None,
        pages=manifest.pages if keep_section(manifest.pages) else None,
        fields=[f for f in manifest.fields if ok(f"fields:{f.physicalName}", f.evidence)],
        buttons=[b for b in manifest.buttons if ok(f"buttons:{b.label}", b.evidence)],
        optionValues=manifest.optionValues if keep_section(manifest.optionValues) else None,
        queryDefaults=[q for q in manifest.queryDefaults
                       if ok(f"queryDefaults:{q.physicalName}", q.evidence)],
        detailReadonlyAll=manifest.detailReadonlyAll,
        indexes=[i for i in manifest.indexes
                 if ok(f"indexes:{i.name or ','.join(i.columns)}", i.evidence)],
        relations=[r for r in manifest.relations if ok(f"relations:{r.matchLabel}", r.evidence)],
        serviceIO=manifest.serviceIO if keep_section(manifest.serviceIO) else None,
        lifecycles=[lc for lc in manifest.lifecycles
                    if ok(f"lifecycles:{lc.trigger}", lc.evidence)],
        fieldBehaviors=[fb for fb in manifest.fieldBehaviors
                        if ok(f"fieldBehaviors:{fb.physicalName}", fb.evidence)],
    )

    if not clean.mainObject:
        warnings.append("缺少 mainObject：字段与服务出入参核对将跳过")
    if not clean.fields:
        warnings.append("清单未枚举任何字段，覆盖下限会很松，需人工确认")
    return clean, {"dropped": dropped, "warnings": warnings}


def generate_baseline_manifest(material: str, settings: Settings) -> BaselineGeneration:
    """一次结构化调用产出清单；解析失败抛异常，由调用方兜底。"""
    started = perf_counter()
    model = ChatDeepSeek(**settings.model_params)
    raw = model.with_structured_output(MaterialManifest, method="json_mode", include_raw=True).invoke([
        ("system", GENERATOR_SYSTEM + "\n输出必须符合此 JSON Schema：\n"
         + json.dumps(MaterialManifest.model_json_schema(), ensure_ascii=False)),
        ("user", GENERATOR_USER.format(material=material)),
    ])
    parsed, events = parse_manifest_response(raw)
    clean, report = self_check_manifest(parsed, material)
    report["unparsed_facts"] = [event for event in events if event["kind"] == "review"]
    report["warnings"].extend(f"{event['path']}: 未纳入自动核对，原事实保留在 unparsed_facts 待复核"
                              for event in report["unparsed_facts"])
    usage = getattr(raw.get("raw"), "usage_metadata", None) or {}
    meta = {
        "source": "auto",
        "response_mode": "json_mode",
        "normalizations": [event for event in events if event["kind"] == "normalized"],
        "generator_elapsed_seconds": round(perf_counter() - started, 3),
        "generator_input_tokens": usage.get("input_tokens"),
        "generator_output_tokens": usage.get("output_tokens"),
        "self_check": report,
        "counts": {"facts": len(clean.facts)},
    }
    return BaselineGeneration(manifest=clean.model_dump(), meta=meta)
