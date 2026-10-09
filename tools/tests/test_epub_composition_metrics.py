from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from epub_char_count import EpubSource
from epub_composition_metrics import (
    image_anchors,
    is_page_anchor,
    page_ref_of,
    ref_str,
    scan_book,
    sub_offsets,
)


def make_book(root: Path, pages: dict[str, str]) -> Path:
    """最小解包书目录：`pages` 是 {文件名: body 内容}，按传入顺序进 spine。"""
    book = root / "[S1_01]测试书"
    (book / "META-INF").mkdir(parents=True)
    (book / "OEBPS" / "Text").mkdir(parents=True)
    (book / "OEBPS" / "Images").mkdir(parents=True)
    (book / "META-INF" / "container.xml").write_text(
        '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        encoding="utf-8")
    items, refs = [], []
    for index, (name, body) in enumerate(pages.items(), 1):
        (book / "OEBPS" / "Text" / name).write_text(
            "\n".join(["<?xml version='1.0' encoding='utf-8'?>", "<!DOCTYPE html>",
                       "<html><head><title></title></head><body>", "", "", body, "</body></html>"]),
            encoding="utf-8")
        items.append(f'<item id="p{index}" href="Text/{name}" media-type="application/xhtml+xml"/>')
        refs.append(f'<itemref idref="p{index}"/>')
    (book / "OEBPS" / "content.opf").write_text(
        "<package><manifest>" + "".join(items) + "</manifest><spine>" + "".join(refs) + "</spine></package>",
        encoding="utf-8")
    return book


class PageRefTests(unittest.TestCase):
    def test_page_ref_parses_printed_page_and_range(self):
        self.assertEqual(page_ref_of("../Images/S1_01-i-045.jpg"), (45, 45))
        self.assertEqual(page_ref_of("S1_01-i-314-315.jpg"), (314, 315))
        self.assertEqual(page_ref_of("S1_01-kuchie-003-005.jpg"), (3, 5))
        self.assertEqual(page_ref_of("S1_01-cover.jpg"), None)
        self.assertEqual(page_ref_of("S1_01-i-0007.png"), (7, 7))

    def test_reversed_range_is_normalised(self):
        self.assertEqual(page_ref_of("S1_01-i-315-314.jpg"), (314, 315))

    def test_page_anchor_excludes_front_matter_images(self):
        self.assertTrue(is_page_anchor("S1_01-i-045.jpg"))
        self.assertTrue(is_page_anchor("S1_01-i-045-046.jpg"))
        self.assertFalse(is_page_anchor("S1_01-kuchie-003-005.jpg"))   # 彩页不作印刷页锚点
        self.assertFalse(is_page_anchor("S1_01-cover.jpg"))

    def test_image_anchors_keep_document_order(self):
        raw = ('<p><img src="../Images/S1_01-i-010.jpg"/></p>'
               '<p><img src="../Images/S1_01-i-050.jpg"/></p>')
        self.assertEqual(image_anchors(raw),
                         [("../Images/S1_01-i-010.jpg", (10, 10)),
                          ("../Images/S1_01-i-050.jpg", (50, 50))])

    def test_ref_str_formats_single_page_and_range(self):
        self.assertEqual(ref_str(45, 45), "p.45")
        self.assertEqual(ref_str(314, 315), "p.314-315")
        self.assertEqual(ref_str(0, 0), "")

    def test_sub_offsets_point_at_each_h2(self):
        raw = "<h1>第一章</h1><p>开场</p><h2>一</h2><p>甲</p><h2>二</h2><p>乙</p>"
        offsets = sub_offsets(raw)
        self.assertEqual(len(offsets), 2)
        for offset in offsets:
            self.assertTrue(raw.startswith("<h2", offset), raw[offset:offset + 4])


class PrintedPageAnalysisTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_printed_pages_are_measured_and_monotonic(self):
        """印刷页来自插图文件名，成分区间按字符比例内插，严格递增不重叠。"""
        body = ("<h1>第一章</h1><h2>一</h2><p>" + "甲" * 100 + "</p>"
                '<p class="fit"><img src="../Images/S1_01-i-010.jpg"/></p>'
                "<h2>二</h2><p>" + "乙" * 100 + "</p>"
                '<p class="fit"><img src="../Images/S1_01-i-050.jpg"/></p>')
        book = make_book(self.root, {"S1_01-01_Chapter1.xhtml": body})
        report = scan_book(EpubSource(book), pages_per=400, include_all=False)
        totals = report["totals"]
        self.assertEqual((totals["printed_from"], totals["printed_to"]), (10, 50))
        self.assertEqual(totals["printed_pages"], 41)
        component = report["components"][0]
        # 锚点页来自实测：成分起点不早于首个锚点所在书首推算区，终点落在末锚点之后
        self.assertLessEqual(component["page_start"], 10)
        self.assertGreaterEqual(component["page_end"], 50)
        self.assertEqual([a for a in component["anchors"]], [(10, 10), (50, 50)])
        previous_end = 0
        for sub in component["subs"]:
            self.assertGreater(sub["page_start"], previous_end)
            self.assertGreaterEqual(sub["page_end"], sub["page_start"])
            previous_end = sub["page_end"]

    def test_anchor_coverage_and_pages_sum(self):
        body = ("<h1>第一章</h1><p>" + "甲" * 200 + "</p>"
                '<p class="fit"><img src="../Images/S1_01-i-020.jpg"/></p>')
        book = make_book(self.root, {"S1_01-01_Chapter1.xhtml": body})
        report = scan_book(EpubSource(book), pages_per=400, include_all=False)
        self.assertEqual(report["totals"]["anchor_coverage"], 1.0)
        component = report["components"][0]
        self.assertEqual(component["pages"], component["page_end"] - component["page_start"] + 1)

    def test_kuchie_images_do_not_become_printed_anchors(self):
        body = ('<p>' + "甲" * 100 + "</p>"
                '<p class="fit"><img src="../Images/S1_01-kuchie-003-005.jpg"/></p>')
        book = make_book(self.root, {"S1_01-01_Chapter1.xhtml": body})
        report = scan_book(EpubSource(book), pages_per=400, include_all=False)
        self.assertEqual(report["components"][0]["anchors"], [])
        self.assertEqual(report["totals"]["printed_pages"], 0)

    def test_component_page_ranges_do_not_overlap(self):
        """相邻成分取整后可能重叠，扫描时按顺序压实。"""
        pages = {
            "S1_01-01_Chapter1.xhtml": "<h1>第一章</h1><p>" + "甲" * 120 + "</p>",
            "S1_01-02_Chapter2.xhtml": "<h1>第二章</h1><p>" + "乙" * 120 + "</p>",
        }
        book = make_book(self.root, pages)
        report = scan_book(EpubSource(book), pages_per=400, include_all=False)
        spans = [(c["page_start"], c["page_end"]) for c in report["components"]]
        self.assertEqual(len(spans), 2)
        self.assertLess(spans[0][1], spans[1][0])
        self.assertEqual(report["totals"]["span_from"], spans[0][0])
        self.assertEqual(report["totals"]["span_to"], spans[1][1])

    def test_packaging_pages_are_skipped_unless_include_all(self):
        book = make_book(self.root, {
            "S1_01-Cover.xhtml": "<p>封面</p>",
            "S1_01-01_Chapter1.xhtml": "<h1>第一章</h1><p>" + "甲" * 30 + "</p>",
        })
        report = scan_book(EpubSource(book), pages_per=400, include_all=False)
        self.assertEqual([Path(c["path"]).name for c in report["components"]],
                         ["S1_01-01_Chapter1.xhtml"])
        self.assertIn("S1_01-Cover", report["skipped"])
        report_all = scan_book(EpubSource(book), pages_per=400, include_all=True)
        self.assertEqual(len(report_all["components"]), 2)


if __name__ == "__main__":
    unittest.main()
