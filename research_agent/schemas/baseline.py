"""场景基准清单：材料事实的数据化表达；核对过程在 audit/baseline_engine.py。

清单只用材料语言（中文名、物理名、按钮文字、选项值），不出现 agent 生成的
对象 ID——清单在提取之前生成，不可能预知 ID；ID 由引擎按物理名解析。
行为断言只开数据口子（必须含哪些关键词 / 必须为空），核对逻辑全部在引擎。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    primary: bool = False
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
    cardinality: str                   # oneToMany / manyToOne / oneToMany|manyToOne
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
