# 提取输出契约与优化边界

状态：2026-10-26 源码与本地 Markdown 对账；本轮未运行测试、未调用模型。此目录核对不等于业务完整性验收。

## 依据与优先级

- 对象结构依据 `../基础资料/设计模型/设计模型.md`，材料事实依据本轮完整输入；参考案例不作为客户事实。
- `需求调研方案设计.md` 和 `质量检查思路（用户路线）.md` 规定保留既有成果、区分候选与确认内容，并检查细节实际落点。
- 旧附件与技能中的 Entity/属性归属等旧名称，按本轮 Markdown 的 dataObject/Attribute.dataObject 对照，不混用两版协议。
- 当前 Markdown 的颜色必填标记不完整，不能由示例值推断最终必填。已补查字段总表的明确取值与必填列；表中 Entity 等旧名称按当前 Markdown 对照。下表只核对示例顶层字段，附件约束与枚举另见下节。

## 最终输出

`ExtractionResult` 保留 `objects / omissions / conflicts / unknowns` 四个顶层数组；对象保留同层 `object_type / data / evidence`。`data.object_type` 是程序判别标签，`id` 是提取技术标识，不冒充客户业务编码。

- `Attribute` 与页面 `FieldView` 分开，通过 `bind` 连接；页面、组件、动作、关系按实际 ID 连接，不按同名猜测。
- `constraint / openItem / assumption / quality / note` 按设计文档挂在对象或内嵌配置上，不独立造对象。
- `DataSet.summaries` 是内嵌对象数组，含 key、label、valueAttribute、aggregation、caliber、calculation，不是字符串数组。
- 未明确的可选值不补齐；明确的 false、0、非必填、无此能力与已知限制必须保留。
- evidence 必须非空白且逐字命中材料；证据中出现某项事实不等于该事实已落入设计字段或规则。
- 明确漏提记 omissions；同条件下不能同时成立的材料陈述记 conflicts；原文未明确或定义无法承载记 unknowns，并保留影响。
- 本输出是提取候选封装，未冒充已确认版本、平台可执行配置或设计文档定义的正式内容包。

## 本轮字段目录

类型化模型在示例字段之外统一允许五种附加内容；过程对象的技术 id 和内部判别标签不改变业务字段。运行时生成 `contract_*.json`，若参考新增类型或字段尚未承接，则在调用模型前中止。

