from __future__ import annotations

import contextlib
import importlib
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

import edit_safety
import normalize_single
import normalize_paired
import sync_pb_tags
import restore_cn_scene_breaks
import fix_legacy_pagebreak_br
import text_norm
import shift_content_sequences

MUTATORS = ("normalize_single", "normalize_paired", "migrate_heading_breaks",
            "fix_empty_placeholders", "fix_legacy_pagebreak_br",
            "restore_cn_scene_breaks", "reorder_notes", "wrap_cn_image_lines",
            "sync_pb_tags", "text_norm", "shift_content_sequences")


def xhtml(*body: str) -> str:
    return "\n".join(['<?xml version="1.0" encoding="utf-8"?>', '<!DOCTYPE html>',
                      '<html><head></head><body>', '<h1>章</h1>', '',
                      *body, '</body></html>', ''])


class OutputStreamCliTests(unittest.TestCase):
    def run_cli(self, module, *args):
        return subprocess.run([sys.executable, "-B", str(TOOLS / f"{module}.py"), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8", check=False)

    def test_input_failures_use_stderr_without_polluting_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "不存在"
            cases = (
                ("normalize_single", ["--dir", missing], 1, "目录不存在"),
                ("merge_bw_pages", [root], 1, "没有 p-NNN.xhtml"),
                ("import_docx_outline", [missing.with_suffix(".docx")], 2, "交稿不存在"),
                ("import_align_plan", [missing.with_suffix(".docx"), "--work", "S4_04"], 2, "交稿不存在"),
                ("import_build_text", [missing.with_suffix(".json"), "--out", root / "out"], 2, "计划文件不存在"),
                ("bw_preprocess", [missing], 1, "不存在"),
                ("epub2docx", [missing], 1, "不存在"),
            )
            for module, args, status, message in cases:
                with self.subTest(tool=module):
                    result = self.run_cli(module, *args)
                    self.assertEqual(result.returncode, status, result.stderr)
                    self.assertIn(message, result.stderr)
                    self.assertNotIn(message, result.stdout)
                    self.assertNotIn("Traceback", result.stderr)

    def test_unsafe_repairs_keep_summary_on_stdout_and_refusal_on_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, jp_root = Path(tmp) / "cn", Path(tmp) / "jp"
            cn = root / "【S1_01】书" / "S1_01-01_Chapter.xhtml"
            jp = jp_root / "【S1_01】本" / "S1_01-01.xhtml"
            cn.parent.mkdir(parents=True)
            jp.parent.mkdir(parents=True)
            cases = (
                ("normalize_paired", xhtml("<p>甲</span>"), xhtml("<p>日文</p>"), 1, "[阻断]"),
                ("sync_pb_tags", xhtml("<h2>甲</h2>"), xhtml('<p class="pb">日文</p>'), 1, "[拒绝]"),
                ("restore_cn_scene_breaks", xhtml("<h2>甲</h2>"), xhtml("<p>日文</p>", "<br/>"), 0, "[跳过]"),
            )
            for module, chinese, japanese, status, diagnostic in cases:
                with self.subTest(tool=module):
                    cn.write_text(chinese, encoding="utf-8")
                    jp.write_text(japanese, encoding="utf-8")
                    result = self.run_cli(module, "--root", root, "--jp-root", jp_root)
                    self.assertEqual(result.returncode, status, result.stderr)
                    self.assertIn(diagnostic, result.stderr)
                    self.assertNotIn(diagnostic, result.stdout)
                    self.assertEqual(cn.read_text(encoding="utf-8"), chinese)

    def test_paired_repairs_reject_empty_references_before_writing_earlier_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, jp_root = Path(tmp) / "cn", Path(tmp) / "jp"
            files = {}
            for side, directory in (("cn", root), ("jp", jp_root)):
                book = directory / "【S1_01】书"
                book.mkdir(parents=True)
                for sequence in ("01", "02"):
                    path = book / f"S1_01-{sequence}.xhtml"
                    path.write_text(xhtml('<p class="pb">正文</p>'), encoding="utf-8")
                    files[side, sequence] = path
            for tool in ("sync_pb_tags", "restore_cn_scene_breaks", "fix_legacy_pagebreak_br"):
                for side in ("cn", "jp"):
                    with self.subTest(tool=tool, side=side):
                        path = files[side, "02"]
                        original = path.read_bytes()
                        path.write_text("\ufeff \n\t", encoding="utf-8")
                        before = {file: file.read_bytes() for file in files.values()}
                        try:
                            result = self.run_cli(tool, "--root", root, "--jp-root", jp_root,
                                                  "--staging", "--apply")
                            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                            self.assertIn("S1_01-02", result.stderr)
                            self.assertIn("为空", result.stderr)
                            self.assertNotIn("Traceback", result.stderr)
                            self.assertEqual({file: file.read_bytes() for file in before}, before)
                        finally:
                            path.write_bytes(original)

    def test_note_and_image_refusals_keep_preview_summary_on_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text_dir = root / "【S1_01】书" / "OEBPS/Text"
            text_dir.mkdir(parents=True)
            (text_dir / "S1_01-Note.xhtml").write_text(
                '<html><body><ul><li id="note1">孤立译注</li></ul></body></html>', encoding="utf-8")
            result = self.run_cli("reorder_notes", "--root", root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("定义集合与引用集合不一致", result.stderr)
            self.assertNotIn("定义集合与引用集合不一致", result.stdout)
            self.assertIn("预览", result.stdout)

            image_page = text_dir / "S1_01-01_Chapter.xhtml"
            invalid = xhtml('<img src="../Images/a.jpg"/>', '</span>')
            image_page.write_text(invalid, encoding="utf-8")
            result = self.run_cli("wrap_cn_image_lines", "--root", root, "--wrap-only")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("拒绝写入", result.stderr)
            self.assertNotIn("拒绝写入", result.stdout)
            self.assertIn("预览", result.stdout)
            self.assertEqual(image_page.read_text(encoding="utf-8"), invalid)

    def test_bw_runtime_warning_is_separate_from_merge_findings(self):
        module = importlib.import_module("bw_preprocess")
        output, errors = io.StringIO(), io.StringIO()
        stats = {"total": 0, "content": 0, "changed": 0, "issues": [],
                 "merge_notes": ["[OPF更新警告] 更新失败", "[插图归属] 请核对"]}
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            module.report_stats("测试", stats, True, False)
        self.assertIn("[OPF更新警告]", errors.getvalue())
        self.assertNotIn("[OPF更新警告]", output.getvalue())
        self.assertIn("[插图归属]", output.getvalue())


class EditTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.epub = self.repo / "EPUB"
        self.epub.mkdir()
        self.cache = self.repo / ".cache"
        self.cache.mkdir()
        self.patchers = [patch.object(edit_safety, "REPO_ROOT", self.repo),
                         patch.object(edit_safety, "DEFAULT_EPUB", self.epub)]
        for patcher in self.patchers:
            patcher.start()
        self.addCleanup(self.tmp.cleanup)
        for patcher in self.patchers:
            self.addCleanup(patcher.stop)

    def test_archive_allowed_external_requires_staging(self):
        self.assertEqual(edit_safety.require_edit_target(self.epub / "book"), self.epub / "book")
        outside = Path(self.tmp.name) / "staging"
        with self.assertRaises(edit_safety.EditSafetyError):
            edit_safety.require_edit_target(outside)
        self.assertEqual(edit_safety.require_edit_target(outside, staging=True), outside)

    def test_custom_archive_root_for_explicit_embedding(self):
        custom = Path(self.tmp.name) / "archive"
        self.assertEqual(edit_safety.require_edit_target(custom / "book", epub_root=custom), custom / "book")

    def test_cache_and_onedrive_rejected_even_in_staging(self):
        cloud = Path(self.tmp.name) / "OneDrive - Example" / "book"
        for target in (self.cache / "book", cloud):
            for staging in (False, True):
                with self.subTest(target=target, staging=staging), self.assertRaises(edit_safety.EditSafetyError):
                    edit_safety.require_edit_target(target, staging)

    def test_configured_onedrive_path_is_rejected(self):
        cloud = Path(self.tmp.name) / "cloud-with-custom-name"
        with patch.dict(os.environ, {"OneDrive": str(cloud)}):
            with self.assertRaises(edit_safety.EditSafetyError):
                edit_safety.require_edit_target(cloud / "book", staging=True)

    def test_archive_symlink_cannot_escape_boundary(self):
        alias = self.epub / "alias"
        outside = Path(self.tmp.name) / "external"
        outside.mkdir()
        try:
            alias.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("平台不允许创建 symlink")
        with self.assertRaises(edit_safety.EditSafetyError):
            edit_safety.require_edit_target(alias / "book")

    def test_staging_symlink_to_cache_is_always_rejected(self):
        alias = Path(self.tmp.name) / "cache-alias"
        try:
            alias.symlink_to(self.cache, target_is_directory=True)
        except OSError:
            self.skipTest("平台不允许创建 symlink")
        with self.assertRaises(edit_safety.EditSafetyError):
            edit_safety.require_edit_target(alias / "book", staging=True)


class MutatorCliTests(unittest.TestCase):
    def call(self, module, *args):
        with patch.object(sys, "argv", [module.__name__ + ".py", *map(str, args)]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return module.main()

    def test_all_mutators_reject_apply_dry_run_combination(self):
        for name in MUTATORS:
            module = importlib.import_module(name)
            required = ["--work-id", "S1_01", "--offset", "1"] if name == "shift_content_sequences" else []
            with self.subTest(name=name), self.assertRaises(SystemExit) as error:
                self.call(module, *required, "--apply", "--dry-run")
            self.assertEqual(error.exception.code, 2)

    def test_single_default_previews_real_change_and_apply_requires_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.xhtml"
            path.write_text(xhtml("<p>内容</p>"), encoding="utf-8")
            original = path.read_bytes()
            with patch.object(normalize_single, "rebuild", return_value=(xhtml("<p>changed</p>").splitlines(), "ok")):
                self.assertEqual(self.call(normalize_single, path), 0)
                self.assertEqual(path.read_bytes(), original)
                with self.assertRaises(SystemExit):
                    self.call(normalize_single, path, "--apply")
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(self.call(normalize_single, path, "--apply", "--staging"), 0)
                self.assertNotEqual(path.read_bytes(), original)

    def test_single_refuses_invalid_xml_or_encoding_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.xhtml"
            original = xhtml("<p>内容</p>").encode("utf-8")
            path.write_bytes(original)
            with patch.object(normalize_single, "rebuild", return_value=(xhtml("<p>损坏</span>").splitlines(), "ok")):
                self.assertEqual(self.call(normalize_single, path, "--apply", "--staging"), 1)
            self.assertEqual(path.read_bytes(), original)
            invalid = original.replace("内容".encode("utf-8"), b"\xff")
            path.write_bytes(invalid)
            self.assertEqual(self.call(normalize_single, path, "--apply", "--staging"), 1)
            self.assertEqual(path.read_bytes(), invalid)

    def test_single_batch_write_failure_rolls_back_all_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / "a.xhtml", root / "b.xhtml"]
            for path in paths:
                path.write_text(xhtml("<p>内容</p>"), encoding="utf-8")
            originals = [path.read_bytes() for path in paths]

            def rebuild(path, *_):
                return xhtml(f"<p>{path.stem}</p>").splitlines(), "ok"

            real_write = normalize_single.write_lines
            calls = 0

            def failing_write(path, *args):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("模拟写入失败")
                return real_write(path, *args)

            with patch.object(normalize_single, "rebuild", side_effect=rebuild), \
                    patch.object(normalize_single, "write_lines", side_effect=failing_write):
                self.assertEqual(self.call(normalize_single, "--dir", root,
                                           "--apply", "--staging"), 1)
            self.assertEqual([path.read_bytes() for path in paths], originals)

    def test_every_root_mutator_blocks_cache_write_before_scanning(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            cache = repo / ".cache"
            jp = Path(tmp) / "jp"
            cache.mkdir(parents=True)
            jp.mkdir()
            with patch.object(edit_safety, "REPO_ROOT", repo):
                for name in MUTATORS[1:]:
                    module = importlib.import_module(name)
                    args = ["--root", cache, "--apply", "--staging"]
                    if name in ("normalize_paired", "fix_legacy_pagebreak_br",
                                "restore_cn_scene_breaks", "sync_pb_tags"):
                        args += ["--jp-root", jp]
                    if name == "wrap_cn_image_lines":
                        args += ["--wrap-only"]
                    if name == "shift_content_sequences":
                        args += ["--work-id", "S1_01", "--offset", "1"]
                    with self.subTest(name=name), self.assertRaises(SystemExit) as error:
                        self.call(module, *args)
                    self.assertEqual(error.exception.code, 2)

    def test_pair_archive_mode_does_not_write_japanese_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, jp_root = Path(tmp) / "archive", Path(tmp) / "reference"
            cn = root / "【S1_01】书" / "OEBPS" / "Text" / "S1_01-01_Chapter.xhtml"
            jp = jp_root / "【S1_01】本" / "OEBPS" / "Text" / "S1_01-01.xhtml"
            for path in (cn, jp):
                path.parent.mkdir(parents=True)
                path.write_text(xhtml("<p>内容</p>"), encoding="utf-8")
            original = jp.read_bytes()
            def cn_only_rebuild(path, *args):
                self.assertNotEqual(path, jp, "归档模式不得重建日文参考")
                return path.read_text(encoding="utf-8").replace("内容", "更新").splitlines(), "ok"
            with patch.object(edit_safety, "DEFAULT_EPUB", root), \
                    patch.object(normalize_paired, "rebuild", side_effect=cn_only_rebuild):
                original_cn = cn.read_bytes()
                self.assertEqual(self.call(normalize_paired, "--root", root, "--jp-root", jp_root), 0)
                self.assertEqual(cn.read_bytes(), original_cn)
                self.assertEqual(jp.read_bytes(), original)
                self.assertEqual(self.call(normalize_paired, "--root", root, "--jp-root", jp_root, "--apply"), 0)
            self.assertEqual(jp.read_bytes(), original)
            self.assertIn("更新", cn.read_text(encoding="utf-8"))

    def test_pair_staging_explicitly_writes_both_sides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / side / "【S1_01】书" / "S1_01-01.xhtml"
                     for side in ("chinese-text", "japanese-text")]
            for path in paths:
                path.parent.mkdir(parents=True)
                path.write_text(xhtml("<p>内容</p>"), encoding="utf-8")
            with patch.object(normalize_paired, "rebuild", side_effect=lambda p, *a:
                              (p.read_text(encoding="utf-8").replace("内容", "更新").splitlines(), "ok")):
                self.assertEqual(self.call(normalize_paired, "--cache", root, "--staging", "--apply"), 0)
            self.assertTrue(all("更新" in path.read_text(encoding="utf-8") for path in paths))

    def test_pb_default_preview_and_apply_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, jp_root = Path(tmp) / "cn", Path(tmp) / "jp"
            cn = root / "【S1_01】书" / "S1_01-01_Chapter.xhtml"
            jp = jp_root / "【S1_01】本" / "S1_01-01.xhtml"
            for path, paragraph in ((cn, '<p class="center">中文</p>'), (jp, '<p class="pb">日文</p>')):
                path.parent.mkdir(parents=True)
                path.write_text(xhtml(paragraph), encoding="utf-8")
            original_cn, original_jp = cn.read_bytes(), jp.read_bytes()
            args = ["--root", root, "--jp-root", jp_root]
            self.assertEqual(self.call(sync_pb_tags, *args), 0)
            self.assertEqual(cn.read_bytes(), original_cn)
            self.assertEqual(self.call(sync_pb_tags, *args, "--staging", "--apply"), 0)
            updated = cn.read_bytes()
            self.assertIn(b'class="center pb"', updated)
            self.assertEqual(jp.read_bytes(), original_jp)
            self.assertEqual(self.call(sync_pb_tags, *args, "--staging", "--apply"), 0)
            self.assertEqual(cn.read_bytes(), updated)

    def test_scene_repairs_preserve_one_bom_and_source(self):
        for module, japanese, chinese in (
                (restore_cn_scene_breaks, xhtml('<p>A</p>', '<br/>', '<p>B</p>'),
                 xhtml('<p>甲</p>', '<p>乙</p>')),
                (fix_legacy_pagebreak_br, xhtml('<p>A</p>', '<p class="pb">B</p>', '<p>C</p>'),
                 xhtml('<p>甲</p>', '<p>乙</p>', '<br/>', '<p>丙</p>'))):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as tmp:
                root, jp_root = Path(tmp) / "cn", Path(tmp) / "jp"
                cn = root / "【S1_01】书" / "S1_01-01_Chapter.xhtml"
                jp = jp_root / "【S1_01】本" / "S1_01-01.xhtml"
                cn.parent.mkdir(parents=True)
                jp.parent.mkdir(parents=True)
                cn.write_bytes(b'\xef\xbb\xbf' + chinese.encode('utf-8'))
                jp.write_text(japanese, encoding='utf-8')
                source = jp.read_bytes()
                self.assertEqual(self.call(module, '--root', root, '--jp-root', jp_root,
                                           '--apply', '--staging'), 0)
                result = cn.read_bytes()
                self.assertTrue(result.startswith(b'\xef\xbb\xbf'))
                self.assertEqual(result.count(b'\xef\xbb\xbf'), 1)
                self.assertEqual(jp.read_bytes(), source)
                self.assertEqual(len(result.decode('utf-8-sig').splitlines()), len(japanese.splitlines()))

    def test_text_norm_reads_cache_but_blocks_its_content_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            root = repo / '.cache' / 'cn'
            path = root / '【S1_01】书' / 'S1_01-01.xhtml'
            path.parent.mkdir(parents=True)
            path.write_text(xhtml('<p>甲,乙</p>'), encoding='utf-8')
            original = path.read_bytes()
            with patch.object(edit_safety, 'REPO_ROOT', repo):
                self.assertEqual(self.call(text_norm, '--root', root, '--dry-run'), 0)
                self.assertEqual(path.read_bytes(), original)
                with self.assertRaises(SystemExit):
                    self.call(text_norm, '--root', root, '--apply', '--staging')
                self.assertEqual(path.read_bytes(), original)

    def test_shift_requires_staging_and_updates_references_when_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'S1_01-01_Chapter.xhtml'
            path.write_text('<a href="S1_01-01_Chapter.xhtml">文</a>', encoding='utf-8')
            original = path.read_bytes()
            args = [root, '--work-id', 'S1_01', '--offset', '1']
            self.assertEqual(self.call(shift_content_sequences, *args), 0)
            self.assertEqual(path.read_bytes(), original)
            with self.assertRaises(SystemExit):
                self.call(shift_content_sequences, *args, '--apply')
            self.assertEqual(self.call(shift_content_sequences, *args, '--apply', '--staging'), 0)
            shifted = root / 'S1_01-02_Chapter.xhtml'
            self.assertFalse(path.exists())
            self.assertIn('S1_01-02_Chapter.xhtml', shifted.read_text(encoding='utf-8'))

    def test_pair_duplicate_headers_stop_all_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, jp_root = Path(tmp) / 'cn', Path(tmp) / 'jp'
            cn_book, jp_book = root / '【S1_01】书', jp_root / '【S1_01】本'
            cn_book.mkdir(parents=True)
            jp_book.mkdir(parents=True)
            paths = [cn_book / 'S1_01-01_Chapter1.xhtml', cn_book / 'S1_01-01_Chapter2.xhtml',
                     jp_book / 'S1_01-01.xhtml']
            for path in paths:
                path.write_text(xhtml('<p>内容</p>'), encoding='utf-8')
            originals = [path.read_bytes() for path in paths]
            with patch.object(normalize_paired, 'write_lines') as writer:
                self.assertEqual(self.call(normalize_paired, '--root', root, '--jp-root', jp_root,
                                           '--apply', '--staging'), 1)
                writer.assert_not_called()
            self.assertEqual([path.read_bytes() for path in paths], originals)

    def test_pair_duplicate_work_ids_stop_before_rebuilding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, jp_root = Path(tmp) / 'cn', Path(tmp) / 'jp'
            (root / '【S1_01】书').mkdir(parents=True)
            (root / '【S1_01】重复').mkdir()
            jp_root.mkdir()
            with patch.object(normalize_paired, 'rebuild') as rebuilder:
                self.assertEqual(self.call(normalize_paired, '--root', root, '--jp-root', jp_root), 1)
                rebuilder.assert_not_called()

    def test_archive_note_template_uses_explicit_chinese_side(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, jp_root = Path(tmp) / 'archive', Path(tmp) / 'reference'
            cn_book, jp_book = root / '【S1_01】书', jp_root / '【S1_01】本'
            cn_book.mkdir(parents=True)
            jp_book.mkdir(parents=True)
            chapter = cn_book / 'S1_01-01_Chapter.xhtml'
            chapter.write_text(xhtml('<p>正文</p>'), encoding='utf-8')
            reference = jp_book / 'S1_01-01.xhtml'
            reference.write_text(xhtml('<p>本文</p>'), encoding='utf-8')
            note = cn_book / 'S1_01-Note.xhtml'
            note.write_text(xhtml('<ul>', '<p><li id="note1">注</li></p>', '</ul>'), encoding='utf-8')
            before = note.read_bytes()
            with patch.object(edit_safety, 'DEFAULT_EPUB', root):
                args = ['--root', root, '--jp-root', jp_root]
                self.assertEqual(self.call(normalize_paired, *args), 0)
                self.assertEqual(note.read_bytes(), before)
                self.assertEqual(self.call(normalize_paired, *args, '--apply'), 0)
            lines = note.read_text(encoding='utf-8').splitlines()
            self.assertEqual(lines[4], '<ul>')
            self.assertEqual(lines[5], '<li id="note1">注</li>')

    def test_pair_late_contract_failure_never_partially_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, jp_root = Path(tmp) / 'cn', Path(tmp) / 'jp'
            paths = []
            for base in (root, jp_root):
                book = base / '【S1_01】书'
                book.mkdir(parents=True)
                for sequence in (1, 2):
                    path = book / f'S1_01-{sequence:02d}.xhtml'
                    path.write_text(xhtml('<p>内容</p>'), encoding='utf-8')
                    paths.append(path)
            originals = [path.read_bytes() for path in paths]
            def candidate(path, _h1, side):
                if side == 'cn' and '-02.' in path.name:
                    return None, '不可重建'
                text = path.read_text(encoding='utf-8')
                return text.replace('内容', '更新').splitlines(), 'ok'
            with patch.object(normalize_paired, 'rebuild', side_effect=candidate), \
                    patch.object(normalize_paired, 'write_lines') as writer:
                self.assertEqual(self.call(normalize_paired, '--root', root, '--jp-root', jp_root,
                                           '--apply', '--staging'), 1)
                writer.assert_not_called()
            self.assertEqual([path.read_bytes() for path in paths], originals)

    def test_pair_write_failure_rolls_back_all_written_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, jp_root = Path(tmp) / 'cn', Path(tmp) / 'jp'
            cn_book, jp_book = root / '【S1_01】书', jp_root / '【S1_01】本'
            cn_book.mkdir(parents=True)
            jp_book.mkdir(parents=True)
            cn_paths = []
            for sequence in (1, 2):
                for book in (cn_book, jp_book):
                    path = book / f'S1_01-{sequence:02d}.xhtml'
                    path.write_text(xhtml('<p>内容</p>'), encoding='utf-8')
                    if book == cn_book:
                        cn_paths.append(path)
            originals = [path.read_bytes() for path in cn_paths]
            writer = normalize_paired.write_lines
            calls = 0
            def failing_writer(path, lines, bom, crlf):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError('模拟写入失败')
                writer(path, lines, bom, crlf)
            with patch.object(edit_safety, 'DEFAULT_EPUB', root), \
                    patch.object(normalize_paired, 'rebuild', side_effect=lambda p, *a:
                                 (p.read_text(encoding='utf-8').replace('内容', '更新').splitlines(), 'ok')), \
                    patch.object(normalize_paired, 'write_lines', side_effect=failing_writer):
                self.assertEqual(self.call(normalize_paired, '--root', root, '--jp-root', jp_root, '--apply'), 1)
            self.assertEqual([path.read_bytes() for path in cn_paths], originals)


if __name__ == "__main__":
    unittest.main()
