from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_illustration_mapping

HEADER = (
    "| 卷号 | 图片 | 图片文字 | 正文文件 | 行号 | 正文原句 | 备注 |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n"
)
BODY = (
    '<html><body>\n'
    '<p>一行目</p>\n'
    '<p>二行目</p>\n'
    '<p>「<ruby>三行目<rt>さんぎょうめ</rt></ruby>の台詞」</p>\n'
    '<p>四行目</p>\n'
    '</body></html>\n'
)


class IllustrationMappingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.jp_root = self.root / "japanese-text"
        xhtml = self.jp_root / "【S1_01】书" / "item" / "xhtml"
        xhtml.mkdir(parents=True)
        (xhtml / "S1_01-01.xhtml").write_text(BODY, encoding="utf-8")
        self.doc = self.root / "mapping.md"
        self.body = BODY

    def write_doc(self, rows: list[str]) -> None:
        self.doc.write_text(
            "# 表\n\n## 映射表\n\n" + HEADER + "".join(row + "\n" for row in rows),
            encoding="utf-8")

    def run_main(self, *extra: str) -> int:
        return check_illustration_mapping.main(
            ["--doc", str(self.doc), "--jp-root", str(self.jp_root), *extra])

    def test_anchor_matches_body_line(self):
        self.write_doc([
            "| S1_01 | S1_01-kuchie-001.jpg | 「三行目の台詞」 | S1_01-01.xhtml | 4 | "
            "「三行目の台詞」 | — |",
        ])
        self.assertEqual(self.run_main(), 0)

    def test_escaped_pipe_in_cell_is_read_back(self):
        self.write_doc([
            "| S1_01 | S1_01-kuchie-001.jpg | 「A\\|B」 | S1_01-01.xhtml | 4 | "
            "「三行目の台詞」 | — |",
        ])
        self.assertEqual(self.run_main(), 0)

    def test_drift_is_reported_with_suggestion(self):
        self.write_doc([
            "| S1_01 | S1_01-kuchie-001.jpg | 「三行目の台詞」 | S1_01-01.xhtml | 3 | "
            "「三行目の台詞」 | — |",
        ])
        self.assertEqual(self.run_main(), 1)
        rows, _ = check_illustration_mapping.read_rows(self.doc)
        _, problems, _ = check_illustration_mapping.check(
            self.doc, self.jp_root, limit=0)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["kind"], "line_drift")
        self.assertEqual(problems[0]["suggest"], 4)
        self.assertEqual(len(rows), 1)

    def test_row_without_anchor_is_skipped(self):
        self.write_doc([
            "| S1_01 | S1_01-kuchie-001.jpg | 「正文没有」 | — | — | — | 正文无此句。 |",
        ])
        self.assertEqual(self.run_main(), 0)
        checked, problems, _ = check_illustration_mapping.check(
            self.doc, self.jp_root, limit=0)
        self.assertEqual((checked, problems), (0, []))

    def test_missing_cache_is_precondition_error(self):
        self.write_doc([
            "| S1_01 | S1_01-kuchie-001.jpg | 「三行目の台詞」 | S1_01-01.xhtml | 4 | "
            "「三行目の台詞」 | — |",
        ])
        missing = self.root / "no-such-cache"
        self.assertEqual(check_illustration_mapping.main(
            ["--doc", str(self.doc), "--jp-root", str(missing)]), 2)

    def test_other_tables_in_doc_are_ignored(self):
        self.doc.write_text(
            "# 表\n\n## 列\n\n| 列 | 含义 |\n| --- | --- |\n| 卷号 | 卷 |\n\n"
            "## 映射表\n\n" + HEADER +
            "| S1_01 | S1_01-kuchie-001.jpg | 「三行目の台詞」 | S1_01-01.xhtml | 4 | "
            "「三行目の台詞」 | — |\n",
            encoding="utf-8")
        self.assertEqual(self.run_main(), 0)


if __name__ == "__main__":
    unittest.main()