| 类型 | 设计正文行号 | 文档示例字段 | 静态目录对账 |
| --- | ---: | --- | --- |
| Project | 20 | `id`, `name`, `label`, `systems`, `dataSources`, `services` | 顶层字段已承接 |
| ExistingSystem | 49 | `id`, `name`, `state`, `boundary`, `address` | 顶层字段已承接 |
| ExternalDataSource | 65 | `id`, `name`, `system`, `kind`, `access`, `connectionNote` | 顶层字段已承接 |
| ExternalService | 82 | `id`, `name`, `label`, `system`, `kind`, `purpose`, `operation`, `inputs`, `outputs`, `syncMode`, `failureHandling`, `realization`, `note` | 顶层字段已承接 |
| Application | 115 | `id`, `name`, `label`, `purpose`, `domain`, `audience`, `conventions`, `systems`, `realization`, `homepage`, `theme`, `actors`, `designPreferences`, `project`, `navPlacement`, `constraint`, `assumption`, `note` | 顶层字段已承接 |
| Actor | 209 | `id`, `name`, `description` | 顶层字段已承接 |
| dataObject | 227 | `label`, `physicalName`, `module`, `description`, `dataState`, `handling`, `realization`, `businessdataObject`, `id`, `application`, `database` | 顶层字段已承接 |
| Attribute | 251 | `dataObject`, `label`, `physicalName`, `physicalNameHint`, `bizType`, `capacity`, `primary`, `description`, `defaultValue`, `codeRule`, `defaultOptionSource`, `caliber`, `unit`, `suggestedControl`, `id`, `requiredField`, `calculation` | 顶层字段已承接 |
| Relation | 281 | `id`, `label`, `kind`, `from`, `to`, `displayAttribute`, `cardinality`, `usage`, `realization`, `onDelete` | 顶层字段已承接 |
| DataSet | 308 | `id`, `name`, `source`, `columns`, `caliber`, `realization`, `joins`, `dimensions`, `filterNote`, `summaries` | 顶层字段已承接 |
| DataView | 356 | `id`, `name`, `consumers`, `sourcedataObject`, `columns`, `grain`, `freshness`, `filterNote`, `realization` | 顶层字段已承接 |
| DataService | 384 | `id`, `name`, `kind`, `sourcedataObject`, `inputs`, `outputs`, `queryNote`, `realization` | 顶层字段已承接 |
| Integration | 415 | `id`, `name`, `system`, `direction`, `trigger`, `inputs`, `outputs`, `protocol`, `failureHandling`, `idempotency`, `realization`, `dataObject`, `schedule`, `note` | 顶层字段已承接 |
| Automation | 462 | `id`, `name`, `trigger`, `condition`, `actions`, `expectedResult`, `failureHandling`, `realization`, `schedule`, `targetdataObject` | 顶层字段已承接 |
| Database | 499 | `id`, `name`, `application`, `kind`, `engine`, `charset`, `collation`, `tablePrefix`, `softDelete`, `auditFields`, `indexing`, `partitioning`, `retention`, `capacityNote`, `realization`, `quality` | 顶层字段已承接 |
| Module | 592 | `id`, `name`, `label`, `order`, `realization`, `application`, `businessModules`, `description`, `scope`, `boundary`, `primaryActors` | 顶层字段已承接 |
| Navigation | 620 | `id`, `name`, `label`, `module`, `parent`, `order`, `entry`, `realization`, `reason` | 顶层字段已承接 |
| Feature | 640 | `id`, `name`, `label`, `module`, `actors`, `trigger`, `preconditions`, `inputs`, `outputs`, `mainFlow`, `exceptionPaths`, `acceptance`, `realization`, `businessScenarios` | 顶层字段已承接 |
| Process | 681 | `id`, `name`, `label`, `module`, `trigger`, `exceptionPaths`, `realization` | 顶层字段已承接 |
| ProcessStep | 701 | `id`, `name`, `label`, `actor`, `action`, `condition`, `statedataObject`, `toState`, `inputs`, `outputs`, `next`, `process` | 顶层字段已承接 |
| Permission | 729 | `actor`, `feature`, `operations`, `scope`, `condition`, `realization`, `id`, `name`, `label` | 顶层字段已承接 |
| PageGroup | 755 | `id`, `label`, `application`, `menu`, `order`, `description`, `realization` | 顶层字段已承接 |
| Page | 773 | `id`, `label`, `pageGroup`, `kind`, `presentation`, `openLogic`, `primarydataObject`, `serves`, `realization` | 顶层字段已承接 |
| Block | 795 | `id`, `label`, `page`, `parent`, `order`, `kind`, `columnCount`, `collapsedByDefault`, `style`, `dataObject`, `relation`, `openLogic`, `saveLogic`, `createLogic`, `editable`, `deletable`, `inspectable`, `realization`, `dataSet`, `chart`, `content`, `geometry`, `embeddedPage` | 顶层字段已承接 |
| BlockRule | 845 | `id`, `label`, `block`, `kind`, `actor`, `condition`, `target`, `fields`, `operations`, `effect`, `realization` | 顶层字段已承接 |
| FieldView | 871 | `id`, `label`, `block`, `bind`, `control`, `optionSource`, `required`, `readonly`, `visibility`, `order`, `filterable`, `listed`, `displayStyle`, `widthPreset`, `defaultValue`, `realization`, `calculation` | 顶层字段已承接 |
| OptionSource | 902 | `id`, `kind`, `relation`, `valueAttribute`, `displayAttribute`, `filterNote` | 顶层字段已承接 |
| Option | 919 | `id`, `label`, `value`, `order`, `optionSource`, `semanticColor` | 顶层字段已承接 |
| Action | 936 | `page`, `scope`, `label`, `kind`, `origin`, `systemKind`, `target`, `presentation`, `refreshOnReturn`, `params`, `condition`, `preconditions`, `logic`, `outcomes`, `authority`, `icon`, `order`, `realization`, `feature`, `reads`, `writes`, `id`, `block` | 顶层字段已承接 |
| Artifact | 1057 | `kind`, `title`, `path`, `producedByStep`, `version`, `status`, `note` | 顶层字段已承接 |
| ChangeIntent | 1073 | `id`, `operation`, `target`, `sourceMode`, `scope`, `impact`, `propagation`, `externalDeps`, `status` | 顶层字段已承接 |
| ChangeSet | 1101 | `id`, `baseVersion`, `author`, `createdAt`, `changes`, `summary`, `status` | 顶层字段已承接 |
| Deliverable | 1125 | `kind`, `sourceVersion`, `includes`, `marks` | 顶层字段已承接 |
| Proposal | 1143 | `target`, `slot`, `currentValue`, `proposedValue`, `basis`, `impact`, `author`, `status` | 顶层字段已承接 |
| Requirement | 1167 | `id`, `statement`, `coveredBy`, `coverageStatus` | 顶层字段已承接 |
| ResearchStep | 1182 | `code`, `parent`, `order`, `title`, `description`, `phase`, `inputs`, `outputs`, `touches`, `isGate`, `status`, `owner`, `startedAt`, `finishedAt`, `blockedBy`, `notes` | 顶层字段已承接 |
| Role | 1229 | `id`, `label`, `permissions` | 顶层字段已承接 |
| Validation | 1244 | `changeSet`, `rule`, `locator`, `severity`, `message`, `status` | 顶层字段已承接 |
| Version | 1262 | `id`, `parent`, `changeSet`, `createdAt` | 顶层字段已承接 |

