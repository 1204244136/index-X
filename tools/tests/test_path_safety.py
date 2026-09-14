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


class PathSafetyTests(unittest.TestCase):
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
