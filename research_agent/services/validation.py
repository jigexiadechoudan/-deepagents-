"""识别现有结构化调用解析失败，不增加业务或证据校验。"""

import json
from typing import Any

from langchain.messages import AIMessage


def get_retry_error(result: dict[str, Any]) -> str | None:
    returned_messages = result.get("messages", [])
    last_message = returned_messages[-1] if returned_messages else None

    if (
        result.get("structured_response") is None
        and isinstance(last_message, AIMessage)
        and not last_message.tool_calls
        and len(last_message.invalid_tool_calls) == 1
        and last_message.invalid_tool_calls[0]["name"] == "ExtractionResult"
    ):
        invalid_call = last_message.invalid_tool_calls[0]
        try:
            json.loads(invalid_call.get("args") or "")
        except json.JSONDecodeError as error:
            return str(error)
        return "工具参数未能解析为有效工具调用"

    return None
