from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import check_note_order
import docx2epub
import import_build_text
import import_plan


def make_inputs(root: Path, body: str = "正文", *, two_chapters: bool = False):
    docx = root / "【S1_01】测试.docx"
    paragraphs = []
    chapters = []
    jp = root / "japanese"
    jp.mkdir()
    for number in range(1, 3 if two_chapters else 2):
        title = "序章" if number == 1 else "终章"
        paragraphs.append(
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            f'<w:r><w:t>{title}</w:t></w:r></w:p>'
            f'<w:p><w:r><w:t>{body}</w:t></w:r></w:p>')
        name = f"S1_01-{number:02d}.xhtml"
        (jp / name).write_text(
            '<?xml version="1.0"?>\n<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head/><body>\n'
            f'<h1>{title}</h1>\n\n<p>本文</p>\n</body></html>\n', encoding="utf-8")
        chapters.append({"cn_title": title, "jp_file": name, "fname": name,
                         "h1_main": title, "ops": []})
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body>{"".join(paragraphs)}</w:body></w:document>')
    plan = {"work_id": "S1_01", "book_dir": "【S1_01】测试", "source_docx": str(docx),
            "jp_root": str(root), "jp_dir": jp.name, "chapters": chapters}
    plan_path = import_plan.write_plan(root / "plan.json", plan)
    return docx, jp, plan, plan_path


def file_bytes(root: Path):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


