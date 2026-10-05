from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from japanese_lookup import (
    JapaneseSourceLookup,
    strip_rt_and_tags,
    to_ruby_markup,
    strip_ruby_markup,
)


class JapaneseLookupTests(unittest.TestCase):
    def test_strip_rt_and_tags(self):
        html = '<p>彼女の<ruby>横槍<rt>よこやり</rt></ruby>がなければ<ruby>浜面<rt>はまづら</rt></ruby>達は助からなかった。</p>'
        cleaned = strip_rt_and_tags(html)
        self.assertEqual(cleaned, "彼女の横槍がなければ浜面達は助からなかった。")

    def test_to_ruby_markup(self):
        # 汉化组标准标记 |基文[注音] 测试
        html = '<p>彼女の<ruby>横槍<rt>よこやり</rt></ruby>がなければ<ruby>浜面<rt>はまづら</rt></ruby>達は助からなかった。</p>'
        markup = to_ruby_markup(html)
        self.assertEqual(markup, "彼女の|横槍[よこやり]がなければ|浜面[はまづら]達は助からなかった。")

        # 快速还原基文
        self.assertEqual(strip_ruby_markup(markup), "彼女の横槍がなければ浜面達は助からなかった。")

    def test_multi_segment_ruby_markup(self):
        # 多段注音合并
        html = '<p>学園都市の<ruby>超<rt>レ</rt>能<rt>ベ</rt>力<rt>ル</rt>者<rt>５</rt></ruby>なのよ</p>'
        markup = to_ruby_markup(html)
        self.assertEqual(markup, "学園都市の|超能力者[レベル５]なのよ")
        self.assertEqual(strip_ruby_markup(markup), "学園都市の超能力者なのよ")

    def test_strip_rp_and_entities(self):
        html = '<p>『Ｒ&amp;Ｃオカルティクス』<ruby>魔術<rp>(</rp><rt>まじゅつ</rt><rp>)</rp></ruby></p>'
        cleaned = strip_rt_and_tags(html)
        self.assertEqual(cleaned, "『Ｒ&Ｃオカルティクス』魔術")
        markup = to_ruby_markup(html)
        self.assertEqual(markup, "『Ｒ&Ｃオカルティクス』|魔術[まじゅつ]")

    def test_resolve_jp_filename(self):
        lookup = JapaneseSourceLookup()
        self.assertEqual(lookup.resolve_jp_filename("S3_03", "S3_03-04_Chapter2.xhtml"), "S3_03-04.xhtml")
        self.assertEqual(lookup.resolve_jp_filename("S3_03", "04"), "S3_03-04.xhtml")
        self.assertEqual(lookup.resolve_jp_filename("S3_03", "4"), "S3_03-04.xhtml")
        self.assertEqual(lookup.resolve_jp_filename("S5_01_03", "S5_01_03-02_Chapter2.xhtml"), "S5_01_03-02.xhtml")


if __name__ == "__main__":
    unittest.main()
