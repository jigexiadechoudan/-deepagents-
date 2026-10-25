import json
from datetime import datetime
from pathlib import Path

from audit.baseline_engine import run_baseline_engine
from research_agent.agent.factory import create_extraction_agent
from research_agent.agent.prompts import build_messages
from research_agent.config import load_settings
from research_agent.services.artifacts import save_failure_diagnostic, save_success
from research_agent.services.baseline_generator import generate_baseline_manifest
from research_agent.services.checks import run_checks
from research_agent.services.execution import execute_agent
from research_agent.services.materials import load_material, load_reference, load_skill_files


def _load_baseline_manifest(settings, material: str) -> tuple[dict | None, dict]:
    """前置分析步：按 baseline_mode 取得基准清单；获取失败不阻断提取主流程。"""
    mode = settings.baseline_mode
    try:
        if mode == "file":
            path = settings.baseline_manifest_path
            if not path or not Path(path).exists():
                print("[基准] file 模式但清单文件缺失，本轮不做基准核对", flush=True)
                return None, {"source": "file", "missing": True}
            manifest = json.loads(Path(path).read_text(encoding="utf-8"))
            return manifest, {"source": "file", "path": str(path)}
        if mode == "auto":
            print("[基准] 前置分析步：正在从材料生成基准清单……", flush=True)
            generation = generate_baseline_manifest(material, settings)
            counts = generation.meta["counts"]
            dropped = generation.meta["self_check"]["dropped"]
            warnings = generation.meta["self_check"]["warnings"]
            print(
                f"[基准] 清单生成完成：字段 {counts['fields']} / 按钮 {counts['buttons']}"
                f" / 选项值 {counts['option_values']}；剔除 {len(dropped)} 条幻觉嫌疑",
                flush=True,
            )
            for warning in warnings:
                print(f"[基准] 自检告警：{warning}", flush=True)
            return generation.manifest, generation.meta
        if mode != "off":
            print(f"[基准] 未知 baseline_mode={mode}，本轮不做基准核对", flush=True)
            return None, {"source": mode}
        return None, {"source": "off"}
    except Exception as error:
        print(f"[基准] 清单获取失败，本轮不做基准核对：{error}", flush=True)
        return None, {"source": "error", "error": str(error)}


def run_extraction() -> None:
    settings = load_settings()
    material = load_material(settings.material_path)
    reference = load_reference(settings.reference_path)
    print("测试材料字符数：", len(material))
    print("设计参考字符数：", len(reference))

    agent = create_extraction_agent(settings, reference, material)
    messages = build_messages(material)
    settings.output_dir.mkdir(exist_ok=True)
    print("正在提取设计模型……", flush=True)
    skill_files = load_skill_files(settings.skill_dir)
    baseline_manifest, baseline_stage = _load_baseline_manifest(settings, material)
    execution = execute_agent(agent, messages, settings.output_dir, settings.recursion_limit, skill_files)
    extraction = execution.result.get("structured_response")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    if extraction is None:
        debug_path = save_failure_diagnostic(settings.output_dir, timestamp, execution)
        raise RuntimeError(
            f"Agent 未返回结构化结果，诊断信息已保存到：{debug_path}"
        )

    violations = run_checks(extraction.model_dump(by_alias=True), material)
    errors = sum(1 for v in violations if v["severity"] == "error")
    print(f"通用校验：{errors} 个错误 / {len(violations) - errors} 个警告", flush=True)
    for v in violations:
        print(f"  [{v['severity']}] {v['check']} | {v['object_id']} | {v['message']}", flush=True)

    baseline = None
    if baseline_manifest is not None:
        baseline = run_baseline_engine(extraction.model_dump(by_alias=True), baseline_manifest, material)
        print(f"场景基准：通过 {baseline['passed']} / 告警 {baseline['warnings']} / 失败 {baseline['failures']}",
              flush=True)
        for i in baseline["items"]:
            if i["status"] != "pass":
                print(f"  [{i['status']}] {i['check']} | {i['detail']}", flush=True)

    output_path, record_path, run_record = save_success(
        settings, timestamp, execution, extraction, material, reference,
        checks=violations, baseline=baseline,
        baseline_manifest=baseline_manifest, baseline_stage=baseline_stage,
    )
    print("Agent 执行耗时：", run_record["agent_elapsed_seconds"], "秒")
    print("测试记录保存到：", record_path)
    print("结果保存到：", output_path)
    print("提取对象数量：", len(extraction.objects))
    print(extraction.model_dump_json(indent=2, by_alias=True))
