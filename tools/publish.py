#!/usr/bin/env python3
"""Publish changed cache files to EPUB/ and OneDrive (incremental).

Workflow:
  1. ./tools/pull.ps1           -- extract changed OneDrive EPUBs to cache + update manifest
  2. (agent modifies cache)
  3. python tools/publish.py     -- detect changes, sync EPUB/, package, upload

Only books with changed files (vs the manifest) are processed, and only the
changed files are written into EPUB/; a full directory rebuild happens only
with --force. OneDrive upload granularity is one .epub per changed book.

Usage:
    python tools/publish.py --dry-run
    python tools/publish.py
    python tools/publish.py --side chinese --pattern "*S1_01*"
    python tools/publish.py --force          # treat all files as changed (full rebuild)
    python tools/publish.py --no-upload      # skip OneDrive upload
    python tools/publish.py --sync-only      # only sync changed files to EPUB/, no packaging/upload
    python tools/publish.py --only-books "chinese-text/[S1_01]..."  # restrict to these books
"""

from __future__ import annotations

import argparse
import fnmatch
import shutil
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
from manifest import scan_cache, load_manifest, save_manifest
from package_cache_epubs import package_book, PackageError

REPO_ROOT = TOOLS_DIR.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "epub-work"
DEFAULT_EPUB = REPO_ROOT / "EPUB"

SIDE_MAP = {
    "chinese": "chinese-text",
    "japanese": "japanese-text",
}
ONEDRIVE_DEFAULTS = {
    "chinese-text": Path.home() / "OneDrive" / "某系列" / "X系列" / "EPUB",
    "japanese-text": Path.home() / "OneDrive" / "某系列" / "日文原文",
}

STATUS_LABELS = {"added": "新增", "modified": "修改", "deleted": "删除"}

# pull.ps1 records OneDrive epub state (mtime/size) in this file so it can
# skip books that did not change. publish.py keeps the record in sync after
# uploading, otherwise the next pull would re-extract the just-published book.
PULL_STATE_FILENAME = "pull-state.tsv"
# .NET DateTime.Ticks are 100ns units since 0001-01-01; stat().st_mtime_ns is
# nanoseconds since 1970-01-01.
UNIX_TO_DOTNET_TICKS_OFFSET = 621355968000000000


def update_pull_state_record(
    cache_root: Path, book_key: str, mtime_ticks: int, size: int
) -> None:
    """Record one book's OneDrive epub state for pull.ps1 incremental skip."""
    state_path = cache_root / PULL_STATE_FILENAME
    records: dict[str, str] = {}
    if state_path.is_file():
        for line in state_path.read_text(encoding="utf-8-sig").splitlines():
            parts = line.split("\t")
            if len(parts) == 4:
                records[f"{parts[0]}\t{parts[1]}"] = f"{parts[2]}\t{parts[3]}"
    records[book_key.replace("/", "\t", 1)] = f"{mtime_ticks}\t{size}"
    state_path.write_text(
        "".join(f"{key}\t{value}\n" for key, value in sorted(records.items())),
        encoding="utf-8",
    )


def parse_book_path(rel_path: str) -> tuple[str, str, str] | None:
    """Split 'chinese-text/[book]/path/to/file' into (side, book, file_in_book)."""
    parts = rel_path.split("/", 2)
    if len(parts) < 3:
        return None
    return parts[0], parts[1], parts[2]


def detect_changes(
    current: dict[str, str], baseline: dict[str, str]
) -> dict[str, dict[str, str]]:
    """Return {book_key: {file_in_book: status}} for all changed files."""
    changes: dict[str, dict[str, str]] = {}

    for path, hash_val in current.items():
        parsed = parse_book_path(path)
        if parsed is None:
            continue
        side, book, file_in_book = parsed
        book_key = f"{side}/{book}"

        if path not in baseline:
            status = "added"
        elif baseline[path] != hash_val:
            status = "modified"
        else:
            continue

        changes.setdefault(book_key, {})[file_in_book] = status

    for path in baseline:
        if path in current:
            continue
        parsed = parse_book_path(path)
        if parsed is None:
            continue
        side, book, file_in_book = parsed
        book_key = f"{side}/{book}"
        changes.setdefault(book_key, {})[file_in_book] = "deleted"

    return changes


