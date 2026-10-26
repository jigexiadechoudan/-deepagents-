"""定向回归：断链补建范围，以及 Schema 局部重试保留完整候选；不调用模型。"""

import unittest
from copy import deepcopy
from types import SimpleNamespace

from langchain.agents.middleware import ModelResponse
from langchain.messages import AIMessage

from research_agent.agent.middleware import StructuredOutputRepairMiddleware
from research_agent.schemas.repair import ExtractionRepair
from research_agent.schemas.typed import ExtractionResult
from research_agent.services.checks import run_checks
from research_agent.services.repair import _issues, _repair_scope, merge_repair


def obj(kind, oid, **fields):
    return {"object_type": kind, "data": {"object_type": kind, "id": oid, **fields},
            "evidence": ["来源"]}


def result(objects, **reports):
    return {"objects": objects, "omissions": [], "conflicts": [], "unknowns": [], **reports}


def message(payload, call_id):
    return AIMessage(content="", tool_calls=[{"name": "ExtractionResult", "args": payload,
                                             "id": call_id}])


class RetryRetentionTests(unittest.TestCase):
    def test_new_id_is_allowed_when_repairing_description_reference(self):
        candidate = ExtractionResult.model_validate(result([
            obj("Automation", "auto_import", actions=["导入后更新来源"])]))
        scope = _repair_scope(candidate, _issues(run_checks(candidate.model_dump(by_alias=True), "来源"), None))
        patch = ExtractionRepair.model_validate({"replacements": [{
            "target_id": "auto_import", "replacement": obj("Automation", "auto_import", actions=["act_mark"]),
            "changed_fields": ["data.actions"], "reason": "改用动作引用", "evidence": ["来源"]}],
            "additions": [obj("Action", "act_mark", label="更新来源")]})
        merged = merge_repair(candidate, patch, "来源", scope)
        self.assertEqual(len(merged.objects), 2)
        self.assertFalse([v for v in run_checks(merged.model_dump(by_alias=True), "来源") if v["severity"] == "error"])
        patch.additions.append(patch.additions[0].model_copy(deep=True))
        patch.additions[-1].data.id = "act_unrelated"
        with self.assertRaisesRegex(ValueError, "未被本轮断链字段"):
            merge_repair(candidate, patch, "来源", scope)

    def test_evidence_only_scope_does_not_allow_additions(self):
        candidate = ExtractionResult.model_validate(result([obj("Project", "proj_test")]))
        scope = {"replacements": {"proj_test": ["evidence"]}, "additions": [], "report_changes": []}
        patch = ExtractionRepair.model_validate({"additions": [obj("Action", "act_extra", label="动作")]})
        with self.assertRaises(ValueError):
            merge_repair(candidate, patch, "来源", scope)

    def test_missing_endpoint_allows_minimal_target_and_related_explanation(self):
        before = obj("Relation", "rel_test", **{"from": {"dataObject": "entity_source"}, "to": None})
        candidate = ExtractionResult.model_validate(result([
            obj("dataObject", "entity_source", label="源对象"), before]))
        scope = _repair_scope(candidate, _issues(run_checks(candidate.model_dump(by_alias=True), "来源"), None))
        after = deepcopy(before)
        after["data"]["to"] = {"dataObject": "entity_target"}
        after["data"]["openItem"] = [{"statement": "目标对象字段未说明"}]
        patch = ExtractionRepair.model_validate({"replacements": [{
            "target_id": "rel_test", "replacement": after,
            "changed_fields": ["data.to", "data.openItem"], "reason": "补齐材料提及的端点", "evidence": ["来源"]}],
            "additions": [obj("dataObject", "entity_target", label="目标对象")]})
        merged = merge_repair(candidate, patch, "来源", scope)
        self.assertEqual(len(merged.objects), 3)
        self.assertFalse([v for v in run_checks(merged.model_dump(by_alias=True), "来源") if v["severity"] == "error"])

    def test_unchanged_format_warning_does_not_block_corrected_evidence(self):
        before = obj("Project", "proj_test")
        before["evidence"] = ["来 源", "错误引文"]
        after = deepcopy(before)
        after["evidence"] = ["来 源", "来源"]
        candidate = ExtractionResult.model_validate(result([before]))
        patch = ExtractionRepair.model_validate({"replacements": [{
            "target_id": "proj_test", "replacement": after, "changed_fields": ["evidence"],
            "reason": "纠正错误引文", "evidence": ["来源"]}]})
        merged = merge_repair(candidate, patch, "来源")
        checks = run_checks(merged.model_dump(), "来源")
        self.assertFalse([v for v in checks if v["severity"] == "error"])
        self.assertTrue(any(v["rule_code"] == "evidence.format" for v in checks))
        patch.replacements[0].replacement.evidence.append("新造引文")
        with self.assertRaisesRegex(ValueError, "逐字命中"):
            merge_repair(candidate, patch, "来源")

    def retry(self, previous, submitted):
        middleware = StructuredOutputRepairMiddleware()
        current = message(submitted, "retry")
        try:
            parsed = ExtractionResult.model_validate(submitted)
        except ValueError:
            parsed = None
        response = middleware.wrap_model_call(
            SimpleNamespace(messages=[message(previous, "initial")]),
            lambda request: ModelResponse(result=[current], structured_response=parsed))
        return response, middleware.model_calls[-1]

    def test_single_corrected_object_retains_other_objects_and_reports(self):
        good = obj("DataService", "svc_mark")
        bad = deepcopy(good)
        bad["data"]["explanation"] = None
        previous = result([obj("Project", "proj_test"), bad], unknowns=["材料未明确参数类型"])
        response, record = self.retry(previous, result([good]))
        self.assertEqual([o.data.id for o in response.structured_response.objects], ["proj_test", "svc_mark"])
        self.assertEqual(response.structured_response.unknowns, previous["unknowns"])
        self.assertEqual(record["submitted_object_count"], 1)
        self.assertEqual(record["retained_object_count"], 2)
        self.assertIn("explanation", previous["objects"][1]["data"])

    def test_unfixed_object_cannot_be_omitted_to_pass_schema(self):
        previous = result([obj("Project", "proj_test"), obj("DataService", "svc_bad", explanation=None)])
        response, _ = self.retry(previous, result([previous["objects"][0]]))
        self.assertIsNone(response.structured_response)
        self.assertEqual(len(response.result[0].tool_calls[0]["args"]["objects"]), 2)

    def test_renamed_partial_retry_is_rejected_without_losing_candidate(self):
        previous = result([obj("Project", "proj_test"), obj("DataService", "svc_bad", explanation=None)])
        response, record = self.retry(previous, result([obj("DataService", "svc_renamed")]))
        self.assertIsNone(response.structured_response)
        self.assertEqual(record["schema_retry_mode"], "rejected_partial")
        self.assertEqual(response.result[0].tool_calls[0]["args"], previous)


if __name__ == "__main__":
    unittest.main()
