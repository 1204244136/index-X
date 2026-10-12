from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import publish_auto  # noqa: E402
from manifest import save_manifest, scan_cache, scan_epub  # noqa: E402
from sync_core import UNIX_TO_DOTNET_TICKS_OFFSET  # noqa: E402

BOOK_CN = "【S1_01】某书X"
BOOK_CN2 = "【S1_02】他书X"
BOOK_JP = "【S1_01】某書"


class Fixture:
    """临时三副本工作区：缓存 / EPUB/ / OneDrive，基线由 manifest.json 记录。"""

    def __init__(self, root: Path):
        self.root = root
        self.cache = root / "cache"
        self.epub = root / "epub"
        self.onedrive_cn = root / "onedrive-cn"
        self.onedrive_jp = root / "onedrive-jp"
        for side in ("chinese-text", "japanese-text"):
            (self.cache / side).mkdir(parents=True, exist_ok=True)
        self.epub.mkdir(parents=True, exist_ok=True)
        self.write_cache_book("chinese-text", BOOK_CN, "<p>中文A</p>")
        self.write_cache_book("chinese-text", BOOK_CN2, "<p>中文C</p>")
        self.write_cache_book("japanese-text", BOOK_JP, "<p>日文A</p>")
        # EPUB/ 只镜像中文书，且以书目录直接存放在根下（无 side 层）
        self.write_epub_book(BOOK_CN, "<p>中文A</p>")
        self.write_epub_book(BOOK_CN2, "<p>中文C</p>")
        self.rebaseline()

    @staticmethod
    def xhtml(text: str) -> str:
        return "\n".join(["<?xml version='1.0' encoding='utf-8'?>", "<!DOCTYPE html>",
                          "<html><head/><body>", "", "", text, "</body></html>"])

    @staticmethod
    def _populate(book: Path, text: str) -> None:
        from docx2epub import _CSS
        wid = book.name.split("】")[0][1:]
        name = f"{wid}-01_Chapter.xhtml"
        (book / "META-INF").mkdir(parents=True, exist_ok=True)
        (book / "mimetype").write_bytes(b"application/epub+zip")
        (book / "META-INF" / "container.xml").write_text(
            '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>', encoding="utf-8")
        (book / "OEBPS" / "Text").mkdir(parents=True, exist_ok=True)
        (book / "OEBPS" / "Styles").mkdir(parents=True, exist_ok=True)
        (book / "OEBPS" / "Styles" / "style.css").write_text(_CSS, encoding="utf-8")
        # 构成合规（docs/epub-artifact-spec.md）：dc:title 等于书目录名，导航与两张必备包装页齐备。
        # 发布预检会把成品构成的 error 级一并纳入阻断，夹具不满足它就跑不出「成功发布」路径。
        (book / "OEBPS" / "content.opf").write_text(
            '<package><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<dc:title id="id">{book.name}</dc:title></metadata><manifest>'
            f'<item id="cover" href="Text/{wid}-Cover.xhtml" media-type="application/xhtml+xml"/>'
            f'<item id="info" href="Text/{wid}-Information.xhtml" media-type="application/xhtml+xml"/>'
            f'<item id="text" href="Text/{name}" media-type="application/xhtml+xml"/>'
            '<item id="css" href="Styles/style.css" media-type="text/css"/>'
            '<item id="nav" href="../nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            '<item id="ncx" href="../toc.ncx" media-type="application/x-dtbncx+xml"/>'
            '</manifest><spine toc="ncx">'
            '<itemref idref="cover"/><itemref idref="info"/><itemref idref="text"/>'
            '</spine></package>', encoding="utf-8")
        (book / "OEBPS" / "Text" / name).write_text(Fixture.xhtml(text), encoding="utf-8")
        (book / "OEBPS" / "Text" / f"{wid}-Cover.xhtml").write_text(
            Fixture.xhtml("<p>封面</p>"), encoding="utf-8")
        (book / "OEBPS" / "Text" / f"{wid}-Information.xhtml").write_text(
            Fixture.xhtml("<p>制作信息</p>"), encoding="utf-8")
        (book / "nav.xhtml").write_text(
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
            '<head><title>Navigation</title></head>'
            '<body><nav epub:type="toc"><ol>'
            f'<li><a href="OEBPS/Text/{wid}-Information.xhtml">制作信息</a></li>'
            '</ol></nav></body></html>', encoding="utf-8")
        (book / "toc.ncx").write_text(
            f'<ncx><docTitle><text>{book.name}</text></docTitle><navMap>'
            '<navPoint id="num_1" playOrder="1"><navLabel><text>制作信息</text></navLabel>'
            f'<content src="OEBPS/Text/{wid}-Information.xhtml"/></navPoint>'
            '</navMap></ncx>', encoding="utf-8")

    def write_cache_book(self, side: str, name: str, text: str) -> Path:
        book = self.cache / side / name
        self._populate(book, text)
        return book

    def write_epub_book(self, name: str, text: str) -> Path:
        book = self.epub / name
        self._populate(book, text)
        return book

    def write_book(self, base: Path, side: str, name: str, text: str) -> Path:
        """按副本布局写入：缓存为 '<side>/<书>'，EPUB/ 为根下的 '<书>'。"""
        if base == self.epub:
            return self.write_epub_book(name, text)
        return self.write_cache_book(side, name, text)

    def rebaseline(self) -> None:
        files = dict(scan_cache(self.cache))
        files.update(scan_epub(self.epub))
        save_manifest(self.cache, files)

    def argv(self, *extra: str) -> list[str]:
        return [
            "--cache", str(self.cache),
            "--epub", str(self.epub),
            "--chinese-onedrive", str(self.onedrive_cn),
            "--japanese-onedrive", str(self.onedrive_jp),
            *extra,
        ]


