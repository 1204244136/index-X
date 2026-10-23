"""Exercise paired-normalization scope through the real CLI."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]


def xhtml() -> str:
    return "\n".join([
        '<?xml version="1.0" encoding="utf-8"?>', '<!DOCTYPE html>',
        '<html><head></head><body>', '<h1>章</h1>', '', '',
        '<p>内容</p>', '</body></html>', '',
    ])


class NormalizePairedScopeCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "cn"
        self.jp_root = Path(self.tmp.name) / "jp"
        self.paths = {}
        for wid in ("S1_01", "S1_02"):
            for side, root in (("cn", self.root), ("jp", self.jp_root)):
                path = root / f"【{wid}】书" / "Text" / f"{wid}-01.xhtml"
                path.parent.mkdir(parents=True)
                path.write_text(xhtml(), encoding="utf-8")
                self.paths[side, wid] = path

    def run_cli(self, *args, root=None, jp_root=None, apply=True):
        return subprocess.run(
            [sys.executable, str(TOOLS / "normalize_paired.py"),
             "--root", str(root or self.root),
             "--jp-root", str(jp_root or self.jp_root),
             "--staging", *(["--apply"] if apply else []), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8",
        )

    def snapshot(self):
        return {path: path.read_bytes() for path in self.paths.values()}

    def test_book_selection_leaves_other_pair_unchanged(self):
        before = self.snapshot()
        result = self.run_cli("--book", "S1_01")
        self.assertEqual(result.returncode, 0, result.stderr)
        for (side, wid), path in self.paths.items():
            with self.subTest(side=side, book=wid):
                if wid == "S1_01":
                    self.assertNotEqual(path.read_bytes(), before[path])
                else:
                    self.assertEqual(path.read_bytes(), before[path])

    def test_file_selection_leaves_sibling_and_other_pair_unchanged(self):
        for side in ("cn", "jp"):
            sibling = self.paths[side, "S1_01"].with_name("S1_01-02.xhtml")
            sibling.write_text(xhtml(), encoding="utf-8")
            self.paths[side, "sibling"] = sibling
        before = self.snapshot()
        result = self.run_cli("--file", self.paths["cn", "S1_01"])
        self.assertEqual(result.returncode, 0, result.stderr)
        for (side, key), path in self.paths.items():
            with self.subTest(side=side, target=key):
                if key == "S1_01":
                    self.assertNotEqual(path.read_bytes(), before[path])
                else:
                    self.assertEqual(path.read_bytes(), before[path])

    def test_single_book_roots_process_the_pair(self):
        before = self.snapshot()
        result = self.run_cli(root=self.paths["cn", "S1_01"].parents[1],
                              jp_root=self.paths["jp", "S1_01"].parents[1])
        self.assertEqual(result.returncode, 0, result.stderr)
        for (side, wid), path in self.paths.items():
            with self.subTest(side=side, book=wid):
                if wid == "S1_01":
                    self.assertNotEqual(path.read_bytes(), before[path])
                else:
                    self.assertEqual(path.read_bytes(), before[path])

    def test_book_selection_ignores_unrelated_duplicate_books_and_headers(self):
        for root in (self.root, self.jp_root):
            duplicate = root / "【S1_02】重复" / "S1_02-01.xhtml"
            duplicate.parent.mkdir()
            duplicate.write_bytes(b"not XML")
            self.paths[str(root), "duplicate_book"] = duplicate
            path = self.paths["cn" if root == self.root else "jp", "S1_02"]
            duplicate_header = path.with_name("S1_02-01_Duplicate.xhtml")
            duplicate_header.write_bytes(b"not XML")
            self.paths[str(root), "duplicate_header"] = duplicate_header
        before = self.snapshot()
        result = self.run_cli("--book", "S1_01")
        self.assertEqual(result.returncode, 0, result.stderr)
        for key, path in self.paths.items():
            if key[1] != "S1_01":
                self.assertEqual(path.read_bytes(), before[path])

    def test_file_selection_ignores_unrelated_malformed_and_duplicate_headers(self):
        for side in ("cn", "jp"):
            for suffix in ("a", "b"):
                path = self.paths[side, "S1_01"].with_name(f"S1_01-02_{suffix}.xhtml")
                path.write_bytes(b"not XML")
                self.paths[side, suffix] = path
        before = self.snapshot()
        result = self.run_cli("--file", self.paths["cn", "S1_01"])
        self.assertEqual(result.returncode, 0, result.stderr)
        for key, path in self.paths.items():
            if key[1] != "S1_01":
                self.assertEqual(path.read_bytes(), before[path])

    def test_selected_duplicate_header_refuses_all_writes(self):
        duplicate = self.paths["jp", "S1_01"].with_name("S1_01-01_Duplicate.xhtml")
        duplicate.write_text(xhtml(), encoding="utf-8")
        self.paths["jp", "duplicate"] = duplicate
        before = self.snapshot()
        result = self.run_cli("--file", self.paths["cn", "S1_01"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("同侧重复表头", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_targets_and_directories_refuse_all_writes(self):
        unrecognized = self.paths["cn", "S1_01"].with_name("page.xhtml")
        unrecognized.write_text(xhtml(), encoding="utf-8")
        self.paths["cn", "unrecognized"] = unrecognized
        before = self.snapshot()
        cases = (
            (("--book", "S1_01", "--book", "S1_99"), "未知中文作品号"),
            (("--book", "S1"), "完整作品号"),
            (("--file", self.paths["cn", "S1_01"].with_name("missing.xhtml")), "存在的中文 XHTML"),
            (("--file", self.paths["cn", "S1_01"].parent), "存在的中文 XHTML"),
            (("--file", unrecognized), "可识别的 XHTML"),
        )
        for args, message in cases:
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual(self.snapshot(), before)

    def test_outside_file_refuses_all_writes(self):
        outside = Path(self.tmp.name) / "S1_01-01.xhtml"
        outside.write_text(xhtml(), encoding="utf-8")
        before = self.snapshot()
        original_outside = outside.read_bytes()
        result = self.run_cli("--file", self.paths["cn", "S1_01"], "--file", outside)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("超出中文 --root", result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(outside.read_bytes(), original_outside)

    def test_file_symlink_cannot_escape_root(self):
        outside = Path(self.tmp.name) / "S1_01-03.xhtml"
        outside.write_text(xhtml(), encoding="utf-8")
        alias = self.paths["cn", "S1_01"].with_name("S1_01-03.xhtml")
        try:
            alias.symlink_to(outside)
        except OSError:
            self.skipTest("平台不允许创建 symlink")
        before = self.snapshot()
        original_outside = outside.read_bytes()
        result = self.run_cli("--file", alias)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("超出中文 --root", result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(outside.read_bytes(), original_outside)

    def test_book_and_file_selectors_intersect(self):
        before = self.snapshot()
        result = self.run_cli("--book", "S1_01", "--file", self.paths["cn", "S1_01"],
                              "--file", self.paths["cn", "S1_02"])
        self.assertEqual(result.returncode, 0, result.stderr)
        for (side, wid), path in self.paths.items():
            with self.subTest(side=side, book=wid):
                if wid == "S1_01":
                    self.assertNotEqual(path.read_bytes(), before[path])
                else:
                    self.assertEqual(path.read_bytes(), before[path])

    def test_empty_intersection_refuses_all_writes(self):
        before = self.snapshot()
        result = self.run_cli("--book", "S1_01", "--file", self.paths["cn", "S1_02"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("没有交集", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_intersection_excludes_unrelated_duplicate_books_before_validation(self):
        for root in (self.root, self.jp_root):
            (root / "【S1_02】重复").mkdir()
        original = {self.paths[side, "S1_02"]: self.paths[side, "S1_02"].read_bytes()
                    for side in ("cn", "jp")}
        result = self.run_cli("--book", "S1_01", "--file", self.paths["cn", "S1_01"],
                              "--file", self.paths["cn", "S1_02"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({path: path.read_bytes() for path in original}, original)

    def test_repeated_books_use_complete_s5_and_s6_ids(self):
        before = self.snapshot()
        targets = []
        for wid in ("S5_01_03", "S6_22.06.10"):
            for root in (self.root, self.jp_root):
                path = root / f"【{wid}】书" / f"{wid}-02.xhtml"
                path.parent.mkdir()
                path.write_text(xhtml(), encoding="utf-8")
                targets.append(path)
        originals = {path: path.read_bytes() for path in targets}
        result = self.run_cli("--book", "S5_01_03", "--book", "s6_22.06.10")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(path.read_bytes() != originals[path] for path in targets))
        self.assertEqual(self.snapshot(), before)

    def test_known_book_without_japanese_book_keeps_original_skip_behavior(self):
        before = self.snapshot()
        result = self.run_cli("--file", self.paths["cn", "S1_01"],
                              jp_root=self.paths["jp", "S1_02"].parents[1])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("待改写文件：0", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_known_structure_exception_is_still_skipped(self):
        paths = []
        for root in (self.root, self.jp_root):
            path = root / "【S2_14】书" / "S2_14-02.xhtml"
            path.parent.mkdir()
            path.write_bytes(b"not XML")
            paths.append(path)
        originals = {path: path.read_bytes() for path in paths}
        result = self.run_cli("--file", paths[0])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("已确认结构特例", result.stdout)
        self.assertEqual({path: path.read_bytes() for path in paths}, originals)

    def test_selected_preview_plans_changes_without_writing(self):
        before = self.snapshot()
        result = self.run_cli("--file", self.paths["cn", "S1_01"], apply=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("待改写文件：2", result.stdout)
        self.assertIn("预览模式", result.stdout)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
