"""Run real entry points from a clone with an archive and no private sources."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_package_cache_epubs import make_book


TOOLS = Path(__file__).resolve().parents[1]


class CloneWithoutReferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.clone = Path(cls.temporary.name)
        target = cls.clone / "tools"
        target.mkdir()
        for pattern in ("*.py", "*.json"):
            for source in TOOLS.glob(pattern):
                shutil.copy2(source, target / source.name)
        docs = cls.clone / "docs"
        docs.mkdir()
        shutil.copy2(TOOLS.parent / "docs/translation-name-rulings.md", docs)
        make_book(cls.clone / "EPUB/【S1_01】中文X", layout=True)
        (cls.clone / "empty-jp").mkdir()

    def run_cli(self, tool, *args):
        return subprocess.run(
            [sys.executable, str(self.clone / "tools" / tool), *args],
            cwd=self.clone, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def test_chinese_checks_and_packaging_need_no_reference_cache(self):
        commands = (
            ("check_epub_health.py", "--strict"),
            ("check_alignment.py", "--strict"),
            ("check_note_order.py",),
            ("check_translation_spec.py",),
            ("publish_preflight.py",),
            ("package_cache_epubs.py", "--source", "EPUB", "--output", "output/epubs"),
            ("search_text.py", "正文", "--side", "cn", "--no-pair"),
        )
        for command in commands:
            with self.subTest(command=command):
                result = self.run_cli(*command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.clone / ".cache/epub-work/chinese-text").exists())
        self.assertFalse((self.clone / ".cache/epub-work/japanese-text").exists())

    def test_required_reference_commands_explain_the_missing_input(self):
        commands = (
            ("normalize_paired.py", "--dry-run"),
            ("fix_legacy_pagebreak_br.py", "--dry-run"),
            ("restore_cn_scene_breaks.py", "--dry-run"),
            ("sync_pb_tags.py", "--dry-run"),
            ("check_term_anchors.py", "--strict"),
            ("search_text.py", "原文", "--side", "jp"),
            ("japanese_lookup.py", "S1_01", "01", "6"),
        )
        for command in commands:
            with self.subTest(command=command):
                result = self.run_cli(*command)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("日文", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_empty_japanese_directory_does_not_satisfy_bilingual_gates(self):
        commands = (
            (("check_term_anchors.py", "--strict", "--jp-dir", "empty-jp"), 2),
            (("publish_preflight.py", "--jp-root", "empty-jp"), 1),
            (("check_alignment.py", "--jp-root", "empty-jp", "--require-jp"), 2),
        )
        for command, expected in commands:
            with self.subTest(command=command):
                result = self.run_cli(*command)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