## 字段总表补查与一致性处理

来源：`../基础资料/设计模型/图片和附件/设计模型-字段总表.xlsx`，标题 v1.6（成员定义补齐）。已读取七张表的字段、类型、必填、取值/指向和说明列；原文件未修改。源文件 SHA-256：`edb2739f8388ba087245749a69870e6866326c4cdf057d32e8aa57327804c67f`。

| 明确取值所在位置 | 本轮处理 |
| --- | --- |
| 数据层 Attribute.bizType（C19/G19） | 采用 text、longText、integer、number、amount、percent、date、dateTime、boolean、choice、reference、file、image、location、signature、process、computed；历史产物的 person/datetime 仅保留兼容，不作为新的材料事实 |
| 页面层 FieldView.control（C23/G23） | 保留字段总表枚举的完整控件集合，含 longText、richText、dateTime、multiChoice 等；不再强制压成原来的八种控件 |
| 页面层 FieldView.visibility（C27/G27） | always、conditional、hidden |
| 各层 realization | structured、partial、intent；仅意图不得当作已落地，缺口保留在对象 openItem |
| 数据层 DataSet.summaries（C59/G59） | object 数组；与 Markdown 的内嵌汇总项结构一致 |
| OptionSource.kind | fixed、reference |

必填列中的 20 条“是”主要是已出现内嵌结构的成员，例如 Relation 的端点、Database 索引成员、Action 参数绑定、治理对象定位器和变更成员；不等于要求每次提取创建全部这些对象。外部档案主键等原文未明确时，不为填满必填位置而编造，应保留最小有据对象、partial/openItem 及具体表达缺口。当前运行时已检查引用存在、引用目标类型、关系属性归属和索引字段归属；并未据此宣称全部附件语义都已自动校验。

词表集中在 `schemas/vocabulary.py`，Schema、生成器和内容校验器共用。设计字段名以本轮 Markdown 为准，字段总表用于补充明确枚举与成员语义。原 Skill 的词表子集由宿主本轮提示明确覆盖，其原文保留。来源附件存在但指纹已变化时，在调用模型前要求重新对账；只使用随代码保存的附件词表快照时，运行记录明确说明未重新读取原附件。

## 局部修复协议

首次 ExtractionResult 一次提交全部对象。内部 ExtractionRepair 只提交需修正的对象、必要的有据新增及报告条目变更。宿主保存首次完整候选，按稳定 ID 合并，不删除或改名既有对象。replacement 需带完整对象、实际 changed_fields、reason 和逐字 evidence；没有声明的字段变化整轮拒绝。所有合并先形成独立候选，重跑完整 Schema、引用、证据和当前基准；引入新的 error、告警或覆盖缺口则整轮回滚。

修复不变更用户已确认的成果。重复 ID 无法安全定位时保留候选并报告，不能自动猜测应修改哪一个。

## 质量与证据边界

保留全量材料、设计正文和全部 39 类对象定义。预加载附属规则只减少读取往返，不删减业务范围。基准只提供覆盖检查，不是全部业务语义的证明。每次运行分别记录结构错误、证据、引用、覆盖失败、审核状态和实际调用耗时；自动检查通过也不代表独立评审、平台验证或客户确认。

本轮只修改实现并进行静态源码检查；性能、模型兼容性、提取完整性与实际修复效果均未通过运行验证。字段总表的颜色含义、全部成员约束的运行验证及独立业务评审不在本轮已验证范围内。
