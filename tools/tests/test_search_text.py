from __future__ import annotations

import json
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import search_text

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
    def write_chinese(self, root: Path, wid: str, content: str) -> None:
        path = root / f"【{wid}】测试" / "OEBPS" / "Text" / f"{wid}-01_Chapter.xhtml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"<p>{content}</p>", encoding="utf-8")

    def run_default_sources(self, root: Path, *extra: str):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(search_text, "DEFAULT_CN_CACHE", root / "cache"), \
                patch.object(search_text, "DEFAULT_EPUB_DIR", root / "archive"), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = search_text.main(["中文", "--side", "cn", "--no-pair", "--format", "json",
                                     "--jp-root", str(root / "jp"), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_default_empty_cache_falls_back_to_available_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cache").mkdir()
            self.write_chinese(root / "archive", "S1_01", "中文归档")
            code, out, err = self.run_default_sources(root)
            self.assertEqual(code, 0, err)
            self.assertEqual(len(json.loads(out)), 1)

    def test_default_partial_cache_fills_missing_books_from_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_chinese(root / "cache", "S1_01", "中文缓存")
            self.write_chinese(root / "archive", "S1_02", "中文归档")
            code, out, err = self.run_default_sources(root, "--work", "S1_02")
            self.assertEqual(code, 0, err)
            self.assertEqual(len(json.loads(out)), 1)

    def test_default_cache_takes_precedence_for_the_same_book(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_chinese(root / "cache", "S1_01", "中文缓存")
            self.write_chinese(root / "archive", "S1_01", "中文归档")
            code, out, err = self.run_default_sources(root)
            self.assertEqual(code, 0, err)
            self.assertEqual(len(json.loads(out)), 1)
            self.assertIn("中文缓存", out)
            self.assertNotIn("中文归档", out)

    def test_explicit_empty_chinese_source_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "empty").mkdir()
            self.write_chinese(root / "archive", "S1_01", "中文归档")
            code, out, err = self.run_default_sources(root, "--cn-root", str(root / "empty"))
            self.assertEqual(code, 2)
            self.assertEqual(out, "")

    def test_cli_missing_query_reports_usage_on_stderr(self):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "search_text.py")],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr)

    def test_no_matches_preserves_output_format(self):
        self.assertEqual(json.loads(format_search_results([], "json", "absent")), [])
        self.assertEqual(
            format_search_results([], "tsv", "absent"),
            "Work\tSide\tFile\tLine\tTrack\tFormatted_Text\tPaired_Text",
        )
        for output_format in ("text", "markdown", "md"):
            with self.subTest(output_format=output_format):
                self.assertIn("未找到", format_search_results([], output_format, "absent"))

    def test_cli_unknown_work_is_setup_error_instead_of_zero_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cn = root / "cn" / "【S1_01】中文" / "OEBPS" / "Text"
            cn.mkdir(parents=True)
            (cn / "S1_01-01_Chapter.xhtml").write_text("<p>正文。</p>", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(TOOLS / "search_text.py"), "absent", "--side", "cn",
                 "--cn-root", str(root / "cn"), "--work", "S1_99", "--format", "json"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertIn("作品", result.stderr)

    def test_cli_no_matches_emits_parseable_json_and_tsv_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cn = root / "cn" / "【S1_01】中文" / "OEBPS" / "Text"
            cn.mkdir(parents=True)
            (cn / "S1_01-01_Chapter.xhtml").write_text("<p>正文。</p>", encoding="utf-8")
            for output_format in ("json", "tsv"):
                with self.subTest(output_format=output_format):
                    result = subprocess.run(
                        [sys.executable, str(TOOLS / "search_text.py"), "absent", "--side", "cn",
                         "--cn-root", str(root / "cn"), "--no-pair", "--format", output_format],
                        capture_output=True, text=True, encoding="utf-8", check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, "")
                    if output_format == "json":
                        self.assertEqual(json.loads(result.stdout), [])
                    else:
                        self.assertEqual(result.stdout.strip().split("\t"),
                                         ["Work", "Side", "File", "Line", "Track",
                                          "Formatted_Text", "Paired_Text"])

    def test_cli_missing_japanese_is_partial_for_both_but_error_for_jp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cn = root / "cn" / "【S1_01】中文" / "OEBPS" / "Text"
            cn.mkdir(parents=True)
            (cn / "S1_01-01_Chapter.xhtml").write_text("<p>正文。</p>", encoding="utf-8")
            command = [sys.executable, str(TOOLS / "search_text.py"), "正文",
                       "--cn-root", str(root / "cn"), "--jp-root", str(root / "missing-jp"),
                       "--format", "json"]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(json.loads(result.stdout)), 1)
            self.assertIn("日文", result.stderr)
            result = subprocess.run(command + ["--side", "jp"], capture_output=True,
                                    text=True, encoding="utf-8", check=False)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertIn("--jp-root", result.stderr)

    def test_explicit_missing_chinese_root_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(TOOLS / "search_text.py"), "正文", "--side", "cn",
                 "--cn-root", str(Path(directory) / "missing"), "--format", "json"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertIn("中文", result.stderr)

    def test_cli_invalid_regex_reports_setup_error_without_traceback(self):
        for output_format in ("json", "tsv"):
            with self.subTest(output_format=output_format):
                result = subprocess.run(
                    [sys.executable, str(TOOLS / "search_text.py"), "[", "--regex",
                     "--side", "cn", "--format", output_format],
                    capture_output=True, text=True, encoding="utf-8", check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("Traceback", result.stderr)

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

            cn_book = cn_dir / "【S1_01】某魔法的禁书目录 01" / "item" / "xhtml"
            jp_book = jp_dir / "【S1_01】とある魔術の禁書目録(01)" / "item" / "xhtml"
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

            corpus = BilingualCorpus(cn_dir=cn_dir, jp_dir=jp_dir, epub_dir=temp_path / "archive")

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
