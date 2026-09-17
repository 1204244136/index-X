from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import check_epub_health  # noqa: E402
from check_epub_health import audit_book  # noqa: E402

HEAD = "<?xml version='1.0' encoding='utf-8'?>"
DOCT = "<!DOCTYPE html>"
BODY_OPEN = ('<html xmlns="http://www.w3.org/1999/xhtml">'
             '<head><title>t</title></head><body>')

GOOD = [
    HEAD,
    DOCT,
    BODY_OPEN,
    "<h1>第一章</h1>",
    "",
    "<p>正文首行。</p>",
    "<p>第二段<b>加粗文字</b>与<ruby>注音<rt>zhu yin</rt></ruby>。</p>",
    "</body></html>",
]


def body(*tail: str) -> list[str]:
    """固定行模板的正确头部 + 指定正文行。"""
    return GOOD[:6] + list(tail) + ["</body></html>"]


class HealthCheckNegativeTests(unittest.TestCase):
    """体检类工具最大的风险不是漏报，而是**永远报 0**（判定写错、路径没匹配上、
    正则静默失配）却看上去一切正常。每个检查项都要有一个能触发它的最小反例。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def build(self, bid: str, files: dict[str, list[str]], root: Path | None = None) -> Path:
        book = (root or self.tmp) / ("[%s]测试书" % bid)
        for rel, lines in files.items():
            path = book / Path(rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix.lower() in (".jpg", ".png"):
                path.write_bytes(b"\xff\xd8\xff")
            else:
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return book

    def assert_detects(self, check: str, bid: str, files: dict[str, list[str]]):
        book = self.build(bid, files)
        findings, counts, _exempt, _cov = audit_book(book, {check})
        hits = [f for f in findings if f[0] == check]
        self.assertGreaterEqual(
            counts.get(check, 0), 1,
            "检查项 %s 未检出缺陷；findings=%s" % (check, findings))
        self.assertIn(check, {f[0] for f in hits})
        return hits[0]

    # ---- 正常样本不得误报 ----
    def test_clean_sample_reports_nothing(self):
        book = self.build("S1_01", {"OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD})
        findings, counts, _exempt, covered = audit_book(book, None)
        self.assertEqual(findings, [])
        self.assertEqual(sum(counts.values()), 0)
        self.assertEqual(covered["files"], 1)

    # ---- 每个检查项一个反例 ----
    def test_xml_parse_failure(self):
        hit = self.assert_detects("XML", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD[:3] + ["<h1>未闭合"] + GOOD[4:],
        })
        self.assertIn("XML 解析失败", hit[5])

    def test_img_without_src(self):
        hit = self.assert_detects("XML", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": body('<p><img alt="x"/></p>'),
        })
        self.assertIn("缺 src", hit[5])

    def test_template_and_body_atomicity(self):
        hit = self.assert_detects("template", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD[:3] + ["", "", "<p>a</p><p>b</p>",
                                                             "</body></html>"],
        })
        self.assertIn("同一物理行包含多个正文块", hit[5])

    def test_bold_contains_punctuation(self):
        hit = self.assert_detects("bold-punct", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": body("<p><b>住手，你</b>听我说。</p>"),
        })
        self.assertIn("住手，你", hit[5])

    def test_bold_punctuation_protects_entities_and_ids(self):
        """与每日 CI 同源：XML 实体、作品号、缩写点不得被误判为标点。"""
        for line in ("<p><b>R&amp;C</b>项目</p>",
                     "<p><b>[S5_01_01]</b>标识</p>",
                     "<p>Mr.<b>秘技酱</b></p>",
                     "<p><b>3.5</b>倍</p>"):
            _new, hits = check_epub_health.split_bold_punct(line)
            self.assertEqual(hits, [], "不应命中：%s" % line)

    def test_empty_bold(self):
        hit = self.assert_detects("bold-empty", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": body("<p><b></b>空白加粗。</p>"),
        })
        self.assertIn("<b></b>", hit[5])

    def test_bold_not_closed(self):
        # 用自闭合 `<b/>` 构造「开标签多于闭标签」：XML 合法（否则会先被 XML 项拦掉），
        # 但 `<b` 计数为 2、`</b>` 计数为 1，正是要检的失衡。
        hit = self.assert_detects("bold-pair", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": body("<p><b/>只有开标签。<b>另一个</b></p>"),
        })
        self.assertIn("2 个 / `</b>` 1 个", hit[5])

    def test_ruby_without_rt(self):
        hit = self.assert_detects("ruby", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": body("<p><ruby>无注音</ruby>。</p>"),
        })
        self.assertIn("缺 `<rt>`", hit[5])

    def test_zero_content_sequence(self):
        hit = self.assert_detects("seq-00", "S1_01", {
            "OEBPS/Text/S1_01-00_Prologue.xhtml": GOOD,
        })
        self.assertIn("-00", hit[5])

    def test_duplicate_header(self):
        hit = self.assert_detects("dup-header", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD,
            "OEBPS/Text/S1_01-01_Chapter1_dup.xhtml": GOOD,
        })
        self.assertIn("出现 2 次", hit[5])

    def test_content_sequence_gap(self):
        hit = self.assert_detects("seq-gap", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD,
            "OEBPS/Text/S1_01-03_Chapter2.xhtml": GOOD,
        })
        self.assertIn("缺号", hit[5])

    def test_image_without_work_id_prefix(self):
        hit = self.assert_detects("img-prefix", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD,
            "OEBPS/Images/i-030.jpg": [],
        })
        self.assertIn("i-030.jpg", hit[5])

    def test_dangling_resource_reference(self):
        hit = self.assert_detects("dangling", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": body(
                '<p><img src="../Images/S1_01-missing.jpg" alt="x"/></p>'),
        })
        self.assertIn("不存在", hit[5])

    def test_dangling_anchor_reference(self):
        hit = self.assert_detects("dangling", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": body(
                '<p><a href="S1_01-01_Chapter1.xhtml#nope">x</a></p>'),
        })
        self.assertIn("#nope", hit[5])

    # ---- 豁免与 --only ----
    def test_exempt_books_suppress_template_only(self):
        """豁免按「书 + 检查项」：豁免 template 不等于豁免这本书的全部检查。

        名单本体在 `alignment_rules.TEMPLATE_EXEMPT_WORK_IDS`（与 check_alignment
        共用），所以这里直接改那个集合，验证两边确实是同一份。
        """
        import alignment_rules

        book = self.build("S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD[:3] + ["", "", "<p>a</p><p>b</p>",
                                                             "</body></html>"],
        })
        with patch.object(alignment_rules, "TEMPLATE_EXEMPT_WORK_IDS",
                          frozenset({"S1_01"})):
            findings, counts, exempted, _cov = audit_book(book, {"template"})
            self.assertEqual(findings, [])
            self.assertEqual(exempted.get("template"), 1)
        # 同一本书的其它检查项不受豁免影响
        book2 = self.build("S1_01", {
            "OEBPS/Text/S1_01-02_Chapter2.xhtml": body("<p><b>住手，你</b>听我说。</p>"),
        })
        findings2, counts2, _e2, _c2 = audit_book(book2, {"bold-punct"})
        self.assertEqual(counts2.get("bold-punct"), 1)
        self.assertTrue(findings2)

    def test_real_exempt_works_are_the_reviewed_three(self):
        """名单是「已裁定不纳入模板检查」的三本，不是随手积累的忽略项。"""
        import alignment_rules
        self.assertEqual(
            alignment_rules.TEMPLATE_EXEMPT_WORK_IDS,
            frozenset({"S0_00", "S6_10.06.26", "S6_24.12.10"}))
        self.assertTrue(alignment_rules.template_exempt("S0_00"))
        self.assertTrue(alignment_rules.template_exempt("s6_10.06.26"))
        self.assertFalse(alignment_rules.template_exempt("S1_01"))
        self.assertFalse(alignment_rules.template_exempt(None))

    def test_only_restricts_checks(self):
        book = self.build("S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": body("<p><b>住手，你</b>听我说。</p>"),
        })
        _f, counts, _e, _c = audit_book(book, {"bold-punct"})
        self.assertEqual(set(counts) - {"bold-punct"}, set())

    def test_strict_exit_code_follows_error_severity(self):
        clean = self.tmp / "clean"
        broken = self.tmp / "broken"
        clean.mkdir()
        broken.mkdir()
        self.build("S1_01", {"OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD}, root=clean)
        self.build("S1_01",
                   {"OEBPS/Text/S1_01-01_Chapter1.xhtml":
                    GOOD[:3] + ["<h1>未闭合"] + GOOD[4:]},
                   root=broken)

        with patch.object(sys, "argv", ["check_epub_health.py", "--root", str(clean),
                                        "--strict"]):
            self.assertEqual(check_epub_health.main(), 0)
        with patch.object(sys, "argv", ["check_epub_health.py", "--root", str(broken),
                                        "--strict"]):
            self.assertEqual(check_epub_health.main(), 1)

    def test_broken_xml_skips_line_level_checks(self):
        """解析失败时行级检查没有可信输入：只报 XML，不报噪声。"""
        book = self.build("S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml":
                GOOD[:3] + ["<h1>未闭合"] + GOOD[4:] + ["<p><b>住手，你</b></p>"],
        })
        _f, counts, _e, _c = audit_book(book, None)
        self.assertEqual(counts.get("XML"), 1)
        self.assertEqual(counts.get("bold-punct", 0), 0)

    def test_unknown_check_name_is_rejected(self):
        with patch.object(sys, "argv", ["check_epub_health.py", "--only", "nope"]):
            with self.assertRaises(SystemExit):
                check_epub_health.main()


if __name__ == "__main__":
    unittest.main()
