"""离线回归测试：模拟 Agent，不加载实际 .env，不访问网络。"""

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from langchain.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError

from research_agent import workflow
from research_agent.agent.factory import create_extraction_agent
from research_agent.agent.prompts import build_messages, build_retry_messages, build_system_prompt
from research_agent.config import MATERIAL_PATH, PROJECT_DIR, REFERENCE_PATH, Settings, load_settings
from research_agent.schemas.design import DesignObject, ExtractionResult
from research_agent.services.execution import execute_agent
from research_agent.services.materials import load_material, load_reference
from research_agent.services.validation import get_retry_error


MODEL_PARAMS = {
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "timeout": 180,
    "max_retries": 1,
    "max_tokens": 32768,
    "extra_body": {"thinking": {"type": "disabled"}},
}


class FakeAgent:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def invoke(self, payload, config):
        self.calls.append((payload, config))
        if len(self.calls) > len(self.replies):
            raise AssertionError("发生了未预期的额外 Agent 调用")
        return self.replies[len(self.calls) - 1]


def malformed_result(name="ExtractionResult", args='{"objects": [}'):
    return {
        "messages": [
            HumanMessage(content="测试材料"),
            AIMessage(content="", tool_calls=[
                {"name": "ls", "args": {"path": "/"}, "id": "ls_1"}
            ]),
            ToolMessage(content="No files found", name="ls", tool_call_id="ls_1"),
            AIMessage(content="", invalid_tool_calls=[
                {"name": name, "args": args, "id": "bad_1", "error": "invalid JSON"}
            ]),
        ],
        "structured_response": None,
    }


def successful_result():
    return {
        "messages": [AIMessage(content="done")],
        "structured_response": ExtractionResult(
            objects=[
                DesignObject(object_type="Page", data={"id": "page_1"}, evidence=["证据"]),
                DesignObject(object_type="Page", data={"id": "page_2"}, evidence=["证据"]),
            ],
            omissions=[], conflicts=[], unknowns=[],
        ),
    }


