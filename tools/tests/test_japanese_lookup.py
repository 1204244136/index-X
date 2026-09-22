from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from japanese_lookup import JapaneseSourceLookup, strip_rt_and_tags


class JapaneseLookupTests(unittest.TestCase):
    def test_strip_rt_and_tags(self):
        html = '<p>彼女の<ruby>横槍<rt>よこやり</rt></ruby>がなければ<ruby>浜面<rt>はまづら</rt></ruby>達は助からなかった。</p>'
        cleaned = strip_rt_and_tags(html)
        self.assertEqual(cleaned, "彼女の横槍がなければ浜面達は助からなかった。")

    def test_strip_rp_and_entities(self):
        html = '<p>『Ｒ&amp;Ｃオカルティクス』<ruby>魔術<rp>(</rp><rt>まじゅつ</rt><rp>)</rp></ruby></p>'
        cleaned = strip_rt_and_tags(html)
        self.assertEqual(cleaned, "『Ｒ&Ｃオカルティクス』魔術")

    def test_resolve_jp_filename(self):
        lookup = JapaneseSourceLookup()
        self.assertEqual(lookup.resolve_jp_filename("S3_03", "S3_03-04_Chapter2.xhtml"), "S3_03-04.xhtml")
        self.assertEqual(lookup.resolve_jp_filename("S3_03", "04"), "S3_03-04.xhtml")
        self.assertEqual(lookup.resolve_jp_filename("S3_03", "4"), "S3_03-04.xhtml")
        self.assertEqual(lookup.resolve_jp_filename("S5_01_03", "S5_01_03-02_Chapter2.xhtml"), "S5_01_03-02.xhtml")


if __name__ == "__main__":
    unittest.main()
