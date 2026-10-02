from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import split_s5_epubs as splitter

SPECS = [{"vol": 1, "splits": [("S5_01_01", "作品一", 1, 1), ("S5_01_02", "作品二", 2, 2)]}]


def create_source(source: Path, pages: tuple[int, ...] = (1, 2), *, vol: int = 1) -> Path:
    source.mkdir(parents=True, exist_ok=True)
    path = source / f"とある魔術の禁書目録 外典書庫（{chr(0xFF10 + vol)}）.epub"
    entries = {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="item/standard.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        "item/style/book-style.css": b"p { margin: 0; }",
    }
    manifest = ['<item id="css" href="style/book-style.css" media-type="text/css"/>']
    spine = []
    for number in pages:
        name = f"p-{number:03d}.xhtml"
        entries[f"item/xhtml/{name}"] = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
            '<link rel="stylesheet" href="../style/book-style.css"/></head>'
            '<body class="p-text"><div class="main">\n'
            f'<h1>章{number}</h1>\n\n<p>正文{number}</p>\n</div></body></html>\n'
        ).encode("utf-8")
        manifest.append(f'<item id="page{number}" href="xhtml/{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="page{number}"/>')
    entries["item/standard.opf"] = (
        '<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">'
        '<metadata><dc:title>原书</dc:title></metadata><manifest>\n'
        + "\n".join(manifest) + '\n</manifest><spine>\n'
        + "\n".join(spine) + '\n</spine></package>'
    ).encode("utf-8")
    with zipfile.ZipFile(path, "w") as archive:
        for info in splitter._zip_infos(entries):
            archive.writestr(info, entries[info.filename])
    return path


