from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from proofread_review import (  # noqa: E402
    clip,
    core_of,
    enrich_rows,
    grade,
    minimal_diff,
    parse_diff_file,
    parse_diff_rows,
    spec_kind,
    to_text,
    unquote_git_path,
)

# 两个文件交错的 diff：用于验证片段不会串到别的文件上
DIFF = '''diff --git "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml" "b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml"
index 0000000..1111111 100644
--- "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml"
+++ "b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml"
@@ -16 +16 @@
-<p>不补课的话</p>
+<p>要是不开门的话</p>
@@ -54 +54 @@
-<p>氢氦锂～铍～硼～</p>
+<p>氢氦锂～铍～</p>
diff --git "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-11_Epilogue.xhtml" "b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-11_Epilogue.xhtml"
index 2222222..3333333 100644
--- "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-11_Epilogue.xhtml"
+++ "b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-11_Epilogue.xhtml"
@@ -101 +101 @@
-<p>阴沉幼女的全裸装扮</p>
+<p>阴沉幼女的装扮</p>
@@ -222 +222 @@
-<p>而这一切的元凶就站在那里。</p>
-<p>多余的整段。</p>
+<p>而这一切的元凶。</p>
'''


# 一个 hunk 含多行改动：`-`/`+` 行各占一行，行号必须逐行递增，
# 不能整个 hunk 都沿用 `@@ -a,n` 的起始行号。
MULTILINE_HUNK_DIFF = '''diff --git "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml" "b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml"
index 0000000..1111111 100644
--- "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml"
+++ "b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml"
@@ -13,2 +13,2 @@
-<p>旧甲。</p>
-<p>旧乙。</p>
+<p>新甲。</p>
+<p>新乙。</p>
@@ -20,2 +20,2 @@
-<p>旧丙。</p>
+<p>新丙。</p>
-<p>旧丁。</p>
+<p>新丁。</p>
'''

# 纯删除行：新侧没有对应行，行号退回旧侧。
PURE_DELETION_DIFF = '''diff --git "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml" "b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml"
index 0000000..1111111 100644
--- "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml"
+++ "b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml"
@@ -30 +30 @@
-<p>整段删掉。</p>
'''


def g(old, new):
    """按 grade 接口取级别（row 只需 old/new）。"""
    return grade({"old": old, "new": new})


class ParseWordDiffTests(unittest.TestCase):
    def test_extraction_preserves_readings_but_excludes_script_and_style(self):
        self.assertEqual(to_text(
            '<style>ignored</style><p>魔術<rt>まじゅつ</rt> &amp; 光</p>'
            '<script>ignored</script>'
        ), "魔術 まじゅつ & 光")

    def test_each_change_keeps_its_own_file(self):
        rows = parse_diff_rows(DIFF, "abcdef12")
        by_line = {r["line"]: r for r in rows}
        self.assertEqual(by_line["16"]["file"], "S3_01-03_Chapter1.xhtml")
        self.assertEqual(by_line["101"]["file"], "S3_01-11_Epilogue.xhtml")
        self.assertEqual(by_line["222"]["file"], "S3_01-11_Epilogue.xhtml")

    def test_tags_are_stripped(self):
        rows = {r["line"]: r for r in parse_diff_rows(DIFF, "abcdef12")}
        self.assertEqual(rows["101"]["old"], "阴沉幼女的全裸装扮")
        self.assertEqual(rows["101"]["new"], "阴沉幼女的装扮")

    def test_unbalanced_hunk_merges_into_one_row(self):
        rows = [r for r in parse_diff_rows(DIFF, "abcdef12") if r["line"] == "222"]
        self.assertEqual(len(rows), 1)
        self.assertIn("多余的整段。", rows[0]["old"])
        self.assertEqual(rows[0]["new"], "而这一切的元凶。")

    def test_commit_label_and_line_numbers(self):
        rows = parse_diff_rows(DIFF, "abcdef12")
        self.assertTrue(all(r["commit"] == "abcdef12" for r in rows))
        self.assertEqual([r["line"] for r in rows], ["16", "54", "101", "222"])


class MultilineHunkLineNumberTests(unittest.TestCase):
    """hunk 含多行改动时，每个片段必须拿到自己在当前文件里的行号。

    旧版只取 hunk 头 `@@ -a,n` 的起始行号，hunk 内后续改动行全部沿用该值，
    实测让 33% 的片段行号偏小 1~6 行，`line` 与随之填充的 `jp` 列都不可用。
    """

    def test_each_row_in_multiline_hunk_gets_its_own_line_number(self):
        rows = parse_diff_rows(MULTILINE_HUNK_DIFF, "abcdef12")
        self.assertEqual([r["line"] for r in rows], ["13", "14", "20", "21"])
        self.assertEqual([r["old"] for r in rows], ["旧甲。", "旧乙。", "旧丙。", "旧丁。"])
        self.assertEqual([r["new"] for r in rows], ["新甲。", "新乙。", "新丙。", "新丁。"])

    def test_pairing_stays_aligned_across_multiline_hunk(self):
        # 同一 hunk 内 2 删 2 增：配对顺序必须与行序一致，不能错位
        rows = parse_diff_rows(MULTILINE_HUNK_DIFF, "abcdef12")
        self.assertEqual(rows[0]["new"], "新甲。")
        self.assertEqual(rows[1]["new"], "新乙。")

    def test_pure_deletion_falls_back_to_old_line_number(self):
        rows = parse_diff_rows(PURE_DELETION_DIFF, "abcdef12")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["line"], "30")
        self.assertEqual(rows[0]["old"], "整段删掉。")
        self.assertEqual(rows[0]["new"], "")


