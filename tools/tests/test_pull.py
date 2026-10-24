from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from manifest import load_manifest, scan_cache  # noqa: E402
from sync_lock import cache_lock  # noqa: E402
from test_publish_auto import BOOK_CN, BOOK_CN2, BOOK_JP, Fixture  # noqa: E402

POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(POWERSHELL, "PowerShell is required for pull.ps1 integration tests")
class PullTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fx = Fixture(Path(self.temporary.name))
        self.fx.onedrive_cn.mkdir()
        self.fx.onedrive_jp.mkdir()
        self.key = f"chinese-text/{BOOK_CN}"
        self.cache_book = self.fx.cache / self.key
        self.chapter = Path("OEBPS/Text/S1_01-01_Chapter.xhtml")
        (self.fx.cache / "pull-state.tsv").write_text("", encoding="utf-8")

    def external(self, name=BOOK_CN, text="<p>外部更新</p>", *, japanese=False):
        stage = self.fx.root / "external" / name
        Fixture._populate(stage, text)
        destination = (self.fx.onedrive_jp if japanese else self.fx.onedrive_cn) / f"{name}.epub"
        with zipfile.ZipFile(destination, "w") as archive:
            for path in stage.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(stage).as_posix())
        return destination

    def run_pull(self, *extra, shell=None, cwd=None):
        return subprocess.run(
            [shell or POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(TOOLS / "pull.ps1"),
             "-CacheDirectory", str(self.fx.cache), "-EpubDirectory", str(self.fx.epub),
             "-ChineseSourceDirectory", str(self.fx.onedrive_cn),
             "-JapaneseSourceDirectory", str(self.fx.onedrive_jp), *extra],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, cwd=cwd,
        )

    def snapshot(self):
        return {p.relative_to(self.fx.root).as_posix(): p.read_bytes()
                for root in (self.fx.cache, self.fx.epub)
                for p in root.rglob("*") if p.is_file()
                and not p.relative_to(root).parts[0].startswith(".sync")}

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unpublished_cache_changes_block_whole_selected_batch_even_with_force(self):
        self.external(text="<p>远程甲</p>")
        self.external(BOOK_CN2, "<p>远程乙</p>")
        chapter2 = self.fx.cache / "chinese-text" / BOOK_CN2 / "OEBPS/Text/S1_02-01_Chapter.xhtml"
        chapter2.write_text(Fixture.xhtml("<p>另一对话的本地内容</p>"), encoding="utf-8")
        before = self.snapshot()
        result = self.run_pull("-Side", "chinese", "-Force")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("未发布变化", result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_unpublished_additions_and_deletions_are_preserved(self):
        self.external()
        target = self.cache_book / self.chapter
        for change in ("added", "deleted"):
            with self.subTest(change=change):
                original = target.read_bytes()
                added = self.cache_book / "unpublished.txt"
                if change == "added":
                    added.write_text("local", encoding="utf-8")
                else:
                    target.unlink()
                before = self.snapshot()
                result = self.run_pull("-Side", "chinese", "-OnlyBooks", self.key)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(self.snapshot(), before)
                added.unlink(missing_ok=True)
                target.write_bytes(original)

    def test_sync_to_epub_checks_archive_before_replacing_cache(self):
        self.external()
        (self.fx.epub / BOOK_CN / self.chapter).write_text(Fixture.xhtml("<p>归档未发布修改</p>"), encoding="utf-8")
        before = self.snapshot()
        result = self.run_pull("-Side", "chinese", "-SyncToEpub", "-OnlyBooks", self.key)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("归档", result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_identical_local_changes_already_in_external_book_are_safe(self):
        text = "<p>双方已含相同修改</p>"
        self.external(text=text)
        for book in (self.cache_book, self.fx.epub / BOOK_CN):
            (book / self.chapter).write_text(Fixture.xhtml(text), encoding="utf-8")
        self.assert_success(self.run_pull("-Side", "chinese", "-SyncToEpub", "-OnlyBooks", self.key))
        self.assertEqual(load_manifest(self.fx.cache), scan_cache(self.fx.cache))

    def test_exact_selection_intersects_side_and_pattern_and_keeps_other_baselines(self):
        self.external()
        self.external(BOOK_CN2, "<p>不应拉取</p>")
        self.external(BOOK_JP, "<p>拉取しない</p>", japanese=True)
        unrelated = self.fx.cache / "chinese-text" / BOOK_CN2 / "unpublished.txt"
        unrelated.write_text("pending", encoding="utf-8")
        baseline = load_manifest(self.fx.cache)
        unselected_before = {k: v for k, v in self.snapshot().items() if BOOK_CN2 in k or BOOK_JP in k}
        keys = ",".join((self.key, f"chinese-text/{BOOK_CN2}", f"japanese-text/{BOOK_JP}"))
        self.assert_success(self.run_pull("-Side", "chinese", "-Pattern", "*S1_01*", "-OnlyBooks", keys))
        self.assertEqual(unselected_before, {k: v for k, v in self.snapshot().items() if BOOK_CN2 in k or BOOK_JP in k})
        after = load_manifest(self.fx.cache)
        self.assertEqual({k: v for k, v in baseline.items() if not k.startswith(self.key + "/")},
                         {k: v for k, v in after.items() if not k.startswith(self.key + "/")})
        self.assertNotIn(BOOK_CN2, (self.fx.cache / "pull-state.tsv").read_text(encoding="utf-8-sig"))

    def test_first_scoped_pull_does_not_baseline_other_existing_cache_books(self):
        self.external(text="<p>中文A</p>")
        (self.fx.cache / "manifest.json").unlink()
        self.assert_success(self.run_pull("-Side", "chinese", "-OnlyBooks", self.key))
        self.assertTrue(load_manifest(self.fx.cache))
        self.assertTrue(all(k.startswith(self.key + "/") for k in load_manifest(self.fx.cache)))

    def test_first_import_into_empty_cache_and_archive(self):
        self.external()
        self.external(BOOK_JP, "<p>日本語</p>", japanese=True)
        shutil.rmtree(self.fx.cache)
        shutil.rmtree(self.fx.epub)
        self.fx.epub.mkdir()
        self.assert_success(self.run_pull("-OnlyBooks", self.key + f",japanese-text/{BOOK_JP}", "-SyncToEpub"))
        self.assertEqual((self.cache_book / self.chapter).read_bytes(),
                         (self.fx.epub / BOOK_CN / self.chapter).read_bytes())
        self.assertEqual(load_manifest(self.fx.cache), scan_cache(self.fx.cache))

    def test_normal_incremental_pull_and_unchanged_retry(self):
        self.external()
        self.assert_success(self.run_pull("-Side", "chinese", "-OnlyBooks", self.key, "-SyncToEpub"))
        self.assertEqual((self.cache_book / self.chapter).read_bytes(),
                         (self.fx.epub / BOOK_CN / self.chapter).read_bytes())
        before = self.snapshot()
        self.assert_success(self.run_pull("-Side", "chinese", "-OnlyBooks", self.key, "-SyncToEpub"))
        self.assertEqual(self.snapshot(), before)

    def assert_pattern_sync(self, pattern=None):
        text = "<p>通配筛选后的新正文</p>"
        self.external(text=text)
        self.external(BOOK_CN2, text=text)
        caller = self.fx.root / "caller"
        caller.mkdir()
        # Matching cwd entries must never become native command arguments.
        for name in ("local-S1_01-a", "local-S1_01-b"):
            (caller / name).touch()
        other_chapter = Path("OEBPS/Text/S1_02-01_Chapter.xhtml")
        other_cache = self.fx.cache / "chinese-text" / BOOK_CN2 / other_chapter
        other_archive = self.fx.epub / BOOK_CN2 / other_chapter
        other_before = (other_cache.read_bytes(), other_archive.read_bytes())
        extra = () if pattern is None else ("-Pattern", pattern)
        self.assert_success(self.run_pull(
            "-Side", "chinese", "-SyncToEpub", "-OnlyBooks",
            self.key + f",chinese-text/{BOOK_CN2}", *extra, cwd=caller,
        ))
        expected = (self.fx.root / "external" / BOOK_CN / self.chapter).read_bytes()
        self.assertEqual((self.cache_book / self.chapter).read_bytes(), expected)
        self.assertEqual((self.fx.epub / BOOK_CN / self.chapter).read_bytes(), expected)
        other_after = (other_cache.read_bytes(), other_archive.read_bytes())
        self.assertEqual(other_after, (expected, expected) if pattern is None else other_before)
        self.assertEqual(load_manifest(self.fx.cache), scan_cache(self.fx.cache))
        state = (self.fx.cache / "pull-state.tsv").read_text(encoding="utf-8-sig")
        self.assertIn(BOOK_CN, state)
        self.assertEqual(BOOK_CN2 in state, pattern is None)

    def test_sync_to_epub_preserves_default_pattern(self):
        self.assert_pattern_sync()

    def test_sync_to_epub_preserves_star_pattern(self):
        self.assert_pattern_sync("*S1_01*")

    def test_sync_to_epub_preserves_character_wildcards(self):
        self.assert_pattern_sync("*S1_0[1]?*")

    def test_completed_extraction_can_retry_after_downstream_gate_failure(self):
        self.external(text="<p>broken")
        manifest = (self.fx.cache / "manifest.json").read_bytes()
        state = (self.fx.cache / "pull-state.tsv").read_bytes()
        archive = (self.fx.epub / BOOK_CN / self.chapter).read_bytes()
        for _ in range(2):
            result = self.run_pull("-Side", "chinese", "-OnlyBooks", self.key, "-SyncToEpub")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("同步失败", result.stdout + result.stderr)
            self.assertNotIn("拉取会覆盖", result.stdout + result.stderr)
            self.assertEqual((self.fx.cache / "manifest.json").read_bytes(), manifest)
            self.assertEqual((self.fx.cache / "pull-state.tsv").read_bytes(), state)
            self.assertEqual((self.fx.epub / BOOK_CN / self.chapter).read_bytes(), archive)

    def test_preview_does_not_write(self):
        self.external()
        before = self.snapshot()
        self.assert_success(self.run_pull("-Side", "chinese", "-OnlyBooks", self.key, "-WhatIf"))
        self.assertEqual(self.snapshot(), before)

    def test_another_sync_process_blocks_before_any_book_is_replaced(self):
        self.external()
        before = self.snapshot()
        with cache_lock(self.fx.cache):
            result = self.run_pull("-Side", "chinese", "-OnlyBooks", self.key)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("另一个同步进程", result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell participant lifetime regression")
    def test_powershell_keeps_lock_after_python_wrapper_is_terminated(self):
        # Pause the real PowerShell body after its lock setup. The fixture copy
        # supplies a deterministic barrier without adding hooks to the tool.
        controlled_tools = self.fx.root / "controlled-tools"
        controlled_tools.mkdir()
        for name in ("sync_lock.py", "file_transaction.py", "cli_output.py"):
            shutil.copy2(TOOLS / name, controlled_tools / name)
        marker = self.fx.root / "powershell-ready.txt"
        release = self.fx.root / "powershell-release.txt"
        quoted_marker = str(marker).replace("'", "''")
        quoted_release = str(release).replace("'", "''")
        script = (TOOLS / "pull.ps1").read_text(encoding="utf-8-sig")
        barrier = (f"[System.IO.File]::WriteAllText('{quoted_marker}', [string]$PID)\n"
                   f"while (-not (Test-Path -LiteralPath '{quoted_release}')) {{ Start-Sleep -Milliseconds 20 }}\n")
        script = script.replace("# Incremental pull records", barrier + "# Incremental pull records", 1)
        controlled_pull = controlled_tools / "pull.ps1"
        controlled_pull.write_text(script, encoding="utf-8-sig")
        self.external()
        wrapper = subprocess.Popen(
            [sys.executable, str(TOOLS / "sync_lock.py"), "--cache", str(self.fx.cache), "--",
             POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(controlled_pull),
             "-CacheDirectory", str(self.fx.cache), "-EpubDirectory", str(self.fx.epub),
             "-ChineseSourceDirectory", str(self.fx.onedrive_cn), "-Side", "chinese", "-OnlyBooks", self.key],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        child_pid = None
        try:
            deadline = time.monotonic() + 15
            while not marker.is_file() and time.monotonic() < deadline:
                self.assertIsNone(wrapper.poll(), "Wrapper exited before PowerShell acquired its lease")
                time.sleep(0.02)
            self.assertTrue(marker.is_file(), "PowerShell did not reach the transaction barrier")
            child_pid = int(marker.read_text())
            wrapper.terminate()
            wrapper.wait(timeout=10)
            result = self.run_pull("-Side", "chinese", "-OnlyBooks", self.key)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("另一个同步进程", result.stdout + result.stderr)
        finally:
            if wrapper.poll() is None:
                wrapper.terminate()
                wrapper.wait(timeout=10)
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGTERM)
                except OSError:
                    pass
        self.assert_success(self.run_pull("-Side", "chinese", "-OnlyBooks", self.key))

    def test_windows_powershell_entry_point(self):
        legacy = shutil.which("powershell")
        if not legacy:
            self.skipTest("Windows PowerShell 5.1 is unavailable")
        self.external()
        self.assert_success(self.run_pull("-Side", "chinese", "-OnlyBooks", self.key, shell=legacy))


if __name__ == "__main__":
    unittest.main()
