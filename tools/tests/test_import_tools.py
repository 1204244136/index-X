from __future__ import annotations

import base64
import contextlib
import io
import json
import sys
import tempfile
import unittest
import xml.sax.saxutils
import zipfile
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import import_align_plan  # noqa: E402
import import_build_text  # noqa: E402
import import_build_wrappers  # noqa: E402
import import_docx_outline  # noqa: E402
import import_images  # noqa: E402
import import_materials  # noqa: E402
import import_plan  # noqa: E402

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
HEAD3 = ('<html xmlns="http://www.w3.org/1999/xhtml" '
         'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
         '<link href="../Styles/style.css" rel="stylesheet" type="text/css"/>'
         "<title></title></head><body>")

# 1×1 透明 PNG：装了 Pillow 的环境也认它是一张可解码的图
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def write_docx(path: Path, paragraphs: list[dict]) -> Path:
    """最小交稿 docx：每段 {style, runs}，runs 里的 '<br/>'/'<tab/>' 写成 w:br/w:tab。"""
    chunks = []
    for paragraph in paragraphs:
        parts = []
        style = paragraph.get("style", "Normal")
        if style:
            parts.append(f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>')
        for piece in paragraph.get("runs", []):
            if piece == "<br/>":
                parts.append("<w:r><w:br/></w:r>")
            elif piece == "<tab/>":
                parts.append("<w:r><w:tab/></w:r>")
            else:
                parts.append("<w:r><w:t xml:space=\"preserve\">"
                             + xml.sax.saxutils.escape(piece) + "</w:t></w:r>")
        chunks.append("<w:p>" + "".join(parts) + "</w:p>")
    document = (f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W_NS}">'
                f'<w:body>{"".join(chunks)}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
    return path


def write_jp_page(path: Path, *, h1: str | None, items: list[tuple[str, str]]) -> Path:
    """最小日文对齐工作源页：L1–L3 头部、L4 h1、L5 h2、L6 起内容、末行闭标签。"""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<!DOCTYPE html>",
             '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head><body>']
    lines.append(f"<h1>{h1}</h1>" if h1 else "")
    first_h2 = next((text for kind, text in items if kind == "h2"), None)
    lines.append(f"<h2>{first_h2}</h2>" if first_h2 else "")
    seen_h2 = False
    for kind, text in items:
        if kind == "h2":
            if not seen_h2 and text == first_h2:
                seen_h2 = True
                continue
            lines.append(f"<h2>{text}</h2>")
        elif kind == "br":
            lines.append("<br/>")
        elif kind == "img":
            lines.append(f'<p><img class="fit" src="../image/{text}" alt=""/></p>')
        else:
            lines.append(f"<p>{text}</p>")
    lines.append("</body></html>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def jp_dir_for(root: Path, work: str = "S4_04") -> Path:
    directory = root / f"【{work}】とある暗部の少女共棲(4)"
    (directory / "item" / "xhtml").mkdir(parents=True, exist_ok=True)
    return directory


def sample_plan(jp_dir: Path, work: str = "S4_04", docx: Path | None = None) -> dict:
    return {
        "work_id": work,
        "book_dir": f"【{work}】某暗部的少女共栖 4",
        "source_docx": str(docx) if docx else "",
        "jp_root": str(jp_dir.parent),
        "jp_dir": jp_dir.name,
        "images_source": "",
        "images": [
            {"dst": f"{work}-Cover.jpg", "src": "cover.jpg", "role": "cover"},
            {"dst": f"{work}-Contents.jpg", "src": "contents.jpg", "role": "illustration"},
        ],
        "chapters": [
            {"cn_title": "引子", "jp_file": "item/xhtml/S4_04-01.xhtml",
             "fname": f"{work}-01_Before_the_Prologue.xhtml",
             "h1_main": None, "h1_sub": None, "nav": None, "ops": []},
            {"cn_title": "序章 起点", "jp_file": "item/xhtml/S4_04-02.xhtml",
             "fname": f"{work}-02_Prologue.xhtml",
             "h1_main": "序　章", "h1_sub": "起点", "nav": "序　章 起点", "ops": []},
        ],
    }


class DocxOutlineTests(unittest.TestCase):
    def test_outline_counts_and_reports_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            docx = write_docx(Path(tmp) / "稿.docx", [
                {"style": "Heading1", "runs": ["引子"]},
                {"runs": ["正文一。"]},
                {"style": "Heading1", "runs": ["序章 起点"]},
                {"runs": ["|超能力者[Level 5]登场。"]},
                {"runs": [""]},
                {"runs": ["「走。」【*译注：说明。】"]},
                {"runs": ["【*插图】"]},
            ])
            out = Path(tmp) / "outline.tsv"
            code = import_docx_outline.main([str(docx), "--out", str(out)])
            self.assertEqual(code, 0)
            body = out.read_text(encoding="utf-8")
            self.assertIn("Heading1", body)
            self.assertIn("引子", body)
            self.assertEqual(body.count("\n"), 8)  # 表头 + 7 段

    def test_intra_paragraph_break_blocks_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            docx = write_docx(Path(tmp) / "稿.docx", [
                {"style": "Heading1", "runs": ["序章"]},
                {"runs": ["前半", "<br/>", "后半"]},
            ])
            code = import_docx_outline.main([str(docx), "--check"])
            self.assertEqual(code, 1)

    def test_missing_heading_blocks_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            docx = write_docx(Path(tmp) / "稿.docx", [{"runs": ["没有章标题。"]}])
            self.assertEqual(import_docx_outline.main([str(docx), "--check"]), 1)

    def test_unclosed_ruby_marks_block_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            docx = write_docx(Path(tmp) / "稿.docx", [
                {"style": "Heading1", "runs": ["序章"]},
                {"runs": ["|超能力者 少了括号。"]},
            ])
            self.assertEqual(import_docx_outline.main([str(docx), "--check"]), 1)


class PlanValidationTests(unittest.TestCase):
    def test_unknown_op_and_duplicate_para(self):
        plan = {"work_id": "S4_04", "book_dir": "x", "chapters": [
            {"cn_title": "序章", "jp_file": "a.xhtml", "fname": "S4_04-02_Prologue.xhtml",
             "ops": [{"op": "wat", "para": 1},
                     {"op": "drop", "para": 2},
                     {"op": "drop", "para": 2}]}]}
        problems = import_plan.validate_plan(plan)
        self.assertTrue(any("op 非法" in item for item in problems))
        self.assertTrue(any("重复" in item for item in problems))

    def test_apply_ops_rejects_mismatched_kind(self):
        rows = [{"idx": 1, "kind": "blank", "text": ""},
                {"idx": 2, "kind": "p", "text": "正文"}]
        with self.assertRaises(import_plan.PlanError):
            import_plan.apply_ops(rows, {"ops": [{"op": "merge_prev", "para": 2}]}, where="序章")
        with self.assertRaises(import_plan.PlanError):
            import_plan.apply_ops(rows, {"ops": [{"op": "insert_br_after", "para": 1}]}, where="序章")

    def test_undeclared_note_only_row_blocks(self):
        rows = [{"idx": 1, "kind": "p", "text": "正文"},
                {"idx": 2, "kind": "note-only", "text": "【*译注：说。】"}]
        with self.assertRaises(import_plan.PlanError):
            import_plan.apply_ops(rows, {"ops": []}, where="序章")


class AlignPlanTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        jp = jp_dir_for(root)
        write_jp_page(jp / "item/xhtml/S4_04-01.xhtml", h1=None,
                      items=[("p", "その街は『壁』に覆われている。"),
                             ("p", "無断でまたいだ者は分かっていない。")])
        write_jp_page(jp / "item/xhtml/S4_04-02.xhtml", h1="序　章　起点",
                      items=[("p", "最初の段落である。"), ("br", ""),
                             ("p", "二つ目の段落である。")])
        return jp

    def test_skeleton_and_relations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jp = self._fixture(root)
            docx = write_docx(root / "稿.docx", [
                {"style": "Heading1", "runs": ["引子"]},
                {"runs": ["这座城市被一道「墙壁」完全围住。"]},
                {"runs": ["无故跨越之人究竟会有何下场，就连「暗部」之人都不清楚。"]},
                {"style": "Heading1", "runs": ["序章 起点"]},
                {"runs": ["最初の段落である。"]},
                {"runs": ["二つ目の段落である。"]},
            ])
            plan_path = root / "plan.json"
            code = import_align_plan.main([
                str(docx), "--work", "S4_04", "--book-dir", "【S4_04】某暗部的少女共栖 4X",
                "--jp-root", str(root), "--out", str(plan_path)])
            self.assertEqual(code, 0)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["chapters"][0]["fname"], "S4_04-01_Before_the_Prologue.xhtml")
            self.assertEqual(plan["chapters"][1]["h1_main"], "序　章")
            # 日文有分隔行、中文没有 → 报告应给出 1:0 并可对齐
            report, odd, deltas = import_align_plan.build(
                jp, plan, docx, root / "gaps.txt", )
            self.assertTrue((root / "gaps.txt").is_file())
            self.assertEqual(odd, 1)          # 日文独有的分隔行
            self.assertEqual(deltas, [0, -1])  # 引子对齐；序章少一行待补 insert_br_after

    def test_check_fails_while_mismatched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root)
            docx = write_docx(root / "稿.docx", [
                {"style": "Heading1", "runs": ["引子"]},
                {"runs": ["这座城市被一道「墙壁」完全围住。"]},
                {"runs": ["无故跨越之人究竟会有何下场。"]},
                {"style": "Heading1", "runs": ["序章 起点"]},
                {"runs": ["最初の段落である。"]},
                {"runs": ["二つ目の段落である。"]},
            ])
            plan_path = root / "plan.json"
            import_align_plan.main([str(docx), "--work", "S4_04",
                                    "--book-dir", "【S4_04】某暗部的少女共栖 4X",
                                    "--jp-root", str(root), "--out", str(plan_path)])
            code = import_align_plan.main([str(docx), "--work", "S4_04",
                                           "--book-dir", "【S4_04】某暗部的少女共栖 4X",
                                           "--jp-root", str(root),
                                           "--plan", str(plan_path), "--check"])
            self.assertEqual(code, 1)


class BuildTextTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        jp = jp_dir_for(root)
        write_jp_page(jp / "item/xhtml/S4_04-01.xhtml", h1=None,
                      items=[("p", "最初の段落である。")])
        staged = root / "out" / "【S4_04】某暗部的少女共栖 4X"
        write_jp_page(jp / "item/xhtml/S4_04-02.xhtml", h1="序　章",
                      items=[("p", "段落一。"), ("p", "段落二。")])
        docx = write_docx(root / "稿.docx", [
            {"style": "Heading1", "runs": ["引子"]},
            {"runs": ["第一段。"]},
            {"style": "Heading1", "runs": ["序章"]},
            {"runs": ["段落一。"]},
            {"runs": [" 段落二。"]},
        ])
        return jp, staged, docx

    def test_writes_and_checks_line_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jp, staged, docx = self._fixture(root)
            plan = sample_plan(jp, docx=docx)
            plan["images"] = []
            plan_path = import_plan.write_plan(root / "plan.json", plan)
            code = import_build_text.main([str(plan_path), "--out", str(staged),
                                           "--apply", "--staging"])
            self.assertEqual(code, 0)
            prologue = (staged / "OEBPS/Text/S4_04-02_Prologue.xhtml").read_text(encoding="utf-8")
            self.assertIn("<h1", prologue.splitlines()[3])
            self.assertEqual(len(prologue.splitlines()),
                             len((jp / "item/xhtml/S4_04-02.xhtml").read_text(
                                 encoding="utf-8").splitlines()))
            # 段首的 ASCII 空格是交稿噪声，渲染时清掉
            self.assertIn("<p>段落二。</p>", prologue)

    def test_line_count_mismatch_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jp, staged, docx = self._fixture(root)
            plan = sample_plan(jp, docx=docx)
            plan["images"] = []
            plan["chapters"][1]["ops"] = [{"op": "drop", "para": 4}]  # 少一行，必然对不齐
            plan_path = import_plan.write_plan(root / "plan.json", plan)
            code = import_build_text.main([str(plan_path), "--out", str(staged),
                                           "--apply", "--staging"])
            self.assertEqual(code, 1)
            self.assertFalse((staged / "OEBPS/Text").exists())


