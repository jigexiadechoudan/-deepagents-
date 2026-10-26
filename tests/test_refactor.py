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

from audit.baseline_engine import run_baseline_engine
from research_agent import workflow
from research_agent.agent.factory import create_extraction_agent
from research_agent.agent.prompts import build_messages, build_retry_messages, build_system_prompt
from research_agent.config import MATERIAL_PATH, PROJECT_DIR, REFERENCE_PATH, Settings, load_settings
from research_agent.schemas.baseline import BaselineManifest, FieldFact
from research_agent.schemas.design import DesignObject, ExtractionResult
from research_agent.services.baseline_generator import BaselineGeneration, self_check_manifest
from research_agent.services.execution import execute_agent
from research_agent.services.materials import load_material, load_reference
from research_agent.services.validation import get_retry_error
from research_agent.services.repair import RepairExecution


MODEL_PARAMS = {
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "timeout": 180,
    "max_retries": 1,
    "max_tokens": 65536,
    "extra_body": {"thinking": {"type": "disabled"}},
}

WINDOWS_SYSTEM_ROOT = os.environ.get("SystemRoot")


class FakeAgent:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def invoke(self, payload, config):
        self.calls.append((payload, config))
        if len(self.calls) > len(self.replies):
            raise AssertionError("发生了未预期的额外 Agent 调用")
        return self.replies[len(self.calls) - 1]

    def stream(self, payload, config, stream_mode=None):
        """适配 execute_agent 的流式执行：整份结果作为一个 values 块返回。"""
        self.calls.append((payload, config))
        if len(self.calls) > len(self.replies):
            raise AssertionError("发生了未预期的额外 Agent 调用")
        return iter([self.replies[len(self.calls) - 1]])


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
                DesignObject(object_type="Page",
                             data={"object_type": "Page", "id": "page_1", "label": "页一"},
                             evidence=["证据"]),
                DesignObject(object_type="Page",
                             data={"object_type": "Page", "id": "page_2", "label": "页二"},
                             evidence=["证据"]),
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
            baseline_mode="off",
        )

    def run_workflow(self, replies, expect_failure=False, extra_patches=None):
        agent = FakeAgent(replies)
        patches = {
            "research_agent.workflow.load_settings": patch(
                "research_agent.workflow.load_settings", return_value=self.settings),
            "research_agent.workflow.create_extraction_agent": patch(
                "research_agent.workflow.create_extraction_agent", return_value=agent),
            "research_agent.workflow.load_skill_files": patch(
                "research_agent.workflow.load_skill_files", return_value={}),
            "research_agent.workflow.inspect_reference_contract": patch(
                "research_agent.workflow.inspect_reference_contract", return_value={
                    "missing_types": [], "unmodeled_types": [], "field_mismatches": [],
                    "field_table": {"status": "matched"}}),
            "research_agent.workflow.repair_extraction": patch(
                "research_agent.workflow.repair_extraction",
                side_effect=lambda candidate, *args, **kwargs: RepairExecution(candidate)),
        }
        patches.update(extra_patches or {})
        with (
            contextlib.ExitStack() as stack,
            contextlib.redirect_stdout(io.StringIO()) as _stdout,
        ):
            for started in patches.values():
                stack.enter_context(started)
            if expect_failure:
                with self.assertRaisesRegex(RuntimeError, "Agent 未返回结构化结果"):
                    workflow.run_extraction()
            else:
                workflow.run_extraction()
        records = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in self.settings.output_dir.glob("*.json")
            if path.name.startswith(("run_", "extraction_", "retry_", "debug_"))
        }
        return agent, records

    def assert_filenames(self, records):
        for name in records:
            self.assertRegex(name, r"^(retry|debug|run|extraction)_\d{8}_\d{6}_\d{6}\.json$")

    def test_default_model_config_and_environment_override(self):
        settings = load_settings()
        self.assertEqual(settings.model_params, MODEL_PARAMS)
        self.assertEqual(settings.recursion_limit, 48)
        self.dotenv.assert_called_once_with(PROJECT_DIR / ".env")
        self.assertNotIn("api_key", settings.model_params)
        with patch.dict(os.environ, {"DEEPSEEK_MODEL": "offline-custom"}):
            self.assertEqual(load_settings().model_params["model"], "offline-custom")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
                load_settings()

    def test_prompts_preserve_reference_material_and_unknown_boundary(self):
        prompt = build_system_prompt("REFERENCE")
        self.assertIn("<design_reference>\n    REFERENCE", prompt)
        self.assertIn("业务推断只放 assumption/openItem", prompt)
        self.assertIn("Artifact 是实际材料或文件", prompt)
        self.assertIn("MATERIAL", build_messages("MATERIAL")[0]["content"])
        self.assertEqual(set(ExtractionResult.model_fields), {"objects", "omissions", "conflicts", "unknowns"})

    def test_schema_enforces_typed_payload(self):
        # 合法类型 + 完整载荷通过（data 内的 object_type 标签与外层一致）
        DesignObject(object_type="Page",
                     data={"object_type": "Page", "id": "page_1", "label": "页"}, evidence=["原文"])
        # 清单外的对象类型被拒绝
        with self.assertRaises(ValidationError):
            DesignObject(object_type="任意类型",
                         data={"object_type": "任意类型", "id": "x"}, evidence=["原文"])
        # 清单外的键（模型发明的字段）被拒绝
        with self.assertRaises(ValidationError):
            DesignObject(object_type="Attribute",
                         data={"object_type": "Attribute", "id": "a", "dataObject": "e",
                               "label": "l", "calcification": None},
                         evidence=["原文"])
        # 词表外的枚举值被拒绝
        with self.assertRaises(ValidationError):
            DesignObject(object_type="FieldView",
                         data={"object_type": "FieldView", "id": "f", "block": "b", "bind": "a",
                               "label": "l", "control": "dropdown"},
                         evidence=["原文"])
        # 缺身份字段被拒绝
        with self.assertRaises(ValidationError):
            DesignObject(object_type="Page", data={"object_type": "Page", "id": "page_2"},
                         evidence=["原文"])
        # data 内缺 object_type 标签被拒绝
        with self.assertRaises(ValidationError):
            DesignObject(object_type="Page", data={"id": "page_2", "label": "页"}, evidence=["原文"])
        # 空证据被拒绝
        with self.assertRaises(ValidationError):
            DesignObject(object_type="Page",
                         data={"object_type": "Page", "id": "page_2", "label": "页"}, evidence=[])
        # 挂载内容按第五章形态校验：纯字符串 constraint 被拒绝
        with self.assertRaises(ValidationError):
            DesignObject(object_type="dataObject",
                         data={"object_type": "dataObject", "id": "e", "label": "表",
                               "constraint": ["纯字符串"]},
                         evidence=["原文"])
        DesignObject(object_type="dataObject",
                     data={"object_type": "dataObject", "id": "e", "label": "表",
                           "constraint": [{"statement": "唯一索引", "blocking": True}]},
                     evidence=["原文"])
        # 标签与外层不一致被拒绝
        with self.assertRaises(ValidationError):
            DesignObject(object_type="Page",
                         data={"object_type": "Block", "id": "x", "page": "p"}, evidence=["原文"])

    def test_factory_preserves_configuration_and_registers_no_new_tools(self):
        with (
            patch("research_agent.agent.factory.ChatDeepSeek") as model,
            patch("research_agent.agent.factory.create_deep_agent") as builder,
        ):
            agent = create_extraction_agent(self.settings, "REFERENCE", "MATERIAL")
        model.assert_called_once_with(**MODEL_PARAMS)
        self.assertIs(agent, builder.return_value)
        kwargs = builder.call_args.kwargs
        self.assertEqual(set(kwargs), {"model", "system_prompt", "response_format", "skills", "middleware"})
        self.assertIs(kwargs["model"], model.return_value)
        self.assertEqual(kwargs["system_prompt"], build_system_prompt("REFERENCE"))
        self.assertIs(kwargs["response_format"].schema, ExtractionResult)
        (mw,) = kwargs["middleware"]
        self.assertEqual(mw.max_rounds, self.settings.max_structured_repair_rounds)
        self.assertFalse(hasattr(mw, "_check_submission"))

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
            {"messages": build_messages(load_material(self.material)),
             "files": {}, "pinned_skills": ["design-model-extraction"]},
            {"recursion_limit": 48}
        ))
        self.assert_filenames(records)
        record = next(value for name, value in records.items() if name.startswith("run_"))
        self.assertTrue({
            "run_id", "status", "started_at", "finished_at", "agent_elapsed_seconds",
            "invalid_tool_call_retry_count", "schema_validation_retry_count", "retry_debug_file",
            "model_params", "recursion_limit",
            "deepagents_version", "skill_version_sha256", "material_chars", "reference_chars", "object_count",
            "object_type_counts", "result_file", "total_completion_tokens", "transcript", "checks",
            "recursion_exhausted", "baseline_check", "baseline_manifest",
            "baseline_manifest_sha256", "baseline_stage",
        } <= set(record))
        self.assertEqual(record["structure_status"], "schema_valid")
        self.assertEqual(record["quality_status"], "needs_review")
        self.assertTrue((self.settings.output_dir / record["candidate_file"]).is_file())
        self.assertTrue((self.settings.output_dir / record["contract_file"]).is_file())
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["invalid_tool_call_retry_count"], 0)
        self.assertIsNone(record["retry_debug_file"])
        self.assertEqual(record["object_type_counts"], {"Page": 2})
        self.assertEqual(record["object_count"], 2)
        self.assertEqual(record["model_params"], MODEL_PARAMS)
        self.assertEqual(record["material_chars"], len(load_material(self.material)))
        self.assertEqual(record["reference_chars"], len(load_reference(self.reference)))
        self.assertIsNotNone(datetime.fromisoformat(record["started_at"]).tzinfo)
        self.assertEqual(records[record["result_file"]],
                         successful_result()["structured_response"].model_dump(by_alias=True, exclude_none=True))
        self.assertEqual(len(records), 2)

    def test_baseline_manifest_roundtrip_from_converted_file(self):
        path = PROJECT_DIR / "baselines" / "八达光电_客户料号映射_smardaten配置方案.json"
        manifest = BaselineManifest.model_validate_json(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest.mainObject.physicalName, "t_sal_customer_material_ref")
        self.assertEqual(len([f for f in manifest.fields if not f.onObject]), 22)   # 主表 22 字段
        self.assertEqual({f.onObject for f in manifest.fields if f.onObject},
                         {"客商档案", "料品档案"})                                  # 档案侧 3 字段
        self.assertEqual(len(manifest.buttons), 9)
        self.assertEqual(BaselineManifest.model_validate(manifest.model_dump()), manifest)
        # 清单只用材料语言：不出现 agent 生成的技术 ID
        self.assertNotIn("attr_cmr_", json.dumps(manifest.model_dump(), ensure_ascii=False))

    def test_baseline_engine_checks_are_manifest_driven(self):
        extraction = {
            "objects": [
                {"object_type": "dataObject",
                 "data": {"object_type": "dataObject", "id": "entity_t", "label": "T表",
                          "physicalName": "t_main"}},
                {"object_type": "Attribute",
                 "data": {"object_type": "Attribute", "id": "attr_a", "dataObject": "entity_t",
                          "label": "客户", "physicalName": "cust_id", "bizType": "text",
                          "primary": True}},
                {"object_type": "Attribute",
                 "data": {"object_type": "Attribute", "id": "attr_b", "dataObject": "entity_t",
                          "label": "备注", "physicalName": "remark", "bizType": "text"}},
            ],
        }
        manifest = {
            "names": {"fields_presence": "主表字段:材料2个物理名全部在场"},
            "mainObject": {"physicalName": "t_main"},
            "fields": [
                {"label": "客户", "physicalName": "cust_id", "type": "text", "primary": True},
                {"label": "停用原因", "physicalName": "stop_reason"},
            ],
        }
        result = run_baseline_engine(extraction, manifest, "材料原文")
        items = {i["check"]: i["status"] for i in result["items"]}
        self.assertEqual(items["主表字段:材料2个物理名全部在场"], "fail")   # stop_reason 缺失
        self.assertEqual(items["主表字段:清单外多出"], "warn")            # remark 多出
        self.assertEqual(items["字段中文名:cust_id"], "pass")
        self.assertEqual(items["类型:cust_id"], "pass")
        self.assertEqual(items["主键:主表仅 cust_id"], "pass")
        self.assertEqual(items["证据:全部逐字命中原文"], "pass")
        self.assertEqual(result["failures"], 1)
        self.assertEqual(result["warnings"], 1)

    def test_generator_self_check_drops_hallucinated_evidence(self):
        manifest = BaselineManifest(fields=[
            FieldFact(label="客户", physicalName="cust_id", evidence=["材料里不存在的句子"]),
            FieldFact(label="备注", physicalName="remark"),
        ])
        clean, report = self_check_manifest(manifest, "真实材料文本，只有这一句。")
        self.assertEqual([f.physicalName for f in clean.fields], ["remark"])
        self.assertTrue(any("fields:cust_id" in d for d in report["dropped"]))
        self.assertTrue(any("fields:remark" in w and "无证据" in w for w in report["warnings"]))

    def test_auto_mode_wires_generated_manifest_into_run_record(self):
        manifest = {"mainObject": {"physicalName": "t_main"}, "fields": []}
        meta = {"source": "auto", "generator_elapsed_seconds": 1.0,
                "self_check": {"dropped": [], "warnings": []},
                "counts": {"fields": 0, "buttons": 0, "option_values": 0,
                           "indexes": 0, "lifecycles": 0}}
        seen = []

        def fake_generator(material, settings):
            seen.append(material)
            return BaselineGeneration(manifest=manifest, meta=meta)

        self.settings.baseline_mode = "auto"
        agent, records = self.run_workflow(
            [successful_result()],
            extra_patches={"research_agent.services.baseline_store.generate_baseline_manifest":
                           patch("research_agent.services.baseline_store.generate_baseline_manifest", fake_generator)},
        )
        self.assertEqual(seen, [load_material(self.material)])
        self.assertEqual(len(agent.calls), 1)
        record = next(value for name, value in records.items() if name.startswith("run_"))
        self.assertEqual(record["baseline_manifest"], manifest)
        self.assertEqual(record["baseline_stage"]["source"], "auto")
        self.assertEqual(
            record["baseline_manifest_sha256"],
            hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True)
                           .encode("utf-8")).hexdigest(),
        )
        self.assertIsNotNone(record["baseline_check"])
        # 2 个对象各有 1 条证据回链失败：汇总 1 条 + 逐对象 2 条
        self.assertEqual(record["baseline_check"]["failures"], 3)

    def test_baseline_engine_required_existence_checks(self):
        base_objects = [
            {"object_type": "dataObject",
             "data": {"object_type": "dataObject", "id": "entity_cmr", "label": "客户料号对照",
                      "physicalName": "t_main"}},
        ]
        manifest = {
            "relations": [{"matchLabel": "装车", "cardinality": "manyToOne"}],
            "fields": [
                {"label": "客户名称", "physicalName": "customer_name", "onObject": "客商档案"},
            ],
        }
        # 静默缺失：关系与档案字段都没有 → 双 fail
        result = run_baseline_engine({"objects": base_objects}, manifest, "材料")
        items = {(i["check"], i["status"]) for i in result["items"]}
        self.assertIn(("关系必建:装车", "fail"), items)
        self.assertIn(("对象字段:客商档案", "fail"), items)
        # 已在 omissions 声明缺口 → 关系降级为 warn
        declared = {"objects": base_objects,
                    "omissions": ["装车单明细对象不在本轮材料范围，关系无法落端点"]}
        result = run_baseline_engine(declared, manifest, "材料")
        items = {(i["check"], i["status"]) for i in result["items"]}
        self.assertIn(("关系必建:装车", "warn"), items)
        # 承接在场（partial 定义也算）→ 不出条目
        carried = {"objects": base_objects + [
            {"object_type": "Relation",
             "data": {"object_type": "Relation", "id": "rel_x", "label": "对照 → 装车单行",
                      "from": {"dataObject": "entity_cmr"},
                      "to": {"dataObject": "entity_cmr"}, "cardinality": "manyToOne"}},
            {"object_type": "dataObject",
             "data": {"object_type": "dataObject", "id": "entity_arch", "label": "客商档案"}},
            {"object_type": "Attribute",
             "data": {"object_type": "Attribute", "id": "attr_cn", "dataObject": "entity_arch",
                      "label": "客户名称", "physicalName": "customer_name", "bizType": "text"}},
        ]}
        result = run_baseline_engine(carried, manifest, "材料")
        items = {(i["check"], i["status"]) for i in result["items"]}
        self.assertNotIn(("关系必建:装车", "fail"), items)
        self.assertNotIn(("关系必建:装车", "warn"), items)
        self.assertNotIn(("对象字段:客商档案", "fail"), items)

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
        self.assertEqual(history[:-1], failed["messages"][:1])
        self.assertIsInstance(history[-1], HumanMessage)
        self.assertIn(retry["error"], history[-1].content)
        self.assertFalse(any(isinstance(m, ToolMessage) for m in history))
        self.assertFalse(any(isinstance(m, AIMessage) and m.invalid_tool_calls for m in history))
        self.assertEqual(agent.calls[1][1], {"recursion_limit": 48})
        self.assert_filenames(records)

    def test_second_failure_stops_and_preserves_final_diagnostic(self):
        agent, records = self.run_workflow([malformed_result(), malformed_result()], expect_failure=True)
        self.assertEqual(len(agent.calls), 2)
        self.assertEqual(len(records), 2)
        debug = next(value for name, value in records.items() if name.startswith("debug_"))
        self.assertEqual(set(debug), {
            "run_id", "status", "reason", "started_at", "finished_at", "agent_elapsed_seconds",
            "invalid_tool_call_retry_count", "retry_debug_file", "recursion_exhausted", "messages",
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
                execution = execute_agent(agent, [], self.settings.output_dir, 12, {})
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
            execution = execute_agent(agent, [], self.settings.output_dir, 12, {})
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
            # Windows 的 Winsock/DLL 初始化需要此项；setUp 清空环境仅用于隔离密钥。
            if WINDOWS_SYSTEM_ROOT:
                env["SystemRoot"] = WINDOWS_SYSTEM_ROOT
            result = subprocess.run(
                [sys.executable, "-B", "-c", script], cwd=cwd, env=env,
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("imports safe", result.stdout)


if __name__ == "__main__":
    unittest.main()