class SplitPreflightTests(unittest.TestCase):
    def test_missing_source_directory_and_missing_volume_are_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            packed, unpacked = root / "packed", root / "unpacked"
            with patch.object(splitter, "SPLIT_SPECS", SPECS):
                self.assertEqual(splitter.split_and_process_s5(source, packed, unpacked, apply=True), 1)
                source.mkdir()
                self.assertEqual(splitter.split_and_process_s5(source, packed, unpacked, apply=True), 1)
            self.assertFalse(packed.exists())
            self.assertFalse(unpacked.exists())

    def test_empty_plan_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "没有找到"):
                splitter.prepare_split_plans(Path(tmp), specs=[])

    def test_missing_page_blocks_the_whole_batch_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_source(root / "source", (1,))
            packed, unpacked = root / "packed", root / "unpacked"
            with patch.object(splitter, "SPLIT_SPECS", SPECS):
                self.assertEqual(splitter.split_and_process_s5(root / "source", packed, unpacked, apply=True), 1)
            self.assertFalse(packed.exists())
            self.assertFalse(unpacked.exists())

    def test_later_missing_volume_does_not_write_earlier_plans(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_source(root / "source")
            specs = [*SPECS, {"vol": 2, "splits": [("S5_02_01", "后卷", 1, 1)]}]
            with patch.object(splitter, "SPLIT_SPECS", specs):
                self.assertEqual(splitter.split_and_process_s5(root / "source", root / "packed", root / "unpacked", apply=True), 1)
            self.assertFalse((root / "packed").exists())

    def test_contract_failure_preserves_existing_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_source(root / "source")
            packed, unpacked = root / "packed", root / "unpacked"
            packed.mkdir()
            old = packed / "[S5_01_01]作品一.epub"
            old.write_bytes(b"previous output")
            with patch.object(splitter, "SPLIT_SPECS", SPECS), \
                    patch.object(splitter, "artifact_contract_issues", return_value=[("x.xhtml", "bad contract")]):
                self.assertEqual(splitter.split_and_process_s5(root / "source", packed, unpacked, apply=True), 1)
            self.assertEqual(old.read_bytes(), b"previous output")
            self.assertFalse(unpacked.exists())

    def test_default_preview_checks_all_plans_without_creating_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            create_source(source)
            packed, unpacked = root / "packed", root / "unpacked"
            with patch.object(splitter, "SPLIT_SPECS", SPECS):
                self.assertEqual(splitter.split_and_process_s5(source, packed, unpacked), 0)
            self.assertFalse(packed.exists())
            self.assertFalse(unpacked.exists())

    def test_apply_outputs_valid_packages_and_unpacked_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_source(root / "source")
            packed, unpacked = root / "packed", root / "unpacked"
            with patch.object(splitter, "SPLIT_SPECS", SPECS):
                self.assertEqual(splitter.split_and_process_s5(root / "source", packed, unpacked, apply=True), 0)
            self.assertEqual(len(list(packed.glob("*.epub"))), 2)
            for epub in packed.glob("*.epub"):
                with zipfile.ZipFile(epub) as archive:
                    self.assertEqual(archive.infolist()[0].filename, "mimetype")
                    self.assertEqual(archive.infolist()[0].compress_type, zipfile.ZIP_STORED)
                    entries = {name: archive.read(name) for name in archive.namelist()}
                    work = epub.stem.split("]", 1)[0][1:]
                    self.assertEqual(splitter.artifact_contract_issues(entries, work), [])
                    self.assertIn(f"item/xhtml/{work}-01.xhtml", entries)
                self.assertTrue((unpacked / epub.stem / "mimetype").is_file())
            self.assertFalse(list(packed.glob(".split-s5-*")))
            self.assertFalse(list(unpacked.glob(".split-s5-*")))

    def test_output_roots_cannot_overlap_source_or_each_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / "source"
            for packed, unpacked in ((source / "out", root / "unpacked"),
                                     (root / "out", root / "out" / "inner")):
                with self.subTest(packed=packed), self.assertRaises(ValueError):
                    splitter.validate_outputs(source, packed, unpacked)

    def test_cache_and_onedrive_output_roots_are_rejected_before_writes(self):
        source = TOOLS.parent / "source-fixture"
        for packed in (TOOLS.parent / ".cache" / "split-output", TOOLS.parent / "OneDrive" / "split-output"):
            with self.subTest(packed=packed), self.assertRaises(ValueError):
                splitter.validate_outputs(source.resolve(), packed.resolve(), (TOOLS.parent / "split-unpacked").resolve())


class SplitAtomicOutputTests(unittest.TestCase):
    def test_replace_failure_restores_old_epub_and_unpacked_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            create_source(source)
            plans = splitter.prepare_split_plans(source, specs=SPECS)
            packed, unpacked = root / "packed", root / "unpacked"
            packed.mkdir()
            unpacked.mkdir()
            old_epub = packed / f"{plans[0].basename}.epub"
            old_epub.write_bytes(b"old epub")
            old_book = unpacked / plans[0].basename
            old_book.mkdir()
            (old_book / "old.txt").write_bytes(b"old unpacked")
            actual_replace = os.replace
            failed = False

            def fail_install(source_path, destination_path):
                nonlocal failed
                if Path(source_path).name == "1" and not failed:
                    failed = True
                    raise OSError("simulated second book installation failure")
                return actual_replace(source_path, destination_path)

            with patch.object(splitter.os, "replace", side_effect=fail_install):
                with self.assertRaises(OSError):
                    splitter.apply_split_plans(plans, packed, unpacked)
            self.assertTrue(failed)
            self.assertEqual(old_epub.read_bytes(), b"old epub")
            self.assertEqual((old_book / "old.txt").read_bytes(), b"old unpacked")
            self.assertEqual(sorted(path.name for path in packed.iterdir()), [old_epub.name])
            self.assertEqual(sorted(path.name for path in unpacked.iterdir()), [old_book.name])

    def test_cli_requires_explicit_output_roots(self):
        result = subprocess.run([sys.executable, str(TOOLS / "split_s5_epubs.py"), "missing"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--packed-out", result.stderr)
        self.assertIn("--unpacked-out", result.stderr)


if __name__ == "__main__":
    unittest.main()
