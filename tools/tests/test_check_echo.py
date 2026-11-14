from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from check_echo import (  # noqa: E402
    _longest_common_span,
    convention_stats,
    default_prior_works,
    find_book_dir,
    frag_groups,
    grams,
    iter_works,
    load_pairs,
    main as echo_main,
    norm_cn,
    norm_jp,
    pattern_echo_pairs,
    quote_lookups,
    render,
    render_convention,
    short_parallel_pairs,
    sim_pairs,
    term_groups,
)

CN_PROLOGUE = """<p>「那么，你愿意跟我一起走到地狱之底吗？」</p>
<p>无关行。</p>
<p>『那么，你愿意陪我一起走到地狱之底吗？』</p>
<p>无关行。</p>
<p>『即使我下地狱，你也愿意陪着我？』</p>
"""

JP_PROLOGUE = """<p>「……、じゃあ。私と一緒に地獄の底までついてきてくれる？」</p>
<p>どうでもいい行。</p>
<p>『……、じゃあ。私と一緒に地獄の底までついてきてくれる？』</p>
<p>どうでもいい行。</p>
<p>『……、じゃあ。私と一緒に地獄の底までついてきてくれる？』</p>
"""


def build_fixture(root: Path, work: str = "S1_01") -> tuple[Path, Path]:
    cn_book = root / "EPUB" / f"【{work}】测试书"
    (cn_book / "OEBPS" / "Text").mkdir(parents=True)
    (cn_book / "OEBPS" / "Text" / f"{work}-01_Prologue.xhtml").write_text(CN_PROLOGUE, encoding="utf-8")
    jp_book = root / "jp" / f"【{work}】テスト本"
    (jp_book / "item" / "xhtml").mkdir(parents=True)
    (jp_book / "item" / "xhtml" / f"{work}-01.xhtml").write_text(JP_PROLOGUE, encoding="utf-8")
    return cn_book.parent, root / "jp"


def _wrap(cn_texts: list[str], jp_text: str = "『私と一緒に地獄の底までついてきてくれる？』") -> list[dict]:
    """把一组中文造成为「同一日文片段」的行记录（供差异分类测试）。"""
    return [
        {"file": "a.xhtml", "line": i + 1, "cn": cn, "jp": jp_text}
        for i, cn in enumerate(cn_texts)
    ]


class NormaliseTests(unittest.TestCase):
    def test_norm_jp_keeps_kana_and_kanji_only(self):
        self.assertEqual(norm_jp("「……、じゃあ。私と一緒に」"), "じゃあ私と一緒に")

    def test_norm_cn_keeps_han_and_alnum(self):
        self.assertEqual(norm_cn("『那么，你愿意陪我一起走到地狱之底吗？』"), "那么你愿意陪我一起走到地狱之底吗")

    def test_grams_short_text(self):
        # 短于 n 时返回自身，不产生空集
        self.assertEqual(grams("abc", 4), {"abc"})
        self.assertEqual(grams("", 4), set())


class FindBookDirTests(unittest.TestCase):
    def test_accepts_fullwidth_and_legacy_halfwidth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "【S1_01】新形态").mkdir()
            (root / "[S1_02]旧形态").mkdir()
            self.assertEqual(find_book_dir(root, "S1_01").name, "【S1_01】新形态")
            self.assertEqual(find_book_dir(root, "S1_02").name, "[S1_02]旧形态")
            self.assertIsNone(find_book_dir(root, "S1_03"))

    def test_missing_root(self):
        self.assertIsNone(find_book_dir(Path("no-such-root"), "S1_01"))

    def test_duplicate_work_is_not_resolved_to_an_arbitrary_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "【S1_01】版本甲").mkdir()
            (root / "【S1_01】版本乙").mkdir()
            with self.assertRaisesRegex(ValueError, "重复作品号"):
                find_book_dir(root, "S1_01")


