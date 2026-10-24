# 调研助手 MVP

使用 DeepAgents 从测试材料中提取结构化设计模型。当前进行广度提取，模型为 DeepSeek，结果使用 `ExtractionResult` 外层结构校验。

## 运行

使用 Python 3.11 或更高版本。在项目根目录创建虚拟环境并安装依赖（已有环境可跳过前两步）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在本地 `.env` 填写自己的 `DEEPSEEK_API_KEY`。已有 `.env` 时不要覆盖。

此公开仓库不包含客户材料、设计参考、外部提取技能和历史运行输出。运行前需要在本地准备 `research_agent/config.py` 中的 `MATERIAL_PATH`、`REFERENCE_PATH` 和 `Settings.skill_dir` 对应文件；这些路径仍采用原开发环境的配置，换机器时需要调整。缺少技能目录时当前代码会返回空技能文件集合，不会主动报错。

准备完成后启动：

```powershell
.\.venv\Scripts\python.exe main.py
```

PyCharm 继续选择项目 `.venv` 解释器，直接运行根目录 `main.py`。程序路径根据文件位置计算，不依赖工作目录。

运行时从根目录 `.env` 加载 `DEEPSEEK_API_KEY`；可选的 `DEEPSEEK_MODEL` 默认是 `deepseek-flash`。启动主流程会调用真实模型，可能产生费用。导入模块、运行下面的读取示例及离线测试不会调用模型。

## 代码职责

| 位置 | 职责 |
| --- | --- |
| `main.py` | 程序入口，只启动总流程 |
| `research_agent/config.py` | 项目路径、环境加载、模型参数和循环限制 |
| `research_agent/workflow.py` | 读取、创建 Agent、执行、判断结果和保存的总流程 |
| `research_agent/agent/` | 模型与 Agent 创建，以及系统、初始和重试提示词 |
| `research_agent/schemas/` | 现有 Pydantic 设计对象与提取结果结构 |
| `research_agent/services/materials.py` | UTF-8 读取测试材料和设计参考 |
| `research_agent/services/validation.py` | 判断现有结构化调用是否满足应用层重试条件 |
| `research_agent/services/execution.py` | Agent 调用、最多一次应用层重试及执行计时 |
| `research_agent/services/artifacts.py` | 提取结果、诊断和运行记录的文件保存 |
| `tests/test_refactor.py` | 使用模拟 Agent 的离线回归测试 |

固定流程：加载配置 → 读取材料和参考 → 创建 Agent → 执行与有限重试 → 判断结果 → 保存与打印。

当前没有注册自定义业务工具。材料读取、初始化、重试和最终保存由程序执行；`ExtractionResult` 仍通过 `ToolStrategy` 作为结构化输出入口。本次重构没有加入规划、草稿管理或额外质量校验。

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

现有测试尚未同步技能加载接口，详见 [项目审查记录](PROJECT_REVIEW.md)。本次上传只进行静态审查和提交内容的隐私扫描，未运行测试，也未调用模型。

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

测试使用模拟 Agent、虚拟环境变量和项目内的临时目录，不加载真实 `.env`，不调用真实模型，不写入历史 `outputs/`。提示词和输出模型与重构前的摘要对照检查。

## 输出含义

- `extraction_时间戳.json`：取得的结构化提取结果。
- `run_时间戳.json`：运行参数、时间、对象计数和重试信息。
- `retry_时间戳.json`：应用层重试前的首次无效工具调用记录。
- `debug_时间戳.json`：最终未取得结构化结果时的诊断，保存后抛出错误。

`completed` 仅表示取得结构化结果，不代表业务提取质量通过。现有结构未校验对象类型范围、`data` 内部字段、ID 唯一性、关联完整性或证据真实性。

## 隐私与提交范围

`.env`、客户测试材料、`outputs/`、本地协作说明、IDE 配置、虚拟环境及常见私钥文件均由 `.gitignore` 排除，仓库只提供空密钥的 `.env.example`。运行输出和诊断可能包含完整业务原文与模型消息，应保留在本地。不要使用 `git add -f` 强行上传这些文件。

运行时会将材料、设计参考及所加载技能的内容发送给配置的 DeepSeek 服务，运行前应确认材料允许发送到该服务。

应用层解析失败后的重跑最多一次；客户端请求重试与 ToolStrategy 自身的结构校验重试仍是独立机制。`recursion_limit=12` 是单次 Agent 图执行的步数限制。
