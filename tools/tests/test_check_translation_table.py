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
    DEFAULT_RULINGS,
    ToolError,
    audit_rulings,
    book_id,
    collect_books,
    compare,
    fold,
    is_suspect,
    load_table,
    load_rulings,
    main,
    norm_anchor,
    strip_markup,
    to_ruby_text,
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


class StripMarkupEntityTests(unittest.TestCase):
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


class LoadRulingsTests(unittest.TestCase):
    """裁定表门禁：解析 Markdown 表格（锚点列反引号、裁定列 `／` 多写法、判定列 `人读`）。

    `docs/translation-name-rulings.md` 登记的是已决口径（含与灰机 Wiki 译名表的人为固有
    差异）。工具必须先过这道门禁，否则会把裁定写法报成术语未落地。
    """

    SAMPLE = "\n".join([
        "# 标题",
        "",
        "| 日文锚点 | 裁定 | 被否决或并存的候选 | 理由 | 判定 |",
        "| --- | --- | --- | --- | --- |",
        "| `妹達` | 妹妹 | 妹妹们 | 符合语境 | |",
        "| `ハイウェイクレイドル` | 高速摇篮号 | Highway Cradle | 原创词 | |",
        "| `投擲の槌` | 投掷之锤／雷神之锤 | Mjölnir | 中文注音 | |",
        "| `機能` | 设备类→功能；生物类→机能 | — | 按指代分层 | 人读 |",
    ])

    def _write(self, tmp: str, text: str) -> Path:
        p = Path(tmp) / "r.md"
        p.write_text(text, encoding="utf-8")
        return p

    def test_parses_rows_and_skips_header_and_separator(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = load_rulings(self._write(tmp, self.SAMPLE))
            self.assertEqual(len(d), 4)                     # 表头与分隔行不计入
            self.assertNotIn("日文锚点", d)
            self.assertEqual(d["妹達"]["forms"], ["妹妹"])
            self.assertFalse(d["妹達"]["human_only"])
            self.assertTrue(d[norm_anchor("機能")]["human_only"])
            self.assertEqual(d[norm_anchor("投擲の槌")]["forms"], ["投掷之锤", "雷神之锤"])
            # 键是折叠后的形式（§5.3）：ハイウェイ… 的 ウェ 折叠为 ウエ
            self.assertEqual(d[norm_anchor("ハイウェイクレイドル")]["forms"], ["高速摇篮号"])

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_rulings(Path("不存在的裁定表.md")), {})

    HEADER = "| 日文锚点 | 裁定 | 被否决或并存的候选 | 理由 | 判定 |\n| --- | --- | --- | --- | --- |\n"

    def test_anchor_is_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = load_rulings(self._write(
                tmp, self.HEADER + "| `【実践魔女】` | 里 | 表 | 类别 | |\n"))
            self.assertIn("実践魔女", d)

    def test_multiple_backticks_are_all_anchors(self):
        """锚点列一行多个反引号内容都算锚点（§12 格式约定）。"""
        with tempfile.TemporaryDirectory() as tmp:
            d = load_rulings(self._write(
                tmp, self.HEADER + "| `魔術`／`魔術師`（术语层） | 魔法／魔法师 | 魔术 | 分层 | |\n"))
            self.assertIn("魔術", d)
            self.assertIn("魔術師", d)

    def test_same_anchor_rows_merge_forms(self):
        """同一锚点多条登记合并为候选集合（分层与同词异译）。"""
        with tempfile.TemporaryDirectory() as tmp:
            d = load_rulings(self._write(tmp, self.HEADER + "\n".join([
                "| `スフィア`（装备） | 天体仪 | — | 装备义 | |",
                "| `スフィア`（组织） | 天体 | — | 组织义 | |"])))
            self.assertEqual(sorted(d[norm_anchor("スフィア")]["forms"]), ["天体", "天体仪"])

    RUBY_SAMPLE = "\n".join([
        "| 日文锚点 | 裁定 | 被否决或并存的候选 | 理由 | 判定 |",
        "| --- | --- | --- | --- | --- |",
        "| `<ruby>主神の槍<rt>グングニル</rt></ruby>` | `<ruby>主神之枪<rt>冈格尼尔</rt></ruby>` "
        "| 表侧「<ruby>主神之枪<rt>Gungnir</rt></ruby>」 | 中文注音：仅注音不同 | |",
    ])

    def test_ruby_readings_are_stripped_from_forms(self):
        """裁定列里的注音用 `<ruby>` 呈现，解析只取基文（注音不参与匹配）。"""
        with tempfile.TemporaryDirectory() as tmp:
            d = load_rulings(self._write(tmp, self.RUBY_SAMPLE))
            self.assertIn("主神の槍", d)
            self.assertEqual(d["主神の槍"]["forms"], ["主神之枪"])
            self.assertNotIn("<ruby>", d["主神の槍"]["forms"][0])
            self.assertNotIn("冈格尼尔", d["主神の槍"]["forms"][0])   # 注音不进匹配值

    def test_ruby_form_matches_plain_cn_text(self):
        """裁定写法带 ruby、成品文本已剥注音 —— 仍应判定落地。"""
        with tempfile.TemporaryDirectory() as tmp:
            rd = load_rulings(self._write(tmp, self.RUBY_SAMPLE))
            recs, _s, _sh = compare(
                [{"ori": "主神の槍", "trans": "主神之枪", "type": "", "debuts": ""}],
                {"S1_01": "主神の槍"},
                {"S1_01": "主神之枪"},          # 成品侧同样已剥注音
                rd)
            self.assertEqual(recs[0]["status"], "landed")
            self.assertEqual(recs[0]["form_kind"], "ruling")

    def test_repo_gate_file_is_present_and_parsable(self):
        """仓库内的门禁文件必须存在、可解析，且覆盖已知条目。"""
        self.assertTrue(DEFAULT_RULINGS.is_file(), f"门禁文件缺失：{DEFAULT_RULINGS}")
        d = load_rulings(DEFAULT_RULINGS)
        self.assertGreater(len(d), 20, "裁定表条目数异常偏少")
        for anchor in ("妹達", "ハイウェイクレイドル", "保温鍋バンマリ", "主神の槍",
                       "クロウリーズ・ハザード"):
            self.assertIn(norm_anchor(anchor), d, f"裁定表缺少已知条目：{anchor}")

    def test_repo_gate_values_carry_no_ruby_markup(self):
        """仓库裁定表解析出的写法必须是干净基文（注音已剥），否则匹配会失败。"""
        d = load_rulings(DEFAULT_RULINGS)
        self.assertEqual(d[norm_anchor("主神の槍")]["forms"], ["主神之枪"])
        for key, val in d.items():
            for form in val["forms"]:
                self.assertNotIn("<ruby>", form, f"{key} 残留 ruby 标记")
                self.assertNotIn("<rt>", form, f"{key} 残留 rt 标记")


