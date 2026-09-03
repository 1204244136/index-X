from __future__ import annotations

import sys
import unittest
import zipfile
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from bw_preprocess import (  # noqa: E402
    apply_entry_renames,
    apply_rules,
    artifact_contract_issues,
    epub_zip_issues,
    is_content,
    load_header_map,
    load_rules,
    page_map_contract_issues,
    pairing_header_renames,
    template_issues,
)


RULES = load_rules(None)


def raw_page(body_lines: list[str], *, body_class: str = "p-text") -> str:
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE html>",
        "<html",
        ' xmlns="http://www.w3.org/1999/xhtml"',
        ' xmlns:epub="http://www.idpf.org/2007/ops"',
        ' xml:lang="ja"',
        ' class="vrtl"',
        ">",
        "<head>",
        '<meta charset="UTF-8"/>',
        "<title>测试</title>",
        '<link rel="stylesheet" type="text/css" href="../style/book-style.css"/>',
        "</head>",
        f'<body class="{body_class}">',
        '<div class="main">',
        *body_lines,
        "</div>",
        "</body>",
        "</html>",
    ])


class BookWalkerTemplateTests(unittest.TestCase):
    def test_unprocessed_multiline_header_is_rejected(self):
        text = raw_page(["<p>正文</p>"])
        self.assertTrue(is_content(text))
        self.assertTrue(any(
            issue.startswith("L3 未折叠")
            for issue in template_issues(text.splitlines())
        ))

    def test_untitled_page_gets_blank_header_slots_without_losing_body(self):
        source = raw_page(["<p>第一段</p>", "<p>第二段</p>"])
        result = apply_rules(source, RULES)
        lines = result.splitlines()
        self.assertIn('<div class="main">', lines[2])
        self.assertEqual(lines[3:7], ["", "", "<p>第一段</p>", "<p>第二段</p>"])
        self.assertEqual(template_issues(lines), [])
        self.assertEqual(apply_rules(result, RULES), result)

    def test_title_and_numeric_sections_become_h1_and_h2(self):
        source = raw_page([
            '<div class="start-3em">',
            '<p class="font-1em30" id="toc-001">第一章　标题</p>',
            "</div>",
            "<br/>",
            "<br/>",
            '<div class="start-5em">',
            "<p>１</p>",
            "</div>",
            "<br/>",
            "<p>第一段</p>",
            '<div class="start-5em"><p>２</p></div>',
            "<p>第二段</p>",
        ])
        result = apply_rules(source, RULES)
        lines = result.splitlines()
        self.assertEqual(
            lines[3],
            '<h1 class="font-1em30" id="toc-001">第一章　标题</h1>',
        )
        self.assertEqual(lines[4], "<h2>１</h2>")
        self.assertEqual(lines[5], "<p>第一段</p>")
        self.assertIn("<h2>２</h2>", lines)
        self.assertNotIn("start-3em", result)
        self.assertNotIn("start-5em", result)
        self.assertEqual(template_issues(lines), [])

    def test_title_without_first_subsection_keeps_empty_l5(self):
        source = raw_page([
            '<div class="start-3em">',
            '<p class="font-1em30">あとがき</p>',
            "</div>",
            "<br/>",
            "<br/>",
            "<p>正文</p>",
        ])
        lines = apply_rules(source, RULES).splitlines()
        self.assertEqual(lines[3], '<h1 class="font-1em30">あとがき</h1>')
        self.assertEqual(lines[4], "")
        self.assertEqual(lines[5], "<p>正文</p>")
        self.assertEqual(template_issues(lines), [])

    def test_malformed_xml_is_reported_after_template_conversion(self):
        result = apply_rules(raw_page(["<p>正文</p>"]), RULES)
        malformed = result.replace("</p>", "", 1)
        issues = template_issues(malformed.splitlines())
        self.assertTrue(any(issue.startswith("XML 解析失败：") for issue in issues))

    def test_pairing_headers_follow_h1_units_and_rewrite_references(self):
        intro = apply_rules(raw_page(["<p>引子</p>"]), RULES).encode()
        chapter = apply_rules(raw_page([
            '<div class="start-3em"><p class="font-1em30">序章</p></div>',
            "<p>正文</p>",
        ]), RULES).encode()
        continuation = apply_rules(raw_page(["<p>续页</p>"]), RULES).encode()
        entries = {
            "item/xhtml/p-001.xhtml": intro.replace(
                b'<p>\xe5\xbc\x95\xe5\xad\x90</p>',
                b'<p><img src="../image/i-030.jpg"/></p>',
            ),
            "item/xhtml/p-002.xhtml": chapter,
            "item/xhtml/p-003.xhtml": continuation,
            "item/xhtml/p-cover.xhtml": b"<html/>",
            "item/navigation-documents.xhtml": b'<a href="xhtml/p-002.xhtml"/>',
            "item/standard.opf": b'<item href="xhtml/p-001.xhtml"/>'
                                 b'<item href="xhtml/p-003.xhtml"/>'
                                 b'<item href="image/i-030.jpg"/>',
            "item/style/book-style.css": b'body{background:url("../image/i-030.jpg")}',
            "item/image/i-030.jpg": b"jpeg data",
        }
        renames = pairing_header_renames(entries, "S4_05")
        self.assertEqual(
            renames["item/xhtml/p-001.xhtml"],
            "item/xhtml/S4_05-01_p-001.xhtml",
        )
        self.assertEqual(
            renames["item/xhtml/p-002.xhtml"],
            "item/xhtml/S4_05-02_p-002.xhtml",
        )
        self.assertEqual(
            renames["item/xhtml/p-003.xhtml"],
            "item/xhtml/S4_05-02_p-003.xhtml",
        )
        self.assertEqual(
            renames["item/xhtml/p-cover.xhtml"],
            "item/xhtml/S4_05-p-cover.xhtml",
        )
        self.assertEqual(
            renames["item/image/i-030.jpg"],
            "item/image/S4_05-i-030.jpg",
        )
        rewritten = apply_entry_renames(entries, renames)
        self.assertIn("item/xhtml/S4_05-02_p-003.xhtml", rewritten)
        self.assertIn(b"S4_05-01_p-001.xhtml", rewritten["item/standard.opf"])
        self.assertIn(
            b"S4_05-02_p-002.xhtml",
            rewritten["item/S4_05-navigation-documents.xhtml"],
        )
        self.assertIn(b"S4_05-i-030.jpg", rewritten["item/standard.opf"])
        self.assertIn(b"S4_05-i-030.jpg", rewritten["item/style/book-style.css"])

    def test_audited_page_map_can_split_untitled_tail_and_exclude_wrappers(self):
        page = apply_rules(raw_page(["<p>正文</p>"]), RULES).encode()
        entries = {
            "item/xhtml/p-001.xhtml": page,
            "item/xhtml/p-002.xhtml": page,
            "item/xhtml/p-003.xhtml": b"<html/>",
        }
        page_map = {"p-001.xhtml": 8, "p-002.xhtml": 9, "p-003.xhtml": None}
        renames = pairing_header_renames(entries, "S4_05", page_map)
        self.assertEqual(
            renames["item/xhtml/p-001.xhtml"],
            "item/xhtml/S4_05-08_p-001.xhtml",
        )
        self.assertEqual(
            renames["item/xhtml/p-002.xhtml"],
            "item/xhtml/S4_05-09_p-002.xhtml",
        )
        self.assertEqual(
            renames["item/xhtml/p-003.xhtml"],
            "item/xhtml/S4_05-p-003.xhtml",
        )
        rewritten = apply_entry_renames(entries, renames)
        self.assertEqual(
            page_map_contract_issues(rewritten, "S4_05", page_map), [])

    def test_default_s4_05_map_records_tail_and_backmatter(self):
        page_map = load_header_map("S4_05", None)
        self.assertIsNotNone(page_map)
        assert page_map is not None
        self.assertEqual(page_map["p-001.xhtml"], 1)
        self.assertEqual(page_map["p-012.xhtml"], 10)
        self.assertEqual(page_map["p-013.xhtml"], 10)
        self.assertIsNone(page_map["p-014.xhtml"])
        self.assertIsNone(page_map["p-015.xhtml"])

    def test_artifact_contract_rejects_unprefixed_images_and_broken_references(self):
        entries = {
            "mimetype": b"application/epub+zip",
            "META-INF/container.xml": (
                b'<container><rootfiles><rootfile full-path="item/standard.opf"/>'
                b'</rootfiles></container>'
            ),
            "item/standard.opf": b'<package><manifest>'
                                 b'<item href="image/missing.jpg"/>'
                                 b'</manifest></package>',
            "item/image/i-030.jpg": b"jpeg data",
        }
        issues = artifact_contract_issues(entries, "S4_05")
        self.assertTrue(any("图片缺少作品号表头" in issue for _, issue in issues))
        self.assertTrue(any("资源引用不存在" in issue for _, issue in issues))

    def test_artifact_contract_rejects_zero_content_sequence(self):
        entries = {
            "mimetype": b"application/epub+zip",
            "META-INF/container.xml": b"<container/>",
            "item/xhtml/S4_05-00_p-001.xhtml": b"<html/>",
        }
        issues = artifact_contract_issues(entries, "S4_05")
        self.assertTrue(any("内容序 -00 非法" in issue for _, issue in issues))

    def test_artifact_contract_accepts_prefixed_image_and_valid_references(self):
        entries = {
            "mimetype": b"application/epub+zip",
            "META-INF/container.xml": (
                b'<container><rootfiles><rootfile full-path="item/standard.opf"/>'
                b'</rootfiles></container>'
            ),
            "item/standard.opf": b'<package><manifest>'
                                 b'<item href="image/S4_05-i-030.jpg"/>'
                                 b'</manifest></package>',
            "item/image/S4_05-i-030.jpg": b"jpeg data",
        }
        self.assertEqual(artifact_contract_issues(entries, "S4_05"), [])

    def test_epub_zip_contract_requires_stored_first_mimetype(self):
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_DEFLATED
        issues = epub_zip_issues(
            [zipfile.ZipInfo("other"), mimetype],
            {"mimetype": b"application/epub+zip"},
        )
        self.assertTrue(any("第一个条目" in issue for _, issue in issues))

    def test_infer_book_id(self):
        from bw_preprocess import infer_book_id
        self.assertEqual(infer_book_id("とある暗部の少女共棲"), "S4_01")
        self.assertEqual(infer_book_id("とある暗部の少女共棲（２）"), "S4_02")
        self.assertEqual(infer_book_id("とある暗部の少女共棲(6)"), "S4_06")
        self.assertEqual(infer_book_id("創約 とある魔術の禁書目録(11)"), "S3_11")
        self.assertEqual(infer_book_id("[S4_05]とある暗部の少女共棲"), "S4_05")


if __name__ == "__main__":
    unittest.main()
