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


class P26DateExpressionTests(unittest.TestCase):
    """P26 按故事体与功能页分域校验日期数字、占位零与单位间距。"""

    def p26(self, line, fkind="content"):
        return [h for h in cts.check_text(line, fkind) if h[0] == "P26"]

    def test_classify_splits_story_intro_afterwords_and_image_pages(self):
        self.assertEqual(cts.classify("S2_22-02_Prologue.xhtml"), "content")
        self.assertEqual(cts.classify("S1_03-07_Afterwords.xhtml"), "after")
        self.assertEqual(cts.classify("S1_25-Afterwords.xhtml"), "after")
        self.assertEqual(cts.classify("S1_01-Note.xhtml"), "note")
        self.assertEqual(cts.classify("S1_01-Information.xhtml"), "info")
        self.assertEqual(cts.classify("S1_01-Introduction.xhtml"), "intro")
        self.assertEqual(cts.classify("S1_01-Illustrations.xhtml"), "img")
        self.assertEqual(cts.classify("S6_10.06.26-Manga.xhtml"), "img")
        self.assertEqual(cts.classify("S2_20-Special.xhtml"), "other")

    def test_story_ling_year_and_arabic_calendar_dates_are_errors(self):
        bad_story = (
            "<p>「一六零二年？这家伙十五岁的时候？」</p>",
            "<p>「大女儿莉莉丝明明是1904年出生的。」</p>",
            "<p>这个人在1170年12月29日被暗杀了。</p>",
            "<p>第一次得到正式确认是在1750年代，巴黎的社交界。</p>",
            "<p>他生活在80年代。</p>",
            "<p>传说起源于公历1378年。</p>",
            "<p>智慧的大女神的知识停留在19世纪。</p>",
            "<p>打捞在17～18世纪集中沉没的古商船。</p>",
            "<p>在12月25日发生的「暗部」清除。</p>",
            "<p>ATM恢复运行要等到明年1月4号。</p>",
            "<p>看着倾泻下来的阳光，真的快要忘记现在是9月的事情了。</p>",
        )
        for kind in ("content", "after", "other"):
            for s in bad_story:
                with self.subTest(kind=kind, s=s):
                    hits = self.p26(s, kind)
                    self.assertTrue(hits, "故事体违规日期应命中 P26 (%s)：%s" % (kind, s))
                    self.assertTrue(any(h[1] == "error" for h in hits),
                                    "应为 error 级：%s" % (hits,))

    def test_story_standalone_arabic_day_is_warning(self):
        for s in ("<p>『生日是28日。可是因为放寒假谁都聚不起来。』</p>",
                  "<p>（在29日的事件中一次都没出现过的地方。）</p>"):
            with self.subTest(s=s):
                hits = self.p26(s, "content")
                self.assertTrue(hits, "故事体单写阿拉伯日期应提示 P26：%s" % s)
                self.assertEqual(hits[0][1], "warning")

    def test_unit_space_is_error_in_both_story_and_packaging(self):
        for kind in ("content", "note", "info", "intro"):
            for s in ('<li epub:type="footnote" id="note1">1872 年，在大西洋被发现。</li>',
                      '<li epub:type="footnote" id="note8">颁布前（1868 年～1947 年）存在。</li>',
                      "<p>收录于 2018 年 4 月 10 日发售的杂志。</p>"):
                with self.subTest(kind=kind, s=s):
                    hits = self.p26(s, kind)
                    self.assertTrue(hits, "数字与时间单位间空格应命中 P26 (%s)：%s" % (kind, s))
                    self.assertTrue(all(h[1] == "error" for h in hits))

    def test_story_clean_and_exemptions_not_flagged(self):
        clean_story = (
            "<p>「大女儿莉莉丝明明是一九〇四年出生的。」</p>",
            "<p>「一六〇二年？传说起源于公历一三七八年，生活在一六〇〇年代。」</p>",
            "<p>这个人在一一七〇年十二月二十九日被暗杀了。</p>",
            "<p>智慧的大女神的知识停留在十九世纪。</p>",
            "<p>打捞在十七～十八世纪集中沉没的古商船。</p>",
            "<p>束缚1000年的封印，维持1000年的安定，跨越100年的计划。</p>",
            "<p>大概需要3个月时间，过了10日后或3日内再看第3日。</p>",
            "<p>钱包里只剩30日元，买不到5号电池、7号电池或12号弹，生菜3号也是。</p>",
            "<p>「Soror,Kingsford,1888。」使用F2000R与Nu-AD1967武装。</p>",
            '<h1 class="heading-lines"><span class="heading-main">第三章</span>'
            '<span class="heading-code font06">A.D.1900_Invisible_War.</span></h1>',
            '<h2 id="toc_1">1（<span>Aug.31_AM00:00</span>）</h2>',
        )
        for s in clean_story:
            with self.subTest(s=s):
                self.assertFalse(self.p26(s, "content"), "合规正文与豁免写法不应命中 P26：%s" % s)

    def test_packaging_and_image_pages_allow_arabic_and_quoted_kanji_dates(self):
        for kind in ("note", "info", "intro", "img"):
            for s in (
                '<li epub:type="footnote" id="note1">1872年在大西洋发现，15～17世纪流行。</li>',
                '<li epub:type="footnote" id="note2">朔勒姆（1897-1982），19世纪人物。</li>',
                '<li epub:type="footnote" id="note3">原文为：一九九三年就禁止贩卖。</li>',
                '<li epub:type="footnote" id="note4">嘉永六年（1853年）黑船来航。</li>',
                '<li epub:type="footnote" id="note5">「二十日鼠」或者「廿日鼠」。</li>',
                "<p>2018年4月10日发售，8月31日的学园都市，10月。100年前。</p>",
            ):
                with self.subTest(kind=kind, s=s):
                    self.assertFalse(self.p26(s, kind), "功能/图片页合法写法不应命中 P26 (%s)：%s" % (kind, s))

    def test_audit_book_applies_file_classification_for_p26(self):
        with tempfile.TemporaryDirectory() as td:
            text_dir = Path(td)
            (text_dir / "S2_22-02_Prologue.xhtml").write_text(
                "\n".join([HEAD, DOCT, BODY_OPEN, "<h1>序章</h1>",
                           "<p>大女儿莉莉丝明明是1904年出生的。</p>",
                           "</body></html>"]),
                encoding="utf-8",
            )
            (text_dir / "S1_25-Afterwords.xhtml").write_text(
                "\n".join([HEAD, DOCT, BODY_OPEN, "<h1>后记</h1>",
                           "<p>写于2008年10月。</p>",
                           "</body></html>"]),
                encoding="utf-8",
            )
            (text_dir / "S1_01-Note.xhtml").write_text(
                "\n".join([HEAD, DOCT, BODY_OPEN, "<h1>译注</h1>", "<ul>",
                           '<li epub:type="footnote" id="note1">玛丽号是1872 年被发现的船。</li>',
                           '<li epub:type="footnote" id="note2">原文为：一九九三年禁止贩卖。</li>',
                           "</ul></body></html>"]),
                encoding="utf-8",
            )
            (text_dir / "S1_01-Introduction.xhtml").write_text(
                "\n".join([HEAD, DOCT, BODY_OPEN, "<h1>简介</h1>",
                           "<p>8月31日的学园都市。</p>",
                           "</body></html>"]),
                encoding="utf-8",
            )
            p26_hits = [h for h in cts.audit_book(text_dir) if h[2] == "P26"]
            self.assertEqual(len(p26_hits), 4)
            hit_files = [(h[0], h[1], h[3]) for h in p26_hits]
            self.assertEqual(hit_files, [
                ("S1_01-Note.xhtml", 6, "error"),
                ("S1_25-Afterwords.xhtml", 5, "error"),
                ("S1_25-Afterwords.xhtml", 5, "error"),
                ("S2_22-02_Prologue.xhtml", 5, "error"),
            ])

    def test_errors_only_matches_filtered_full_audit_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            text_dir = Path(td)
            (text_dir / "S1_01-01_Chapter1.xhtml").write_text(
                "\n".join([
                    HEAD, DOCT, BODY_OPEN, "<h1>第一章</h1>", "",
                    "<p>半角,标点和 ~ 波浪号，还有！？与。。和……。及〇.七。</p>",
                    "<p>“弯引号”与十公里和呀吼还有カタカナ与繁體字，二零〇一年1月2日。</p>",
                    "<p>   三个空格，还有<ruby>魔<rt>ま</rt></ruby>。</p>",
                    "</body></html>",
                ]),
                encoding="utf-8",
            )
            (text_dir / "S1_01-Note.xhtml").write_text(
                "\n".join([
                    HEAD, DOCT, BODY_OPEN, "<h1>译注</h1>", "<ul>",
                    '<li epub:type="footnote" id="note1">（半角)与（不配对和（英语：test）1872 年。</li>',
                    '<li epub:type="footnote" id="note2">这里指【标记】1至3米，详见注释1。</li>',
                    "</ul></body></html>",
                ]),
                encoding="utf-8",
            )
            full_errors = [h for h in cts.audit_book(text_dir) if h[3] == "error"]
            fast_errors = cts.audit_book(text_dir, errors_only=True)
            self.assertEqual(fast_errors, full_errors)
            self.assertTrue(any(h[2] == "P1" for h in fast_errors))
            self.assertTrue(any(h[2] == "P17" for h in fast_errors))
            self.assertTrue(any(h[2] == "P20" for h in fast_errors))
            self.assertTrue(any(h[2] == "P26" for h in fast_errors))


if __name__ == "__main__":
    unittest.main()
