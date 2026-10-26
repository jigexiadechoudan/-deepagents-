from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages import BaseMessage

if TYPE_CHECKING:
    from research_agent.config import Settings
    from research_agent.schemas.design import ExtractionResult
    from research_agent.services.execution import AgentExecution
    from research_agent.services.repair import RepairExecution


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_retry_diagnostic(
    output_dir: Path, error_text: str, messages: list[BaseMessage]
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = output_dir / f"retry_{timestamp}.json"
    _write_json(
        path,
        {
            "status": "invalid_tool_call",
            "attempt": 1,
            "error": error_text,
            "messages": [message.model_dump(mode="json") for message in messages],
        },
    )
    return path


def save_failure_diagnostic(
    output_dir: Path, timestamp: str, execution: AgentExecution
) -> Path:
    path = output_dir / f"debug_{timestamp}.json"
    _write_json(
        path,
        {
            "run_id": timestamp,
            "status": "failed",
            "reason": "没有获得结构化提取结果",
            "started_at": execution.started_at.isoformat(),
            "finished_at": execution.finished_at.isoformat(),
            "agent_elapsed_seconds": round(execution.elapsed_seconds, 3),
            "invalid_tool_call_retry_count": execution.retry_count,
            "recursion_exhausted": execution.recursion_exhausted,
            "retry_debug_file": execution.retry_debug_file,
            "messages": [
                message.model_dump(mode="json")
                for message in execution.result.get("messages", [])
            ],
        },
    )
    return path


def _skill_version_sha(skill_dir: Path) -> str | None:
    """技能目录内容快照：按相对路径排序逐文件哈希，目录不存在时返回 None。"""
    if not skill_dir.is_dir():
        return None
    hasher = hashlib.sha256()
    for path in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
        hasher.update(path.relative_to(skill_dir).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _transcript(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """每次模型调用的动作与 token 用量，用于事后定位输出截断与重复提交。

    ToolMessage 的两类错误反馈也记录在案：schema 校验失败（langchain
    ToolStrategy handle_errors=True 的固定模板，以 "Error: " 开头且不带
    error 状态）与工具/修复注入的 error 状态消息，此前均为黑盒。
    """
    rows: list[dict[str, Any]] = []
    for message in messages:
        row: dict[str, Any] = {"type": message.type}
        usage = getattr(message, "usage_metadata", None) or {}
        legacy = (getattr(message, "response_metadata", None) or {}).get("token_usage") or {}
        if usage or legacy:
            row["prompt_tokens"] = usage.get("input_tokens", legacy.get("prompt_tokens", 0))
            row["completion_tokens"] = usage.get("output_tokens", legacy.get("completion_tokens", 0))
        if isinstance(message, AIMessage):
            if message.tool_calls:
                row["tool_calls"] = [call["name"] for call in message.tool_calls]
            if message.invalid_tool_calls:
                row["invalid"] = [call["name"] for call in message.invalid_tool_calls]
        if isinstance(message, ToolMessage):
            content = message.content if isinstance(message.content, str) else ""
            if content.startswith("Error: ") and message.status != "error":
                row["schema_feedback"] = content[:600]
            elif message.status == "error":
                row["tool_error"] = content[:300]
        if isinstance(message, HumanMessage) and isinstance(message.content, str) \
                and message.content.startswith("内容校验未通过："):
            row["check_feedback"] = message.content[:500]
        rows.append(row)
    return rows


def save_success(
    settings: Settings,
    timestamp: str,
    execution: AgentExecution,
    extraction: ExtractionResult,
    material: str,
    reference: str,
    checks: list[dict[str, Any]] | None = None,
    baseline: dict[str, Any] | None = None,
    baseline_manifest: dict[str, Any] | None = None,
    baseline_stage: dict[str, Any] | None = None,
    repair: RepairExecution | None = None,
    model_calls: list[dict] | None = None,
    candidate_file: str | None = None,
    contract_file: str | None = None,
    stage_timings: dict | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    output_path = settings.output_dir / f"extraction_{timestamp}.json"
    output_path.write_text(
        extraction.model_dump_json(indent=2, by_alias=True, exclude_none=True), encoding="utf-8"
    )
    transcript = _transcript(execution.result.get("messages", []))
    error_count = sum(1 for v in (checks or []) if v["severity"] == "error")
    if error_count or (baseline or {}).get("failures", 0):
        quality_status = "needs_review"
    elif baseline is None:
        quality_status = "coverage_unchecked"
    elif (baseline_stage or {}).get("review_status") != "reviewed":
        quality_status = "baseline_review_required"
    elif checks or (baseline or {}).get("warnings", 0):
        quality_status = "needs_review"
    else:
        quality_status = "automated_checks_passed"
    initial_tokens = (
        sum(row.get("usage", {}).get("output_tokens", 0) for row in model_calls)
        if model_calls else sum(row.get("completion_tokens", 0) for row in transcript)
    )
    repair_records = repair.records if repair else []
    repair_tokens = sum(row.get("output_tokens", 0) for row in repair_records)
    baseline_tokens = (baseline_stage or {}).get("generator_output_tokens") or 0
    run_record = {
        "run_id": timestamp,
        "status": "completed",
        "started_at": execution.started_at.isoformat(),
        "finished_at": execution.finished_at.isoformat(),
        "agent_elapsed_seconds": round(execution.elapsed_seconds, 3),
        "invalid_tool_call_retry_count": execution.retry_count,
        "schema_validation_retry_count": sum(
            1 for row in transcript if "schema_feedback" in row
        ),
        "recursion_exhausted": execution.recursion_exhausted,
        "retry_debug_file": execution.retry_debug_file,
        "model_params": settings.model_params,
        "recursion_limit": settings.recursion_limit,
        "deepagents_version": version("deepagents"),
        "skill_version_sha256": _skill_version_sha(settings.skill_dir),
        "total_completion_tokens": initial_tokens + repair_tokens,
        "extraction_completion_tokens": initial_tokens,
        "repair_completion_tokens": repair_tokens,
        "baseline_completion_tokens": baseline_tokens,
        "pipeline_completion_tokens": initial_tokens + repair_tokens + baseline_tokens,
        "model_calls": model_calls or [],
        "repair": {"rounds": repair_records, "elapsed_seconds": repair.elapsed_seconds if repair else 0},
        "candidate_file": candidate_file,
        "contract_file": contract_file,
        "stage_timings": stage_timings or {},
        "quality_status": quality_status,
        "business_completeness": "not_independently_reviewed",
        "structure_status": "schema_valid",
        "coverage_summary": (baseline or {}).get("coverage", {}),
        "coverage_scope": (baseline or {}).get("coverage_scope", "not_checked"),
        "unchecked": {
            "coverage": baseline is None or not (baseline or {}).get("items"),
            "source_semantics": (baseline or {}).get("source_review", {}),
            "baseline_generation": (baseline_stage or {}).get("self_check", {}),
            "business_completeness": True,
            "platform_execution": True,
        },
        "transcript": transcript,
        "checks": {
            "error_count": error_count,
            "items": checks or [],
        },
        "baseline_check": baseline,
        "baseline_manifest": baseline_manifest,
        "baseline_manifest_sha256": (
            hashlib.sha256(
                json.dumps(baseline_manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            if baseline_manifest else None
        ),
        "baseline_stage": baseline_stage,
        "material_chars": len(material),
        "reference_chars": len(reference),
        "object_count": len(extraction.objects),
        "object_type_counts": dict(Counter(obj.object_type for obj in extraction.objects)),
        "result_file": output_path.name,
    }
    record_path = settings.output_dir / f"run_{timestamp}.json"
    _write_json(record_path, run_record)
    return output_path, record_path, run_record
