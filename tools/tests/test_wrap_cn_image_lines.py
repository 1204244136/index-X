from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from wrap_cn_image_lines import normalize  # noqa: E402

IMG = '<img alt="图片" class="fit" src="../Images/a.jpg"/>'


def wrap(lines):
    return normalize(lines)


class WrapImageLineTests(unittest.TestCase):
    def test_bare_image_line_is_wrapped_in_p(self):
        out, wrapped, dropped = wrap(["<body>", IMG, "<p>正文</p>"])
        self.assertEqual(out, ["<body>", f"<p>{IMG}</p>", "<p>正文</p>"])
        self.assertEqual((wrapped, dropped), (1, 0))

    def test_already_wrapped_is_untouched(self):
        src = [f"<p>{IMG}</p>", '<p class="x">' + IMG + "</p>"]
        out, wrapped, dropped = wrap(src)
        self.assertEqual(out, src)
        self.assertEqual((wrapped, dropped), (0, 0))

    def test_multi_image_div_block_keeps_line_count_and_class(self):
        """漫画跨页块：div 开/闭标签行本身承载图片，逐图转 p 后行数必须不变。"""
        src = [
            '<div class="center"><img src="1.jpg"/>',
            '<img src="2.jpg"/>',
            '<img src="3.jpg"/></div>',
            "<h2>2</h2>",
        ]
        out, wrapped, dropped = wrap(src)
        self.assertEqual(wrapped, 3)
        self.assertEqual(dropped, 0)
        self.assertEqual(len(out), len(src))
        self.assertEqual(
            out,
            ['<p class="center"><img src="1.jpg"/></p>',
             '<p class="center"><img src="2.jpg"/></p>',
             '<p class="center"><img src="3.jpg"/></p>',
             "<h2>2</h2>"])

    def test_last_image_keeps_class_of_closing_line(self):
        """闭标签与图片同行的那张图，必须仍拿到该层 div 的 class（先输出后弹栈）。"""
        out, _, _ = wrap(['<div class="center"><img src="1.jpg"/>', '<img src="2.jpg"/></div>'])
        self.assertEqual(out[1], '<p class="center"><img src="2.jpg"/></p>')

    def test_non_image_div_is_never_touched(self):
        src = ['<div class="note">', "<p>文字内容</p>", "</div>"]
        out, wrapped, dropped = wrap(src)
        self.assertEqual(out, src)
        self.assertEqual((wrapped, dropped), (0, 0))

    def test_unbalanced_div_run_is_left_alone(self):
        """div 开闭不配平（跨区段）时绝不猜测解包装。"""
        src = ['<div class="center"><img src="1.jpg"/>', "<p>正文</p>", "</div>"]
        out, wrapped, dropped = wrap(src)
        self.assertEqual(out, src)

    def test_svg_image_element_is_never_touched(self):
        src = ['<svg width="10" height="10">',
              '<image width="10" height="10" xlink:href="../Images/x.jpg"/>',
              "</svg>"]
        out, wrapped, dropped = wrap(src)
        self.assertEqual(out, src)
        self.assertEqual((wrapped, dropped), (0, 0))

    def test_interleaved_single_image_divs_collapse_to_p_per_image(self):
        src = ["<div>" + IMG,
               "</div><div>",
               '<img src="b.jpg"/></div>']
        out, wrapped, dropped = wrap(src)
        self.assertEqual(wrapped, 2)
        self.assertEqual(dropped, 1)
        self.assertEqual(out, [f"<p>{IMG}</p>", '<p><img src="b.jpg"/></p>'])


if __name__ == "__main__":
    unittest.main()