def sync_book_changes(
    book_key: str,
    file_changes: dict[str, str],
    cache_root: Path,
    epub_root: Path,
    full_mirror: bool = False,
) -> tuple[int, int]:
    """Write only changed files of one Chinese cache book into EPUB/.

    Incremental mode touches exactly the files listed in file_changes:
    added/modified are copied, deleted are removed, emptied directories are
    pruned. Files that did not change are never rewritten.
    Full mirror mode (--force) rebuilds the whole book directory from cache.
    Returns (files_copied, files_deleted).
    """
    side, book = book_key.split("/", 1)
    if side != "chinese-text":
        return 0, 0

    book_dir = cache_root / book_key
    epub_book_dir = epub_root / book

    if full_mirror:
        if epub_book_dir.is_dir():
            shutil.rmtree(epub_book_dir)
        copied = 0
        for src in book_dir.rglob("*"):
            if not src.is_file() or ".extract-" in src.name:
                continue
            rel = src.relative_to(book_dir)
            dest = epub_book_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
        return copied, 0

    copied = 0
    deleted = 0
    for file_in_book, status in file_changes.items():
        rel = Path(file_in_book)
        dest = epub_book_dir / rel
        if status == "deleted":
            if dest.is_file():
                dest.unlink()
                deleted += 1
            parent = dest.parent
            while (
                parent != epub_book_dir
                and parent.is_dir()
                and not any(parent.iterdir())
            ):
                parent.rmdir()
                parent = parent.parent
            continue
        src = book_dir / rel
        if not src.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    return copied, deleted


def publish_book(
    book_key: str,
    file_changes: dict[str, str],
    cache_root: Path,
    epub_root: Path,
    onedrive_dirs: dict[str, Path | None],
    no_upload: bool = False,
    sync_only: bool = False,
    full_mirror: bool = False,
) -> tuple[bool, str]:
    """Publish a single changed book. Returns (success, error_message)."""
    side, book = book_key.split("/", 1)
    book_dir = cache_root / book_key
    packed_epub = cache_root / "packed-epubs" / side / f"{book}.epub"

    # 1. Package first, so a packaging error cannot leave EPUB/ half-updated
    if not sync_only:
        try:
            size = package_book(book_dir, packed_epub)
        except (OSError, PackageError) as exc:
            return False, f"打包失败 {book_key}: {exc}"
        print(f"  [打包] {side}/{book}.epub ({size:,} bytes)")

    # 2. Sync only changed files to EPUB/ (Chinese only)
    if side == "chinese-text":
        copied, deleted = sync_book_changes(
            book_key, file_changes, cache_root, epub_root, full_mirror
        )
        if full_mirror:
            print(f"  [EPUB/] {book}: 已全量重建 {copied} 个文件")
        elif copied or deleted:
            parts = [f"写入 {copied} 个文件"]
            if deleted:
                parts.append(f"删除 {deleted} 个文件")
            print(f"  [EPUB/] {book}: " + "，".join(parts))

    if sync_only:
        return True, ""

    # 3. Upload to OneDrive
    if not no_upload:
        onedrive_dir = onedrive_dirs.get(side)
        if onedrive_dir and onedrive_dir.is_dir():
            dest = onedrive_dir / f"{book}.epub"
            shutil.copy2(packed_epub, dest)
            st = dest.stat()
            update_pull_state_record(
                cache_root,
                book_key,
                st.st_mtime_ns // 100 + UNIX_TO_DOTNET_TICKS_OFFSET,
                st.st_size,
            )
            print(f"  [上传] -> {dest}")
        elif onedrive_dir:
            print(f"  [跳过上传] OneDrive 目录不存在: {onedrive_dir}")
        else:
            print("  [跳过上传] 未配置 OneDrive 目录")

    return True, ""


