from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from docx2epub import build_chapters, render_content  # noqa: E402
from notes_core import book_order_key, gather_refs  # noqa: E402


class DocxIntroTests(unittest.TestCase):
    def test_text_before_prologue_becomes_numbered_intro_unit(self):
        paragraphs = [
            {"idx": 0, "style": "Normal", "text": "引子正文", "imgs": [], "has_link": False},
            {"idx": 1, "style": "Heading 1", "text": "序章", "imgs": [], "has_link": False},
            {"idx": 2, "style": "Normal", "text": "序章正文", "imgs": [], "has_link": False},
        ]
        chapters, _, front_text, _ = build_chapters(paragraphs)
        self.assertEqual(front_text, ["引子正文"])
        self.assertEqual(chapters[0]["suffix"], "Before_the_Prologue")
        self.assertEqual(chapters[0]["title"], "")
        rendered = render_content(chapters[0], {})
        self.assertEqual(rendered.splitlines()[3], "")
        self.assertEqual(rendered.splitlines()[5], "<p>引子正文</p>")


class NoteOrderTests(unittest.TestCase):
    def test_order_uses_header_sequence(self):
        names = [
            "S5_01_03-10_Chapter1.xhtml",
            "S5_01_03-00_Introduction.xhtml",
            "S5_01_03-02_Chapter9.xhtml",
        ]
        ordered = sorted(names, key=lambda name: book_order_key(name, "S5_01_03-Note.xhtml"))
        self.assertEqual(ordered, [names[1], names[2], names[0]])

    def test_single_quoted_noteref_is_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "S1_01-01_Chapter1.xhtml").write_text(
                "<a epub:type='noteref' href='S1_01-Note.xhtml#note1'>注</a>",
                encoding="utf-8",
            )
            (root / "S1_01-Note.xhtml").write_text("<li id='note1'>注</li>", encoding="utf-8")
            appearance, refs = gather_refs(root, "S1_01-Note.xhtml")
            self.assertEqual(list(appearance), ["note1"])
            self.assertEqual(refs["note1"], [("S1_01-01_Chapter1.xhtml", 1)])


if __name__ == "__main__":
    unittest.main()
