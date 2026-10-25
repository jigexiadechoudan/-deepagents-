"""循环内修复结构化输出的无效调用与内容违规。

ExtractionResult 的参数 JSON 解析失败时，该调用进入 invalid_tool_calls，
路由器因 tool_calls 为空而直接结束循环。本中间件在路由判定前拦截这种失败，
注入带具体错误文本的反馈并跳回模型节点，让模型当场重新提交。

语法合格的提交再过一遍 run_checks 语义校验：存在 error 级违规时打回重交，
structured_response 同步置空，防止模型摆烂时旧结果静默过审；warning 不触发
循环内打回，只留在后置报告。
"""

import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain.messages import AIMessage, HumanMessage, ToolMessage

from research_agent.services.checks import run_checks

STRUCTURED_TOOL_NAME = "ExtractionResult"
CHECK_FEEDBACK_PREFIX = "内容校验未通过："


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


def count_check_feedbacks(messages: list) -> int:
    """历史中语义校验打回的次数（按反馈消息前缀计数）。"""
    return sum(
        1
        for message in messages
        if isinstance(message, HumanMessage)
        and isinstance(message.content, str)
        and message.content.startswith(CHECK_FEEDBACK_PREFIX)
    )


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


def build_check_feedback(errors: list[dict]) -> str:
    shown = errors[:15]
    lines = "\n".join(
        f"- [{v['check']}] {v['object_id']}: {v['message']}" for v in shown
    )
    more = f"\n（共 {len(errors)} 项，其余以后置报告为准）" if len(errors) > 15 else ""
    return (
        f"{CHECK_FEEDBACK_PREFIX}刚才提交的 ExtractionResult 语法合格，"
        f"但内容校验发现 {len(errors)} 项错误：\n{lines}{more}\n"
        "请修复这些问题后重新通过 ExtractionResult 提交完整结果。"
        "修复对象而不是删除对象，删除有依据的对象视为信息丢失。"
        "完整材料和设计参考已经提供，无须搜索文件。"
    )


class StructuredOutputRepairMiddleware(AgentMiddleware):
    """invalid JSON 的静默终止与语义违规在这里都变成循环内的一轮修复。"""

    def __init__(
        self,
        max_rounds: int = 2,
        material: str | None = None,
        max_check_rounds: int = 2,
    ) -> None:
        self.max_rounds = max_rounds
        self.material = material
        self.max_check_rounds = max_check_rounds

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

        return self._check_submission(state, last, messages)

    def _check_submission(self, state, last: AIMessage, messages: list):
        """合法提交后的语义校验：error 级违规打回重交，warning 放行。"""
        if self.material is None or state.get("structured_response") is None:
            return None
        if not any(tc["name"] == STRUCTURED_TOOL_NAME for tc in last.tool_calls):
            return None
        if count_check_feedbacks(messages) >= self.max_check_rounds:
            return None
        response = state["structured_response"]
        payload = (response.model_dump(by_alias=True) if hasattr(response, "model_dump") else response)
        errors = [
            v for v in run_checks(payload, self.material) if v["severity"] == "error"
        ]
        if not errors:
            return None
        print(
            f"[循环内校验] 提交未过内容校验（{len(errors)} 个错误），打回重交",
            flush=True,
        )
        return {
            "messages": [HumanMessage(content=build_check_feedback(errors))],
            "structured_response": None,
            "jump_to": "model",
        }
