from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import shift_content_sequences
from shift_content_sequences import (  # noqa: E402
    apply_shift,
    plan_shift,
    reference_rewrites,
)


class ShiftContentSequencesTests(unittest.TestCase):
    def test_one_time_rename_failure_restores_adjacent_sources_and_references(self):
        for phase in ("stage", "commit"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                first, second = root / "S1_01-01.xhtml", root / "S1_01-02.xhtml"
                first.write_bytes(b'<a href="S1_01-02.xhtml">next</a>')
                second.write_bytes(b"second")
                metadata = root / "content.opf"
                metadata.write_bytes(b'<item href="S1_01-01.xhtml"/>')
                before = {path: path.read_bytes() for path in root.iterdir()}
                renames = plan_shift(root, "S1_01", 1)
                rewrites = reference_rewrites(root, renames)
                original_rename = Path.rename
                failed = False

                def fail_once(source, target):
                    nonlocal failed
                    hit = source == second if phase == "stage" else source.name.startswith(".shift-sequence-0002")
                    if hit and not failed:
                        failed = True
                        raise PermissionError("one-time rename failure")
                    return original_rename(source, target)

                with patch.object(Path, "rename", fail_once), self.assertRaises(PermissionError):
                    apply_shift(root, renames, rewrites)
                self.assertTrue(failed)
                self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, before)

    def test_reference_write_failure_rolls_back_earlier_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = root / "S1_01-01.xhtml", root / "S1_01-02.xhtml"
            for path in (first, second):
                path.write_bytes(b'<a href="S1_01-01.xhtml">text</a>')
            before = {path: path.read_bytes() for path in root.iterdir()}
            renames = plan_shift(root, "S1_01", 1)
            rewrites = reference_rewrites(root, renames)
            original_write = shift_content_sequences.atomic_write_bytes
            calls = []

            def fail_second(path, data):
                calls.append(path)
                if len(calls) == 2:
                    path.write_bytes(b"partial write")
                    raise OSError("one-time write failure")
                return original_write(path, data)

            with patch.object(shift_content_sequences, "atomic_write_bytes", side_effect=fail_second), \
                    self.assertRaises(OSError):
                apply_shift(root, renames, rewrites)
            self.assertEqual(len(calls), 2)
            self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, before)

    def test_temporary_name_collision_is_checked_before_reference_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "S1_01-01.xhtml"
            source.write_bytes(b'<a href="S1_01-01.xhtml">text</a>')
            (root / ".shift-sequence-0001-S1_01-01.xhtml").write_bytes(b"existing")
            before = {path: path.read_bytes() for path in root.iterdir()}
            renames = plan_shift(root, "S1_01", 1)
            with self.assertRaisesRegex(ValueError, "临时文件已存在"):
                apply_shift(root, renames, reference_rewrites(root, renames))
            self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, before)

    def test_adjacent_sequences_shift_once_and_references_follow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = root / "OEBPS" / "Text"
            text.mkdir(parents=True)
            zero = text / "S1_19-00_Prologue.xhtml"
            one = text / "S1_19-01_Chapter1.xhtml"
            page = text / "S1_19-01_p-001.xhtml"
            zero.write_text('<a href="S1_19-01_Chapter1.xhtml">next</a>', encoding="utf-8")
            one.write_text("<p>chapter</p>", encoding="utf-8")
            page.write_text("<p>page</p>", encoding="utf-8")
            opf = root / "OEBPS" / "content.opf"
            opf.write_text(
                '<item href="Text/S1_19-00_Prologue.xhtml"/>'
                '<item href="Text/S1_19-01_Chapter1.xhtml"/>',
                encoding="utf-8",
            )
            toc = text / "S1_19-p-toc.xhtml"
            toc.write_text('<a href="p-001.xhtml#toc-001">chapter</a>', encoding="utf-8")

            renames = plan_shift(root, "S1_19", 1)
            rewrites = reference_rewrites(root, renames)
            apply_shift(root, renames, rewrites)

            self.assertFalse(zero.exists())
            self.assertTrue((text / "S1_19-01_Prologue.xhtml").exists())
            self.assertTrue((text / "S1_19-02_Chapter1.xhtml").exists())
            self.assertTrue((text / "S1_19-02_p-001.xhtml").exists())
            self.assertIn("S1_19-01_Prologue.xhtml", opf.read_text(encoding="utf-8"))
            self.assertIn("S1_19-02_Chapter1.xhtml", opf.read_text(encoding="utf-8"))
            self.assertIn(
                "S1_19-02_Chapter1.xhtml",
                (text / "S1_19-01_Prologue.xhtml").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "S1_19-02_p-001.xhtml#toc-001",
                toc.read_text(encoding="utf-8"),
            )
            self.assertNotIn(
                "S1_19-02_S1_19-02_p-001.xhtml",
                toc.read_text(encoding="utf-8"),
            )

    def test_shift_refuses_sequence_below_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "S1_01-01_Chapter1.xhtml").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "必须从 01 开始"):
                plan_shift(root, "S1_01", -1)


if __name__ == "__main__":
    unittest.main()
