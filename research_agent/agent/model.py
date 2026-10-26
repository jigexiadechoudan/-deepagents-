"""补齐当前客户端在 DeepSeek 思考模式工具循环中的字段回传。"""

from langchain_deepseek import ChatDeepSeek as BaseChatDeepSeek
from langchain.messages import AIMessage


class ChatDeepSeek(BaseChatDeepSeek):
    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        thinking = (payload.get("extra_body") or {}).get("thinking", {}).get("type")
        choice = payload.get("tool_choice")
        if thinking == "enabled" and payload.get("tools") and (
                choice in ("any", "required") or isinstance(choice, dict)):
            # ToolStrategy 会强制选择工具，DeepSeek 思考模式只接受自动选择。
            payload["tool_choice"] = "auto"
        messages = self._convert_input(input_).to_messages()
        for message, serialized in zip(messages, payload["messages"], strict=True):
            if isinstance(message, AIMessage):
                reasoning = message.additional_kwargs.get("reasoning_content")
                if reasoning is not None:
                    serialized["reasoning_content"] = reasoning
        return payload
