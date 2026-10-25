from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from langchain.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError

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
    recursion_exhausted: bool = False


def execute_agent(
    agent,
    messages: list,
    output_dir: Path,
    recursion_limit: int,
    skill_files: dict,
    ) -> AgentExecution:
    started_at = datetime.now().astimezone()
    start_counter = perf_counter()
    result, exhausted = _stream_agent(agent, messages, skill_files, recursion_limit)

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
        result, exhausted = _stream_agent(agent, retry_messages, skill_files, recursion_limit, pinned=False)

    elapsed_seconds = perf_counter() - start_counter
    finished_at = datetime.now().astimezone()
    return AgentExecution(
        result=result,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_seconds=elapsed_seconds,
        retry_count=retry_count,
        retry_debug_file=retry_debug_file,
        recursion_exhausted=exhausted,
    )


def _stream_agent(
    agent, messages: list, skill_files: dict, recursion_limit: int, pinned: bool = True
) -> dict:
    """流式执行：实时打印模型动作；递归预算耗尽时保留已有现场，按无结构化结果处理。"""
    payload: dict[str, Any] = {"messages": messages, "files": skill_files}
    if pinned:
        payload["pinned_skills"] = ["design-model-extraction"]

    final_state: dict[str, Any] = {}
    exhausted = False
    seen_ids: set = set()
    try:
        for chunk in agent.stream(
            payload, config={"recursion_limit": recursion_limit}, stream_mode="values"
        ):
            final_state = chunk
            for msg in chunk.get("messages", []):
                mid = getattr(msg, "id", None)
                if not mid or mid in seen_ids:
                    continue
                seen_ids.add(mid)
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    print(
                        f"[循环] 模型调用: {', '.join(tc['name'] for tc in msg.tool_calls)}",
                        flush=True,
                    )
                elif isinstance(msg, AIMessage) and msg.invalid_tool_calls:
                    print("[循环] 模型发出无效的 ExtractionResult 调用", flush=True)
                elif isinstance(msg, ToolMessage):
                    content = str(msg.content)
                    if content.startswith("Error:"):
                        print("[循环] 结构化输出未通过校验，框架已注入错误反馈要求重试", flush=True)
                    else:
                        print(f"[循环] 工具返回 ({getattr(msg, 'status', None) or 'ok'})", flush=True)
    except GraphRecursionError:
        exhausted = True
        print(
            f"[错误] 递归预算 {recursion_limit} 步耗尽，已有现场保留，按无结构化结果处理",
            flush=True,
        )
    return final_state, exhausted
