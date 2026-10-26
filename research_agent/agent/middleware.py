"""循环内仅处理结构错误；内容错误交给宿主的独立局部修复阶段。

ExtractionResult 的参数 JSON 解析失败时，该调用进入 invalid_tool_calls，
路由器因 tool_calls 为空而直接结束循环。本中间件在路由判定前拦截这种失败，
注入带具体错误文本的反馈并跳回模型节点，让模型当场重新提交。

完整候选不因少量内容错误在 Agent 历史中反复重写。
"""

import json
from typing import Any
from time import perf_counter

from langchain.agents.middleware import AgentMiddleware, ModelResponse, hook_config
from langchain.messages import AIMessage, ToolMessage

from research_agent.schemas.typed import ExtractionResult

STRUCTURED_TOOL_NAME = "ExtractionResult"


def find_broken_structured_calls(message: AIMessage) -> list[dict[str, Any]]:
    return [
        call
        for call in message.invalid_tool_calls
        if call.get("name") == STRUCTURED_TOOL_NAME
    ]


def count_structured_failures(messages: list) -> int:
    """历史中含无效 ExtractionResult 调用的 AIMessage 数，即已发生的失败轮数。"""
    total = 0
    for message in messages:
        if isinstance(message, AIMessage):
            total += len(find_broken_structured_calls(message))
    return total


def build_repair_feedback(call: dict[str, Any]) -> str:
    args_text = call.get("args") or ""
    error_text = call.get("error")
    position = None
    if not error_text:
        try:
            json.loads(args_text)
            error_text = "工具参数未能解析为有效工具调用"
        except json.JSONDecodeError as exc:
            error_text = str(exc)
            position = exc.pos                      # ←出错字符的下标

    snippet = ""
    if position is not None and args_text:
        start = max(0, position - 80)
        fragment = args_text[start:position + 80]
        snippet = f"\n出错位置附近的原文：…{fragment} ← 这里"

    return (
        f"上一次调用 {STRUCTURED_TOOL_NAME} 的参数 JSON 解析失败：{error_text}。{snippet}\n"
        "请依据已有材料重新生成完整结果，通过 ExtractionResult 返回。"
        "检查所有对象和数组的闭合，以及属性名的双引号；"
        "每个设计对象的 object_type、data、evidence 必须位于同一层，"
        "且 data 内也要写 object_type（与外层一致）。"
        "完整材料和设计参考已经提供，无须搜索文件。"
    )


class StructuredOutputRepairMiddleware(AgentMiddleware):
    """保留 invalid JSON 兜底，并记录每次实际模型调用耗时。"""

    def __init__(self, max_rounds: int = 2, model_calls: list[dict] | None = None) -> None:
        self.max_rounds = max_rounds
        self.model_calls = model_calls if model_calls is not None else []

    def wrap_model_call(self, request, handler):
        started = perf_counter()
        record = {}
        try:
            response = handler(request)
            last = next((m for m in response.result if isinstance(m, AIMessage)), None)
            if last:
                record["usage"] = last.usage_metadata or {}
                record["tool_calls"] = [call["name"] for call in last.tool_calls]
            # 只去除明确的单层参数包装；不猜测业务值，也不修补截断 JSON。
            if last and response.structured_response is None and len(last.tool_calls) == 1:
                call = last.tool_calls[0]
                args = call.get("args")
                if call["name"] == STRUCTURED_TOOL_NAME and isinstance(args, dict) \
                        and set(args) == {"arguments"}:
                    try:
                        unwrapped = args["arguments"]
                        if isinstance(unwrapped, str):
                            unwrapped = json.loads(unwrapped)
                    except (ValueError, TypeError):
                        pass
                    else:
                        if isinstance(unwrapped, dict) and set(unwrapped) == {
                            "objects", "omissions", "conflicts", "unknowns"
                        }:
                            try:
                                parsed = ExtractionResult.model_validate(unwrapped)
                            except ValueError as error:
                                parsed = None
                                feedback = f"Error: 去除 arguments 包装后结构校验仍失败：{error}"
                            else:
                                feedback = "宿主已去除单层 arguments 包装并完成结构校验。"
                            fixed_call = {**call, "args": unwrapped}
                            fixed = last.model_copy(update={"tool_calls": [fixed_call]})
                            response = ModelResponse(
                                result=[fixed, ToolMessage(
                                    content=feedback,
                                    tool_call_id=call["id"], name=STRUCTURED_TOOL_NAME,
                                )], structured_response=parsed,
                            )
                            record["normalization"] = "unwrapped_arguments"
            return response
        except Exception as error:
            record["error"] = str(error)
            raise
        finally:
            record["elapsed_seconds"] = round(perf_counter() - started, 3)
            self.model_calls.append(record)

    @hook_config(can_jump_to=["model"])
    def after_model(self, state, runtime):
        messages = state["messages"]
        # 成功提交时框架会在模型节点内追加成功 ToolMessage，最后一条不再是
        # AIMessage，必须回溯找最后一条 AIMessage 才能覆盖两条分支。
        last = next(
            (m for m in reversed(messages) if isinstance(m, AIMessage)), None
        )
        if last is None:
            return None

        broken = find_broken_structured_calls(last)
        if broken:
            # 当前失败已计入历史；超过上限就放行结束，交给外部兜底。
            if count_structured_failures(messages) > self.max_rounds:
                return None
            feedback = [
                ToolMessage(
                    content=build_repair_feedback(call),
                    tool_call_id=call["id"],
                    name=call.get("name"),
                    status="error",
                )
                for call in broken
                if call.get("id")
            ]
            if not feedback:
                return None
            print(f"[循环内修复] 第 {count_structured_failures(messages)} 次解析失败，已注入修复反馈", flush=True)
            return {"messages": feedback, "jump_to": "model"}

        return None