class WrappersTests(unittest.TestCase):
    def test_report_write_error_restores_wrappers_and_existing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jp, staged, template, materials = self._material(root)
            materials.mkdir(parents=True)
            info, intro = materials / "info.txt", materials / "intro.txt"
            info.write_text('<h1>制作信息</h1>\n\n<p>翻译：甲</p>\n', encoding="utf-8")
            intro.write_text('<h1>简介</h1>\n\n<p>简介正文。</p>\n', encoding="utf-8")
            plan_path = import_plan.write_plan(root / "plan.json", sample_plan(jp))
            report = root / "existing-report.txt"
            report.write_bytes(b"old report")
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            real_write = import_build_wrappers.atomic_write_bytes

            def fail_report(path, data):
                if path == report:
                    raise OSError("simulated report write failure")
                return real_write(path, data)

            errors = io.StringIO()
            with patch.object(import_build_wrappers, "atomic_write_bytes", side_effect=fail_report), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                code = import_build_wrappers.main([str(plan_path), "--template", str(template),
                                                   "--info", str(info), "--intro", str(intro),
                                                   "--out", str(staged), "--report", str(report),
                                                   "--apply", "--staging"])
            self.assertEqual(code, 1)
            self.assertIn("报告写入失败", errors.getvalue())
            self.assertEqual({p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}, before)

    def test_report_collisions_are_rejected_before_any_wrapper_write(self):
        for apply in (False, True):
            for collision in ("body", "plan", "template", "info", "intro", "japanese", "source", "output"):
                with self.subTest(apply=apply, collision=collision), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    jp, staged, template, materials = self._material(root)
                    materials.mkdir(parents=True)
                    info, intro = materials / "info.txt", materials / "intro.txt"
                    info.write_text('<h1>制作信息</h1>\n\n<p>翻译：甲</p>\n', encoding="utf-8")
                    intro.write_text('<h1>简介</h1>\n\n<p>简介正文。</p>\n', encoding="utf-8")
                    source = root / "source"
                    source.mkdir()
                    (source / "cover.jpg").write_bytes(PNG_1PX)
                    plan = sample_plan(jp)
                    plan["images_source"] = str(source)
                    plan_path = import_plan.write_plan(root / "plan.json", plan)
                    reports = {
                        "body": staged / "OEBPS/Text/S4_04-01_Before_the_Prologue.xhtml",
                        "plan": plan_path, "template": template / "OEBPS/Styles/style.css",
                        "info": info, "intro": intro, "japanese": jp / "item/xhtml/S4_04-01.xhtml",
                        "source": source / "cover.jpg", "output": staged / "new-report.txt",
                    }
                    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                    output, errors = io.StringIO(), io.StringIO()
                    args = [str(plan_path), "--template", str(template), "--info", str(info),
                            "--intro", str(intro), "--out", str(staged), "--report", str(reports[collision])]
                    args += ["--apply", "--staging"] if apply else ["--dry-run"]
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                        code = import_build_wrappers.main(args)
                    self.assertEqual({p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}, before)
                    self.assertEqual(code, 2)
                    self.assertIn("报告", errors.getvalue())
                    self.assertNotIn("已写入", output.getvalue())

    def test_preview_writes_explicit_report_without_writing_wrappers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jp, staged, template, materials = self._material(root)
            materials.mkdir(parents=True)
            info, intro = materials / "info.txt", materials / "intro.txt"
            info.write_text('<h1>制作信息</h1>\n\n<p>翻译：甲</p>\n', encoding="utf-8")
            intro.write_text('<h1>简介</h1>\n\n<p>简介正文。</p>\n', encoding="utf-8")
            plan_path = import_plan.write_plan(root / "plan.json", sample_plan(jp))
            before = {p.relative_to(staged): p.read_bytes() for p in staged.rglob("*") if p.is_file()}
            report = root / "reports/wrappers.txt"
            code = import_build_wrappers.main([str(plan_path), "--template", str(template),
                                               "--info", str(info), "--intro", str(intro),
                                               "--out", str(staged), "--dry-run", "--report", str(report)])
            self.assertEqual(code, 0)
            self.assertIn("预览", report.read_text(encoding="utf-8"))
            self.assertIn("S4_04-02_Prologue.xhtml", report.read_text(encoding="utf-8"))
            self.assertEqual({p.relative_to(staged): p.read_bytes() for p in staged.rglob("*") if p.is_file()}, before)

    def test_title_contract_failure_blocks_wrappers_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jp, staged, template, materials = self._material(root)
            materials.mkdir(parents=True)
            info = materials / "info.txt"
            intro = materials / "intro.txt"
            info.write_text('<h1 class="color1">制作信息</h1>\n\n<p>制作署名</p>\n', encoding="utf-8")
            intro.write_text('<h1>简介</h1>\n\n<p>简介正文。</p>\n', encoding="utf-8")
            plan_path = import_plan.write_plan(root / "plan.json", sample_plan(jp))
            before = {p.relative_to(staged): p.read_bytes() for p in staged.rglob("*") if p.is_file()}
            code = import_build_wrappers.main([str(plan_path), "--template", str(template),
                                               "--info", str(info), "--intro", str(intro),
                                               "--out", str(staged), "--apply", "--staging"])
            self.assertEqual(code, 1)
            self.assertEqual({p.relative_to(staged): p.read_bytes() for p in staged.rglob("*") if p.is_file()}, before)

    def _template(self, root: Path) -> Path:
        template = root / "template"
        (template / "OEBPS/Styles").mkdir(parents=True)
        (template / "META-INF").mkdir(parents=True)
        from docx2epub import _CSS
        (template / "OEBPS/Styles/style.css").write_text(_CSS, encoding="utf-8")
        (template / "META-INF/container.xml").write_text("<container/>\n", encoding="utf-8")
        (template / "OEBPS/content.opf").write_text(
            '<meta property="calibre:user_metadata">{}</meta>\n', encoding="utf-8")
        return template

    def _material(self, root: Path) -> tuple[Path, Path, Path, Path]:
        jp = jp_dir_for(root)
        write_jp_page(jp / "item/xhtml/S4_04-01.xhtml", h1=None, items=[("p", "一。")])
        write_jp_page(jp / "item/xhtml/S4_04-02.xhtml", h1="序　章", items=[("p", "二。")])
        staged = root / "out" / "【S4_04】某暗部的少女共栖 4X"
        (staged / "OEBPS/Text").mkdir(parents=True)
        (staged / "OEBPS/Text/S4_04-01_Before_the_Prologue.xhtml").write_text(
            '<html><head><link rel="stylesheet" href="../Styles/style.css"/></head><body>\n'
            "<p>一。</p>\n</body></html>\n", encoding="utf-8")
        (staged / "OEBPS/Text/S4_04-02_Prologue.xhtml").write_text(
            '<html><head><link rel="stylesheet" href="../Styles/style.css"/></head><body>\n'
            '<h1 class="heading-lines"><span class="heading-main">序　章</span>'
            '<span class="heading-subtitle font08">起点</span></h1>\n<h2 id="toc_1">1</h2>\n<p>二。</p>\n'
            "</body></html>\n", encoding="utf-8")
        (staged / "OEBPS/Images").mkdir(parents=True)
        for name in ("S4_04-Cover.jpg", "S4_04-Contents.jpg"):
            (staged / "OEBPS/Images" / name).write_bytes(PNG_1PX)
        return jp, staged, self._template(root), root / "materials"

    def test_wrappers_require_text_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jp, staged, template, materials = self._material(root)
            info = materials / "info.txt"
            intro = materials / "intro.txt"
            materials.mkdir(parents=True, exist_ok=True)
            info.write_text('<h1>制作信息</h1>\n\n<p>翻译：甲</p>\n'
                            "<p>校对：乙</p>\n<p>美工：丙</p>\n", encoding="utf-8")
            intro.write_text('<h1>简介</h1>\n\n<p><b>导语</b></p>\n'
                             "<p>正文。</p>\n", encoding="utf-8")
            plan = sample_plan(jp)
            plan["images"].append(
                {"dst": "S4_04-i-032.jpg", "src": "i-032.jpg", "role": "body"})
            plan_path = import_plan.write_plan(root / "plan.json", plan)

            # 彩页缺一张 → 阻断且不写盘（包装页会引用它）
            illustration = staged / "OEBPS/Images/S4_04-Contents.jpg"
            payload = illustration.read_bytes()
            illustration.unlink()
            code = import_build_wrappers.main([str(plan_path), "--template", str(template),
                                               "--info", str(info), "--intro", str(intro),
                                               "--out", str(staged), "--apply", "--staging"])
            self.assertEqual(code, 1)
            self.assertFalse((staged / "nav.xhtml").exists())

            illustration.write_bytes(payload)
            code = import_build_wrappers.main([str(plan_path), "--template", str(template),
                                               "--info", str(info), "--intro", str(intro),
                                               "--out", str(staged), "--apply", "--staging"])
            self.assertEqual(code, 0)
            opf = (staged / "OEBPS/content.opf").read_text(encoding="utf-8")
            nav = (staged / "nav.xhtml").read_text(encoding="utf-8")
            ncx = (staged / "toc.ncx").read_text(encoding="utf-8")
            self.assertIn("序　章 起点", nav)
            self.assertIn("序　章 起点", ncx)
            self.assertIn("S4_04-i-032.jpg", opf)
            # 回归：manifest 里的 id 必须唯一（calibre 会因重复 id 报错）
            ids = import_build_wrappers.re.findall(r'<item id="([^"]+)"', opf)
            self.assertEqual(len(ids), len(set(ids)))
            # spine 必须都指向 manifest 里存在的 id
            idrefs = import_build_wrappers.re.findall(r'<itemref idref="([^"]+)"', opf)
            self.assertTrue(set(idrefs) <= set(ids))
            self.assertTrue((staged / "mimetype").read_bytes() == b"application/epub+zip")

    def test_missing_chapter_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jp, staged, template, materials = self._material(root)
            (staged / "OEBPS/Text/S4_04-02_Prologue.xhtml").unlink()
            info = materials / "info.txt"
            intro = materials / "intro.txt"
            materials.mkdir(parents=True, exist_ok=True)
            info.write_text('<h1 class="x">制作信息</h1>\n\n<p>翻译：甲</p>\n'
                            "<p>校对：乙</p>\n<p>美工：丙</p>\n", encoding="utf-8")
            intro.write_text('<h1 class="color1">简介</h1>\n\n<p>正文。</p>\n', encoding="utf-8")
            plan = sample_plan(jp)
            plan["images"] = []
            plan_path = import_plan.write_plan(root / "plan.json", plan)
            code = import_build_wrappers.main([str(plan_path), "--template", str(template),
                                               "--info", str(info), "--intro", str(intro),
                                               "--out", str(staged), "--apply", "--staging"])
            self.assertEqual(code, 1)
            self.assertFalse((staged / "nav.xhtml").exists())


