from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xhtml_text import (
    RT_ELEMENT,
    RUBY_ELEMENT,
    strip_ruby_annotations,
    text_of,
    text_of_without_ruby,
    visible_text_of,
)


class XhtmlTextTests(unittest.TestCase):
    """注音剥除与纯文本提取的唯一实现：三种口径各测正例与边界。"""

    RUBY = "<p><ruby>超電磁砲<rt>レールガン</rt></ruby>はすごい</p>"

    def test_text_of_keeps_readings(self):
        """复核口径保留注音，否则注音改动不会出现在 diff 里。"""
        self.assertEqual(text_of(self.RUBY.encode("utf-8")), "超電磁砲 レールガン はすごい")

    def test_text_of_without_ruby_drops_readings(self):
        """原文检索口径先剥注音，避免 `魔術サイド` 被拆成 `魔術 まじゆつ サイド`。"""
        self.assertEqual(text_of_without_ruby(self.RUBY.encode("utf-8")), "超電磁砲 はすごい")

    def test_visible_text_drops_rt_but_keeps_rp_brackets(self):
        """可见文本比较剥 <rt>，但保留 <rp> 的可见括号。"""
        html = "<p><ruby>水<rp>(</rp><rt>みず</rt><rp>)</rp></ruby>の星</p>"
        self.assertEqual(visible_text_of(html), "水()の星")
        self.assertEqual(strip_ruby_annotations(html), "<p><ruby>水</ruby>の星</p>")

    def test_cross_line_rt_is_removed(self):
        """<rt> 内容跨行时同样整体移除（正则带 re.S）。"""
        html = "<p><ruby>水<rt>みず\nがめ</rt></ruby></p>"
        self.assertEqual(strip_ruby_annotations(html), "<p><ruby>水</ruby></p>")
        self.assertEqual(text_of_without_ruby(html.encode("utf-8")), "水")

    def test_no_ruby_input_is_unchanged_by_stripping(self):
        """无注音时剥除是恒等变换，调用方不会因为走共享实现而改变输入。"""
        plain = "<p>ただの本文</p>"
        self.assertEqual(strip_ruby_annotations(plain), plain)
        self.assertEqual(visible_text_of(plain), "ただの本文")

    def test_script_and_style_are_not_counted(self):
        """脚本与样式表不进正文文本（保持 text_of 既有口径）。"""
        html = "<html><head><style>p{color:red}</style></head><body><p>本文</p></body></html>"
        self.assertEqual(text_of(html.encode("utf-8")), "本文")

    def test_entities_are_unescaped(self):
        """实体反转义后再折叠空白，含 `&` 的术语才能比对（R&amp;C → R&C）。"""
        html = "<p>R&amp;C\u3000\u3000\u3000超自然公司</p>"
        self.assertEqual(text_of(html.encode("utf-8")), "R&C 超自然公司")

    def test_patterns_match_only_annotation_elements(self):
        """锚点误伤防线：`<rt>` 规则不吞 `<ruby>`，`<rt>`/`<rp>` 规则不动正文标签。"""
        self.assertIsNone(RUBY_ELEMENT.search("<ruby>水</ruby>"))
        self.assertIsNone(RT_ELEMENT.search("<ruby>水</ruby>"))
        self.assertEqual(RT_ELEMENT.sub("", "<rt>x</rt>水<rp>(</rp>"), "水<rp>(</rp>")


if __name__ == "__main__":
    unittest.main()
