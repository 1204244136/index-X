from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_note_order


class NoteOrderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.text = self.root / "【S1_01】书" / "OEBPS" / "Text"
        self.text.mkdir(parents=True)
        self.notes = self.text / "S1_01-Note.xhtml"

    def write(self, definitions: list[str], refs: list[str]):
        self.notes.write_text('<html><body><ol>' + ''.join(f'<li id="{note}">注释</li>' for note in definitions) + '</ol></body></html>', encoding="utf-8")
        (self.text / "S1_01-01_Chapter.xhtml").write_text(
            '<html xmlns:epub="http://www.idpf.org/2007/ops"><body>' +
            ''.join(f'<p><a epub:type="noteref" href="S1_01-Note.xhtml#{note}">注</a></p>' for note in refs) +
            '</body></html>', encoding="utf-8")

    def test_first_reference_order_and_repeated_references(self):
        self.write(["note1", "note2"], ["note1", "note2", "note1"])
        _, issues = check_note_order.check_book("书", str(self.text), self.notes.name)
        self.assertEqual(issues, [])

    def test_missing_or_orphan_definitions_and_wrong_order(self):
        cases = [(["note1"], ["note1", "note2"], "未定义"),
                 (["note1", "note2"], ["note1"], "未引用"),
                 (["note2", "note1"], ["note1", "note2"], "列表顺序")]
        for definitions, refs, expected in cases:
            with self.subTest(expected=expected):
                self.write(definitions, refs)
                _, issues = check_note_order.check_book("书", str(self.text), self.notes.name)
                self.assertTrue(any(expected in issue for issue in issues))

    def test_cli_failure_is_nonzero_and_inputs_stay_unchanged(self):
        self.write(["note1"], ["note2"])
        original = self.notes.read_bytes()
        with patch.object(sys, "argv", ["check_note_order.py", "--root", str(self.root), "--output", str(self.root / "report")]):
            self.assertEqual(check_note_order.main(), 1)
        self.assertEqual(self.notes.read_bytes(), original)

    def test_tsv_and_json_preserve_the_same_note_findings(self):
        self.write(["note1"], ["note2"])
        report = self.root / "report"
        with patch.object(sys, "argv", ["check_note_order.py", "--root", str(self.root),
                                       "--output", str(report)]):
            self.assertEqual(check_note_order.main(), 1)
        payload = json.loads((report / "note-order-check.json").read_text(encoding="utf-8"))
        with (report / "note-order-check.tsv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(len(rows), 1)
        entry = payload[rows[0]["book"]]
        self.assertEqual(rows[0]["note_file"], self.notes.name)
        for key in ("defined_order", "appearance_order", "first_appearance", "issues"):
            self.assertEqual(json.loads(rows[0][key]), entry[key])
        self.assertTrue((report / "note-order-check.md").is_file())

    def test_explicit_report_write_failure_is_nonzero_on_stderr(self):
        self.write(["note1"], ["note1"])
        blocked = self.root / "blocked"
        blocked.write_text("not a directory", encoding="utf-8")
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["check_note_order.py", "--root", str(self.root),
                                       "--output", str(blocked / "report")]):
            with redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(check_note_order.main(), 2)
        self.assertIn("报告", errors.getvalue())
        self.assertNotIn("跳过写入", output.getvalue())

    def test_invalid_input_root_returns_two_without_writing_reports(self):
        for kind in ("missing", "file"):
            with self.subTest(kind=kind):
                source = self.root / kind
                if kind == "file":
                    source.write_text("not a directory", encoding="utf-8")
                report = self.root / "report"
                output, errors = io.StringIO(), io.StringIO()
                with patch.object(sys, "argv", ["check_note_order.py", "--root", str(source),
                                               "--output", str(report)]):
                    with redirect_stdout(output), redirect_stderr(errors):
                        self.assertEqual(check_note_order.main(), 2)
                self.assertEqual(output.getvalue(), "")
                self.assertIn(str(source), errors.getvalue())
                self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
