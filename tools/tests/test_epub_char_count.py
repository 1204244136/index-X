from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from epub_char_count import (
    EpubSource,
    apply_label_rules,
    h2_label_of,
    is_wrapper,
    normalize_label,
    scan_book,
    spine_xhtml_items,
    split_sections,
    text_of,
)


def make_book(root: Path, pages: dict[str, str], *, nav: bool = True, fixed_layout: str = "",
              title: str = "") -> Path:
    """最小解包书目录：`pages` 是 {文件名: body 内容}，按传入顺序进 spine。

    `fixed_layout` 给出需要标成 pre-paginated 的文件名（固定版式包装页）；
    `title` 非空时写进 `<head><title>`，用于验证 head 文字是否计入。
    """
    book = root / "[S1_01]测试书"
    (book / "META-INF").mkdir(parents=True)
    (book / "OEBPS" / "Text").mkdir(parents=True)
    (book / "META-INF" / "container.xml").write_text(
        '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        encoding="utf-8")
    items, refs = [], []
    for index, (name, body) in enumerate(pages.items(), 1):
        (book / "OEBPS" / "Text" / name).write_text(
            "\n".join(["<?xml version='1.0' encoding='utf-8'?>", "<!DOCTYPE html>",
                       f"<html><head><title>{title}</title></head><body>", "", "", body, "</body></html>"]),
            encoding="utf-8")
        items.append(f'<item id="p{index}" href="Text/{name}" media-type="application/xhtml+xml"/>')
        # 固定版式标记在 spine 的 itemref 上（EPUB 3 的 pre-paginated）
        props = ' properties="pre-paginated"' if name == fixed_layout else ""
        refs.append(f'<itemref idref="p{index}"{props}/>')
    if nav:
        (book / "OEBPS" / "Text" / "nav.xhtml").write_text("<html><body><nav/></body></html>", encoding="utf-8")
        items.append('<item id="nav" href="Text/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
    (book / "OEBPS" / "content.opf").write_text(
        "<package><manifest>" + "".join(items) + "</manifest><spine>" + "".join(refs) + "</spine></package>",
        encoding="utf-8")
    return book


class TextPipelineTests(unittest.TestCase):
    def test_text_of_strips_ruby_tags_entities_and_all_whitespace(self):
        """字数口径：去注音、去标签、解实体、去全部空白（注音不重复计数）。"""
        raw = "<p>彼女の<ruby>超<rt>レ</rt>能<rt>ベ</rt>力<rt>ル</rt>者<rt>５</rt></ruby>なのよ</p>"
        self.assertEqual(text_of(raw), "彼女の超能力者なのよ")
        self.assertEqual(text_of("<p>R&amp;C\u3000超自然公司</p>"), "R&C超自然公司")

    def test_normalize_label_truncates_and_translates(self):
        """成分名规范化：章节标题截断为「序章/第N章/终章」，日文常用词转中文。"""
        self.assertEqual(normalize_label("第一章 魔法师她降临在高塔"), "第一章")
        self.assertEqual(normalize_label("序章 某少年的日常"), "序章")
        self.assertEqual(normalize_label("終章 而后，故事继续"), "终章")
        self.assertEqual(normalize_label("あとがき"), "后记")
        self.assertEqual(normalize_label("行間 一"), "行间一")

    def test_apply_label_rules_marks_intro_and_epilogue(self):
        """位置规则：第一个「序章」之前 → 引子；第一个「后记」之后 → 尾声。"""
        comps = [{"label": "某短篇"}, {"label": "序章"}, {"label": "第一章"},
                 {"label": "后记"}, {"label": "著者介绍"}]
        apply_label_rules(comps)
        self.assertEqual([c["label"] for c in comps],
                         ["引子", "序章", "第一章", "后记", "尾声"])

    def test_h2_label_uses_fullwidth_to_halfwidth_digits(self):
        self.assertEqual(h2_label_of("<h2>３ 小节</h2>"), "3 小节")

    def test_split_sections_merges_pre_h2_text_and_keeps_h1_out(self):
        """子成分不含 h1；h1 之前的开场文字并入第一节，且字数守恒。"""
        raw = ("<h1>第一章</h1><p>开场</p><h2>1 小标题</h2><p>甲</p>"
               "<h2>2 小标题</h2><p>乙</p>")
        sections = split_sections(raw)
        self.assertEqual([label for label, _ in sections], ["1 小标题", "2 小标题"])
        self.assertIn("开场", sections[0][1])
        self.assertNotIn("<h1", "".join(seg for _, seg in sections))
        self.assertEqual(len(text_of(raw)),
                         len(text_of(raw[raw.index("<h1"):raw.index("</h1>") + 5]))
                         + sum(len(text_of(seg)) for _, seg in sections))

    def test_wrapper_detection_uses_filename_or_title(self):
        self.assertTrue(is_wrapper("Cover", "OEBPS/Text/S1_01-Cover.xhtml"))
        self.assertTrue(is_wrapper("目次", "OEBPS/Text/x.xhtml"))
        self.assertFalse(is_wrapper("第一章", "OEBPS/Text/S1_01-01_Chapter1.xhtml"))


class ScanBookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_scan_skips_nav_wrapper_and_fixed_layout_pages(self):
        """默认只统计正文成分：nav 不进成分表，包装页与固定版式页进 skipped。"""
        book = make_book(self.root, {
            "S1_01-Cover.xhtml": "<p>封面文字</p>",
            "S1_01-01_Chapter1.xhtml": "<p>" + "正" * 30 + "</p>",
            "S1_01-02_Fixed.xhtml": "<p>固定版式</p>",
        }, fixed_layout="S1_01-02_Fixed.xhtml")
        report = scan_book(book, pages_per=10, include_wrapper=False, min_chars=1, label_map={})
        names = [Path(c["path"]).name for c in report["components"]]
        self.assertEqual(names, ["S1_01-01_Chapter1.xhtml"])
        self.assertEqual(report["components"][0]["all_chars"], 30)
        self.assertEqual(report["components"][0]["pages"], 3)          # ceil(30 / 10)
        self.assertIn("S1_01-Cover", report["skipped"])
        self.assertIn("S1_01-02_Fixed", report["skipped"])
        self.assertNotIn("nav.xhtml", names)
        # 彩页（Illustrations）不在包装页关键词里：有文字就会进成分表，这是既有口径
        self.assertNotIn("Illustrations", " ".join(report["skipped"]))

    def test_include_wrapper_keeps_packaging_pages(self):
        book = make_book(self.root, {
            "S1_01-Cover.xhtml": "<p>封面文字</p>",
            "S1_01-01_Chapter1.xhtml": "<p>正文</p>",
        })
        report = scan_book(book, pages_per=10, include_wrapper=True, min_chars=1, label_map={})
        names = [Path(c["path"]).name for c in report["components"]]
        self.assertEqual(names, ["S1_01-Cover.xhtml", "S1_01-01_Chapter1.xhtml"])

    def test_pages_are_ceil_with_minimum_one(self):
        book = make_book(self.root, {
            "S1_01-01_Chapter1.xhtml": "<p>短</p>" + "<h2>一</h2><p>" + "字" * 21 + "</p>",
        })
        report = scan_book(book, pages_per=10, include_wrapper=False, min_chars=1, label_map={})
        component = report["components"][0]
        subs = component["sub_components"]
        self.assertTrue(subs)
        for sub in subs:
            self.assertEqual(sub["pages"], max(1, -(-sub["all_chars"] // 10)))
        # 章级页数 = 子成分页数之和
        self.assertEqual(component["pages"], sum(s["pages"] for s in subs))

    def test_normalize_applies_position_rules_to_components(self):
        book = make_book(self.root, {
            "S1_01-01_Before.xhtml": "<h1>某短篇</h1><p>正文</p>",
            "S1_01-02_Prologue.xhtml": "<h1>序章</h1><p>正文</p>",
            "S1_01-03_Afterwords.xhtml": "<h1>后记</h1><p>正文</p>",
            "S1_01-04_Extra.xhtml": "<h1>著者介绍</h1><p>正文</p>",
        })
        report = scan_book(book, pages_per=10, include_wrapper=False, min_chars=1, label_map={})
        self.assertEqual([c["label"] for c in report["components"]],
                         ["引子", "序章", "后记", "尾声"])
        report_raw = scan_book(book, pages_per=10, include_wrapper=False, min_chars=1,
                               label_map={}, normalize=False)
        self.assertEqual([c["label"] for c in report_raw["components"]],
                         ["某短篇", "序章", "后记", "著者介绍"])

    def test_min_chars_drops_short_pages(self):
        book = make_book(self.root, {
            "S1_01-01_Short.xhtml": "<p>短</p>",
            "S1_01-02_Long.xhtml": "<p>" + "长" * 12 + "</p>",
        })
        report = scan_book(book, pages_per=10, include_wrapper=False, min_chars=10, label_map={})
        self.assertEqual([Path(c["path"]).name for c in report["components"]],
                         ["S1_01-02_Long.xhtml"])

    def test_label_map_overrides_component_name(self):
        book = make_book(self.root, {"S1_01-01_Chapter1.xhtml": "<h1>第一章</h1><p>正文</p>"})
        report = scan_book(book, pages_per=10, include_wrapper=False, min_chars=1,
                           label_map={"S1_01-01_Chapter1": "开篇"})
        self.assertEqual(report["components"][0]["label"], "开篇")

    def test_head_text_is_counted_today(self):
        """现状口径：`<head>` 里的文字（如 `<title>`）也计入全字符。

        两个字数工具共用同一口径；若要改成只统计正文，须同时改实现、`tools/README.md`
        的字数口径说明与这里。
        """
        book = make_book(self.root, {"S1_01-01_Chapter1.xhtml": "<p>正</p>"}, title="标题")
        report = scan_book(book, pages_per=10, include_wrapper=False, min_chars=1, label_map={})
        self.assertEqual(report["components"][0]["all_chars"], 3)   # 标题(2) + 正(1)

    def test_directory_input_is_a_single_book(self):
        """解包目录按单本处理：EpubSource 读 container.xml 定位 OPF，不递归找 .epub。"""
        book = make_book(self.root, {"S1_01-01_Chapter1.xhtml": "<p>正文</p>"})
        source = EpubSource(book)
        self.assertEqual(source.book_name, book.name)
        items = [item["path"] for item in spine_xhtml_items(source)]
        self.assertIn("OEBPS/Text/S1_01-01_Chapter1.xhtml", items)


if __name__ == "__main__":
    unittest.main()
