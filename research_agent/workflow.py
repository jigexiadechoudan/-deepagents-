from datetime import datetime

from research_agent.agent.factory import create_extraction_agent
from research_agent.agent.prompts import build_messages
from research_agent.config import load_settings
from research_agent.services.artifacts import save_failure_diagnostic, save_success
from research_agent.services.execution import execute_agent
from research_agent.services.materials import load_material, load_reference, load_skill_files


def run_extraction() -> None:
    settings = load_settings()
    material = load_material(settings.material_path)
    reference = load_reference(settings.reference_path)
    print("测试材料字符数：", len(material))
    print("设计参考字符数：", len(reference))

    agent = create_extraction_agent(settings, reference)
    messages = build_messages(material)
    settings.output_dir.mkdir(exist_ok=True)
    print("正在提取设计模型……", flush=True)
    skill_files = load_skill_files(settings.skill_dir)
    execution = execute_agent(agent, messages, settings.output_dir, settings.recursion_limit, skill_files)
    extraction = execution.result.get("structured_response")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    if extraction is None:
        debug_path = save_failure_diagnostic(settings.output_dir, timestamp, execution)
        raise RuntimeError(
            f"Agent 未返回结构化结果，诊断信息已保存到：{debug_path}"
        )

    output_path, record_path, run_record = save_success(
        settings, timestamp, execution, extraction, material, reference
    )
    print("Agent 执行耗时：", run_record["agent_elapsed_seconds"], "秒")
    print("测试记录保存到：", record_path)
    print("结果保存到：", output_path)
    print("提取对象数量：", len(extraction.objects))
    print(extraction.model_dump_json(indent=2))
