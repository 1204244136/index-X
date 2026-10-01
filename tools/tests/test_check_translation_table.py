from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

# openpyxl 与 read_xlsx.py 保持一致的**可选依赖**口径：CI 只用官方 Python 环境、
# 不安装任何第三方包，此处若硬导入会在测试采集阶段就 ImportError，使整个
# unittest discover 失败（而不是仅跳过 Excel 相关用例）。
try:
    import openpyxl
except ImportError:  # pragma: no cover - 取决于运行环境是否装有 openpyxl
    openpyxl = None  # type: ignore

from check_translation_table import (  # noqa: E402
    DEFAULT_X_DIFF,
    ToolError,
    audit_x_diff,
    book_id,
    collect_books,
    compare,
    fold,
    is_suspect,
    load_table,
    load_x_diff,
    main,
    norm_anchor,
    strip_markup,
)


class NormTests(unittest.TestCase):
    def test_fullwidth_equals_and_brackets_normalized(self):
        # 归一化含 §5.3 折叠，故比较也应走同一函数（两侧写成等价形式即相等）
        self.assertEqual(norm_anchor("アンナ＝シュプレンゲル"),
                         norm_anchor("アンナ=シュプレンゲル"))
        self.assertEqual(norm_anchor("【実践魔女】"), "実践魔女")

    def test_whitespace_removed(self):
        self.assertEqual(norm_anchor("超絶者 　アラディア"),
                         norm_anchor("超絶者アラディア"))


class StripMarkupTests(unittest.TestCase):
    """剥标签 + 反转义实体：含 `&` 的术语必须能匹配（`R&amp;C` → `R&C`）。"""

    def test_entity_unescaped(self):
        self.assertEqual(strip_markup("<p>R&amp;C超自然公司</p>"), "R&C超自然公司")

    def test_escaped_tags_survive(self):
        """顺序是「先剥标签、再反转义」：`&lt;p&gt;` 应还原成字面文本，而不是被当标签删掉。"""
        self.assertEqual(strip_markup("<p>a&lt;b&gt;c</p>"), "a<b>c")

    def test_rt_stripped_before_unescape(self):
        self.assertEqual(strip_markup("<p><ruby>主神之枪<rt>Gungnir</rt></ruby></p>"), "主神之枪")

    def test_nbsp_becomes_removable_whitespace(self):
        self.assertEqual(norm_anchor(strip_markup("<p>a&nbsp;b</p>")), "ab")

    def test_ampersand_term_lands_against_table(self):
        """端到端语义：成品含 `&amp;`、表内是 `&`，反转义后应判落地（此前误报未落地）。"""
        recs, _s, _sh = compare(
            [{"ori": "テスト", "trans": "R&C超自然公司", "type": "", "debuts": ""}],
            {"S1_01": "テスト"},
            {"S1_01": strip_markup("<p>R&amp;C超自然公司</p>")})
        self.assertEqual(recs[0]["status"], "landed")


class FoldTests(unittest.TestCase):
    """§5.3「不妥协写法」：译名表写不妥协形式，BW 源是印刷妥协形式（注音小字假名写成
    大字、半角英数写成全角），检索时两侧必须同时折叠——否则大量条目会静默漏检。
    """

    # (源侧妥协形, 表侧不妥协写法)
    CASES = [
        ("レベル６シフト", "レベル6シフト"),          # 全角英数 → 半角
        ("シープ＆シープ", "シープ&シープ"),          # 全角 ＆ → 半角 &
        ("ジェーン＝エルブス", "ジェーン=エルブス"),    # 全角 ＝ → 半角 =
        ("ＵＭＡ", "UMA"),
        ("ＯＳ", "OS"),
        ("ＭＲＩスキャナ", "MRIスキャナ"),
        ("五〇％減", "五〇%減"),
        ("カリキユラム", "カリキュラム"),            # 大字假名 → 小字（折叠到同一形式）
        ("エキシビジヨン", "エキシビジョン"),
        ("レデイオノイズ", "レディオノイズ"),
        ("スチユーデントキーパー", "スチューデントキーパー"),
        ("ヒユドラ", "ヒュドラ"),
        ("ペルセフオネ", "ペルセフォネ"),
    ]

    def test_source_and_table_forms_fold_together(self):
        for src, tbl in self.CASES:
            with self.subTest(src=src):
                self.assertEqual(norm_anchor(src), norm_anchor(tbl))

    def test_fold_is_not_a_rewrite(self):
        """折叠只服务匹配：大字本来就不变，小字折叠为对应大字。"""
        self.assertEqual(fold("カリキユラム"), "カリキユラム")
        self.assertEqual(fold("カリキュラム"), "カリキユラム")
        self.assertEqual(fold("レベル６シフト"), "レベル6シフト")

    def test_other_marks_are_not_folded(self):
        """日文中黑点 `・` 与中文间隔号 `·` 不折叠——§5.2 明确二者算不一致，须保持可检出。"""
        self.assertNotEqual(norm_anchor("クロウリーズ・ハザード"),
                            norm_anchor("クロウリーズ·ハザード"))


