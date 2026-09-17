from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from epub_ids import (  # noqa: E402
    book_id,
    content_sequence,
    header_of,
    japanese_book_id,
    work_id,
)
from alignment_rules import pairing_header_of  # noqa: E402


class EpubIdTests(unittest.TestCase):
    def test_complete_book_ids(self):
        self.assertEqual(book_id("[S5_01_03]作品"), "S5_01_03")
        self.assertEqual(book_id("[S6_24.06.07]短篇"), "S6_24.06.07")

    def test_japanese_side_uses_the_same_work_id(self):
        """日文侧不是合订卷目录，而是 split_s5_epubs.py 拆出的独立作品目录。

        这里曾经断言 `S5_01_03 -> S5_01`（映射到「外典书库」合订卷）。真实缓存里
        日文侧是 `[S5_01_01]…`、`[S5_01_02]…`、`[S5_01_03]…`，与 split_s5_epubs.py
        的 SPLIT_SPECS 命名一致；折叠后的 id 查不到目录，于是所有调用方都把这本
        当成「无日文对应」静默跳过——8 本 S5 作品从未参与配对检查和对齐工具。
        """
        for value in ("S5_01_03", "S5_02_03", "S1_01", "S6_24.06.07", "S0_00"):
            self.assertEqual(japanese_book_id(value), value)

    def test_headers_and_sequence(self):
        # 解析器仍识别旧的 -00，供验证器明确报告；规范名称从 -01 开始。
        self.assertEqual(header_of("S5_01_03-00_Introduction.xhtml"), "S5_01_03-00")
        self.assertEqual(content_sequence("S5_01_03-00_Introduction.xhtml"), 0)
        self.assertEqual(header_of("S6_24.06.07-02_Chapter.xhtml"), "S6_24.06.07-02")
        self.assertEqual(header_of("S1_25-Uiharu_Kazari.xhtml"), "S1_25-UIHARU_KAZARI")
        self.assertEqual(content_sequence("S1_01-02_Chapter1.xhtml"), 2)
        self.assertEqual(content_sequence("S6_24.06.07-Main.xhtml"), None)

    def test_historical_alias_is_not_guessed_as_pairing_header(self):
        old = "S5_02-03_coldgame_p-020.xhtml"
        self.assertIsNone(header_of(old))
        self.assertEqual(work_id(old), "S5_02_03")

    def test_canonical_pairing_header(self):
        self.assertEqual(
            pairing_header_of("S6_22.06.10-02.xhtml"),
            "S6_22.06.10-02",
        )
        self.assertIsNone(pairing_header_of("S6_22.06.10-p-caution.xhtml"))


if __name__ == "__main__":
    unittest.main()
