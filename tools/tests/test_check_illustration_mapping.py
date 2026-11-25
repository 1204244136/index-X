import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import check_illustration_mapping as cim


MAP_HEADER = (
    "| 卷号 | 日文图片 | 日文图片文字 | 日文正文文件 | 日文行号 | 日文正文原句 "
    "| 中文图片 | 中文图片文字 | 中文正文文件 | 中文行号 | 中文正文原句 | 嵌字状态 | 备注 |"
)
MAP_SEP = "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
RETYPESET_HEADER = "| 卷号 | 中文图片 | 优先级 | 类别 | 当前图上问题 | 建议修改／参考文本 | 映射表行位 |"
RETYPESET_SEP = "| --- | --- | --- | --- | --- | --- | --- |"


def make_row(
    vol: str = "S1_01",
    jp_img: str = "S1_01-kuchie-002.jpg",
    jp_img_txt: str = "「台词」",
    jp_file: str = "S1_01-02.xhtml",
    jp_line: str = "2",
    jp_sent: str = "「正文原句」",
    cn_img: str = "S1_01-Illustrations1.jpg",
    cn_img_txt: str = "「中文图上」",
    cn_file: str = "S1_01-02_Chapter1.xhtml",
    cn_line: str = "2",
    cn_sent: str = "「中文原句」",
    state: str = "无需重嵌",
    note: str = "",
) -> str:
    return (
        f"| {vol} | {jp_img} | {jp_img_txt} | {jp_file} | {jp_line} | {jp_sent} "
        f"| {cn_img} | {cn_img_txt} | {cn_file} | {cn_line} | {cn_sent} | {state} | {note} |"
    )


class IllustrationMappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.doc = self.root / "mapping.md"
        self.jp_root = self.root / "jp"
        self.cn_root = self.root / "cn"

        jp_vol = self.jp_root / "【S1_01】テスト"
        (jp_vol / "item" / "xhtml").mkdir(parents=True)
        (jp_vol / "item" / "image").mkdir(parents=True)
        (jp_vol / "item" / "image" / "S1_01-kuchie-002.jpg").write_bytes(b"img")
        (jp_vol / "item" / "xhtml" / "S1_01-02.xhtml").write_text(
            "<html>\n<p><ruby>正<rt>せい</rt></ruby>文</p>\n<p>「正文原句」</p>\n</html>\n",
            encoding="utf-8",
        )
        (jp_vol / "item" / "xhtml" / "S1_01-03.xhtml").write_text(
            "<html>\n<p>别处台词</p>\n<p>「跨文件原句」</p>\n</html>\n",
            encoding="utf-8",
        )

        cn_vol = self.cn_root / "【S1_01】中文测试"
        (cn_vol / "OEBPS" / "Text").mkdir(parents=True)
        (cn_vol / "OEBPS" / "Images").mkdir(parents=True)
        (cn_vol / "OEBPS" / "Images" / "S1_01-Illustrations1.jpg").write_bytes(b"cnimg")
        (cn_vol / "OEBPS" / "Images" / "S1_01-Contents.jpg").write_bytes(b"cntoc")
        (cn_vol / "OEBPS" / "Text" / "S1_01-02_Chapter1.xhtml").write_text(
            "<html>\n<h1>第一章</h1>\n<p>「中文原句」</p>\n</html>\n",
            encoding="utf-8",
        )

    def write_doc(self, rows: list[str], extra_sections: list[str] | None = None) -> None:
        lines = [
            "# Test",
            "",
            MAP_HEADER,
            MAP_SEP,
            *rows,
            "",
        ]
        if extra_sections:
            lines.extend(extra_sections)
        self.doc.write_text("\n".join(lines), encoding="utf-8")

    def run_main(self, *extra: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cim.main(["--doc", str(self.doc), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_anchor_matches_body_line(self):
        self.write_doc([make_row(jp_line="3", cn_line="3")])
        code, out, err = self.run_main("--jp-root", str(self.jp_root), "--cn-root", str(self.cn_root))
        self.assertEqual(code, 0, out + err)
        self.assertIn("已核锚点 2 个／问题 0 条", out)

    def test_escaped_pipe_in_cell_is_read_back(self):
        self.write_doc([make_row(jp_line="3", note=r"A\|B")])
        rows, errs = cim.read_rows(self.doc)
        self.assertEqual(errs, [])
        self.assertEqual(rows[0]["备注"], "A|B")

    def test_drift_is_reported_with_suggestion(self):
        self.write_doc([make_row(jp_line="2", cn_line="2")])
        checked, probs, errs = cim.check(
            self.doc, self.jp_root, cn_root=self.cn_root, check_jp=True, check_cn=True
        )
        self.assertEqual(errs, [])
        self.assertEqual(checked, 2)
        self.assertEqual(len(probs), 2)
        self.assertTrue(all(p["kind"] == "line_drift" and p["suggest"] == 3 for p in probs))

    def test_cross_file_drift_reports_suggest_file(self):
        self.write_doc([make_row(jp_file="S1_01-02.xhtml", jp_line="3", jp_sent="「跨文件原句」")])
        _, probs, _ = cim.check(self.doc, self.jp_root, check_jp=True, check_cn=False)
        self.assertEqual(probs[0]["kind"], "line_drift")
        self.assertEqual(probs[0]["suggest_file"], "S1_01-03.xhtml")
        self.assertEqual(probs[0]["suggest"], 3)

    def test_row_without_anchor_is_skipped(self):
        self.write_doc([
            make_row(jp_file="—", jp_line="—", jp_sent="—", cn_file="—", cn_line="—", cn_sent="—")
        ])
        checked, probs, errs = cim.check(
            self.doc, self.jp_root, cn_root=self.cn_root, check_jp=True, check_cn=True
        )
        self.assertEqual(errs, [])
        self.assertEqual(checked, 0)
        self.assertEqual(probs, [])

    def test_missing_cache_is_precondition_error(self):
        self.write_doc([make_row(jp_line="3")])
        code, _out, err = self.run_main("--jp-root", str(self.root / "missing-jp"))
        self.assertEqual(code, 2)
        self.assertIn("不存在", err)

    def test_omitted_default_jp_cache_runs_cn_only(self):
        self.write_doc([make_row(jp_line="3", cn_line="3")])
        orig_jp = cim.DEFAULT_JP_ROOT
        try:
            cim.DEFAULT_JP_ROOT = self.root / "missing-default-jp"
            code, out, err = self.run_main("--cn-root", str(self.cn_root), "--require-jp")
            self.assertEqual(code, 2)
            # Without --require-jp and with neither explicit --cn-root nor --jp-root?
            # Verify default fallback when DEFAULT_JP_ROOT is absent:
            orig_cn = cim.DEFAULT_CN_ROOT
            cim.DEFAULT_CN_ROOT = self.cn_root
            try:
                code2, out2, err2 = self.run_main()
            finally:
                cim.DEFAULT_CN_ROOT = orig_cn
            self.assertEqual(code2, 0, out2 + err2)
            self.assertIn("跳过日文侧", out2)
        finally:
            cim.DEFAULT_JP_ROOT = orig_jp

    def test_other_tables_in_doc_are_ignored(self):
        other = ["| 其他表 | 列2 |", "| --- | --- |", "| a | b |"]
        self.write_doc([make_row(jp_line="3")], extra_sections=other)
        rows, errs = cim.read_rows(self.doc)
        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 1)

    def test_limit_only_truncates_terminal_examples(self):
        self.write_doc([
            make_row(cn_line="2"),
            make_row(cn_line="99"),
            make_row(cn_line="2", cn_sent="变了的句子"),
        ])
        code, out, _err = self.run_main("--cn-root", str(self.cn_root), "--limit", "1")
        self.assertEqual(code, 1)
        self.assertIn("问题 3 条", out)
        self.assertIn("其余 2 条已省略", out)
        self.assertIn("【插图文本联动提醒】", out)

    def test_negative_limit_is_argument_error(self):
        self.write_doc([make_row(cn_line="3")])
        with self.assertRaises(SystemExit) as ctx:
            self.run_main("--cn-root", str(self.cn_root), "--limit", "-1")
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_input_error_uses_stderr(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cim.main(["--doc", str(self.root / "nope.md"), "--cn-root", str(self.cn_root)])
        self.assertEqual(code, 2)
        self.assertIn("不存在", err.getvalue())

    def test_cn_content_change_blocks_and_prints_reminder(self):
        self.write_doc([make_row(jp_line="3", cn_line="3", cn_sent="「旧的译文」")])
        code, out, _err = self.run_main("--cn-root", str(self.cn_root), "--cn-only")
        self.assertEqual(code, 1)
        self.assertIn("content_changed", out)
        self.assertIn("S1_01-Illustrations1.jpg", out)
        self.assertIn("【插图文本联动提醒】", out)

    def test_retypeset_cross_check_and_missing_image(self):
        self.write_doc(
            [make_row(jp_line="3", cn_line="3", state="待重新嵌字")],
            extra_sections=[],
        )
        _rows, _rt, errs = cim.read_doc(self.doc)
        self.assertTrue(errs)

        # Now add Section 5 table pointing to missing image
        self.write_doc(
            [make_row(jp_line="3", cn_line="3", state="待重新嵌字")],
            extra_sections=[
                RETYPESET_HEADER,
                RETYPESET_SEP,
                "| S1_01 | S1_01-Illustrations1.jpg | 高 | 对话气泡 | 旧译 | 新译 | S1_01-02_Chapter1.xhtml:3 |",
                "| S1_01 | S1_01-Missing.jpg | 低 | 人物介绍 | 缺图 | 缺图 | — |",
            ],
        )
        _, probs, errs2 = cim.check(self.doc, self.jp_root, cn_root=self.cn_root, check_jp=True, check_cn=True)
        self.assertEqual(errs2, [])
        self.assertEqual(len(probs), 1)
        self.assertEqual(probs[0]["kind"], "missing_image")

    def test_find_cn_hits_and_line_range(self):
        (self.cn_root / "【S1_01】中文测试" / "OEBPS" / "Text" / "S1_01-02_Chapter1.xhtml").write_text(
            "<html>\n<h1>第一章</h1>\n<p>第一句</p>\n<p>第二句</p>\n</html>\n",
            encoding="utf-8",
        )
        self.write_doc([make_row(jp_line="3", cn_line="3–4", cn_sent="第一句 第二句")])
        _, probs, errs = cim.check(self.doc, self.jp_root, cn_root=self.cn_root, check_jp=False, check_cn=True)
        self.assertEqual(errs, [])
        self.assertEqual(probs, [])
        hits = cim.find_cn_hits([("S1_01", "OEBPS/Text/S1_01-02_Chapter1.xhtml", 4), ("S1_01", "S1_01-02_Chapter1.xhtml", 1)], self.doc)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["line"], 4)

    def test_scan_git_diff_detects_anchor_and_contents_heading(self):
        repo = self.root / "gitrepo"
        ep = repo / "EPUB" / "【S1_01】中文测试" / "OEBPS"
        (ep / "Text").mkdir(parents=True)
        (ep / "Images").mkdir(parents=True)
        (ep / "Images" / "S1_01-Illustrations1.jpg").write_bytes(b"a")
        (ep / "Images" / "S1_01-Contents.jpg").write_bytes(b"b")
        xhtml = ep / "Text" / "S1_01-02_Chapter1.xhtml"
        xhtml.write_text("<html>\n<h1>旧章名</h1>\n<p>「旧台词」</p>\n</html>\n", encoding="utf-8")
        doc = repo / "docs" / "illustration-text-mapping.md"
        doc.parent.mkdir(parents=True)
        doc.write_text(
            "\n".join([
                MAP_HEADER,
                MAP_SEP,
                make_row(jp_file="—", jp_line="—", jp_sent="—", cn_line="3", cn_sent="「旧台词」"),
            ]),
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)

        # Modify both heading (line 2) and mapped line (line 3)
        xhtml.write_text("<html>\n<h1>新章名</h1>\n<p>「新台词」</p>\n</html>\n", encoding="utf-8")
        res = cim.scan_git_diff("HEAD", repo_root=repo, doc=doc, cn_root=repo / "EPUB")
        self.assertIsNone(res["error"])
        self.assertEqual(len(res["line_hits"]), 1)
        self.assertEqual(res["line_hits"][0]["line"], 3)
        self.assertEqual(len(res["heading_hits"]), 1)
        self.assertEqual(res["heading_hits"][0]["contents_img"], "S1_01-Contents.jpg")

    def test_scan_git_diff_toc_from_section5_and_deleted_file(self):
        repo = self.root / "gitrepo_s1_18"
        ep = repo / "EPUB" / "【S1_18】目录测试" / "OEBPS"
        (ep / "Text").mkdir(parents=True)
        (ep / "Images").mkdir(parents=True)
        (ep / "Images" / "S1_18-Illustrations2.jpg").write_bytes(b"img")
        x1 = ep / "Text" / "S1_18-02_Chapter1.xhtml"
        x1.write_text("<html>\n<h1>旧目录名</h1>\n<p>正文无关行</p>\n</html>\n", encoding="utf-8")
        x2 = ep / "Text" / "S1_18-03_Chapter2.xhtml"
        x2.write_text("<html>\n<p>「已删映射句」</p>\n</html>\n", encoding="utf-8")
        doc = repo / "docs" / "illustration-text-mapping.md"
        doc.parent.mkdir(parents=True)
        doc.write_text(
            "\n".join([
                MAP_HEADER,
                MAP_SEP,
                make_row(
                    vol="S1_18",
                    jp_file="—",
                    jp_line="—",
                    jp_sent="—",
                    cn_img="S1_18-Illustrations3.jpg",
                    cn_file="S1_18-03_Chapter2.xhtml",
                    cn_line="2",
                    cn_sent="「已删映射句」",
                ),
                "",
                RETYPESET_HEADER,
                RETYPESET_SEP,
                "| S1_18 | S1_18-Illustrations2.jpg | 高 | 标题与目录 | 目录差异 | 对齐正文 | —（未入正文对白锚点） |",
            ]),
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)

        x1.write_text("<html>\n<h1>新目录名</h1>\n<p>正文无关行</p>\n</html>\n", encoding="utf-8")
        x2.unlink()
        res = cim.scan_git_diff("HEAD", repo_root=repo, doc=doc, cn_root=repo / "EPUB")
        self.assertIsNone(res["error"])
        self.assertEqual(len(res["heading_hits"]), 1)
        self.assertEqual(res["heading_hits"][0]["contents_img"], "S1_18-Illustrations2.jpg")
        self.assertEqual(len(res["line_hits"]), 1)
        self.assertEqual(res["line_hits"][0]["file"], "S1_18-03_Chapter2.xhtml")
        self.assertEqual(res["line_hits"][0]["line"], 2)

    def test_print_illustration_reminder_dedup_and_diff_zero_silent(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cim.print_illustration_reminder([
                ("S1_01", "S1_01-Illustrations1.jpg", "dup detail"),
                ("S1_01", "S1_01-Illustrations1.jpg", "dup detail"),
                ("S1_01", "S1_01-Illustrations2.jpg", "other detail"),
            ])
        out = buf.getvalue()
        self.assertEqual(out.count("dup detail"), 1)
        self.assertIn("other detail", out)
        self.assertIn("未命中清单时保持静默", out)

        from unittest.mock import patch
        self.write_doc([make_row()])
        out_diff = io.StringIO()
        with (
            patch.object(cim, "scan_git_diff", return_value={
                "error": None, "ref": "HEAD", "line_hits": [], "heading_hits": [], "asset_hits": [],
            }),
            redirect_stdout(out_diff),
        ):
            rc = cim.main(["--diff", "HEAD", "--doc", str(self.doc), "--cn-root", str(self.cn_root)])
        self.assertEqual(rc, 0)
        self.assertNotIn("未涉及已映射", out_diff.getvalue())


if __name__ == "__main__":
    unittest.main()
