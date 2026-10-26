"""按设计模型逐类型定义的强类型数据载荷。

由 audit/generate_typed_schema.py 生成：每个类型的字段 = 设计模型.md 示例字段
+ 五种挂载内容；extra=forbid 拒绝清单外键；值字段一律 Optional（配合省略
null 规则）；身份字段（id 与各类型的核心引用）必填。改字段清单请改生成器。
"""

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_agent.schemas.vocabulary import BusinessType, ControlType, RealizationType, VisibilityType


class NoteItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str

class ConstraintItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str | None = None
    severity: str | None = None
    verification: str | None = None
    blocking: bool | None = None

class OpenItemItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str | None = None
    blocking: bool | None = None

class AssumptionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str | None = None
    agreed: bool | None = None

class QualityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str | None = None
    verification: str | None = None


class RelationEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataObject: str
    attribute: str | None = None


class SummaryItem(BaseModel):
    """DataSet 内嵌汇总项，字段来自设计模型.md 的 DataSet 示例。"""

    model_config = ConfigDict(extra="forbid")
    key: str
    label: str | None = None
    valueAttribute: str | None = None
    aggregation: str | None = None
    caliber: str | None = None
    calculation: Any = None
    constraint: list[ConstraintItem] | None = None
    openItem: list[OpenItemItem] | None = None
    assumption: list[AssumptionItem] | None = None
    quality: list[QualityItem] | None = None
    note: list[NoteItem] | None = None

class ProjectData(BaseModel):
    """Project 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Project"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    dataSources: list[str] | None = None
    label: list[str] | None = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    services: list[str] | None = None
    systems: list[str] | None = None

class ExistingSystemData(BaseModel):
    """ExistingSystem 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["ExistingSystem"]
    id: str
    address: Any = None
    assumption: list[AssumptionItem] | None = None
    boundary: Any = None
    constraint: list[ConstraintItem] | None = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    state: Any = None

