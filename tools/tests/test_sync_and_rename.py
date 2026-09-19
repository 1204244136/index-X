from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from fix_empty_placeholders import apply_candidate  # noqa: E402
from manifest import compute_hash, scan_cache, scan_epub  # noqa: E402
from publish import alignment_preflight, publish_book  # noqa: E402
from publish_epub import publish_book_reverse  # noqa: E402
from sync_core import (  # noqa: E402
    UNIX_TO_DOTNET_TICKS_OFFSET,
    detect_changes,
    find_conflicts,
    missing_baseline_sides,
    read_pull_state,
    sync_file_changes,
    upload_book,
)


class SyncCoreTests(unittest.TestCase):
    def test_upload_records_destination_and_preserves_other_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packed, destination = root / "packed.epub", root / "uploaded.epub"
            packed.write_bytes(b"packaged book")
            (root / "pull-state.tsv").write_text(
                "\ufeffjapanese-text\tother\t123\t456\ninvalid\n",
                encoding="utf-8",
            )
            upload_book(packed, destination, root, "chinese-text/book")
            self.assertEqual(destination.read_bytes(), packed.read_bytes())
            stat = destination.stat()
            self.assertEqual(read_pull_state(root), {
                "japanese-text/other": ("123", "456"),
                "chinese-text/book": (
                    str(stat.st_mtime_ns // 100 + UNIX_TO_DOTNET_TICKS_OFFSET),
                    str(stat.st_size),
                ),
            })

    def test_failed_upload_does_not_advance_pull_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "pull-state.tsv"
            original = b"chinese-text\tbook\t123\t456\n"
            state.write_bytes(original)
            with self.assertRaises(OSError):
                upload_book(root / "missing.epub", root / "dest.epub", root,
                            "chinese-text/book")
            self.assertEqual(state.read_bytes(), original)

    def test_reverse_upload_state_failure_stops_cache_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub, cache, onedrive = root / "epub", root / "cache", root / "onedrive"
            (epub / "book").mkdir(parents=True)
            (cache / "chinese-text/book").mkdir(parents=True)
            onedrive.mkdir()
            target = cache / "chinese-text/book/a.txt"
            target.write_bytes(b"old")
            (epub / "book/a.txt").write_bytes(b"new")
            with patch("publish_epub.package_book", return_value=3), \
                    patch("publish_epub.upload_book", side_effect=OSError("state failed")):
                ok, message = publish_book_reverse(
                    "chinese-text/book", {"a.txt": "modified"}, epub, cache, onedrive,
                )
            self.assertFalse(ok)
            self.assertIn("state failed", message)
            self.assertEqual(target.read_bytes(), b"old")

    def test_alignment_preflight_uses_strict_mode(self):
        with patch("publish.subprocess.run") as run:
            run.return_value.returncode = 1
            self.assertFalse(alignment_preflight(Path("cache")))
            self.assertIn("--strict", run.call_args.args[0])

    def test_detect_and_apply_delta(self):
        current = {"chinese-text/book/a.txt": "new", "chinese-text/book/b.txt": "b"}
        baseline = {"chinese-text/book/a.txt": "old", "chinese-text/book/c.txt": "c"}
        changes = detect_changes(current, baseline)["chinese-text/book"]
        self.assertEqual(changes, {"a.txt": "modified", "b.txt": "added", "c.txt": "deleted"})

        with tempfile.TemporaryDirectory() as tmp:
            source, destination = Path(tmp) / "src", Path(tmp) / "dst"
            source.mkdir()
            destination.mkdir()
            (source / "a.txt").write_text("new", encoding="utf-8")
            (source / "b.txt").write_text("b", encoding="utf-8")
            (destination / "a.txt").write_text("old", encoding="utf-8")
            (destination / "c.txt").write_text("c", encoding="utf-8")
            self.assertEqual(sync_file_changes(source, destination, changes), (2, 1))
            self.assertEqual((destination / "a.txt").read_text(encoding="utf-8"), "new")
            self.assertFalse((destination / "c.txt").exists())

    def test_missing_source_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, destination = Path(tmp) / "src", Path(tmp) / "dst"
            source.mkdir()
            with self.assertRaises(FileNotFoundError):
                sync_file_changes(source, destination, {"missing": "added"})

    def test_missing_upload_target_fails_before_mirroring(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache, epub = root / "cache", root / "epub"
            source = cache / "chinese-text" / "book"
            source.mkdir(parents=True)
            epub.mkdir()
            (source / "a.txt").write_text("a", encoding="utf-8")
            missing = root / "missing-onedrive"
            ok, message = publish_book(
                "chinese-text/book", {"a.txt": "added"}, cache, epub,
                {"chinese-text": missing},
            )
            self.assertFalse(ok)
            self.assertIn("OneDrive", message)
            self.assertFalse((epub / "book").exists())

            ok, message = publish_book_reverse(
                "chinese-text/book", {"a.txt": "added"}, epub, cache, missing,
            )
            self.assertFalse(ok)
            self.assertIn("OneDrive", message)

    def test_removed_book_is_retired_not_packaged(self):
        """整本已从缓存移除的书走清理路径：删 OneDrive 旧 EPUB 与 pull-state 记录，不打包。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache, epub, onedrive = (
                root / "cache", root / "epub", root / "onedrive")
            cache.mkdir()
            onedrive.mkdir()
            epub.mkdir()
            (cache / "pull-state.tsv").write_text(
                "japanese-text\t[S5_01]旧合订卷\t123\t456\n"
                "japanese-text\t[S5_01_01]新拆分\t789\t10\n",
                encoding="utf-8",
            )
            (onedrive / "[S5_01]旧合订卷.epub").write_bytes(b"old")

            ok, message = publish_book(
                "japanese-text/[S5_01]旧合订卷",
                {"mimetype": "deleted", "item/a.xhtml": "deleted"},
                cache, epub,
                {"japanese-text": onedrive},
            )
            self.assertTrue(ok, message)
            self.assertFalse((onedrive / "[S5_01]旧合订卷.epub").exists())
            state = (cache / "pull-state.tsv").read_text(encoding="utf-8")
            self.assertNotIn("旧合订卷", state)
            self.assertIn("[S5_01_01]新拆分", state)

    def test_removed_chinese_book_also_drops_epub_archive(self):
        """中文侧整本删除时，EPUB/ 归档目录一并删除。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache, epub, onedrive = (
                root / "cache", root / "epub", root / "onedrive")
            cache.mkdir()
            onedrive.mkdir()
            epub.mkdir()
            (epub / "[S1_01]旧书").mkdir()
            (epub / "[S1_01]旧书" / "a.xhtml").write_text("x", encoding="utf-8")

            ok, message = publish_book(
                "chinese-text/[S1_01]旧书", {"a.xhtml": "deleted"},
                cache, epub, {"chinese-text": onedrive},
                no_upload=True,
            )
            self.assertTrue(ok, message)
            self.assertFalse((epub / "[S1_01]旧书").exists())


    def test_missing_baseline_side_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / "chinese-text" / "book").mkdir(parents=True)
            (cache / "japanese-text" / "book").mkdir(parents=True)
            baseline = {"chinese-text/book/a.txt": "h"}
            self.assertEqual(missing_baseline_sides(cache, baseline), ["japanese-text"])
            self.assertEqual(
                missing_baseline_sides(cache, baseline, ("chinese-text",)), []
            )

    def test_missing_baseline_side_ignores_side_without_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / "chinese-text" / "book").mkdir(parents=True)
            (cache / "japanese-text").mkdir()
            baseline = {"chinese-text/book/a.txt": "h"}
            self.assertEqual(missing_baseline_sides(cache, baseline), [])

    def test_internal_extract_directories_are_ignored_by_scans_and_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache, epub = root / "cache", root / "epub"
            cache_book = cache / "chinese-text" / "book"
            epub_book = epub / "book"
            cache_book.mkdir(parents=True)
            epub_book.mkdir(parents=True)
            (cache_book / "a.txt").write_text("a", encoding="utf-8")
            (epub_book / "a.txt").write_text("a", encoding="utf-8")
            for base, name in (
                (cache / "chinese-text", ".extract-orphan"),
                (cache_book, ".extract-nested"),
                (epub, ".extract-orphan"),
                (epub_book, ".extract-nested"),
            ):
                target = base / name / "OEBPS" / "leak.txt"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("leak", encoding="utf-8")

            self.assertEqual(set(scan_cache(cache)), {"chinese-text/book/a.txt"})
            self.assertEqual(set(scan_epub(epub)), {"chinese-text/book/a.txt"})

            source, destination = root / "source", root / "destination"
            source.mkdir()
            (source / "a.txt").write_text("a", encoding="utf-8")
            nested = source / ".extract-nested" / "leak.txt"
            nested.parent.mkdir()
            nested.write_text("leak", encoding="utf-8")
            copied, deleted = sync_file_changes(
                source, destination, {}, full_mirror=True
            )
            self.assertEqual((copied, deleted), (1, 0))
            self.assertFalse((destination / ".extract-nested").exists())

    def test_reverse_conflicts_cover_added_modified_and_deleted_cache_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            book_key = "chinese-text/book"
            book = cache / book_key
            book.mkdir(parents=True)
            unchanged = book / "unchanged.txt"
            modified = book / "modified.txt"
            unchanged.write_text("same", encoding="utf-8")
            modified.write_text("cache edit", encoding="utf-8")
            (book / "added.txt").write_text("cache addition", encoding="utf-8")
            baseline = {
                f"{book_key}/unchanged.txt": compute_hash(unchanged),
                f"{book_key}/modified.txt": "baseline hash",
                f"{book_key}/deleted.txt": "baseline hash",
            }

            epub_current = {
                f"{book_key}/deleted.txt": "baseline hash",
            }
            conflicts = find_conflicts(
                book_key, scan_cache(cache), epub_current, baseline
            )

            report = "\n".join(conflicts)
            self.assertIn("added.txt", report)
            self.assertIn("modified.txt", report)
            self.assertIn("deleted.txt", report)
            self.assertNotIn("unchanged.txt", report)

    def test_reverse_conflict_ignores_cache_edits_already_in_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            book_key = "chinese-text/book"
            book = cache / book_key
            book.mkdir(parents=True)
            modified = book / "modified.txt"
            added = book / "added.txt"
            modified.write_text("same edit", encoding="utf-8")
            added.write_text("same addition", encoding="utf-8")
            baseline = {
                f"{book_key}/modified.txt": "baseline hash",
                f"{book_key}/deleted.txt": "baseline hash",
            }
            epub_current = {
                f"{book_key}/modified.txt": compute_hash(modified),
                f"{book_key}/added.txt": compute_hash(added),
            }

            conflicts = find_conflicts(
                book_key, scan_cache(cache), epub_current, baseline
            )

            self.assertEqual(conflicts, [])


