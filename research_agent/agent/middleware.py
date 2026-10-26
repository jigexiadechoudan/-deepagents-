"""循环内仅处理结构错误；内容错误交给宿主的独立局部修复阶段。

ExtractionResult 的参数 JSON 解析失败时，该调用进入 invalid_tool_calls，
路由器因 tool_calls 为空而直接结束循环。本中间件在路由判定前拦截这种失败，
注入带具体错误文本的反馈并跳回模型节点，让模型当场重新提交。

完整候选不因少量内容错误在 Agent 历史中反复重写。
"""

import json
from copy import deepcopy
from typing import Any
from time import perf_counter

from langchain.agents.middleware import AgentMiddleware, ModelResponse, hook_config
from langchain.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from research_agent.schemas.typed import ExtractionResult

STRUCTURED_TOOL_NAME = "ExtractionResult"
RESULT_KEYS = {"objects", "omissions", "conflicts", "unknowns"}


def _result_payload(message):
    if not isinstance(message, AIMessage) or len(message.tool_calls) != 1:
        return None
    call = message.tool_calls[0]
    if call["name"] != STRUCTURED_TOOL_NAME:
        return None
    payload = call.get("args")
    if isinstance(payload, dict) and set(payload) == {"arguments"}:
        payload = payload["arguments"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                return None
    if isinstance(payload, dict) and set(payload) == RESULT_KEYS \
            and all(isinstance(payload[key], list) for key in RESULT_KEYS):
        return payload
    return None


def retain_schema_candidate(previous, submitted):
    """Schema 重试按稳定 ID 保留完整候选；只合并能明确定位的局部对象修正。"""
    try:
        ExtractionResult.model_validate(previous)
    except ValidationError as error:
        errors = error.errors(include_url=False, include_input=False)
    else:
        return submitted

    def indexed(payload):
        objects = payload["objects"]
        ids = [obj.get("data", {}).get("id") if isinstance(obj, dict) else None
               for obj in objects]
        if any(not isinstance(oid, str) or not oid.strip() for oid in ids) \
                or len(ids) != len(set(ids)):
            raise ValueError("Schema 重试对象缺少唯一稳定 ID，不能安全合并；请重新提交完整候选")
        return dict(zip(ids, objects))

    before, after = indexed(previous), indexed(submitted)
    missing = set(before) - set(after)
    if missing:
        invalid_ids = set()
        for error in errors:
            path = error["loc"]
            if len(path) < 2 or path[0] != "objects" or not isinstance(path[1], int):
                raise ValueError("上次存在对象以外的 Schema 错误，请重交完整结果，不能提交局部候选")
            invalid_ids.add(previous["objects"][path[1]]["data"]["id"])
        if set(after) - set(before):
            raise ValueError("局部 Schema 重试不能重命名或新增对象，请保留原 ID 提交修正")
        if any(obj != before[oid] for oid, obj in after.items() if oid not in invalid_ids):
            raise ValueError("局部 Schema 重试修改了无错误对象，请仅修正报错对象或提交完整结果")
    merged = deepcopy(previous)
    merged["objects"] = [after.get(oid, obj) for oid, obj in before.items()]
    merged["objects"].extend(obj for oid, obj in after.items() if oid not in before)
    for key in RESULT_KEYS - {"objects"}:
        # Schema 纠错没有删除业务报告的授权；空数组不能抹掉前次完整报告。
        merged[key].extend(item for item in submitted[key] if item not in merged[key])
    return merged


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
                record["reasoning_content_chars"] = len(last.additional_kwargs.get("reasoning_content") or "")
            payload = _result_payload(last)
            if payload is not None:
                call = last.tool_calls[0]
                record["submitted_object_count"] = len(payload["objects"])
                previous = next((value for message in reversed(request.messages)
                                 if (value := _result_payload(message)) is not None), None)
                feedback = None
                if previous is not None:
                    try:
                        payload = retain_schema_candidate(previous, payload)
                    except ValueError as error:
                        payload = previous
                        feedback = str(error)
                        record["schema_retry_mode"] = "rejected_partial"
                    else:
                        record["schema_retry_mode"] = "retained_complete_candidate"
                    record["previous_object_count"] = len(previous["objects"])
                try:
                    parsed = ExtractionResult.model_validate(payload) if feedback is None else None
                except ValidationError as error:
                    parsed = None
                    feedback = json.dumps(error.errors(include_url=False, include_input=False),
                                          ensure_ascii=False, default=str)
                record["retained_object_count"] = len(payload["objects"])
                if parsed is None:
                    feedback = (f"Error: Schema 校验失败：{feedback}。宿主保留完整候选的 "
                                f"{len(payload['objects'])} 个对象及报告。"
                                "按稳定 ID 修正报错对象；可提交这些对象的完整定义，"
                                "其余对象与报告由宿主保留。不能重命名对象或改写无错误对象。")
                else:
                    feedback = f"已接收完整候选，共 {len(parsed.objects)} 个对象；宿主将执行全量检查。"
                fixed = last.model_copy(update={"tool_calls": [{**call, "args": payload}]})
                response = ModelResponse(result=[fixed, ToolMessage(
                    content=feedback, tool_call_id=call["id"], name=STRUCTURED_TOOL_NAME,
                    status="error" if parsed is None else "success",
                    additional_kwargs={"schema_validation_error": parsed is None},
                )], structured_response=parsed)
                if set(call.get("args", {})) == {"arguments"}:
                    record["normalization"] = "unwrapped_arguments"
                return response
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