class CompareWithRulingsTests(unittest.TestCase):
    """门禁生效后的判定分支（每个分支一个反例）。"""

    RD = {"妹達": {"forms": ["妹妹"], "raw": ["妹妹"], "labels": [""],
                   "ori_raw": ["妹達"], "human_only": False}}

    @staticmethod
    def entry(ori: str, trans: str) -> dict[str, str]:
        return {"ori": ori, "trans": trans, "type": "", "debuts": ""}

    def test_ruling_form_lands(self):
        """成品用裁定写法 → 落地（不过门禁就会被误报未落地）。"""
        recs, _s, _sh = compare(
            [self.entry("妹達", "妹妹们")],
            {"S1_01": "妹達は"},
            {"S1_01": "妹妹"},
            self.RD)
        self.assertEqual(recs[0]["status"], "landed")
        self.assertEqual(recs[0]["rulings"], "1")
        self.assertEqual(recs[0]["form_kind"], "ruling")

    def test_longer_form_wins_when_both_present(self):
        """多种裁定写法同时出现时取更长者（长写法优先）。"""
        rd = {"投擲の槌": {"forms": ["投掷之锤", "雷神之锤"], "raw": [], "labels": [""],
                           "ori_raw": ["投擲の槌"], "human_only": False}}
        recs, _s, _sh = compare(
            [self.entry("投擲の槌", "投掷之锤")],
            {"S1_01": "投擲の槌"},
            {"S1_01": "雷神之锤"},
            rd)
        self.assertEqual(recs[0]["status"], "landed")
        self.assertEqual(recs[0]["form_kind"], "ruling")

    def test_table_form_no_longer_lands(self):
        """退回表侧写法 → 不再算落地（并存已取消，与旧行为相反的反例）。"""
        rd = {"妹達": {"forms": ["妹妹们"], "raw": [], "labels": [""],
                       "ori_raw": ["妹達"], "human_only": False}}
        recs, _s, _sh = compare(
            [self.entry("妹達", "妹妹们")],
            {"S1_01": "妹達は"},
            {"S1_01": "妹妹"},
            rd)
        self.assertEqual(recs[0]["status"], "missing")

    def test_neither_form_reports_missing(self):
        """裁定写法没有 → 报未落地（负向自检）。"""
        recs, _s, _sh = compare(
            [self.entry("妹達", "妹妹们")],
            {"S1_01": "妹達は"},
            {"S1_01": "姐妹们"},
            self.RD)
        self.assertEqual(recs[0]["status"], "missing")
        self.assertEqual(recs[0]["form_kind"], "")

    def test_without_gate_the_same_line_is_reported(self):
        """不传门禁时同一行会被报未落地——反证门禁确实在起作用。"""
        recs, _s, _sh = compare(
            [self.entry("妹達", "妹妹们")],
            {"S1_01": "妹達は"},
            {"S1_01": "妹妹"})
        self.assertEqual(recs[0]["status"], "missing")

    def test_human_only_is_skipped(self):
        """判定列标 `人读` 的条目：工具不判定，记 human_only。"""
        rd = {"妹達": {"forms": ["妹妹"], "raw": ["带数量修饰→妹妹；其余→妹妹们"],
                       "labels": [""], "ori_raw": ["妹達"], "human_only": True}}
        recs, _s, _sh = compare(
            [self.entry("妹達", "妹妹们")],
            {"S1_01": "妹達は"},
            {"S1_01": "姐妹们"},
            rd)
        self.assertEqual(recs[0]["status"], "human_only")



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