class PlaceholderTests(unittest.TestCase):
    def test_rename_updates_metadata_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp)
            (book / "META-INF").mkdir()
            (book / "META-INF" / "container.xml").write_text("container", encoding="utf-8")
            (book / "mimetype").write_text("application/epub+zip", encoding="ascii")
            text = book / "OEBPS" / "Text"
            text.mkdir(parents=True)
            one = text / "S5_01_03-01_p-001.xhtml"
            empty = text / "S5_01_03-02_p-002.xhtml"
            three = text / "S5_01_03-03_p-003.xhtml"
            one.write_text("<body><p>one</p></body>", encoding="utf-8")
            empty.write_text("<body></body>", encoding="utf-8")
            three.write_text("<body><p>three</p></body>", encoding="utf-8")
            opf = book / "OEBPS" / "content.opf"
            opf.write_text(
                '<package><manifest>'
                f'<item id="empty" href="Text/{empty.name}"/>'
                f'<item id="three" href="Text/{three.name}"/>'
                '</manifest><spine><itemref idref="empty"/><itemref idref="three"/>'
                '</spine></package>',
                encoding="utf-8",
            )
            nav = text / "nav.xhtml"
            nav.write_text(
                f'<ol><li><a href="{empty.name}">empty</a></li>'
                f'<li><a href="{three.name}">three</a></li></ol>',
                encoding="utf-8",
            )
            ncx = book / "OEBPS" / "toc.ncx"
            ncx.write_text(
                f'<navMap><navPoint id="empty"><content src="Text/{empty.name}"/></navPoint>'
                f'<navPoint id="three"><content src="Text/{three.name}"/></navPoint></navMap>',
                encoding="utf-8",
            )

            renamed, refs = apply_candidate(empty)
            target = text / "S5_01_03-02_p-002.xhtml"
            self.assertEqual(len(renamed), 1)
            self.assertEqual(refs, 3)
            self.assertTrue(target.is_file())
            opf_text = opf.read_text(encoding="utf-8")
            self.assertIn(target.name, opf_text)
            self.assertNotIn(three.name, opf_text)
            self.assertNotIn('id="empty"', opf_text)
            self.assertNotIn('idref="empty"', opf_text)
            self.assertNotIn("empty</a>", nav.read_text(encoding="utf-8"))
            self.assertIn(target.name, nav.read_text(encoding="utf-8"))
            self.assertNotIn('id="empty"', ncx.read_text(encoding="utf-8"))
            self.assertIn(target.name, ncx.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
