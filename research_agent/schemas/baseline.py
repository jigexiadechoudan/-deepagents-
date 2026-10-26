"""通用材料事实 v2：作用域、属性、原文及未知状态；旧清单结构仅供历史兼容。

清单使用材料中的名称和物理名，不依赖后续提取生成的技术 ID。
v2 核对由 services.fact_review 执行，audit.baseline_engine 保留统一入口。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class FactScope(BaseModel):
    """材料中的上下文名称，不依赖提取 Agent 生成的 ID。"""

    model_config = ConfigDict(extra="forbid")
    object: str | None = None
    page: str | None = None
    pageKind: str | None = None
    block: str | None = None
    field: str | None = None
    targetObject: str | None = None
    targetField: str | None = None


class SourceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: int
    end: int
    line: int


class MaterialFact(BaseModel):
    """原子材料事实；未知值不产生取值断言，语义存疑的检查交给复核。"""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["object", "attribute", "field_view", "action", "option",
                  "relation", "service", "lifecycle", "rule", "constraint"]
    subject: str
    scope: FactScope = Field(default_factory=FactScope)
    property: str = "exists"
    expected: JsonValue = None
    state: Literal["explicit", "unknown", "conflict"] = "explicit"
    evidence: list[str] = Field(default_factory=list)
    # 偏移和核验状态由程序计算，模型不负责签发核验结论。
    locations: list[SourceSpan] = Field(default_factory=list)
    verification: Literal["literal", "normalized", "review"] = "review"


class MaterialManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal[2] = 2
    materialName: str | None = None
    facts: list[MaterialFact] = Field(default_factory=list)


class MainObject(BaseModel):
    """材料声明的主数据对象，按物理名定位。"""

    model_config = ConfigDict(extra="forbid")

    physicalName: str
    evidence: list[str] = Field(default_factory=list)


class Pages(BaseModel):
    """材料声明的页面形态（如 列表/表单/详情）。"""

    model_config = ConfigDict(extra="forbid")

    kinds: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class FieldFact(BaseModel):
    """一个字段的材料事实：中文名、物理名、类型、主键、表单必填与默认值。

    onObject：字段所在对象的材料名（中文名优先，物理名兜底）；缺省=主表，
    用于材料在档案等其他对象上逐字点名的字段。
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    physicalName: str
    type: str | None = None            # varchar(N) / datetime / text，其余类型不做断言
    primary: bool | None = None
    formRequired: bool | None = None   # None = 材料未说，不做断言
    formDefault: str | None = None
    onObject: str | None = None
    evidence: list[str] = Field(default_factory=list)


class ButtonFact(BaseModel):
    """一个按钮的材料事实：在场 + 显示条件关键词 + 逻辑/参数/跳转行为。"""

    model_config = ConfigDict(extra="forbid")

    label: str
    conditionMustContain: list[str] = Field(default_factory=list)
    conditionMustBeEmpty: bool = False
    paramsContain: list[str] = Field(default_factory=list)
    targetPageKind: str | None = None          # 跳转目标页的 kind（如 form）
    logicContains: list[str] = Field(default_factory=list)
    logicScope: Literal["action", "action+structured"] = "action+structured"
    name: str | None = None                    # 核对报告里的条目名，缺省自动生成
    evidence: list[str] = Field(default_factory=list)


class OptionValues(BaseModel):
    """材料逐字枚举的选项值与引用型取值来源字段。"""

    model_config = ConfigDict(extra="forbid")

    values: list[str] = Field(default_factory=list)
    referenceFields: list[str] = Field(default_factory=list)  # 物理名
    evidence: list[str] = Field(default_factory=list)


class QueryDefault(BaseModel):
    """列表页查询条件的默认值事实。"""

    model_config = ConfigDict(extra="forbid")

    physicalName: str
    value: str                         # 多候选用 | 分隔，如 生效|1
    evidence: list[str] = Field(default_factory=list)


class IndexFact(BaseModel):
    """建表约束里的索引事实；name 与 columns 至少填一个。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    columns: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class RelationFact(BaseModel):
    """关系基数期望：按 label/端点文本子串匹配提取出的关系。"""

    model_config = ConfigDict(extra="forbid")

    matchLabel: str                    # 多候选用 | 分隔
    cardinality: str | None = None
    evidence: list[str] = Field(default_factory=list)


class ServiceIO(BaseModel):
    """数据服务出入参事实，用物理名表达。"""

    model_config = ConfigDict(extra="forbid")

    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class LifecycleFact(BaseModel):
    """表单生命周期事实：结构化到 openLogic/saveLogic 记 pass，
    只出现在 note/constraint 记 warn，都找不到记 fail。"""

    model_config = ConfigDict(extra="forbid")

    trigger: str                       # 多候选用 | 分隔
    subject: str
    verb: str | None = None
    evidence: list[str] = Field(default_factory=list)


class FieldBehavior(BaseModel):
    """挂在单个字段位上的交互行为关键词（任一命中即通过）。"""

    model_config = ConfigDict(extra="forbid")

    physicalName: str
    keywords: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class BaselineManifest(BaseModel):
    """整份清单。所有段落可选：材料没有的留空，引擎跳过对应核对段。

    names：核对条目名的覆盖表（key 由引擎约定，如 fields_presence），
    生成器不用填；人工转换的历史清单可借此保持与 v3 相同的条目名。
    """

    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1, 2] = 1
    facts: list[MaterialFact] = Field(default_factory=list)
    materialName: str | None = None
    names: dict[str, str] = Field(default_factory=dict)
    mainObject: MainObject | None = None
    pages: Pages | None = None
    fields: list[FieldFact] = Field(default_factory=list)
    buttons: list[ButtonFact] = Field(default_factory=list)
    optionValues: OptionValues | None = None
    queryDefaults: list[QueryDefault] = Field(default_factory=list)
    detailReadonlyAll: bool | None = None
    indexes: list[IndexFact] = Field(default_factory=list)
    relations: list[RelationFact] = Field(default_factory=list)
    serviceIO: ServiceIO | None = None
    lifecycles: list[LifecycleFact] = Field(default_factory=list)
    fieldBehaviors: list[FieldBehavior] = Field(default_factory=list)
