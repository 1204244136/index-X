from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from bw_preprocess import (  # noqa: E402
    apply_entry_renames,
    apply_rules,
    artifact_contract_issues,
    check_dir,
    epub_zip_issues,
    is_content,
    is_epilogue_story_page,
    is_reading_notice,
    load_header_map,
    load_rules,
    page_map_contract_issues,
    pairing_header_renames,
    template_issues,
)


RULES = load_rules(None)


def raw_page(body_lines: list[str], *, body_class: str = "p-text") -> str:
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE html>",
        "<html",
        ' xmlns="http://www.w3.org/1999/xhtml"',
        ' xmlns:epub="http://www.idpf.org/2007/ops"',
        ' xml:lang="ja"',
        ' class="vrtl"',
        ">",
        "<head>",
        '<meta charset="UTF-8"/>',
        "<title>测试</title>",
        '<link rel="stylesheet" type="text/css" href="../style/book-style.css"/>',
        "</head>",
        f'<body class="{body_class}">',
        '<div class="main">',
        *body_lines,
        "</div>",
        "</body>",
        "</html>",
    ])


def merged_page(body_lines: list[str], *, body_class: str = "p-text") -> str:
    """merge_bw_pages 之后的章节文件形态：L3 折叠且不含 <div class="main">。"""
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE html>",
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ja">'
        '<head><title>测试</title></head>'
        f'<body class="{body_class}">',
        *body_lines,
        "</body></html>",
    ])


