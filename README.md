# 调研助手 MVP

## 通用广度核对（本轮优化）

当前自动生成使用材料事实清单 v2，每条事实包含主体、对象/页面/组件作用域、属性、期望值、
明确/未知/冲突状态及原文片段。程序重新计算证据位置和支持状态；模型不能自行签发通过。
历史 v1 清单继续可读，仅用于历史回放，不要求新材料符合某个客户的字段或对象数量。
自动事实清单与局部修复使用 JSON 模式；expected 保留标量、数组或对象等合法 JSON 值。
格式损坏的单条事实不连带丢弃其他条目，原始坏条目与原因保留在生成诊断中，明确未纳入自动核对。

`baseline_check.coverage` 分别统计 structured（属性已承接）、text（文字已承接）、
partial、uncovered、conflict、review 和 not_checked。文字承接属于结构化告警，未知值不强填；
自由文本的条件、顺序和逻辑蕴含仍需语义复核，不将关键词命中当作业务完整性证明。
覆盖范围明确为本轮生成的事实清单，清单本身可能遗漏，零错误不代表全部材料已完整提取。

本轮运行技能位于 `research_agent/skills/design-model-extraction/`，不再修改或依赖外部共享
技能的案例必建规则。当前设计正文与字段总表的明确枚举仍由既有契约对账检查。
只有确定的引用/结构错误和有据属性矛盾触发局部修复；告警和待复核项不迫使模型补造业务决定。
运行记录独立保存结构状态、质量状态、覆盖分项、来源待复核项及未验证的业务/平台边界。

使用 DeepAgents 从需求或设计材料中进行广度提取，使用 DeepSeek 模型，通过 `ExtractionResult` 返回完整的结构化候选。内容纠错使用独立的局部修复请求，合并后仍按完整结果检查。输出依据、39 类对象字段对照及验证边界见 [输出契约](OUTPUT_CONTRACT.md)。本轮优化未运行测试、未启动提取、未调用模型；具体性能与质量效果尚未实测。

## 运行

使用 Python 3.11 或更高版本。在项目根目录创建虚拟环境并安装依赖（已有环境可跳过前两步）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在本地 `.env` 填写自己的 `DEEPSEEK_API_KEY`。已有 `.env` 时不要覆盖。

此公开仓库不包含客户材料、设计参考、外部提取技能、人工基准清单和历史运行输出。运行前需要在本地准备 `research_agent/config.py` 中的 `MATERIAL_PATH`、`REFERENCE_PATH` 和 `Settings.skill_dir` 对应文件；换机器时需要调整。缺少 `SKILL.md` 会明确报错，不再静默降级。

准备完成后启动：

```powershell
.\.venv\Scripts\python.exe main.py
```

PyCharm 继续选择项目 `.venv` 解释器，直接运行根目录 `main.py`。程序路径根据文件位置计算，不依赖工作目录。

运行时从根目录 `.env` 加载 `DEEPSEEK_API_KEY`；可选的 `DEEPSEEK_MODEL` 默认是 `deepseek-flash`。启动主流程会调用真实模型；没有匹配的人工审核基准时，默认 `baseline_mode="auto"` 还会调用模型生成待审核清单。局部修复也会调用模型。

`Settings.baseline_mode` 可设为 `auto`（优先复用审核缓存，否则生成清单）、`file`（读取 `baseline_manifest_path` 指向的已审核清单包）或 `off`（跳过基准核对）。清单获取失败时记录原因并继续提取，最终标为覆盖未检查；跳过不能算通过。设置目前由 `Settings` 管理。

自动生成稿保存在 `outputs/baseline_cache/`，默认 `review_status=pending`，不会直接作为审核缓存复用。人工逐项对照原文核对、补齐证据后，可显式记录审核：

```powershell
.\.venv\Scripts\python.exe -m audit.review_baseline "outputs/baseline_cache/待审核清单文件.json" --reviewer "审核人"
```

