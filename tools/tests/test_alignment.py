from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import check_alignment  # noqa: E402
import alignment_rules  # noqa: E402


def xhtml(body_lines: list[str]) -> str:
    return "\n".join([
        "<?xml version='1.0' encoding='utf-8'?>",
        "<!DOCTYPE html>",
        "<html><head></head><body>",
        "<h1>章</h1>",
        "",
        *body_lines,
        "</body></html>",
        "",
    ])


class AlignmentTests(unittest.TestCase):
    def test_heading_breaks_and_block_wrappers_are_rejected(self):
        heading_break = xhtml(["<p>正文</p>"]).splitlines()
        heading_break[3] = "<h1>主标题<br/>副标题</h1>"
        block_wrapper = xhtml(["<p>正文</p>"]).splitlines()
        block_wrapper[3] = "<h1><div>标题</div></h1>"
        body_heading = xhtml(["<p>正文</p>", "<h2>特典<br/>副标题</h2>"]).splitlines()
        embedded = xhtml(["<p>正文</p>", "<p>前缀</p><h2>标题</h2>"]).splitlines()

        self.assertIn("L4 h1/h2 内嵌 <br/>", check_alignment.check_file(heading_break))
        self.assertIn(
            "L4 h1/h2 含 div/p 块级包装",
            check_alignment.check_file(block_wrapper),
        )
        self.assertIn("L7 h1/h2 内嵌 <br/>", check_alignment.check_file(body_heading))
        self.assertIn("L7 h1/h2 未独占一个物理行", check_alignment.check_file(embedded))

    def test_semantic_heading_spans_are_allowed(self):
        lines = xhtml(["<p>正文</p>"]).splitlines()
        lines[3] = (
            '<h1 class="heading-lines"><span class="heading-main">主标题</span>'
            '<span class="heading-subtitle">副标题</span></h1>'
        )
        self.assertEqual(check_alignment.check_file(lines), [])

    def test_body_lines_must_be_atomic(self):
        adjacent = xhtml(["<p>一</p><p>二</p>"]).splitlines()
        footer = xhtml(["<p>一</p><hr/>"]).splitlines()
        content_close = xhtml(["<p>一</p></body></html>"]).splitlines()
        self.assertIn(
            "L6 同一物理行包含多个正文块",
            check_alignment.check_file(adjacent),
        )
        self.assertIn(
            "L6 同一物理行包含多个正文块",
            check_alignment.check_file(footer),
        )
        self.assertIn(
            "L6 正文与 body 闭标签同行",
            check_alignment.check_file(content_close),
        )

    def test_books_without_a_japanese_counterpart_are_still_checked(self):
        """没有日文对应的中文书也必须做单侧模板检查。

        这段逻辑曾经被嵌在 `for ... in pairs:` 里面，于是缓存里没有日文对应的书
        永远拿不到检查；S5 又因 japanese_book_id 的错误折叠进不了 pairs，
        结果是既没配对也没单侧检查，而且不报任何错。
        """
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            jp = cache / "japanese-text" / "[S1_01]日" / "OEBPS" / "Text"
            cn = cache / "chinese-text" / "[S1_99]无日文对应" / "OEBPS" / "Text"
            jp.mkdir(parents=True)
            cn.mkdir(parents=True)
            (jp / "S1_01-01_p-001.xhtml").write_text(
                xhtml(["<p>一</p>"]), encoding="utf-8")
            # 该文件 L6 不是单一块：只有真的跑了检查才会报出来
            broken = xhtml(["<p>一</p><p>二</p>"]).splitlines()
            (cn / "S1_99-01_Chapter.xhtml").write_text(
                "\n".join(broken), encoding="utf-8")
            with patch.object(sys, "argv", ["check_alignment.py", "--cache", str(cache)]):
                self.assertEqual(check_alignment.main(), 0)
            report = (cache / "alignment-check.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("同一物理行包含多个正文块", report)
            self.assertNotIn("无日文对应作品", report)   # 有问题时不额外打标记

    def test_japanese_only_books_are_still_checked(self):
        """只有日文侧存在的作品同样要检查（S3_12 之后的新卷、S6 日文独有短篇）。"""
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            jp = cache / "japanese-text" / "[S6_24.06.07]日文独有" / "OEBPS" / "Text"
            jp.mkdir(parents=True)
            broken = xhtml(["<p>一</p><p>二</p>"]).splitlines()
            (jp / "S6_24.06.07-01_Chapter.xhtml").write_text(
                "\n".join(broken), encoding="utf-8")
            with patch.object(sys, "argv", ["check_alignment.py", "--cache", str(cache)]):
                self.assertEqual(check_alignment.main(), 0)
            report = (cache / "alignment-check.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("同一物理行包含多个正文块", report)

    def test_s5_pairs_by_the_same_work_id(self):
        """S5 按同一作品号配对，不再折叠成合订卷号。"""
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            cn = cache / "chinese-text" / "[S5_01_03]中" / "OEBPS" / "Text"
            jp = cache / "japanese-text" / "[S5_01_03]日" / "OEBPS" / "Text"
            cn.mkdir(parents=True)
            jp.mkdir(parents=True)
            (cn / "S5_01_03-01_Chapter1.xhtml").write_text(
                xhtml(["<p>一</p>"]), encoding="utf-8")
            (jp / "S5_01_03-01_p-001.xhtml").write_text(
                xhtml(["<p>一</p>", "<p>二</p>"]), encoding="utf-8")
            with patch.object(sys, "argv", ["check_alignment.py", "--cache", str(cache)]):
                self.assertEqual(check_alignment.main(), 0)
            report = (cache / "alignment-check.tsv").read_text(encoding="utf-8-sig")
            # 配对成立：报告里应出现配对差异，而不是「无日文对应作品」
            self.assertIn("配对差异", report)
            self.assertNotIn("无日文对应作品", report)

    def test_template_exempt_books_skip_only_template_problems(self):
        """S0_00 这类作品豁免模板项，但仍参与 -00 / 重复表头等其它检查。"""
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            cn = cache / "chinese-text" / "[S0_00]无日文对应" / "OEBPS" / "Text"
            cn.mkdir(parents=True)
            broken = xhtml(["<p>一</p><p>二</p>"]).splitlines()
            (cn / "S0_00-01_Chapter.xhtml").write_text(
                "\n".join(broken), encoding="utf-8")
            (cn / "S0_00-00_Bad.xhtml").write_text(
                "\n".join(xhtml(["<p>一</p>"]).splitlines()), encoding="utf-8")
            with patch.object(sys, "argv", ["check_alignment.py", "--cache", str(cache)]):
                self.assertEqual(check_alignment.main(), 0)
            report = (cache / "alignment-check.tsv").read_text(encoding="utf-8-sig")
            self.assertNotIn("同一物理行包含多个正文块", report)   # 模板项已豁免
            self.assertIn("内容序 -00 非法", report)               # 其它检查仍生效

    def test_pair_rules_only_cancel_the_problem_they_explain(self):
        """确认过的例外只抵消它解释得了的问题项，其余差异照报。"""
        header = "S5_01_03-06"
        jp = xhtml(["<p>一</p>", "<p>本文</p>"]).splitlines()
        cn = xhtml(["<p>一</p>"]).splitlines()          # 少一行
        # 没有「あとがき」形状 → 规则不生效，行数差异必须保留
        self.assertIn("行数", " ".join(check_alignment.pair_problems(header, jp, cn)))

        # 后记形状成立：日文比中文多出「あとがき」+ 10 行，
        # 去掉这段后行数与 <br/> 位置都与中文一致（两侧闭合行都在页尾）。
        # 注意日文的 `</body></html>` 在页尾，扣除的是「あとがき」到闭合行之间的正文。
        cn_after = xhtml(["<p>一</p>"]).splitlines()
        jp_after = cn_after[:-1] + ["<p>あとがき</p>"] + ["<p>后</p>"] * 10 + ["</body></html>"]
        self.assertEqual(check_alignment.afterword_offset(jp_after, cn_after), 7)
        self.assertEqual(check_alignment.pair_problems(header, jp_after, cn_after), [])
        # 行数差确实被规则解释掉了（不抵消的话会报 18 vs 7）
        self.assertIn("行数", " ".join(check_alignment.pair_problems_raw(
            header, jp_after, cn_after)))

        # 中文侧另有 <br/> 差异 → 规则不得把它一起放掉，但同时仍抵消行数项
        cn_br = cn_after[:3] + ["<br/>"] + cn_after[3:]
        self.assertIsNone(check_alignment.afterword_offset(jp_after, cn_br))
        problems = check_alignment.pair_problems(header, jp_after, cn_br)
        self.assertTrue(problems)
        self.assertTrue(any(p.startswith("<br/> 位置") for p in problems))

        # 日文尾部与「后记」形状不符（没有独占的 あとがき 行）→ 例外不成立
        jp_no_marker = cn_after[:-1] + ["<p>本文</p>"] * 11 + ["</body></html>"]
        self.assertIsNone(check_alignment.afterword_offset(jp_no_marker, cn_after))
        self.assertTrue(check_alignment.pair_problems(header, jp_no_marker, cn_after))

    def test_afterword_rule_requires_an_afterword(self):
        lines = xhtml(["<p>一</p>"]).splitlines()
        self.assertIsNone(check_alignment.afterword_offset(lines, lines))
        # 后面不足 10 行
        short = ["<p>一</p>", "<p>あとがき</p>", "<p>x</p>", "</body></html>"]
        self.assertIsNone(check_alignment.afterword_offset(short, short))

    def test_section_order_rule_requires_a_pure_swap(self):
        jp = ["<h1>t</h1>", "", "<p>a</p>", '<p><img src="x"/></p>', "<h2>6</h2>", "<p>b</p>"]
        cn = ["<h1>t</h1>", "", "<p>甲</p>", "<h2>6</h2>", '<p><img src="x"/></p>', "<p>乙</p>"]
        self.assertEqual(check_alignment.order_swap_offset(jp, cn), 4)
        # 除了互换还多出别的结构差异 → 不是纯互换，拒绝
        cn_extra = cn[:]
        cn_extra.insert(2, "<br/>")
        self.assertIsNone(check_alignment.order_swap_offset(jp, cn_extra))
        # 行数不同 → 拒绝
        self.assertIsNone(check_alignment.order_swap_offset(jp, cn[:-1]))
        # 没有互换 → 拒绝
        self.assertIsNone(check_alignment.order_swap_offset(jp, jp))

    def test_pair_rules_table_only_lists_reviewed_headers(self):
        """规则表是逐条确认的结果，不是「遇到差异就登记」。"""
        self.assertEqual(
            alignment_rules.PAIR_RULES,
            {"S5_01_03-06": "afterword-moved", "S5_01_02-09": "section-order"})
        for header, rule in alignment_rules.PAIR_RULES.items():
            self.assertIn(rule, ("afterword-moved", "section-order"), header)

    def test_fixed_layout_work_is_not_paired(self):
        """S5_02_03 日文是一页式固定版式，与中文文本化重排无法逐行对应。"""
        self.assertIn("S5_02_03", alignment_rules.NON_PAIR_WORK_IDS)

    def test_pair_difference_is_a_problem_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            cn = cache / "chinese-text" / "[S1_01]中" / "OEBPS" / "Text"
            jp = cache / "japanese-text" / "[S1_01]日" / "OEBPS" / "Text"
            cn.mkdir(parents=True)
            jp.mkdir(parents=True)
            (cn / "S1_01-01_Chapter1.xhtml").write_text(
                xhtml(["<p>一</p>"]), encoding="utf-8"
            )
            (jp / "S1_01-01_p-001.xhtml").write_text(
                xhtml(["<p>一</p>", "<p>二</p>"]), encoding="utf-8"
            )
            with patch.object(sys, "argv", ["check_alignment.py", "--cache", str(cache)]):
                self.assertEqual(check_alignment.main(), 0)
            report = (cache / "alignment-check.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("配对差异", report)
            self.assertIn("行数", report)
            with patch.object(
                sys,
                "argv",
                ["check_alignment.py", "--cache", str(cache), "--strict"],
            ):
                self.assertEqual(check_alignment.main(), 1)

    def test_missing_japanese_cache_side_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            cn = cache / "chinese-text" / "[S1_01]中" / "OEBPS" / "Text"
            cn.mkdir(parents=True)
            (cn / "S1_01-01_Chapter1.xhtml").write_text(
                xhtml(["<p>一</p>"]), encoding="utf-8"
            )
            with patch.object(
                sys,
                "argv",
                ["check_alignment.py", "--cache", str(cache), "--strict"],
            ):
                self.assertEqual(check_alignment.main(), 0)
            self.assertTrue((cache / "alignment-check.tsv").is_file())

    def test_zero_content_sequence_is_a_strict_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            cn = cache / "chinese-text" / "[S1_01]中" / "OEBPS" / "Text"
            jp = cache / "japanese-text" / "[S1_01]日" / "OEBPS" / "Text"
            cn.mkdir(parents=True)
            jp.mkdir(parents=True)
            (cn / "S1_01-00_Prologue.xhtml").write_text(
                xhtml(["<p>一</p>"]), encoding="utf-8"
            )
            (jp / "S1_01-00_p-001.xhtml").write_text(
                xhtml(["<p>一</p>"]), encoding="utf-8"
            )
            with patch.object(
                sys,
                "argv",
                ["check_alignment.py", "--cache", str(cache), "--strict"],
            ):
                self.assertEqual(check_alignment.main(), 1)
            report = (cache / "alignment-check.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("内容序 -00 非法", report)

    def test_standalone_br_positions_must_match(self):
        japanese = xhtml(["<p>一</p>", "<br/>", "<p>二</p>"]).splitlines()
        chinese = xhtml(["<br/>", "<p>一</p>", "<p>二</p>"]).splitlines()
        problems = check_alignment.pair_problems("S1_01-01", japanese, chinese)
        self.assertIn("<br/> 位置 JP[7] vs CN[6]", problems)

    def test_textual_image_headers_waive_pairing_checks(self):
        """文本化图片例外（AGENTS.md）：配对检查整体豁免（行数/h2/图片行/<br/>）。"""
        japanese = xhtml(["<p>一</p>", "<br/>", "<p>二</p>"]).splitlines()
        chinese = xhtml(["<br/>", "<p>一</p>", "<p>二</p>"]).splitlines()
        for header in ("S2_14-02", "S2_14-04", "S2_14-07", "S2_14-10", "S2_14-13"):
            self.assertEqual(
                check_alignment.pair_problems(header, japanese, chinese), [])
        problems = check_alignment.pair_problems("S1_01-01", japanese, chinese)
        self.assertTrue(any(p.startswith("<br/> 位置") for p in problems))


if __name__ == "__main__":
    unittest.main()
