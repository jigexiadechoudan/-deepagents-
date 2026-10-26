import json
from datetime import datetime
from time import perf_counter

from audit.baseline_engine import run_baseline_engine
from research_agent.agent.factory import create_extraction_agent
from research_agent.agent.prompts import build_messages
from research_agent.config import load_settings
from research_agent.services.artifacts import save_failure_diagnostic, save_success
from research_agent.services.baseline_store import load_baseline
from research_agent.services.checks import run_checks
from research_agent.services.contract import inspect_reference_contract
from research_agent.services.execution import execute_agent
from research_agent.services.materials import load_material, load_reference, load_skill_files, load_skill_references
from research_agent.services.repair import repair_extraction


def _load_baseline_manifest(settings, material: str, reference: str, skill_files: dict) -> tuple[dict | None, dict]:
    return load_baseline(settings, material, reference, skill_files)


def run_extraction() -> None:
    run_started = perf_counter()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    settings = load_settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    material = load_material(settings.material_path)
    reference = load_reference(settings.reference_path)
    print("测试材料字符数：", len(material))
    print("设计参考字符数：", len(reference))

    contract = inspect_reference_contract(
        reference, settings.reference_path.parent / "图片和附件" / "设计模型-字段总表.xlsx"
    )
    contract_path = settings.output_dir / f"contract_{timestamp}.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    if contract["missing_types"] or contract["unmodeled_types"] or contract["field_mismatches"] \
            or contract["field_table"]["status"] == "changed":
        raise RuntimeError(f"设计参考与 Schema 的字段目录不一致，请先核对：{contract_path}")
    skill_files = load_skill_files(settings.skill_dir)
    skill_references = load_skill_references(skill_files)
    messages = build_messages(material, skill_references)
    model_calls = []
    agent = create_extraction_agent(settings, reference, material, model_calls=model_calls)
    baseline_manifest, baseline_stage = _load_baseline_manifest(settings, material, reference, skill_files)
    print("正在提取设计模型……", flush=True)
    execution = execute_agent(agent, messages, settings.output_dir, settings.recursion_limit, skill_files)
    extraction = execution.result.get("structured_response")
    if extraction is None:
        debug_path = save_failure_diagnostic(settings.output_dir, timestamp, execution)
        raise RuntimeError(
            f"Agent 未返回结构化结果，诊断信息已保存到：{debug_path}"
        )

    candidate_path = settings.output_dir / f"candidate_{timestamp}.json"
    candidate_path.write_text(extraction.model_dump_json(indent=2, by_alias=True, exclude_none=True), encoding="utf-8")
    repair_sources = {path: data["content"] for path, data in skill_files.items()}
    repair = repair_extraction(extraction, settings, material, reference, repair_sources, baseline_manifest)
    extraction = repair.extraction
    validation_started = perf_counter()
    violations = run_checks(extraction.model_dump(by_alias=True, exclude_none=True), material)
    errors = sum(1 for v in violations if v["severity"] == "error")
    print(f"通用校验：{errors} 个错误 / {len(violations) - errors} 个警告", flush=True)
    for v in violations:
        print(f"  [{v['severity']}] {v['check']} | {v['object_id']} | {v['message']}", flush=True)

    baseline = None
    if baseline_manifest is not None:
        baseline = run_baseline_engine(extraction.model_dump(by_alias=True, exclude_none=True), baseline_manifest, material)
        print(f"场景基准：通过 {baseline['passed']} / 告警 {baseline['warnings']} / 失败 {baseline['failures']}",
              flush=True)
        for i in baseline["items"]:
            if i["status"] != "pass":
                print(f"  [{i['status']}] {i['check']} | {i['detail']}", flush=True)

    output_path, record_path, run_record = save_success(
        settings, timestamp, execution, extraction, material, reference,
        checks=violations, baseline=baseline,
        baseline_manifest=baseline_manifest, baseline_stage=baseline_stage,
        repair=repair, model_calls=model_calls,
        candidate_file=candidate_path.name, contract_file=contract_path.name,
        stage_timings={
            "baseline_seconds": baseline_stage.get("elapsed_seconds", 0),
            "extraction_seconds": round(execution.elapsed_seconds, 3),
            "repair_seconds": repair.elapsed_seconds,
            "final_validation_seconds": round(perf_counter() - validation_started, 3),
            "total_before_save_seconds": round(perf_counter() - run_started, 3),
        },
    )
    print("Agent 执行耗时：", run_record["agent_elapsed_seconds"], "秒")
    print("测试记录保存到：", record_path)
    print("结果保存到：", output_path)
    print("提取对象数量：", len(extraction.objects))
    print("质量状态：", run_record["quality_status"])
    print("局部修复耗时：", repair.elapsed_seconds, "秒")
    print("总耗时（保存前）：", run_record["stage_timings"]["total_before_save_seconds"], "秒")
    print(extraction.model_dump_json(indent=2, by_alias=True, exclude_none=True))