class BookWalkerTemplateTests(unittest.TestCase):
    def test_unprocessed_multiline_header_is_rejected(self):
        text = raw_page(["<p>正文</p>"])
        self.assertTrue(is_content(text))
        self.assertTrue(any(
            issue.startswith("L3 未折叠")
            for issue in template_issues(text.splitlines())
        ))

    def test_merged_contract_accepts_chapter_file_without_main_div(self):
        """合并后的章节文件没有 main 容器：--merged 契约下应当通过。"""
        lines = merged_page(["<h1>第一章</h1>", "", "<p>正文</p>", "<p>第二段</p>"]).splitlines()
        self.assertEqual(template_issues(lines, merged=True), [])

    def test_paged_contract_still_rejects_chapter_file_but_hints_merged(self):
        """默认分页契约必须继续拒绝缺 main 的文件（保护合并管线），同时给出可执行提示。"""
        lines = merged_page(["<h1>第一章</h1>", "", "<p>正文</p>"]).splitlines()
        issues = template_issues(lines)
        self.assertTrue(any(i.startswith("L3 未折叠") for i in issues), issues)
        self.assertTrue(any("--merged" in i for i in issues), issues)

    def test_merged_contract_still_checks_l4_to_l6(self):
        """放宽的只有 L3 的 main 锚点，L4-L6 与 XML 语法照样要查。"""
        bad = merged_page(["<p>误置的正文</p>", "", "<p>正文</p>"]).splitlines()
        issues = template_issues(bad, merged=True)
        self.assertTrue(any(i.startswith("L4") for i in issues), issues)

    def test_check_dir_honours_merged_contract(self):
        root = Path(tempfile.mkdtemp())
        try:
            (root / "S4_01-02.xhtml").write_text(
                merged_page(["<h1>第二章</h1>", "", "<p>正文</p>"]), encoding="utf-8")
            strict = check_dir(root, RULES)
            lenient = check_dir(root, RULES, merged=True)
            self.assertTrue(any(i.startswith("L3 未折叠") for _, i in strict["issues"]))
            self.assertEqual(lenient["issues"], [])
            self.assertEqual(lenient["content"], 1)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_cli_rejects_merged_without_directory_input(self):
        r = subprocess.run(
            [sys.executable, str(TOOLS / "bw_preprocess.py"), "--merged", "不存在.epub"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("--merged 只适用于目录输入", r.stderr)

    def test_untitled_page_gets_blank_header_slots_without_losing_body(self):
        source = raw_page(["<p>第一段</p>", "<p>第二段</p>"])
        result = apply_rules(source, RULES)
        lines = result.splitlines()
        self.assertIn('<div class="main">', lines[2])
        self.assertEqual(lines[3:7], ["", "", "<p>第一段</p>", "<p>第二段</p>"])
        self.assertEqual(template_issues(lines), [])
        self.assertEqual(apply_rules(result, RULES), result)

    def test_title_and_numeric_sections_become_h1_and_h2(self):
        source = raw_page([
            '<div class="start-3em">',
            '<p class="font-1em30" id="toc-001">第一章　标题</p>',
            "</div>",
            "<br/>",
            "<br/>",
            '<div class="start-5em">',
            "<p>１</p>",
            "</div>",
            "<br/>",
            "<p>第一段</p>",
            '<div class="start-5em"><p>２</p></div>',
            "<p>第二段</p>",
        ])
        result = apply_rules(source, RULES)
        lines = result.splitlines()
        self.assertEqual(
            lines[3],
            '<h1 class="font-1em30" id="toc-001">第一章　标题</h1>',
        )
        self.assertEqual(lines[4], "<h2>１</h2>")
        self.assertEqual(lines[5], "<p>第一段</p>")
        self.assertIn("<h2>２</h2>", lines)
        self.assertNotIn("start-3em", result)
        self.assertNotIn("start-5em", result)
        self.assertEqual(template_issues(lines), [])

    def test_title_without_first_subsection_keeps_empty_l5(self):
        source = raw_page([
            '<div class="start-3em">',
            '<p class="font-1em30">あとがき</p>',
            "</div>",
            "<br/>",
            "<br/>",
            "<p>正文</p>",
        ])
        lines = apply_rules(source, RULES).splitlines()
        self.assertEqual(lines[3], '<h1 class="font-1em30">あとがき</h1>')
        self.assertEqual(lines[4], "")
        self.assertEqual(lines[5], "<p>正文</p>")
        self.assertEqual(template_issues(lines), [])

    def test_malformed_xml_is_reported_after_template_conversion(self):
        result = apply_rules(raw_page(["<p>正文</p>"]), RULES)
        malformed = result.replace("</p>", "", 1)
        issues = template_issues(malformed.splitlines())
        self.assertTrue(any(issue.startswith("XML 解析失败：") for issue in issues))

    def test_pairing_headers_follow_h1_units_and_rewrite_references(self):
        intro = apply_rules(raw_page(["<p>引子</p>"]), RULES).encode()
        chapter = apply_rules(raw_page([
            '<div class="start-3em"><p class="font-1em30">序章</p></div>',
            "<p>正文</p>",
        ]), RULES).encode()
        continuation = apply_rules(raw_page(["<p>续页</p>"]), RULES).encode()
        entries = {
            "item/xhtml/p-001.xhtml": intro.replace(
                b'<p>\xe5\xbc\x95\xe5\xad\x90</p>',
                b'<p><img src="../image/i-030.jpg"/></p>',
            ),
            "item/xhtml/p-002.xhtml": chapter,
            "item/xhtml/p-003.xhtml": continuation,
            "item/xhtml/p-cover.xhtml": b"<html/>",
            "item/navigation-documents.xhtml": b'<a href="xhtml/p-002.xhtml"/>',
            "item/standard.opf": b'<item href="xhtml/p-001.xhtml"/>'
                                 b'<item href="xhtml/p-003.xhtml"/>'
                                 b'<item href="image/i-030.jpg"/>',
            "item/style/book-style.css": b'body{background:url("../image/i-030.jpg")}',
            "item/image/i-030.jpg": b"jpeg data",
        }
        renames = pairing_header_renames(entries, "S4_05")
        self.assertEqual(
            renames["item/xhtml/p-001.xhtml"],
            "item/xhtml/S4_05-01_p-001.xhtml",
        )
        self.assertEqual(
            renames["item/xhtml/p-002.xhtml"],
            "item/xhtml/S4_05-02_p-002.xhtml",
        )
        self.assertEqual(
            renames["item/xhtml/p-003.xhtml"],
            "item/xhtml/S4_05-02_p-003.xhtml",
        )
        self.assertNotIn("item/xhtml/p-cover.xhtml", renames)
        self.assertEqual(
            renames["item/image/i-030.jpg"],
            "item/image/S4_05-i-030.jpg",
        )
        rewritten = apply_entry_renames(entries, renames)
        self.assertIn("item/xhtml/S4_05-02_p-003.xhtml", rewritten)
        self.assertIn(b"S4_05-01_p-001.xhtml", rewritten["item/standard.opf"])
        self.assertIn(
            b"S4_05-02_p-002.xhtml",
            rewritten["item/navigation-documents.xhtml"],
        )
        self.assertIn(b"S4_05-i-030.jpg", rewritten["item/standard.opf"])
        self.assertIn(b"S4_05-i-030.jpg", rewritten["item/style/book-style.css"])

    def test_reading_notice_p001_is_wrapper_and_p002_starts_content_sequence(self):
        notice = apply_rules(raw_page([
            '<div class="font-080per"><p>※本書⑲巻は、⑮巻の続編です。</p></div>',
        ]), RULES).encode()
        prologue = apply_rules(raw_page([
            '<div class="start-3em"><p class="font-1em30">序章</p></div>',
            "<p>正文</p>",
        ]), RULES).encode()
        continuation = apply_rules(raw_page(["<p>续页</p>"]), RULES).encode()
        entries = {
            "item/xhtml/p-001.xhtml": notice,
            "item/xhtml/p-002.xhtml": prologue,
            "item/xhtml/p-003.xhtml": continuation,
        }

        self.assertTrue(is_reading_notice(notice.decode("utf-8")))
        self.assertFalse(is_content(notice.decode("utf-8")))
        renames = pairing_header_renames(entries, "S1_21")
        self.assertNotIn("item/xhtml/p-001.xhtml", renames)
        self.assertEqual(
            renames["item/xhtml/p-002.xhtml"],
            "item/xhtml/S1_21-01_p-002.xhtml",
        )
        self.assertEqual(
            renames["item/xhtml/p-003.xhtml"],
            "item/xhtml/S1_21-01_p-003.xhtml",
        )

    def test_audited_page_map_can_split_untitled_tail_and_exclude_wrappers(self):
        page = apply_rules(raw_page(["<p>正文</p>"]), RULES).encode()
        entries = {
            "item/xhtml/p-001.xhtml": page,
            "item/xhtml/p-002.xhtml": page,
            "item/xhtml/p-003.xhtml": b"<html/>",
        }
        page_map = {"p-001.xhtml": 8, "p-002.xhtml": 9, "p-003.xhtml": None}
        renames = pairing_header_renames(entries, "S4_05", page_map)
        self.assertEqual(
            renames["item/xhtml/p-001.xhtml"],
            "item/xhtml/S4_05-08_p-001.xhtml",
        )
        self.assertEqual(
            renames["item/xhtml/p-002.xhtml"],
            "item/xhtml/S4_05-09_p-002.xhtml",
        )
        self.assertNotIn("item/xhtml/p-003.xhtml", renames)
        rewritten = apply_entry_renames(entries, renames)
        self.assertEqual(
            page_map_contract_issues(rewritten, "S4_05", page_map), [])

    def test_single_paragraph_typography_container_folds_to_p(self):
        """白名单内的单段排版 div 容器折叠为带类名的 p，且幂等。"""
        for cls in ("align-end", "align-center", "align-right", "gfont",
                    "h-indent-1em", "h-indent-5em", "start-4em",
                    "font-1em30 start-2em"):
            src = f'<div class="{cls}">\n<p>一行正文</p>\n</div>'
            out = apply_rules(src, RULES)
            self.assertEqual(out, f'<p class="{cls}">一行正文</p>', cls)
            self.assertEqual(apply_rules(out, RULES), out, f"{cls} 折叠后非幂等")

    def test_multi_paragraph_container_is_never_folded(self):
        """容器内含两段以上时必须原样保留——折叠会把两段并成一行，破坏行原子性。

        旧版规则用惰性 `(.*?)` + dot_all，会把 `<p>甲</p>\\n<p>乙</p>` 连同
        `</div>` 一起吞掉，只给首段套上容器类名（后续段落丢失对齐语义）。
        """
        src = '<div class="align-end">\n<p>甲</p>\n<p>乙</p>\n</div>'
        out = apply_rules(src, RULES)
        self.assertEqual(out, src, "多段容器不应被改写")
        self.assertEqual(out.count("</p>"), 2)
        self.assertEqual(out.splitlines()[0], '<div class="align-end">')
        self.assertNotIn('<p class="align-end">', out)

    def test_container_with_attributed_paragraph_is_not_folded(self):
        """内层 <p> 自带属性时不折叠，避免造出重复 class/丢失属性。"""
        src = '<div class="align-center">\n<p class="note">正文</p>\n</div>'
        out = apply_rules(src, RULES)
        self.assertIn('<p class="note">正文</p>', out)
        self.assertNotIn('class="align-center note"', out)

    def test_fold_runs_before_image_padding_br_cleanup_and_is_stable(self):
        """幂等回归：折叠后紧邻的填充 <br/> 必须在同一趟被清掉。

        折叠规则一旦排在「图片前/后填充br清理」之后，第一遍会留下 <br/>、
        第二遍才删，行数随重跑漂移（S1_14-02 实测差 3 行）。
        """
        src = ('<p>前段</p>\n<br/>\n'
               '<div class="align-center">\n'
               '<p><img class="fit" src="../image/a.jpg" alt=""/></p>\n'
               '</div>\n<br/>\n<p>后段</p>')
        once = apply_rules(src, RULES)
        self.assertEqual(apply_rules(once, RULES), once, "两遍结果不同")
        self.assertNotIn("<br/>", once)
        self.assertIn('<p class="align-center"><img', once)

    def test_backmatter_boundary_closes_epilogue_for_good(self):
        """后记之后遇到纯插图页即进入书末附录：其后的文本页不得再算尾声。

        回归 S1_15：p-012 あとがき → p-013/014/015 著者近影纯图页 →
        p-016 著者/插画师介绍页。p-016 曾被当作「尾声」而拿到 -11。
        """
        afterword = apply_rules(raw_page([
            '<p class="font-1em30">あとがき</p>', "<p>作者署名</p>",
        ]), RULES).encode()
        photo = apply_rules(raw_page(
            ['<p><img src="../image/hyou4.jpg"/></p>'],
            body_class="p-image"), RULES).encode()
        profile = apply_rules(raw_page([
            "<p>鎌池和馬</p>",
            "<p>魔術ＶＳ科学という構図を作ってみたかったのですが…</p>",
        ]), RULES).encode()
        renames = pairing_header_renames({
            "item/xhtml/p-001.xhtml": afterword,
            "item/xhtml/p-002.xhtml": photo,
            "item/xhtml/p-003.xhtml": profile,
        }, "S1_15")
        self.assertEqual(renames["item/xhtml/p-001.xhtml"],
                         "item/xhtml/S1_15-01_p-001.xhtml")
        self.assertNotIn("item/xhtml/p-002.xhtml", renames, "纯插图页应是包装页")
        self.assertNotIn("item/xhtml/p-003.xhtml", renames,
                         "附录起点之后的介绍页不得成为尾声")

    def test_backmatter_latch_also_blocks_pages_with_h1(self):
        """附录起点之后的 h1 页（解说/收录短篇/次卷预告）也必须保留原名。

        `has_new_h1` 分支排在后记分支之前，若闩锁只在后记分支内检查，这类页仍会
        拿到内容序（回归：S1_15 附录中的 h1 页曾被编为正文）。
        """
        afterword = apply_rules(raw_page([
            '<p class="font-1em30">あとがき</p>', "<p>作者署名</p>",
        ]), RULES).encode()
        photo = apply_rules(raw_page(
            ['<p><img src="../image/hyou4.jpg"/></p>'],
            body_class="p-image"), RULES).encode()
        commentary = apply_rules(raw_page([
            '<p class="font-1em30">解説</p>', "<p>解说正文。</p>",
        ]), RULES).encode()
        renames = pairing_header_renames({
            "item/xhtml/p-001.xhtml": afterword,
            "item/xhtml/p-002.xhtml": photo,
            "item/xhtml/p-003.xhtml": commentary,
        }, "S1_15")
        self.assertEqual(renames["item/xhtml/p-001.xhtml"],
                         "item/xhtml/S1_15-01_p-001.xhtml")
        self.assertNotIn("item/xhtml/p-003.xhtml", renames,
                         f"附录后的 h1 页仍被赋内容序："
                         f"{renames.get('item/xhtml/p-003.xhtml')}")

    def test_epilogue_aggregates_until_backmatter_then_h1_page_blocked(self):
        """先聚尾声、再遇附录页、最后 h1 页：三步都要按规则走。"""
        afterword = apply_rules(raw_page([
            '<p class="font-1em30">あとがき</p>', "<p>署名</p>",
        ]), RULES).encode()
        tail = apply_rules(raw_page(["<p>尾声正文。</p>"]), RULES).encode()
        photo = apply_rules(raw_page(
            ['<p><img src="../image/hyou4.jpg"/></p>'],
            body_class="p-image"), RULES).encode()
        story = apply_rules(raw_page([
            '<p class="font-1em30">巻末短篇</p>', "<p>短篇正文。</p>",
        ]), RULES).encode()
        renames = pairing_header_renames({
            "item/xhtml/p-001.xhtml": afterword,
            "item/xhtml/p-002.xhtml": tail,
            "item/xhtml/p-003.xhtml": photo,
            "item/xhtml/p-004.xhtml": story,
        }, "S1_15")
        self.assertEqual(renames["item/xhtml/p-002.xhtml"],
                         "item/xhtml/S1_15-02_p-002.xhtml", "附录前的正文页仍是尾声")
        self.assertNotIn("item/xhtml/p-003.xhtml", renames)
        self.assertNotIn("item/xhtml/p-004.xhtml", renames,
                         "附录开始后的 h1 页不得再取得内容序")

    def test_continuous_epilogue_still_aggregates_before_backmatter(self):
        """紧接后记的连续正文页仍聚成单一尾声单元；附录起点之后才封住。"""
        afterword = apply_rules(raw_page([
            '<p class="font-1em30">あとがき</p>', "<p>署名</p>",
        ]), RULES).encode()
        tail1 = apply_rules(raw_page(["<p>尾声正文一</p>"]), RULES).encode()
        tail2 = apply_rules(raw_page(["<p>尾声正文二</p>"]), RULES).encode()
        photo = apply_rules(raw_page(
            ['<p><img src="../image/hyou4.jpg"/></p>'],
            body_class="p-image"), RULES).encode()
        bio = apply_rules(raw_page(["<p>著者近影</p>", "<p>介绍</p>"]), RULES).encode()
        renames = pairing_header_renames({
            "item/xhtml/p-001.xhtml": afterword,
            "item/xhtml/p-002.xhtml": tail1,
            "item/xhtml/p-003.xhtml": tail2,
            "item/xhtml/p-004.xhtml": photo,
            "item/xhtml/p-005.xhtml": bio,
        }, "S4_05")
        self.assertEqual(renames["item/xhtml/p-002.xhtml"],
                         "item/xhtml/S4_05-02_p-002.xhtml")
        self.assertEqual(renames["item/xhtml/p-003.xhtml"],
                         "item/xhtml/S4_05-02_p-003.xhtml")
        self.assertNotIn("item/xhtml/p-004.xhtml", renames)
        self.assertNotIn("item/xhtml/p-005.xhtml", renames)

    def test_span_wrapped_afterword_title_starts_epilogue_unit(self):
        afterword = apply_rules(raw_page([
            '<p><span class="font-1em30">あとがき</span></p>',
            "<p>作者署名</p>",
        ]), RULES).encode()
        epilogue = apply_rules(raw_page(["<p>尾声正文</p>"]), RULES).encode()
        colophon = apply_rules(raw_page(["<p>奥付</p>"]), RULES).encode()
        entries = {
            "item/xhtml/p-001.xhtml": afterword,
            "item/xhtml/p-002.xhtml": epilogue,
            "item/xhtml/p-003.xhtml": colophon,
        }
        renames = pairing_header_renames(entries, "S2_99")
        self.assertEqual(
            renames["item/xhtml/p-001.xhtml"],
            "item/xhtml/S2_99-01_p-001.xhtml",
        )
        self.assertEqual(
            renames["item/xhtml/p-002.xhtml"],
            "item/xhtml/S2_99-02_p-002.xhtml",
        )
        self.assertNotIn("item/xhtml/p-003.xhtml", renames)

    def test_epilogue_prose_mentioning_profile_word_is_not_dropped(self):
        """尾声正文页叙述中出现「プロフィール」不得被当作著者介绍页整页丢弃。

        回归 S4_01：p-014（107 段尾声正文，第 63 段含「プロフィール」）曾被全文
        关键词匹配误判为包装页而保留裸文件名，导致 -12 只剩尾页 8 行。
        """
        epilogue = apply_rules(raw_page(
            ["<p>「まったく」</p>"]
            + [f"<p>第{i}段のやり取り。</p>" for i in range(1, 14)]
            + ["<p>痴漢の逆ギレまで含めてプロフィールを作るのが一番大変だった。</p>"]
        ), RULES)
        profile = apply_rules(raw_page([
            "<p>著者近影</p>",
            "<p>１９７３年生まれ。</p>",
        ]), RULES)
        self.assertTrue(is_epilogue_story_page(epilogue))
        self.assertFalse(is_epilogue_story_page(profile))

    def test_default_s4_05_map_records_tail_and_backmatter(self):
        page_map = load_header_map("S4_05", None)
        self.assertIsNotNone(page_map)
        assert page_map is not None
        self.assertEqual(page_map["p-001.xhtml"], 1)
        self.assertEqual(page_map["p-012.xhtml"], 10)
        self.assertEqual(page_map["p-013.xhtml"], 10)
        self.assertIsNone(page_map["p-014.xhtml"])
        self.assertIsNone(page_map["p-015.xhtml"])

    def test_artifact_contract_rejects_unprefixed_images_and_broken_references(self):
        entries = {
            "mimetype": b"application/epub+zip",
            "META-INF/container.xml": (
                b'<container><rootfiles><rootfile full-path="item/standard.opf"/>'
                b'</rootfiles></container>'
            ),
            "item/standard.opf": b'<package><manifest>'
                                 b'<item href="image/missing.jpg"/>'
                                 b'</manifest></package>',
            "item/image/i-030.jpg": b"jpeg data",
        }
        issues = artifact_contract_issues(entries, "S4_05")
        self.assertTrue(any("图片缺少作品号表头" in issue for _, issue in issues))
        self.assertTrue(any("资源引用不存在" in issue for _, issue in issues))

    def test_artifact_contract_rejects_zero_content_sequence(self):
        entries = {
            "mimetype": b"application/epub+zip",
            "META-INF/container.xml": b"<container/>",
            "item/xhtml/S4_05-00_p-001.xhtml": b"<html/>",
        }
        issues = artifact_contract_issues(entries, "S4_05")
        self.assertTrue(any("内容序 -00 非法" in issue for _, issue in issues))

    def test_artifact_contract_accepts_prefixed_image_and_valid_references(self):
        entries = {
            "mimetype": b"application/epub+zip",
            "META-INF/container.xml": (
                b'<container><rootfiles><rootfile full-path="item/standard.opf"/>'
                b'</rootfiles></container>'
            ),
            "item/standard.opf": b'<package><manifest>'
                                 b'<item href="image/S4_05-i-030.jpg"/>'
                                 b'</manifest></package>',
            "item/image/S4_05-i-030.jpg": b"jpeg data",
        }
        self.assertEqual(artifact_contract_issues(entries, "S4_05"), [])

    def test_epub_zip_contract_requires_stored_first_mimetype(self):
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_DEFLATED
        issues = epub_zip_issues(
            [zipfile.ZipInfo("other"), mimetype],
            {"mimetype": b"application/epub+zip"},
        )
        self.assertTrue(any("第一个条目" in issue for _, issue in issues))

    def test_infer_book_id(self):
        from bw_preprocess import infer_book_id
        self.assertEqual(infer_book_id("とある暗部の少女共棲"), "S4_01")
        self.assertEqual(infer_book_id("とある暗部の少女共棲（２）"), "S4_02")
        self.assertEqual(infer_book_id("とある暗部の少女共棲(6)"), "S4_06")
        self.assertEqual(infer_book_id("創約 とある魔術の禁書目録(11)"), "S3_11")
        self.assertEqual(infer_book_id("[S4_05]とある暗部の少女共棲"), "S4_05")


if __name__ == "__main__":
    unittest.main()
