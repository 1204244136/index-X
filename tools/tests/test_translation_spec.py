from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import check_translation_spec as cts  # noqa: E402

HEAD = "<?xml version='1.0' encoding='utf-8'?>"
DOCT = "<!DOCTYPE html>"
BODY_OPEN = ('<html xmlns="http://www.w3.org/1999/xhtml">'
             '<head><title>t</title></head><body>')


def p9_pattern():
    return [rx for rx, cat, _sev, _msg in cts.CHECK_TEXT if cat == "P9"][0]


class P9EventNameExemptionTests(unittest.TestCase):
    """P9 对「赛事项目名 + 公里」放行，但仍须抓住一般距离/时速里的「公里」「公斤」。

    豁免是负向先行断言：最容易出的错是**豁免写宽了**，把真缺陷一起放掉，
    报告看起来变干净了、其实漏报。所以正反两侧都要有最小用例。
    """

    def test_event_names_exempt(self):
        rx = p9_pattern()
        for s in ("十公里长跑的指定路线",
                  "十公里长跑无法通行",
                  "十公里赛跑",
                  "五公里路跑",
                  "二十公里越野",
                  "十公里马拉松"):
            with self.subTest(s=s):
                self.assertIsNone(rx.search(s), "赛事项目名不应命中 P9：%s" % s)

    def test_plain_units_still_flagged(self):
        rx = p9_pattern()
        for s in ("直径达十公里左右的学艺都市外周",
                  "距离约十公里",
                  "五公斤重",
                  "以公里为单位"):
            with self.subTest(s=s):
                self.assertIsNotNone(rx.search(s), "一般单位用法仍应命中 P9：%s" % s)

    def test_suffix_list_is_the_documented_closed_set(self):
        """词表是封闭集合：改动必须同步 docs/translation-spec.md 与译名裁定总表。"""
        self.assertEqual(
            cts.P9_EVENT_SUFFIXES,
            ("长跑", "赛跑", "路跑", "马拉松", "竞走", "接力", "越野", "健走", "徒步"),
        )


class P9EndToEndTests(unittest.TestCase):
    """端到端跑一遍 main()：确认豁免在整条管线里生效，而不只是正则层面。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.cache = self.tmp / "cache"
        self.out = self.tmp / "out"

    def build_book(self, paragraphs):
        text_dir = self.cache / "[S1_10]测试书" / "OEBPS" / "Text"
        text_dir.mkdir(parents=True, exist_ok=True)
        lines = [HEAD, DOCT, BODY_OPEN, "<h1>第一章</h1>", ""]
        lines += ["<p>%s</p>" % p for p in paragraphs]
        lines.append("</body></html>")
        (text_dir / "S1_10-07_Chapter8.xhtml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_checker(self):
        argv = sys.argv
        sys.argv = ["check_translation_spec.py",
                    "--cache", str(self.cache), "--output", str(self.out)]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                cts.main()
        finally:
            sys.argv = argv
        tsv = (self.out / "translation-spec-check.tsv").read_text(encoding="utf-8")
        return [ln for ln in tsv.splitlines() if "\tP9\t" in ln]

    def test_event_name_not_reported_but_distance_is(self):
        self.build_book([
            "这附近的路好像是十公里长跑的指定路线。",
            "整体直径达十公里左右的都市外周。",
        ])
        hits = self.run_checker()
        self.assertEqual(len(hits), 1, "应只报一般距离那一处，实得：%r" % (hits,))
        # 只比 example 列：message 里本身带「十公里长跑」这个示例词
        example = hits[0].split("\t")[-1]
        self.assertIn("十公里左右", example)
        self.assertNotIn("十公里长跑", example)

    def test_clean_book_reports_no_p9(self):
        self.build_book(["这附近的路好像是十公里长跑的指定路线。"])
        self.assertEqual(self.run_checker(), [])


if __name__ == "__main__":
    unittest.main()
