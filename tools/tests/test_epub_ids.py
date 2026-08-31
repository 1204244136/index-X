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
        self.assertEqual(japanese_book_id("S5_01_03"), "S5_01")

    def test_headers_and_sequence(self):
        self.assertEqual(header_of("S5_01_03-00_Introduction.xhtml"), "S5_01_03-00")
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
