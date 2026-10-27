from __future__ import annotations

import subprocess
import sys
import tempfile
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


def page(*body):
    return "\n".join(['<?xml version="1.0"?>', '<!DOCTYPE html>', '<html><head/><body>',
                      '<h1>章</h1>', '', '<p>正文</p>', *body, '</body></html>', ''])


class ImageReferenceCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.cn, self.jp = root / "cn", root / "jp"
        self.cn_book, self.jp_book = self.cn / "【S1_01】中文", self.jp / "【S1_01】日文"
        self.cn_book.mkdir(parents=True)
        self.jp_book.mkdir(parents=True)
        self.cn_file = self.cn_book / "S1_01-01.xhtml"
        self.jp_file = self.jp_book / "S1_01-01.xhtml"
        self.cn_file.write_text(page('<div class="fit">', '<img src="image.jpg"/>', '</div>'), encoding="utf-8")
        self.jp_file.write_text(page('<p class="fit"><img src="image.jpg"/></p>'), encoding="utf-8")

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(TOOLS / "wrap_cn_image_lines.py"),
                               "--root", str(self.cn), "--jp-root", str(self.jp),
                               "--staging", "--apply", *args], capture_output=True,
                              text=True, encoding="utf-8", timeout=20)

    def test_structure_cleanup_requires_the_actual_reference_file(self):
        self.jp_file.unlink()
        before = self.cn_file.read_bytes()
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("日文参考", result.stderr)
        self.assertEqual(self.cn_file.read_bytes(), before)

    def test_aligned_cleanup_is_allowed_but_length_mismatch_is_refused(self):
        self.jp_file.write_text(page('<p class="fit"><img src="image.jpg"/></p>', '<p>额外</p>'), encoding="utf-8")
        before = self.cn_file.read_bytes()
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.cn_file.read_bytes(), before)
        self.jp_file.write_text(page('<p class="fit"><img src="image.jpg"/></p>'), encoding="utf-8")
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('<p class="fit"><img', self.cn_file.read_text(encoding="utf-8"))
        self.assertEqual(len(self.cn_file.read_text(encoding="utf-8").splitlines()),
                         len(self.jp_file.read_text(encoding="utf-8").splitlines()))

    def test_a_later_missing_reference_blocks_all_writes(self):
        sibling = self.cn_file.with_name("S1_01-02.xhtml")
        sibling.write_bytes(self.cn_file.read_bytes())
        before = {path: path.read_bytes() for path in (self.cn_file, sibling)}
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_unknown_book_does_not_report_success(self):
        result = self.run_cli("--book", "S1_99")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
