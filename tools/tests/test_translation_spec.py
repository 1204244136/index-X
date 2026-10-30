from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import check_translation_spec as cts  # noqa: E402

HEAD = "<?xml version='1.0' encoding='utf-8'?>"
DOCT = "<!DOCTYPE html>"
BODY_OPEN = ('<html xmlns="http://www.w3.org/1999/xhtml">'
             '<head><title>t</title></head><body>')


def p9_pattern():
    return [rx for rx, cat, _sev, _msg in cts.CHECK_TEXT if cat == "P9"][0]


class P9EventNameExemptionTests(unittest.TestCase):
    """P9 对「赛事项目名 + 公里」放行，但仍须抓住一般距离/时速里的「公里」「公斤」。

    豁免是负向先行断言：最容易出的错是**豁免写宽了**，把真缺陷一起放掉，
    报告看起来变干净了、其实漏报。所以正反两侧都要有最小用例。
    """

    def test_event_names_exempt(self):
        rx = p9_pattern()
        for s in ("十公里长跑的指定路线",
                  "十公里长跑无法通行",
                  "十公里赛跑",
                  "五公里路跑",
                  "二十公里越野",
                  "十公里马拉松"):
            with self.subTest(s=s):
                self.assertIsNone(rx.search(s), "赛事项目名不应命中 P9：%s" % s)

    def test_plain_units_still_flagged(self):
        rx = p9_pattern()
        for s in ("直径达十公里左右的学艺都市外周",
                  "距离约十公里",
                  "五公斤重",
                  "以公里为单位"):
            with self.subTest(s=s):
                self.assertIsNotNone(rx.search(s), "一般单位用法仍应命中 P9：%s" % s)

    def test_suffix_list_is_the_documented_closed_set(self):
        """词表是封闭集合：改动必须同步 docs/translation-spec.md 与译名裁定总表。"""
        self.assertEqual(
            cts.P9_EVENT_SUFFIXES,
            ("长跑", "赛跑", "路跑", "马拉松", "竞走", "接力", "越野", "健走", "徒步"),
        )


