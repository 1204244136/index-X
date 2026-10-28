from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from check_paired_text import (  # noqa: E402
    RUBY_COVERAGE_FLOOR,
    audit_coverage,
    main,
    scan_pair,
)

TRUNCATED_JP = (
    '<p>「……まだ、『<ruby>必要悪の教会<rt>ネセサリウス</rt></ruby>』への道が残っているとでも？」</p>'
)
TRUNCATED_CN = "<p>『必要之恶教会』</p>"


class ScanPairTests(unittest.TestCase):
    def test_truncation_detected(self):
        """中文只剩术语、日文是完整长句时命中。"""
        hits, _, _ = scan_pair([TRUNCATED_JP], [TRUNCATED_CN])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][0], 1)
        self.assertIn("必要之恶教会", hits[0][2])

    def test_complete_dialogue_not_flagged(self):
        """中文有句末标点的完整台词不判截断。"""
        cn = "<p>「……你是说，还有通往『必要之恶教会』的路？」</p>"
        hits, _, _ = scan_pair([TRUNCATED_JP], [cn])
        self.assertEqual(hits, [])

    def test_short_japanese_not_flagged(self):
        """日文本身是短句时不判截断。"""
        hits, _, _ = scan_pair(["<p>『はあ』</p>"], ["<p>『唉』</p>"])
        self.assertEqual(hits, [])

    def test_trailing_tone_not_flagged(self):
        """中文引号内含拖长音时视为语气效果，不判截断。"""
        jp = ["<p>「おおおおおおおおおおおおおおおおおおおおおおおおおおおおおお!!」</p>"]
        cn = ["<p>「哦————」</p>"]
        hits, _, _ = scan_pair(jp, cn)
        self.assertEqual(hits, [])

    def test_narration_truncation_not_flagged(self):
        """判据只覆盖对话行；叙述行不在本条范围。"""
        jp = ["<p>何者かが、図書館の中へと足を踏み入れてきたのだ。</p>"]
        cn = ["<p>有人踏进了图书馆。</p>"]
        hits, _, _ = scan_pair(jp, cn)
        self.assertEqual(hits, [])

    def test_ruby_counts_separate_term_readings(self):
        """片假名读音计入日文术语行；平假名读音不计。"""
        jp = [
            '<p>「<ruby>必要悪の教会<rt>ネセサリウス</rt></ruby>」</p>',
            "<p><ruby>五和<rt>いつわ</rt></ruby>は言った。</p>",
        ]
        cn = [
            '<p>「<ruby>必要之恶教会<rt>Necessarius</rt></ruby>」</p>',
            "<p>五和说道。</p>",
        ]
        _, jp_term, cn_ruby = scan_pair(jp, cn)
        self.assertEqual(jp_term, 1)
        self.assertEqual(cn_ruby, 1)


class AuditCoverageTests(unittest.TestCase):
    def _book(self, root: Path, cn_lines: list[str], jp_lines: list[str]) -> tuple[Path, Path]:
        cn_dir = root / "EPUB" / "【S1_01】测试书" / "OEBPS" / "Text"
        jp_dir = root / "jp" / "【S1_01】テスト" / "item" / "xhtml"
        cn_dir.mkdir(parents=True)
        jp_dir.mkdir(parents=True)
        (cn_dir / "S1_01-01_Chapter1.xhtml").write_text("\n".join(cn_lines) + "\n", encoding="utf-8")
        (jp_dir / "S1_01-01.xhtml").write_text("\n".join(jp_lines) + "\n", encoding="utf-8")
        return root / "EPUB", root / "jp"

    def test_low_ruby_coverage_listed_for_review(self):
        """术语型 ruby 达阈值、中文零注音时列入报告。"""
        with tempfile.TemporaryDirectory() as tmp:
            jp_lines = [
                f"<p><ruby>英国女王<rt>クイーンレグナント</rt></ruby>第{i}行</p>"
                for i in range(12)
            ]
            cn_lines = [f"<p>英国女王第{i}行</p>" for i in range(12)]
            cn_root, jp_root = self._book(Path(tmp), cn_lines, jp_lines)
            result = audit_coverage(cn_root, jp_root)
        self.assertEqual(len(result.coverage), 1)
        self.assertLess(result.coverage[0]["ratio"], RUBY_COVERAGE_FLOOR)
        self.assertEqual(result.coverage[0]["jp_term_lines"], 12)

    def test_covered_ruby_not_listed(self):
        """中文注音充足时不列入报告。"""
        with tempfile.TemporaryDirectory() as tmp:
            jp_lines = [
                f"<p><ruby>英国女王<rt>クイーンレグナント</rt></ruby>第{i}行</p>"
                for i in range(12)
            ]
            cn_lines = [
                f"<p><ruby>英国女王<rt>Queen Regnant</rt></ruby>第{i}行</p>"
                for i in range(12)
            ]
            cn_root, jp_root = self._book(Path(tmp), cn_lines, jp_lines)
            result = audit_coverage(cn_root, jp_root)
        self.assertEqual(result.coverage, [])

    def test_truncation_row_recorded(self):
        """截断命中写入 rows，带文件与行号。"""
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = self._book(Path(tmp), [TRUNCATED_CN], [TRUNCATED_JP])
            result = audit_coverage(cn_root, jp_root)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["line"], 1)
        self.assertEqual(result.rows[0]["kind"], "truncation")


class MainExitCodeTests(unittest.TestCase):
    def test_strict_truncation_returns_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cn_dir = root / "EPUB" / "【S1_01】测试书" / "OEBPS" / "Text"
            jp_dir = root / "jp" / "【S1_01】テスト" / "item" / "xhtml"
            cn_dir.mkdir(parents=True)
            jp_dir.mkdir(parents=True)
            (cn_dir / "S1_01-01_Chapter1.xhtml").write_text(TRUNCATED_CN + "\n", encoding="utf-8")
            (jp_dir / "S1_01-01.xhtml").write_text(TRUNCATED_JP + "\n", encoding="utf-8")
            out = root / "report.tsv"
            code = main(["--epub", str(root / "EPUB"), "--jp-dir", str(root / "jp"),
                         "--out", str(out), "--strict"])
            self.assertEqual(code, 1)
            self.assertTrue(out.exists())

    def test_missing_japanese_book_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cn_dir = root / "EPUB" / "【S1_01】测试书" / "OEBPS" / "Text"
            cn_dir.mkdir(parents=True)
            (cn_dir / "S1_01-01_Chapter1.xhtml").write_text("<p>正文</p>\n", encoding="utf-8")
            (root / "jp").mkdir()
            out = root / "report.tsv"
            code = main(["--epub", str(root / "EPUB"), "--jp-dir", str(root / "jp"),
                         "--out", str(out), "--strict"])
            self.assertEqual(code, 2)

    def test_unknown_book_is_setup_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "EPUB").mkdir()
            (root / "jp").mkdir()
            code = main(["--epub", str(root / "EPUB"), "--jp-dir", str(root / "jp"),
                         "--book", "S9_99", "--out", str(root / "report.tsv")])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
