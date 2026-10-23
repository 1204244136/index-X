"""Exercise the public CLI output contract, including Windows pipe encoding."""
from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1]


class CliOutputTests(unittest.TestCase):
    def test_output_configuration_accepts_memory_capture_streams(self):
        from tools.cli_output import configure_output

        output, errors = io.StringIO(), io.StringIO()
        with patch("sys.stdout", output), patch("sys.stderr", errors):
            configure_output()
            print("测试𠮷")
            print("警告𠮷", file=sys.stderr)
        self.assertEqual(output.getvalue(), "测试𠮷\n")
        self.assertEqual(errors.getvalue(), "警告𠮷\n")

    def test_importing_tools_does_not_reconfigure_host_streams(self):
        code = (
            f"import sys; sys.path.insert(0, {str(TOOLS)!r}); "
            "sys.stdout.reconfigure(encoding='ascii'); "
            "sys.stderr.reconfigure(encoding='ascii'); "
            "import bw_preprocess, split_s5_epubs, check_semantic_alignment; "
            "assert sys.stdout.encoding == 'ascii'; "
            "assert sys.stderr.encoding == 'ascii'"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")

    def test_tools_remain_importable_as_packages_in_a_clean_process(self):
        for name in ("audit_risk", "epub_char_count", "read_xlsx", "search_text", "diff_paired_lines"):
            with self.subTest(tool=name):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", f"import tools.{name}"],
                    cwd=TOOLS.parent, capture_output=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
                self.assertEqual(result.stdout, b"")

    def run_cli(self, script: Path, *args: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.update(PYTHONIOENCODING="gbk", PYTHONUTF8="0", PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(
            [sys.executable, str(script), *args], capture_output=True,
            env=env, timeout=30,
        )

    def test_every_tool_help_is_utf8_even_with_gbk_pipes(self):
        for script in sorted(TOOLS.glob("*.py")):
            if "__main__" not in script.read_text(encoding="utf-8-sig"):
                continue
            if script.name == "compare_epub_images.py" and importlib.util.find_spec("PIL") is None:
                continue
            with self.subTest(tool=script.name):
                result = self.run_cli(script, "--help")
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
                self.assertIn("usage:", result.stdout.decode("utf-8"))
                self.assertEqual(result.stderr, b"")

    def test_manifest_missing_cache_is_a_concise_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli(TOOLS / "manifest.py", "--cache", str(Path(tmp) / "missing"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        diagnostic = result.stderr.decode("utf-8")
        self.assertIn("缓存目录不存在", diagnostic)
        self.assertNotIn("Traceback", diagnostic)

    def test_manifest_missing_baseline_warning_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli(
                TOOLS / "manifest.py", "--cache", tmp,
                "--update-books", "chinese-text/example",
            )
            self.assertTrue((Path(tmp) / "manifest.json").is_file())
        self.assertEqual(result.returncode, 0)
        self.assertIn("警告", result.stderr.decode("utf-8"))
        self.assertNotIn("Traceback", result.stderr.decode("utf-8"))

    def test_executable_skill_help_is_utf8_even_with_gbk_pipes(self):
        references = TOOLS.parent / ".agents" / "skills"
        lookup = references / "proofread-review" / "references" / "lookup_source.py"
        template = references / "translation-term-unification" / "references" / "unify_terms_template.py"
        with tempfile.TemporaryDirectory() as tmp:
            copied_template = Path(tmp) / "unify_terms.py"
            copied_template.write_bytes(template.read_bytes())
            for script in (lookup, template, copied_template):
                with self.subTest(script=str(script)):
                    result = self.run_cli(script, "--help")
                    self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
                    self.assertIn("usage:", result.stdout.decode("utf-8"))
                    self.assertEqual(result.stderr, b"")

    def test_publish_force_warnings_use_utf8_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, archive = Path(tmp) / "cache", Path(tmp) / "archive"
            cache.mkdir()
            archive.mkdir()
            common = ["--cache", str(cache), "--epub", str(archive), "--force", "--dry-run", "--no-upload"]
            for tool in ("publish.py", "publish_epub.py", "publish_auto.py"):
                args = common + ["--chinese-onedrive", tmp]
                if tool != "publish_epub.py":
                    args += ["--japanese-onedrive", tmp]
                if tool == "publish_auto.py":
                    args += ["--from", "cache"]
                with self.subTest(tool=tool):
                    result = self.run_cli(TOOLS / tool, *args)
                    self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
                    self.assertIn("警告", result.stderr.decode("utf-8"))
                    self.assertNotIn("警告", result.stdout.decode("utf-8"))
            self.assertFalse((cache / "manifest.json").exists())

    def test_package_preview_reports_no_generated_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "source", Path(tmp) / "output"
            (source / "book").mkdir(parents=True)
            result = self.run_cli(
                TOOLS / "package_cache_epubs.py", "--source", str(source),
                "--output", str(output), "--dry-run",
            )
            self.assertFalse(output.exists())
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertIn("未生成 EPUB", result.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