class P9EndToEndTests(unittest.TestCase):
    """端到端跑一遍 main()：确认豁免在整条管线里生效，而不只是正则层面。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.cache = self.tmp / "cache"
        self.out = self.tmp / "out"

    def build_book(self, paragraphs):
        text_dir = self.cache / "【S1_10】测试书" / "OEBPS" / "Text"
        text_dir.mkdir(parents=True, exist_ok=True)
        lines = [HEAD, DOCT, BODY_OPEN, "<h1>第一章</h1>", ""]
        lines += ["<p>%s</p>" % p for p in paragraphs]
        lines.append("</body></html>")
        (text_dir / "S1_10-07_Chapter8.xhtml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_checker(self):
        argv = sys.argv
        sys.argv = ["check_translation_spec.py",
                    "--cache", str(self.cache), "--output", str(self.out)]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                cts.main()
        finally:
            sys.argv = argv
        tsv = (self.out / "translation-spec-check.tsv").read_text(encoding="utf-8")
        return [ln for ln in tsv.splitlines() if "\tP9\t" in ln]

    def test_default_source_is_archive_without_cache(self):
        self.build_book(["正文。"])
        with patch.dict(cts.__dict__, {"DEFAULT_ROOT": str(self.cache),
                                     "DEFAULT_CACHE": str(self.tmp / "missing-cache")}):
            with patch.object(sys, "argv", ["check_translation_spec.py", "--output", str(self.out)]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cts.main(), 0)
        import json
        report = json.loads((self.out / "translation-spec-check.json").read_text(encoding="utf-8"))
        self.assertEqual(report["books_checked"], 1)

    def test_empty_selection_is_setup_error_without_report(self):
        self.build_book(["正文。"])
        with patch.object(sys, "argv", ["check_translation_spec.py", "--cache", str(self.cache),
                                       "--pattern", "*unknown*", "--output", str(self.out)]):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cts.main(), 2)
        self.assertFalse(self.out.exists())

    def test_report_write_failure_returns_two_on_stderr(self):
        self.build_book(["正文。"])
        self.out.write_text("not a directory", encoding="utf-8")
        errors = io.StringIO()
        with patch.object(sys, "argv", ["check_translation_spec.py", "--cache", str(self.cache),
                                       "--output", str(self.out)]):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                self.assertEqual(cts.main(), 2)
        self.assertIn("未完成", errors.getvalue())

    def test_event_name_not_reported_but_distance_is(self):
        self.build_book([
            "这附近的路好像是十公里长跑的指定路线。",
            "整体直径达十公里左右的都市外周。",
        ])
        hits = self.run_checker()
        self.assertEqual(len(hits), 1, "应只报一般距离那一处，实得：%r" % (hits,))
        # 只比 example 列：message 里本身带「十公里长跑」这个示例词
        example = hits[0].split("\t")[-1]
        self.assertIn("十公里左右", example)
        self.assertNotIn("十公里长跑", example)

    def test_clean_book_reports_no_p9(self):
        self.build_book(["这附近的路好像是十公里长跑的指定路线。"])
        self.assertEqual(self.run_checker(), [])

    def test_invalid_input_root_returns_two_without_writing_reports(self):
        for kind in ("missing", "file"):
            with self.subTest(kind=kind):
                if kind == "file":
                    self.cache.write_text("not a directory", encoding="utf-8")
                output, errors = io.StringIO(), io.StringIO()
                with patch.object(sys, "argv", ["check_translation_spec.py", "--cache", str(self.cache),
                                               "--output", str(self.out)]):
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                        self.assertEqual(cts.main(), 2)
                self.assertEqual(output.getvalue(), "")
                self.assertIn(str(self.cache), errors.getvalue())
                self.assertFalse(self.out.exists())


class P16TraditionalChineseTests(unittest.TestCase):
    """P16 只抓中文正文的繁体字。

    放行面容易写宽（包装页、含假名的原文引用行），白名单面容易漏（简繁同形或
    中文规范本就用该字形的「著／祇／潟／瞭／吋／乾」与已裁定保留的专名用字
    「姪／燐／鮟鱇」）。两侧都要有最小用例。
    """

    def p16(self, line, fkind="content"):
        return [h for h in cts.check_text(line, fkind) if h[0] == "P16"]

    def test_traditional_flagged(self):
        for s in ("<p>「這就說來話長了。」</p>",
                  "<p>准確來說，他是個好人。</p>",
                  "<p>「所有的魔法都應该平等分配。」</p>"):
            with self.subTest(s=s):
                self.assertTrue(self.p16(s), "正文繁体应命中 P16：%s" % s)

    def test_simplified_clean(self):
        for s in ("<p>「这就说来话长了。」</p>", "<p>他说：没问题。</p>"):
            with self.subTest(s=s):
                self.assertFalse(self.p16(s), "简体不应命中 P16：%s" % s)

    def test_normative_forms_not_flagged(self):
        for s in ("<p>以气质优雅著称的常盘台大小姐。</p>",
                  "<p>包含任何神祇或恶魔。</p>",
                  "<p>是一名应该正在就读大学的年轻男性，乾山庄治。</p>",
                  "<p>暗器高手姪龙、捕食女王瑛魅。</p>",
                  "<p>由蓝白燐光构成的巨大长枪。</p>",
                  "<p>深海鮟鱇那样用火光吸引人类。</p>"):
            with self.subTest(s=s):
                self.assertFalse(self.p16(s), "规范用字不应命中 P16：%s" % s)

    def test_packaging_pages_exempt(self):
        for kind in ("note", "info", "after", "other"):
            with self.subTest(kind=kind):
                self.assertFalse(self.p16("<li>原文写作「妹達」。</li>", kind),
                                 "包装页不应命中 P16：%s" % kind)

    def test_kana_line_exempt(self):
        self.assertFalse(self.p16("<p>形状是く字形，這裡是日文引用。</p>"),
                         "含假名的原文引用行不应命中 P16")


class P15SidiTests(unittest.TestCase):
    """P15 抓比况助词异形「似地」，但放过 似-compound 后接「地」的黏着组合。

    豁免写成负向后视，最容易出的错是**豁免写宽了**：把「似」前一个字一概放行，
    真缺陷就漏报了。两侧都要有最小用例，并锁死封闭字表。
    """

    def p15(self, line, fkind="content"):
        return [h for h in cts.check_text(line, fkind) if h[0] == "P15"]

    def test_particle_form_flagged(self):
        for s in ("<p>史提尔无可奈何地摇了摇头，仿佛想再透过浓烟看上一眼似地，说道：</p>",
                  "<p>他嫌麻烦似地朝身旁的一名黑衣人挥了挥手，</p>",
                  "<p>美琴抓住上条的后颈，像要咬上去似地在他耳边大喊。</p>",
                  "<p>少女垂着头，像在重复着什么似地低声呢喃。</p>"):
            with self.subTest(s=s):
                self.assertTrue(self.p15(s), "比况助词「似地」应命中 P15：%s" % s)

    def test_compounds_exempt(self):
        for s in ("<p>一幢类似地铁出入口的建筑物附近，有一群人影穿越而过。</p>",
                  "<p>不远处还开着状似地下暗渠入口的铁路隧道。</p>",
                  "<p>神裂听到了某种类似地鸣的声音。</p>",
                  "<p>使其气候、温度、生态类似地球的环境。</p>",
                  "<p>两条曲线相似地展开。</p>",
                  "<p>那是一枚形似地雷的装置。</p>"):
            with self.subTest(s=s):
                self.assertFalse(self.p15(s), "黏着组合不应命中 P15：%s" % s)

    def test_normative_form_clean(self):
        for s in ("<p>仿佛想再透过浓烟看上一眼似的，说道：</p>",
                  "<p>就像发生了小火灾一样。</p>"):
            with self.subTest(s=s):
                self.assertFalse(self.p15(s), "规范词形不应命中 P15：%s" % s)

    def test_compound_prefix_table_is_the_documented_closed_set(self):
        """字表是封闭集合：改动必须同步 docs/translation-spec.md §一.9。"""
        self.assertEqual(cts.P15_SIDI_COMPOUND_PREFIX, "类状形近相好恰神酷胜貌疑宛似")


class P15PalaTests(unittest.TestCase):
    """P15 抓拟声词「噼里啪啦」的异形写法，放过规范词形本身。

    异形面容易漏：起头字（噼／劈／霹）、承接字（里／哩／雳）、末字（啦／拉）
    三种维度都会被写错，两侧都要有最小用例。
    """

    def p15(self, line, fkind="content"):
        return [h for h in cts.check_text(line, fkind) if h[0] == "P15"]

    def test_variants_flagged(self):
        for s in ("<p>随着一阵疑似柔软物体破裂的霹哩啪啦声，多臂男撑破了那件燕尾服。</p>",
                  "<p>劈里啪啦！伴随着轰响，测定机械的游戏机前后左右上下剧烈摇晃。</p>",
                  "<p>她身上开始霹雳啪啦地响起来了。</p>",
                  "<p>刘海噼哩啪啦地迸出蓝白色的火花。</p>",
                  "<p>美琴的指尖噼里啪拉地放电。</p>"):
            with self.subTest(s=s):
                self.assertTrue(self.p15(s), "拟声词异形应命中 P15：%s" % s)

    def test_normative_form_clean(self):
        for s in ("<p>随着一阵疑似柔软物体破裂的噼里啪啦声，多臂男撑破了那件燕尾服。</p>",
                  "<p>噼里啪啦噼里啪啦！让人心惊胆战的电击声迸裂开来。</p>",
                  "<p>那是一枚形似地雷的装置。</p>"):
            with self.subTest(s=s):
                self.assertFalse(self.p15(s), "规范词形不应命中 P15：%s" % s)


if __name__ == "__main__":
    unittest.main()