class LoadPairsTests(unittest.TestCase):
    def test_pairs_by_content_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = build_fixture(Path(tmp))
            rows, notes = load_pairs("S1_01", cn_root, jp_root)
            self.assertEqual(notes, [])
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[0]["seq"], "S1_01-01")
            self.assertIn("地狱之底", rows[0]["cn"])
            self.assertIn("地獄の底", rows[0]["jp"])

    def test_reports_missing_counterpart(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = build_fixture(Path(tmp))
            (jp_root / "【S1_01】テスト本" / "item" / "xhtml" / "S1_01-01.xhtml").unlink()
            rows, notes = load_pairs("S1_01", cn_root, jp_root)
            self.assertEqual(rows, [])
            self.assertTrue(any("缺日文对照" in n for n in notes))

    def test_reports_line_count_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = build_fixture(Path(tmp))
            target = jp_root / "【S1_01】テスト本" / "item" / "xhtml" / "S1_01-01.xhtml"
            target.write_text(JP_PROLOGUE + "<p>多余行。</p>\n", encoding="utf-8")
            rows, notes = load_pairs("S1_01", cn_root, jp_root)
            self.assertEqual(rows, [])
            self.assertTrue(any("行数不等" in n for n in notes))

    def test_skips_non_pair_work_even_with_matching_line_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = build_fixture(Path(tmp), "S5_02_03")
            rows, notes = load_pairs("S5_02_03", cn_root, jp_root)
            self.assertEqual(rows, [])
            self.assertTrue(any("非同一形态" in n for n in notes))

    def test_skips_registered_pair_exceptions_and_packaging(self):
        cases = [
            ("S2_14", "02", "文本化图片"),
            ("S5_01_03", "06", "afterword-moved"),
            ("S5_01_02", "09", "section-order"),
            ("S1_25", "Stiyl_Magnus", "人工对齐"),
        ]
        for work, suffix, reason in cases:
            with self.subTest(work=work, suffix=suffix), tempfile.TemporaryDirectory() as tmp:
                cn_root, jp_root = build_fixture(Path(tmp), work)
                cn_dir = cn_root / f"【{work}】测试书" / "OEBPS" / "Text"
                jp_dir = jp_root / f"【{work}】テスト本" / "item" / "xhtml"
                (cn_dir / f"{work}-01_Prologue.xhtml").rename(cn_dir / f"{work}-88_Chapter.xhtml")
                (jp_dir / f"{work}-01.xhtml").rename(jp_dir / f"{work}-88.xhtml")
                for name in (f"{work}-{suffix}.xhtml", f"{work}-Cover.xhtml"):
                    (cn_dir / name).write_text(CN_PROLOGUE, encoding="utf-8")
                    (jp_dir / name).write_text(JP_PROLOGUE, encoding="utf-8")
                rows, notes = load_pairs(work, cn_root, jp_root)
                self.assertEqual({row["seq"] for row in rows}, {f"{work}-88"})
                self.assertTrue(any(reason in n for n in notes), notes)

    def test_pairs_named_headers_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = "S1_25"
            cn_root, jp_root = build_fixture(Path(tmp), work)
            cn_dir = cn_root / f"【{work}】测试书" / "OEBPS" / "Text"
            jp_dir = jp_root / f"【{work}】テスト本" / "item" / "xhtml"
            (cn_dir / f"{work}-uiharu_kazari.xhtml").write_text(CN_PROLOGUE, encoding="utf-8")
            (jp_dir / f"{work}-Uiharu_Kazari.xhtml").write_text(JP_PROLOGUE, encoding="utf-8")
            rows, notes = load_pairs(work, cn_root, jp_root)
            self.assertEqual(notes, [])
            self.assertEqual({row["seq"] for row in rows}, {f"{work}-01", f"{work}-UIHARU_KAZARI"})

    def test_rejects_duplicate_headers_instead_of_selecting_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = build_fixture(Path(tmp))
            cn_dir = cn_root / "【S1_01】测试书" / "OEBPS" / "Text"
            (cn_dir / "S1_01-01_Duplicate.xhtml").write_text(CN_PROLOGUE, encoding="utf-8")
            rows, notes = load_pairs("S1_01", cn_root, jp_root)
            self.assertEqual(rows, [])
            self.assertTrue(any("重复表头" in n for n in notes))

    def test_rejects_equal_length_with_different_line_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = build_fixture(Path(tmp))
            target = jp_root / "【S1_01】テスト本" / "item" / "xhtml" / "S1_01-01.xhtml"
            target.write_text(JP_PROLOGUE.replace("<p>どうでもいい行。</p>", "<br/>", 1), encoding="utf-8")
            rows, notes = load_pairs("S1_01", cn_root, jp_root)
            self.assertEqual(rows, [])
            self.assertTrue(any("行类型错位" in n for n in notes))

    def test_skips_metadata_lines(self):
        # head 区的 title／meta／link 与 XML 声明不参与配对：各文件这些行往往同号，
        # 不过滤会在「同源复现」里造出假对（实测 S6_24.06.07 因此多报 66 对）。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cn_dir = root / "EPUB" / "【S1_01】测试书" / "OEBPS" / "Text"
            cn_dir.mkdir(parents=True)
            (cn_dir / "S1_01-01_Prologue.xhtml").write_text(
                "<?xml version='1.0' encoding='utf-8'?>\n"
                "<title>测试书</title>\n"
                "<p>正文一行。</p>\n", encoding="utf-8")
            jp_dir = root / "jp" / "【S1_01】テスト本" / "item" / "xhtml"
            jp_dir.mkdir(parents=True)
            (jp_dir / "S1_01-01.xhtml").write_text(
                "<?xml version='1.0' encoding='utf-8'?>\n"
                "<title>テスト本</title>\n"
                "<p>本文一行。</p>\n", encoding="utf-8")
            rows, _ = load_pairs("S1_01", cn_dir.parent.parent.parent, root / "jp")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["line"], 3)