def update_manifest_for_book(
    manifest: dict[str, str], book_key: str, current: dict[str, str]
) -> None:
    """Replace manifest entries for one book with current cache state."""
    prefix = book_key + "/"
    for path in list(manifest.keys()):
        if path.startswith(prefix):
            del manifest[path]
    for path, hash_val in current.items():
        if path.startswith(prefix):
            manifest[path] = hash_val


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish changed cache files to EPUB/ and OneDrive.",
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--epub", type=Path, default=DEFAULT_EPUB)
    parser.add_argument(
        "--side", choices=("all", "chinese", "japanese"), default="all"
    )
    parser.add_argument(
        "--pattern", default="*", help="filter book names (case-insensitive glob)"
    )
    parser.add_argument("--dry-run", action="store_true", help="preview without writing")
    parser.add_argument(
        "--force", action="store_true", help="treat all files as changed"
    )
    parser.add_argument(
        "--no-upload", action="store_true", help="skip OneDrive upload"
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="only sync changed files into EPUB/ and update the manifest "
        "(no packaging, no upload)",
    )
    parser.add_argument(
        "--only-books",
        default="",
        help="comma-separated 'side/book' keys; only process these books",
    )
    parser.add_argument(
        "--chinese-onedrive",
        type=Path,
        default=ONEDRIVE_DEFAULTS["chinese-text"],
    )
    parser.add_argument(
        "--japanese-onedrive",
        type=Path,
        default=ONEDRIVE_DEFAULTS["japanese-text"],
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cache = args.cache.resolve()
    epub_root = args.epub.resolve()

    if not cache.is_dir():
        print(f"错误: 缓存目录不存在: {cache}", file=sys.stderr)
        return 1
    if not epub_root.is_dir():
        print(f"错误: EPUB 目录不存在: {epub_root}", file=sys.stderr)
        return 1

    onedrive_dirs: dict[str, Path | None] = {
        "chinese-text": args.chinese_onedrive.resolve() if args.chinese_onedrive else None,
        "japanese-text": args.japanese_onedrive.resolve() if args.japanese_onedrive else None,
    }

    # Load manifest (baseline for change detection)
    baseline = load_manifest(cache)
    if baseline is None:
        if args.force:
            print("警告: 未找到清单，--force 模式将处理所有文件。")
            baseline = {}
        else:
            print(
                "错误: 未找到清单。请先运行 pull.ps1，或使用 --force 处理所有文件。",
                file=sys.stderr,
            )
            return 1
    elif args.force:
        print("警告: --force 模式，忽略已有清单，处理所有文件。")
        baseline = {}

    # Scan current cache state
    print("扫描缓存...")
    current = scan_cache(cache)
    print(f"  当前缓存: {len(current)} 个文件")
    print(f"  清单基线: {len(baseline)} 个文件")

    # Detect changes
    changes = detect_changes(current, baseline)

    if not changes:
        print("\n没有检测到变更。")
        return 0

    # Filter by side
    if args.side != "all":
        side_dir = SIDE_MAP[args.side]
        changes = {
            k: v for k, v in changes.items() if k.startswith(side_dir + "/")
        }

    # Filter by pattern (match book name = second path component)
    pattern = args.pattern.casefold()
    changes = {
        k: v
        for k, v in changes.items()
        if fnmatch.fnmatch(k.split("/", 1)[1].casefold(), pattern)
    }

    # Restrict to explicitly listed books (pull.ps1 -SyncToEpub uses this)
    if args.only_books:
        wanted = {item.strip() for item in args.only_books.split(",") if item.strip()}
        changes = {k: v for k, v in changes.items() if k in wanted}
        if not changes:
            print("\n没有检测到变更（--only-books 范围内）。")
            return 0

    if not changes:
        print("\n没有检测到变更（已应用筛选条件）。")
        return 0

    # Print detected changes
    print(f"\n== 检测到 {len(changes)} 本书籍有变更 ==")
    for book_key in sorted(changes.keys()):
        file_changes = changes[book_key]
        side, book = book_key.split("/", 1)
        side_label = "中文" if side == "chinese-text" else "日文"
        print(f"\n  {side_label} {book}:")
        for file_in_book, status in sorted(file_changes.items()):
            print(f"    {STATUS_LABELS[status]}: {file_in_book}")

    if args.dry_run:
        print("\n[dry-run] 未执行任何操作。")
        return 0

    # Publish each changed book
    print("\n== 发布 ==")
    successful: list[str] = []
    failed: list[tuple[str, str]] = []

    for book_key in sorted(changes.keys()):
        success, msg = publish_book(
            book_key,
            changes[book_key],
            cache,
            epub_root,
            onedrive_dirs,
            no_upload=args.no_upload,
            sync_only=args.sync_only,
            full_mirror=args.force,
        )
        if success:
            successful.append(book_key)
        else:
            failed.append((book_key, msg))
            print(f"  [失败] {msg}", file=sys.stderr)

    # Update manifest for successful books only (failed books stay "changed")
    if successful:
        print("\n== 更新清单 ==")
        for book_key in successful:
            update_manifest_for_book(baseline, book_key, current)
        save_manifest(cache, baseline)
        print(f"  已更新 {len(successful)} 本书的清单记录。")

    # Summary
    print(f"\n== 完成 ==")
    print(f"  成功: {len(successful)} 本")
    if failed:
        print(f"  失败: {len(failed)} 本")
        for book_key, msg in failed:
            print(f"    {book_key}: {msg}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
