from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import check_alignment  # noqa: E402


def xhtml(body_lines: list[str]) -> str:
    return "\n".join([
        "<?xml version='1.0' encoding='utf-8'?>",
        "<!DOCTYPE html>",
        "<html><head></head><body>",
        "<h1>章</h1>",
        "",
        *body_lines,
        "</body></html>",
        "",
    ])


class AlignmentTests(unittest.TestCase):
    def test_body_lines_must_be_atomic(self):
        adjacent = xhtml(["<p>一</p><p>二</p>"]).splitlines()
        footer = xhtml(["<p>一</p><hr/>"]).splitlines()
        content_close = xhtml(["<p>一</p></body></html>"]).splitlines()
        self.assertIn(
            "L6 同一物理行包含多个正文块",
            check_alignment.check_file(adjacent),
        )
        self.assertIn(
            "L6 同一物理行包含多个正文块",
            check_alignment.check_file(footer),
        )
        self.assertIn(
            "L6 正文与 body 闭标签同行",
            check_alignment.check_file(content_close),
        )

    def test_pair_difference_is_a_problem_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            cn = cache / "chinese-text" / "[S1_01]中" / "OEBPS" / "Text"
            jp = cache / "japanese-text" / "[S1_01]日" / "OEBPS" / "Text"
            cn.mkdir(parents=True)
            jp.mkdir(parents=True)
            (cn / "S1_01-01_Chapter1.xhtml").write_text(
                xhtml(["<p>一</p>"]), encoding="utf-8"
            )
            (jp / "S1_01-01_p-001.xhtml").write_text(
                xhtml(["<p>一</p>", "<p>二</p>"]), encoding="utf-8"
            )
            with patch.object(sys, "argv", ["check_alignment.py", "--cache", str(cache)]):
                self.assertEqual(check_alignment.main(), 0)
            report = (cache / "alignment-check.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("配对差异", report)
            self.assertIn("行数", report)
            with patch.object(
                sys,
                "argv",
                ["check_alignment.py", "--cache", str(cache), "--strict"],
            ):
                self.assertEqual(check_alignment.main(), 1)

    def test_standalone_br_positions_must_match(self):
        japanese = xhtml(["<p>一</p>", "<br/>", "<p>二</p>"]).splitlines()
        chinese = xhtml(["<br/>", "<p>一</p>", "<p>二</p>"]).splitlines()
        problems = check_alignment.pair_problems("S1_01-01", japanese, chinese)
        self.assertIn("<br/> 位置 JP[7] vs CN[6]", problems)

    def test_textual_image_headers_exempt_br_positions(self):
        japanese = xhtml(["<p>一</p>", "<br/>", "<p>二</p>"]).splitlines()
        chinese = xhtml(["<br/>", "<p>一</p>", "<p>二</p>"]).splitlines()
        problems = check_alignment.pair_problems("S2_14-04", japanese, chinese)
        self.assertFalse(any(problem.startswith("<br/> 位置") for problem in problems))


if __name__ == "__main__":
    unittest.main()
