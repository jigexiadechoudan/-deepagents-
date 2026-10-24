from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage

if TYPE_CHECKING:
    from research_agent.config import Settings
    from research_agent.schemas.design import ExtractionResult
    from research_agent.services.execution import AgentExecution


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
            "retry_debug_file": execution.retry_debug_file,
            "messages": [
                message.model_dump(mode="json")
                for message in execution.result.get("messages", [])
            ],
        },
    )
    return path


def save_success(
    settings: Settings,
    timestamp: str,
    execution: AgentExecution,
    extraction: ExtractionResult,
    material: str,
    reference: str,
) -> tuple[Path, Path, dict[str, Any]]:
    output_path = settings.output_dir / f"extraction_{timestamp}.json"
    output_path.write_text(extraction.model_dump_json(indent=2), encoding="utf-8")
    run_record = {
        "run_id": timestamp,
        "status": "completed",
        "started_at": execution.started_at.isoformat(),
        "finished_at": execution.finished_at.isoformat(),
        "agent_elapsed_seconds": round(execution.elapsed_seconds, 3),
        "invalid_tool_call_retry_count": execution.retry_count,
        "retry_debug_file": execution.retry_debug_file,
        "model_params": settings.model_params,
        "recursion_limit": settings.recursion_limit,
        "deepagents_version": version("deepagents"),
        "material_chars": len(material),
        "reference_chars": len(reference),
        "object_count": len(extraction.objects),
        "object_type_counts": dict(Counter(obj.object_type for obj in extraction.objects)),
        "result_file": output_path.name,
    }
    record_path = settings.output_dir / f"run_{timestamp}.json"
    _write_json(record_path, run_record)
    return output_path, record_path, run_record