class ExternalDataSourceData(BaseModel):
    """ExternalDataSource 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["ExternalDataSource"]
    id: str
    access: Any = None
    assumption: list[AssumptionItem] | None = None
    connectionNote: Any = None
    constraint: list[ConstraintItem] | None = None
    kind: Any = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    system: Any = None

class ExternalServiceData(BaseModel):
    """ExternalService 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["ExternalService"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    failureHandling: Any = None
    inputs: list[str] | None = None
    kind: Any = None
    label: str | list[str] | None = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    operation: Any = None
    outputs: list[str] | None = None
    purpose: Any = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    syncMode: Any = None
    system: Any = None

class ApplicationData(BaseModel):
    """Application 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Application"]
    id: str
    actors: list[str] | None = None
    assumption: list[AssumptionItem] | None = None
    audience: Any = None
    constraint: list[ConstraintItem] | None = None
    conventions: list[str] | None = None
    designPreferences: Any = None
    domain: Any = None
    homepage: Any = None
    label: list[str] | None = None
    name: Any = None
    navPlacement: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    project: Any = None
    purpose: Any = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    systems: list[str] | None = None
    theme: dict[str, Any] | None = None

class ActorData(BaseModel):
    """Actor 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Actor"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    description: Any = None
    name: Any
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None

class DataObjectData(BaseModel):
    """dataObject 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["dataObject"]
    id: str
    application: Any = None
    assumption: list[AssumptionItem] | None = None
    businessdataObject: Any = None
    constraint: list[ConstraintItem] | None = None
    dataState: Any = None
    database: Any = None
    description: Any = None
    handling: Any = None
    label: str | list[str] | None
    module: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    physicalName: Any = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None

class AttributeData(BaseModel):
    """Attribute 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Attribute"]
    id: str
    assumption: list[AssumptionItem] | None = None
    bizType: BusinessType | None = None
    calculation: Any = None
    caliber: Any = None
    capacity: dict[str, Any] | None = None
    codeRule: Any = None
    constraint: list[ConstraintItem] | None = None
    dataObject: Any
    defaultOptionSource: Any = None
    defaultValue: Any = None
    description: Any = None
    label: str | list[str] | None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    physicalName: Any = None
    physicalNameHint: Any = None
    primary: Any = None
    quality: list[QualityItem] | None = None
    requiredField: Any = None
    suggestedControl: ControlType | None = None
    unit: Any = None

class RelationData(BaseModel):
    """Relation 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Relation"]
    id: str
    assumption: list[AssumptionItem] | None = None
    cardinality: Any = None
    constraint: list[ConstraintItem] | None = None
    displayAttribute: Any = None
    from_: Annotated[RelationEnd, Field(alias="from")]
    kind: Any = None
    label: str | list[str] | None = None
    note: list[NoteItem] | None = None
    onDelete: Any = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    to: RelationEnd | None
    usage: Any = None

class DataSetData(BaseModel):
    """DataSet 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["DataSet"]
    id: str
    assumption: list[AssumptionItem] | None = None
    caliber: Any = None
    columns: list[str] | None = None
    constraint: list[ConstraintItem] | None = None
    dimensions: list[str] | None = None
    filterNote: Any = None
    joins: list[Any] | None = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    source: Any = None
    summaries: list[SummaryItem] | None = None

class DataViewData(BaseModel):
    """DataView 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["DataView"]
    id: str
    assumption: list[AssumptionItem] | None = None
    columns: Any = None
    constraint: list[ConstraintItem] | None = None
    consumers: Any = None
    filterNote: Any = None
    freshness: Any = None
    grain: Any = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    sourcedataObject: Any = None

class DataServiceData(BaseModel):
    """DataService 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["DataService"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    inputs: list[str] | None = None
    kind: Any = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    outputs: list[str] | None = None
    quality: list[QualityItem] | None = None
    queryNote: Any = None
    realization: RealizationType | None = None
    sourcedataObject: list[str] | None = None

class IntegrationData(BaseModel):
    """Integration 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Integration"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    dataObject: Any = None
    direction: Any = None
    failureHandling: Any = None
    idempotency: Any = None
    inputs: Any = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    outputs: Any = None
    protocol: Any = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    schedule: Any = None
    system: Any = None
    trigger: Any = None

class AutomationData(BaseModel):
    """Automation 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Automation"]
    id: str
    actions: list[str] | None = None
    assumption: list[AssumptionItem] | None = None
    condition: Any = None
    constraint: list[ConstraintItem] | None = None
    expectedResult: Any = None
    failureHandling: Any = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    schedule: Any = None
    targetdataObject: list[str] | None = None
    trigger: Any = None

class DatabaseData(BaseModel):
    """Database 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Database"]
    id: str
    application: Any = None
    assumption: list[AssumptionItem] | None = None
    auditFields: list[str] | None = None
    capacityNote: Any = None
    charset: Any = None
    collation: Any = None
    constraint: list[ConstraintItem] | None = None
    engine: Any = None
    indexing: list[dict[str, Any]] | None = None
    kind: Any = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    partitioning: Any = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    retention: Any = None
    softDelete: Any = None
    tablePrefix: Any = None

class ModuleData(BaseModel):
    """Module 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Module"]
    id: str
    application: Any = None
    assumption: list[AssumptionItem] | None = None
    boundary: Any = None
    businessModules: Any = None
    constraint: list[ConstraintItem] | None = None
    description: Any = None
    label: list[str] | None = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    order: int | None = None
    primaryActors: list[str] | None = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    scope: Any = None

class NavigationData(BaseModel):
    """Navigation 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Navigation"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    entry: Any = None
    label: str | list[str] | None = None
    module: Any = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    order: int | None = None
    parent: Any = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    reason: Any = None

class FeatureData(BaseModel):
    """Feature 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Feature"]
    id: str
    acceptance: list[str] | None = None
    actors: list[str] | None = None
    assumption: list[AssumptionItem] | None = None
    businessScenarios: list[str] | None = None
    constraint: list[ConstraintItem] | None = None
    exceptionPaths: list[str] | None = None
    inputs: list[str] | None = None
    label: list[str] | None = None
    mainFlow: list[str] | None = None
    module: Any = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    outputs: list[str] | None = None
    preconditions: list[str] | None = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    trigger: Any = None

class ProcessData(BaseModel):
    """Process 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Process"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    exceptionPaths: Any = None
    label: str | list[str] | None = None
    module: Any = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    trigger: Any = None

class ProcessStepData(BaseModel):
    """ProcessStep 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["ProcessStep"]
    id: str
    action: Any = None
    actor: Any = None
    assumption: list[AssumptionItem] | None = None
    condition: Any = None
    constraint: list[ConstraintItem] | None = None
    inputs: Any = None
    label: str | list[str] | None = None
    name: Any = None
    next: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    outputs: Any = None
    process: Any = None
    quality: list[QualityItem] | None = None
    statedataObject: Any = None
    toState: Any = None

class PermissionData(BaseModel):
    """Permission 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Permission"]
    id: str
    actor: Any = None
    assumption: list[AssumptionItem] | None = None
    condition: Any = None
    constraint: list[ConstraintItem] | None = None
    feature: Any
    label: str | list[str] | None = None
    name: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    operations: Any = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    scope: Any = None

class PageGroupData(BaseModel):
    """PageGroup 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["PageGroup"]
    id: str
    application: Any = None
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    description: Any = None
    label: str | list[str] | None = None
    menu: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    order: Any = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None

class PageData(BaseModel):
    """Page 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Page"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    kind: Any = None
    label: str | list[str] | None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    openLogic: list[Any] | None = None
    pageGroup: Any = None
    presentation: Any = None
    primarydataObject: Any = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    serves: list[str] | None = None

class BlockData(BaseModel):
    """Block 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Block"]
    id: str
    assumption: list[AssumptionItem] | None = None
    chart: dict[str, Any] | None = None
    collapsedByDefault: Any = None
    columnCount: int | None = None
    constraint: list[ConstraintItem] | None = None
    content: Any = None
    createLogic: list[Any] | None = None
    dataObject: Any = None
    dataSet: Any = None
    deletable: Any = None
    editable: Any = None
    embeddedPage: Any = None
    geometry: Any = None
    inspectable: Any = None
    kind: Any = None
    label: str | list[str] | None = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    openLogic: list[Any] | None = None
    order: Any = None
    page: Any
    parent: Any = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    relation: Any = None
    saveLogic: list[Any] | None = None
    style: Any = None

class BlockRuleData(BaseModel):
    """BlockRule 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["BlockRule"]
    id: str
    actor: Any = None
    assumption: list[AssumptionItem] | None = None
    block: Any
    condition: Any = None
    constraint: list[ConstraintItem] | None = None
    effect: Any = None
    fields: Any = None
    kind: Any = None
    label: str | list[str] | None = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    operations: Any = None
    quality: list[QualityItem] | None = None
    realization: RealizationType | None = None
    target: Any = None

class FieldViewData(BaseModel):
    """FieldView 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["FieldView"]
    id: str
    assumption: list[AssumptionItem] | None = None
    bind: Any
    block: Any
    calculation: Any = None
    constraint: list[ConstraintItem] | None = None
    control: ControlType | None = None
    defaultValue: str | int | float | bool | None = None
    displayStyle: dict[str, Any] | None = None
    filterable: Any = None
    label: str | list[str] | None
    listed: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    optionSource: Any = None
    order: Any = None
    quality: list[QualityItem] | None = None
    readonly: Any = None
    realization: RealizationType | None = None
    required: Any = None
    visibility: VisibilityType | None = None
    widthPreset: Any = None

class OptionSourceData(BaseModel):
    """OptionSource 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["OptionSource"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    displayAttribute: Any = None
    filterNote: Any = None
    kind: Literal["fixed", "reference"]
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    relation: Any = None
    valueAttribute: Any = None

class OptionData(BaseModel):
    """Option 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Option"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    label: str | list[str] | None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    optionSource: Any = None
    order: Any = None
    quality: list[QualityItem] | None = None
    semanticColor: str | None = None
    value: str | int | float | None

class ActionData(BaseModel):
    """Action 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Action"]
    id: str
    assumption: list[AssumptionItem] | None = None
    authority: Any = None
    block: Any = None
    condition: Any = None
    constraint: list[ConstraintItem] | None = None
    feature: Any = None
    icon: str | None = None
    kind: Any = None
    label: str | list[str] | None
    logic: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    order: Any = None
    origin: Any = None
    outcomes: Any = None
    page: Any = None
    params: list[str | dict[str, Any]] | None = None
    preconditions: Any = None
    presentation: Any = None
    quality: list[QualityItem] | None = None
    reads: Any = None
    realization: RealizationType | None = None
    refreshOnReturn: Any = None
    scope: Any = None
    systemKind: str | None = None
    target: Any = None
    writes: Any = None

class ArtifactData(BaseModel):
    """Artifact 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Artifact"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    kind: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    path: Any = None
    producedByStep: Any = None
    quality: list[QualityItem] | None = None
    status: str | None = None
    title: Any = None
    version: Any = None

class ChangeIntentData(BaseModel):
    """ChangeIntent 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["ChangeIntent"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    externalDeps: Any = None
    impact: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    operation: Any = None
    propagation: Any = None
    quality: list[QualityItem] | None = None
    scope: Any = None
    sourceMode: Any = None
    status: Any = None
    target: Any = None

class ChangeSetData(BaseModel):
    """ChangeSet 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["ChangeSet"]
    id: str
    assumption: list[AssumptionItem] | None = None
    author: Any = None
    baseVersion: Any = None
    changes: Any = None
    constraint: list[ConstraintItem] | None = None
    createdAt: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    status: Any = None
    summary: Any = None

class DeliverableData(BaseModel):
    """Deliverable 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Deliverable"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    includes: Any = None
    kind: Any = None
    marks: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    sourceVersion: Any = None

class ProposalData(BaseModel):
    """Proposal 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Proposal"]
    id: str
    assumption: list[AssumptionItem] | None = None
    author: Any = None
    basis: Any = None
    constraint: list[ConstraintItem] | None = None
    currentValue: Any = None
    impact: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    proposedValue: Any = None
    quality: list[QualityItem] | None = None
    slot: Any = None
    status: Any = None
    target: Any = None

class RequirementData(BaseModel):
    """Requirement 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Requirement"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    coverageStatus: Any = None
    coveredBy: list[str] | None = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    statement: Any = None

class ResearchStepData(BaseModel):
    """ResearchStep 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["ResearchStep"]
    id: str
    assumption: list[AssumptionItem] | None = None
    blockedBy: Any = None
    code: Any = None
    constraint: list[ConstraintItem] | None = None
    description: Any = None
    finishedAt: Any = None
    inputs: Any = None
    isGate: Any = None
    note: list[NoteItem] | None = None
    notes: Any = None
    openItem: list[OpenItemItem] | None = None
    order: Any = None
    outputs: Any = None
    owner: Any = None
    parent: Any = None
    phase: Any = None
    quality: list[QualityItem] | None = None
    startedAt: Any = None
    status: Any = None
    title: Any = None
    touches: Any = None

class RoleData(BaseModel):
    """Role 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Role"]
    id: str
    assumption: list[AssumptionItem] | None = None
    constraint: list[ConstraintItem] | None = None
    label: str | list[str] | None = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    permissions: Any = None
    quality: list[QualityItem] | None = None

class ValidationData(BaseModel):
    """Validation 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Validation"]
    id: str
    assumption: list[AssumptionItem] | None = None
    changeSet: Any = None
    constraint: list[ConstraintItem] | None = None
    locator: Any = None
    message: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    quality: list[QualityItem] | None = None
    rule: Any = None
    severity: Any = None
    status: Any = None

class VersionData(BaseModel):
    """Version 数据载荷。无值的键一律省略（不写 null）：只需 object_type、id 与有值的字段。"""
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Version"]
    id: str
    assumption: list[AssumptionItem] | None = None
    changeSet: Any = None
    constraint: list[ConstraintItem] | None = None
    createdAt: Any = None
    note: list[NoteItem] | None = None
    openItem: list[OpenItemItem] | None = None
    parent: Any = None
    quality: list[QualityItem] | None = None

_DATA_BY_TYPE = {
    "Project": ProjectData,
    "ExistingSystem": ExistingSystemData,
    "ExternalDataSource": ExternalDataSourceData,
    "ExternalService": ExternalServiceData,
    "Application": ApplicationData,
    "Actor": ActorData,
    "dataObject": DataObjectData,
    "Attribute": AttributeData,
    "Relation": RelationData,
    "DataSet": DataSetData,
    "DataView": DataViewData,
    "DataService": DataServiceData,
    "Integration": IntegrationData,
    "Automation": AutomationData,
    "Database": DatabaseData,
    "Module": ModuleData,
    "Navigation": NavigationData,
    "Feature": FeatureData,
    "Process": ProcessData,
    "ProcessStep": ProcessStepData,
    "Permission": PermissionData,
    "PageGroup": PageGroupData,
    "Page": PageData,
    "Block": BlockData,
    "BlockRule": BlockRuleData,
    "FieldView": FieldViewData,
    "OptionSource": OptionSourceData,
    "Option": OptionData,
    "Action": ActionData,
    "Artifact": ArtifactData,
    "ChangeIntent": ChangeIntentData,
    "ChangeSet": ChangeSetData,
    "Deliverable": DeliverableData,
    "Proposal": ProposalData,
    "Requirement": RequirementData,
    "ResearchStep": ResearchStepData,
    "Role": RoleData,
    "Validation": ValidationData,
    "Version": VersionData,
}

class DesignObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: Literal["Project", "ExistingSystem", "ExternalDataSource", "ExternalService", "Application", "Actor", "dataObject", "Attribute", "Relation", "DataSet", "DataView", "DataService", "Integration", "Automation", "Database", "Module", "Navigation", "Feature", "Process", "ProcessStep", "Permission", "PageGroup", "Page", "Block", "BlockRule", "FieldView", "OptionSource", "Option", "Action", "Artifact", "ChangeIntent", "ChangeSet", "Deliverable", "Proposal", "Requirement", "ResearchStep", "Role", "Validation", "Version"] = Field(
        description="设计对象类型（判别标签，与 data.object_type 一致）")
    data: Annotated[
        ProjectData | ExistingSystemData | ExternalDataSourceData | ExternalServiceData | ApplicationData | ActorData | DataObjectData | AttributeData | RelationData | DataSetData | DataViewData | DataServiceData | IntegrationData | AutomationData | DatabaseData | ModuleData | NavigationData | FeatureData | ProcessData | ProcessStepData | PermissionData | PageGroupData | PageData | BlockData | BlockRuleData | FieldViewData | OptionSourceData | OptionData | ActionData | ArtifactData | ChangeIntentData | ChangeSetData | DeliverableData | ProposalData | RequirementData | ResearchStepData | RoleData | ValidationData | VersionData,
        Field(discriminator="object_type"),
    ] = Field(description="设计文档中定义的对象字段，按类型强校验")
    evidence: list[str] = Field(min_length=1, description="支持这个对象的测试材料原文片段")

    @field_validator("evidence")
    @classmethod
    def _nonblank_evidence(cls, value):
        if any(not item.strip() for item in value):
            raise ValueError("每条 evidence 必须是非空白原文片段")
        return value

    @model_validator(mode="after")
    def _data_matches_object_type(self):
        # 无判别标签的联合可能被宽松成员吞掉最小载荷，这里强制对号入座。
        expected = _DATA_BY_TYPE[self.object_type]
        if not self.data.id.strip():
            raise ValueError("设计对象技术 id 不能为空白")
        if type(self.data) is not expected:
            raise ValueError(
                f"data 应为 {expected.__name__}，实际 {type(self.data).__name__}"
            )
        return self


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objects: list[DesignObject] = Field(description="从材料中提取的设计对象")
    omissions: list[str] = Field(description="尚未完整提取的内容")
    conflicts: list[str] = Field(description="材料中互相矛盾的内容")
    unknowns: list[str] = Field(description="材料没有明确说明的信息")