此命令仅记录操作者已经完成的人工审核，不代替人工核对，不调用模型。也可导入旧的原始清单文件，但需先补齐每条事实的原文证据。命令会生成绑定当前材料、设计参考、Schema、技能及核对规则指纹的审核包；正文在审核后修改、或相关输入版本变化，复用即失效。`file` 模式只接受该类审核包，原始清单不再被静默视为已审核。自定义路径时，审核命令的 `--material / --reference / --skill-dir / --output-dir` 必须与主流程一致。

## 代码职责

| 位置 | 职责 |
| --- | --- |
| `main.py` | 程序入口，只启动总流程 |
| `research_agent/config.py` | 项目路径、环境加载、模型参数和循环限制 |
| `research_agent/workflow.py` | 读取、创建 Agent、执行、判断结果和保存的总流程 |
| `research_agent/agent/` | Agent 创建、提示词及结构化输出修复中间件 |
| `research_agent/schemas/typed.py` | 39 类设计对象的载荷、判别联合和提取结果结构 |
| `research_agent/schemas/baseline.py` | 材料事实清单结构 |
| `research_agent/schemas/repair.py` | 内部对象修复及报告条目修正协议 |
| `research_agent/services/materials.py` | UTF-8 读取测试材料和设计参考 |
| `research_agent/services/validation.py` | 判断现有结构化调用是否满足应用层重试条件 |
| `research_agent/services/execution.py` | 流式执行、递归预算现场保留、最多一次应用层重试及计时 |
| `research_agent/services/checks.py` | 证据、类型、ID、引用、词表等通用内容校验 |
| `research_agent/services/baseline_generator.py` | 前置模型调用生成事实清单，并进行证据自检 |
| `research_agent/services/baseline_store.py` | 基准审核缓存、输入指纹及失效判定 |
| `research_agent/services/contract.py` | 本轮设计参考与 Schema 的字段目录对账 |
| `research_agent/services/repair.py` | 独立局部修复、完整候选合并、全量复查与回滚 |
| `research_agent/services/artifacts.py` | 提取结果、诊断和运行记录的文件保存 |
| `audit/baseline_engine.py` | 清单驱动的确定性核对引擎，主流程会导入 |
| `audit/semantic_diff.py` | 两份提取结果的语义差异分析工具 |
| `audit/generate_typed_schema.py` | 从本地设计参考生成 `typed.py` 的开发脚本 |
| `audit/review_baseline.py` | 显式记录人工已完成的基准审核 |
| `tests/test_refactor.py` | 使用模拟 Agent 的离线回归测试 |

固定流程：读取完整材料和设计参考 → 字段目录对账 → 加载技能和预加载附属正文 → 取得基准 → 首次完整提取 → 保存首次候选 → 有限局部修复与全量复查 → 保存完整结果及记录。

`ExtractionResult` 通过 `ToolStrategy` 一次性返回全部对象。中间件保留无效 JSON 的有限重试；多套一层 `arguments` 的确定性包装可由宿主去除并重新校验，不修改业务值。无法解析时的应用层重试使用首次调用前的材料与技能，原始失败历史另存，避免反复发送巨型失败结果。

内容错误不再要求 Agent 重写全部对象。独立 `ExtractionRepair` 返回需要修正的完整对象、必要的有据新增及报告条目变更。宿主校验稳定 ID、类型、实际变更字段与原文证据，再在独立候选上合并并全量检查；引入新的错误、告警或覆盖缺口则整轮回滚。重复 ID 无法安全定位时保留候选供人工核对。JSON 修复和局部内容修复分别由 `max_structured_repair_rounds`、`max_check_rounds` 控制，默认均为 2。修复对象仍是本轮候选，不自动变更用户已确认成果。

