from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from bw_preprocess import load_rules, process_epub  # noqa: E402
from path_safety import (  # noqa: E402
    UnsafeArchivePath,
    archive_member_destination,
    is_extract_artifact,
    validate_archive_member_name,
)
import path_safety  # noqa: E402


class PathSafetyTests(unittest.TestCase):
    def test_report_target_protects_inputs_and_directory_trees_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            plan = root / "plan.json"
            plan.write_bytes(b"input plan")
            for path in (plan, root / "nested/../plan.json", source / "new/report.md"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    path_safety.require_report_target(path, protected_files=[plan], protected_dirs=[source])
            allowed = root / "reports/review.md"
            self.assertEqual(path_safety.require_report_target(allowed, protected_files=[plan],
                                                              protected_dirs=[source]), allowed.resolve())
            self.assertEqual(plan.read_bytes(), b"input plan")
            self.assertFalse(allowed.parent.exists())

    def test_report_target_rejects_existing_file_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "input.txt"
            original.write_bytes(b"protected input")
            alias = root / "report.md"
            alias.hardlink_to(original)
            with self.assertRaises(ValueError):
                path_safety.require_report_target(alias, protected_files=[original])
            self.assertEqual(original.read_bytes(), b"protected input")
            self.assertEqual(alias.read_bytes(), b"protected input")

    def test_report_target_rejects_symlink_into_protected_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            alias = root / "report-alias"
            try:
                alias.symlink_to(source, target_is_directory=True)
            except OSError as exc:
                if sys.platform != "win32":
                    self.skipTest(f"当前环境不支持创建目录符号链接：{exc}")
                import _winapi
                _winapi.CreateJunction(str(source), str(alias))
            with self.assertRaises(ValueError):
                path_safety.require_report_target(alias / "report.md", protected_dirs=[source])
            self.assertFalse((source / "report.md").exists())

    def test_report_target_rejects_directory_or_file_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "existing-report.md"
            existing.write_bytes(b"keep this report")
            for target in (root, existing / "child.md"):
                with self.subTest(path=target), self.assertRaises(ValueError):
                    path_safety.require_report_target(target)
            self.assertEqual(existing.read_bytes(), b"keep this report")

    def test_archive_member_paths_are_rejected(self):
        unsafe_names = (
            "../escaped.txt",
            "OEBPS/../../escaped.txt",
            "/absolute.txt",
            "C:/drive.txt",
            r"OEBPS\..\escaped.txt",
            "OEBPS/file.txt:stream",
        )
        for name in unsafe_names:
            with self.subTest(name=name):
                with self.assertRaises(UnsafeArchivePath):
                    validate_archive_member_name(name)

    def test_archive_destination_stays_under_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "out"
            destination = archive_member_destination(root, "OEBPS/Text/a.xhtml")
            self.assertEqual(destination, root / "OEBPS" / "Text" / "a.xhtml")
            self.assertTrue(destination.is_relative_to(root.resolve()))

    def test_extract_marker_must_be_checked_in_every_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orphan = root / "chinese-text" / ".extract-orphan" / "OEBPS" / "a.xhtml"
            nested = root / "chinese-text" / "book" / ".extract-step" / "a.xhtml"
            normal = root / "chinese-text" / "book" / "a.xhtml"
            self.assertTrue(is_extract_artifact(orphan, root=root))
            self.assertTrue(is_extract_artifact(nested, root=root))
            self.assertFalse(is_extract_artifact(normal, root=root))

    def test_process_epub_blocks_traversal_before_writing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub_path = root / "source.epub"
            out_path = root / "out.epub"
            unpacked = root / "unpacked"
            with zipfile.ZipFile(epub_path, "w") as archive:
                archive.writestr("mimetype", b"application/epub+zip")
                archive.writestr("../escaped.txt", b"escaped")

            stats = process_epub(
                epub_path,
                load_rules(None),
                out_path,
                dry_run=False,
                book_id=None,
                merge_pages=False,
                unpacked_dir=unpacked,
            )

            self.assertTrue(stats["blocked"])
            self.assertTrue(any("路径不安全" in issue for _, issue in stats["issues"]))
            self.assertFalse((root / "escaped.txt").exists())
            self.assertFalse(out_path.exists())
            self.assertFalse(unpacked.exists())


if __name__ == "__main__":
    unittest.main()
