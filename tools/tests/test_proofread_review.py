from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from proofread_review import (  # noqa: E402
    grade,
    minimal_diff,
    parse_diff_file,
    parse_word_diff,
    unquote_git_path,
)

# 两个文件交错的 word-diff：用于验证片段不会串到别的文件上
DIFF = '''diff --git "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml" "b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml"
index 0000000..1111111 100644
--- "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml"
+++ "b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-03_Chapter1.xhtml"
@@ -16 +16 @@
[-<p>不补课的话</p>-]{+<p>要是不开门的话</p>+}
@@ -54 +54 @@
[-<p>氢氦锂～铍～硼～</p>-]{+<p>氢氦锂～铍～</p>+}
diff --git "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-11_Epilogue.xhtml" "b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-11_Epilogue.xhtml"
index 2222222..3333333 100644
--- "a/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-11_Epilogue.xhtml"
+++ "b/EPUB/[S3_01]x 01X/OEBPS/Text/S3_01-11_Epilogue.xhtml"
@@ -101 +101 @@
[-<p>阴沉幼女的全裸装扮</p>-]{+<p>阴沉幼女的装扮</p>+}
@@ -222 +222 @@
[-<p>而这一切的元凶就站在那里。</p>-]
[-<p>多余的整段。</p>-]{+<p>而这一切的元凶。</p>+}
'''


class ParseWordDiffTests(unittest.TestCase):
    def test_each_change_keeps_its_own_file(self):
        rows = parse_word_diff(DIFF, "abcdef12")
        by_line = {r["line"]: r for r in rows}
        self.assertEqual(by_line["16"]["file"], "S3_01-03_Chapter1.xhtml")
        self.assertEqual(by_line["101"]["file"], "S3_01-11_Epilogue.xhtml")
        self.assertEqual(by_line["222"]["file"], "S3_01-11_Epilogue.xhtml")

    def test_tags_are_stripped(self):
        rows = {r["line"]: r for r in parse_word_diff(DIFF, "abcdef12")}
        self.assertEqual(rows["101"]["old"], "阴沉幼女的全裸装扮")
        self.assertEqual(rows["101"]["new"], "阴沉幼女的装扮")

    def test_unbalanced_hunk_merges_into_one_row(self):
        rows = [r for r in parse_word_diff(DIFF, "abcdef12") if r["line"] == "222"]
        self.assertEqual(len(rows), 1)
        self.assertIn("多余的整段。", rows[0]["old"])
        self.assertEqual(rows[0]["new"], "而这一切的元凶。")

    def test_commit_label_and_line_numbers(self):
        rows = parse_word_diff(DIFF, "abcdef12")
        self.assertTrue(all(r["commit"] == "abcdef12" for r in rows))
        self.assertEqual([r["line"] for r in rows], ["16", "54", "101", "222"])


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


class GradeTests(unittest.TestCase):
    def test_punctuation_only_change(self):
        self.assertEqual(grade({"old": "但是。", "new": "但是——"}), "punct")

    def test_local_substitution(self):
        self.assertEqual(grade({"old": "念动力", "new": "念动能力"}), "local")

    def test_rewrite(self):
        old = "所有人都在期待平安夜的到来。" * 3
        new = "大家都盼着平安夜。" * 3
        self.assertEqual(grade({"old": old, "new": new}), "rewrite")


class MinimalDiffTests(unittest.TestCase):
    def test_common_prefix_and_suffix_are_trimmed(self):
        self.assertEqual(minimal_diff("阴沉幼女的全裸装扮", "阴沉幼女的装扮"),
                         ("全裸", ""))

    def test_identical(self):
        self.assertEqual(minimal_diff("相同", "相同"), ("", ""))


if __name__ == "__main__":
    unittest.main()
