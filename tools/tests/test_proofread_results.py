from __future__ import annotations

import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from proofread_packets import (  # noqa: E402
    initialize_manifest, prepare_session, sha256_file, source_context, write_new_artifacts,
)
from proofread_results import (  # noqa: E402
    assemble_result, coverage_summary, validate_data, validate_result,
)


class ProofreadResultsTests(unittest.TestCase):
    """Exercise frozen inputs and real citations, not a mocked validator."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "review-run"
        self.root.mkdir()
        self.jp = self.base / "jp-source"
        self.cn = self.base / "cn-source"
        self.jp.mkdir()
        self.cn.mkdir()
        self.filename = "S3_01-03.xhtml"
        self.jp_file = self.jp / self.filename
        jp_lines = [f"<p>隣接する第{i}行。</p>" for i in range(1, 15)]
        jp_lines[7] = '<p>彼は<ruby>魔術<rt>まじゅつ</rt></ruby>を使った。</p>'
        jp_lines[8] = "<p>二人は来なかった。</p>"
        self.jp_file.write_text("\n".join(jp_lines) + "\n", encoding="utf-8")
        cn_lines = [f"<p>邻接第{i}行。</p>" for i in range(1, 15)]
        cn_lines[7], cn_lines[8] = "<p>他使用了魔法。</p>", "<p>两人都没来。</p>"
        (self.cn / "S3_01-03_Chapter1.xhtml").write_text(
            "\n".join(cn_lines) + "\n", encoding="utf-8")
        fields = ("commit", "work", "file", "line", "old", "new", "grade")
        self.changes = [
            dict(zip(fields, ("HEAD", "S3_01", "S3_01-03_Chapter1.xhtml", "8",
                              "他没有使用魔法。", "他使用了魔法。", "local"))),
            dict(zip(fields, ("HEAD", "S3_01", "S3_01-03_Chapter1.xhtml", "9",
                              "两人都来了。", "两人都没来。", "local"))),
        ]
        with (self.root / "changes.tsv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fields, delimiter="\t")
            writer.writeheader()
            writer.writerows(self.changes)
        initialize_manifest(self.root, apply=True)
        plan = self.root / "plan.json"
        self.write_json(plan, {"slices": [{"slice_id": "risk-01", "item_ids": ["C000001", "C000002"]}]})
        prepare_session(self.root, jp_base=self.jp, cn_base=self.cn, plan_path=plan, apply=True)
        self.draft = {
            "items": [
                {"item_id": "C000001", "decision": "保留新译",
                 "reason": "原文使用肯定动词使った，支持新译。", "proposed_cn": None, "original_fix": None},
                {"item_id": "C000002", "decision": "保留新译",
                 "reason": "来なかった为否定，支持新译。", "proposed_cn": None, "original_fix": None},
            ], "discoveries": [],
        }
        self.decisions = self.root / "decisions.json"

    @staticmethod
    def write_json(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def assemble(self, *, apply=False, attempt=1, revision=0):
        self.write_json(self.decisions, self.draft)
        return assemble_result(self.root, "risk-01", self.decisions, apply=apply,
                               attempt=attempt, revision=revision)

    def result_path(self, suffix="a1"):
        return self.root / "slices" / f"risk-01.{suffix}.json"

    def selected(self, relative="slices/risk-01.a1.json"):
        path = self.root / "selection.json"
        self.write_json(path, {"risk-01": relative} if relative is not None else {})
        return coverage_summary(self.root, path)

    def test_explicit_decisions_attach_real_evidence_without_writing_by_default(self):
        result = self.assemble()
        self.assertEqual(result["items"][0]["jp_location"], "S3_01-03.xhtml:8")
        self.assertIn("<rt>まじゅつ</rt>", result["items"][0]["jp_quote"])
        self.assertFalse(self.result_path().exists())
        self.assertEqual(validate_data(self.root, result), [])

    def test_required_draft_fields_and_complete_ids_cannot_be_defaulted(self):
        for field in ("decision", "reason", "proposed_cn", "original_fix"):
            with self.subTest(field=field):
                saved = self.draft["items"][0].pop(field)
                with self.assertRaises(ValueError):
                    self.assemble()
                self.draft["items"][0][field] = saved
        self.draft["items"].pop()
        with self.assertRaises(ValueError):
            self.assemble()

    def test_explicit_citations_are_paired_and_never_silently_repaired(self):
        item = self.draft["items"][0]
        item["jp_location"] = "S3_01-03.xhtml:8"
        with self.assertRaisesRegex(ValueError, "成对"):
            self.assemble()
        item["jp_quote"] = "完全に捏造された句。"
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.assemble()

    def test_ruby_readings_are_verified_when_provided(self):
        item = self.draft["items"][0]
        item["jp_location"] = "S3_01-03.xhtml:8"
        for quote in ("彼は魔術を使った。", "彼は|魔術[まじゅつ]を使った。",
                      '<p>彼は<ruby>魔術<rt>まじゅつ</rt></ruby>を使った。</p>'):
            item["jp_quote"] = quote
            self.assemble()
        for quote in ("彼は|魔術[まほう]を使った。",
                      '<p>彼は<ruby>魔術<rt>まほう</rt></ruby>を使った。</p>',
                      "彼は魔 術を使った。", "彼は魔術を使わなかった。"):
            with self.subTest(quote=quote):
                item["jp_quote"] = quote
                with self.assertRaisesRegex(ValueError, "evidence"):
                    self.assemble()

    def test_multiple_locations_do_not_accept_swapped_quotations(self):
        item = self.draft["items"][0]
        item.update(jp_location="S3_01-03.xhtml:8;S3_01-03.xhtml:9",
                    jp_quote="二人は来なかった。\n彼は魔術を使った。")
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.assemble()

    def test_actual_line_required_even_when_quote_occurs_in_same_file(self):
        self.draft["items"][0].update(jp_location="S3_01-03.xhtml:7", jp_quote="彼は魔術を使った。")
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.assemble()

    def test_nullable_state_fields_are_strictly_validated(self):
        result = self.assemble()
        for key, value, expected_kind in (("decision", [], "structure"),
                                           ("proposed_cn", "多余修正", "structure"),
                                           ("reason", "", "evidence")):
            with self.subTest(key=key):
                changed = copy.deepcopy(result)
                changed["items"][0][key] = value
                self.assertIn(expected_kind, {issue["kind"] for issue in validate_data(self.root, changed)})
        result["items"][0]["decision"] = "确认误改"
        self.assertIn("structure", {issue["kind"] for issue in validate_data(self.root, result)})

    def test_original_fix_quotes_frozen_initial_old_and_new(self):
        self.draft["items"][0]["original_fix"] = {
            "category": "否定与逻辑方向", "old_error": "旧译「他没有使用魔法。」颠倒肯定。",
            "new_fix": "新译「他使用了魔法。」恢复使った的肯定。", "impact": "影响动作是否发生。",
        }
        result = self.assemble()
        self.assertEqual(validate_data(self.root, result), [])
        changed = copy.deepcopy(result)
        changed["items"][0]["original_fix"]["new_fix"] = "新译「我修改后的第三版」恢复事实。"
        self.assertIn("evidence", {issue["kind"] for issue in validate_data(self.root, changed)})
        changed = copy.deepcopy(result)
        changed["items"][0].update(decision="确认误改", proposed_cn="他使用了术式。")
        self.assertIn("input", {issue["kind"] for issue in validate_data(self.root, changed)})

    def test_original_fix_is_forbidden_in_acceptance_round(self):
        # Freeze the parent relationship in a separate report round.
        manifest = self.root / "manifest.tsv"
        text = manifest.read_text(encoding="utf-8")
        manifest.write_text(text.replace("\tlocal\tlocal\t\n", "\tlocal\tlocal\tfirst-run:C000001\n", 1),
                            encoding="utf-8")
        # Re-freeze only fixture metadata, preserving the source and old/new values.
        session_path = self.root / "session.json"
        session = json.loads(session_path.read_text(encoding="utf-8"))
        session["manifest_sha256"] = sha256_file(manifest)
        self.write_json(session_path, session)
        session_path.with_suffix(".sha256").write_text(sha256_file(session_path) + "\n", encoding="ascii")
        self.draft["items"][0]["original_fix"] = {
            "category": "否定与逻辑方向", "old_error": "「他没有使用魔法。」", "new_fix": "「他使用了魔法。」",
            "impact": "否定改变。",
        }
        with self.assertRaisesRegex(ValueError, "initial|初始"):
            self.assemble()

    def test_duplicate_json_fields_are_rejected(self):
        path = self.result_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"slice_id":"risk-01","slice_id":"risk-02"}', encoding="utf-8")
        issues = validate_result(self.root, path)
        self.assertEqual(issues[0]["kind"], "structure")
        self.assertIn("重复", issues[0]["message"])

    def test_input_drift_is_distinct_from_report_structure_errors(self):
        result = self.assemble()
        self.jp_file.write_text(self.jp_file.read_text(encoding="utf-8") + "drift", encoding="utf-8")
        issues = validate_data(self.root, result)
        self.assertEqual({issue["kind"] for issue in issues}, {"input"})

    def test_packet_and_session_drift_are_rejected(self):
        result = self.assemble()
        for path in (self.root / "session.json", self.root / "slices/packets/risk-01.json"):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                self.assertEqual(validate_data(self.root, result)[0]["kind"], "input")
                path.write_bytes(original)

    def test_atomic_apply_does_not_overwrite_previous_results(self):
        self.assemble(apply=True)
        original = self.result_path().read_bytes()
        with self.assertRaises(ValueError):
            self.assemble(apply=True)
        self.assertEqual(self.result_path().read_bytes(), original)

    def test_format_revisions_preserve_semantics_and_previous_artifacts(self):
        self.assemble(apply=True)
        old = self.result_path().read_bytes()
        self.assemble(revision=1, apply=True)
        self.assertEqual(validate_result(self.root, self.result_path("a1.r1")), [])
        self.assertEqual(self.result_path().read_bytes(), old)
        self.draft["items"][0]["reason"] = "换了一套取证理由。"
        with self.assertRaisesRegex(ValueError, "格式修订不能改变"):
            self.assemble(revision=2, apply=True)
        self.assertFalse(self.result_path("a1.r2").exists())

    def test_format_revision_can_fill_missing_null_fields_but_not_missing_evidence(self):
        result = self.assemble()
        del result["items"][0]["original_fix"]
        self.write_json(self.result_path(), result)
        self.assemble(revision=1)
        del result["items"][0]["jp_quote"]
        self.write_json(self.result_path(), result)
        with self.assertRaisesRegex(ValueError, "语义字段"):
            self.assemble(revision=1)

    def test_revision_needs_a_deterministic_previous_artifact(self):
        with self.assertRaisesRegex(ValueError, "前一产物"):
            self.assemble(revision=1)
        self.assemble(apply=True)
        with self.assertRaisesRegex(ValueError, "前一产物"):
            self.assemble(revision=2)

    def test_selected_revision_cannot_bypass_semantic_comparison(self):
        result = self.assemble(apply=True)
        result["items"][0]["reason"] = "偷偷改变理由。"
        self.write_json(self.result_path("a1.r1"), result)
        data = self.selected("slices/risk-01.a1.r1.json")
        self.assertFalse(data["ready_for_lead_acceptance"])
        self.assertEqual(data["counts"]["U"], 2)

    def test_revision_chain_cannot_hide_a_prior_semantic_change(self):
        result = self.assemble(apply=True)
        result["items"][0]["reason"] = "先在第一修订偷偷改变理由。"
        self.write_json(self.result_path("a1.r1"), result)
        self.write_json(self.result_path("a1.r2"), result)
        data = self.selected("slices/risk-01.a1.r2.json")
        self.assertFalse(data["ready_for_lead_acceptance"])
        self.assertEqual(data["counts"]["U"], 2)

    def test_missing_report_is_an_input_failure(self):
        issues = validate_result(self.root, self.result_path())
        self.assertEqual({issue["kind"] for issue in issues}, {"input"})

    def test_result_path_and_attempt_are_checked_independently(self):
        result = self.assemble()
        self.write_json(self.result_path("a2"), result)
        issues = validate_result(self.root, self.result_path("a2"))
        self.assertEqual({issue["kind"] for issue in issues}, {"input"})

    def test_coverage_uses_explicit_selection_and_counts_all_failure_items(self):
        self.assemble(apply=True)
        self.draft["items"][0].update(decision="未覆盖", reason="子智能体故障，未读原文。")
        self.assemble(attempt=2, apply=True)
        chosen = self.selected()
        self.assertTrue(chosen["ready_for_lead_acceptance"])
        self.assertEqual(chosen["counts"]["K"], 2)
        missing = self.selected(None)
        self.assertEqual(missing["counts"]["U"], 2)
        self.assertEqual(len(missing["unresolved"]), 2)
        self.assertFalse(missing["ready_for_lead_acceptance"])

    def test_pending_and_uncovered_are_blocking_even_with_structural_acceptance(self):
        self.draft["items"][0].update(decision="待人工", reason="已核肯定动词，但缺少所需前文。")
        self.draft["items"][1].update(decision="未覆盖", reason="任务中断，尚未读取。")
        self.assemble(apply=True)
        data = self.selected()
        self.assertEqual((data["counts"]["H"], data["counts"]["U"]), (1, 1))
        self.assertFalse(data["coverage_complete"])

    def test_selection_cannot_escape_or_select_an_unassigned_filename(self):
        for relative in ("../elsewhere.json", "slices/risk-02.a1.json", "decisions.json"):
            with self.subTest(relative=relative):
                with self.assertRaises(ValueError):
                    self.selected(relative)

    def test_sealed_item_context_allows_explicit_dependencies_only(self):
        item = self.draft["items"][0]
        item.update(jp_location="S3_01-03.xhtml:11", jp_quote="隣接する第11行。")
        with self.assertRaisesRegex(ValueError, "冻结窗口"):
            self.assemble()
        extra = source_context(self.root, "risk-01", "C000001", radius=3)
        path = self.root / "slices/context/risk-01/C000001.c1.json"
        data = (json.dumps(extra, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        import hashlib
        write_new_artifacts({path: data, path.with_suffix(".sha256"):
                             (hashlib.sha256(data).hexdigest() + "\n").encode("ascii")}, apply=True)
        self.assemble()
        extra["context"][0]["raw"] = "<p>偽造。</p>"
        self.write_json(path, extra)
        path.with_suffix(".sha256").write_text(sha256_file(path) + "\n", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "input"):
            self.assemble()

    def test_unicode_separators_remain_inside_physical_source_and_quote_lines(self):
        """Unicode line/paragraph whitespace cannot shift XHTML physical IDs."""
        original_root = self.root
        jp_lines = self.jp_file.read_text(encoding="utf-8").split("\n")
        cn_path = self.cn / "S3_01-03_Chapter1.xhtml"
        cn_lines = cn_path.read_text(encoding="utf-8").split("\n")
        for index, separator in enumerate(("\u2028", "\u2029", "\u0085"), 1):
            with self.subTest(separator=f"U+{ord(separator):04X}"):
                # One earlier source line and one referenced line contain the
                # separator. CN's neighbor is checked independently by validation.
                jp_lines[1] = f"<p>先の段落{separator}まだ同じ物理行。</p>"
                jp_lines[7] = f"<p>彼は魔術を使った。{separator}それで終わった。</p>"
                cn_lines[1] = f"<p>前文{separator}仍属同一物理行。</p>"
                cn_lines[6] = f"<p>邻接前文{separator}仍属同一物理行。</p>"
                self.jp_file.write_text("\n".join(jp_lines), encoding="utf-8")
                cn_path.write_text("\n".join(cn_lines), encoding="utf-8")
                self.root = self.base / f"unicode-run-{index}"
                self.root.mkdir()
                (self.root / "changes.tsv").write_bytes((original_root / "changes.tsv").read_bytes())
                initialize_manifest(self.root, apply=True)
                plan = self.root / "plan.json"
                self.write_json(plan, {"slices": [{"slice_id": "risk-01",
                                                   "item_ids": ["C000001", "C000002"]}]})
                prepare_session(self.root, jp_base=self.jp, cn_base=self.cn, plan_path=plan, apply=True)
                self.decisions = self.root / "decisions.json"
                self.draft["items"][0].update(
                    jp_location="S3_01-03.xhtml:8",
                    jp_quote=f"彼は魔術を使った。{separator}それで終わった。")
                result = self.assemble(apply=True)
                self.assertIn(separator, result["items"][0]["jp_quote"])
                self.assertEqual(validate_result(self.root, self.result_path()), [])
                self.assertTrue(self.selected()["ready_for_lead_acceptance"])


if __name__ == "__main__":
    unittest.main()
