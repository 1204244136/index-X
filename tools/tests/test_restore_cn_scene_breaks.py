from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from restore_cn_scene_breaks import plan  # noqa: E402

HEAD = ['<?xml version="1.0" encoding="UTF-8"?>', "<!DOCTYPE html>",
        '<html xmlns="http://www.w3.org/1999/xhtml"><head></head><body class="p-text">',
        "<h1>第一章</h1>", "<h2>１</h2>"]


def jp(*lines: str) -> list[str]:
    return HEAD + list(lines)


class RestoreSceneBreakTests(unittest.TestCase):
    def test_inserts_br_at_jp_positions_and_matches_length(self):
        japanese = jp("<p>甲。</p>", "<br/>", "<p>乙。</p>", "<br/>", "<p>丙。</p>")
        chinese = jp("<p>A。</p>", "<p>B。</p>", "<p>C。</p>")
        out, reason = plan(japanese, chinese)
        self.assertEqual(reason, "")
        self.assertEqual(out, chinese[:5] + ["<p>A。</p>", "<br/>", "<p>B。</p>",
                                             "<br/>", "<p>C。</p>"])
        self.assertEqual(len(out), len(japanese))

    def test_existing_chinese_br_positions_are_reproduced_unchanged(self):
        """幂等：已补过的文件再跑一次不产生变化。"""
        japanese = jp("<p>甲。</p>", "<br/>", "<p>乙。</p>")
        chinese = jp("<p>A。</p>", "<br/>", "<p>B。</p>")
        out, reason = plan(japanese, chinese)
        self.assertEqual(reason, "")
        self.assertEqual(out, chinese)

    def test_refuses_when_content_line_kinds_differ(self):
        """段落/标题结构不同 → 拒绝，绝不靠插删行硬凑。"""
        japanese = jp("<p>甲。</p>", "<br/>", "<h2>２</h2>", "<p>乙。</p>")
        chinese = jp("<p>A。</p>", "<p>B。</p>")          # 缺一个 h2 内容行
        out, reason = plan(japanese, chinese)
        self.assertIsNone(out)
        self.assertIn("行类型序列不同", reason)

    def test_refuses_when_chinese_has_more_br_than_japanese(self):
        japanese = jp("<p>甲。</p>", "<p>乙。</p>")
        chinese = jp("<p>A。</p>", "<br/>", "<p>B。</p>")
        out, reason = plan(japanese, chinese)
        self.assertIsNone(out)
        self.assertIn("不擅自搬动", reason)

    def test_refuses_when_lengths_still_differ_after_insert(self):
        """br 数量不足以解释差值（还存在段落合并等别的差异）→ 拒绝。"""
        japanese = jp("<p>甲。</p>", "<br/>", "<p>乙。</p>", "<p>丙。</p>")
        chinese = jp("<p>A。</p>")          # 中文并成了 1 段
        out, reason = plan(japanese, chinese)
        self.assertIsNone(out)

    def test_head_lines_are_taken_from_chinese_untouched(self):
        """L1-L5 必须保留中文侧自己的头部（含其 h2 id/class），只重建正文区。"""
        japanese = jp("<p>甲。</p>", "<br/>", "<p>乙。</p>")
        chinese = ['<?xml version="1.0" encoding="utf-8"?>', "<!DOCTYPE html>",
                   '<html lang="zh"><body>', "<h1 class=\"t\">第一章</h1>",
                   '<h2 id="toc_1">1</h2>', "<p>A。</p>", "<p>B。</p>"]
        out, reason = plan(japanese, chinese)
        self.assertEqual(reason, "")
        self.assertEqual(out[:5], chinese[:5])


if __name__ == "__main__":
    unittest.main()