class ToolTestCase(unittest.TestCase):
    """公共夹具与命令捕获；不含测试方法，供各测试类继承。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, *extra: str) -> tuple[int, list[list[str]], str]:
        calls: list[list[str]] = []
        buffer = io.StringIO()

        def fake_run(cmd: list[str]) -> int:
            calls.append(cmd)
            return 0

        with patch.object(publish_auto, "run_command", fake_run), patch.object(
            publish_auto, "find_powershell", lambda: "pwsh"
        ), contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = publish_auto.main(self.fx.argv(*extra))
        return code, calls, buffer.getvalue()

    @staticmethod
    def tool_name(cmd: list[str]) -> str:
        return Path(cmd[1]).name

    @staticmethod
    def run_script(cmd: list[str]) -> str:
        for part in cmd:
            name = Path(part).name
            if name.endswith(".py"):
                return name
            if name.endswith(".ps1"):
                return name
        return ""

    @staticmethod
    def only_books(cmd: list[str]) -> str:
        return cmd[cmd.index("--only-books") + 1]


class RoutingTests(ToolTestCase):

    def test_cache_only_change_routes_to_publish(self):
        self.fx.write_book(self.fx.cache, "chinese-text", BOOK_CN, "<p>中文B</p>")
        code, calls, _ = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.tool_name(calls[0]), "publish.py")
        self.assertEqual(self.only_books(calls[0]), f"chinese-text/{BOOK_CN}")

    def test_epub_only_change_routes_to_publish_epub(self):
        self.fx.write_book(self.fx.epub, "chinese-text", BOOK_CN, "<p>中文B</p>")
        code, calls, _ = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.tool_name(calls[0]), "publish_epub.py")
        self.assertEqual(self.only_books(calls[0]), f"chinese-text/{BOOK_CN}")

    def test_disjoint_changes_run_both_directions(self):
        self.fx.write_book(self.fx.cache, "chinese-text", BOOK_CN, "<p>中文B</p>")
        self.fx.write_book(self.fx.epub, "chinese-text", BOOK_CN2, "<p>中文D</p>")
        code, calls, _ = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual([self.tool_name(cmd) for cmd in calls], ["publish.py", "publish_epub.py"])
        self.assertEqual(self.only_books(calls[0]), f"chinese-text/{BOOK_CN}")
        self.assertEqual(self.only_books(calls[1]), f"chinese-text/{BOOK_CN2}")

    def test_same_book_on_both_sides_stops_without_guessing(self):
        self.fx.write_book(self.fx.cache, "chinese-text", BOOK_CN, "<p>缓存版</p>")
        self.fx.write_book(self.fx.epub, "chinese-text", BOOK_CN, "<p>归档版</p>")
        code, calls, output = self.run_tool()
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertIn("--from cache", output)
        self.assertIn("--from epub", output)

    def test_identical_changes_on_both_sides_route_to_flow_c(self):
        self.fx.write_book(self.fx.cache, "chinese-text", BOOK_CN, "<p>双方同改</p>")
        self.fx.write_book(self.fx.epub, "chinese-text", BOOK_CN, "<p>双方同改</p>")
        code, calls, output = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual([self.tool_name(cmd) for cmd in calls], ["publish_epub.py"])
        self.assertNotIn("--overwrite-cache", calls[0])
        self.assertIn("缓存侧内容已包含在 EPUB/ 中", output)

    def test_identical_overlap_with_epub_only_file_routes_to_flow_c(self):
        self.fx.write_book(self.fx.cache, "chinese-text", BOOK_CN, "<p>双方同改</p>")
        epub_book = self.fx.write_book(
            self.fx.epub, "chinese-text", BOOK_CN, "<p>双方同改</p>"
        )
        (epub_book / "OEBPS" / "b.xhtml").write_text(
            "<p>仅归档新增</p>", encoding="utf-8"
        )
        code, calls, _ = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual([self.tool_name(cmd) for cmd in calls], ["publish_epub.py"])
        self.assertNotIn("--overwrite-cache", calls[0])

    def test_from_cache_resolves_conflict_to_flow_b(self):
        self.fx.write_book(self.fx.cache, "chinese-text", BOOK_CN, "<p>缓存版</p>")
        self.fx.write_book(self.fx.epub, "chinese-text", BOOK_CN, "<p>归档版</p>")
        code, calls, output = self.run_tool("--from", "cache")
        self.assertEqual(code, 0)
        self.assertEqual([self.tool_name(cmd) for cmd in calls], ["publish.py"])
        self.assertIn("以缓存为准", output)

    def test_from_cache_resolves_identical_overlap_only_once(self):
        self.fx.write_book(self.fx.cache, "chinese-text", BOOK_CN, "<p>双方同改</p>")
        epub_book = self.fx.write_book(
            self.fx.epub, "chinese-text", BOOK_CN, "<p>双方同改</p>"
        )
        (epub_book / "OEBPS" / "b.xhtml").write_text(
            "<p>仅归档新增</p>", encoding="utf-8"
        )
        code, calls, _ = self.run_tool("--from", "cache")
        self.assertEqual(code, 0)
        self.assertEqual([self.tool_name(cmd) for cmd in calls], ["publish.py"])

    def test_from_epub_requires_overwrite_cache_for_conflicts(self):
        self.fx.write_book(self.fx.cache, "chinese-text", BOOK_CN, "<p>缓存版</p>")
        self.fx.write_book(self.fx.epub, "chinese-text", BOOK_CN, "<p>归档版</p>")
        code, calls, output = self.run_tool("--from", "epub")
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertIn("--overwrite-cache", output)

        code, calls, _ = self.run_tool("--from", "epub", "--overwrite-cache")
        self.assertEqual(code, 0)
        self.assertEqual([self.tool_name(cmd) for cmd in calls], ["publish_epub.py"])
        self.assertIn("--overwrite-cache", calls[0])

    def test_dry_run_previews_without_executing(self):
        self.fx.write_book(self.fx.cache, "chinese-text", BOOK_CN, "<p>中文B</p>")
        code, calls, output = self.run_tool("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertIn("publish.py", output)

    def test_side_filter_excludes_other_side(self):
        self.fx.write_book(self.fx.cache, "chinese-text", BOOK_CN, "<p>中文B</p>")
        code, calls, _ = self.run_tool("--side", "japanese")
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])

    def test_newline_diff_has_no_warning(self):
        """换行符差异不输出任何警告，项目对换行符不敏感。"""
        cache_file = self.fx.cache / "chinese-text" / BOOK_CN / "OEBPS" / "Text" / "S1_01-01_Chapter.xhtml"
        epub_file = self.fx.epub / BOOK_CN / "OEBPS" / "Text" / "S1_01-01_Chapter.xhtml"
        cache_file.write_bytes(b"<p>x</p>\r\n")
        epub_file.write_bytes(b"<p>x</p>\n")
        # 基线记录上次发布的缓存字节（CRLF）；归档被检出成 LF
        save_manifest(self.fx.cache, scan_cache(self.fx.cache))
        code, _, output = self.run_tool("--dry-run")
        self.assertEqual(code, 0)
        self.assertNotIn("只差换行符", output)
        self.assertNotIn("换行", output)

    def test_force_requires_explicit_direction(self):
        code, calls, output = self.run_tool("--force")
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertIn("--from", output)

    def test_missing_manifest_stops(self):
        (self.fx.cache / "manifest.json").unlink()
        code, calls, output = self.run_tool()
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertIn("pull.ps1", output)


class OnedriveDriftTests(ToolTestCase):
    """OneDrive 侧外部更新：与 pull.ps1 同一判定（pull-state 的 mtime/size）。"""

    def seed_onedrive(self, side_dir: Path, name: str, contents: bytes = b"epub") -> Path:
        side_dir.mkdir(parents=True, exist_ok=True)
        target = side_dir / f"{name}.epub"
        target.write_bytes(contents)
        return target

    def write_pull_state(self, records: dict[str, tuple[int, int]]) -> None:
        lines = [f"{key.split('/', 1)[0]}\t{key.split('/', 1)[1]}\t{ticks}\t{size}"
                 for key, (ticks, size) in sorted(records.items())]
        (self.fx.cache / "pull-state.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def record_of(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_mtime_ns // 100 + UNIX_TO_DOTNET_TICKS_OFFSET, stat.st_size

    def test_no_record_counts_as_external_update(self):
        self.seed_onedrive(self.fx.onedrive_jp, BOOK_JP)
        code, calls, output = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.run_script(calls[0]), "pull.ps1")
        self.assertIn("-SyncToEpub", calls[0])
        self.assertIn("流程 A", output)

    def test_matching_record_is_not_drift(self):
        epub = self.seed_onedrive(self.fx.onedrive_jp, BOOK_JP)
        self.write_pull_state({f"japanese-text/{BOOK_JP}": self.record_of(epub)})
        code, calls, _ = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])

    def test_touched_file_is_drift(self):
        epub = self.seed_onedrive(self.fx.onedrive_jp, BOOK_JP, b"old")
        self.write_pull_state({f"japanese-text/{BOOK_JP}": self.record_of(epub)})
        epub.write_bytes(b"new contents")
        code, calls, _ = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual([self.run_script(cmd) for cmd in calls], ["pull.ps1"])

    def test_drift_plus_local_edit_on_same_book_stops(self):
        self.seed_onedrive(self.fx.onedrive_cn, BOOK_CN)
        self.fx.write_book(self.fx.cache, "chinese-text", BOOK_CN, "<p>本地版</p>")
        code, calls, output = self.run_tool()
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertIn("--from onedrive", output)

    def test_from_cache_skips_implicit_pull(self):
        self.seed_onedrive(self.fx.onedrive_jp, BOOK_JP)
        self.fx.write_book(self.fx.cache, "chinese-text", BOOK_CN, "<p>中文B</p>")
        code, calls, _ = self.run_tool("--from", "cache")
        self.assertEqual(code, 0)
        self.assertEqual([self.tool_name(cmd) for cmd in calls], ["publish.py"])

    def test_only_books_skips_flow_a_instead_of_widening_scope(self):
        """--only-books 不能约束 pull.ps1 的整本解压，此时宁可不拉也不越界写入。"""
        self.seed_onedrive(self.fx.onedrive_jp, BOOK_JP)
        code, calls, output = self.run_tool("--only-books", f"japanese-text/{BOOK_JP}")
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertIn("已跳过 OneDrive 拉取", output)


class IntegrationTests(unittest.TestCase):
    """真调用底层工具，验证路由传参确实驱动完整发布链路。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, *extra: str) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return publish_auto.main(self.fx.argv(*extra))

    def test_cache_change_publishes_through_real_tools(self):
        target = self.fx.cache / "chinese-text" / BOOK_CN / "OEBPS" / "Text" / "S1_01-01_Chapter.xhtml"
        target.write_text(Fixture.xhtml("<p>中文B</p>"), encoding="utf-8")

        self.assertEqual(self.run_tool("--side", "chinese", "--no-upload"), 0)

        archived = self.fx.epub / BOOK_CN / "OEBPS" / "Text" / "S1_01-01_Chapter.xhtml"
        self.assertEqual(archived.read_text(encoding="utf-8"), Fixture.xhtml("<p>中文B</p>"))
        self.assertTrue(
            (self.fx.cache / "packed-epubs" / "chinese-text" / f"{BOOK_CN}.epub").is_file()
        )
        # 发布成功后基线推进，重跑应为空操作
        self.assertEqual(self.run_tool("--side", "chinese", "--no-upload"), 0)
        japanese = self.fx.cache / "japanese-text" / BOOK_JP / "OEBPS" / "Text" / "S1_01-01_Chapter.xhtml"
        self.assertEqual(japanese.read_text(encoding="utf-8"), Fixture.xhtml("<p>日文A</p>"))

    def test_epub_change_flows_back_through_real_tools(self):
        target = self.fx.epub / BOOK_CN / "OEBPS" / "Text" / "S1_01-01_Chapter.xhtml"
        target.write_text(Fixture.xhtml("<p>归档新</p>"), encoding="utf-8")

        self.assertEqual(self.run_tool("--side", "chinese", "--no-upload"), 0)

        cached = self.fx.cache / "chinese-text" / BOOK_CN / "OEBPS" / "Text" / "S1_01-01_Chapter.xhtml"
        self.assertEqual(cached.read_text(encoding="utf-8"), Fixture.xhtml("<p>归档新</p>"))

    def test_identical_changes_advance_manifest_through_real_tools(self):
        cache_target = self.fx.cache / "chinese-text" / BOOK_CN / "OEBPS" / "Text" / "S1_01-01_Chapter.xhtml"
        epub_target = self.fx.epub / BOOK_CN / "OEBPS" / "Text" / "S1_01-01_Chapter.xhtml"
        cache_target.write_text(Fixture.xhtml("<p>双方同改</p>"), encoding="utf-8")
        epub_target.write_text(Fixture.xhtml("<p>双方同改</p>"), encoding="utf-8")

        self.assertEqual(self.run_tool("--side", "chinese", "--no-upload"), 0)
        self.assertEqual(self.run_tool("--side", "chinese", "--no-upload"), 0)


