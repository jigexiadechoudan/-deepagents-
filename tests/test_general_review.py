"""通用回归：多对象/同名主体/未知/合法自关联，全部离线，不调用 main。"""

import unittest
from copy import deepcopy
from unittest.mock import patch

from audit.baseline_engine import run_baseline_engine
from research_agent.schemas.baseline import FieldFact, MaterialFact, MaterialManifest, RelationFact
from research_agent.services.baseline_generator import self_check_manifest, parse_manifest_response
from research_agent.services.checks import (check_model_relations, check_option_source_dedup,
                                          check_conditional_readonly, check_delete_policy_support, run_checks)
from langchain.messages import AIMessage
from research_agent.config import Settings
from research_agent.schemas.design import ExtractionResult
from research_agent.schemas.repair import ExtractionRepair
from research_agent.services.repair import repair_extraction, merge_repair


def obj(object_type, oid, **data):
    return {"object_type": object_type, "data": {"object_type": object_type, "id": oid, **data}, "evidence": ["来源"]}


def review(objects, fact, material):
    return run_baseline_engine({"objects": objects},
                               MaterialManifest(facts=[MaterialFact(**fact)]).model_dump(), material)


class GeneralReviewTests(unittest.TestCase):
    def test_unknown_primary_and_cardinality_are_not_false_or_candidates(self):
        self.assertIsNone(FieldFact(label="编号", physicalName="code").primary)
        self.assertIsNone(RelationFact(matchLabel="所属部门").cardinality)

    def test_manifest_only_moves_unambiguous_misplaced_property(self):
        payload = {"facts": [{"kind": "service", "subject": "接口",
                              "scope": {"property": "inputs"}, "expected": ["code"]}]}
        raw = AIMessage(content="", tool_calls=[{"name": "MaterialManifest", "args": payload, "id": "call"}])
        parsed, records = parse_manifest_response({"raw": raw, "parsed": None})
        self.assertEqual(parsed.facts[0].property, "inputs")
        self.assertEqual(len(records), 1)
        payload["facts"][0]["property"] = "outputs"
        raw = AIMessage(content="", tool_calls=[{"name": "MaterialManifest", "args": payload, "id": "call"}])
        parsed, events = parse_manifest_response({"raw": raw, "parsed": None})
        self.assertEqual(parsed.facts, [])
        self.assertEqual(events[0]["kind"], "review")
        self.assertIn("冲突", events[0]["reason"])

    def test_composite_expected_values_are_retained_for_review(self):
        source = "状态：值1 标签生效；值0 标签停用。"
        fact = MaterialFact(kind="field_view", subject="状态", property="options",
                            expected=[{"value": "1", "label": "生效"}, {"value": "0", "label": "停用"}],
                            evidence=[source])
        clean, _ = self_check_manifest(MaterialManifest(facts=[fact]), source)
        self.assertEqual(clean.facts[0].expected, fact.expected)
        self.assertEqual(clean.facts[0].verification, "review")

    def test_one_malformed_fact_does_not_discard_valid_facts(self):
        payload = {"protocol_version": 2, "facts": [
            {"kind": "attribute", "subject": "编号", "evidence": ["编号"]},
            {"kind": "invented_kind", "subject": "坏条目"}]}
        raw = AIMessage(content=__import__('json').dumps(payload, ensure_ascii=False))
        parsed, events = parse_manifest_response({"raw": raw, "parsed": None})
        self.assertEqual(len(parsed.facts), 1)
        self.assertEqual(events[0]["fact"]["subject"], "坏条目")

    def test_unconditional_readonly_cannot_override_its_own_conditions(self):
        objects = [obj("FieldView", "f", readonly=True, note=[{
            "statement": "编辑态禁用（编辑加载设置，新增态可填）。"}])]
        self.assertEqual(check_conditional_readonly(objects)[0]["severity"], "error")
        objects[0]["data"]["readonly"] = None
        self.assertEqual(check_conditional_readonly(objects), [])

    def test_readonly_does_not_prove_delete_restrict(self):
        objects = [obj("Relation", "r", onDelete="restrict")]
        objects[0]["evidence"] = ["只读引用"]
        self.assertEqual(check_delete_policy_support(objects)[0]["severity"], "warning")
        objects[0]["evidence"] = ["引用存在时禁止删除"]
        self.assertEqual(check_delete_policy_support(objects), [])

    def test_explicit_absence_does_not_become_a_presence_requirement(self):
        source = "业务流：无"
        result = review([obj("Process", "p", name="业务流")], {
            "kind": "object", "subject": "业务流", "evidence": [source]}, source)
        self.assertEqual(result["coverage"], {"review": 1})
        self.assertEqual(result["passed"], 0)

    def test_all_evidence_is_checked_and_positions_are_calculated(self):
        source = "请假单\n编号 code 必填。\n编号 code 必填。"
        clean, report = self_check_manifest(MaterialManifest(facts=[MaterialFact(
            kind="attribute", subject="code", evidence=["编号 code 必填。"], verification="review"
        )]), source)
        self.assertEqual(clean.facts[0].verification, "literal")
        self.assertEqual([span.line for span in clean.facts[0].locations], [2, 3])
        self.assertEqual(report["review_required"], 0)
        clean, _ = self_check_manifest(MaterialManifest(facts=[MaterialFact(
            kind="attribute", subject="code", evidence=["编号 code 必填。", "不存在的证据"]
        )]), source)
        self.assertEqual(clean.facts[0].verification, "review")

    def test_quote_existence_does_not_prove_primary(self):
        result = review([obj("Attribute", "a", label="编号", primary=True)], {
            "kind": "attribute", "subject": "编号", "property": "primary", "expected": True,
            "evidence": ["编号用于查找，不是主键。"]}, "编号用于查找，不是主键。")
        self.assertEqual(result["coverage"], {"review": 1})
        self.assertEqual(result["failures"], 0)

    def test_forged_verification_and_locations_are_ignored(self):
        result = review([], {"kind": "attribute", "subject": "编号", "property": "primary",
                            "expected": True, "verification": "literal",
                            "locations": [{"start": 0, "end": 2, "line": 1}],
                            "evidence": ["假原文"]}, "真实原文")
        self.assertEqual(result["items"][0]["coverage"], "review")
        self.assertEqual(result["items"][0]["locations"], [])

    def test_multi_object_same_physical_field_is_scoped(self):
        objects = [obj("dataObject", "a", label="请假单"), obj("dataObject", "b", label="报销单"),
                   obj("Attribute", "aa", dataObject="a", label="编号", physicalName="code", primary=True),
                   obj("Attribute", "bb", dataObject="b", label="编号", physicalName="code", primary=False)]
        fact = {"kind": "attribute", "subject": "code", "scope": {"object": "请假单"},
                "property": "primary", "expected": True, "evidence": ["请假单 code 为主键。"]}
        result = review(objects, fact, "请假单 code 为主键。")
        self.assertEqual(result["items"][0]["object_id"], "aa")
        self.assertEqual(result["passed"], 1)
        fact["scope"] = {}
        self.assertEqual(review(objects, fact, "请假单 code 为主键。")["coverage"], {"review": 1})

    def test_same_button_on_two_form_pages_does_not_cross_match(self):
        objects = [obj("Page", "p1", label="请假表单", kind="form"),
                   obj("Page", "p2", label="报销表单", kind="form"),
                   obj("Action", "a1", label="保存", page="p1", refreshOnReturn=False),
                   obj("Action", "a2", label="保存", page="p2", refreshOnReturn=True)]
        fact = {"kind": "action", "subject": "保存", "scope": {"page": "请假表单"},
                "property": "exists", "evidence": ["请假表单有保存按钮。"]}
        result = review(objects, fact, "请假表单有保存按钮。")
        self.assertEqual(result["items"][0]["object_id"], "a1")
        fact["scope"] = {"pageKind": "form"}
        self.assertEqual(review(objects, fact, "请假表单有保存按钮。")["coverage"], {"review": 1})

    def test_false_and_zero_are_not_missing(self):
        objects = [obj("FieldView", "f", label="备注", required=False, defaultValue=0)]
        source = "备注非必填，默认值0。"
        for prop, expected in [("required", False), ("defaultValue", 0)]:
            result = review(objects, {"kind": "field_view", "subject": "备注", "property": prop,
                                      "expected": expected, "evidence": [source]}, source)
            self.assertEqual(result["passed"], 1)

    def test_notes_count_as_covered_but_evidence_only_does_not(self):
        source = "状态默认值为生效。"
        fact = {"kind": "field_view", "subject": "状态", "property": "defaultValue",
                "expected": "生效", "evidence": [source]}
        objects = [obj("FieldView", "f", label="状态", note=[{"statement": source}])]
        self.assertEqual(review(objects, fact, source)["coverage"], {"text": 1})
        objects[0]["data"].pop("note")
        objects[0]["evidence"] = [source]
        self.assertEqual(review(objects, fact, source)["coverage"], {"uncovered": 1})

    def test_conflicting_value_is_not_hidden_by_correct_notes(self):
        source = "状态默认值为生效。"
        result = review([obj("FieldView", "f", label="状态", defaultValue="停用",
                             note=[{"statement": source}])], {
            "kind": "field_view", "subject": "状态", "property": "defaultValue",
            "expected": "生效", "evidence": [source]}, source)
        self.assertEqual(result["coverage"], {"conflict": 1})
        self.assertEqual(result["failures"], 1)

    def test_default_label_mapping_uses_only_its_option_set(self):
        source = "状态默认值为生效。"
        objects = [obj("FieldView", "f", label="状态", defaultValue="1", optionSource="s"),
                   obj("Option", "o1", label="生效", value="1", optionSource="s"),
                   obj("Option", "o2", label="停用", value="1", optionSource="other")]
        fact = {"kind": "field_view", "subject": "状态", "property": "defaultValue",
                "expected": "生效", "evidence": [source]}
        self.assertEqual(review(objects, fact, source)["passed"], 1)
        objects[1]["data"]["optionSource"] = "other"
        self.assertEqual(review(objects, fact, source)["failures"], 1)

    def test_unknown_cardinality_is_not_an_error(self):
        source = "部门引用负责人，未说明基数。"
        objects = [obj("Relation", "r", label="负责人", cardinality=None)]
        fact = {"kind": "relation", "subject": "负责人", "property": "cardinality",
                "expected": None, "state": "unknown", "evidence": [source]}
        self.assertEqual(review(objects, fact, source)["coverage"], {"not_checked": 1})
        objects[0]["data"]["cardinality"] = "manyToOne"
        self.assertEqual(review(objects, fact, source)["coverage"], {"review": 1})

    def test_lifecycle_does_not_use_another_pages_text(self):
        source = "申请表单加载时隐藏原因。"
        objects = [obj("Page", "p1", label="申请表单", kind="form"),
                   obj("Page", "p2", label="复核表单", kind="form", openLogic=[source])]
        fact = {"kind": "lifecycle", "subject": "原因", "scope": {"page": "申请表单"},
                "property": "openLogic", "expected": "隐藏原因", "evidence": [source]}
        self.assertEqual(review(objects, fact, source)["coverage"], {"uncovered": 1})

    def test_real_self_relation_is_allowed_but_wrong_owner_is_rejected(self):
        objects = [obj("dataObject", "e", label="组织"),
                   obj("Attribute", "a", dataObject="e", label="上级编号"),
                   obj("Relation", "r", label="上级组织", **{
                       "from": {"dataObject": "e", "attribute": "a"},
                       "to": {"dataObject": "e", "attribute": "a"}})]
        self.assertEqual(check_model_relations(objects), [])
        objects[1]["data"]["dataObject"] = "other"
        self.assertTrue(any("不属于端点" in v["message"] for v in check_model_relations(objects)))

    def test_wrong_reference_type_and_action_page_are_detected(self):
        objects = [obj("Feature", "f", name="功能"),
                   obj("Relation", "r", **{"from": {"dataObject": "f"}, "to": {"dataObject": "f"}}),
                   obj("Block", "b", page="p1"), obj("Action", "a", block="b", page="p2")]
        violations = check_model_relations(objects)
        self.assertTrue(any("引用类型错误" in v["message"] for v in violations))
        self.assertTrue(any("Action.page" in v["message"] for v in violations))

    def test_different_filters_are_not_duplicate_sources(self):
        objects = [obj("OptionSource", "s1", kind="reference", valueAttribute="a", filterNote="启用"),
                   obj("OptionSource", "s2", kind="reference", valueAttribute="a", filterNote="全部")]
        self.assertEqual(check_option_source_dedup(objects), [])
        objects[1]["data"]["filterNote"] = "启用"
        self.assertTrue(all(v["severity"] == "warning" for v in check_option_source_dedup(objects)))

    def test_empty_or_bad_manifest_does_not_prove_coverage(self):
        result = run_baseline_engine({"objects": []}, MaterialManifest().model_dump(), "材料")
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["source_review"]["review_required"], 1)
        self.assertEqual(result["business_completeness"], "not_proven")

    def repair_fixture(self, value):
        source = "状态默认值为生效。"
        objects = [obj("dataObject", "e", label="档案"),
                   obj("Attribute", "a", label="状态", dataObject="e"),
                   obj("Page", "p", label="表单", kind="form"),
                   obj("Block", "b", page="p", dataObject="e"),
                   obj("FieldView", "f", label="状态", bind="a", block="b")]
        for item in objects:
            item["evidence"] = [source]
        if value is None:
            objects[-1]["data"]["note"] = [{"statement": source}]
        else:
            objects[-1]["data"]["defaultValue"] = value
        candidate = ExtractionResult.model_validate({"objects": objects, "omissions": [], "conflicts": [], "unknowns": []})
        manifest = MaterialManifest(facts=[MaterialFact(kind="field_view", subject="状态",
            property="defaultValue", expected="生效", evidence=[source])]).model_dump()
        return candidate, manifest, source

    def test_repair_ignores_covered_text_warning(self):
        candidate, manifest, source = self.repair_fixture(None)
        with patch("research_agent.services.repair.ChatDeepSeek") as model:
            result = repair_extraction(candidate, Settings(model_params={}), source, "", {}, manifest)
        model.assert_not_called()
        self.assertEqual(result.records, [])

    def test_unchanged_candidate_is_checked_once_even_with_zero_repair_rounds(self):
        for rounds, value in ((2, "生效"), (0, "停用")):
            with self.subTest(rounds=rounds):
                candidate, manifest, source = self.repair_fixture(value)
                expected_checks = run_checks(candidate.model_dump(by_alias=True, exclude_none=True), source)
                expected_baseline = run_baseline_engine(
                    candidate.model_dump(by_alias=True, exclude_none=True), manifest, source)
                with (
                    patch("research_agent.services.repair.run_checks", wraps=run_checks) as checks,
                    patch("research_agent.services.repair.run_baseline_engine", wraps=run_baseline_engine) as baseline,
                    patch("research_agent.services.repair.ChatDeepSeek") as model,
                ):
                    result = repair_extraction(candidate, Settings(model_params={}, max_check_rounds=rounds),
                                               source, "", {}, manifest)
                checks.assert_called_once()
                baseline.assert_called_once()
                model.assert_not_called()
                self.assertIs(result.extraction, candidate)
                self.assertEqual(result.checks, expected_checks)
                self.assertEqual(result.baseline, expected_baseline)
                self.assertEqual(result.records, [])

    def test_missing_manifest_returns_none_without_baseline_check(self):
        candidate, _, source = self.repair_fixture("生效")
        with (
            patch("research_agent.services.repair.run_checks", wraps=run_checks) as checks,
            patch("research_agent.services.repair.run_baseline_engine") as baseline,
            patch("research_agent.services.repair.ChatDeepSeek") as model,
        ):
            result = repair_extraction(candidate, Settings(model_params={}), source, "", {}, None)
        checks.assert_called_once()
        baseline.assert_not_called()
        model.assert_not_called()
        self.assertIsNone(result.baseline)

    def test_local_repair_is_merged_and_new_broken_reference_rolls_back(self):
        candidate, manifest, source = self.repair_fixture("停用")
        for broken in (False, True):
            replacement = candidate.objects[-1].model_dump(by_alias=True, exclude_none=True)
            replacement["data"]["defaultValue"] = "生效"
            fields = ["data.defaultValue"]
            if broken:
                replacement["data"]["bind"] = "missing_attribute"
                fields.append("data.bind")
            revision = ExtractionRepair.model_validate({"replacements": [{
                "target_id": "f", "replacement": replacement, "changed_fields": fields,
                "reason": "按原文明示默认值修正", "evidence": [source]}]})
            with (
                patch("research_agent.services.repair.ChatDeepSeek") as model,
                patch("research_agent.services.repair.run_checks", wraps=run_checks) as checks,
                patch("research_agent.services.repair.run_baseline_engine", wraps=run_baseline_engine) as baseline,
            ):
                model.return_value.with_structured_output.return_value.invoke.return_value = {"parsed": revision}
                result = repair_extraction(candidate, Settings(model_params={}, max_check_rounds=2),
                                           source, "", {}, manifest)
            attempts = 2 if broken else 1
            self.assertEqual(len(result.records), attempts)
            self.assertEqual(checks.call_count, 1 + attempts)
            self.assertEqual(baseline.call_count, 1 + attempts)
            self.assertEqual(result.checks, run_checks(result.extraction.model_dump(by_alias=True, exclude_none=True), source))
            self.assertEqual(result.baseline, run_baseline_engine(
                result.extraction.model_dump(by_alias=True, exclude_none=True), manifest, source))
            self.assertEqual(result.records[0]["accepted"], not broken)
            self.assertEqual(result.extraction.objects[-1].data.defaultValue, "停用" if broken else "生效")
            self.assertEqual([o.data.id for o in result.extraction.objects], [o.data.id for o in candidate.objects])

    def test_rejected_second_patch_keeps_last_accepted_candidate_and_checks(self):
        candidate, manifest, source = self.repair_fixture("停用")
        payload = candidate.model_dump(by_alias=True, exclude_none=True)
        payload["objects"][2]["data"]["pageGroup"] = "missing_group"
        candidate = ExtractionResult.model_validate(payload)
        fixed = candidate.objects[-1].model_dump(by_alias=True, exclude_none=True)
        fixed["data"]["defaultValue"] = "生效"
        broken = deepcopy(fixed)
        broken["data"]["bind"] = "missing_attribute"
        revisions = [ExtractionRepair.model_validate({"replacements": [{
            "target_id": "f", "replacement": replacement, "changed_fields": [field],
            "reason": "按原文修正", "evidence": [source]}]})
            for replacement, field in ((fixed, "data.defaultValue"), (broken, "data.bind"))]
        with (
            patch("research_agent.services.repair.run_checks", wraps=run_checks) as checks,
            patch("research_agent.services.repair.run_baseline_engine", wraps=run_baseline_engine) as baseline,
            patch("research_agent.services.repair.ChatDeepSeek") as model,
        ):
            model.return_value.with_structured_output.return_value.invoke.side_effect = [
                {"parsed": revision} for revision in revisions]
            result = repair_extraction(candidate, Settings(model_params={}, max_check_rounds=2),
                                       source, "", {}, manifest)
        self.assertEqual([row["accepted"] for row in result.records], [True, False])
        self.assertEqual(checks.call_count, 3)
        self.assertEqual(baseline.call_count, 3)
        self.assertEqual(result.extraction.objects[-1].data.defaultValue, "生效")
        self.assertEqual(result.extraction.objects[-1].data.bind, "a")
        self.assertEqual(result.baseline["coverage"], {"structured": 1})
        self.assertEqual(result.checks, run_checks(result.extraction.model_dump(by_alias=True, exclude_none=True), source))

    def test_invalid_repair_response_reuses_original_check_results(self):
        candidate, manifest, source = self.repair_fixture("停用")
        with (
            patch("research_agent.services.repair.run_checks", wraps=run_checks) as checks,
            patch("research_agent.services.repair.run_baseline_engine", wraps=run_baseline_engine) as baseline,
            patch("research_agent.services.repair.ChatDeepSeek") as model,
        ):
            model.return_value.with_structured_output.return_value.invoke.return_value = {
                "parsed": None, "parsing_error": "invalid JSON"}
            result = repair_extraction(candidate, Settings(model_params={}, max_check_rounds=2),
                                       source, "", {}, manifest)
        checks.assert_called_once()
        baseline.assert_called_once()
        self.assertIs(result.extraction, candidate)
        self.assertEqual(len(result.records), 2)
        self.assertTrue(all(not row["accepted"] for row in result.records))
        self.assertEqual(result.baseline["coverage"], {"conflict": 1})

    def test_undeclared_repair_field_change_is_rejected(self):
        candidate, _, source = self.repair_fixture("停用")
        replacement = candidate.objects[-1].model_dump(by_alias=True, exclude_none=True)
        replacement["data"]["defaultValue"] = "生效"
        replacement["data"]["label"] = "改名"
        revision = ExtractionRepair.model_validate({"replacements": [{
            "target_id": "f", "replacement": replacement, "changed_fields": ["data.defaultValue"],
            "reason": "修正默认值", "evidence": [source]}]})
        with self.assertRaisesRegex(ValueError, "changed_fields"):
            merge_repair(candidate, revision, source)

    def test_repair_cannot_turn_text_coverage_into_missing_information(self):
        candidate, manifest, source = self.repair_fixture("停用")
        extra = "状态由主管审批。"
        payload = candidate.model_dump(by_alias=True, exclude_none=True)
        payload["objects"][-1]["data"]["note"] = [{"statement": extra}]
        candidate = ExtractionResult.model_validate(payload)
        manifest["facts"].append(MaterialFact(kind="field_view", subject="状态",
            property="calculation", expected="主管审批", evidence=[extra]).model_dump())
        replacement = candidate.objects[-1].model_dump(by_alias=True, exclude_none=True)
        replacement["data"]["defaultValue"] = "生效"
        replacement["data"].pop("note")
        revision = ExtractionRepair.model_validate({"replacements": [{
            "target_id": "f", "replacement": replacement,
            "changed_fields": ["data.defaultValue", "data.note"],
            "reason": "修正默认值", "evidence": [source]}]})
        with patch("research_agent.services.repair.ChatDeepSeek") as model:
            model.return_value.with_structured_output.return_value.invoke.return_value = {"parsed": revision}
            result = repair_extraction(candidate, Settings(model_params={}, max_check_rounds=1),
                                       source + extra, "", {}, manifest)
        self.assertFalse(result.records[0]["accepted"])
        self.assertEqual(result.extraction.objects[-1].data.note[0].statement, extra)


if __name__ == "__main__":
    unittest.main()
