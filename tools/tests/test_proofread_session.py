"""Public CLI exercise with isolated paired sources and real report files."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]


class SessionCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="proofread-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "run-one"
        self.root.mkdir()
        self.jp = self.base / "source-jp"
        self.cn = self.base / "source-cn"
        self.jp.mkdir()
        self.cn.mkdir()
        self.jp_file = self.jp / "S1_01-01.xhtml"
        self.cn_file = self.cn / "S1_01-01_Prologue.xhtml"
        self.jp_file.write_text(
            '<html>\n<body>\n<p>隣上</p>\n'
            '<p><ruby>魔術<rt>まじゅつ</rt></ruby>を使う。</p>\n'
            '<p>隣下</p>\n</body>\n</html>\n', encoding="utf-8")
        self.cn_file.write_text(
            '<html>\n<body>\n<p>邻上</p>\n<p>新译</p>\n'
            '<p>邻下</p>\n</body>\n</html>\n', encoding="utf-8")
        fields = ("commit", "work", "file", "line", "grade", "kind", "flags", "old", "new", "jp")
        with (self.root / "changes.tsv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fields, delimiter="\t")
            writer.writeheader()
            writer.writerow(dict(commit="worktree", work="S1_01", file=self.cn_file.name,
                                 line="4", grade="local", kind="", flags="kanji",
                                 old="旧译", new="新译", jp="魔術を使う。"))
            writer.writerow(dict(commit="worktree", work="S1_01", file=self.cn_file.name,
                                 line="3", grade="spec", kind="punct", flags="",
                                 old="邻上。", new="邻上", jp="隣上"))
        self.sid = "S1_01-01-s01"
        self.plan = self.base / "plan.json"
        self.write_json(self.plan, {"slices": [dict(slice_id=self.sid,
                                                  item_ids=["C000001"], diff_lines=2)]})
        self.decisions = self.root / "slices" / f"{self.sid}.a1.decisions.json"
        self.result = self.root / "slices" / f"{self.sid}.a1.json"
        self.selection = self.root / "selection.json"

    def write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def run_cli(self, command, *arguments, expected=0):
        environment = dict(os.environ, PYTHONIOENCODING="gbk", PYTHONUTF8="0",
                           PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(
            [sys.executable, "-B", str(TOOLS / "proofread_session.py"), command,
             "--report-root", str(self.root), *map(str, arguments)],
            capture_output=True, env=environment, timeout=30,
        )
        self.assertEqual(result.returncode, expected,
                         result.stdout.decode("utf-8", "replace") +
                         result.stderr.decode("utf-8", "replace"))
        self.assertNotIn("Traceback", result.stderr.decode("utf-8"))
        return result

    def prepare(self):
        self.run_cli("init", "--apply")
        self.run_cli("prepare", "--jp-base", self.jp, "--cn-base", self.cn,
                     "--plan", self.plan, "--apply")

    def explicit_decisions(self):
        self.write_json(self.decisions, {"items": [{
            "item_id": "C000001", "decision": "保留新译",
            "reason": "原文明确描述使用魔术，保留本项新译。",
            "proposed_cn": None, "original_fix": None,
        }], "discoveries": []})

    def test_default_preview_and_complete_review_transport(self):
        initial = self.run_cli("init")
        self.assertFalse(json.loads(initial.stdout)["applied"])
        self.assertFalse((self.root / "manifest.tsv").exists())
        self.run_cli("init", "--apply")
        self.run_cli("prepare", "--jp-base", self.jp, "--cn-base", self.cn, "--plan", self.plan)
        self.assertFalse((self.root / "session.json").exists())
        self.run_cli("prepare", "--jp-base", self.jp, "--cn-base", self.cn,
                     "--plan", self.plan, "--apply")
        shown = self.run_cli("read", "--slice", self.sid, "--ids", "C000001", "--json")
        page = json.loads(shown.stdout)
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["evidence"][0]["plain"], "魔術を使う。")
        self.assertEqual(len(page["items"][0]["context"]), 2)
        self.explicit_decisions()
        self.run_cli("assemble", "--slice", self.sid, "--decisions", self.decisions)
        self.assertFalse(self.result.exists())
        self.run_cli("assemble", "--slice", self.sid, "--decisions", self.decisions, "--apply")
        checked = self.run_cli("validate", "--result", self.result, "--json")
        self.assertTrue(json.loads(checked.stdout)["valid"])
        self.write_json(self.selection, {self.sid: f"slices/{self.result.name}"})
        summary = json.loads(self.run_cli("coverage", "--selection", self.selection).stdout)
        self.assertEqual(summary["counts"], dict(T=2, S=1, M=1, K=1, R=0, H=0, U=0))
        self.assertEqual(summary["semantic_acceptance"], "requires_lead_review")

    def test_failed_draft_never_generates_default_keep_or_partial_result(self):
        self.prepare()
        self.write_json(self.decisions, {"items": [], "discoveries": []})
        result = self.run_cli("assemble", "--slice", self.sid, "--decisions", self.decisions,
                              "--apply", expected=1)
        self.assertFalse(self.result.exists())
        self.assertIn("[阻断]", result.stderr.decode("utf-8"))

    def test_validator_rejects_real_wrong_quote_and_coverage_counts_whole_slice_uncovered(self):
        self.prepare()
        self.explicit_decisions()
        self.run_cli("assemble", "--slice", self.sid, "--decisions", self.decisions, "--apply")
        data = json.loads(self.result.read_text(encoding="utf-8"))
        data["items"][0]["jp_quote"] = "実際には存在しない引用。"
        self.write_json(self.result, data)
        checked = self.run_cli("validate", "--result", self.result, "--json", expected=1)
        self.assertIn("evidence", [issue["kind"] for issue in json.loads(checked.stdout)["issues"]])
        self.write_json(self.selection, {self.sid: f"slices/{self.result.name}"})
        summary = json.loads(self.run_cli("coverage", "--selection", self.selection, expected=1).stdout)
        self.assertEqual(summary["counts"]["U"], 1)
        self.assertFalse(summary["ready_for_lead_acceptance"])

    def test_duplicate_write_is_blocked_and_source_drift_invalidates_read(self):
        self.prepare()
        self.explicit_decisions()
        self.run_cli("assemble", "--slice", self.sid, "--decisions", self.decisions, "--apply")
        original = self.result.read_bytes()
        self.run_cli("assemble", "--slice", self.sid, "--decisions", self.decisions,
                     "--apply", expected=1)
        self.assertEqual(original, self.result.read_bytes())
        self.jp_file.write_text("changed\n", encoding="utf-8")
        self.run_cli("read", "--slice", self.sid, expected=1)

    def test_context_requires_apply_and_coverage_cannot_escape_report_root(self):
        self.prepare()
        self.run_cli("context", "--slice", self.sid, "--item-id", "C000001", "--radius", "2")
        context_file = self.root / "slices/context" / self.sid / "C000001.c1.json"
        self.assertFalse(context_file.exists())
        self.run_cli("context", "--slice", self.sid, "--item-id", "C000001",
                     "--radius", "2", "--apply")
        self.assertTrue(context_file.exists())
        self.write_json(self.selection, {})
        escaped = self.base / "escaped.json"
        self.run_cli("coverage", "--selection", self.selection, "--output", escaped,
                     "--apply", expected=1)
        self.assertFalse(escaped.exists())


if __name__ == "__main__":
    unittest.main()
