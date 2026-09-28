from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from search_text import (
    BilingualCorpus,
    ParsedRubyLine,
    SearchMatch,
    fold_text,
    format_search_results,
    highlight_match,
    match_line,
    parse_ruby_line,
    search_corpus,
)


class SearchTextTests(unittest.TestCase):
    def test_fold_text(self):
        # 1. 小字假名折叠为大字假名
        self.assertEqual(fold_text("カリキュラム"), "カリキユラム")
        self.assertEqual(fold_text("カリキユラム"), "カリキユラム")
        self.assertEqual(fold_text("エキシビジョン"), "エキシビジヨン")

        # 2. 全角英数转半角并小写
        self.assertEqual(fold_text("Ｌｅｖｅｌ５"), "level5")
        self.assertEqual(fold_text("Level 5"), "level 5")
        self.assertEqual(fold_text("＝"), "=")

    def test_parse_ruby_line_standard(self):
        # 标准整词注音
        raw = '<p>「ねえ、<ruby>超電磁砲<rt>レールガン</rt></ruby>って言葉、知ってる？」</p>'
        parsed = parse_ruby_line(raw, 10)
        self.assertEqual(parsed.formatted, "「ねえ、超電磁砲(レールガン)って言葉、知ってる？」")
        self.assertEqual(parsed.base, "「ねえ、超電磁砲って言葉、知ってる？」")
        self.assertEqual(parsed.rubies, ["レールガン"])
        self.assertEqual(parsed.line_no, 10)

    def test_parse_ruby_line_multiple_and_rp(self):
        # 连续单字注音 + rp 括号标签
        raw = '<p><ruby>上<rp>（</rp><rt>かみ</rt><rp>）</rp></ruby><ruby>条<rp>（</rp><rt>じよう</rt><rp>）</rp></ruby>当麻</p>'
        parsed = parse_ruby_line(raw, 25)
        self.assertEqual(parsed.formatted, "上(かみ)条(じよう)当麻")
        self.assertEqual(parsed.base, "上条当麻")
        self.assertEqual(parsed.rubies, ["かみ", "じよう"])

    def test_match_line_base_track(self):
        # 基文匹配：即便原 HTML 中汉字被 ruby 标签打碎，也能命中
        raw = '<p>学園都市の<ruby>超<rt>レ</rt></ruby><ruby>能<rt>ベ</rt></ruby><ruby>力<rt>ル</rt></ruby><ruby>者<rt>５</rt></ruby>なのよ</p>'
        parsed = parse_ruby_line(raw, 1)

        # 搜纯基文 "超能力者"
        res = match_line(parsed, "超能力者")
        self.assertIsNotNone(res)
        track, hl = res
        self.assertEqual(track, "base")

    def test_match_line_ruby_track(self):
        # 注音匹配：搜假名读音直接命中
        raw = '<p><ruby>幻想殺し<rt>イマジンブレイカー</rt></ruby>の右手</p>'
        parsed = parse_ruby_line(raw, 1)

        res = match_line(parsed, "イマジンブレイカー")
        self.assertIsNotNone(res)
        track, hl = res
        self.assertEqual(track, "ruby")
        self.assertIn("**イマジンブレイカー**", hl)

    def test_match_line_kana_folding(self):
        # 折叠匹配：用户搜不妥协写法（小字），文本中是源的大字妥协形
        raw = '<p>能力開発の<ruby>時間割り<rt>カリキユラム</rt></ruby>である。</p>'
        parsed = parse_ruby_line(raw, 5)

        # 用户搜小字 "カリキュラム"
        res = match_line(parsed, "カリキュラム")
        self.assertIsNotNone(res)
        track, hl = res
        self.assertEqual(track, "ruby")

    def test_bilingual_corpus_mock(self):
        # 创建模拟双语语料库
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            cn_dir = temp_path / "chinese"
            jp_dir = temp_path / "japanese"

            cn_book = cn_dir / "[S1_01]某魔法的禁书目录 01" / "item" / "xhtml"
            jp_book = jp_dir / "[S1_01]とある魔術の禁書目録(01)" / "item" / "xhtml"
            cn_book.mkdir(parents=True)
            jp_book.mkdir(parents=True)

            # 写入对齐的测试文件
            cn_file = cn_book / "S1_01-01_Prologue.xhtml"
            jp_file = jp_book / "S1_01-01.xhtml"

            cn_content = "\n".join([
                "<?xml version='1.0' encoding='utf-8'?>",
                "<!DOCTYPE html>",
                "<html><head></head><body>",
                "<h1>序章</h1>",
                "",
                "<p>呐，你听说过超电磁炮吗？</p>",
                "<p>幻想杀手是右手的力量。</p>",
            ])
            jp_content = "\n".join([
                "<?xml version='1.0' encoding='utf-8'?>",
                "<!DOCTYPE html>",
                "<html><head></head><body>",
                "<h1>プロローグ</h1>",
                "",
                "<p>「ねえ、<ruby>超電磁砲<rt>レールガン</rt></ruby>って言葉、知ってる？」</p>",
                "<p><ruby>幻想殺し<rt>イマジンブレイカー</rt></ruby>は右手の力だ。</p>",
            ])

            cn_file.write_text(cn_content, encoding="utf-8")
            jp_file.write_text(jp_content, encoding="utf-8")

            corpus = BilingualCorpus(cn_dir=cn_dir, jp_dir=jp_dir)

            # 1. 搜中文，联动出日文
            matches_cn = search_corpus(corpus, "超电磁炮", side="cn")
            self.assertEqual(len(matches_cn), 1)
            m = matches_cn[0]
            self.assertEqual(m.side, "cn")
            self.assertEqual(m.line_no, 6)
            self.assertIsNotNone(m.paired_line)
            self.assertEqual(m.paired_line.formatted, "「ねえ、超電磁砲(レールガン)って言葉、知ってる？」")

            # 2. 搜日文注音，联动出中文
            matches_jp = search_corpus(corpus, "イマジンブレイカー", side="jp")
            self.assertEqual(len(matches_jp), 1)
            m_jp = matches_jp[0]
            self.assertEqual(m_jp.side, "jp")
            self.assertEqual(m_jp.line_no, 7)
            self.assertIsNotNone(m_jp.paired_line)
            self.assertEqual(m_jp.paired_line.formatted, "幻想杀手是右手的力量。")

            # 3. 格式化测试
            md_out = format_search_results(matches_jp, output_format="markdown", query="イマジンブレイカー")
            self.assertIn("#### [S1_01]", md_out)
            self.assertIn("对应中文 (L7)", md_out)


if __name__ == "__main__":
    unittest.main()