class FragGroupTests(unittest.TestCase):
    def test_flags_same_jp_with_divergent_chinese(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = build_fixture(Path(tmp))
            rows, _ = load_pairs("S1_01", cn_root, jp_root)
            groups = frag_groups(rows, min_len=12)
            self.assertEqual(len(groups), 1)
            frag, items, klass = groups[0]
            self.assertIn("地獄の底", frag)
            self.assertEqual({r["line"] for r in items}, {1, 3, 5})
            # 「即使我下地狱，你也愿意陪着我？」与另两处实词不同 → 实词级
            self.assertEqual(klass, "实词")

    def test_classifies_function_word_only_difference(self):
        # 「陪我一起」↔「跟我一起」只差虚词：差异性质应为虚词级
        rows = _wrap([
            "「……那么，你愿意陪我一起走到地狱之底吗？」",
            "「……那么，你愿意跟我一起走到地狱之底吗？」",
        ])
        self.assertEqual(frag_groups(rows, min_len=8)[0][2], "虚词")

    def test_classifies_style_word_difference(self):
        # 「女孩」↔「少女」是译体词差异，须提示回核语气层
        rows = _wrap([
            "「他要去救那个女孩。」",
            "「他要去救那个少女。」",
        ], jp_text="「女の子を助けよう」")
        self.assertEqual(frag_groups(rows, min_len=8)[0][2], "语体")

    def test_ignores_uniform_chinese(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = build_fixture(Path(tmp))
            book = cn_root / "【S1_01】测试书" / "OEBPS" / "Text" / "S1_01-01_Prologue.xhtml"
            uniform = CN_PROLOGUE.replace("陪我一起", "跟我一起").replace(
                "『即使我下地狱，你也愿意陪着我？』", "『那么，你愿意跟我一起走到地狱之底吗？』"
            )
            book.write_text(uniform, encoding="utf-8")
            rows, _ = load_pairs("S1_01", cn_root, jp_root)
            self.assertEqual(frag_groups(rows, min_len=12), [])


class SimPairTests(unittest.TestCase):
    def test_preserves_sparse_sampled_pair_when_full_gram_is_frequent(self):
        source = "明日は図書館へ行って新しい本を探す予定ですが君も一緒に来ませんか"
        rows = [
            {"file": "a.xhtml", "line": 1, "jp": source, "cn": "去图书馆找书。"},
            {"file": "b.xhtml", "line": 1, "jp": source, "cn": "去书店买书。"},
        ]
        rows += [
            {"file": f"noise-{i}.xhtml", "line": 1, "jp": "ね" + source, "cn": "重复句。"}
            for i in range(41)
        ]
        pairs = sim_pairs(rows, n=8, threshold=0.9)
        self.assertEqual(len(pairs), 1)
        self.assertEqual({pairs[0][0]["file"], pairs[0][1]["file"]}, {"a.xhtml", "b.xhtml"})

    def test_recalls_insertions_and_deletions_across_ngram_offsets(self):
        source = "明日は図書館へ行って新しい本を探す予定ですが君も一緒に来ませんか"
        for offset in (0, 2, 9):
            for inserted in ("ね", "ねえ", "ねえね"):
                shifted = source[:offset] + inserted + source[offset:]
                for left, right in ((source, shifted), (shifted, source)):
                    with self.subTest(offset=offset, inserted=inserted, left=left):
                        rows = [
                            {"file": "a.xhtml", "line": 1, "jp": left, "cn": "去图书馆找书。"},
                            {"file": "b.xhtml", "line": 1, "jp": right, "cn": "去书店买书。"},
                        ]
                        pairs = sim_pairs(rows, n=8, threshold=0.9)
                        self.assertEqual(len(pairs), 1)
                        self.assertGreater(pairs[0][2], 0.9)

    def test_finds_near_identical_jp(self):
        rows = [
            {"file": "a.xhtml", "line": 1,
             "jp": "『……、じゃあ。私と一緒に地獄の底までついてきてくれる？』",
             "cn": "『……那么，你愿意陪我一起走到地狱之底吗？』"},
            {"file": "a.xhtml", "line": 2,
             "jp": "「……、じゃあ。私と一緒に地獄の底までついてきてくれる？」",
             "cn": "「……那么，你愿意跟我一起走到地狱之底吗？」"},
            {"file": "a.xhtml", "line": 3, "jp": "全く別の文章がここにあります。", "cn": "完全不同的句子。"},
        ]
        pairs = sim_pairs(rows, n=8, threshold=0.5)
        self.assertEqual(len(pairs), 1)
        self.assertGreater(pairs[0][2], 0.9)


class ShortParallelTests(unittest.TestCase):
    def _pair(self, right_cn: str = "与仅有三人的「格雷姆林」，") -> list[dict]:
        return [
            {"file": "a.xhtml", "line": 6,
             "jp": "たった三人の『木原』と。", "cn": "仅有三名「木原」。"},
            {"file": "a.xhtml", "line": 7,
             "jp": "たった三人の『グレムリン』。", "cn": right_cn},
        ]

    def test_flags_measure_word_parallel(self):
        # 类 1 要求日文片段相同、类 2 只收 ≥20 字；这类 9/11 字的短平行句
        # 是两类的长度盲区（S2_04-01 L6/L7 的真实断裂形态）。
        pairs = short_parallel_pairs(self._pair())
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["kind"], "量词")
        self.assertEqual((pairs[0]["left"]["line"], pairs[0]["right"]["line"]), (6, 7))

    def test_measure_word_signal_disappears_after_sync(self):
        # 两侧都改成「三名」后仍会作为短平行句候选（中文内容不同），
        # 但不应再被标成量词差异——工具只报候选，不自动判定。
        pairs = short_parallel_pairs(self._pair("与仅有三名「格雷姆林」，"))
        self.assertEqual(len(pairs), 1)
        self.assertNotEqual(pairs[0]["kind"], "量词")

    def test_ignores_identical_chinese(self):
        pairs = short_parallel_pairs(self._pair("仅有三名「木原」。"))
        self.assertEqual(pairs, [])

    def test_ignores_long_vowel_and_long_lines(self):
        # 长音／重复假名串（惨叫、拟声）与类 2 一样不参与，避免拟声互配。
        rows = [
            {"file": "a.xhtml", "line": 1, "jp": "あああああああ", "cn": "啊啊啊啊——"},
            {"file": "a.xhtml", "line": 2, "jp": "ああああああああ", "cn": "啊啊啊啊啊——"},
        ]
        self.assertEqual(short_parallel_pairs(rows), [])
        long_jp = "あ" * 30
        rows = [
            {"file": "a.xhtml", "line": 1, "jp": long_jp + "。", "cn": "很长的句子甲。"},
            {"file": "a.xhtml", "line": 2, "jp": long_jp + "と。", "cn": "很长的句子乙。"},
        ]
        self.assertEqual(short_parallel_pairs(rows), [])

    def test_respects_window(self):
        rows = self._pair()
        rows.insert(1, {"file": "a.xhtml", "line": 7, "jp": "どうでもいい行。",
                        "cn": "无关行。"})
        rows[2]["line"] = 8
        self.assertEqual(short_parallel_pairs(rows, window=1), [])
        self.assertEqual(len(short_parallel_pairs(rows, window=2)), 1)

    def test_classifies_function_word_difference(self):
        rows = [
            {"file": "a.xhtml", "line": 1,
             "jp": "そういう事は言わない。", "cn": "那种事不会说。"},
            {"file": "a.xhtml", "line": 2,
             "jp": "そういう事は言わないのか。", "cn": "那种事不会说吗？"},
        ]
        pairs = short_parallel_pairs(rows)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["kind"], "功能词")

    def test_render_includes_short_parallel_section(self):
        rows = self._pair()
        report = {"frag": [], "pairs": [], "short": short_parallel_pairs(rows), "quotes": []}
        text, summary = render("S1_01", rows, report)
        self.assertIn("## 类 4 短平行句（1 对）", text)
        self.assertIn("短平行句 1 对", summary)


class LongestCommonSpanTests(unittest.TestCase):
    def test_finds_run_in_the_middle(self):
        # 类 4 的 affix 判据在这两行上得到 0/0；最长公共子串落在中间。
        self.assertEqual(_longest_common_span("あらキスの方が良い", "キスの方が良いッ"), (7, 2, 0))

    def test_falls_back_to_dynamic_programming_for_short_strings(self):
        self.assertEqual(_longest_common_span("あい", "あい"), (2, 0, 0))
        self.assertEqual(_longest_common_span("あ", "う"), (0, 0, 0))