class StripMarkupTests(unittest.TestCase):
    def test_rt_removed_before_tags(self):
        # 注音不得串入正文：剥掉 <rt> 后锚点才可检索
        self.assertEqual(
            strip_markup("<p><ruby>橋架結社<rt>はしかけけつしや</rt></ruby>だ</p>"),
            "橋架結社だ")

    def test_rp_removed(self):
        self.assertEqual(
            strip_markup("<ruby>漢<rp>(</rp><rt>かん</rt><rp>)</rp></ruby>"), "漢")


class IsSuspectTests(unittest.TestCase):
    def test_kana_neighbour_is_suspect(self):
        self.assertTrue(is_suspect("パニック", 1, "ニック"))

    def test_quote_neighbour_is_not_suspect(self):
        self.assertFalse(is_suspect("『橋架結社』の", 1, "橋架結社"))

    def test_cjk_neighbour_is_suspect(self):
        self.assertTrue(is_suspect("超絶者達", 0, "超絶者"))


class CompareTests(unittest.TestCase):
    """核心判定：每个分支都要有一个能触发它的最小反例。

    体检类工具最大的风险不是漏报，而是**永远报 0**（判定写错、归一化没生效、
    路径没匹配上）却看上去一切正常。
    """

    @staticmethod
    def entry(ori: str, trans: str) -> dict[str, str]:
        return {"ori": ori, "trans": trans, "type": "", "debuts": ""}

    def test_landed_not_reported(self):
        recs, _skipped, _shared = compare(
            [self.entry("橋架結社", "桥架结社")],
            {"S1_01": "『橋架結社』の会議"},
            {"S1_01": "『桥架结社』的会议"})
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["status"], "landed")

    def test_missing_detected(self):
        """负向自检：中文侧写成 Miliphone（表定 Milliphone）必须报未落地。"""
        recs, _skipped, _shared = compare(
            [self.entry("ミリフォン", "Milliphone")],
            {"S1_01": "最新スマホ・ミリフォン15"},
            {"S1_01": "最新型智能手机Miliphone 15"})
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["status"], "missing")
        self.assertEqual(recs[0]["suspect"], "")  # 前后是「・」与数字，非疑似子串

    def test_suspect_substring_flagged(self):
        recs, _skipped, _shared = compare(
            [self.entry("ニック", "尼克")],
            {"S1_01": "パニックが起きる"},
            {"S1_01": "发生了恐慌"})
        self.assertEqual(recs[0]["status"], "missing")
        self.assertEqual(recs[0]["suspect"], "1")

    def test_anchor_absent_in_japanese_not_reported(self):
        recs, _skipped, _shared = compare(
            [self.entry("存在しない語", "不存在的词")],
            {"S1_01": "本文"},
            {"S1_01": "正文"})
        self.assertEqual(recs, [])

    def test_empty_translation_skipped(self):
        """表内译名为空（尚未定名）→ 跳过核对，不计未落地。"""
        recs, skipped, _shared = compare(
            [self.entry("オーバー", "")],
            {"S1_01": "どうぞ。【オーバー】"},
            {"S1_01": "完毕。【结束】"})
        self.assertEqual(recs, [])
        self.assertEqual(skipped, 1)

    def test_short_anchor_skipped(self):
        recs, _skipped, _shared = compare(
            [self.entry("あ", "啊")],
            {"S1_01": "あいうえお"},
            {"S1_01": "啊"})
        self.assertEqual(recs, [])

    def test_only_shared_books_compared(self):
        recs, _skipped, shared = compare(
            [self.entry("橋架結社", "桥架结社")],
            {"S1_01": "橋架結社", "S1_02": "橋架結社"},
            {"S1_01": "桥架结社"})
        self.assertEqual(shared, ["S1_01"])
        self.assertEqual([r["book"] for r in recs], ["S1_01"])

    def test_normalization_applies_to_both_sides(self):
        """表内半角 `=`／带【】的锚点，要能匹配原文的全角 `＝` 与裸写。"""
        recs, _skipped, _shared = compare(
            [self.entry("アンナ=シュプレンゲル", "安娜·施普伦格尔"),
             self.entry("【実践魔女】", "实践魔女")],
            {"S1_01": "アンナ＝シュプレンゲルと実践魔女"},
            {"S1_01": "安娜·施普伦格尔与实践魔女"})
        self.assertEqual(len(recs), 2)
        self.assertEqual({r["status"] for r in recs}, {"landed"})

    def test_rt_reading_does_not_count_as_hit(self):
        """锚点只出现在注音里时不得算命中（由 collect_books 剥 rt 保证）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / "[S1_01]书" / "item" / "xhtml"
            d.mkdir(parents=True)
            (d / "a.xhtml").write_text(
                "<p><ruby>漢字<rt>かんじ</rt></ruby></p>", encoding="utf-8")
            books = collect_books(root, "item/xhtml", set())
            self.assertEqual(books["S1_01"].strip(), "漢字")
            recs, _skipped, _shared = compare(
                [self.entry("かんじ", "汉字")], books, {"S1_01": "汉字"})
            self.assertEqual(recs, [])

    def test_context_includes_anchor(self):
        recs, _skipped, _shared = compare(
            [self.entry("橋架結社", "桥架结社")],
            {"S1_01": "『橋架結社』の会議"},
            {"S1_01": "『桥架结社』的会议"})
        self.assertIn("【橋架結社】", recs[0]["jp_context"])


class BookIdTests(unittest.TestCase):
    def test_book_id_variants(self):
        self.assertEqual(book_id("[S3_06]创约 某魔法的禁书目录 06X"), "S3_06")
        self.assertEqual(book_id("[S5_01_03]某魔法的禁书目录SS"), "S5_01_03")
        self.assertEqual(book_id("[S6_24.06.07]某科学的超电磁炮 SS"), "S6_24.06.07")
        self.assertEqual(book_id("无方括号"), "")


class CollectBooksTests(unittest.TestCase):
    def test_collects_only_requested_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for bid in ("S1_01", "S2_01"):
                d = root / ("[%s]书" % bid) / "item" / "xhtml"
                d.mkdir(parents=True)
                (d / "a.xhtml").write_text("<p>本文</p>", encoding="utf-8")
            books = collect_books(root, "item/xhtml", {"S1_01"})
            self.assertEqual(list(books), ["S1_01"])
            self.assertEqual(len(collect_books(root, "item/xhtml", set())), 2)

    def test_missing_root_returns_empty(self):
        self.assertEqual(collect_books(Path("不存在的目录"), "item/xhtml", set()), {})


@unittest.skipUnless(openpyxl is not None, "未安装 openpyxl，跳过译名表相关用例")
class LoadTableTests(unittest.TestCase):
    @staticmethod
    def make_table(tmp: Path) -> Path:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "data"
        ws.append(["Debuts", "Base_Ori", "Base_Trans", "Type"])
        ws.append(["正传 创约04", "ミリフォン", "Milliphone", "科技/装备"])
        ws.append(["正传 创约04", "オーバー", "", "术语"])
        path = tmp / "table.xlsx"
        wb.save(path)
        return path

    def test_reads_expected_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries, headers = load_table(self.make_table(Path(tmp)), "data",
                                          "Base_Ori", "Base_Trans", "Type", "Debuts")
            self.assertIn("Base_Ori", headers)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["ori"], "ミリフォン")
            self.assertEqual(entries[0]["trans"], "Milliphone")

    def test_missing_column_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ToolError):
                load_table(self.make_table(Path(tmp)), "data",
                           "NoSuchColumn", "Base_Trans", "Type", "Debuts")

    def test_missing_file_rejected(self):
        with self.assertRaises(ToolError):
            load_table(Path("不存在的译名表.xlsx"), "data",
                       "Base_Ori", "Base_Trans", "Type", "Debuts")


class LoadXDiffTests(unittest.TestCase):
    """X 版固有差异门禁：解析 Markdown 表格。

    `docs/x-translation-differences.md` 登记的是本项目与灰机 Wiki 译名表之间
    **人为制定的取舍**（「两侧各自维持、不计入待改、不得按表回改」），
    工具必须先过这道门禁，否则会把这些差异报成术语未落地。
    """

    SAMPLE = "\n".join([
        "# 标题",
        "",
        "| 日文锚点 | 表侧写法 | X 版写法 | 类别 | 说明 |",
        "| --- | --- | --- | --- | --- |",
        "| 妹達 | 妹妹们 | 妹妹 | 符合语境 | 说明文字 |",
        "| ハイウェイクレイドル | Highway Cradle | 高速摇篮号 | 原创词 | — |",
        "| 投擲の槌 | 投掷之锤 | 投掷之锤／雷神之锤 | 中文注音 | 多写法 |",
    ])

    def _write(self, tmp: str, text: str) -> Path:
        p = Path(tmp) / "x.md"
        p.write_text(text, encoding="utf-8")
        return p

    def test_parses_rows_and_skips_header_and_separator(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = load_x_diff(self._write(tmp, self.SAMPLE))
            self.assertEqual(len(d), 3)                     # 表头与分隔行不计入
            self.assertNotIn("日文锚点", d)
            self.assertEqual(d["妹達"]["x"], "妹妹")
            self.assertEqual(d["妹達"]["table"], "妹妹们")
            self.assertEqual(d["妹達"]["cat"], "符合语境")
            # 键是折叠后的形式（§5.3）：ハイウェイ… 的 ウェ 折叠为 ウエ
            self.assertEqual(d[norm_anchor("ハイウェイクレイドル")]["x"], "高速摇篮号")

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_x_diff(Path("不存在的清单.md")), {})

    def test_anchor_is_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = load_x_diff(self._write(tmp, "| 【実践魔女】 | 表 | 里 | 类别 | 说明 |\n"))
            self.assertIn("実践魔女", d)

    RUBY_SAMPLE = "\n".join([
        "| 日文锚点 | 表侧写法 | X 版写法 | 类别 | 说明 |",
        "| --- | --- | --- | --- | --- |",
        "| <ruby>主神の槍<rt>グングニル</rt></ruby> | <ruby>主神之枪<rt>Gungnir</rt></ruby> "
        "| <ruby>主神之枪<rt>冈格尼尔</rt></ruby> | 中文注音 | 仅注音不同 |",
        "| <ruby>投擲の槌<rt>ミヨルニル</rt></ruby> | <ruby>投掷之锤<rt>Mjölnir</rt></ruby> "
        "| <ruby>投掷之锤<rt>妙尔尼尔</rt></ruby>／<ruby>雷神之锤<rt>妙尔尼尔</rt></ruby> "
        "| 中文注音 | 多写法 |",
    ])

    def test_ruby_readings_are_stripped_from_all_columns(self):
        """注音用 `<ruby>` 写在写法列里，解析只取基文（注音不参与匹配）。"""
        with tempfile.TemporaryDirectory() as tmp:
            d = load_x_diff(self._write(tmp, self.RUBY_SAMPLE))
            self.assertIn("主神の槍", d)                       # 锚点取基文
            self.assertEqual(d["主神の槍"]["ori"], "主神の槍")
            self.assertEqual(d["主神の槍"]["table"], "主神之枪")
            self.assertEqual(d["主神の槍"]["x"], "主神之枪")     # 注音已剥
            self.assertNotIn("<ruby>", d["主神の槍"]["x"])
            self.assertNotIn("冈格尼尔", d["主神の槍"]["x"])     # 注音不进匹配值
            self.assertEqual(d["投擲の槌"]["x"], "投掷之锤／雷神之锤")

    def test_ruby_form_matches_plain_cn_text(self):
        """清单写法带 ruby、成品文本已剥注音 —— 仍应判定落地。"""
        with tempfile.TemporaryDirectory() as tmp:
            xd = load_x_diff(self._write(tmp, self.RUBY_SAMPLE))
            recs, _s, _sh = compare(
                [{"ori": "主神の槍", "trans": "主神之枪", "type": "", "debuts": ""}],
                {"S1_01": "主神の槍"},
                {"S1_01": "主神之枪"},          # 成品侧同样已剥注音
                xd)
            self.assertEqual(recs[0]["status"], "landed")
            self.assertEqual(recs[0]["x_form"], "x")

    def test_repo_gate_file_is_present_and_parsable(self):
        """仓库内的门禁文件必须存在、可解析，且覆盖已知条目。"""
        self.assertTrue(DEFAULT_X_DIFF.is_file(), f"门禁文件缺失：{DEFAULT_X_DIFF}")
        d = load_x_diff(DEFAULT_X_DIFF)
        self.assertGreater(len(d), 20, "门禁清单条目数异常偏少")
        for anchor in ("妹達", "ハイウェイクレイドル", "保温鍋バンマリ", "主神の槍"):
            self.assertIn(norm_anchor(anchor), d, f"门禁清单缺少已知条目：{anchor}")

    def test_repo_gate_values_carry_no_ruby_markup(self):
        """仓库门禁解析出的写法必须是干净基文（注音已剥），否则匹配会失败。"""
        d = load_x_diff(DEFAULT_X_DIFF)
        self.assertEqual(d["主神の槍"]["x"], "主神之枪")
        self.assertEqual(d["妹達"]["x"], "妹妹")
        for key, val in d.items():
            for col in ("table", "x"):
                self.assertNotIn("<ruby>", val[col], f"{key}.{col} 残留 ruby 标记")
                self.assertNotIn("<rt>", val[col], f"{key}.{col} 残留 rt 标记")


class CompareWithXDiffTests(unittest.TestCase):
    """门禁生效后的判定分支（每个分支一个反例）。"""

    XD = {"妹達": {"ori": "妹達", "table": "妹妹们", "x": "妹妹", "cat": "符合语境"}}

    @staticmethod
    def entry(ori: str, trans: str) -> dict[str, str]:
        return {"ori": ori, "trans": trans, "type": "", "debuts": ""}

    def test_x_form_lands(self):
        """成品只含 X 版写法 → 落地（不过门禁就会被误报未落地）。"""
        recs, _s, _sh = compare(
            [self.entry("妹達", "妹妹们")],
            {"S1_01": "妹達は"},
            {"S1_01": "妹妹"},
            self.XD)
        self.assertEqual(recs[0]["status"], "landed")
        self.assertEqual(recs[0]["x_diff"], "1")
        self.assertEqual(recs[0]["x_form"], "x")

    def test_longer_form_wins_when_both_present(self):
        """两种写法同时出现时取更长者——否则「妹妹」是「妹妹们」的子串，来源会被误判。"""
        recs, _s, _sh = compare(
            [self.entry("妹達", "妹妹们")],
            {"S1_01": "妹達は"},
            {"S1_01": "妹妹们与妹妹"},
            self.XD)
        self.assertEqual(recs[0]["status"], "landed")
        self.assertEqual(recs[0]["x_form"], "table")

    def test_table_form_lands_but_marked(self):
        """成品退回表侧写法 → 也算落地，但标 x_form=table。"""
        recs, _s, _sh = compare(
            [self.entry("妹達", "妹妹们")],
            {"S1_01": "妹達は"},
            {"S1_01": "妹妹们"},
            self.XD)
        self.assertEqual(recs[0]["status"], "landed")
        self.assertEqual(recs[0]["x_form"], "table")

    def test_neither_form_reports_missing(self):
        """两种写法都没有 → 才报未落地（负向自检）。"""
        recs, _s, _sh = compare(
            [self.entry("妹達", "妹妹们")],
            {"S1_01": "妹達は"},
            {"S1_01": "姐妹们"},
            self.XD)
        self.assertEqual(recs[0]["status"], "missing")
        self.assertEqual(recs[0]["x_form"], "")

    def test_without_gate_the_same_line_is_reported(self):
        """不传门禁时同一行会被报未落地——反证门禁确实在起作用。"""
        recs, _s, _sh = compare(
            [self.entry("妹達", "妹妹们")],
            {"S1_01": "妹達は"},
            {"S1_01": "妹妹"})
        self.assertEqual(recs[0]["status"], "missing")

    def test_multi_form_split_by_fullwidth_slash(self):
        recs, _s, _sh = compare(
            [self.entry("投擲の槌", "投掷之锤")],
            {"S1_01": "投擲の槌"},
            {"S1_01": "雷神之锤"},
            {"投擲の槌": {"ori": "投擲の槌", "table": "投掷之锤",
                          "x": "投掷之锤／雷神之锤", "cat": "中文注音"}})
        self.assertEqual(recs[0]["status"], "landed")
        self.assertEqual(recs[0]["x_form"], "x")


class TranslationHostTests(unittest.TestCase):
    """译文归属映射：日文锚点在 A 书、中文译文在 B 书时仍应判落地。"""

    ENTRY = [{"ori": "テスト", "trans": "译文", "type": "", "debuts": ""}]
    HOST = {"S5_02_03": "S5_02_01"}

    def test_host_book_counts_as_landed(self):
        recs, _s, _sh = compare(self.ENTRY,
                                {"S5_02_03": "テスト"},
                                {"S5_02_03": "无关内容", "S5_02_01": "译文"},
                                None, self.HOST)
        self.assertEqual(recs[0]["status"], "landed")
        self.assertEqual(recs[0]["cn_host"], "S5_02_01")

    def test_without_mapping_reports_missing(self):
        """不传映射时同一行报未落地——反证映射确实在起作用。"""
        recs, _s, _sh = compare(self.ENTRY,
                                {"S5_02_03": "テスト"},
                                {"S5_02_03": "无关内容", "S5_02_01": "译文"})
        self.assertEqual(recs[0]["status"], "missing")
        self.assertEqual(recs[0]["cn_host"], "")

    def test_own_book_takes_precedence(self):
        """自己书命中时不标归属书。"""
        recs, _s, _sh = compare(self.ENTRY,
                                {"S5_02_03": "テスト"},
                                {"S5_02_03": "译文", "S5_02_01": "译文"},
                                None, self.HOST)
        self.assertEqual(recs[0]["status"], "landed")
        self.assertEqual(recs[0]["cn_host"], "")

    def test_host_absent_from_corpus_is_ignored(self):
        """归属书不在语料里时不报错，照旧判未落地。"""
        recs, _s, _sh = compare(self.ENTRY,
                                {"S5_02_03": "テスト"},
                                {"S5_02_03": "无关内容"},
                                None, self.HOST)
        self.assertEqual(recs[0]["status"], "missing")

    def test_repo_mapping_registers_the_known_host(self):
        """仓库映射表必须含已确认的 S5_02_03→S5_02_01。"""
        try:
            from alignment_rules import TRANSLATION_HOST
        except ImportError:  # pragma: no cover
            self.skipTest("无法导入 alignment_rules")
        self.assertEqual(TRANSLATION_HOST.get("S5_02_03"), "S5_02_01")


class SettledAnchorTests(unittest.TestCase):
    """已判定锚点：同形不同义／暂缓，命中时**不计入待判**。"""

    ENTRY = [{"ori": "テスト", "trans": "译文", "type": "", "debuts": ""}]
    SETTLED = {"テスト": "表内是专名，正文是普通词"}

    def test_settled_not_counted_as_missing(self):
        recs, _s, _sh = compare(self.ENTRY,
                                {"S1_01": "テスト"},
                                {"S1_01": "无关内容"},
                                None, None, self.SETTLED)
        self.assertEqual(recs[0]["status"], "settled")

    def test_without_settled_it_is_missing(self):
        """不传登记表时同一行报未落地——反证登记确实在起作用。"""
        recs, _s, _sh = compare(self.ENTRY,
                                {"S1_01": "テスト"},
                                {"S1_01": "无关内容"})
        self.assertEqual(recs[0]["status"], "missing")

    def test_settled_takes_precedence(self):
        """即使中文侧命中也记 settled：该锚点已判定，不再参与落地判定。"""
        recs, _s, _sh = compare(self.ENTRY,
                                {"S1_01": "テスト"},
                                {"S1_01": "译文"},
                                None, None, self.SETTLED)
        self.assertEqual(recs[0]["status"], "settled")

    def test_repo_settled_registers_known_anchors(self):
        try:
            from alignment_rules import SETTLED_ANCHORS
        except ImportError:  # pragma: no cover
            self.skipTest("无法导入 alignment_rules")
        for anchor in ("昼間", "ラベンダー", "ヘイヘイ", "ヒュドラ"):
            self.assertIn(anchor, SETTLED_ANCHORS)

    def test_small_kana_key_is_folded(self):
        """登记表按自然写法维护，含小字假名的键必须能被折叠后查到。"""
        recs, _s, _sh = compare(
            [{"ori": "ヒュドラ", "trans": "海德拉", "type": "", "debuts": ""}],
            {"S1_01": "ヒユドラ"},          # 源侧是大字（折叠后同形）
            {"S1_01": "无关内容"},
            None, None, {"ヒュドラ": "同形不同义"})
        self.assertEqual(recs[0]["status"], "settled")


class AuditXDiffTests(unittest.TestCase):
    """清单 ↔ 译名表一致性核对（`--audit-x-diff`）：每个问题类型一个反例。"""

    @staticmethod
    def entry(ori: str, trans: str, ruby_ori: str = "", ruby_trans: str = "") -> dict[str, str]:
        return {"ori": ori, "trans": trans, "type": "", "debuts": "",
                "ruby_ori": ruby_ori, "ruby_trans": ruby_trans}

    @staticmethod
    def xd(ori_raw: str, table_raw: str = "", x_raw: str = "", cat: str = "类别"):
        """构造与 `load_x_diff` 同形的条目：`table`/`x` 存**剥音后的基文**，`*_raw` 保留原样。"""
        def cell(v: str) -> str:
            v = (v or "").strip()
            return "" if v in ("—", "-", "") else strip_markup(v).strip()

        return {norm_anchor(strip_markup(ori_raw)): {
            "ori": strip_markup(ori_raw).strip(),
            "table": cell(table_raw), "x": cell(x_raw), "cat": cat,
            "ori_raw": ori_raw, "table_raw": table_raw, "x_raw": x_raw}}

    def kinds(self, x_diff, entries):
        return {p["kind"] for p in audit_x_diff(x_diff, entries)}

    def test_clean_sample_reports_nothing(self):
        xd = self.xd("<ruby>妹達<rt>シスターズ</rt></ruby>",
                     "<ruby>妹妹们<rt>Sisters</rt></ruby>", "妹妹")
        e = self.entry("妹達", "妹妹们", "シスターズ", "Sisters")
        self.assertEqual(audit_x_diff(xd, [e]), [])

    def test_table_missing_detected(self):
        """负向自检：表侧留空但译名表有值 → table-missing（本轮实际漏过的类型）。"""
        xd = self.xd("<ruby>妹達<rt>シスターズ</rt></ruby>", "—", "妹妹")
        self.assertIn("table-missing", self.kinds(xd, [self.entry("妹達", "妹妹们")]))

    def test_table_mismatch_detected(self):
        xd = self.xd("妹達", "妹妹", "妹妹")
        self.assertIn("table-mismatch", self.kinds(xd, [self.entry("妹達", "妹妹们")]))

    def test_ruby_ori_mismatch_detected(self):
        """负向自检：锚点 <rt> 照抄了源的大字形式 → ruby-mismatch。"""
        xd = self.xd("<ruby>投擲の槌<rt>ミヨルニル</rt></ruby>", "投掷之锤", "投掷之锤")
        e = self.entry("投擲の槌", "投掷之锤", "ミョルニル")
        self.assertIn("ruby-mismatch", self.kinds(xd, [e]))

    def test_anchor_fullwidth_detected(self):
        """负向自检：锚点写全角 ＆ → anchor-fullwidth（本轮实际漏过的类型）。"""
        xd = self.xd("シープ＆シープ", "", "两只绵羊")
        e = self.entry("シープ&シープ", "Sheep & Sheep")
        self.assertIn("anchor-fullwidth", self.kinds(xd, [e]))

    def test_fullwidth_exempts_cjk_punct_and_separator(self):
        """中文标点 `，` 与多写法分隔符 `／` 不算违规。"""
        xd = self.xd("汝の欲する所を為せ、それが汝の法とならん",
                     "为汝所欲为，即为汝之法", "甲／乙")
        kinds = self.kinds(xd, [])
        self.assertNotIn("table-fullwidth", kinds)
        self.assertNotIn("x-fullwidth", kinds)

    def test_unknown_anchor_with_table_value_is_flagged(self):
        """译名表查无此锚点、清单却填了表侧 → 提示确认依据。"""
        xd = self.xd("存在しない語", "某写法", "另一写法")
        self.assertIn("table-mismatch", self.kinds(xd, []))


@unittest.skipUnless(openpyxl is not None, "未安装 openpyxl，跳过端到端用例")
class EndToEndTests(unittest.TestCase):
    """端到端：真的会写报告、真的会因未落地项非 0 退出。"""

    def _layout(self, root: Path, cn_text: str) -> Path:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "data"
        ws.append(["Debuts", "Base_Ori", "Base_Trans", "Type"])
        ws.append(["正传 创约04", "ミリフォン", "Milliphone", "科技/装备"])
        table = root / "table.xlsx"
        wb.save(table)

        jp = root / "jp" / "[S1_01]日文书" / "item" / "xhtml"
        jp.mkdir(parents=True)
        (jp / "p-001.xhtml").write_text("<p>最新スマホ・ミリフォン15</p>", encoding="utf-8")

        cn = root / "cn" / "[S1_01]中文书" / "OEBPS" / "Text"
        cn.mkdir(parents=True)
        (cn / "S1_01-01_Chapter1.xhtml").write_text(cn_text, encoding="utf-8")
        return table

    def test_missing_reported_and_strict_exit_is_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            table = self._layout(root, "<p>最新型智能手机Miliphone 15</p>")
            out = root / "out"
            rc = main(["--table", str(table), "--jp-dir", str(root / "jp"),
                       "--epub", str(root / "cn"), "--out", str(out), "--strict"])
            self.assertEqual(rc, 1, "存在未落地项时 --strict 必须非 0 退出")
            md = (out / "translation-table-check.md").read_text(encoding="utf-8")
            self.assertIn("ミリフォン", md)
            self.assertIn("Milliphone", md)
            self.assertIn("待判", md)

    def test_landed_passes_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            table = self._layout(root, "<p>最新型智能手机Milliphone 15</p>")
            rc = main(["--table", str(table), "--jp-dir", str(root / "jp"),
                       "--epub", str(root / "cn"), "--out", str(root / "out"), "--strict"])
            self.assertEqual(rc, 0, "译名已落地时不应阻断")

    def test_suspect_excluded_from_strict_by_default(self):
        """疑似子串默认不计入未落地；加 --include-suspect 才纳入。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "data"
            ws.append(["Debuts", "Base_Ori", "Base_Trans", "Type"])
            ws.append(["", "ニック", "尼克", "人名/西式名字"])
            table = root / "table.xlsx"
            wb.save(table)
            jp = root / "jp" / "[S1_01]日文书" / "item" / "xhtml"
            jp.mkdir(parents=True)
            (jp / "p-001.xhtml").write_text("<p>パニックが起きる</p>", encoding="utf-8")
            cn = root / "cn" / "[S1_01]中文书" / "OEBPS" / "Text"
            cn.mkdir(parents=True)
            (cn / "a.xhtml").write_text("<p>发生了恐慌</p>", encoding="utf-8")
            base = ["--table", str(table), "--jp-dir", str(root / "jp"),
                    "--epub", str(root / "cn"), "--out", str(root / "out"), "--strict"]
            self.assertEqual(main(base), 0)
            self.assertEqual(main(base + ["--include-suspect"]), 1)

    def test_book_filter_limits_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            table = self._layout(root, "<p>最新型智能手机Miliphone 15</p>")
            rc = main(["--table", str(table), "--jp-dir", str(root / "jp"),
                       "--epub", str(root / "cn"), "--out", str(root / "out"),
                       "--book", "S9_99"])
            self.assertEqual(rc, 2, "限定到不存在作品时应以参数错误退出")

    def test_audit_x_diff_exit_code(self):
        """`--audit-x-diff`：清单表侧漏填时报错退出，补齐后通过。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "data"
            ws.append(["Debuts", "Base_Ori", "Ruby_Ori", "Base_Trans", "Ruby_Trans", "Type"])
            ws.append(["", "妹達", "シスターズ", "妹妹们", "Sisters", "人名/别名"])
            table = root / "t.xlsx"
            wb.save(table)

            head = ("| 日文锚点 | 表侧写法 | X 版写法 | 类别 | 说明 |\n"
                    "| --- | --- | --- | --- | --- |\n")
            xd = root / "x.md"
            base = ["--table", str(table), "--audit-x-diff", "--x-diff", str(xd),
                    "--out", str(root / "out")]

            xd.write_text(
                head + "| <ruby>妹達<rt>シスターズ</rt></ruby> | — | 妹妹 | 符合语境 | — |\n",
                encoding="utf-8")
            self.assertEqual(main(base), 1, "表侧漏填时应非 0 退出")

            xd.write_text(
                head + "| <ruby>妹達<rt>シスターズ</rt></ruby> | 妹妹们 | 妹妹 | 符合语境 | — |\n",
                encoding="utf-8")
            self.assertEqual(main(base), 0, "补齐表侧后应通过")


if __name__ == "__main__":
    unittest.main()
