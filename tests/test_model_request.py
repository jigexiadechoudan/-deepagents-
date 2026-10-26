"""思考模式请求兼容检查；不访问网络。"""

import unittest

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from research_agent.agent.model import ChatDeepSeek


class ModelRequestTests(unittest.TestCase):
    def payload(self, mode, choice):
        model = ChatDeepSeek(model="deepseek-flash", api_key="offline-placeholder",
                             extra_body={"thinking": {"type": mode}})
        messages = [HumanMessage(content="input"), AIMessage(content="", additional_kwargs={
            "reasoning_content": "offline reasoning"}, tool_calls=[{
                "name": "read_file", "args": {}, "id": "call1"}]),
            ToolMessage(content="text", tool_call_id="call1")]
        tools = [{"type": "function", "function": {"name": "read_file", "parameters": {
            "type": "object", "properties": {}}}}]
        return model._get_request_payload(messages, tools=tools, tool_choice=choice)

    def test_thinking_converts_forced_tool_choice_to_auto(self):
        for choice in ("required", "any", {"type": "function", "function": {"name": "read_file"}}):
            with self.subTest(choice=choice):
                self.assertEqual(self.payload("enabled", choice)["tool_choice"], "auto")

    def test_non_thinking_retains_forced_tool_choice(self):
        self.assertEqual(self.payload("disabled", "required")["tool_choice"], "required")

    def test_preserves_reasoning_for_tool_continuation(self):
        payload = self.payload("enabled", "auto")
        self.assertEqual(payload["messages"][1]["reasoning_content"], "offline reasoning")
        self.assertNotIn("reasoning_content", payload["messages"][0])
        self.assertNotIn("reasoning_content", payload["messages"][2])


if __name__ == "__main__":
    unittest.main()
