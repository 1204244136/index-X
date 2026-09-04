from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from merge_bw_pages import (  # noqa: E402
    attach_nav_titles,
    collect_pages,
    group_units,
    leading_image_pages,
    merge_unit,
    nav_page_titles,
)

BOOK = "S9_99"

# BW 图片扉页：整页 SVG 插图，无 body class，章名画在图里
IMAGE_PAGE = (
    "<?xml version='1.0' encoding='utf-8'?>\n"
    "<!DOCTYPE html>\n"
    '<html xmlns="http://www.w3.org/1999/xhtml"\n'
    ' xmlns:epub="http://www.idpf.org/2007/ops"\n'
    ' xml:lang="ja"\n'
    ">\n"
    "<head>\n"
    '<meta charset="UTF-8"/>\n'
    "<title>测试</title>\n"
    '<link rel="stylesheet" type="text/css" href="../style/fixed-layout-jp.css"/>\n'
    "</head>\n"
    "<body>\n"
    '<div class="main" id="toc-002">\n'
    '<svg xmlns="http://www.w3.org/2000/svg" version="1.1"\n'
    ' xmlns:xlink="http://www.w3.org/1999/xlink" width="100%" height="100%">\n'
    '<image width="100" height="100" xlink:href="../image/S9_99-m-002.jpg"/>\n'
    "</svg>\n"
    "</div>\n"
    "</body>\n"
    "</html>\n"
)

# 正文页：竖排 p-text，首小节在 L5 槽位
TEXT_PAGE = (
    "<?xml version='1.0' encoding='utf-8'?>\n"
    "<!DOCTYPE html>\n"
    '<html xmlns="http://www.w3.org/1999/xhtml"\n'
    ' xml:lang="ja"\n'
    ' class="vrtl"\n'
    ">\n"
    "<head>\n"
    '<meta charset="UTF-8"/>\n'
    "<title>测试</title>\n"
    '<link rel="stylesheet" type="text/css" href="../style/book-style.css"/>\n'
    "</head>\n"
    '<body class="p-text">\n'
    '<div class="main">\n'
    "\n"
    "<h2>１</h2>\n"
    "<p>正文甲。</p>\n"
    "<p>正文乙。</p>\n"
    "</div>\n"
    "</body>\n"
    "</html>\n"
)

NAV = (
    "<?xml version='1.0' encoding='utf-8'?>\n"
    "<!DOCTYPE html>\n"
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title/></head><body>\n'
    '<nav>\n'
    f'<a href="xhtml/{BOOK}-01_p-001.xhtml#toc-002">第一章 白井黒子は躊躇わない</a>\n'
    f'<a href="xhtml/{BOOK}-01_p-002.xhtml">（续页，不应作为单元首页标题）</a>\n'
    "</nav>\n"
    "</body></html>\n"
)


def _write(root: Path, name: str, text: str) -> None:
    (root / "xhtml" / name).parent.mkdir(parents=True, exist_ok=True)
    (root / "xhtml" / name).write_text(text, encoding="utf-8")


class ImageTitlePageMergeTests(unittest.TestCase):
    def _units(self, root: Path, *, with_nav: bool):
        if with_nav:
            _write(root, "navigation-documents.xhtml", NAV)
        notes: list[str] = []
        pages = collect_pages(root)
        units = group_units(pages, notes)
        nav_text = (root / "xhtml" / "navigation-documents.xhtml").read_text(
            encoding="utf-8") if with_nav else None
        attach_nav_titles(units, nav_text, notes)
        return units, notes

    def _merge(self, root: Path, *, with_nav: bool = True):
        units, notes = self._units(root, with_nav=with_nav)
        self.assertEqual(len(units), 1, "图片扉页与正文页应属于同一单元")
        return merge_unit(units[0], notes), notes

    def test_image_is_folded_into_l3_and_head_comes_from_text_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, f"{BOOK}-01_p-001.xhtml", IMAGE_PAGE)
            _write(root, f"{BOOK}-01_p-002.xhtml", TEXT_PAGE)
            out, _ = self._merge(root)
            self.assertIn("book-style.css", out[2], "L3 必须取自文本页，否则正文套用固定版面 CSS")
            self.assertIn('class="p-text"', out[2])
            self.assertIn('class="vrtl"', out[2].split("<head>")[0])
            self.assertIn("<image", out[2], "篇首插图应并入 L3 头部行")
            self.assertNotIn("<svg", out[5], "正文区不应再占一行图片")

    def test_nav_title_fills_h1_and_first_section_returns_to_l5(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, f"{BOOK}-01_p-001.xhtml", IMAGE_PAGE)
            _write(root, f"{BOOK}-01_p-002.xhtml", TEXT_PAGE)
            out, _ = self._merge(root)
            self.assertEqual(out[3], "<h1>第一章 白井黒子は躊躇わない</h1>")
            self.assertEqual(out[4], "<h2>１</h2>")
            self.assertEqual(out[5], "<p>正文甲。</p>")

    def test_without_nav_l4_stays_blank_but_slots_still_correct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, f"{BOOK}-01_p-001.xhtml", IMAGE_PAGE)
            _write(root, f"{BOOK}-01_p-002.xhtml", TEXT_PAGE)
            out, notes = self._merge(root, with_nav=False)
            self.assertEqual(out[3], "", "补不到目录标题时 L4 必须留空槽，不得猜测")
            self.assertEqual(out[4], "<h2>１</h2>")
            self.assertEqual(out[5], "<p>正文甲。</p>")
            self.assertTrue(any("缺目录标题" in n for n in notes), notes)

    def test_line_count_shrinks_by_exactly_the_folded_slots(self):
        """折叠图片行 + 上提 h2 → 比旧行为少 2 行，且总行数 = 头部3 + L4 + L5 + 正文 + 闭标签。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, f"{BOOK}-01_p-001.xhtml", IMAGE_PAGE)
            _write(root, f"{BOOK}-01_p-002.xhtml", TEXT_PAGE)
            out, _ = self._merge(root)
            self.assertEqual(len(out), 3 + 2 + 2 + 1)
            self.assertEqual(out[-1], "</body></html>")

    def test_leading_image_detection_skips_units_with_real_h1(self):
        """守卫：单元已有文本 h1 时绝不走图片扉页路径，避免波及既有已对齐的书。"""
        fake_page = {"is_image_page": True, "is_p_text": False}
        unit = {"h1": "第一章", "pages": [fake_page, fake_page]}
        self.assertEqual(leading_image_pages(unit), [])
        unit_no_h1 = {"h1": None, "pages": [fake_page, fake_page]}
        self.assertEqual(leading_image_pages(unit_no_h1), [0, 1])

    def test_fold_needs_a_text_page_in_the_unit(self):
        """纯图片单元（无文本页可取头部）不折叠，保持原有头部来源。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, f"{BOOK}-01_p-001.xhtml", IMAGE_PAGE)
            notes: list[str] = []
            units = group_units(collect_pages(root), notes)
            attach_nav_titles(units, None, notes)
            out = merge_unit(units[0], notes)
            self.assertIn("fixed-layout-jp.css", out[2], "无文本页时仍用图片页头部")
            self.assertTrue(any("<image" in l for l in out[3:]),
                            "无文本页可借头部时，图片应继续作为正文行，不并入 L3")

    def test_nav_parser_only_accepts_page_anchors(self):
        titles = nav_page_titles(NAV)
        self.assertEqual(titles, {f"{BOOK}-01_p-001.xhtml": "第一章 白井黒子は躊躇わない"})


if __name__ == "__main__":
    unittest.main()
