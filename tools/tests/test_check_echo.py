from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from check_echo import (  # noqa: E402
    convention_stats,
    find_book_dir,
    frag_groups,
    grams,
    iter_works,
    load_pairs,
    norm_cn,
    norm_jp,
    quote_lookups,
    render_convention,
    sim_pairs,
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
            self.assertEqual(len(rows), 6)
            self.assertTrue(any("行数不等" in n for n in notes))

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


class IterWorksTests(unittest.TestCase):
    def test_returns_intersection_of_both_sides(self):
        # 只有单侧书目录的作品号不参与统计，否则会刷「缺日文对照」告警
        with tempfile.TemporaryDirectory() as tmp:
            cn_root, jp_root = build_fixture(Path(tmp))
            (cn_root / "【S1_02】只有中文").mkdir()
            (jp_root / "【S1_03】只有日文").mkdir()
            self.assertEqual(["S1_01"], iter_works(cn_root, jp_root))


class ConventionStatsTests(unittest.TestCase):
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
