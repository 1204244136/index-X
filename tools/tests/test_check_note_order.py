from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_note_order


class NoteOrderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.text = self.root / "[S1_01]书" / "OEBPS" / "Text"
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


if __name__ == "__main__":
    unittest.main()
