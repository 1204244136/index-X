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
from manifest import save_manifest, scan_cache  # noqa: E402
from publish_epub import scan_epub  # noqa: E402
from sync_core import UNIX_TO_DOTNET_TICKS_OFFSET  # noqa: E402

BOOK_CN = "[S1_01]某书"
BOOK_CN2 = "[S1_02]他书"
BOOK_JP = "[S1_01]某書"


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
    def _populate(book: Path, text: str) -> None:
        (book / "META-INF").mkdir(parents=True, exist_ok=True)
        (book / "mimetype").write_bytes(b"application/epub+zip")
        (book / "META-INF" / "container.xml").write_text("<container/>", encoding="utf-8")
        (book / "OEBPS").mkdir(parents=True, exist_ok=True)
        (book / "OEBPS" / "a.xhtml").write_text(text, encoding="utf-8")

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

    def test_newline_only_epub_diff_is_flagged(self):
        """归档目录被换行转换时给出警告，避免误当成真实编辑反向覆盖缓存。"""
        cache_file = self.fx.cache / "chinese-text" / BOOK_CN / "OEBPS" / "a.xhtml"
        epub_file = self.fx.epub / BOOK_CN / "OEBPS" / "a.xhtml"
        cache_file.write_bytes(b"<p>x</p>\r\n")
        epub_file.write_bytes(b"<p>x</p>\n")
        # 基线记录上次发布的缓存字节（CRLF）；归档被检出成 LF
        save_manifest(self.fx.cache, scan_cache(self.fx.cache))
        code, _, output = self.run_tool("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("只差换行符", output)

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
        target = self.fx.cache / "chinese-text" / BOOK_CN / "OEBPS" / "a.xhtml"
        target.write_text("<p>中文B</p>", encoding="utf-8")

        self.assertEqual(self.run_tool("--side", "chinese", "--no-upload"), 0)

        archived = self.fx.epub / BOOK_CN / "OEBPS" / "a.xhtml"
        self.assertEqual(archived.read_text(encoding="utf-8"), "<p>中文B</p>")
        self.assertTrue(
            (self.fx.cache / "packed-epubs" / "chinese-text" / f"{BOOK_CN}.epub").is_file()
        )
        # 发布成功后基线推进，重跑应为空操作
        self.assertEqual(self.run_tool("--side", "chinese", "--no-upload"), 0)
        japanese = self.fx.cache / "japanese-text" / BOOK_JP / "OEBPS" / "a.xhtml"
        self.assertEqual(japanese.read_text(encoding="utf-8"), "<p>日文A</p>")

    def test_epub_change_flows_back_through_real_tools(self):
        target = self.fx.epub / BOOK_CN / "OEBPS" / "a.xhtml"
        target.write_text("<p>归档新</p>", encoding="utf-8")

        self.assertEqual(self.run_tool("--side", "chinese", "--no-upload"), 0)

        cached = self.fx.cache / "chinese-text" / BOOK_CN / "OEBPS" / "a.xhtml"
        self.assertEqual(cached.read_text(encoding="utf-8"), "<p>归档新</p>")

    def test_identical_changes_advance_manifest_through_real_tools(self):
        cache_target = self.fx.cache / "chinese-text" / BOOK_CN / "OEBPS" / "a.xhtml"
        epub_target = self.fx.epub / BOOK_CN / "OEBPS" / "a.xhtml"
        cache_target.write_text("<p>双方同改</p>", encoding="utf-8")
        epub_target.write_text("<p>双方同改</p>", encoding="utf-8")

        self.assertEqual(self.run_tool("--side", "chinese", "--no-upload"), 0)
        self.assertEqual(self.run_tool("--side", "chinese", "--no-upload"), 0)


if __name__ == "__main__":
    unittest.main()