class RefactorTests(unittest.TestCase):
    def setUp(self):
        # 所有临时文件都在项目目录内；清理前先确认绝对路径边界。
        self.temp = tempfile.TemporaryDirectory(prefix=".refactor_test_", dir=PROJECT_DIR)
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(PROJECT_DIR.resolve()))
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.dict(os.environ, {"DEEPSEEK_API_KEY": "offline-placeholder"}, clear=True))
        self.dotenv = self.enterContext(patch("research_agent.config.load_dotenv"))
        self.enterContext(patch("socket.socket.connect", side_effect=AssertionError("禁止网络请求")))
        self.enterContext(patch("socket.socket.connect_ex", side_effect=AssertionError("禁止网络请求")))
        self.material = self.root / "material.md"
        self.reference = self.root / "reference.md"
        self.material.write_text("测试材料，保持 UTF-8。", encoding="utf-8")
        self.reference.write_text("设计参考。", encoding="utf-8")
        self.settings = Settings(
            model_params=MODEL_PARAMS.copy(),
            material_path=self.material,
            reference_path=self.reference,
            output_dir=self.root / "outputs",
        )

    def run_workflow(self, replies, expect_failure=False):
        agent = FakeAgent(replies)
        with (
            patch("research_agent.workflow.load_settings", return_value=self.settings),
            patch("research_agent.workflow.create_extraction_agent", return_value=agent),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            if expect_failure:
                with self.assertRaisesRegex(RuntimeError, "Agent 未返回结构化结果"):
                    workflow.run_extraction()
            else:
                workflow.run_extraction()
        records = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in self.settings.output_dir.glob("*.json")
        }
        return agent, records

    def assert_filenames(self, records):
        for name in records:
            self.assertRegex(name, r"^(retry|debug|run|extraction)_\d{8}_\d{6}_\d{6}\.json$")

    def test_default_model_config_and_environment_override(self):
        settings = load_settings()
        self.assertEqual(settings.model_params, MODEL_PARAMS)
        self.assertEqual(settings.recursion_limit, 12)
        self.dotenv.assert_called_once_with(PROJECT_DIR / ".env")
        self.assertNotIn("api_key", settings.model_params)
        with patch.dict(os.environ, {"DEEPSEEK_MODEL": "offline-custom"}):
            self.assertEqual(load_settings().model_params["model"], "offline-custom")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
                load_settings()

    def test_prompts_and_schema_match_pre_refactor_fingerprints(self):
        # 摘要在重构前从原 main.py 和 design_schema.py 的运行值计算。
        digest = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual(digest(build_system_prompt("REFERENCE")),
                         "91d1036e505e99732554d9cb4e8c4a1577252339085d1d7e6d018aa5aba24796")
        self.assertEqual(digest(json.dumps(build_messages("MATERIAL"), ensure_ascii=False)),
                         "f40b006db4e8fcb1e204766e685547aef90b454e3394de49ac5b0d2d63733391")
        schema = json.dumps(ExtractionResult.model_json_schema(), sort_keys=True, ensure_ascii=False)
        self.assertEqual(digest(schema),
                         "33519be68be438b153550f66e3c9cafdd190562fc111d72e13ba7eb6eb73f772")

    def test_schema_still_only_checks_existing_outer_structure(self):
        DesignObject(object_type="任意类型", data={"未限定字段": 1}, evidence=["未核实的原文"])
        with self.assertRaises(ValidationError):
            DesignObject(object_type="Page", data={}, evidence=[])
        with self.assertRaises(ValidationError):
            DesignObject(object_type="Page", data={}, evidence=["原文"], unexpected=True)

    def test_factory_preserves_configuration_and_registers_no_new_tools(self):
        with (
            patch("research_agent.agent.factory.ChatDeepSeek") as model,
            patch("research_agent.agent.factory.create_deep_agent") as builder,
        ):
            agent = create_extraction_agent(self.settings, "REFERENCE")
        model.assert_called_once_with(**MODEL_PARAMS)
        self.assertIs(agent, builder.return_value)
        kwargs = builder.call_args.kwargs
        self.assertEqual(set(kwargs), {"model", "system_prompt", "response_format"})
        self.assertIs(kwargs["model"], model.return_value)
        self.assertEqual(kwargs["system_prompt"], build_system_prompt("REFERENCE"))
        self.assertIs(kwargs["response_format"].schema, ExtractionResult)

    def test_paths_and_reading_are_independent_of_working_directory(self):
        original = Path.cwd()
        try:
            os.chdir(self.root)
            settings = load_settings()
            self.assertEqual(settings.material_path, MATERIAL_PATH)
            self.assertEqual(settings.reference_path, REFERENCE_PATH)
            self.assertEqual(settings.output_dir, PROJECT_DIR / "outputs")
            self.assertEqual(load_material(), MATERIAL_PATH.read_text(encoding="utf-8"))
            self.assertEqual(load_reference(), REFERENCE_PATH.read_text(encoding="utf-8"))
            self.assertEqual(load_material(self.material), "测试材料，保持 UTF-8。")
        finally:
            os.chdir(original)

    def test_success_preserves_record_and_result_formats(self):
        agent, records = self.run_workflow([successful_result()])
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(agent.calls[0], (
            {"messages": build_messages(load_material(self.material))}, {"recursion_limit": 12}
        ))
        self.assert_filenames(records)
        record = next(value for name, value in records.items() if name.startswith("run_"))
        self.assertEqual(set(record), {
            "run_id", "status", "started_at", "finished_at", "agent_elapsed_seconds",
            "invalid_tool_call_retry_count", "retry_debug_file", "model_params", "recursion_limit",
            "deepagents_version", "material_chars", "reference_chars", "object_count",
            "object_type_counts", "result_file",
        })
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["invalid_tool_call_retry_count"], 0)
        self.assertIsNone(record["retry_debug_file"])
        self.assertEqual(record["object_type_counts"], {"Page": 2})
        self.assertEqual(record["object_count"], 2)
        self.assertEqual(record["model_params"], MODEL_PARAMS)
        self.assertEqual(record["material_chars"], len(load_material(self.material)))
        self.assertEqual(record["reference_chars"], len(load_reference(self.reference)))
        self.assertIsNotNone(datetime.fromisoformat(record["started_at"]).tzinfo)
        self.assertEqual(records[record["result_file"]], successful_result()["structured_response"].model_dump())
        self.assertEqual(len(records), 2)

    def test_retry_success_keeps_raw_failure_and_paired_history(self):
        failed = malformed_result()
        agent, records = self.run_workflow([failed, successful_result()])
        self.assertEqual(len(agent.calls), 2)
        record = next(value for name, value in records.items() if name.startswith("run_"))
        self.assertEqual(record["invalid_tool_call_retry_count"], 1)
        retry = records[record["retry_debug_file"]]
        self.assertEqual(set(retry), {"status", "attempt", "error", "messages"})
        self.assertEqual(retry["messages"], [m.model_dump(mode="json") for m in failed["messages"]])
        self.assertEqual(retry["attempt"], 1)
        self.assertEqual(retry["status"], "invalid_tool_call")
        history = agent.calls[1][0]["messages"]
        self.assertEqual(history[:-1], failed["messages"][:-1])
        self.assertIsInstance(history[-1], HumanMessage)
        self.assertIn(retry["error"], history[-1].content)
        self.assertEqual(history[1].tool_calls[0]["id"], history[2].tool_call_id)
        self.assertFalse(any(isinstance(m, AIMessage) and m.invalid_tool_calls for m in history))
        self.assertEqual(agent.calls[1][1], {"recursion_limit": 12})
        self.assert_filenames(records)

    def test_second_failure_stops_and_preserves_final_diagnostic(self):
        agent, records = self.run_workflow([malformed_result(), malformed_result()], expect_failure=True)
        self.assertEqual(len(agent.calls), 2)
        self.assertEqual(len(records), 2)
        debug = next(value for name, value in records.items() if name.startswith("debug_"))
        self.assertEqual(set(debug), {
            "run_id", "status", "reason", "started_at", "finished_at", "agent_elapsed_seconds",
            "invalid_tool_call_retry_count", "retry_debug_file", "messages",
        })
        self.assertEqual(debug["status"], "failed")
        self.assertEqual(debug["invalid_tool_call_retry_count"], 1)
        self.assertIn(debug["retry_debug_file"], records)
        self.assertEqual(debug["messages"][-1]["invalid_tool_calls"][0]["args"], '{"objects": [}')
        self.assertFalse(any(n.startswith(("run_", "extraction_")) for n in records))
        self.assert_filenames(records)

    def test_no_retry_for_missing_or_other_calls(self):
        mixed = malformed_result()
        mixed["messages"][-1].tool_calls = [
            {"name": "ls", "args": {"path": "/"}, "id": "valid_1", "type": "tool_call"}
        ]
        multiple = malformed_result()
        multiple["messages"][-1].invalid_tool_calls *= 2
        results = [
            {}, {"structured_response": None},
            {"messages": [HumanMessage(content="no AI")]},
            {"messages": [AIMessage(content="plain text")]},
            {"messages": [AIMessage(content="", tool_calls=[
                {"name": "ls", "args": {"path": "/"}, "id": "valid_1"}
            ])]},
            malformed_result(name="other"), mixed, multiple,
        ]
        self.settings.output_dir.mkdir()
        for result in results:
            with self.subTest(result=result), contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(get_retry_error(result))
                agent = FakeAgent([result])
                execution = execute_agent(agent, [], self.settings.output_dir, 12)
                self.assertEqual(len(agent.calls), 1)
                self.assertEqual(execution.retry_count, 0)
        self.assertEqual(list(self.settings.output_dir.iterdir()), [])

    def test_missing_result_saves_failure_before_raising(self):
        agent, records = self.run_workflow([{}], expect_failure=True)
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(len(records), 1)
        debug = next(iter(records.values()))
        self.assertEqual(debug["messages"], [])
        self.assertEqual(debug["invalid_tool_call_retry_count"], 0)
        self.assertIsNone(debug["retry_debug_file"])

    def test_generic_parse_error_and_retry_feedback_remain_unchanged(self):
        failed = malformed_result(args="{}")
        error = get_retry_error(failed)
        self.assertEqual(error, "工具参数未能解析为有效工具调用")
        feedback = build_retry_messages(failed["messages"], "ERROR")[-1].content
        self.assertEqual(feedback, (
            "上一次尝试调用 ExtractionResult，但参数 JSON 解析失败：ERROR。\n"
            "请依据已有材料重新生成完整结果，通过 ExtractionResult 返回。"
            "检查所有对象和数组的闭合，以及属性名的双引号；"
            "每个设计对象的 object_type、data、evidence 必须位于同一层。"
            "完整材料和设计参考已经提供，无须搜索文件。"
        ))
        with_result = malformed_result()
        with_result["structured_response"] = successful_result()["structured_response"]
        self.assertIsNone(get_retry_error(with_result))

    def test_elapsed_time_includes_both_invocations(self):
        self.settings.output_dir.mkdir()
        agent = FakeAgent([malformed_result(), successful_result()])
        instant = datetime(2026, 10, 23, tzinfo=timezone.utc)
        with (
            patch("research_agent.services.execution.perf_counter", side_effect=[10.0, 25.1254]),
            patch("research_agent.services.execution.datetime") as clock,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            clock.now.return_value = instant
            execution = execute_agent(agent, [], self.settings.output_dir, 12)
        self.assertAlmostEqual(execution.elapsed_seconds, 15.1254)
        self.assertEqual(execution.started_at, instant)
        self.assertEqual(execution.finished_at, instant)

    def test_imports_have_no_environment_or_client_side_effects(self):
        script = '''
import importlib
import os
import pkgutil
import socket
import dotenv
import deepagents
import langchain_deepseek

def forbidden(*args, **kwargs):
    raise AssertionError("import caused a side effect")

dotenv.load_dotenv = forbidden
deepagents.create_deep_agent = forbidden
langchain_deepseek.ChatDeepSeek = forbidden
socket.socket.connect = forbidden
original_getenv = os.getenv
def guarded_getenv(name, *args):
    if name in {"DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"}:
        forbidden()
    return original_getenv(name, *args)
os.getenv = guarded_getenv
import main
import research_agent
for module in pkgutil.walk_packages(research_agent.__path__, research_agent.__name__ + "."):
    importlib.import_module(module.name)
assert callable(main.main)
print("imports safe")
'''
        for cwd in (PROJECT_DIR, self.root):
            env = dict(os.environ, PYTHONPATH=str(PROJECT_DIR), PYTHONIOENCODING="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", "-c", script], cwd=cwd, env=env,
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("imports safe", result.stdout)


if __name__ == "__main__":
    unittest.main()
