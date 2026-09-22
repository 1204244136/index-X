from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from text_norm import (  # noqa: E402
    process_file,
    split_bold_punct,
    transform_line,
)
from reorder_notes import process_book  # noqa: E402


class TextNormTransformTests(unittest.TestCase):
    def test_fullwidth_ampersand(self):
        line, hits, _ = transform_line("<p>魔法＆科学</p>", None)
        self.assertEqual(line, "<p>魔法&amp;科学</p>")
        self.assertEqual([h[0] for h in hits], ["fullwidth-ampersand"])

    def test_interrobang_and_variants(self):
        line, hits, _ = transform_line("<p>真的吗！？真的吗！?</p>", None)
        self.assertEqual(line, "<p>真的吗？！真的吗？！</p>")
        self.assertEqual(len(hits), 2)

    def test_ellipsis_period(self):
        # 删省略号后的单句号
        line, hits, _ = transform_line("<p>走吧……。</p>", None)
        self.assertEqual(line, "<p>走吧……</p>")
        self.assertEqual([h[0] for h in hits], ["ellipsis-period"])

        # 保护双重独立停顿
        line_keep, hits_keep, _ = transform_line("<p>「……。……」</p>", None)
        self.assertEqual(line_keep, "<p>「……。……」</p>")
        self.assertEqual(hits_keep, [])

    def test_consecutive_periods(self):
        line, hits, _ = transform_line("<p>停下。。别过来。。。</p>", None)
        self.assertEqual(line, "<p>停下……别过来……</p>")
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(h[0] == "consecutive-periods" for h in hits))

    def test_dash_codepoint(self):
        line, hits, _ = transform_line("<p>前方──危险</p>", None)
        self.assertEqual(line, "<p>前方——危险</p>")
        self.assertEqual(len(hits), 2)

    def test_halfwidth_comma(self):
        line, hits, _ = transform_line("<p>你好, 世界</p>", None)
        self.assertEqual(line, "<p>你好，世界</p>")
        self.assertEqual([h[0] for h in hits], ["halfwidth-comma"])

        # 数字千分位不改
        num_line, num_hits, _ = transform_line("<p>共计 1,000 人</p>", None)
        self.assertEqual(num_line, "<p>共计 1,000 人</p>")
        self.assertEqual(num_hits, [])

    def test_halfwidth_colon_and_tilde(self):
        line, hits, _ = transform_line("<p>注意:开始~结束</p>", None)
        self.assertEqual(line, "<p>注意：开始～结束</p>")
        self.assertEqual(set(h[0] for h in hits), {"halfwidth-colon", "halfwidth-tilde"})

        # URL 与时间不改
        url_line, url_hits, _ = transform_line('<p><a href="http://example.com">12:30</a></p>', None)
        self.assertEqual(url_line, '<p><a href="http://example.com">12:30</a></p>')
        self.assertEqual(url_hits, [])


class BoldRulesTests(unittest.TestCase):
    def test_bold_punctuation_split(self):
        line, hits = split_bold_punct("<p><b>重点，内容！</b></p>")
        self.assertEqual(line, "<p><b>重点</b>，<b>内容</b>！</p>")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][0], "bold-punct")

    def test_bold_empty_removal(self):
        # 纯空 <b> 移除
        line1, hits1 = split_bold_punct("<p>前文<b></b>后文</p>")
        self.assertEqual(line1, "<p>前文后文</p>")
        self.assertEqual([h[0] for h in hits1], ["bold-empty"])

        # 包含空白的 <b> 标签移除并保留空白
        line2, hits2 = split_bold_punct("<p>前文<b> </b>后文</p>")
        self.assertEqual(line2, "<p>前文 后文</p>")
        self.assertEqual([h[0] for h in hits2], ["bold-empty"])

    def test_bold_protection(self):
        # 保护实体、作品号、缩写
        line, hits = split_bold_punct("<p><b>&amp;</b><b>[S1_01]</b><b>Mr.</b></p>")
        self.assertEqual(line, "<p><b>&amp;</b><b>[S1_01]</b><b>Mr.</b></p>")
        self.assertEqual(hits, [])


class ReorderNotesTests(unittest.TestCase):
    def test_reorder_notes_and_rewrites_refs(self):
        with tempfile.TemporaryDirectory() as td:
            book_dir = Path(td) / "S1_01"
            text_dir = book_dir / "OEBPS" / "Text"
            text_dir.mkdir(parents=True)

            note_file = text_dir / "S1_01-Note.xhtml"
            note_file.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<!DOCTYPE html>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml">\n'
                "<head><title>Note</title></head>\n"
                "<body>\n"
                "<h1>注释</h1>\n\n"
                "<ul>\n"
                '<li epub:type="footnote" id="note2">注释二</li>\n'
                '<li epub:type="footnote" id="note1">注释一</li>\n'
                "</ul>\n"
                "</body>\n</html>\n",
                encoding="utf-8",
            )

            ch1 = text_dir / "S1_01-01_Chapter1.xhtml"
            ch1.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<!DOCTYPE html>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml">\n'
                "<head><title>Ch1</title></head>\n"
                "<body>\n<h1>第1章</h1>\n\n"
                '<p>正文先引用注一<a epub:type="noteref" href="S1_01-Note.xhtml#note1"><sup>1</sup></a>，'
                '后引用注二<a epub:type="noteref" href="S1_01-Note.xhtml#note2"><sup>2</sup></a>。</p>\n'
                "</body>\n</html>\n",
                encoding="utf-8",
            )

            # 执行重排（不生成备份）
            res, msg = process_book("S1_01", str(text_dir), "S1_01-Note.xhtml", dry_run=False, backup_dir=None)
            self.assertIsNone(msg)
            self.assertIsNotNone(res)
            self.assertEqual(res["new_order"], ["note1", "note2"])
            self.assertEqual(res["old_order"], ["note2", "note1"])

            # 验证重排后的 Note 文件顺序为 note1, note2
            new_note_content = note_file.read_text(encoding="utf-8")
            idx_1 = new_note_content.index('id="note1">注释一')
            idx_2 = new_note_content.index('id="note2">注释二')
            self.assertLess(idx_1, idx_2)


if __name__ == "__main__":
    unittest.main()
