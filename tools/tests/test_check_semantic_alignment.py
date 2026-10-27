from __future__ import annotations

import argparse
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import check_semantic_alignment as semantic


def add_unit(cache: Path, work: str, sequence: int, *, drift: bool = False) -> None:
    header = f"{work}-{sequence:02d}"
    for side in ("japanese-text", "chinese-text"):
        book = cache / side / f"【{work}】测试"
        book.mkdir(parents=True, exist_ok=True)
        body = "abcdefghijklmnopqrstuvwxyz" if drift and side == "japanese-text" else "正文"
        if drift and side == "chinese-text":
            body = "漢" * 150
        (book / f"{header}_Chapter.xhtml").write_text(
            '<?xml version="1.0"?>\n<!DOCTYPE html>\n<html><head></head><body>\n'
            f'<h1>章节</h1>\n\n<p>{body}</p>\n</body></html>\n',
            encoding="utf-8",
        )


PASS_ANALYSIS = (1.0, 7, 0, 0, [], [])


class SemanticPipelineTests(unittest.TestCase):
    def test_missing_scope_is_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / "chinese-text").mkdir()
            (cache / "japanese-text").mkdir()
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(semantic.run_pipeline(cache, l1_only=True), 2)
            self.assertEqual(output.getvalue(), "")
            self.assertIn("未找到匹配", errors.getvalue())

    def test_missing_cache_and_read_failure_are_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "missing"
            self.assertEqual(semantic.run_pipeline(cache, l1_only=True), 2)
            add_unit(cache, "S1_01", 1)
            with patch.object(Path, "read_text", side_effect=OSError("unreadable")):
                self.assertEqual(semantic.run_pipeline(cache, l1_only=True), 2)

    def test_l1_success_returns_an_integer(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            add_unit(cache, "S1_01", 1)
            self.assertEqual(semantic.run_pipeline(cache, l1_only=True), 0)

    def test_strict_rejects_l1_and_top_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            self.assertEqual(semantic.run_pipeline(cache, strict=True, l1_only=True), 2)
            self.assertEqual(semantic.run_pipeline(cache, strict=True, top_n=20), 2)

    def test_strict_checks_all_selected_units_including_l1_green_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            for number in range(1, 26):
                add_unit(cache, "S1_01", number)
            with patch.object(semantic, "get_embedding_model", return_value=object()), \
                    patch.object(semantic, "run_vector_analysis", return_value=PASS_ANALYSIS) as analyse:
                self.assertEqual(semantic.run_pipeline(cache, strict=True), 0)
            self.assertEqual(analyse.call_count, 25)
            report = (cache / "semantic-alignment-summary.tsv").read_text(encoding="utf-8-sig")
            self.assertEqual(report.count("\t是\t"), 25)

    def test_model_unavailable_does_not_pass_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            add_unit(cache, "S1_01", 1)
            with patch.object(semantic, "get_embedding_model", return_value=None):
                output, errors = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                    self.assertEqual(semantic.run_pipeline(cache, strict=True), 2)
            self.assertNotIn("无法载入", output.getvalue())
            self.assertIn("无法载入", errors.getvalue())

    def test_vector_runtime_failure_is_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            add_unit(cache, "S1_01", 1)
            with patch.object(semantic, "get_embedding_model", return_value=object()), \
                    patch.object(semantic, "run_vector_analysis", side_effect=RuntimeError("encode failed")):
                self.assertEqual(semantic.run_pipeline(cache, strict=True), 2)

    def test_strict_does_not_ignore_unmatched_tail_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            add_unit(cache, "S1_01", 1)
            jp = next((cache / "japanese-text").rglob("*.xhtml"))
            jp.write_text(jp.read_text(encoding="utf-8").replace(
                "</body>", "<p>额外尾部</p>\n</body>"), encoding="utf-8")
            with patch.object(semantic, "get_embedding_model") as model:
                self.assertEqual(semantic.run_pipeline(cache, strict=True), 1)
                model.assert_not_called()

    def test_confirmed_afterword_rule_limits_l2_to_shared_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            add_unit(cache, "S5_01_03", 6)
            jp = next((cache / "japanese-text").rglob("*.xhtml"))
            jp.write_text(jp.read_text(encoding="utf-8").replace(
                "</body>", "<p>あとがき</p>\n" + "<p>后记</p>\n" * 10 + "</body>"), encoding="utf-8")
            with patch.object(semantic, "get_embedding_model", return_value=object()), \
                    patch.object(semantic, "run_vector_analysis", return_value=PASS_ANALYSIS) as analyse:
                self.assertEqual(semantic.run_pipeline(cache, strict=True), 0)
            self.assertEqual(len(analyse.call_args.args[0]), len(analyse.call_args.args[1]))
            report = (cache / "semantic-alignment-summary.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("后记迁出", report)

    def test_invalid_xml_fails_structure_before_loading_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            add_unit(cache, "S1_01", 1)
            jp = next((cache / "japanese-text").rglob("*.xhtml"))
            jp.write_text(jp.read_text(encoding="utf-8").replace("</p>", "</span>"), encoding="utf-8")
            with patch.object(semantic, "get_embedding_model") as model:
                self.assertEqual(semantic.run_pipeline(cache, strict=True), 1)
                model.assert_not_called()

    def test_strict_rejects_missing_work_or_body_partner_in_declared_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            add_unit(cache, "S1_01", 1)
            add_unit(cache, "S2_01", 1)
            jp = next((cache / "japanese-text" / "【S2_01】测试").rglob("*.xhtml"))
            jp.unlink()
            self.assertEqual(semantic.run_pipeline(cache, strict=True), 1)
            with patch.object(semantic, "get_embedding_model", return_value=object()), \
                    patch.object(semantic, "run_vector_analysis", return_value=PASS_ANALYSIS):
                self.assertEqual(semantic.run_pipeline(cache, target_header="S1_01-01", strict=True), 0)
            (cache / "japanese-text" / "【S2_01】测试").rmdir()
            self.assertEqual(semantic.run_pipeline(cache, works=["S2_*"], strict=True), 1)

    def test_corrupted_utf8_is_an_execution_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            add_unit(cache, "S1_01", 1)
            jp = next((cache / "japanese-text").rglob("*.xhtml"))
            jp.write_bytes(jp.read_bytes() + b"\xff")
            self.assertEqual(semantic.run_pipeline(cache, strict=True), 2)

    def test_strict_window_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            add_unit(cache, "S1_01", 1)
            window = semantic.DriftWindow(6, 7, 1, 0.1, 0.9, "drift")
            with patch.object(semantic, "get_embedding_model", return_value=object()), \
                    patch.object(semantic, "run_vector_analysis", return_value=(0.1, 1, 2, 0, [window], [])):
                self.assertEqual(semantic.run_pipeline(cache, strict=True), 1)

    def test_work_and_header_filters_define_strict_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            add_unit(cache, "S1_01", 1)
            add_unit(cache, "S1_01", 2)
            add_unit(cache, "S2_01", 1)
            with patch.object(semantic, "get_embedding_model", return_value=object()), \
                    patch.object(semantic, "run_vector_analysis", return_value=PASS_ANALYSIS) as analyse:
                code = semantic.run_pipeline(cache, works=["s1_*"], target_header="s1_01-02", strict=True)
            self.assertEqual(code, 0)
            self.assertEqual(analyse.call_count, 1)
            with patch.object(semantic, "get_embedding_model") as model:
                self.assertEqual(semantic.run_pipeline(cache, target_header="S1_99-01", strict=True), 2)
                model.assert_not_called()

    def test_duplicate_header_is_nonzero_instead_of_selecting_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            add_unit(cache, "S1_01", 1)
            duplicate = cache / "chinese-text" / "【S1_01】测试" / "S1_01-01_Second.xhtml"
            duplicate.write_text("<p>duplicate</p>", encoding="utf-8")
            self.assertEqual(semantic.run_pipeline(cache, l1_only=True), 2)

    def test_diagnostic_top_is_explicitly_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            for number in range(1, 4):
                add_unit(cache, "S1_01", number, drift=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output), \
                    patch.object(semantic, "get_embedding_model", return_value=object()), \
                    patch.object(semantic, "run_vector_analysis", return_value=PASS_ANALYSIS) as analyse:
                self.assertEqual(semantic.run_pipeline(cache, top_n=1), 0)
            self.assertEqual(analyse.call_count, 1)
            self.assertIn("1/3", output.getvalue())
            self.assertNotIn("[门禁通过]", output.getvalue())

    def test_diagnostic_missing_reference_scope_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            add_unit(root, "S1_01", 1)
            (root / "chinese-text" / "【S1_01】测试" / "S1_01-02_Chapter.xhtml").write_text(
                "<p>没有日文参考。</p>\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(semantic.run_pipeline(root, l1_only=True), 0)
            report = (root / "semantic-alignment-summary.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("未核对", report)
            self.assertIn("S1_01-02", report)

    def test_packaging_only_work_is_excluded_but_empty_work_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            add_unit(root, "S1_01", 1)
            packaging = root / "chinese-text" / "【S0_00】说明"
            packaging.mkdir()
            (packaging / "S0_00-Information.xhtml").write_text("<p>阅读说明。</p>\n", encoding="utf-8")
            with patch.object(semantic, "get_embedding_model", return_value=object()), \
                    patch.object(semantic, "run_vector_analysis", return_value=PASS_ANALYSIS), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(semantic.run_pipeline(root, strict=True), 0)
            (packaging / "S0_00-Information.xhtml").unlink()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertNotEqual(semantic.run_pipeline(root, strict=True), 0)


class SemanticCliEnvironmentTests(unittest.TestCase):
    def test_archive_and_explicit_reference_roots_support_l1_without_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            add_unit(root, "S1_01", 1)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(semantic.main([
                    "--root", str(root / "chinese-text"), "--jp-root", str(root / "japanese-text"),
                    "--out", str(root / "report"), "--l1-only"]), 0)

    def test_missing_reference_is_reported_before_model_environment_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "EPUB").mkdir()
            errors = io.StringIO()
            with patch.object(semantic, "ensure_vector_environment") as environment, \
                    contextlib.redirect_stderr(errors):
                self.assertEqual(semantic.main([
                    "--cache", str(root / "cache"), "--strict"]), 2)
            environment.assert_not_called()
            self.assertIn("输入目录", errors.getvalue())

    def test_unknown_work_is_reported_before_model_environment_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            add_unit(root, "S1_01", 1)
            errors = io.StringIO()
            with patch.object(semantic, "ensure_vector_environment") as environment, \
                    contextlib.redirect_stderr(errors):
                self.assertEqual(semantic.main([
                    "--cache", str(root), "--work", "S1_99", "--strict"]), 2)
            environment.assert_not_called()
            self.assertIn("S1_99", errors.getvalue())

    def test_cli_invalid_strict_modes_and_missing_scope_are_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            for args in (("--strict", "--l1-only"), ("--strict", "--top", "20"),
                         ("--l1-only", "--cache", tmp), ("--top", "0")):
                with self.subTest(args=args):
                    result = subprocess.run([sys.executable, str(TOOLS / "check_semantic_alignment.py"), *args],
                                            capture_output=True, text=True, encoding="utf-8", errors="replace")
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_strict_auto_audit_does_not_inject_top20(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(semantic, "ensure_vector_environment", return_value=None), \
                patch.object(semantic, "run_pipeline", return_value=0) as pipeline:
            root = Path(tmp)
            add_unit(root, "S1_01", 1)
            self.assertEqual(semantic.main(["--strict", "--auto-audit", "--cache", str(root)]), 0)
        self.assertIsNone(pipeline.call_args.kwargs["top_n"])
        self.assertTrue(pipeline.call_args.kwargs["strict"])

    def test_explicit_missing_python_is_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            add_unit(root, "S1_01", 1)
            missing = root / "missing-python"
            self.assertEqual(semantic.main(["--strict", "--cache", str(root), "--vector-python", str(missing)]), 2)

    def test_environment_failure_never_falls_back_to_l1(self):
        args = argparse.Namespace(vector=True, auto_audit=False, strict=True, l1_only=False,
                                  top=None, vector_python=None, betweenlines_dir=None)
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(semantic, "vector_dependencies_available", return_value=False), \
                patch.object(semantic, "vector_python_candidates", return_value=[]):
            self.assertEqual(semantic.ensure_vector_environment(args, ["--strict"]), 2)

    def test_explicit_environment_reexec_propagates_failure_without_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "python"
            executable.touch()
            args = argparse.Namespace(vector=True, auto_audit=False, strict=True, l1_only=False,
                                      top=None, vector_python=executable, betweenlines_dir=None)
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(semantic, "vector_dependencies_available", return_value=False), \
                    patch.object(semantic.subprocess, "run", return_value=subprocess.CompletedProcess([], 7)) as run:
                self.assertEqual(semantic.ensure_vector_environment(args, ["--strict"]), 7)
                self.assertEqual(run.call_args.kwargs["env"][semantic.VECTOR_REEXEC_MARKER], "1")
            with patch.dict(os.environ, {semantic.VECTOR_REEXEC_MARKER: "1"}, clear=True), \
                    patch.object(semantic, "vector_dependencies_available", return_value=False), \
                    patch.object(semantic.subprocess, "run") as run:
                self.assertEqual(semantic.ensure_vector_environment(args, ["--strict"]), 2)
                run.assert_not_called()

    def test_project_environments_and_legacy_explicit_configuration(self):
        args = argparse.Namespace(vector_python=None, betweenlines_dir=None)
        with patch.dict(os.environ, {}, clear=True), patch.object(semantic, "ROOT_DIR", Path("/workspace/index-X")):
            self.assertEqual(semantic.vector_python_candidates(args), [
                Path("/workspace/index-X/.venv-vector/Scripts/python.exe"),
                Path("/workspace/index-X/.venv-vector/bin/python"),
                Path("/workspace/index-X/.venv/Scripts/python.exe"),
                Path("/workspace/index-X/.venv/bin/python"),
            ])
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"BETWEENLINES_DIR": tmp}, clear=True):
            self.assertEqual(semantic.vector_python_candidates(args)[0], Path(tmp).resolve() / ".venv/Scripts/python.exe")

    def test_cli_directory_overrides_environment_python(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                "INDEX_X_VECTOR_PYTHON": "wrong-python", "BETWEENLINES_PYTHON": "also-wrong"}, clear=True):
            args = argparse.Namespace(vector_python=None, betweenlines_dir=Path(tmp))
            self.assertEqual(semantic.vector_python_candidates(args)[0], Path(tmp).resolve() / ".venv/Scripts/python.exe")

    def test_neutral_environment_variable_overrides_legacy_configuration(self):
        args = argparse.Namespace(vector_python=None, betweenlines_dir=None)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                "INDEX_X_VECTOR_PYTHON": tmp, "BETWEENLINES_PYTHON": "wrong-python",
                "BETWEENLINES_DIR": "wrong-directory"}, clear=True):
            self.assertEqual(semantic.vector_python_candidates(args), [Path(tmp).absolute()])

    def test_explicit_python_keeps_virtualenv_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "python"
            try:
                executable.symlink_to(sys.executable)
            except OSError:
                self.skipTest("symlinks unavailable")
            args = argparse.Namespace(vector_python=executable, betweenlines_dir=None)
            self.assertEqual(semantic.vector_python_candidates(args), [executable.absolute()])

    def test_current_ready_environment_runs_without_delegation(self):
        args = argparse.Namespace(vector=True, auto_audit=False, strict=False, l1_only=False,
                                  top=None, vector_python=None, betweenlines_dir=None)
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(semantic, "vector_dependencies_available", return_value=True), \
                patch.object(semantic.subprocess, "run") as run:
            self.assertIsNone(semantic.ensure_vector_environment(args, ["--vector"]))
            run.assert_not_called()

    def test_missing_explicit_directory_does_not_use_current_ready_environment(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            args = argparse.Namespace(vector=True, auto_audit=False, strict=False, l1_only=False,
                                      top=None, vector_python=None, betweenlines_dir=Path(tmp) / "missing")
            with patch.object(semantic, "vector_dependencies_available", return_value=True), \
                    patch.object(semantic.subprocess, "run") as run:
                self.assertEqual(semantic.ensure_vector_environment(args, ["--vector"]), 2)
                run.assert_not_called()

    def test_l1_does_not_probe_vector_dependencies(self):
        args = argparse.Namespace(vector=False, auto_audit=False, strict=False, l1_only=True,
                                  top=None, vector_python=None, betweenlines_dir=None)
        with patch.object(semantic, "vector_dependencies_available") as dependencies, \
                patch.object(semantic, "vector_python_candidates") as candidates:
            self.assertIsNone(semantic.ensure_vector_environment(args, ["--l1-only"]))
            dependencies.assert_not_called()
            candidates.assert_not_called()

    def test_local_vector_environment_is_selected_before_base_environment(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True), \
                patch.object(semantic, "ROOT_DIR", Path(tmp)), \
                patch.object(semantic, "vector_dependencies_available", return_value=False), \
                patch.object(semantic.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            executables = [Path(tmp) / directory / "Scripts/python.exe" for directory in (".venv-vector", ".venv")]
            for executable in executables:
                executable.parent.mkdir(parents=True)
                executable.touch()
            args = argparse.Namespace(vector=True, auto_audit=False, strict=False, l1_only=False,
                                      top=None, vector_python=None, betweenlines_dir=None)
            self.assertEqual(semantic.ensure_vector_environment(args, ["--vector"]), 0)
            self.assertEqual(run.call_args.args[0][0], str(executables[0]))


if __name__ == "__main__":
    unittest.main()
