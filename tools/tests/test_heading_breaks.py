from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from migrate_heading_breaks import (  # noqa: E402
    MigrationError,
    apply_book,
    migrate_heading_line,
    plan_book,
)


class HeadingLineTests(unittest.TestCase):
    def test_nested_three_layer_heading_preserves_text_and_classes(self):
        source = (
            '<h1><div style="text-align: center;"><span>第一章 <br/></span>'
            '<span class="font08">副标题 <br/></span>'
            '<span class="font06">Code.</span></div></h1>'
        )
        result = migrate_heading_line(source)
        self.assertEqual(result.layers, ("第一章", "副标题", "Code."))
        self.assertEqual(result.kind, "layered-3")
        self.assertEqual(
            result.line,
            '<h1 class="heading-lines"><span class="heading-main">第一章</span>'
            '<span class="heading-subtitle font08">副标题</span>'
            '<span class="heading-code font06">Code.</span></h1>',
        )

    def test_nested_two_layer_heading_removes_last_layout_break(self):
        source = (
            '<h1><div style="text-align: center;"><span>序章 <br/></span>'
            '<span class="font08"><ruby>标题<rt>Title</rt></ruby> <br/></span>'
            '</div></h1>'
        )
        result = migrate_heading_line(source)
        self.assertEqual(result.layers, ("序章", "标题Title"))
        self.assertNotIn("<br", result.line)
        self.assertIn('<span class="heading-subtitle font08"><ruby>', result.line)

    def test_direct_subtitle_and_its_trailing_break_are_migrated(self):
        result = migrate_heading_line(
            '<h1>序章 <br/><span class="font08">地下放送A<br/></span></h1>'
        )
        self.assertEqual(result.layers, ("序章", "地下放送A"))
        self.assertEqual(result.kind, "direct-subtitle")
        self.assertNotIn("<br", result.line)

    def test_sup_layer_is_code(self):
        result = migrate_heading_line('<h1>严重的损伤 <br/><sup>code</sup></h1>')
        self.assertEqual(
            result.line,
            '<h1 class="heading-lines"><span class="heading-main">严重的损伤</span>'
            '<span class="heading-code"><sup>code</sup></span></h1>',
        )

    def test_direct_h2_text_becomes_two_layers_and_keeps_id(self):
        result = migrate_heading_line('<h2 id="toc_2">特典 <br/>副标题</h2>')
        self.assertEqual(result.layers, ("特典", "副标题"))
        self.assertEqual(
            result.line,
            '<h2 id="toc_2" class="heading-lines">'
            '<span class="heading-main">特典</span>'
            '<span class="heading-subtitle">副标题</span></h2>',
        )

    def test_single_trailing_break_is_deleted_without_extra_wrappers(self):
        result = migrate_heading_line("<h1>第一章 <br/></h1>")
        self.assertEqual(result.kind, "trailing-noise")
        self.assertFalse(result.layered)
        self.assertEqual(result.line, "<h1>第一章</h1>")

    def test_unknown_div_structure_is_rejected(self):
        with self.assertRaises(MigrationError):
            migrate_heading_line(
                '<h1><div class="title"><span>第一章<br/></span>'
                '<span>副标题</span></div></h1>'
            )


class BookMigrationTests(unittest.TestCase):
    def test_body_break_is_not_mistaken_for_heading_break(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "book"
            text = book / "OEBPS" / "Text"
            text.mkdir(parents=True)
            (text / "plain.xhtml").write_text(
                "<html><body><h1>标题</h1><p>前文<br/>后文</p></body></html>\n",
                encoding="utf-8",
            )
            self.assertIsNone(plan_book(book))

    def test_plan_and_apply_change_xhtml_and_css_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "[S1_01]测试"
            text = book / "OEBPS" / "Text"
            styles = book / "OEBPS" / "Styles"
            text.mkdir(parents=True)
            styles.mkdir(parents=True)
            xhtml = text / "S1_01-01_Chapter1.xhtml"
            css = styles / "style.css"
            source_lines = [
                "<?xml version='1.0' encoding='utf-8'?>",
                "<!DOCTYPE html>",
                '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                '<link href="../Styles/style.css" rel="stylesheet"/></head><body>',
                '<h1>第一章 <br/><span class="font08">副标题</span></h1>',
                "",
                "<p>正文</p>",
                "</body></html>",
            ]
            xhtml.write_bytes(b"\xef\xbb\xbf" + "\r\n".join(source_lines).encode() + b"\r\n")
            css.write_bytes(b"\xef\xbb\xbfbody {\r\n  margin: 0;\r\n}\r\n")

            plan = plan_book(book)
            self.assertIsNotNone(plan)
            assert plan is not None
            self.assertEqual(plan.heading_count, 1)
            self.assertEqual(plan.xhtml_files, {xhtml})
            self.assertEqual(plan.css_files, {css})
            self.assertIn("<br/>", xhtml.read_text(encoding="utf-8-sig"))

            apply_book(plan)

            xhtml_raw = xhtml.read_bytes()
            css_raw = css.read_bytes()
            self.assertTrue(xhtml_raw.startswith(b"\xef\xbb\xbf"))
            self.assertIn(b"\r\n", xhtml_raw)
            self.assertNotIn(b"<br/>", xhtml_raw)
            self.assertIn(b' class="heading-lines"', xhtml_raw)
            self.assertTrue(css_raw.startswith(b"\xef\xbb\xbf"))
            self.assertIn(b".heading-lines > .heading-main,\r\n", css_raw)

    def test_unknown_heading_prevents_book_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "book"
            text = book / "OEBPS" / "Text"
            text.mkdir(parents=True)
            xhtml = text / "bad.xhtml"
            original = '<h1><div class="unknown"><span>章<br/></span></div></h1>\n'
            xhtml.write_text(original, encoding="utf-8")
            with self.assertRaises(MigrationError):
                plan_book(book)
            self.assertEqual(xhtml.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
