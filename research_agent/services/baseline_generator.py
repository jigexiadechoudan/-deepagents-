"""前置分析步：读材料产出基准清单（一次结构化调用，不走工具循环）。

清单生成与主提取互不依赖；调用方对生成失败做兜底（跳过基准核对，不阻断
提取）。生成结果先过证据自检门：带证据但逐字回链失败的条目剔除（幻觉
防守），无证据的条目保留但告警；数量合理性异常打告警。

同源偏差的边界：生成器只做"读"（枚举材料明面事实），提取做"建模"，
两者失败模式不同；清单全文进 run_record 可事后审计；人工可把审核过的
清单落盘到 baselines/ 长期复用（file 模式）。
"""

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from langchain_deepseek import ChatDeepSeek

from audit.baseline_engine import normalize
from research_agent.config import Settings
from research_agent.schemas.baseline import BaselineManifest

GENERATOR_SYSTEM = """你是需求材料的事实清单生成器，产出用于核对提取结果的基准清单。这是纯枚举任务：不做建模、不做推断、不改写用词。

规则：
1. 只抄材料明面写着的配置事实：数据表与字段（中文名/字段名/类型）、表单必填与默认值、按钮及其显示条件、选项值、查询默认值、建表索引、关联关系基数、数据服务出入参、表单生命周期动作、字段交互行为。
2. 每条事实的 evidence 必须逐字复制材料原文片段；找不到原文支撑的事实不要写。
3. 材料没写的槽位一律留空：不编造、不补齐、不推测（材料没写默认值就不要填 formDefault，没写必填就不要填 formRequired）。
4. 字段名、物理名、按钮文字照抄原文用词，一个字不改。
5. 取值类断言只抄值本身：选项 values 抄"值10"里的 10，不要把标签"手工"并写进去；默认值优先抄值（如 10、1）；材料只写了标签时，对照材料里的选项枚举找出对应值，用 | 并列两种写法（如 queryDefaults.value 写 "生效|1"）。
6. 关键词要宽：trigger/subject/verb 抄短语核心，不要抄整句；同一动作在材料里有多种措辞时用 | 并列（如 "设值为0|置为0|设值0"）。
7. 禁止输出任何形如 attr_xxx、entity_xxx 的技术 ID，清单只用材料语言。
8. 关系基数只在材料写明时填：N : 1 记 manyToOne，1 : N 记 oneToMany；材料没写基数的行（如只写"跨页，只读引用"），cardinality 填 "oneToMany|manyToOne"，不断言具体方向。
9. 页面形态 kinds 按设计模型协议取值：列表页记 list、表单页记 form、详情页记 detail。
10. 材料"关联关系"表的每一行都要在 relations 里有对应条目（含跨页只读引用），逐行必列；matchLabel 只填关系的核心关键词（如 客户、料品|内部产品、装车），可多候选 | 并列——不要照抄表格行原文，箭头和空格会让匹配失效。
11. 字段不只主表：材料在其他对象上逐字点名的字段也逐条列入 fields，并填 onObject 为该对象的材料名（中文名优先）；下拉框/引用组件写明的"显示字段"，是它所关联对象上的字段，同样列入并填 onObject=关联对象名。optionValues.referenceFields 只填主表上引用型字段的存储字段物理名（如 cust_id、material_no），显示字段不是引用字段，不要填进来。
12. 字段行为断言挂在材料写明逻辑所属的那个组件上（如失焦查重逻辑绑定在客户料号上就只挂 customer_part_no），不要拆给逻辑步骤里提及的其他字段。
"""

GENERATOR_USER = """请从以下完整材料中生成基准清单：

<material>
{material}
</material>"""


@dataclass
class BaselineGeneration:
    manifest: dict[str, Any]
    meta: dict[str, Any]


def self_check_manifest(
    manifest: BaselineManifest, material: str
) -> tuple[BaselineManifest, dict[str, Any]]:
    """证据自检门：逐条回链原文。带证据但全部回链失败的条目剔除；
    无证据的条目保留并告警；最后做数量合理性检查。"""
    norm_material = normalize(material)
    dropped: list[str] = []
    warnings: list[str] = []

    def ok(loc: str, evidence: list[str]) -> bool:
        if not evidence:
            warnings.append(f"{loc}: 无证据，保留待人工确认")
            return True
        if any(normalize(ev) in norm_material for ev in evidence):
            return True
        dropped.append(f"{loc}: 证据回链失败，已剔除（幻觉嫌疑）")
        return False

    def keep_section(section) -> bool:
        if section is None:
            return False
        if not section.evidence:
            warnings.append("整段清单无证据，保留待人工确认")
            return True
        return any(normalize(ev) in norm_material for ev in section.evidence) or (
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
    if len(clean.buttons) < 3:
        warnings.append(f"按钮仅 {len(clean.buttons)} 个，偏少，需人工确认")
    return clean, {"dropped": dropped, "warnings": warnings}


def generate_baseline_manifest(material: str, settings: Settings) -> BaselineGeneration:
    """一次结构化调用产出清单；解析失败抛异常，由调用方兜底。"""
    started = perf_counter()
    model = ChatDeepSeek(**settings.model_params)
    raw = model.with_structured_output(BaselineManifest, include_raw=True).invoke([
        ("system", GENERATOR_SYSTEM),
        ("user", GENERATOR_USER.format(material=material)),
    ])
    if raw.get("parsing_error") or raw.get("parsed") is None:
        raise RuntimeError(f"基准清单结构化解析失败：{raw.get('parsing_error')}")
    clean, report = self_check_manifest(raw["parsed"], material)
    usage = getattr(raw.get("raw"), "usage_metadata", None) or {}
    meta = {
        "source": "auto",
        "generator_elapsed_seconds": round(perf_counter() - started, 3),
        "generator_input_tokens": usage.get("input_tokens"),
        "generator_output_tokens": usage.get("output_tokens"),
        "self_check": report,
        "counts": {
            "fields": len(clean.fields),
            "buttons": len(clean.buttons),
            "option_values": len(clean.optionValues.values) if clean.optionValues else 0,
            "indexes": len(clean.indexes),
            "lifecycles": len(clean.lifecycles),
        },
    }
    return BaselineGeneration(manifest=clean.model_dump(), meta=meta)
