from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from merge_bw_pages import collect_pages, group_units, merge_unit  # noqa: E402
from xhtml_template import rebuild  # noqa: E402


HEAD = (
    "<?xml version='1.0' encoding='utf-8'?>\n"
    "<!DOCTYPE html>\n"
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title/></head><body>\n'
)


class XhtmlTemplateTests(unittest.TestCase):
    def test_title_and_numeric_section_are_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "japanese-text" / "book" / "S1_01-01.xhtml"
            path.parent.mkdir(parents=True)
            path.write_text(
                HEAD
                + '<p class="font-1em10">あとがき</p>\n'
                + "<p>１</p>\n<p>正文</p>\n</body></html>\n",
                encoding="utf-8",
            )
            lines, _ = rebuild(path)
            self.assertIsNotNone(lines)
            self.assertTrue(lines[3].startswith("<h1"))
            self.assertEqual(lines[4], "<h2>１</h2>")
            self.assertEqual(lines[5], "<p>正文</p>")

    def test_chinese_note_list_uses_l5_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = (
                Path(tmp) / "chinese-text" / "[S1_01]书" / "OEBPS" / "Text"
                / "S1_01-Note.xhtml"
            )
            path.parent.mkdir(parents=True)
            path.write_text(
                HEAD + "<ul>\n<p><li id=\"note1\">注</li></p>\n</ul>\n</body></html>\n",
                encoding="utf-8",
            )
            lines, _ = rebuild(path)
            self.assertIsNotNone(lines)
            self.assertEqual(lines[3], "")
            self.assertEqual(lines[4], "<ul>")
            self.assertEqual(lines[5], '<li id="note1">注</li>')

    def test_classed_body_wrapper_is_closed_without_extra_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "japanese-text" / "book" / "S1_01-01.xhtml"
            path.parent.mkdir(parents=True)
            path.write_text(
                HEAD.replace("<body>", '<body><div class="main">')
                + "<p>正文</p>\n</div>\n</body></html>\n",
                encoding="utf-8",
            )
            lines, _ = rebuild(path)
            self.assertIsNotNone(lines)
            self.assertEqual(lines[5], "<p>正文</p>")
            self.assertEqual(lines[-1], "</div></body></html>")


class MergeBwTests(unittest.TestCase):
    @staticmethod
    def page(h1: str, body: str) -> str:
        return (
            "<?xml version='1.0' encoding='utf-8'?>\n"
            "<!DOCTYPE html>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title/></head>'
            '<body class="p-text">\n'
            '<div class="main">\n'
            f"{h1}\n\n{body}\n"
            "</div>\n</body></html>\n"
        )

    def test_merge_outputs_fixed_template_without_nested_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "p-001.xhtml").write_text(
                self.page('<h1 id="chapter">第一章</h1>', "<p>A</p>"), encoding="utf-8"
            )
            (root / "p-002.xhtml").write_text(
                self.page("", "<p>B</p>"), encoding="utf-8"
            )
            notes: list[str] = []
            units = group_units(collect_pages(root), notes)
            merged = merge_unit(units[0], notes)
            self.assertEqual(merged[0].split()[0], "<?xml")
            self.assertIn("<html", merged[2])
            self.assertIn("<body", merged[2])
            self.assertEqual(merged[3], '<h1 id="chapter">第一章</h1>')
            self.assertEqual(merged[4], "")
            self.assertEqual(merged[5], "<p>A</p>")
            self.assertEqual(merged.count("<br/>"), 3)
            self.assertNotIn("<div", "\n".join(merged))
            self.assertNotIn("<h1><h1", "\n".join(merged))


if __name__ == "__main__":
    unittest.main()
