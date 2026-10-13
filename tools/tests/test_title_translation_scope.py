import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_translation_table import collect_books, main
from title_rules import split_heading_markup


class TitleTranslationScopeTests(unittest.TestCase):
    def test_heading_boundaries_keep_body_and_ruby_separate(self):
        raw = ('<h1><ruby>处刑塔<rt>伦敦塔</rt></ruby></h1><p>正文</p>'
               '<h2 id="a">2</h2><h3>小标题</h3>')
        body, titles = split_heading_markup(raw)
        self.assertNotIn("处刑塔", body)
        self.assertIn("<p>正文</p>", body)
        self.assertIn("<rt>伦敦塔</rt>", titles)
        self.assertNotIn("正文", titles)
        body, titles = split_heading_markup('<x:h1>命名空间标题</x:h1><p>正文</p>')
        self.assertIn("命名空间标题", titles)
        self.assertNotIn("命名空间标题", body)

    def run_cli(self, tmp, jp_raw, cn_raw):
        root = Path(tmp)
        for side, folder, text in (("jp", "item/xhtml", jp_raw), ("cn", "OEBPS/Text", cn_raw)):
            path = root / side / "【S1_01】书" / folder / "a.xhtml"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")
        args = ["--table", str(root / "table.xlsx"), "--jp-dir", str(root / "jp"),
                "--epub", str(root / "cn"), "--out", str(root / "reports"), "--no-rulings", "--strict"]
        entry = {"ori": "魔術組織", "trans": "魔法组织", "type": "", "debuts": ""}
        with patch("check_translation_table.load_table", return_value=([entry], [])):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main(args)
        report = json.loads((root / "reports/translation-table-check.json").read_text(encoding="utf-8"))
        self.assertTrue((root / "reports/translation-title-check.tsv").exists())
        return code, report

    def test_title_only_mismatch_reports_but_does_not_block_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, report = self.run_cli(tmp, "<h1>魔術組織</h1><p>本文</p>",
                                        "<h1>题名专用措辞</h1><p>正文</p>")
            self.assertEqual(code, 0)
            self.assertEqual(report["records"], [])
            self.assertEqual(report["title_records"][0]["status"], "missing")
            self.assertEqual(report["title_records"][0]["scope"], "title")
            self.assertTrue(report["summary"]["title_advisory_only"])

    def test_title_hit_cannot_hide_body_missing_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, report = self.run_cli(tmp, "<h1>题</h1><p>魔術組織</p>",
                                        "<h1>魔法组织</h1><p>其他译法</p>")
            self.assertEqual(code, 1)
            self.assertEqual(report["records"][0]["status"], "missing")

    def test_both_scopes_keep_ruby_and_body_heading_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / "【S1_01】书/OEBPS/Text/a.xhtml"
            file.parent.mkdir(parents=True)
            file.write_text('<h1><ruby>处刑塔<rt>伦敦塔</rt></ruby></h1><p>正文</p>', encoding="utf-8")
            self.assertNotIn("处刑塔", collect_books(root, "OEBPS/Text", set())["S1_01"])
            self.assertEqual(collect_books(root, "OEBPS/Text", set(), titles=True)["S1_01"], "处刑塔")
            self.assertEqual(collect_books(root, "OEBPS/Text", set(), ruby=True, titles=True)["S1_01"],
                             "处刑塔（伦敦塔）")


if __name__ == "__main__":
    unittest.main()
