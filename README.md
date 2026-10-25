# 调研助手 MVP

使用 DeepAgents 从需求或设计材料中进行广度提取，使用 DeepSeek 模型，通过 `ExtractionResult` 返回结构化设计模型。当前代码包含逐类型 Pydantic Schema、循环内修复、通用内容校验和清单驱动的基准核对。

## 运行

使用 Python 3.11 或更高版本。在项目根目录创建虚拟环境并安装依赖（已有环境可跳过前两步）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在本地 `.env` 填写自己的 `DEEPSEEK_API_KEY`。已有 `.env` 时不要覆盖。

此公开仓库不包含客户材料、设计参考、外部提取技能、人工基准清单和历史运行输出。运行前需要在本地准备 `research_agent/config.py` 中的 `MATERIAL_PATH`、`REFERENCE_PATH` 和 `Settings.skill_dir` 对应文件；这些路径仍采用原开发环境的配置，换机器时需要调整。缺少技能目录时当前代码会返回空技能文件集合，不会主动报错。

准备完成后启动：

```powershell
.\.venv\Scripts\python.exe main.py
```

PyCharm 继续选择项目 `.venv` 解释器，直接运行根目录 `main.py`。程序路径根据文件位置计算，不依赖工作目录。

运行时从根目录 `.env` 加载 `DEEPSEEK_API_KEY`；可选的 `DEEPSEEK_MODEL` 默认是 `deepseek-flash`。启动主流程会调用真实模型，默认 `baseline_mode="auto"` 还会在主提取之前调用模型生成基准清单，可能产生费用。

`Settings.baseline_mode` 可设为 `auto`（自动生成清单）、`file`（读取 `baseline_manifest_path` 指向的本地清单）或 `off`（跳过基准核对）。清单获取失败时会记录并跳过本轮基准核对，继续主提取。上述设置目前由代码中的 `Settings` 管理，尚未提供对应命令行参数或环境变量。

## 代码职责

| 位置 | 职责 |
| --- | --- |
| `main.py` | 程序入口，只启动总流程 |
| `research_agent/config.py` | 项目路径、环境加载、模型参数和循环限制 |
| `research_agent/workflow.py` | 读取、创建 Agent、执行、判断结果和保存的总流程 |
| `research_agent/agent/` | Agent 创建、提示词及结构化输出修复中间件 |
| `research_agent/schemas/typed.py` | 39 类设计对象的载荷、判别联合和提取结果结构 |
| `research_agent/schemas/baseline.py` | 材料事实清单结构 |
| `research_agent/services/materials.py` | UTF-8 读取测试材料和设计参考 |
| `research_agent/services/validation.py` | 判断现有结构化调用是否满足应用层重试条件 |
| `research_agent/services/execution.py` | 流式执行、递归预算现场保留、最多一次应用层重试及计时 |
| `research_agent/services/checks.py` | 证据、类型、ID、引用、词表等通用内容校验 |
| `research_agent/services/baseline_generator.py` | 前置模型调用生成事实清单，并进行证据自检 |
| `research_agent/services/artifacts.py` | 提取结果、诊断和运行记录的文件保存 |
| `audit/baseline_engine.py` | 清单驱动的确定性核对引擎，主流程会导入 |
| `audit/semantic_diff.py` | 两份提取结果的语义差异分析工具 |
| `audit/generate_typed_schema.py` | 从本地设计参考生成 `typed.py` 的开发脚本 |
| `tests/test_refactor.py` | 使用模拟 Agent 的离线回归测试 |

固定流程：加载配置 → 读取材料和参考 → 创建 Agent、加载技能 → 获取基准清单 → 流式提取与有限修复 → 通用校验和基准核对 → 保存与打印。

当前没有注册自定义业务工具。材料读取、初始化、清单生成和最终保存由程序执行；`ExtractionResult` 通过 `ToolStrategy` 作为结构化输出入口。修复中间件会将无效 JSON 调用和部分内容错误反馈给模型，修复次数分别由 `max_structured_repair_rounds` 和 `max_check_rounds` 控制，默认均为 2。

Agent 已注册 `/skills/` 技能目录，程序将本地 `Settings.skill_dir` 中的 Markdown 文件加载到 Agent 虚拟文件系统，并在首次调用中固定加载 `design-model-extraction` 技能。

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

测试代码已适配当前技能加载与流式调用接口，但部分测试仍直接读取私有材料、设计参考和人工基准清单，因此仅克隆公开仓库不能直接运行完整测试套件。详见 [项目审查记录](PROJECT_REVIEW.md)。本次上传只进行静态审查和提交内容的隐私扫描，未运行测试，也未调用模型。

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

测试代码使用模拟 Agent、虚拟环境变量和项目内的临时目录，并设置网络调用拦截；这描述的是现有测试设计，不代表本次已执行或通过测试。

## 输出含义

- `extraction_时间戳.json`：取得的结构化提取结果。
- `run_时间戳.json`：运行参数、时间、对象计数、重试信息、技能摘要、调用记录、通用校验及基准核对信息。
- `retry_时间戳.json`：应用层重试前的首次无效工具调用记录。
- `debug_时间戳.json`：最终未取得结构化结果时的诊断，保存后抛出错误。

`completed` 仅表示取得结构化结果，不代表业务提取质量通过。当前 Schema 会限制对象类型、字段键和部分值类型，通用校验器会检查 ID、引用、词表和证据，但仍有已记录的校验缺口。达到内容修复上限后可能保存带有错误的结果，应结合 `checks.error_count`、`baseline_check.failures` 和基准阶段信息人工复核。

## 隐私与提交范围

`.env`、客户测试材料、`outputs/`、人工基准、评估报告、含客户规则的历史核对脚本、优化过程记录、本地协作说明、IDE 配置、虚拟环境及常见私钥文件均由 `.gitignore` 排除，仓库只提供空密钥的 `.env.example`。运行输出、生成的基准和诊断可能包含完整业务原文与模型消息，应保留在本地。不要使用 `git add -f` 强行上传这些文件。

`audit/` 中公开的文件是通用引擎与开发工具；客户专用的历史核对脚本和评估报告仅在本地保留，不影响主提取流程导入通用引擎。

运行时会将材料、设计参考及所加载技能的内容发送给配置的 DeepSeek 服务，运行前应确认材料允许发送到该服务。

应用层解析失败后的重跑最多一次；客户端请求重试、ToolStrategy 自身的结构校验重试及中间件修复是不同机制。`recursion_limit=48` 是单次 Agent 图执行的步数限制。