Agent 已注册 `/skills/` 技能目录，首次调用固定加载 `design-model-extraction`。附属资料直接从本轮 VFS 快照预加载，提示模型无需再读同一份文件；局部修复同时收到完整技能规则。保留完整设计参考、业务材料和 39 类定义，不按历史出现频率裁类型。`false`、`0` 和明确的非必填继续保留，只省略无值可选键。

词表已按本地字段总表明确取值补齐，集中在 `schemas/vocabulary.py`，Schema、生成器及校验器共用。保留 `longText / dateTime / hidden / intent` 等合法值；不再将旧 Skill 的示例子集当成全集。来源表的旧成员名按本轮 Markdown 对照，表存在但版本指纹变化时，启动会要求先重新对账。表缺失时在契约记录中标为 `snapshot_only`，不声称读取了本轮附件。

## 迁移后的独立示例

原 `input_loader.py` 的读取示例：

```powershell
.\.venv\Scripts\python.exe -m research_agent.services.materials
```

原 `design_schema.py` 的结构示例：

```powershell
.\.venv\Scripts\python.exe -m research_agent.schemas.design
```

## 离线测试

按本轮要求，未运行或改写测试。现有测试仍包含旧提示词摘要、全量重提和文件基准行为的期望，且部分依赖私有材料；它们不能作为本轮优化通过的证据。历史静态审查见 [项目审查记录](PROJECT_REVIEW.md)。以下仅保留测试入口，未执行：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

测试代码使用模拟 Agent、虚拟环境变量和项目内的临时目录，并设置网络调用拦截；这描述的是现有测试设计，不代表本次已执行或通过测试。

## 输出含义

- `extraction_时间戳.json`：取得的结构化提取结果。
- `candidate_时间戳.json`：局部修复前首次完整候选，保留用于核对变更。
- `contract_时间戳.json`：本轮设计参考与类型化 Schema 的字段目录对账及证据边界。
- `run_时间戳.json`：运行参数、时间、对象计数、重试信息、技能摘要、调用记录、通用校验及基准核对信息。
- `retry_时间戳.json`：应用层重试前的首次无效工具调用记录。
- `debug_时间戳.json`：最终未取得结构化结果时的诊断，保存后抛出错误。

`completed` 仅表示取得完整结构化候选。`quality_status` 单独说明：`needs_review` 有错误或告警，`coverage_unchecked` 未执行基准核对，`baseline_review_required` 基准尚未人工审核，`automated_checks_passed` 仅当前自动检查通过。`business_completeness=not_independently_reviewed` 明确未完成独立业务评审。任何一种都不代表平台验证或客户确认。

`run_*.json` 新增每次模型调用耗时、阶段耗时、首次候选路径、内部修复内容与采纳/回滚原因。`total_completion_tokens` 为首次提取和局部修复之和；`pipeline_completion_tokens` 再计入本轮基准生成，审核缓存命中时该部分为零。达到修复上限后仍可能保存待复核候选，应结合错误、覆盖结果、审核状态及原文核对，不能只看对象数量。

## 隐私与提交范围

`.env`、客户测试材料、`outputs/`、人工基准、评估报告、含客户规则的历史核对脚本、优化过程记录、本地协作说明、IDE 配置、虚拟环境及常见私钥文件均由 `.gitignore` 排除，仓库只提供空密钥的 `.env.example`。运行输出、生成的基准和诊断可能包含完整业务原文与模型消息，应保留在本地。不要使用 `git add -f` 强行上传这些文件。

`audit/` 中公开的文件是通用引擎与开发工具；客户专用的历史核对脚本和评估报告仅在本地保留，不影响主提取流程导入通用引擎。

运行时会将材料、设计参考及所加载技能的内容发送给配置的 DeepSeek 服务，运行前应确认材料允许发送到该服务。

应用层解析失败后的重跑最多一次；客户端请求重试、ToolStrategy 自身的结构校验重试及中间件修复是不同机制。`recursion_limit=48` 是单次 Agent 图执行的步数限制。