class ImportTextSafetyTests(unittest.TestCase):
    def run_command(self, args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return import_build_text.main(args)

    def test_invalid_chapter_paths_are_rejected_before_any_output(self):
        names = ("../../../escaped.xhtml", "../escaped.xhtml", r"..\escaped.xhtml",
                 "sub/file.xhtml", r"sub\file.xhtml", "C:escaped.xhtml", "C:/escaped.xhtml")
        for name in names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _, _, plan, plan_path = make_inputs(root)
                plan["chapters"][0]["fname"] = name
                import_plan.write_plan(plan_path, plan)
                before = file_bytes(root)
                out, report = root / "out", root / "report.txt"
                code = self.run_command([str(plan_path), "--out", str(out), "--report", str(report),
                                         "--apply", "--staging"])
                self.assertEqual(code, 2)
                self.assertEqual(file_bytes(root), before)
                self.assertFalse(out.exists())

    def test_case_aliases_are_not_two_distinct_chapter_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan, _ = make_inputs(Path(tmp), two_chapters=True)
            plan["chapters"][1]["fname"] = plan["chapters"][0]["fname"].lower()
            self.assertTrue(any("重复" in issue for issue in import_plan.validate_plan(plan)))

    def test_invalid_later_chapter_does_not_replace_earlier_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, plan, plan_path = make_inputs(root, two_chapters=True)
            plan["chapters"][1]["fname"] = "../../../escaped.xhtml"
            import_plan.write_plan(plan_path, plan)
            text = root / "out/OEBPS/Text"
            text.mkdir(parents=True)
            (text / "S1_01-01.xhtml").write_bytes(b"old first chapter")
            before = file_bytes(root)
            self.assertEqual(self.run_command([str(plan_path), "--out", str(root / "out"),
                                               "--apply", "--staging"]), 2)
            self.assertEqual(file_bytes(root), before)

    def test_existing_output_symlink_cannot_escape_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, plan_path = make_inputs(root, two_chapters=True)
            text = root / "out/OEBPS/Text"
            text.mkdir(parents=True)
            first = text / "S1_01-01.xhtml"
            first.write_bytes(b"old chapter")
            outside = root / "reference.xhtml"
            outside.write_bytes(b"read-only reference")
            try:
                (text / "S1_01-02.xhtml").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            before = file_bytes(root)
            self.assertEqual(self.run_command([str(plan_path), "--out", str(root / "out"),
                                               "--apply", "--staging"]), 2)
            self.assertEqual(file_bytes(root), before)

    def test_report_collisions_are_rejected_in_preview_and_apply(self):
        for apply in (False, True):
            for collision in ("docx", "plan", "japanese", "output"):
                with self.subTest(apply=apply, collision=collision), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    docx, jp, _, plan_path = make_inputs(root)
                    out = root / "out"
                    report = {"docx": docx, "plan": plan_path, "japanese": jp / "report.txt",
                              "output": out / "OEBPS/Text/S1_01-01.xhtml"}[collision]
                    before = file_bytes(root)
                    args = [str(plan_path), "--out", str(out), "--report", str(report)]
                    if apply:
                        args += ["--apply", "--staging"]
                    self.assertEqual(self.run_command(args), 2)
                    self.assertEqual(file_bytes(root), before)
                    self.assertFalse(out.exists())

    def test_report_hardlink_to_docx_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docx, _, _, plan_path = make_inputs(root)
            report = root / "report.txt"
            try:
                os.link(docx, report)
            except OSError as exc:
                self.skipTest(f"hardlinks unavailable: {exc}")
            original = docx.read_bytes()
            self.assertEqual(self.run_command([str(plan_path), "--out", str(root / "out"),
                                               "--report", str(report)]), 2)
            self.assertEqual(docx.read_bytes(), original)

    def test_invalid_apply_target_does_not_write_valid_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, plan_path = make_inputs(root)
            report = root / "report.txt"
            self.assertEqual(self.run_command([str(plan_path), "--out", str(root / "out"),
                                               "--report", str(report), "--apply"]), 2)
            self.assertFalse(report.exists())
            self.assertFalse((root / "out").exists())

    def test_report_write_failure_rolls_back_both_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, plan_path = make_inputs(root, two_chapters=True)
            out, report = root / "out", root / "report.txt"
            text = out / "OEBPS/Text"
            text.mkdir(parents=True)
            for number in (1, 2):
                (text / f"S1_01-{number:02d}.xhtml").write_bytes(f"old {number}".encode())
            report.write_bytes(b"old report")
            before = file_bytes(root)
            real_write = import_build_text.atomic_write_bytes
            written = []

            def fail_report(path, data):
                if path == report:
                    raise OSError("one-time report failure")
                written.append(path.name)
                return real_write(path, data)

            with patch.object(import_build_text, "atomic_write_bytes", side_effect=fail_report):
                code = self.run_command([str(plan_path), "--out", str(out), "--report", str(report),
                                         "--apply", "--staging"])
            self.assertEqual(code, 1)
            self.assertEqual(len(written), 2)
            self.assertEqual(file_bytes(root), before)
            self.assertFalse(list(root.rglob(".extract-transaction-*")))

    def test_preview_writes_report_without_creating_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, plan_path = make_inputs(root)
            report = root / "reports/render.txt"
            self.assertEqual(self.run_command([str(plan_path), "--out", str(root / "out"),
                                               "--report", str(report)]), 0)
            self.assertIn("S1_01-01.xhtml", report.read_text(encoding="utf-8"))
            self.assertFalse((root / "out").exists())


class ImportedNoteTests(unittest.TestCase):
    def test_mixed_note_markers_follow_reading_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docx, _, plan, _ = make_inputs(root, "先（译注：第一条）后【译注：第二条】")
            files, _, notes = import_build_text.build(plan, docx)
            text = root / "text"
            text.mkdir()
            for name, content in files.items():
                (text / name).write_text(content, encoding="utf-8")
            entry, issues = check_note_order.check_book("book", str(text), "S1_01-Note.xhtml")
            self.assertEqual(notes, ["第一条", "第二条"])
            self.assertEqual(entry["defined_order"], entry["appearance_order"])
            self.assertEqual(issues, [])

    def test_docx_conversion_preserves_note_entities_and_ruby(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docx, _, _, _ = make_inputs(root, "正文【译注：A &amp; B，|基文[注音]】")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = docx2epub.main([str(docx), "--unpacked", str(root / "out"),
                                       "--no-pack", "--apply", "--staging"])
            self.assertEqual(code, 0)
            note = next((root / "out").rglob("*-Note.xhtml"))
            tree = ET.fromstring(note.read_text(encoding="utf-8"))
            namespace = "{http://www.w3.org/1999/xhtml}"
            entry = tree.find(f".//{namespace}li")
            self.assertEqual(entry.text, "A & B，")
            self.assertEqual(entry.find(namespace + "ruby").text, "基文")
            self.assertEqual(entry.find(f"{namespace}ruby/{namespace}rt").text, "注音")


if __name__ == "__main__":
    unittest.main()