class PatternEchoTests(unittest.TestCase):
    """类 6「模式复述」：类 4 中缀盲区与类 2 长度断档盲区（S1_09 的真实形态）。"""

    @staticmethod
    def _rows(jp_a: str, jp_b: str, cn_a: str, cn_b: str,
              line_a: int = 1, line_b: int = 2) -> list[dict]:
        return [
            {"file": "a.xhtml", "line": line_a, "jp": jp_a, "cn": cn_a},
            {"file": "a.xhtml", "line": line_b, "jp": jp_b, "cn": cn_b},
        ]

    @staticmethod
    def _seed_mid_span() -> list[dict]:
        return PatternEchoTests._rows(
            "「あら。キスの方が良い？」", "「キスの方が良いッ!!」",
            "「哎呀。还是要接吻呢？」", "「还是接吻更好！！」", 391, 394)

    @staticmethod
    def _seed_length_gap() -> list[dict]:
        return PatternEchoTests._rows(
            "「……自分で言ってて哀しくないの？」",
            "哀しくないもん！　と上条は高速であさっての方向を向こうとする。より一層胸の弾力が"
            "伝わってきて、彼の体がガチガチに凍りついた。吹寄は訝しげな表情のまま、やれやれと"
            "上条をヘッドロックから解放する。",
            "「……你自己说出这种话不会感到悲哀吗？」",
            "「我才不悲哀呢！」上条飞快地想把头扭向毫不相干的方向。然而胸部传来的弹力反而"
            "更加清晰，他的身体瞬间彻底僵住了。吹寄依旧一脸纳闷，无奈地叹了口气，松开了锁住"
            "上条脑袋的手臂。", 292, 293)

    def test_flags_shared_run_in_the_middle(self):
        # S1_09-04 L391/L394：归一 9/8 字，公共前后缀 0/0，中间共享 `キスの方が良い`。
        # 类 4 只比最长公共前后缀，整类漏掉。
        pairs = pattern_echo_pairs(self._seed_mid_span())
        self.assertEqual(len(pairs), 1)
        item = pairs[0]
        self.assertEqual(item["blind"], "类4 中间共享")
        self.assertEqual(item["relation"], "中缀")
        self.assertEqual(item["evidence"], "单处实词替换")
        self.assertEqual(item["span"], "キスの方が良い")
        self.assertEqual((item["diff_a"], item["diff_b"]), ("呢", "更好"))

    def test_flags_short_predicate_inside_long_narration(self):
        # S1_09-04 L292/L293：短句 13 字 + 长叙述 89 字。类 2 只收 ≥20 字的行，
        # 类 4 的 max_len 默认 24 又把长行挡掉，两侧都不收。
        pairs = pattern_echo_pairs(self._seed_length_gap())
        self.assertEqual(len(pairs), 1)
        item = pairs[0]
        self.assertEqual(item["blind"], "类2 长度断档")
        self.assertEqual(item["evidence"], "长行开头复述")
        self.assertEqual(item["span"], "哀しくない")

    def test_respects_line_window(self):
        self.assertEqual(pattern_echo_pairs(self._seed_mid_span(), window=2), [])
        self.assertEqual(len(pattern_echo_pairs(self._seed_mid_span(), window=3)), 1)

    def test_ignores_proper_noun_and_particle_only_spans(self):
        # 共享段去掉格助词后没有平假名 = 专名串：名单、职员表类噪音靠这一条整批消失。
        cases = [
            ("「言ったよな。左方のテッラ」",
             "左方のテッラは、土御門元春の言葉を受けて短く黙った。",
             "「你说过的吧，左方之地。」", "左方之地听到土御门元春的话后，陷入短暂的沉默。"),
            ("「まさか、学園都市を!?」",
             "「学園都市を壊せば、それで皆が幸せになるとでも……？」",
             "「该不会是……学园都市吧？！」", "「你认为破坏了学园都市，大家就能幸福吗……？」"),
            ("「でさー、何だってお前はベランダに干してあった訳？」",
             "「干してあった訳じゃないんだよ？」",
             "「对了，为什么你会晾在阳台上？」", "「我又不是晾在那边的？」"),
        ]
        for jp_a, jp_b, cn_a, cn_b in cases:
            with self.subTest(jp_a=jp_a[:12]):
                self.assertEqual(pattern_echo_pairs(self._rows(jp_a, jp_b, cn_a, cn_b)), [])

    def test_does_not_repeat_class4_affix_pairs(self):
        # 公共前后缀够长时属类 4 的 affix 形态，本类不重复报。
        rows = [
            {"file": "a.xhtml", "line": 6, "jp": "たった三人の『木原』と。", "cn": "仅有三名「木原」。"},
            {"file": "a.xhtml", "line": 7, "jp": "たった三人の『グレムリン』。",
             "cn": "与仅有三名「格雷姆林」，"},
        ]
        self.assertEqual(pattern_echo_pairs(rows), [])

    def test_ignores_parallel_template_with_different_neighbours(self):
        # 职员表形态：共享段两侧紧邻的日文本身不同（監督・／脚本・），中文不同是正确行为。
        rows = self._rows("監督・山田太郎はこう語った。", "脚本・山田太郎はこう語った。",
                          "导演·山田太郎这样说道。", "编剧·山田太郎这样说道。")
        self.assertEqual(pattern_echo_pairs(rows), [])

    def test_ignores_pairs_whose_chinese_is_already_consistent(self):
        # 两侧中文在共享段处译法一致（含只剩虚词差异），不是断裂候选。
        cases = [
            ("「でも、放っておけなかった」", "「……放っておけなかったんだ……」",
             "「但是，我不能丢下你们不管。」", "「……我不能丢下你们不管……」"),
            ("「分かってる」", "「分かってる」", "「这我知道。」", "「这个我也知道。」"),
        ]
        for jp_a, jp_b, cn_a, cn_b in cases:
            with self.subTest(jp_b=jp_b[:12]):
                self.assertEqual(pattern_echo_pairs(self._rows(jp_a, jp_b, cn_a, cn_b)), [])

    def test_render_includes_pattern_section(self):
        rows = self._seed_mid_span()
        report = {"frag": [], "pairs": [], "short": [], "quotes": [],
                  "pattern": pattern_echo_pairs(rows)}
        text, summary = render("S1_09", rows, report)
        self.assertIn("## 类 6 模式复述（1 对：类4 中间共享 1 对／类2 长度断档 0 对）", text)
        self.assertIn("模式复述 1 对", summary)

    def test_render_without_pattern_key_reports_zero(self):
        # 兼容旧调用方：report 里没有 pattern 键时按 0 对输出，不抛异常。
        text, summary = render("S1_01", [], {"frag": [], "pairs": [], "short": [], "quotes": []})
        self.assertIn("## 类 6 模式复述（0 对", text)
        self.assertIn("模式复述 0 对", summary)


