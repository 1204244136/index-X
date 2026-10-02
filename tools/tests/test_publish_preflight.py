from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publish_preflight import main, validate_publication
from test_package_cache_epubs import make_book
from test_publish_auto import Fixture, BOOK_CN, BOOK_JP
import publish_auto


class PreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_no_books_and_missing_input_fail(self):
        source = self.root / "empty"
        source.mkdir()
        self.assertEqual(main(["--source", str(source)]), 1)
        self.assertEqual(main(["--source", str(source / "missing")]), 2)

    def test_alignment_reads_archive_not_previous_cache(self):
        cn, jp = self.root / "EPUB", self.root / "japanese"
        chapter = make_book(cn / "[S1_01]中文", layout=True)
        make_book(jp / "[S1_01]日文")
        self.assertTrue(validate_publication(cn, jp))
        chapter.write_text(chapter.read_text(encoding="utf-8").replace("</body>", "<p>额外行</p>\n</body>"), encoding="utf-8")
        self.assertFalse(validate_publication(cn, jp))

    def test_both_publication_directions_fail_before_mutation(self):
        for side in ("cache", "epub"):
            with self.subTest(side=side):
                fx = Fixture(self.root / side)
                source = fx.cache / "chinese-text" / BOOK_CN if side == "cache" else fx.epub / BOOK_CN
                target = source / "OEBPS/Text/S1_01-01_Chapter.xhtml"
                target.write_text("<html>", encoding="utf-8")
                manifest = (fx.cache / "manifest.json").read_bytes()
                mirror = fx.epub / BOOK_CN if side == "cache" else fx.cache / "chinese-text" / BOOK_CN
                mirror_file = mirror / "OEBPS/Text/S1_01-01_Chapter.xhtml"
                previous = mirror_file.read_bytes()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(publish_auto.main(fx.argv("--side", "chinese", "--no-upload")), 1)
                self.assertEqual(mirror_file.read_bytes(), previous)
                self.assertEqual((fx.cache / "manifest.json").read_bytes(), manifest)
                self.assertFalse((fx.cache / "packed-epubs").exists())

    def test_calibre_failure_is_propagated(self):
        make_book(self.root / "[S1_01]中文", layout=True)
        with patch("publish_preflight.subprocess.run") as run:
            run.return_value.returncode = 2
            self.assertEqual(main(["--source", str(self.root), "--calibre"]), 2)
            self.assertIn("--strict", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
