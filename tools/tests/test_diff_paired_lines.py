from __future__ import annotations

import unittest
from tools.diff_paired_lines import (
    align_lines,
    compute_similarity,
    has_body,
    parse_line,
    structural_conflicts,
)

class TestDiffPairedLines(unittest.TestCase):
    def test_exact_match(self):
        jp = [parse_line("<h1>第一章</h1>"), parse_line("<p>上条当麻は走った。</p>")]
        cn = [parse_line("<h1>第一章</h1>"), parse_line("<p>上条当麻奔跑着。</p>")]
        pairs = align_lines(jp, cn)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0].status, "MATCH")
        self.assertEqual(pairs[1].status, "MATCH")

    def test_missing_scene_break(self):
        jp = [
            parse_line("<p>前一段</p>"),
            parse_line("<br/>"),
            parse_line("<p>后一段</p>"),
        ]
        cn = [
            parse_line("<p>前一段</p>"),
            parse_line("<p>后一段</p>"),
        ]
        pairs = align_lines(jp, cn)
        self.assertEqual(len(pairs), 3)
        self.assertEqual(pairs[1].status, "EXTRA_JP")
        self.assertTrue(pairs[1].jp.is_br)

    def test_image_anchor_match(self):
        jp = [parse_line('<p class="fit"><img src="../Images/i-001.jpg"/></p>')]
        cn = [parse_line('<p class="fit"><img src="../Images/S1_01-i-001.jpg"/></p>')]
        pairs = align_lines(jp, cn)
        self.assertEqual(pairs[0].status, "MATCH")

    def test_inline_glyph_is_not_an_image_line(self):
        """gaiji / height-2em 是行内字形，不计入图片行（同 check_alignment 口径）。

        日文用 <img class="gaiji"> 还原特殊字形、中文直接写字符，是两侧常见的
        表达差异；若把字形当成图片行，会大面积误报图片槽位错位。
        """
        jp = parse_line('<p><img class="gaiji" src="../image/x-gaiji-0001.png" alt=""/>予測</p>')
        cn = parse_line("<p>←预测</p>")
        self.assertFalse(jp.is_img)
        self.assertFalse(cn.is_img)

    def test_gaiji_inside_heading_is_not_an_image_line(self):
        """标题行内的 gaiji 不应让 L4 被判成图片行（否则 h1 槽位恒报冲突）。"""
        jp = parse_line('<h1>第三章　N<img class="gaiji" src="../image/x-gaiji-0001.png" alt=""/>L</h1>')
        cn = parse_line('<h1 class="heading-lines"><span class="heading-main">第三章</span></h1>')
        self.assertFalse(jp.is_img)
        self.assertTrue(jp.is_h1)
        self.assertTrue(cn.is_h1)

    def test_equal_line_counts_never_produce_gaps(self):
        """行数相等时按行号 1:1 对齐，不产生任何 EXTRA_JP/EXTRA_CN。

        仓库契约保证配对文件两侧行数一致。序列比对在行数相等时仍可能用
        「一个 gap + 一处错位匹配」换到更高总分，凭空造出成对 gap（实测 747 个
        配对文件中 59 个出现，共 105 对），那是对比算法自身的产物。
        """
        jp = [parse_line(f"<p>日文第{i}段</p>") for i in range(30)]
        cn = [parse_line(f"<p>中文第{i}段</p>") for i in range(30)]
        pairs = align_lines(jp, cn)
        self.assertEqual(len(pairs), 30)
        self.assertEqual([p.status for p in pairs if p.status.startswith("EXTRA")], [])
        for i, p in enumerate(pairs, 1):
            self.assertEqual(p.jp_idx, i)
            self.assertEqual(p.cn_idx, i)

    def test_unequal_line_counts_still_report_gaps(self):
        """行数确实不等时仍要回退序列比对，gap 才是真信号。"""
        jp = [parse_line("<p>前一段</p>"), parse_line("<p>后一段</p>")]
        cn = [parse_line("<p>前一段</p>")]
        pairs = align_lines(jp, cn)
        self.assertEqual(sum(1 for p in pairs if p.status == "EXTRA_JP"), 1)

    def test_structural_conflict_detected_at_same_line_count(self):
        """行数相同但图片槽位错位，必须检出（check_alignment 的集合比较看不到）。"""
        jp = [
            parse_line("<h1>第一章</h1>"),
            parse_line("<p>正文一</p>"),
            parse_line('<p class="fit"><img src="../Images/i-001.jpg"/></p>'),
        ]
        cn = [
            parse_line("<h1>第一章</h1>"),
            parse_line('<p class="fit"><img src="../Images/S1_01-i-001.jpg"/></p>'),
            parse_line("<p>正文一</p>"),
        ]
        self.assertEqual(len(jp), len(cn))
        pairs = align_lines(jp, cn)
        conflicts = structural_conflicts(pairs)
        self.assertEqual([idx for idx, _ in conflicts], [2, 3])

    def test_no_false_conflict_on_plain_translation_differences(self):
        """译文长短/用词不同不是结构冲突：只有结构锚点参与判定。"""
        jp = [parse_line("<p>短い。</p>")]
        cn = [parse_line("<p>这是一句长得多、用词也完全不同的译文。</p>")]
        pairs = align_lines(jp, cn)
        self.assertEqual(structural_conflicts(pairs), [])

    def test_has_body_excludes_pure_image_page(self):
        """纯图片页/无正文页不适用固定行模板，两侧行数天然可不同。"""
        cover = [
            parse_line("<?xml version='1.0' encoding='utf-8'?>"),
            parse_line("<!DOCTYPE html>"),
            parse_line("<html><head><title>t</title></head><body>"),
            parse_line('<p class="cover"><img class="fit" src="Cover.jpg"/></p>'),
            parse_line("</body></html>"),
        ]
        self.assertFalse(has_body(cover))
        self.assertTrue(has_body(cover + [parse_line("<p>正文</p>")]))

    # --- 假阳性回归：以下四类曾在本库全量跑出上万条噪声，必须不再报 DRIFT ---

    def test_ruby_annotation_is_stripped_before_compare(self):
        """`<rt>` 注音必须先剥离再比较。

        日文把读音放进 `<rt>`（`水瓶座` 写作 `<ruby>水<rt>みず</rt></ruby>…`），
        中文放拼音或英文，两侧注音内容本就不同源。不剥离会把注音算进可见文本，
        让长度比与字符重合率同时失真，把正常译文判成漂移。
        """
        jp = parse_line("<p><ruby>水<rt>みず</rt></ruby><ruby>瓶<rt>がめ</rt></ruby>座</p>")
        cn = parse_line("<p>水瓶座</p>")
        # 剥离注音后两侧可见文本应完全相同（注音字数不参与长度）
        self.assertEqual(jp.text, "水瓶座")
        self.assertEqual(cn.text, "水瓶座")
        self.assertGreaterEqual(compute_similarity(jp, cn), 0.15)

    def test_template_header_lines_are_equivalent(self):
        """固定行模板 L1-L3 不是正文：两侧 `<title>` 内容不同源，不算漂移。

        日文头部行填书名、中文留空，不排除会让**每个**文件的 L3 恒判漂移。
        """
        jp = parse_line('<html xmlns="x" xml:lang="ja"><head><title>とある魔術の禁書目録</title></head><body class="p-text">')
        cn = parse_line('<html xmlns="x"><head><link href="../Styles/style.css"/><title></title></head><body>')
        self.assertTrue(jp.is_template and cn.is_template)
        self.assertEqual(compute_similarity(jp, cn), 1.0)

    def test_template_line_does_not_mask_missing_image(self):
        """模板捷径不得吞掉真结构冲突：篇首插图并在头部行的 body 开头。"""
        jp = parse_line('<html xmlns="x"><head><title>t</title></head><body><img class="fit" src="i-001.jpg"/>')
        cn = parse_line('<html xmlns="x"><head><title></title></head><body>')
        self.assertLess(compute_similarity(jp, cn), 0.15)

    def test_short_line_ratio_noise_is_not_drift(self):
        """短行按**绝对字数差**判定，不用纯比例。

        `と、`(2 字) → `接着……`(4 字) 比例 2.0，但只差 2 字，属正常译法；
        旧口径把它判成越界，实测占命中数的 51.6%。
        """
        jp = parse_line("<p>と、</p>")
        cn = parse_line("<p>接着……</p>")
        self.assertGreaterEqual(compute_similarity(jp, cn), 0.15)

    def test_long_line_large_mismatch_is_drift(self):
        """长行差 100+ 字仍要报出来（真合并/拆分信号不能被放宽口径吞掉）。"""
        jp = parse_line("<p>" + "あ" * 30 + "</p>")
        cn = parse_line("<p>" + "字" * 200 + "</p>")
        self.assertLess(compute_similarity(jp, cn), 0.15)

    def test_pure_punctuation_lines_are_equivalent(self):
        """两侧均无实义字符（省略号/符号行）按等价处理，不报漂移。"""
        jp = parse_line("<p>「……………………………………………………………」</p>")
        cn = parse_line("<p>「……………………………………」</p>")
        self.assertFalse(jp.char_set or cn.char_set)
        self.assertEqual(compute_similarity(jp, cn), 1.0)

    def test_translation_difference_still_reported(self):
        """放宽口径不能把「一侧有正文、另一侧空」这类真问题一起放过。"""
        jp = parse_line("<p>彼は走った。</p>")
        cn = parse_line("<p></p>")
        self.assertLess(compute_similarity(jp, cn), 0.15)


if __name__ == "__main__":
    unittest.main()
