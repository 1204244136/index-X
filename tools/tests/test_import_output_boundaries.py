from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import bw_preprocess
import docx2epub
import epub2docx
import merge_bw_pages


def make_bw_directory(directory: Path, *, malformed: bool = False) -> Path:
    directory.mkdir(parents=True)
    page = directory / "p-001.xhtml"
    page.write_text(
        '<?xml version="1.0"?>\n<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head></head>'
        '<body class="p-text"><div class="main">\n<h1>第一章</h1>\n\n'
        + ('<p>正文</span>\n' if malformed else '<p>正文</p>\n')
        + '</div></body></html>\n', encoding="utf-8",
    )
    return page


def make_docx(path: Path, text: str = "正文|基文[注音]") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            '<w:r><w:t>第一章</w:t></w:r></w:p>'
            f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return path


class ImportOutputBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)

    def test_bw_default_is_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "source"
            page = make_bw_directory(directory)
            before = page.read_bytes()
            self.assertEqual(bw_preprocess.main([str(directory)]), 0)
            self.assertEqual(page.read_bytes(), before)

    def test_bw_directory_apply_requires_epub_or_explicit_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "source"
            page = make_bw_directory(directory)
            with self.assertRaises(SystemExit) as exit:
                bw_preprocess.main([str(directory), "--apply"])
            self.assertEqual(exit.exception.code, 2)
            self.assertEqual(bw_preprocess.main([str(directory), "--apply", "--staging"]), 0)
            self.assertTrue(page.is_file())

    def test_bw_invalid_later_page_blocks_all_directory_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "source"
            page = make_bw_directory(directory)
            page.write_text(page.read_text(encoding="utf-8").replace(
                "正文", '<span class="tcy">正文</span>'), encoding="utf-8")
            second = directory / "p-002.xhtml"
            second.write_text(page.read_text(encoding="utf-8").replace("</p>", "</span>"), encoding="utf-8")
            originals = {path: path.read_bytes() for path in (page, second)}
            self.assertEqual(bw_preprocess.main([str(directory), "--apply", "--staging"]), 1)
            for path, original in originals.items():
                self.assertEqual(path.read_bytes(), original)

    def test_bw_write_failure_restores_earlier_directory_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "source"
            first = make_bw_directory(directory)
            second = directory / "p-002.xhtml"
            second.write_bytes(first.read_bytes())
            originals = {path: path.read_bytes() for path in (first, second)}
            atomic_write = bw_preprocess._atomic_write_bytes
            failed = False

            def fail_second(destination, data):
                nonlocal failed
                if destination == second and not failed:
                    failed = True
                    raise OSError("simulated write failure")
                return atomic_write(destination, data)

            def transform(data, _rules):
                return data.replace(b"<p>", b'<p class="changed">'), True

            with patch.object(bw_preprocess, "transform_bytes", side_effect=transform), \
                    patch.object(bw_preprocess, "_atomic_write_bytes", side_effect=fail_second):
                with self.assertRaises(OSError):
                    bw_preprocess.process_dir(directory, [], False)
            self.assertTrue(failed)
            for path, original in originals.items():
                self.assertEqual(path.read_bytes(), original)
            self.assertFalse(list(directory.glob(".bw-xhtml-*")))

    def test_bw_epub_apply_requires_explicit_staging_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.epub"
            source.touch()
            for args in ((str(source), "--apply"),
                         (str(source), "--apply", "--out", str(Path(tmp) / "out"))):
                with self.subTest(args=args), self.assertRaises(SystemExit) as exit:
                    bw_preprocess.main(list(args))
                self.assertEqual(exit.exception.code, 2)

    def test_bw_rejects_cache_and_onedrive_writes_before_processing(self):
        forbidden = TOOLS.parent / ".cache" / "temporary.epub"
        with self.assertRaises(SystemExit) as exit:
            bw_preprocess.main(["source.epub", "--apply", "--staging", "--out", str(forbidden)])
        self.assertEqual(exit.exception.code, 2)

    def test_merge_default_is_preview_and_apply_validates_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_bw_directory(root / "pages")
            output = root / "out"
            args = [str(root / "pages"), "--book", "S1_01", "--out", str(output)]
            self.assertEqual(merge_bw_pages.main(args), 0)
            self.assertFalse(output.exists())
            self.assertEqual(merge_bw_pages.main([*args, "--apply", "--staging"]), 0)
            self.assertTrue((output / "S1_01-01.xhtml").is_file())

    def test_merge_invalid_xml_does_not_replace_old_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_bw_directory(root / "pages", malformed=True)
            output = root / "out"
            output.mkdir()
            old = output / "S1_01-01.xhtml"
            old.write_bytes(b"old output")
            self.assertEqual(merge_bw_pages.main([str(root / "pages"), "--book", "S1_01",
                "--out", str(output), "--apply", "--staging"]), 1)
            self.assertEqual(old.read_bytes(), b"old output")

    def test_merge_apply_requires_explicit_output_and_staging_for_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            for args in ((tmp, "--apply"), (tmp, "--apply", "--out", str(Path(tmp) / "out"))):
                with self.subTest(args=args), self.assertRaises(SystemExit) as exit:
                    merge_bw_pages.main(list(args))
                self.assertEqual(exit.exception.code, 2)

    def test_docx_default_preview_does_not_create_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = make_docx(Path(tmp) / "[S1_01]测试.docx")
            self.assertEqual(docx2epub.main([str(source)]), 0)
            self.assertFalse(list(Path(tmp).glob("*.epub")))

    def test_docx_pack_and_no_pack_validate_complete_generated_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_docx(root / "[S1_01]测试.docx")
            output, unpacked = root / "out", root / "unpacked"
            self.assertEqual(docx2epub.main([str(source), "--out", str(output), "--unpacked", str(unpacked),
                                          "--apply", "--staging"]), 0)
            self.assertTrue((output / "[S1_01]测试.epub").is_file())
            self.assertTrue((unpacked / "[S1_01]测试" / "mimetype").is_file())
            no_pack = root / "no-pack"
            self.assertEqual(docx2epub.main([str(source), "--unpacked", str(no_pack), "--no-pack",
                                          "--apply", "--staging"]), 0)
            self.assertTrue((no_pack / "[S1_01]测试" / "mimetype").is_file())

    def test_docx_invalid_generated_xml_does_not_write_pack_or_unpacked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_docx(root / "[S1_01]测试.docx")
            for no_pack in (False, True):
                output = root / ("no-pack" if no_pack else "pack")
                args = [str(source), "--unpacked", str(output), "--apply", "--staging"]
                args += ["--no-pack"] if no_pack else ["--out", str(output)]
                with patch.object(docx2epub, "render_content", return_value="<html><p>invalid</html>"):
                    self.assertEqual(docx2epub.main(args), 1)
                self.assertFalse(output.exists())

    def test_docx_apply_requires_explicit_safe_outputs(self):
        for args in (("source.docx", "--apply"),
                     ("source.docx", "--apply", "--out", str(TOOLS.parent / ".cache" / "out"), "--staging")):
            with self.subTest(args=args), self.assertRaises(SystemExit) as exit:
                docx2epub.main(list(args))
            self.assertEqual(exit.exception.code, 2)

    def test_epub_preview_requires_valid_container_but_no_calibre(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.epub"
            with zipfile.ZipFile(bad, "w") as archive:
                archive.writestr("page.xhtml", "<html/>")
            with patch.object(epub2docx, "find_ebook_convert") as find:
                self.assertEqual(epub2docx.main([str(bad)]), 1)
                find.assert_not_called()
            self.assertFalse((Path(tmp) / "bad.docx").exists())

    def test_epub_converter_failure_keeps_existing_docx(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_docx(root / "[S1_01]测试.docx")
            docx2epub.main([str(source), "--out", str(root / "epubs"), "--apply", "--staging"])
            epub = root / "epubs" / "[S1_01]测试.epub"
            output = root / "docxs"
            output.mkdir()
            old = output / "[S1_01]测试.docx"
            old.write_bytes(b"old document")
            with patch.object(epub2docx, "find_ebook_convert", return_value="fake-converter"), \
                    patch.object(epub2docx.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "conversion failed")):
                self.assertEqual(epub2docx.main([str(epub), "--out", str(output), "--apply", "--staging"]), 1)
            self.assertEqual(old.read_bytes(), b"old document")
            self.assertFalse(list(epub.parent.glob("*.ruby.epub")))

    def test_epub_apply_keeps_intermediate_in_explicit_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_docx(root / "[S1_01]测试.docx")
            docx2epub.main([str(source), "--out", str(root / "epubs"), "--apply", "--staging"])
            epub = root / "epubs" / "[S1_01]测试.epub"
            output = root / "docxs"

            def convert(command, **_kwargs):
                make_docx(Path(command[2]))
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch.object(epub2docx, "find_ebook_convert", return_value="fake-converter"), \
                    patch.object(epub2docx.subprocess, "run", side_effect=convert):
                self.assertEqual(epub2docx.main([str(epub), "--out", str(output), "--apply", "--staging", "--keep-src-epub"]), 0)
            self.assertTrue((output / "[S1_01]测试.docx").is_file())
            self.assertTrue((output / "[S1_01]测试.ruby.epub").is_file())
            self.assertFalse(list(epub.parent.glob("*.ruby.epub")))

    def test_epub_apply_requires_explicit_output_before_conversion(self):
        with self.assertRaises(SystemExit) as exit:
            epub2docx.main(["source.epub", "--apply"])
        self.assertEqual(exit.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
