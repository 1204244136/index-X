from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from fix_legacy_pagebreak_br import find_legacy_br  # noqa: E402

HEAD = ["<?xml version='1.0'?>", "<!DOCTYPE html>", '<html><head></head><body>']
TAIL = ["</body></html>"]


def jp(*lines: str) -> list[str]:
    return [*HEAD, "<h1>第一章</h1>", "", *lines, *TAIL]


def cn(*lines: str) -> list[str]:
    return [*HEAD, "<h1>第一章</h1>", "", *lines, *TAIL]


class LegacyPagebreakBrTest(unittest.TestCase):
    def test_single_legacy_br_after_pb_paragraph_is_flagged(self):
        """日文侧 pb 段落不占行；中文侧同边界多出的 1 个 <br/> 判为旧合页。"""
        japanese = jp("<p>A</p>", '<p class="pb">B</p>', "<p>C</p>")
        chinese = cn("<p>甲</p>", "<p>乙</p>", "<br/>", "<p>丙</p>")
        # 中文 L7=乙, L8=<br/> → 0-based 7
        self.assertEqual(find_legacy_br(japanese, chinese), [7])

    def test_double_legacy_br_run_is_flagged_wholesale(self):
        """旧合页写法常为 1~2 个连续 <br/>，两处都要判出。"""
        japanese = jp("<p>A</p>", '<p class="pb">B</p>', "<p>C</p>")
        chinese = cn("<p>甲</p>", "<p>乙</p>", "<br/>", "<br/>", "<p>丙</p>")
        self.assertEqual(find_legacy_br(japanese, chinese), [7, 8])

    def test_equal_br_runs_are_real_scene_separators_and_kept(self):
        """两侧 <br/> 数量一致 → 真场景分隔，一行都不删。"""
        japanese = jp("<p>A</p>", '<p class="pb">B</p>', "<br/>", "<p>C</p>")
        chinese = cn("<p>甲</p>", "<p>乙</p>", "<br/>", "<p>丙</p>")
        self.assertEqual(find_legacy_br(japanese, chinese), [])

    def test_scene_br_without_pb_boundary_is_untouched(self):
        """没有 pb 边界的中文 <br/> 一律不处理。"""
        japanese = jp("<p>A</p>", "<p>B</p>", "<br/>", "<p>C</p>")
        chinese = cn("<p>甲</p>", "<p>乙</p>", "<br/>", "<br/>", "<p>丙</p>")
        self.assertEqual(find_legacy_br(japanese, chinese), [])

    def test_surplus_beyond_the_boundary_is_not_consumed(self):
        """第三行 <br/> 已不属于该 pb 边界（日文侧无对应连段）时仍按遗留判出，
        但不得把内容行误删；同时 L1-L6 模板槽位内的行永不进入结果。"""
        japanese = jp("<p>A</p>", '<p class="pb">B</p>', "<p>C</p>")
        chinese = cn("<p>甲</p>", "<p>乙</p>", "<br/>", "<br/>", "<br/>", "<p>丙</p>")
        doomed = find_legacy_br(japanese, chinese)
        self.assertEqual(doomed, [7, 8, 9])
        self.assertTrue(all(i + 1 > 6 for i in doomed))


if __name__ == "__main__":
    unittest.main()