class PatternCliTests(unittest.TestCase):
    """类 6 的命令行接线：默认开启、`--no-pattern-pairs` 可关、`--help` 有说明。"""

    @staticmethod
    def _fixture(root: Path) -> tuple[Path, Path]:
        work = "S1_01"
        cn_dir = root / "EPUB" / f"【{work}】测试书" / "OEBPS" / "Text"
        cn_dir.mkdir(parents=True)
        (cn_dir / f"{work}-01_Prologue.xhtml").write_text(
            "<p>「哎呀。还是要接吻呢？」</p>\n<p>「还是接吻更好！！」</p>\n", encoding="utf-8")
        jp_dir = root / "jp" / f"【{work}】テスト本" / "item" / "xhtml"
        jp_dir.mkdir(parents=True)
        (jp_dir / f"{work}-01.xhtml").write_text(
            "<p>「あら。キスの方が良い？」</p>\n<p>「キスの方が良いッ!!」</p>\n", encoding="utf-8")
        return root / "EPUB", root / "jp"

    def test_cli_enables_pattern_pairs_by_default_and_can_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cn_root, jp_root = self._fixture(root)
            base = [sys.executable, str(TOOLS / "check_echo.py"), "--root", str(cn_root),
                    "--jp-root", str(jp_root), "--book", "S1_01"]
            enabled = subprocess.run([*base, "--out", str(root / "on")],
                                     capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            report = (root / "on" / "S1_01-呼应候选.md").read_text(encoding="utf-8")
            self.assertIn("## 类 6 模式复述（1 对", report)

            disabled = subprocess.run([*base, "--out", str(root / "off"), "--no-pattern-pairs"],
                                      capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(disabled.returncode, 0, disabled.stderr)
            report_off = (root / "off" / "S1_01-呼应候选.md").read_text(encoding="utf-8")
            self.assertIn("## 类 6 模式复述（0 对", report_off)

    def test_cli_help_documents_pattern_options(self):
        result = subprocess.run([sys.executable, str(TOOLS / "check_echo.py"), "--help"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        for flag in ("--pattern-window", "--pattern-min-span", "--pattern-min-share",
                     "--pattern-affix", "--no-pattern-pairs"):
            self.assertIn(flag, result.stdout)


class TermGroupTests(unittest.TestCase):
    @staticmethod
    def _rows(renders: list[str]) -> list[dict]:
        """构造同一术语的多次出现；另加 100 行填充，压低头部译法的全卷占比。"""
        rows = [
            {
                "file": "a.xhtml", "line": i + 1,
                "jp": f"本文{i}。筋ジストロフィーは原因不明の不治の病の一つで、筋肉が動かなくなる。",
                "cn": f"第{i}行。{cn}是原因不明的不治之症之一，肌肉会逐渐无法动弹。",
            }
            for i, cn in enumerate(renders)
        ]
        rows.extend(
            {"file": "b.xhtml", "line": i + 1, "jp": "無関係な文。", "cn": "无关的句子。"}
            for i in range(100)
        )
        return rows

    def test_flags_term_with_divergent_chinese(self):
        # 类 1 要求同一日文片段重复；术语嵌在各不相同的长句中时收不到。
        groups = term_groups(self._rows(["肌肉萎缩症"] * 4 + ["肌营养不良症"] * 2))
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["term"], "ジストロフィー")
        self.assertEqual(
            {variant["cn"]: len(variant["rows"]) for variant in group["variants"]},
            {"肌肉萎缩症": 4, "肌营养不良症": 2},
        )

    def test_ignores_uniform_term(self):
        self.assertEqual(term_groups(self._rows(["肌肉萎缩症"] * 6)), [])

    def test_ignores_single_minority_line(self):
        self.assertEqual(term_groups(self._rows(["肌肉萎缩症"] * 5 + ["肌营养不良症"])), [])

    def test_does_not_treat_scene_word_as_variant(self):
        # 场景词在术语各行都出现时不构成「另一种译法」：两种写法必须互补。
        rows = self._rows(["肌肉萎缩症"] * 4 + ["肌营养不良症"] * 2)
        for row in rows[:6]:
            row["cn"] = "美琴" + row["cn"]
        groups = term_groups(rows)
        self.assertEqual(len(groups), 1)
        self.assertNotIn("美琴", {variant["cn"] for variant in groups[0]["variants"]})

    def test_render_includes_term_section(self):
        rows = self._rows(["肌肉萎缩症"] * 4 + ["肌营养不良症"] * 2)
        report = {"frag": [], "pairs": [], "short": [], "quotes": [],
                  "term": term_groups(rows)}
        text, summary = render("S1_01", rows, report)
        self.assertIn("## 类 5 术语多译（1 组）", text)
        self.assertIn("术语多译 1 组", summary)


class QuoteLookupTests(unittest.TestCase):
    def test_finds_source_of_quotation(self):
        rows = [
            {"file": "a.xhtml", "line": 1, "jp": "「魔法名を名乗る前に彼女を保護したいのですが」",
             "cn": "「在报上魔法名之前，我想保护她。」"},
            {"file": "a.xhtml", "line": 2,
             "jp": "『魔法名を名乗る前に彼女を保護したいのですが』と神裂は言った。",
             "cn": "『在报上魔法名之前，我想保护她。』神裂说道。"},
        ]
        found = quote_lookups(rows, min_len=8, cover=0.5)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["src"]["line"], 2)
        self.assertEqual(found[0]["hits"][0]["row"]["line"], 1)
        # 出处行的叙述框架在归一化时被剥掉，引文与之逐字相同 → exact
        self.assertEqual(found[0]["hits"][0]["relation"], "exact")
        # 两层引文内层完全相同（只有外层「」/『』之别，已被归一剥掉）
        self.assertEqual(found[0]["hits"][0]["cn_class"], "并列")

    def test_detects_quotation_upgrade(self):
        # 出处是简写、引述更完整更逐字 → 出处正文含于引文 → wraps／升级
        rows = [
            {"file": "a.xhtml", "line": 1, "jp": "簡単には殺す気はない",
             "cn": "我不会轻易杀你"},
            {"file": "a.xhtml", "line": 2,
             "jp": "『簡単には殺す気はないから、安心しろよ』と告げた。",
             "cn": "『不会轻易杀了你，你放心吧。』他宣告道。"},
        ]
        found = quote_lookups(rows, min_len=8, cover=0.3)
        self.assertTrue(found)
        match = found[0]["hits"][0]
        self.assertEqual(match["row"]["line"], 1)
        self.assertTrue(match["upgrade"])
        self.assertEqual(match["relation"], "wraps")
        self.assertEqual(match["cn_class"], "实词")

    def test_ignores_quote_without_source(self):
        rows = [
            {"file": "a.xhtml", "line": 1, "jp": "『誰も知らない独自の言い回しである』", "cn": "『没人知道的独特说法。』"},
            {"file": "a.xhtml", "line": 2, "jp": "「まったく別の台詞がここに並んでいる」", "cn": "「完全不同的台词排在这里。」"},
        ]
        self.assertEqual(quote_lookups(rows, min_len=8, cover=0.5), [])

    def test_marker_quotes_only_when_enabled(self):
        # 「…って」形态的回指：默认不扫（噪声高），显式开启后才列，
        # 且日文侧找不到出处、中文保留引号时标为「出处未定位」
        rows = [
            {"file": "a.xhtml", "line": 1, "jp": "「さっきから何を言っているんだ」",
             "cn": "「你从刚才开始都在说什么啊？」"},
            {"file": "a.xhtml", "line": 2, "jp": "「あのな。つかないんだよって、馬鹿いるか」",
             "cn": "「我说啊，还说什么『不会留下伤痕』，哪有这种笨蛋。」"},
        ]
        self.assertEqual(quote_lookups(rows, min_len=8, cover=0.5), [])
        found = quote_lookups(rows, min_len=8, cover=0.5, include_marker=True)
        self.assertTrue(found)
        self.assertEqual(found[0]["kind"], "引述助词")
        self.assertEqual(found[0]["hits"], [])

    def test_requires_source_before_quote(self):
        # 出处必须在引述处之前：出处在后的配对多为误配（引述是「回指前文」）
        rows = [
            {"file": "a.xhtml", "seq": "S1_01-01", "line": 1,
             "jp": "「魔法名を名乗る前に彼女を保護したいのですが」",
             "cn": "「在报上魔法名之前，我想保护她。」"},
            {"file": "a.xhtml", "seq": "S1_01-02", "line": 9,
             "jp": "『魔法名を名乗る前に彼女を保護したいのですが』と神裂は言った。",
             "cn": "『在报上魔法名之前，我想保护她。』神裂说道。"},
        ]
        found = quote_lookups(rows, min_len=8, cover=0.5)
        self.assertTrue(found)
        # 出处（seq 01 / line 1）在引述处（seq 02 / line 9）之前，保留
        self.assertEqual(found[0]["hits"][0]["row"]["line"], 1)
        # 反向：把「引述处」放到前面，则该配对不再成立
        reversed_rows = [rows[1], rows[0]]
        for cand in quote_lookups(reversed_rows, min_len=8, cover=0.5):
            for hit in cand["hits"]:
                self.assertLess(
                    (hit["row"]["seq"], hit["row"]["line"]),
                    (cand["src"]["seq"], cand["src"]["line"]),
                )

    def test_skips_proper_noun_quotes(self):
        # 不含平假名的引文＝纯专名/名词短语，不承载「引述某处说法」的呼应
        rows = [
            {"file": "a.xhtml", "line": 1, "jp": "「ブラフマーアストラ」", "cn": "「梵天法宝」"},
            {"file": "a.xhtml", "line": 2,
             "jp": "彼は『ブラフマーアストラ』を使った。", "cn": "他使用了『梵天法宝』。"},
        ]
        self.assertEqual(quote_lookups(rows, min_len=8, cover=0.5), [])

    def test_reports_fragment_echo_when_quote_is_rewritten(self):
        # 引述整体改写：前半换说法（結構良い環境でしょ？→それほど悪い環境じゃないでしょう？），
        # 后半 26 字逐字照抄。整体覆盖率 0.575 < 0.8，旧规则整条丢弃，这段的中文漂移
        # （「维持这样安逸的生活」／「打理好这里的环境」）就没人核对（S1_11-06 L206/L484）。
        rows = [
            {"file": "a.xhtml", "line": 1,
             "jp": "結構良い環境でしょ？　ソイツを整えるために皆には働いてもらってんですけどね",
             "cn": "「环境还算不错吧？为了维持这样的生活，只好请大家工作喽。」"},
            {"file": "a.xhtml", "line": 2,
             "jp": "『それほど悪い環境じゃないでしょう？　ま、ソイツを整えるために皆には働いてもらってんですけどね』",
             "cn": "『环境也没那么糟吧？不过嘛，为了维持这样的环境，才让大家干活的呢。』"},
        ]
        found = quote_lookups(rows, min_len=8, cover=0.5)
        self.assertTrue(found)
        match = found[0]["hits"][0]
        self.assertEqual(match["relation"], "fuzzy")
        self.assertEqual(match["fragment"], "ソイツを整えるために皆には働いてもらってんですけどね")

        # 片段门槛可调：调到 30 字时该候选不再是呼应点
        self.assertEqual(quote_lookups(rows, min_len=8, cover=0.5, frag_min=30), [])

    def test_skips_kana_only_fragment(self):
        # 12 字片段全是假名语法串（「そういうことなんですけどね」）不构成呼应
        rows = [
            {"file": "a.xhtml", "line": 1,
             "jp": "ええ、そういうことなんですけどね、たしかにそうですね",
             "cn": "「嗯，就是这么回事呢，确实如此。」"},
            {"file": "a.xhtml", "line": 2,
             "jp": "『まあね、そういうことなんですけどね、はいはい』",
             "cn": "『是啊，就是这么回事呢，好好好。』"},
        ]
        self.assertEqual(quote_lookups(rows, min_len=8, cover=0.4), [])

    def test_skips_onomatopoeia_fragment(self):
        # 拟声／长音串不是「说法」：全库扫描里 S2_01 的「呜啊啊啊…」就是这类噪声
        rows = [
            {"file": "a.xhtml", "line": 1,
             "jp": "「ギャアァァァァァァァァァァァァァァァァァァ」",
             "cn": "「啊啊啊啊啊啊啊啊啊啊啊啊啊啊！」"},
            {"file": "a.xhtml", "line": 2,
             "jp": "『うわ、いやだ、やめて、キャアァァァァァァァァァァァァァァァァァ』",
             "cn": "『呜哇，不要，住手，哇啊啊啊啊啊啊啊啊啊啊啊！』"},
        ]
        self.assertEqual(quote_lookups(rows, min_len=8, cover=0.4), [])

    def test_deduplicates_same_position_pair(self):
        # 同一行出现两次相同引文时，位置对只应出现一次
        rows = [
            {"file": "a.xhtml", "line": 1, "jp": "「魔法名を名乗る前に彼女を保護したいのですが」",
             "cn": "「在报上魔法名之前，我想保护她。」"},
            {"file": "a.xhtml", "line": 2,
             "jp": "『魔法名を名乗る前に彼女を保護したいのですが』と述べ、さらに『魔法名を名乗る前に彼女を保護したいのですが』と繰り返した。",
             "cn": "『在报上魔法名之前，我想保护她。』他说，又重复了一遍『在报上魔法名之前，我想保护她。』"},
        ]
        found = quote_lookups(rows, min_len=8, cover=0.5)
        pairs = {(c["src"]["line"], h["row"]["line"]) for c in found for h in c["hits"]}
        self.assertEqual(len(pairs), len(found))
        self.assertEqual(pairs, {(2, 1)})

    def test_finds_cross_book_top_level_quote_source(self):
        prior_rows = [
            {
                "work": "S2_18", "seq": "S2_18-02", "file": "S2_18-02_Chapter1.xhtml", "line": 10,
                "jp": "「魔法名を名乗る前に彼女を保護したいのですが」",
                "cn": "「在报上魔法名之前，我想保护她。」",
            },
            {
                "work": "S2_18", "seq": "S2_18-03", "file": "S2_18-03_Chapter2.xhtml", "line": 20,
                "jp": "「私と一緒に地獄の底までついてきてくれる？」",
                "cn": "「你愿意陪我一起走到地狱之底吗？」",
            },
        ]
        rows = [
            {
                "work": "S2_19", "seq": "S2_19-01", "file": "S2_19-01_Before_the_Prologue.xhtml", "line": 6,
                "jp": "『魔法名を名乗る前に彼女を保護したいのですが』",
                "cn": "『报名之前我先保护她吧。』",
            },
            {
                "work": "S2_19", "seq": "S2_19-01", "file": "S2_19-01_Before_the_Prologue.xhtml", "line": 10,
                "jp": "『私と一緒に地獄の底までついてきてくれる？』",
                "cn": "『你愿意陪我一起走到地狱之底吗？』",
            },
        ]
        found = quote_lookups(rows, min_len=8, cover=0.5, prior_rows=prior_rows)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["src"]["line"], 6)
        hit = found[0]["hits"][0]
        self.assertTrue(hit["cross_book"])
        self.assertEqual(hit["row"]["work"], "S2_18")
        self.assertEqual(hit["row"]["line"], 10)

    def test_default_prior_works_respects_series_and_order(self):
        all_works = ["S1_01", "S1_02", "S2_18", "S2_19", "S2_20", "S3_01", "S4_01", "S4_02"]
        self.assertEqual(default_prior_works("S2_19", all_works), ["S1_01", "S1_02", "S2_18"])
        self.assertEqual(default_prior_works("S4_02", all_works), ["S4_01"])

    def test_cli_cross_books_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cn_root = root / "EPUB"
            jp_root = root / "jp"
            for work, cn_line, jp_line in (
                ("S1_01", "<p>「在报上魔法名之前，我想保护她。」</p>\n",
                 "<p>「魔法名を名乗る前に彼女を保護したいのですが」</p>\n"),
                ("S1_02", "<p>『报上魔法名之前我想先救下她。』</p>\n",
                 "<p>『魔法名を名乗る前に彼女を保護したいのですが』</p>\n"),
            ):
                cn_dir = cn_root / f"【{work}】测试书" / "OEBPS" / "Text"
                jp_dir = jp_root / f"【{work}】テスト本" / "item" / "xhtml"
                cn_dir.mkdir(parents=True)
                jp_dir.mkdir(parents=True)
                (cn_dir / f"{work}-01_Prologue.xhtml").write_text(cn_line, encoding="utf-8")
                (jp_dir / f"{work}-01.xhtml").write_text(jp_line, encoding="utf-8")
            out = root / "out"
            rc = echo_main([
                "--book", "S1_02", "--cross-books", "S1_01",
                "--root", str(cn_root), "--jp-root", str(jp_root), "--out", str(out),
            ])
            self.assertEqual(rc, 0)
            report_text = (out / "S1_02-呼应候选.md").read_text(encoding="utf-8")
            self.assertIn("[跨卷]", report_text)
            self.assertIn("S1_01/S1_01-01_Prologue.xhtml:1", report_text)


class IterWorksTests(unittest.TestCase):
    def test_returns_intersection_of_both_sides(self):
        # 只有单侧书目录的作品号不参与统计，否则会刷「缺日文对照」告警
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = build_fixture(Path(tmp))
            (cn_root / "【S1_02】只有中文").mkdir()
            (jp_root / "【S1_03】只有日文").mkdir()
            self.assertEqual(["S1_01"], iter_works(cn_root, jp_root))


class ConventionStatsTests(unittest.TestCase):
    def test_cli_persists_coverage_and_pairing_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cn_root, jp_root = self._fixture(
                root, "<p>她叹气。</p>\n", "<p>前置き。</p>\n<p>彼女は息を吐く。</p>\n",
            )
            out = root / "report"
            result = subprocess.run(
                [sys.executable, str(TOOLS / "check_echo.py"),
                 "--root", str(cn_root), "--jp-root", str(jp_root), "--out", str(out),
                 "--convention", "息を吐", "--convention-words", "叹气"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            for rendered in (result.stdout, (out / "convention.md").read_text(encoding="utf-8")):
                self.assertIn("请求 1 本", rendered)
                self.assertIn("可靠配对 0 本", rendered)
                self.assertIn("零覆盖：S1_01", rendered)
                self.assertIn("cn=1 jp=2", rendered)

    def test_cli_zero_coverage_is_not_success_but_zero_matches_are(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cn_root, jp_root = build_fixture(root)
            base = [sys.executable, str(TOOLS / "check_echo.py"), "--root", str(cn_root),
                    "--jp-root", str(jp_root), "--out", str(root / "report")]
            no_matches = subprocess.run([*base, "--convention", "存在しない語"],
                                       capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(no_matches.returncode, 0, no_matches.stderr)
            for selection in (["--book", "S1_99"], ["--convention", "息", "--convention-books", "S1_99"]):
                result = subprocess.run([*base, *selection], capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("可靠配对", result.stderr)

    def test_candidate_summary_preserves_partial_coverage_and_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cn_root, jp_root = build_fixture(root)
            out = root / "report"
            result = subprocess.run(
                [sys.executable, str(TOOLS / "check_echo.py"), "--root", str(cn_root),
                 "--jp-root", str(jp_root), "--out", str(out), "--book", "S1_01", "--book", "S1_99"],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            for rendered in (result.stdout, (out / "summary.md").read_text(encoding="utf-8")):
                self.assertIn("请求 2 本", rendered)
                self.assertIn("可靠配对 1 本", rendered)
                self.assertIn("S1_99", rendered)

    def test_repeated_work_arguments_do_not_double_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = self._fixture(
                Path(tmp), "<p>她叹气。</p>\n", "<p>彼女は息を吐く。</p>\n",
            )
            stats = convention_stats(["息を吐"], ["叹气"], cn_root, jp_root, ["S1_01", "s1_01"])
            self.assertEqual(stats["requested_works"], 1)
            self.assertEqual(stats["groups"][0]["hits"], 1)

    def test_reports_skipped_partial_and_matched_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = self._fixture(
                Path(tmp), "<p>她叹气。</p>\n", "<p>彼女は息を吐く。</p>\n",
            )
            cn_dir = cn_root / "【S1_01】测试书" / "OEBPS" / "Text"
            (cn_dir / "S1_01-02_Chapter.xhtml").write_text("<p>缺少对照。</p>\n", encoding="utf-8")
            stats = convention_stats(
                ["息を吐"], ["叹气"], cn_root, jp_root, ["S1_01", "S1_02"],
            )
            self.assertEqual(stats["requested_works"], 2)
            self.assertEqual(stats["works"], 1)
            self.assertEqual(stats["paired_rows"], 1)
            self.assertEqual(stats["matched_works"], ["S1_01"])
            self.assertEqual(stats["partial_works"], ["S1_01"])
            self.assertEqual(stats["skipped_works"], ["S1_02"])
            self.assertTrue(any("缺日文对照" in n for n in stats["notes"]))
            text, summary = render_convention(stats)
            for rendered in (text, summary):
                self.assertIn("请求 2 本", rendered)
                self.assertIn("可靠配对 1 本", rendered)
                self.assertIn("可靠配对行 1", rendered)
                self.assertIn("部分覆盖：S1_01", rendered)
                self.assertIn("零覆盖：S1_02", rendered)
                self.assertIn("缺日文对照", rendered)

    def test_mismatched_file_does_not_become_unclassified_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = self._fixture(
                Path(tmp), "<p>她叹气。</p>\n", "<p>前置き。</p>\n<p>彼女は息を吐く。</p>\n",
            )
            stats = convention_stats(["息を吐"], ["叹气"], cn_root, jp_root)
            self.assertEqual(stats["works"], 0)
            self.assertEqual(stats["groups"][0]["hits"], 0)
            self.assertEqual(stats["groups"][0]["other"], 0)
            self.assertTrue(any("cn=1 jp=2" in n for n in stats["notes"]))

    def test_paired_work_with_no_pattern_match_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = build_fixture(Path(tmp))
            stats = convention_stats(["存在しない語"], [], cn_root, jp_root)
            self.assertEqual(stats["works"], 1)
            self.assertEqual(stats["paired_rows"], 5)
            self.assertEqual(stats["matched_works"], [])
            self.assertEqual(stats["skipped_works"], [])

    def test_empty_roots_and_zero_pair_work_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = build_fixture(Path(tmp))
            for path in jp_root.rglob("*.xhtml"):
                path.unlink()
            stats = convention_stats(["息を吐"], [], cn_root, jp_root)
            self.assertEqual(stats["works"], 0)
            self.assertEqual(stats["skipped_works"], ["S1_01"])
            self.assertTrue(stats["notes"])
            stats = convention_stats(["息を吐"], [], Path(tmp) / "missing-cn", Path(tmp) / "missing-jp")
            self.assertEqual(stats["works"], 0)
            text, summary = render_convention(stats)
            for rendered in (text, summary):
                self.assertIn("中文根目录不存在", rendered)
                self.assertIn("日文根目录不存在", rendered)

    def _fixture(self, root: Path, cn_lines: str, jp_lines: str) -> tuple[Path, Path]:
        cn_root, jp_root = build_fixture(root)
        (cn_root / "【S1_01】测试书" / "OEBPS" / "Text" / "S1_01-01_Prologue.xhtml").write_text(
            cn_lines, encoding="utf-8")
        (jp_root / "【S1_01】テスト本" / "item" / "xhtml" / "S1_01-01.xhtml").write_text(
            jp_lines, encoding="utf-8")
        return cn_root, jp_root

    def test_groups_take_first_match_and_words_are_regex(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = self._fixture(
                Path(tmp),
                "<p>她叹了口气。</p>\n<p>她轻轻地吐出一口气。</p>\n<p>无关行。</p>\n",
                "<p>そっと息を吐く。</p>\n<p>そっと息を吐いて、</p>\n<p>どうでもいい。</p>\n",
            )
            stats = convention_stats([r"息を吐"], [r"叹[气了息]", r"吐[出了气]"], cn_root, jp_root)
            group = stats["groups"][0]
            self.assertEqual(2, group["hits"])
            # 词条按正则解释：「叹了口气」「吐出一口气」都能命中（字面比对会漏判）
            self.assertEqual(1, group["words"][r"叹[气了息]"])
            self.assertEqual(1, group["words"][r"吐[出了气]"])
            self.assertEqual(0, group["other"])

    def test_first_matching_group_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = self._fixture(
                Path(tmp),
                "<p>她叹了口气。</p>\n<p>她吐出一口气。</p>\n<p>无关行。</p>\n",
                "<p>そっと息を吐く。</p>\n<p>息を吐く。</p>\n<p>どうでもいい。</p>\n",
            )
            stats = convention_stats([r"そっと息を吐", r"息を吐"], [r"叹[气了息]"], cn_root, jp_root)
            self.assertEqual(1, stats["groups"][0]["hits"])
            self.assertEqual(1, stats["groups"][1]["hits"])

    def test_reports_other_samples_for_filling_wordlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = self._fixture(
                Path(tmp),
                "<p>她叹了口气。</p>\n<p>她轻舒了口气。</p>\n<p>无关行。</p>\n",
                "<p>そっと息を吐く。</p>\n<p>そっと息を吐いて、</p>\n<p>どうでもいい。</p>\n",
            )
            stats = convention_stats([r"息を吐"], [r"叹[气了息]"], cn_root, jp_root)
            text, summary = render_convention(stats)
            self.assertEqual(1, stats["groups"][0]["other"])
            # 未分类样例带出处，便于据此补词表
            self.assertIn("未分类样例", summary)
            self.assertIn("轻舒了口气", summary)
            self.assertIn("未分类", text)

    def test_stack_and_work_distribution_rendered(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = self._fixture(
                Path(tmp),
                "<p>她叹了口气。</p>\n<p>她吐出一口气。</p>\n<p>无关行。</p>\n",
                "<p>そっと息を吐く。</p>\n<p>そっと息を吐いて、</p>\n<p>どうでもいい。</p>\n",
            )
            stats = convention_stats([r"息を吐"], [r"叹[气了息]", r"吐[出了气]"], cn_root, jp_root)
            text, summary = render_convention(stats, min_book=1)
            self.assertIn("50.0%", summary)
            self.assertIn("S1_01", summary)
            self.assertIn("分卷分布", text)

    def test_ignores_whitespace_left_by_ruby_stripping(self):
        # 注音剥除会留下 `呆 れ たように` 这类空格，正则按连续文本写即可命中
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = self._fixture(
                Path(tmp),
                "<p>她无奈地叹了口气。</p>\n<p>无关行。</p>\n",
                "<p>呆 れ たように息を吐いて、</p>\n<p>どうでもいい。</p>\n",
            )
            stats = convention_stats([r"呆れたように息を吐"], [r"叹[气了息]"], cn_root, jp_root)
            self.assertEqual(1, stats["groups"][0]["hits"])


if __name__ == "__main__":
    unittest.main()