class ImagesTests(unittest.TestCase):
    def test_report_write_error_restores_images_and_existing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "cover.jpg").write_bytes(PNG_1PX)
            plan = sample_plan(jp_dir_for(root))
            plan["images_source"] = str(source)
            plan["images"] = [{"dst": "S4_04-Cover.jpg", "src": "cover.jpg", "role": "cover"}]
            plan_path = import_plan.write_plan(root / "plan.json", plan)
            out = root / "out"
            report = root / "existing-report.txt"
            report.write_bytes(b"old report")
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            real_write = import_images.atomic_write_bytes

            def fail_report(path, data):
                if path == report:
                    raise OSError("simulated report write failure")
                return real_write(path, data)

            errors = io.StringIO()
            with patch.object(import_images, "atomic_write_bytes", side_effect=fail_report), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                code = import_images.main(["apply", str(plan_path), "--out", str(out), "--report", str(report),
                                           "--apply", "--staging"])
            self.assertEqual(code, 1)
            self.assertIn("报告写入失败", errors.getvalue())
            self.assertEqual({p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}, before)

    def test_report_collisions_are_rejected_before_any_image_copy(self):
        for apply in (False, True):
            for collision in ("source", "plan", "japanese", "output"):
                with self.subTest(apply=apply, collision=collision), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    source = root / "source"
                    source.mkdir()
                    original = source / "cover.jpg"
                    original.write_bytes(PNG_1PX)
                    jp = jp_dir_for(root)
                    plan = sample_plan(jp)
                    plan["images_source"] = str(source)
                    plan["images"] = [{"dst": "S4_04-Cover.jpg", "src": "cover.jpg", "role": "cover"}]
                    plan_path = import_plan.write_plan(root / "plan.json", plan)
                    out = root / "out"
                    reports = {"source": original, "plan": plan_path, "japanese": jp / "new-report.txt",
                               "output": out / "OEBPS/Images/S4_04-Cover.jpg"}
                    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                    output, errors = io.StringIO(), io.StringIO()
                    args = ["apply", str(plan_path), "--out", str(out), "--report", str(reports[collision])]
                    args += ["--apply", "--staging"] if apply else ["--dry-run"]
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                        code = import_images.main(args)
                    self.assertEqual({p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}, before)
                    self.assertEqual(code, 2)
                    self.assertIn("报告", errors.getvalue())
                    self.assertFalse(out.exists())

    def test_missing_plan_error_uses_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for command, args in (
                (import_images.main, ["apply", str(root / "missing.json"), "--out", str(root / "out")]),
                (import_build_wrappers.main, [str(root / "missing.json"), "--template", str(root / "template"),
                                             "--info", str(root / "info.txt"), "--intro", str(root / "intro.txt"),
                                             "--out", str(root / "out")]),
            ):
                with self.subTest(tool=command.__module__):
                    output, errors = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                        self.assertEqual(command(args), 2)
                    self.assertEqual(output.getvalue(), "")
                    self.assertIn("[阻断]", errors.getvalue())
                    self.assertIn("计划文件不存在", errors.getvalue())

    def test_preview_writes_explicit_fingerprint_report_without_copying_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "cover.jpg").write_bytes(PNG_1PX)
            plan = sample_plan(jp_dir_for(root))
            plan["images_source"] = str(source)
            plan["images"] = [{"dst": "S4_04-Cover.jpg", "src": "cover.jpg", "role": "cover"}]
            plan_path = import_plan.write_plan(root / "plan.json", plan)
            out, report = root / "out", root / "reports/images.txt"
            code = import_images.main(["apply", str(plan_path), "--out", str(out),
                                       "--dry-run", "--report", str(report)])
            self.assertEqual(code, 0)
            self.assertFalse(out.exists())
            text = report.read_text(encoding="utf-8")
            self.assertIn("预览", text)
            self.assertIn("S4_04-Cover.jpg", text)
            self.assertIn("sha256", text)

    def test_apply_requires_work_prefix_and_existing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "素材"
            source.mkdir()
            (source / "cover.jpg").write_bytes(PNG_1PX)
            (source / "body.jpg").write_bytes(PNG_1PX)
            plan = {
                "work_id": "S4_04", "book_dir": "x", "chapters": [
                    {"cn_title": "引子", "jp_file": "a.xhtml",
                     "fname": "S4_04-01_Before_the_Prologue.xhtml", "ops": []}],
                "images_source": str(source),
                "images": [
                    {"dst": "S4_04-Cover.jpg", "src": "cover.jpg", "role": "cover"},
                    {"dst": "i-001.jpg", "src": "body.jpg", "role": "body"}],
            }
            plan_path = import_plan.write_plan(root / "plan.json", plan)
            out = root / "out" / "【S4_04】某暗部的少女共栖 4X"
            code = import_images.main(["apply", str(plan_path), "--out", str(out),
                                       "--apply", "--staging"])
            self.assertEqual(code, 1)
            self.assertFalse((out / "OEBPS/Images").exists())

            plan["images"][1]["dst"] = "S4_04-i-001.jpg"
            plan_path = import_plan.write_plan(root / "plan.json", plan)
            code = import_images.main(["apply", str(plan_path), "--out", str(out),
                                       "--apply", "--staging"])
            self.assertEqual(code, 0)
            self.assertTrue((out / "OEBPS/Images/S4_04-i-001.jpg").is_file())


class MaterialsTests(unittest.TestCase):
    def test_missing_materials_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = import_materials.main(["--work", "S4_04",
                                          "--book-dir", "【S4_04】某暗部的少女共栖 4X",
                                          "--jp-root", str(root)])
            self.assertEqual(code, 1)

    def test_info_block_requires_h1_and_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "info.txt"
            path.write_text("<p>翻译：甲</p>\n", encoding="utf-8")
            ok, detail = import_materials.check_info(path)
            self.assertFalse(ok)
            self.assertIn("h1", detail)
            path.write_text('<h1 class="x">制作信息</h1>\n\n<p>翻译：甲</p>\n'
                            "<p>校对：乙</p>\n<p>美工：丙</p>\n", encoding="utf-8")
            ok, _ = import_materials.check_info(path)
            self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
