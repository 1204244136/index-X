from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from shift_content_sequences import (  # noqa: E402
    apply_shift,
    plan_shift,
    reference_rewrites,
)


class ShiftContentSequencesTests(unittest.TestCase):
    def test_adjacent_sequences_shift_once_and_references_follow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = root / "OEBPS" / "Text"
            text.mkdir(parents=True)
            zero = text / "S1_19-00_Prologue.xhtml"
            one = text / "S1_19-01_Chapter1.xhtml"
            page = text / "S1_19-01_p-001.xhtml"
            zero.write_text('<a href="S1_19-01_Chapter1.xhtml">next</a>', encoding="utf-8")
            one.write_text("<p>chapter</p>", encoding="utf-8")
            page.write_text("<p>page</p>", encoding="utf-8")
            opf = root / "OEBPS" / "content.opf"
            opf.write_text(
                '<item href="Text/S1_19-00_Prologue.xhtml"/>'
                '<item href="Text/S1_19-01_Chapter1.xhtml"/>',
                encoding="utf-8",
            )
            toc = text / "S1_19-p-toc.xhtml"
            toc.write_text('<a href="p-001.xhtml#toc-001">chapter</a>', encoding="utf-8")

            renames = plan_shift(root, "S1_19", 1)
            rewrites = reference_rewrites(root, renames)
            apply_shift(root, renames, rewrites)

            self.assertFalse(zero.exists())
            self.assertTrue((text / "S1_19-01_Prologue.xhtml").exists())
            self.assertTrue((text / "S1_19-02_Chapter1.xhtml").exists())
            self.assertTrue((text / "S1_19-02_p-001.xhtml").exists())
            self.assertIn("S1_19-01_Prologue.xhtml", opf.read_text(encoding="utf-8"))
            self.assertIn("S1_19-02_Chapter1.xhtml", opf.read_text(encoding="utf-8"))
            self.assertIn(
                "S1_19-02_Chapter1.xhtml",
                (text / "S1_19-01_Prologue.xhtml").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "S1_19-02_p-001.xhtml#toc-001",
                toc.read_text(encoding="utf-8"),
            )
            self.assertNotIn(
                "S1_19-02_S1_19-02_p-001.xhtml",
                toc.read_text(encoding="utf-8"),
            )

    def test_shift_refuses_sequence_below_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "S1_01-01_Chapter1.xhtml").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "必须从 01 开始"):
                plan_shift(root, "S1_01", -1)


if __name__ == "__main__":
    unittest.main()
