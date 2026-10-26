from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from check_term_anchors import (  # noqa: E402
    DEFAULT_ANCHORS,
    audit_roots,
    load_rules,
    main,
    match_line,
)

RULINGS = """# 测试裁定表

| 日文锚点 | 裁定 | 被否决或并存的候选 | 备注 | 判定 |
| --- | --- | --- | --- | --- |
| `魔術`／`魔術師` | 魔法／魔法师 | 魔术／魔术师 | 术语层须与手技层分开 |  |
"""


class TempBook:
    """最小中日配对书：同样的物理行数，便于逐行判定。"""

    def __init__(self, root: Path):
        self.root = root
        self.cn_root = root / "EPUB"
        self.jp_root = root / "jp"
        self.rulings = root / "rulings.md"
        self.rulings.write_text(RULINGS, encoding="utf-8")

    def write(self, cn_lines: list[str], jp_lines: list[str]) -> None:
        cn_dir = self.cn_root / "【S1_01】测试书" / "OEBPS" / "Text"
        jp_dir = self.jp_root / "【S1_01】テスト" / "item" / "xhtml"
        cn_dir.mkdir(parents=True, exist_ok=True)
        jp_dir.mkdir(parents=True, exist_ok=True)
        (cn_dir / "S1_01-01_Chapter1.xhtml").write_text("\n".join(cn_lines) + "\n", encoding="utf-8")
        (jp_dir / "S1_01-01.xhtml").write_text("\n".join(jp_lines) + "\n", encoding="utf-8")


class RuleLoadingTests(unittest.TestCase):
    def test_rules_read_accepted_and_rejected_forms(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = TempBook(Path(tmp))
            rules = load_rules(book.rulings, DEFAULT_ANCHORS)
        by_anchor = {rule["anchor"]: rule for rule in rules}
        self.assertEqual(by_anchor["魔術"]["accepted"], ["魔法", "魔法师"])
        self.assertEqual(by_anchor["魔術"]["rejected"], ["魔术", "魔术师"])
        # 长锚点排前，避免 `魔術` 把 `魔術師` 拆开重复计数
        self.assertEqual(rules[0]["anchor"], "魔術師")

    def test_missing_anchor_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = TempBook(Path(tmp))
            with self.assertRaises(ValueError):
                load_rules(book.rulings, ("存在しない",))


class MatchLineTests(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.rules = load_rules(TempBook(Path(tmp)).rulings, DEFAULT_ANCHORS)

    def test_bare_majutsu_with_majutsu_is_hit(self):
        hits = match_line("魔術を使う。", "使用魔术。", self.rules)
        self.assertEqual([hit["anchor"] for hit in hits], ["魔術"])
        self.assertEqual(hits[0]["found"], "魔术")

    def test_ruling_form_passes(self):
        self.assertEqual(match_line("魔術を使う。", "使用魔法。", self.rules), [])

    def test_majutsushi_is_not_double_counted(self):
        hits = match_line("魔術師だ。", "魔术师。", self.rules)
        self.assertEqual([hit["anchor"] for hit in hits], ["魔術師"])

    def test_tarot_name_is_exception(self):
        self.assertEqual(match_line("タロットの『魔術師』。", "塔罗的『魔术师』。", self.rules), [])

    def test_hand_trick_is_not_an_anchor(self):
        self.assertEqual(match_line("手品だ。", "魔术。", self.rules), [])

    def test_no_rejected_form_is_not_a_hit(self):
        # 缺裁定写法但也没有登记误形：可能是省略或改写，不阻断
        self.assertEqual(match_line("魔術を使う。", "施展术式。", self.rules), [])


class AuditTests(unittest.TestCase):
    def test_hit_reported_with_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = TempBook(Path(tmp))
            book.write(
                ["<p>开场。</p>", "<p>使用魔术。</p>"],
                ["<p>導入。</p>", "<p>魔術を使う。</p>"],
            )
            rows, checked, skipped, notes = audit_roots(
                book.cn_root, book.jp_root, rulings_path=book.rulings,
            )
        self.assertEqual((checked, skipped), (1, 0))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["book"], rows[0]["file"], rows[0]["line"]), ("S1_01", "S1_01-01_Chapter1.xhtml", 2))
        self.assertEqual(rows[0]["found"], "魔术")

    def test_line_count_mismatch_is_skipped_not_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = TempBook(Path(tmp))
            book.write(
                ["<p>一。</p>", "<p>二。</p>", "<p>三。</p>"],
                ["<p>一。</p>"],
            )
            rows, checked, skipped, notes = audit_roots(
                book.cn_root, book.jp_root, rulings_path=book.rulings,
            )
        self.assertEqual((checked, skipped, len(rows)), (0, 1, 0))
        self.assertTrue(any("行数不等" in note for note in notes))

    def test_strict_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = TempBook(Path(tmp))
            book.write(["<p>使用魔术。</p>"], ["<p>魔術。</p>"])
            argv = ["--epub", str(book.cn_root), "--jp-dir", str(book.jp_root),
                    "--rulings", str(book.rulings), "--out", str(Path(tmp) / "out.tsv"), "--strict"]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(argv), 1)
            book.write(["<p>使用魔法。</p>"], ["<p>魔術。</p>"])
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(argv), 0)


if __name__ == "__main__":
    unittest.main()