class PathTests(unittest.TestCase):
    def test_quoted_path_with_spaces(self):
        line = ('diff --git "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03.xhtml" '
                '"b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03.xhtml"')
        self.assertEqual(parse_diff_file(line),
                         "EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03.xhtml")

    def test_unquoted_path(self):
        self.assertEqual(parse_diff_file("diff --git a/EPUB/x.xhtml b/EPUB/x.xhtml"),
                         "EPUB/x.xhtml")

    def test_octal_escapes_are_restored(self):
        # 创 -> \\345\\210\\233
        self.assertEqual(unquote_git_path("\\345\\210\\233"), "创")


class SpecKindTests(unittest.TestCase):
    """规范确定性改动：产出物遵循 docs/translation-spec.md，这类改动不需要回原文。"""

    def test_punctuation_only(self):
        self.assertEqual(spec_kind("但是。", "但是——"), "punct")

    def test_halfwidth_to_fullwidth_punctuation(self):
        # 半角标点必须被规范改写；旧口径只剥全角标点，会把它误判成 local
        self.assertEqual(spec_kind("他说,你好.", "他说，你好。"), "punct")

    def test_quote_style_change(self):
        self.assertEqual(spec_kind("「喵？！」", "『喵？！』"), "quote")

    def test_curly_quote_to_corner_quote(self):
        self.assertEqual(spec_kind("“你好”", "「你好」"), "quote")

    def test_fullwidth_digits_are_glyph(self):
        self.assertEqual(spec_kind("第３位", "第3位"), "glyph")

    def test_erhua_removal(self):
        self.assertEqual(spec_kind("不加把劲儿", "不加把劲"), "erhua")

    def test_spec_particle(self):
        self.assertEqual(spec_kind("切！", "啧！"), "particle")

    def test_erhua_with_other_change_is_not_spec(self):
        # 「块儿」->「起」不是去掉儿化音，是改词，必须留给人工
        self.assertEqual(spec_kind("一块儿", "一起"), "")

    def test_semantic_change_is_not_spec(self):
        self.assertEqual(spec_kind("念动力", "念动能力"), "")
        self.assertEqual(spec_kind("一把椅子", "两把椅子"), "")

    def test_digit_change_is_not_punctuation(self):
        # 数字不是标点：删掉/改掉数字必须留下来复核，不能被 punct 静默放行
        self.assertNotEqual(spec_kind("第10位", "第位"), "punct")
        # 也不能降级成虚词微调（数字不在虚词白名单里）
        self.assertEqual(g("第10位", "第位")[0], "local")


class GradeTests(unittest.TestCase):
    def test_punctuation_only_change(self):
        self.assertEqual(g("但是。", "但是——"), ("spec", "punct"))

    def test_tiny_uses_minimal_diff_not_fragment_length(self):
        # 整片段是长句、差异只有一个虚词，属于虚词级微调（旧口径用整片段长度，恒不触发）
        old = "「我说御坂小姐，这里可是学园都市。」他笑着说的。"
        new = "「我说御坂小姐，这里可是学园都市。」他笑着说。"
        self.assertEqual(g(old, new), ("tiny", ""))

    def test_term_change_of_two_chars_is_not_tiny(self):
        # 术语改动只差 2 字也不能算虚词微调，否则复核者会直接跳过
        old = "「这里可是科学阵营的大本营学园都市。」"
        new = "「这里可是科学侧的大本营学园都市。」"
        self.assertEqual(g(old, new), ("local", ""))

    def test_local_substitution(self):
        self.assertEqual(g("念动力", "念动能力"), ("local", ""))

    def test_rewrite(self):
        old = "所有人都在期待平安夜的到来。" * 3
        new = "大家都盼着平安夜。" * 3
        self.assertEqual(g(old, new)[0], "rewrite")


class ClipTests(unittest.TestCase):
    def test_only_diff_context_is_kept(self):
        old = "甲" * 40 + "儿" + "乙" * 40
        out = clip(old, "儿")
        self.assertLess(len(out), 40)
        self.assertIn("儿", out)
        self.assertTrue(out.startswith("…"))
        self.assertTrue(out.endswith("…"))

    def test_short_text_is_untouched(self):
        self.assertEqual(clip("不加把劲", ""), "不加把劲")


class CoreOfTests(unittest.TestCase):
    def test_digits_are_not_punctuation(self):
        self.assertIn("5", core_of("等级5"))
        self.assertNotIn("，", core_of("你好，世界"))


class MinimalDiffTests(unittest.TestCase):
    def test_common_prefix_and_suffix_are_trimmed(self):
        self.assertEqual(minimal_diff("阴沉幼女的全裸装扮", "阴沉幼女的装扮"),
                         ("全裸", ""))

    def test_identical(self):
        self.assertEqual(minimal_diff("相同", "相同"), ("", ""))


class EnrichRowsTests(unittest.TestCase):
    def test_enrich_adds_jp_and_flags(self):
        rows = [{
            "commit": "test",
            "work": "S3_03",
            "file": "S3_03-04_Chapter2.xhtml",
            "line": "55",
            "old": "它由圣金属制成",
            "new": "它由Saintium制成"
        }]
        enrich_rows(rows, enable_jp=False, enable_audit=True)
        self.assertIn("flags", rows[0])
        self.assertIn("controlled_term", rows[0]["flags"])
        self.assertEqual(rows[0]["jp"], "")

    def test_enrich_with_disabled_options(self):
        rows = [{"old": "a", "new": "b"}]
        enrich_rows(rows, enable_jp=False, enable_audit=False)
        self.assertEqual(rows[0]["jp"], "")
        self.assertEqual(rows[0]["flags"], "")


if __name__ == "__main__":
    unittest.main()
