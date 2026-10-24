from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from research_agent.agent.prompts import build_retry_messages
from research_agent.services.artifacts import save_retry_diagnostic
from research_agent.services.validation import get_retry_error


@dataclass
class AgentExecution:
    result: dict[str, Any]
    started_at: datetime
    finished_at: datetime
    elapsed_seconds: float
    retry_count: int
    retry_debug_file: str | None


def execute_agent(
    agent,
    messages: list,
    output_dir: Path,
    recursion_limit: int,
    skill_files: dict,
    ) -> AgentExecution:
    started_at = datetime.now().astimezone()
    start_counter = perf_counter()
    result = agent.invoke(
        {
            "messages": messages,
            "files": skill_files,
            "pinned_skills": ["design-model-extraction"],
        },
        config={"recursion_limit": recursion_limit},
    )

    retry_count = 0
    retry_debug_file = None
    error_text = get_retry_error(result)
    if error_text is not None:
        returned_messages = result.get("messages", [])
        retry_debug_path = save_retry_diagnostic(output_dir, error_text, returned_messages)
        retry_debug_file = retry_debug_path.name
        retry_messages = build_retry_messages(returned_messages, error_text)

        retry_count = 1
        print("结构化工具参数解析失败，正在重试一次……", flush=True)
        result = agent.invoke(
            {
                "messages": retry_messages,
                "files": skill_files,
            },
            config={"recursion_limit": recursion_limit},
        )

    elapsed_seconds = perf_counter() - start_counter
    finished_at = datetime.now().astimezone()
    return AgentExecution(
        result=result,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_seconds=elapsed_seconds,
        retry_count=retry_count,
        retry_debug_file=retry_debug_file,
    )