class AuditRulingsTests(unittest.TestCase):
    """裁定表 ↔ 译名表一致性核对（`--audit-rulings`）：每个问题类型一个反例。"""

    @staticmethod
    def entry(ori: str, trans: str, ruby_ori: str = "", ruby_trans: str = "") -> dict[str, str]:
        return {"ori": ori, "trans": trans, "type": "", "debuts": "",
                "ruby_ori": ruby_ori, "ruby_trans": ruby_trans}

    @staticmethod
    def rd(ori_raw: str, forms: list[str] | None = None, human_only: bool = False):
        """构造与 `load_rulings` 同形的条目。"""
        def cell(v: str) -> str:
            v = (v or "").strip()
            return "" if v in ("—", "-", "") else strip_markup(v).strip()

        return {norm_anchor(strip_markup(ori_raw)): {
            "forms": [f for f in (cell(x) for x in (forms or [])) if f],
            "raw": [], "labels": [""], "ori_raw": [ori_raw], "human_only": human_only}}

    def kinds(self, rulings, entries):
        return {p["kind"] for p in audit_rulings(rulings, entries)}

    def test_clean_sample_reports_nothing(self):
        rd = self.rd("<ruby>妹達<rt>シスターズ</rt></ruby>", ["妹妹"])
        e = self.entry("妹達", "妹妹们", "シスターズ", "Sisters")
        self.assertEqual(audit_rulings(rd, [e]), [])

    def test_forms_empty_detected(self):
        """负向自检：裁定列解析不出写法（散文格式漏标 `人读`）→ forms-empty。"""
        rd = self.rd("妹達", ["—"])
        self.assertIn("forms-empty", self.kinds(rd, [self.entry("妹達", "妹妹们")]))

    def test_human_only_exempts_forms_empty(self):
        """标了 `人读` 的条目即使解析不出写法也不算问题。"""
        rd = self.rd("機能", [], human_only=True)
        self.assertEqual(self.kinds(rd, []), set())

    def test_ruby_ori_mismatch_detected(self):
        """负向自检：锚点 <rt> 照抄了源的大字形式 → ruby-mismatch。"""
        rd = self.rd("<ruby>投擲の槌<rt>ミヨルニル</rt></ruby>", ["投掷之锤"])
        e = self.entry("投擲の槌", "投掷之锤", "ミョルニル")
        self.assertIn("ruby-mismatch", self.kinds(rd, [e]))

    def test_anchor_fullwidth_detected(self):
        """负向自检：锚点写全角英数字母 → anchor-fullwidth。"""
        rd = self.rd("ＡからＦ班", ["〜小队"])
        e = self.entry("AからF班", "〜小队")
        self.assertIn("anchor-fullwidth", self.kinds(rd, [e]))

    def test_fullwidth_exempts_japanese_punct(self):
        """日文原文的全角标点（？、（））不算违规——只查全角英数字母。"""
        rd1 = self.rd("汝の欲する所を為せ、それが汝の法とならん", ["为汝所欲为，即为汝之法"])
        rd2 = self.rd("とうま、これからどうするの？", ["当麻，接下来怎么办？"])
        self.assertNotIn("anchor-fullwidth", self.kinds(rd1, []))
        self.assertNotIn("anchor-fullwidth", self.kinds(rd2, []))



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

    def test_audit_rulings_exit_code(self):
        """`--audit-rulings`：裁定列解析不出写法时报错退出，补上写法后通过。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "data"
            ws.append(["Debuts", "Base_Ori", "Ruby_Ori", "Base_Trans", "Ruby_Trans", "Type"])
            ws.append(["", "妹達", "シスターズ", "妹妹们", "Sisters", "人名/别名"])
            table = root / "t.xlsx"
            wb.save(table)

            head = ("| 日文锚点 | 裁定 | 被否决或并存的候选 | 理由 | 判定 |\n"
                    "| --- | --- | --- | --- | --- |\n")
            rd = root / "r.md"
            base = ["--table", str(table), "--audit-rulings", "--rulings", str(rd),
                    "--out", str(root / "out")]

            # 裁定列为空占位（散文格式漏标 `人读`）→ forms-empty，非 0 退出
            rd.write_text(
                head + "| `<ruby>妹達<rt>シスターズ</rt></ruby>` | — | — | 符合语境 | |\n",
                encoding="utf-8")
            self.assertEqual(main(base), 1, "裁定列解析不出写法时应非 0 退出")

            # 补上写法（或改标 `人读`）后通过
            rd.write_text(
                head + "| `<ruby>妹達<rt>シスターズ</rt></ruby>` | 妹妹 | 妹妹们 | 符合语境 | |\n",
                encoding="utf-8")
            self.assertEqual(main(base), 0, "补上写法后应通过")


class RubyTextTests(unittest.TestCase):
    """注音复合串：`<ruby>基文<rt>注文</rt></ruby>` → `基文（注文）`。"""

    def test_pair_becomes_composite(self):
        self.assertEqual(to_ruby_text("<p><ruby>主神之枪<rt>冈格尼尔</rt></ruby></p>"),
                         "主神之枪（冈格尼尔）")

    def test_ruby_without_rt_stays_base(self):
        self.assertEqual(to_ruby_text("<p><ruby>主神之枪</ruby></p>"), "主神之枪")

    def test_multi_segment_ruby_expands_per_segment(self):
        self.assertEqual(to_ruby_text("<ruby>封<rt>ド</rt></ruby><ruby>の<rt>ロ</rt></ruby>"),
                         "封（ド）の（ロ）")


class RubyJudgementTests(unittest.TestCase):
    """注音判定：日文侧带注音时，中文侧必须出现裁定的复合串。"""

    ENTRY = [{"ori": "主神の槍", "trans": "主神之枪", "type": "", "debuts": ""}]
    RD = {"主神の槍": {"forms": ["主神之枪"], "ruby_forms": ["主神之枪（冈格尼尔）"],
                       "raw": [], "alt_raw": [], "labels": [""], "ori_raw": ["主神の槍"],
                       "human_only": False}}

    def test_correct_ruby_lands(self):
        recs, _s, _sh = compare(self.ENTRY, {"S1_01": "主神の槍"}, {"S1_01": "主神之枪"}, self.RD,
                                None, None, {"S1_01": "主神の槍（グングニル）"},
                                {"S1_01": "主神之枪（冈格尼尔）"})
        self.assertEqual(recs[0]["status"], "landed")

    def test_wrong_ruby_reports_missing(self):
        """成品注音写成表侧的 Gungnir → 报未落地（剥注音的判定看不出来）。"""
        recs, _s, _sh = compare(self.ENTRY, {"S1_01": "主神の槍"}, {"S1_01": "主神之枪"}, self.RD,
                                None, None, {"S1_01": "主神の槍（グングニル）"},
                                {"S1_01": "主神之枪（Gungnir）"})
        self.assertEqual(recs[0]["status"], "missing")

    def test_no_jp_ruby_skips_judgement(self):
        """日文侧本来就裸写时不做注音判定（否则中文裸写会被误报）。"""
        recs, _s, _sh = compare(self.ENTRY, {"S1_01": "主神の槍"}, {"S1_01": "主神之枪"}, self.RD,
                                None, None, {"S1_01": "主神の槍"}, {"S1_01": "主神之枪"})
        self.assertEqual(recs[0]["status"], "landed")


class NewAuditChecksTests(unittest.TestCase):
    """候选列依据与同词异译登记两项检查。"""

    @staticmethod
    def entry(ori, trans):
        return {"ori": ori, "trans": trans, "type": "", "debuts": "",
                "ruby_ori": "", "ruby_trans": ""}

    def kinds(self, rulings, entries):
        return {p["kind"] for p in audit_rulings(rulings, entries)}

    def test_alt_unfounded_reported(self):
        """候选列标成「表内原值」但译名表里没有该写法 → 报。"""
        rd = {"甲": {"forms": ["乙"], "ruby_forms": [], "raw": ["乙"], "alt_raw": ["丙（表内原值）"],
                     "labels": [""], "ori_raw": ["甲"], "human_only": False}}
        self.assertIn("alt-unfounded", self.kinds(rd, [self.entry("甲", "丁")]))

    def test_alt_with_real_table_value_passes(self):
        rd = {"甲": {"forms": ["乙"], "ruby_forms": [], "raw": ["乙"], "alt_raw": ["丁（译名表当前值）"],
                     "labels": [""], "ori_raw": ["甲"], "human_only": False}}
        self.assertNotIn("alt-unfounded", self.kinds(rd, [self.entry("甲", "丁")]))

    def test_alt_without_source_claim_is_not_checked(self):
        """候选列没声称来源（普通被否决候选，如「势力」）→ 不检查。"""
        rd = {"甲": {"forms": ["乙"], "ruby_forms": [], "raw": ["乙"], "alt_raw": ["势力"],
                     "labels": [""], "ori_raw": ["甲"], "human_only": False}}
        self.assertEqual(self.kinds(rd, [self.entry("甲", "丁")]), set())

    def test_homonym_unregistered_reported(self):
        entries = [self.entry("甲", "乙"), self.entry("甲", "丙")]
        self.assertIn("homonym-unregistered", self.kinds({}, entries))

    def test_homonym_registered_passes(self):
        entries = [self.entry("甲", "乙"), self.entry("甲", "丙")]
        rd = {"甲": {"forms": ["乙"], "ruby_forms": [], "raw": [], "alt_raw": [], "labels": [""],
                     "ori_raw": ["甲"], "human_only": False}}
        self.assertNotIn("homonym-unregistered", self.kinds(rd, entries))


class SettledScopeTests(unittest.TestCase):
    """同形例外按作品登记：抑制只在该作品内生效，裁定表登记后失效。"""

    ENTRY = [{"ori": "テスト", "trans": "译文", "type": "", "debuts": ""}]
    SETTLED = {"テスト": {"note": "表内专名、正文普通词", "scope": "S1_01", "status": "settled"}}

    def test_suppressed_in_scope(self):
        recs, _s, _sh = compare(self.ENTRY, {"S1_01": "テスト"}, {"S1_01": "无关内容"},
                                None, None, self.SETTLED)
        self.assertEqual(recs[0]["status"], "settled")

    def test_not_suppressed_out_of_scope(self):
        """别的书里命中同一锚点 → 不抑制，照常判定。"""
        recs, _s, _sh = compare(self.ENTRY, {"S2_02": "テスト"}, {"S2_02": "无关内容"},
                                None, None, self.SETTLED)
        self.assertEqual(recs[0]["status"], "missing")

    def test_settled_survives_ruling_registration(self):
        """已判定为同形不同义的条目：裁定表登记的是**表内那个义项**，抑制继续生效。"""
        rd = {"テスト": {"forms": ["译文"], "ruby_forms": [], "raw": [], "alt_raw": [], "labels": [""],
                         "ori_raw": ["テスト"], "human_only": False}}
        recs, _s, _sh = compare(self.ENTRY, {"S1_01": "テスト"}, {"S1_01": "译文"}, rd, None, self.SETTLED)
        self.assertEqual(recs[0]["status"], "settled")

    def test_pending_ruling_overridden_by_ruling(self):
        """`待裁定` 的条目：裁定表一旦登记该锚点，抑制失效、改按裁定判定。"""
        settled = {"テスト": {"note": "两案都成立", "scope": "S1_01", "status": "待裁定"}}
        rd = {"テスト": {"forms": ["译文"], "ruby_forms": [], "raw": [], "alt_raw": [], "labels": [""],
                         "ori_raw": ["テスト"], "human_only": False}}
        recs, _s, _sh = compare(self.ENTRY, {"S1_01": "テスト"}, {"S1_01": "译文"}, rd, None, settled)
        self.assertEqual(recs[0]["status"], "landed")

    def test_pending_ruling_status(self):
        settled = {"テスト": {"note": "两案都成立", "scope": "S1_01", "status": "待裁定"}}
        recs, _s, _sh = compare(self.ENTRY, {"S1_01": "テスト"}, {"S1_01": "无关内容"},
                                None, None, settled)
        self.assertEqual(recs[0]["status"], "pending_ruling")


if __name__ == "__main__":
    unittest.main()
