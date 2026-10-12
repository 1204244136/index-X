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

    @staticmethod
    def page(title: str) -> list[str]:
        """作品级包装页的最小合规形态（同样是 L4 标题 / L5 空行 / L6 正文首行）。"""
        return GOOD[:3] + ["<h1>%s</h1>" % title, "", "<p>%s占位。</p>" % title, "</body></html>"]

    def build(self, bid: str, files: dict[str, list[str]], root: Path | None = None) -> Path:
        """造一本**构成合规**的最小书：目录名带 X，且有包文档／导航／NCX／封面／制作信息页。

        构成规则见 `docs/epub-artifact-spec.md`。`assert_detects` 只跑单个检查项，
        多数用例不依赖这些默认件；`test_clean_sample_reports_nothing` 要求整本书在
        **全部**检查项下零命中，所以默认件本身必须是合规形态。
        """
        from docx2epub import _CSS
        files = dict(files)
        files.setdefault("OEBPS/Styles/style.css", [_CSS])
        files.setdefault("OEBPS/Text/%s-Cover.xhtml" % bid, self.page("封面"))
        files.setdefault("OEBPS/Text/%s-Information.xhtml" % bid, self.page("制作信息"))
        dir_name = "[%s]测试书X" % bid
        rels = sorted(rel for rel in files if rel.startswith("OEBPS/Text/"))
        items, refs = [], []
        for i, rel in enumerate(rels, 1):
            items.append('    <item id="id%d" href="%s" media-type="application/xhtml+xml"/>'
                         % (i, rel.split("OEBPS/", 1)[1]))
            refs.append('    <itemref idref="id%d"/>' % i)
        files["OEBPS/content.opf"] = [
            HEAD,
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId">',
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">',
            '    <dc:title id="id">%s</dc:title>' % dir_name,
            '    <dc:identifier id="BookId">uuid:test-%s</dc:identifier>' % bid,
            "    <dc:language>zh-CN</dc:language>",
            "  </metadata>",
            "  <manifest>", *items, "  </manifest>",
            '  <spine toc="ncx">', *refs, "  </spine>",
            "</package>",
        ]
        files["nav.xhtml"] = [
            "<!DOCTYPE html>",
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">',
            "<head><title>Navigation</title></head>",
            "<body>", '<nav epub:type="toc">', "<ol>",
            '<li><a href="OEBPS/Text/%s-Information.xhtml">制作信息</a></li>' % bid,
            "</ol>", "</nav>", "</body></html>",
        ]
        files["toc.ncx"] = [
            HEAD,
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="zh">',
            "  <docTitle>", "    <text>%s</text>" % dir_name, "  </docTitle>",
            "  <navMap>",
            '    <navPoint id="num_1" playOrder="1">',
            "      <navLabel>", "        <text>制作信息</text>", "      </navLabel>",
            '      <content src="OEBPS/Text/%s-Information.xhtml"/>' % bid,
            "    </navPoint>",
            "  </navMap>",
            "</ncx>",
        ]
        book = (root or self.tmp) / dir_name
        for rel, lines in files.items():
            path = book / Path(rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix.lower() in (".jpg", ".png"):
                path.write_bytes(b"\xff\xd8\xff")
            else:
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return book

    def test_book_without_css_fails_layout_gate(self):
        book = self.build("S1_01", {"OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD})
        (book / "OEBPS/Styles/style.css").unlink()
        findings, *_ = audit_book(book, {"css-layout"})
        self.assertTrue(any("缺少主样式表" in f[5] for f in findings))

    def assert_detects(self, check: str, bid: str, files: dict[str, list[str]]):
        book = self.build(bid, files)
        findings, counts, _exempt, _cov = audit_book(book, {check})
        hits = [f for f in findings if f[0] == check]
        self.assertGreaterEqual(
            counts.get(check, 0), 1,
            "检查项 %s 未检出缺陷；findings=%s" % (check, findings))
        self.assertIn(check, {f[0] for f in hits})
        return hits[0]

    # ---- 成品构成（docs/epub-artifact-spec.md）----
    def test_dir_name_without_version_marker(self):
        book = self.build("S1_01", {"OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD})
        renamed = book.parent / "[S1_01]测试书"
        book.rename(renamed)
        findings, counts, _e, _c = audit_book(renamed, {"dir-name"})
        self.assertGreaterEqual(counts.get("dir-name", 0), 1)
        self.assertTrue(any("未以版本标记 `X` 结尾" in f[5] for f in findings))

    def test_dir_name_without_work_id_prefix(self):
        book = self.build("S1_01", {"OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD})
        renamed = book.parent / "测试书X"
        book.rename(renamed)
        findings, counts, _e, _c = audit_book(renamed, {"dir-name"})
        self.assertTrue(any("缺少 `[作品号]` 前缀" in f[5] for f in findings))

    def test_metadata_title_must_equal_dir_name(self):
        book = self.build("S1_01", {"OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD})
        opf = book / "OEBPS/content.opf"
        opf.write_text(opf.read_text(encoding="utf-8").replace("[S1_01]测试书X", "某魔法的禁书目录 01X"),
                       encoding="utf-8")
        findings, counts, _e, _c = audit_book(book, {"metadata-title"})
        self.assertEqual(counts.get("metadata-title"), 1)
        self.assertIn("与书目录名不一致", findings[0][5])

    def test_missing_information_page_is_blocking(self):
        book = self.build("S1_01", {"OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD})
        (book / "OEBPS/Text/S1_01-Information.xhtml").unlink()
        findings, counts, _e, _c = audit_book(book, {"packaging-required"})
        self.assertTrue(any("缺少必备包装页" in f[5] and "Information" in f[5] for f in findings))

    def test_packaging_page_must_be_declared_and_in_spine(self):
        book = self.build("S1_01", {"OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD})
        opf = book / "OEBPS/content.opf"
        opf.write_text(opf.read_text(encoding="utf-8").replace(
            "Text/S1_01-Information.xhtml", "Text/S1_01-Elsewhere.xhtml"), encoding="utf-8")
        findings, counts, _e, _c = audit_book(book, {"packaging-required"})
        self.assertTrue(any("未在 manifest 中声明" in f[5] for f in findings))
        self.assertTrue(any("未进 spine" in f[5] for f in findings))

    def test_toc_first_entry_and_cover_entry(self):
        book = self.build("S1_01", {"OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD})
        ncx = book / "toc.ncx"
        ncx.write_text(ncx.read_text(encoding="utf-8").replace(
            "<text>制作信息</text>", "<text>封面</text>"), encoding="utf-8")
        findings, counts, _e, _c = audit_book(book, {"toc-entry"})
        self.assertTrue(any("首条目应为「制作信息」" in f[5] for f in findings))
        self.assertTrue(any("封面不进目录" in f[5] for f in findings))
        # 存量清零后由报告级升级为阻断（2026-10-12，见 docs/maintenance-records/）
        self.assertTrue(all(f[4] == "error" for f in findings))

    def test_ncx_doctitle_must_match_dc_title(self):
        book = self.build("S1_01", {"OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD})
        ncx = book / "toc.ncx"
        ncx.write_text(ncx.read_text(encoding="utf-8").replace(
            "<text>[S1_01]测试书X</text>", "<text>某魔法的禁书目录 01X</text>"), encoding="utf-8")
        findings, counts, _e, _c = audit_book(book, {"ncx-doctitle"})
        self.assertEqual(counts.get("ncx-doctitle"), 1)
        self.assertIn("`docTitle` 与 `dc:title` 不一致", findings[0][5])
        # 存量清零后由报告级升级为阻断（2026-10-12，见 docs/maintenance-records/）
        self.assertEqual(findings[0][4], "error")

    def test_identifier_duplicates_across_books(self):
        a = self.build("S1_01", {"OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD})
        b = self.build("S1_02", {"OEBPS/Text/S1_02-01_Chapter1.xhtml": GOOD})
        self.assertEqual(check_epub_health.find_identifier_duplicates([a, b]), [])
        opf_a = a / "OEBPS/content.opf"
        shared = opf_a.read_text(encoding="utf-8").split('id="BookId">')[1].split("<")[0]
        opf_b = b / "OEBPS/content.opf"
        text = opf_b.read_text(encoding="utf-8")
        opf_b.write_text(text.replace(text.split('id="BookId">')[1].split("<")[0], shared),
                         encoding="utf-8")
        hits = check_epub_health.find_identifier_duplicates([a, b])
        self.assertEqual(len(hits), 2)
        self.assertTrue(all("共用" in msg for _name, msg in hits))
        # 存量清零后由报告级升级为阻断（2026-10-12，见 docs/maintenance-records/）
        self.assertEqual(check_epub_health.SEVERITY["identifier-unique"], "error")

    def test_artifact_exempt_registry_is_narrow(self):
        import alignment_rules
        self.assertEqual(set(alignment_rules.HEALTH_EXEMPT_WORK_IDS),
                         {"dir-name", "toc-entry"})
        self.assertTrue(alignment_rules.health_exempt("dir-name", "S0_00"))
        self.assertTrue(alignment_rules.health_exempt("toc-entry", "s0_00"))
        self.assertFalse(alignment_rules.health_exempt("ncx-doctitle", "S0_00"))
        self.assertFalse(alignment_rules.health_exempt("metadata-title", "S0_00"))
        self.assertFalse(alignment_rules.health_exempt("dir-name", "S1_01"))
        self.assertFalse(alignment_rules.health_exempt("dir-name", None))

    # ---- 正常样本不得误报 ----
    def test_clean_sample_reports_nothing(self):
        book = self.build("S1_01", {"OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD})
        findings, counts, _exempt, covered = audit_book(book, None)
        self.assertEqual(findings, [])
        self.assertEqual(sum(counts.values()), 0)
        self.assertEqual(covered["files"], 3)  # 正文 + 封面 + 制作信息

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
        """名单是「已裁定不纳入模板检查」的两本，不是随手积累的忽略项。

        `S6_24.12.10` 曾在名单里（日文侧画集无 BW 分页源）；该作品补齐日文侧、
        恢复常规配对后登记已移除（见 `alignment_rules` 中该条注释与提交
        `cd2b7012`），因此这里只断言现存的两本。
        """
        import alignment_rules
        self.assertEqual(
            alignment_rules.TEMPLATE_EXEMPT_WORK_IDS,
            frozenset({"S0_00", "S6_10.06.26"}))
        self.assertTrue(alignment_rules.template_exempt("S0_00"))
        self.assertTrue(alignment_rules.template_exempt("s6_10.06.26"))
        self.assertFalse(alignment_rules.template_exempt("S6_24.12.10"))
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

    def test_css_layout_negative_tests(self):
        # 1. 缺失 box-sizing
        hit1 = self.assert_detects("css-layout", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD,
            "OEBPS/Styles/style.css": ["body { margin: 0; }", ".pb {}", ".fit { display: block; break-inside: avoid; }"],
        })
        self.assertIn("box-sizing", hit1[5])

        # 2. 包含破坏性左右百分比边距
        hit2 = self.assert_detects("css-layout", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD,
            "OEBPS/Styles/style.css": ["* { box-sizing: border-box; }", "body { margin-left: 1%; }", ".pb {}", ".fit { display: block; break-inside: avoid; }"],
        })
        self.assertIn("百分比左右边距", hit2[5])

        # 3. 缺失 .pb 声明
        hit3 = self.assert_detects("css-layout", "S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD,
            "OEBPS/Styles/style.css": ["* { box-sizing: border-box; }", "body { margin: 0; }", ".fit { display: block; break-inside: avoid; }"],
        })
        css_book = self.tmp / "[S1_01]测试书X"
        hits, *_ = audit_book(css_book, {"css-layout"})
        self.assertTrue(any("`.pb`" in f[5] for f in hits))

    def test_css_urls_imports_and_nav_links_are_checked(self):
        book = self.build("S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD,
            "OEBPS/nav.xhtml": ['<html><body><a href="missing.xhtml">目录</a></body></html>'],
            "OEBPS/Styles/font.css": ['/* url(ignored.png) */',
                                      '@import "missing.css";',
                                      '@font-face {src:url("missing font.woff");}'],
        })
        hits = check_epub_health.find_dangling(book, check_epub_health.collect_xhtml(book))
        self.assertEqual(len(hits), 3)
        self.assertFalse(any("ignored.png" in message for _, message in hits))

    def test_auxiliary_css_cannot_override_main_layout(self):
        from docx2epub import _CSS
        book = self.build("S1_01", {
            "OEBPS/Text/S1_01-01_Chapter1.xhtml": GOOD,
            "OEBPS/Styles/style.css": [_CSS],
            "OEBPS/Styles/override.css": ['body {margin:0 1%;}'],
        })
        hits = check_epub_health.find_css_layout_problems(book)
        self.assertTrue(any("override.css" in message for _, message in hits))
        self.assertFalse(any("`OEBPS/Styles/style.css`" in message for _, message in hits))

    def test_layout_checks_values_and_selector_scope(self):
        from docx2epub import _CSS
        book = self.build("S1_01", {"OEBPS/Styles/style.css": [_CSS]})
        self.assertEqual(check_epub_health.find_css_layout_problems(book), [])
        css = book / "OEBPS/Styles/style.css"
        for old, new, marker in [
            ("box-sizing: border-box", "box-sizing: content-box", "box-sizing"),
            ("break-before: column", "break-before: auto", "break-before"),
            ("break-inside: avoid", "break-inside: auto", "break-inside"),
            ("text-indent: 0", "text-indent: 2em", "text-indent"),
        ]:
            with self.subTest(marker=marker):
                css.write_text(_CSS.replace(old, new), encoding="utf-8")
                hits = check_epub_health.find_css_layout_problems(book)
                self.assertTrue(any(marker in message for _, message in hits))

    def test_unknown_check_name_is_rejected(self):
        with patch.object(sys, "argv", ["check_epub_health.py", "--only", "nope"]):
            with self.assertRaises(SystemExit):
                check_epub_health.main()


if __name__ == "__main__":
    unittest.main()