class PublicationPlanTests(ToolTestCase):
    def prepare(self, *extra: str, powershell: str | None = "pwsh"):
        args = publish_auto.parse_args(self.fx.argv(*extra))
        with patch.object(publish_auto, "find_powershell", return_value=powershell):
            return publish_auto.prepare_plan(args)

    @staticmethod
    def option(argv, name):
        return argv[argv.index(name) + 1]

    def test_prepare_is_read_only_and_does_not_print_or_execute(self):
        self.fx.write_cache_book("chinese-text", BOOK_CN, "<p>中文B</p>")
        before = {p.relative_to(self.fx.root): p.read_bytes()
                  for p in self.fx.root.rglob("*") if p.is_file()}
        output = io.StringIO()
        with patch.object(publish_auto, "run_command", side_effect=AssertionError("executed")), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            plan = self.prepare("--side", "chinese")
        after = {p.relative_to(self.fx.root): p.read_bytes()
                 for p in self.fx.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(plan.status, "ready")

    def test_normal_and_forced_commands_keep_supported_config_and_scope(self):
        for source in ("cache", "epub"):
            for forced in (False, True):
                with self.subTest(source=source, forced=forced):
                    self.fx.write_cache_book("chinese-text", BOOK_CN, "<p>中文A</p>")
                    self.fx.write_epub_book(BOOK_CN, "<p>中文A</p>")
                    if source == "cache":
                        self.fx.write_cache_book("chinese-text", BOOK_CN, "<p>中文B</p>")
                    else:
                        self.fx.write_epub_book(BOOK_CN, "<p>归档新</p>")
                    options = ["--from", source, "--side", "chinese",
                               "--pattern", "*S1_01*", "--no-upload", "--overwrite-cache"]
                    if forced:
                        options.append("--force")
                    plan = self.prepare(*options)
                    self.assertEqual(plan.status, "ready")
                    self.assertEqual(len(plan.steps), 1)
                    step = plan.steps[0]
                    self.assertEqual(step.direction, "B" if source == "cache" else "C")
                    self.assertEqual(self.option(step.argv, "--only-books"), f"chinese-text/{BOOK_CN}")
                    self.assertEqual(self.option(step.argv, "--chinese-onedrive"),
                                     str(self.fx.onedrive_cn.resolve()))
                    self.assertIn("--no-upload", step.argv)
                    self.assertEqual("--force" in step.argv, forced)
                    if source == "cache":
                        self.assertEqual(self.option(step.argv, "--side"), "chinese")
                        self.assertEqual(self.option(step.argv, "--japanese-onedrive"),
                                         str(self.fx.onedrive_jp.resolve()))
                        self.assertNotIn("--overwrite-cache", step.argv)
                    else:
                        self.assertNotIn("--side", step.argv)
                        self.assertNotIn("--japanese-onedrive", step.argv)
                        self.assertIn("--overwrite-cache", step.argv)

    def test_force_a_only_books_is_blocked_for_preview_and_execution(self):
        for preview in (False, True):
            options = ["--from", "onedrive", "--force", "--only-books", f"chinese-text/{BOOK_CN}"]
            if preview:
                options.append("--dry-run")
            plan = self.prepare(*options)
            self.assertEqual(plan.status, "blocked")
            self.assertEqual(plan.steps, ())
            output = io.StringIO()
            with patch.object(publish_auto, "run_command") as run, \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.assertEqual(publish_auto.run_plan(plan), 1)
            run.assert_not_called()
            self.assertIn("--only-books", output.getvalue())

    def test_force_a_preview_keeps_side_pattern_sources_and_whatif(self):
        plan = self.prepare("--from", "onedrive", "--force", "--side", "chinese",
                            "--pattern", "*S1_01*", "--dry-run")
        self.assertEqual(plan.status, "ready")
        self.assertEqual([step.direction for step in plan.steps], ["A"])
        argv = plan.steps[0].argv
        self.assertEqual(self.option(argv, "-Side"), "chinese")
        self.assertEqual(self.option(argv, "-Pattern"), "*S1_01*")
        self.assertEqual(self.option(argv, "-ChineseSourceDirectory"), str(self.fx.onedrive_cn.resolve()))
        self.assertEqual(self.option(argv, "-JapaneseSourceDirectory"), str(self.fx.onedrive_jp.resolve()))
        self.assertIn("-Force", argv)
        self.assertIn("-WhatIf", argv)
        with patch.object(publish_auto, "run_command") as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(publish_auto.run_plan(plan), 0)
        run.assert_not_called()

    def test_preview_and_argv_are_fixed_after_preparation(self):
        self.fx.write_cache_book("chinese-text", BOOK_CN, "<p>中文B</p>")
        args = publish_auto.parse_args(self.fx.argv("--dry-run", "--side", "chinese"))
        plan = publish_auto.prepare_plan(args)
        args.dry_run = False
        args.chinese_onedrive = Path("other")
        with self.assertRaises(AttributeError):
            plan.preview = False
        output = io.StringIO()
        with patch.object(publish_auto, "run_command") as run, \
                patch.object(publish_auto, "scan_cache", side_effect=AssertionError("rescanned")), \
                patch.object(publish_auto, "build_publish_command", side_effect=AssertionError("rebuilt")), \
                contextlib.redirect_stdout(output):
            self.assertEqual(publish_auto.run_plan(plan), 0)
        run.assert_not_called()
        self.assertIn(publish_auto.display_command(list(plan.steps[0].argv)), output.getvalue())
        self.assertEqual(self.option(plan.steps[0].argv, "--chinese-onedrive"),
                         str(self.fx.onedrive_cn.resolve()))

    def test_runner_uses_prepared_argv_and_stops_at_first_failure(self):
        self.fx.onedrive_jp.mkdir()
        (self.fx.onedrive_jp / f"{BOOK_JP}.epub").write_bytes(b"external")
        self.fx.write_cache_book("chinese-text", BOOK_CN, "<p>中文B</p>")
        self.fx.write_epub_book(BOOK_CN2, "<p>归档新</p>")
        plan = self.prepare()
        self.assertEqual([step.direction for step in plan.steps], ["A", "B", "C"])
        for failure in (-1, 0, 1, 2):
            calls = []

            def run(argv):
                calls.append(tuple(argv))
                return 7 if len(calls) - 1 == failure else 0

            with patch.object(publish_auto, "run_command", run), \
                    patch.object(publish_auto, "scan_cache", side_effect=AssertionError("rescanned")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(publish_auto.run_plan(plan), 0 if failure == -1 else 1)
            count = 3 if failure == -1 else failure + 1
            self.assertEqual(calls, [step.argv for step in plan.steps[:count]])

    def test_blocked_and_noop_plans_never_execute(self):
        noop = self.prepare()
        (self.fx.cache / "manifest.json").unlink()
        blocked = self.prepare()
        for plan, status, code in ((noop, "noop", 0), (blocked, "blocked", 1)):
            self.assertEqual(plan.status, status)
            self.assertEqual(plan.steps, ())
            with patch.object(publish_auto, "run_command") as run, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(publish_auto.run_plan(plan), code)
            run.assert_not_called()

    def test_completed_pull_is_not_reuploaded_when_a_will_run(self):
        from package_cache_epubs import package_book
        self.fx.write_cache_book("chinese-text", BOOK_CN, "<p>中文B</p>")
        package_book(self.fx.cache / "chinese-text" / BOOK_CN,
                     self.fx.onedrive_cn / f"{BOOK_CN}.epub")
        plan = self.prepare("--side", "chinese")
        self.assertEqual([step.direction for step in plan.steps], ["A"])
        self.assertTrue(any("已完成的拉取" in message.text for message in plan.diagnostics))
        scoped = self.prepare("--side", "chinese", "--only-books", f"chinese-text/{BOOK_CN}")
        self.assertEqual([step.direction for step in scoped.steps], ["B"])
        self.assertTrue(any("本次方向不会执行流程 A" in message.text for message in scoped.diagnostics))

    def test_powershell_is_required_only_for_a(self):
        self.fx.write_cache_book("chinese-text", BOOK_CN, "<p>中文B</p>")
        local = self.prepare("--side", "chinese", powershell=None)
        self.assertEqual([step.direction for step in local.steps], ["B"])
        self.fx.onedrive_jp.mkdir()
        (self.fx.onedrive_jp / f"{BOOK_JP}.epub").write_bytes(b"external")
        mixed = self.prepare(powershell=None)
        self.assertEqual(mixed.status, "blocked")
        self.assertEqual(mixed.steps, ())


class ConfiguredTargetIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def run_local_plan(self, fx, *extra):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            plan = publish_auto.prepare_plan(publish_auto.parse_args(fx.argv(*extra)))
            self.assertEqual(plan.status, "ready")
            # 真实执行前先验证每条命令的全部目录，禁止测试落到任何默认工作区／OneDrive。
            for step in plan.steps:
                self.assertIn(step.direction, ("B", "C"))
                for name, expected in (("--cache", fx.cache), ("--epub", fx.epub),
                                       ("--chinese-onedrive", fx.onedrive_cn)):
                    self.assertEqual(Path(step.argv[step.argv.index(name) + 1]), expected.resolve())
                if step.direction == "B":
                    name = "--japanese-onedrive"
                    self.assertEqual(Path(step.argv[step.argv.index(name) + 1]), fx.onedrive_jp.resolve())
                else:
                    self.assertNotIn("--japanese-onedrive", step.argv)
            return publish_auto.run_plan(plan)

    def test_normal_and_forced_publish_use_configured_temp_targets(self):
        for source in ("cache", "epub"):
            for forced in (False, True):
                with self.subTest(source=source, forced=forced):
                    fx = Fixture(Path(self._tmp.name) / f"{source}-{forced}")
                    fx.onedrive_cn.mkdir()
                    fx.onedrive_jp.mkdir()
                    if source == "cache":
                        fx.write_cache_book("chinese-text", BOOK_CN, "<p>中文B</p>")
                    else:
                        fx.write_epub_book(BOOK_CN, "<p>归档新</p>")
                    options = ["--from", source, "--side", "chinese", "--pattern", "*S1_01*"]
                    if forced:
                        options.append("--force")
                    self.assertEqual(self.run_local_plan(fx, *options), 0)
                    self.assertTrue((fx.onedrive_cn / f"{BOOK_CN}.epub").is_file())
                    self.assertEqual(list(fx.onedrive_jp.iterdir()), [])
                    cache_text = fx.cache / "chinese-text" / BOOK_CN / "OEBPS/Text/S1_01-01_Chapter.xhtml"
                    epub_text = fx.epub / BOOK_CN / "OEBPS/Text/S1_01-01_Chapter.xhtml"
                    self.assertEqual(cache_text.read_bytes(), epub_text.read_bytes())

    def test_chinese_b_does_not_require_a_japanese_baseline(self):
        from manifest import load_manifest
        fx = Fixture(Path(self._tmp.name) / "chinese-only")
        fx.onedrive_cn.mkdir()
        fx.onedrive_jp.mkdir()
        baseline = load_manifest(fx.cache)
        save_manifest(fx.cache, {key: value for key, value in baseline.items()
                                 if key.startswith("chinese-text/")})
        fx.write_cache_book("chinese-text", BOOK_CN, "<p>中文B</p>")
        self.assertEqual(self.run_local_plan(fx, "--side", "chinese"), 0)
        self.assertTrue((fx.onedrive_cn / f"{BOOK_CN}.epub").is_file())
        self.assertFalse(any(key.startswith("japanese-text/") for key in load_manifest(fx.cache)))


if __name__ == "__main__":
    unittest.main()
