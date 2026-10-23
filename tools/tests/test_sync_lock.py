from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from manifest import compute_hash, load_manifest, scan_cache  # noqa: E402
from sync_core import read_pull_state  # noqa: E402
from sync_lock import (LEASE_ENV, LOCK_FILENAME, MEMBER_PREFIX, _try_lock, cache_lock,  # noqa: E402
                       inherited_lock_held, lock_environment, participant_paths)
from test_publish_auto import BOOK_CN, BOOK_CN2, Fixture  # noqa: E402


class SyncLockTests(unittest.TestCase):
    def run_cli(self, script, *arguments, env=None):
        return subprocess.run([sys.executable, "-B", str(TOOLS / script), *map(str, arguments)],
                              capture_output=True, text=True, encoding="utf-8", env=env,
                              timeout=20, check=False)

    def wait_for(self, marker, process):
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.communicate(timeout=5)
                self.fail(f"Worker exited before reaching its barrier: {output}")
            time.sleep(0.01)
        self.assertTrue(marker.exists(), "Worker did not reach its barrier")

    def test_check_without_lease_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "missing-cache"
            result = self.run_cli("sync_lock.py", "--cache", cache, "--check-held")
            self.assertEqual(result.returncode, 1)
            self.assertFalse(cache.exists())

    def test_independent_entrypoints_fail_while_child_can_join(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            original_environment = os.environ.get(LEASE_ENV)
            with cache_lock(fx.cache):
                for script in ("manifest.py", "publish_auto.py", "publish.py", "publish_epub.py"):
                    with self.subTest(script=script):
                        arguments = ["--cache", fx.cache]
                        if script != "manifest.py":
                            arguments += ["--epub", fx.epub, "--only-books", f"chinese-text/{BOOK_CN}"]
                        result = self.run_cli(script, *arguments)
                        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                        self.assertIn("同步进程", result.stderr)
                child_env = lock_environment()
                result = self.run_cli("sync_lock.py", "--cache", fx.cache, "--check-held", env=child_env)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = self.run_cli("manifest.py", "--cache", fx.cache,
                                      "--update-books", f"chinese-text/{BOOK_CN}", env=child_env)
                self.assertEqual(result.returncode, 0, result.stderr)
                wrong_env = {**child_env, LEASE_ENV: json.dumps({str(fx.cache.resolve()): "wrong"})}
                result = self.run_cli("manifest.py", "--cache", fx.cache, env=wrong_env)
                self.assertEqual(result.returncode, 1)
            self.assertEqual(os.environ.get(LEASE_ENV), original_environment)
            self.assertEqual(load_manifest(fx.cache), scan_cache(fx.cache))
            self.assertEqual(list(fx.cache.glob(f"{MEMBER_PREFIX}*.json")), [])
            self.assertTrue((fx.cache / LOCK_FILENAME).exists())
            # The old lease never authorizes a later, unrelated invocation.
            result = self.run_cli("sync_lock.py", "--cache", fx.cache, "--check-held", env=child_env)
            self.assertEqual(result.returncode, 1)

    def test_exception_and_process_exit_release_the_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "deliberate"):
                with cache_lock(cache):
                    with cache_lock(cache):
                        raise RuntimeError("deliberate")
            with cache_lock(cache):
                pass
            marker = cache / "ready"
            code = (
                "import sys,time; from pathlib import Path; "
                "sys.path.insert(0,sys.argv[1]); from sync_lock import cache_lock; "
                "\nwith cache_lock(Path(sys.argv[2])):\n"
                " Path(sys.argv[3]).write_text('ready'); time.sleep(30)\n"
            )
            process = subprocess.Popen([sys.executable, "-B", "-c", code, str(TOOLS), str(cache), str(marker)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.wait_for(marker, process)
            finally:
                process.terminate()
                process.communicate(timeout=10)
            # An abrupt exit leaves metadata behind, but its OS lock is gone.
            self.assertTrue(list(cache.glob(f"{MEMBER_PREFIX}*.json")))
            self.assertFalse(inherited_lock_held(cache))
            with cache_lock(cache):
                pass
            self.assertEqual(list(cache.glob(f"{MEMBER_PREFIX}*.json")), [])

    def test_child_holds_its_own_lock_after_parent_os_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            cache.mkdir()
            marker, release, done = root / "ready", root / "release", root / "done"
            child = root / "child.py"
            child.write_text(
                "import os,sys,time\nfrom pathlib import Path\n"
                "sys.path.insert(0,sys.argv[1])\nfrom sync_lock import cache_lock\n"
                "cache,marker,release,done=map(Path,sys.argv[2:])\n"
                "with cache_lock(cache):\n"
                " marker.write_text(str(os.getpid()))\n"
                " deadline=time.monotonic()+20\n"
                " while not release.exists():\n"
                "  if time.monotonic()>deadline: raise RuntimeError('barrier timeout')\n"
                "  time.sleep(0.01)\n"
                "done.write_text('released')\n", encoding="utf-8")
            parent = root / "parent.py"
            parent.write_text(
                "import os,subprocess,sys,time\nfrom pathlib import Path\n"
                "sys.path.insert(0,sys.argv[1])\n"
                "from sync_lock import cache_lock,lock_environment\n"
                "with cache_lock(Path(sys.argv[3])):\n"
                " subprocess.Popen([sys.executable,'-B',sys.argv[2],sys.argv[1],*sys.argv[3:]],"
                "env=lock_environment(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
                " deadline=time.monotonic()+15\n"
                " while not Path(sys.argv[4]).exists():\n"
                "  if time.monotonic()>deadline: raise RuntimeError('child did not join')\n"
                "  time.sleep(0.01)\n"
                " os._exit(0)\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", str(parent), str(TOOLS), str(child), str(cache),
                 str(marker), str(release), str(done)], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(marker.exists())
            try:
                blocked = self.run_cli("manifest.py", "--cache", cache)
                self.assertEqual(blocked.returncode, 1, blocked.stdout + blocked.stderr)
                self.assertIn("同步进程", blocked.stderr)
                self.assertFalse((cache / "manifest.json").exists())
                release.touch()
                deadline = time.monotonic() + 10
                while not done.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(done.exists(), "Child did not release its participant")
                retry = self.run_cli("manifest.py", "--cache", cache)
                self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
            finally:
                if not done.exists():
                    os.kill(int(marker.read_text()), signal.SIGTERM)

    def test_native_candidate_blocks_admission_before_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            participant = uuid.uuid4().hex
            candidate, metadata = participant_paths(cache, participant)
            candidate.write_bytes(b"\0")
            # A merely named candidate cannot register without an OS lock.
            unlocked = self.run_cli("sync_lock.py", "--cache", cache,
                                    "--join-participant", participant)
            self.assertEqual(unlocked.returncode, 1)
            self.assertFalse(metadata.exists())
            with candidate.open("r+b") as handle:
                self.assertTrue(_try_lock(handle))
                blocked = self.run_cli("manifest.py", "--cache", cache)
                self.assertEqual(blocked.returncode, 1, blocked.stdout + blocked.stderr)
                self.assertIn("同步进程", blocked.stderr)
                joined = self.run_cli("sync_lock.py", "--cache", cache,
                                      "--join-participant", participant)
                self.assertEqual(joined.returncode, 0, joined.stderr)
                lease_env = {**os.environ, LEASE_ENV: joined.stdout.strip()}
                child = self.run_cli("manifest.py", "--cache", cache, env=lease_env)
                self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
                # The native member still excludes independent invocations.
                blocked = self.run_cli("manifest.py", "--cache", cache)
                self.assertEqual(blocked.returncode, 1)
            retry = self.run_cli("manifest.py", "--cache", cache)
            self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)

    def test_empty_manifest_book_selection_is_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            before = {path.relative_to(fx.cache): path.read_bytes()
                      for path in fx.cache.rglob("*") if path.is_file()}
            result = self.run_cli("manifest.py", "--cache", fx.cache, "--update-books")
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            after = {path.relative_to(fx.cache): path.read_bytes()
                     for path in fx.cache.rglob("*") if path.is_file()}
            self.assertEqual(after, before)

    def test_concurrent_book_publish_is_blocked_then_retries_from_fresh_baseline(self):
        for script in ("publish.py", "publish_epub.py"):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as tmp:
                fx = Fixture(Path(tmp))
                fx.onedrive_cn.mkdir()
                if script == "publish.py":
                    fx.write_cache_book("chinese-text", BOOK_CN, "<p>任务甲修改</p>")
                    fx.write_cache_book("chinese-text", BOOK_CN2, "<p>任务乙修改</p>")
                else:
                    fx.write_epub_book(BOOK_CN, "<p>任务甲修改</p>")
                    fx.write_epub_book(BOOK_CN2, "<p>任务乙修改</p>")
                marker, release = fx.root / "ready", fx.root / "release"
                module = Path(script).stem
                code = (
                    "import sys,time; from pathlib import Path; "
                    "sys.path.insert(0,sys.argv[1]); "
                    f"import {module} as publisher; "
                    "original=publisher.package_book; "
                    "marker=Path(sys.argv[2]); release=Path(sys.argv[3]); "
                    "sys.argv=[sys.argv[0],*sys.argv[4:]]\n"
                    "def paused_package(*args,**kwargs):\n"
                    " marker.write_text('ready')\n"
                    " deadline=time.monotonic()+15\n"
                    " while not release.exists():\n"
                    "  if time.monotonic()>deadline: raise RuntimeError('barrier timeout')\n"
                    "  time.sleep(0.01)\n"
                    " return original(*args,**kwargs)\n"
                    "publisher.package_book=paused_package\n"
                    "raise SystemExit(publisher.main())\n"
                )
                common = ["--cache", str(fx.cache), "--epub", str(fx.epub),
                          "--chinese-onedrive", str(fx.onedrive_cn)]
                if script == "publish.py":
                    common += ["--side", "chinese"]
                book_a, book_b = f"chinese-text/{BOOK_CN}", f"chinese-text/{BOOK_CN2}"
                before = load_manifest(fx.cache)
                worker = subprocess.Popen(
                    [sys.executable, "-B", "-c", code, str(TOOLS), str(marker), str(release),
                     *common, "--only-books", book_a],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
                try:
                    self.wait_for(marker, worker)
                    blocked = self.run_cli(script, *common, "--only-books", book_b)
                    self.assertEqual(blocked.returncode, 1, blocked.stdout + blocked.stderr)
                    self.assertIn("同步进程", blocked.stderr)
                    self.assertEqual(load_manifest(fx.cache), before)
                    self.assertFalse((fx.onedrive_cn / f"{BOOK_CN2}.epub").exists())
                    release.touch()
                    output, error = worker.communicate(timeout=20)
                    self.assertEqual(worker.returncode, 0, output + error)
                finally:
                    if worker.poll() is None:
                        worker.kill()
                        worker.communicate(timeout=10)
                retry = self.run_cli(script, *common, "--only-books", book_b)
                self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
                self.assertEqual(load_manifest(fx.cache), scan_cache(fx.cache))
                state = read_pull_state(fx.cache)
                self.assertEqual(set(state), {book_a, book_b})
                for book_key in (book_a, book_b):
                    book = book_key.split("/", 1)[1]
                    packed = fx.onedrive_cn / f"{book}.epub"
                    self.assertEqual(state[book_key][1], str(packed.stat().st_size))
                    wid = book.split("】")[0][1:]
                    suffix = f"OEBPS/Text/{wid}-01_Chapter.xhtml"
                    self.assertEqual(load_manifest(fx.cache)[book_key + "/" + suffix],
                                     compute_hash(fx.epub / book / suffix))

    def test_first_scoped_manifest_does_not_baseline_other_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            (fx.cache / "manifest.json").unlink()
            key = f"chinese-text/{BOOK_CN}"
            result = self.run_cli("manifest.py", "--cache", fx.cache, "--update-books", key)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            files = load_manifest(fx.cache)
            self.assertTrue(files)
            self.assertTrue(all(name.startswith(key + "/") for name in files))

    def test_force_only_books_preserves_unselected_published_baselines(self):
        for script in ("publish.py", "publish_epub.py"):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as tmp:
                fx = Fixture(Path(tmp))
                before = load_manifest(fx.cache)
                writer = fx.write_epub_book if script == "publish_epub.py" else (
                    lambda name, text: fx.write_cache_book("chinese-text", name, text))
                writer(BOOK_CN, "<p>本次已完成修改</p>")
                writer(BOOK_CN2, "<p>其他任务尚未发布</p>")
                key = f"chinese-text/{BOOK_CN}"
                args = ["--cache", fx.cache, "--epub", fx.epub, "--only-books", key,
                        "--force", "--no-upload"]
                if script == "publish.py":
                    args += ["--side", "chinese"]
                result = self.run_cli(script, *args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                after = load_manifest(fx.cache)
                self.assertEqual(set(after), set(before))
                self.assertEqual({name: value for name, value in after.items()
                                  if not name.startswith(key + "/")},
                                 {name: value for name, value in before.items()
                                  if not name.startswith(key + "/")})
                self.assertNotEqual(after, before)


if __name__ == "__main__":
    unittest.main()
