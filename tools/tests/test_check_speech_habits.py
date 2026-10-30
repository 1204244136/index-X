from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_speech_habits

HEADER = "角色,口癖,类型,小说首次出现,网翻,台版（转简中）,X版,备注,裁定状态\n"
RULING_HEAD = (
    "## 六、角色口癖与自称\n\n"
    "| 角色 | 日文锚点 | 裁定 | 被否决或并存的候选 | 备注 | 判定 |\n"
    "| --- | --- | --- | --- | --- | --- |\n"
)


class SpeechHabitsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.csv = self.root / "character-speech-habits.csv"
        self.rulings = self.root / "translation-name-rulings.md"

    def write(self, rows: list[str], rulings: list[str] | None = None) -> None:
        self.csv.write_text(HEADER + "".join(rows), encoding="utf-8")
        self.rulings.write_text(RULING_HEAD + "".join(rulings or []), encoding="utf-8")

    def run_check(self) -> list[str]:
        problems, _, _ = check_speech_habits.check(self.csv, self.rulings)
        return problems

    # ── 通过路径 ──

    def test_minimal_pass(self):
        self.write(
            ["甲,あ,第一人称,S1_01,未查到,未查到,阿,,已裁定\n"],
            ["| 甲 | `あ` | 阿 | — | 说明 |  |\n"],
        )
        self.assertEqual(self.run_check(), [])

    def test_rule_type_pass(self):
        self.write(["乙,不适用,句式,S1_01,未查到,未查到,未查到,句尾变片假名,规则型\n"], [])
        self.assertEqual(self.run_check(), [])

    def test_composite_role_and_anchor_variant_pass(self):
        self.write(
            ["丙,どす・まへん・はる,方言腔调,S2_14,未查到,未查到,不处理,京都弁,已裁定\n"],
            ["| 丙／丁 | `どす` | 按普通口语译出，不拟方言 | — | 说明 | 人读 |\n"],
        )
        self.assertEqual(self.run_check(), [])

    def test_exempt_anchor_pass(self):
        self.write(
            ["甲,あ,第一人称,S1_01,未查到,未查到,阿,,已裁定\n"],
            [
                "| 甲 | `あ` | 阿 | — | 说明 |  |\n",
                "| 乙 | `たん` | 炭 | — | 通用后缀 | 严格全文 |\n",
            ],
        )
        self.assertEqual(self.run_check(), [])

    # ── 失败路径 ──

    def test_header_mismatch(self):
        self.csv.write_text("角色,口癖\n甲,あ\n", encoding="utf-8")
        self.rulings.write_text(RULING_HEAD, encoding="utf-8")
        problems = self.run_check()
        self.assertEqual(len(problems), 1)
        self.assertIn("表头不符", problems[0])

    def test_duplicate_key(self):
        self.write(
            [
                "甲,あ,第一人称,S1_01,未查到,未查到,阿,,已裁定\n",
                "甲,あ,第一人称,S1_01,未查到,未查到,阿,,已裁定\n",
            ],
            ["| 甲 | `あ` | 阿 | — | 说明 |  |\n"],
        )
        self.assertTrue(any("重复" in p for p in self.run_check()))

    def test_dash_forbidden(self):
        self.write(["甲,あ,第一人称,-,未查到,未查到,阿,,已裁定\n"],
                   ["| 甲 | `あ` | 阿 | — | 说明 |  |\n"])
        self.assertTrue(any("不再允许" in p for p in self.run_check()))

    def test_marker_in_wrong_column(self):
        self.write(["甲,未查到,第一人称,S1_01,未查到,未查到,阿,,已裁定\n"],
                   ["| 甲 | `あ` | 阿 | — | 说明 |  |\n"])
        self.assertTrue(any("只允许出现在" in p for p in self.run_check()))

    def test_status_unknown(self):
        self.write(["甲,あ,第一人称,S1_01,未查到,未查到,阿,,已定\n"],
                   ["| 甲 | `あ` | 阿 | — | 说明 |  |\n"])
        self.assertTrue(any("不在" in p for p in self.run_check()))

    def test_rule_type_requires_placeholder(self):
        self.write(["甲,あ,句式,S1_01,未查到,未查到,未查到,,规则型\n"],
                   ["| 甲 | `あ` | 阿 | — | 说明 |  |\n"])
        self.assertTrue(any("必须是 `不适用`" in p for p in self.run_check()))

    def test_ruled_but_missing(self):
        self.write(["甲,あ,第一人称,S1_01,未查到,未查到,阿,,已裁定\n"], [])
        self.assertTrue(any("找不到" in p for p in self.run_check()))

    def test_unruled_but_registered(self):
        self.write(["甲,あ,第一人称,S1_01,未查到,未查到,未查到,,未裁定\n"],
                   ["| 甲 | `あ` | 阿 | — | 说明 |  |\n"])
        self.assertTrue(any("已登记" in p for p in self.run_check()))

    def test_mirror_mismatch(self):
        self.write(["甲,あ,第一人称,S1_01,未查到,未查到,啊,,已裁定\n"],
                   ["| 甲 | `あ` | 阿 | — | 说明 |  |\n"])
        self.assertTrue(any("应镜像" in p for p in self.run_check()))

    def test_prose_decision_requires_no_handle(self):
        self.write(["甲,どす,方言腔调,S2_14,未查到,未查到,按普通口语译出,,已裁定\n"],
                   ["| 甲 | `どす` | 按普通口语译出，不拟方言 | — | 说明 | 人读 |\n"])
        self.assertTrue(any("应镜像 §六 裁定 `不处理`" in p for p in self.run_check()))

    def test_reverse_coverage_missing_row(self):
        self.write(
            ["甲,あ,第一人称,S1_01,未查到,未查到,阿,,已裁定\n"],
            [
                "| 甲 | `あ` | 阿 | — | 说明 |  |\n",
                "| 丙 | `う` | 呜 | — | 说明 |  |\n",
            ],
        )
        self.assertTrue(any("在本表没有对应行" in p for p in self.run_check()))

    def test_missing_input_returns_two(self):
        missing = self.root / "nope.csv"
        code = check_speech_habits.main(["--csv", str(missing), "--rulings", str(self.rulings)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
