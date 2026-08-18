#!/usr/bin/env python3
"""Publish changed EPUB/ files to OneDrive and overwrite them into the cache.

This is the reverse of tools/publish.py (Flow C): you edited files directly
inside EPUB/ and now want to push those edits back out. For each affected
(Chinese) book the tool:

  1. packages the EPUB/ book directory into a .epub (packed-epubs/chinese-text/)
  2. uploads it to OneDrive (某系列\X系列\EPUB) and updates pull-state.tsv so
     the next pull.ps1 run does not re-extract the old file over your edits
  3. incrementally overwrites the changed files into the cache
     (.cache/epub-work/chinese-text/), including deletions

Only books/files that actually changed (vs manifest.json) are touched. EPUB/
only mirrors chinese-text books, so this flow is Chinese-only.

Usage:
    python tools/publish_epub.py --dry-run          # preview
    python tools/publish_epub.py                    # pack + upload + overwrite cache
    python tools/publish_epub.py --pattern "*S1_01*"
    python tools/publish_epub.py --force            # treat all EPUB files as changed (full mirror)
    python tools/publish_epub.py --no-upload        # only overwrite cache + update manifest
    python tools/publish_epub.py --overwrite-cache  # clobber un-published cache edits
    python tools/publish_epub.py --only-books "chinese-text/[S1_01]..."  # restrict books
"""

from __future__ import annotations

import argparse
import fnmatch
import shutil
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
from manifest import compute_hash, load_manifest, save_manifest
from package_cache_epubs import package_book, PackageError
from publish import (
    ONEDRIVE_DEFAULTS,
    STATUS_LABELS,
    UNIX_TO_DOTNET_TICKS_OFFSET,
    detect_changes,
    update_manifest_for_book,
    update_pull_state_record,
)

REPO_ROOT = TOOLS_DIR.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "epub-work"
DEFAULT_EPUB = REPO_ROOT / "EPUB"


def scan_epub(epub_root: Path) -> dict[str, str]:
    """Walk EPUB/ and return {manifest-style key: sha256}.

    EPUB/ stores one directory per (Chinese) book, so every file maps to the
    'chinese-text/<book>/<rel>' key used by manifest.json / publish.py.
    """
    files: dict[str, str] = {}
    for book_dir in sorted(p for p in epub_root.iterdir() if p.is_dir()):
        for path in book_dir.rglob("*"):
            if not path.is_file():
                continue
            if ".extract-" in path.name:
                continue
            rel = path.relative_to(epub_root).as_posix()
            files[f"chinese-text/{rel}"] = compute_hash(path)
    return files


def sync_changes_into_cache(
    book_key: str,
    file_changes: dict[str, str],
    epub_root: Path,
    cache_root: Path,
    full_mirror: bool = False,
) -> tuple[int, int]:
    """Incrementally overwrite one book's changed files from EPUB/ into cache.

    Only the files listed in file_changes are touched: added/modified are
    copied from EPUB/, deleted are removed from the cache, emptied directories
    are pruned. Full mirror mode (--force) rebuilds the whole cache book from
    EPUB/. Returns (files_copied, files_deleted).
    """
    side, book = book_key.split("/", 1)
    epub_book_dir = epub_root / book
    cache_book_dir = cache_root / book_key

    if full_mirror:
        if cache_book_dir.is_dir():
            shutil.rmtree(cache_book_dir)
        copied = 0
        for src in epub_book_dir.rglob("*"):
            if not src.is_file() or ".extract-" in src.name:
                continue
            rel = src.relative_to(epub_book_dir)
            dest = cache_book_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
        return copied, 0

    copied = 0
    deleted = 0
    for file_in_book, status in file_changes.items():
        rel = Path(file_in_book)
        dest = cache_book_dir / rel
        if status == "deleted":
            if dest.is_file():
                dest.unlink()
                deleted += 1
            parent = dest.parent
            while (
                parent != cache_book_dir
                and parent.is_dir()
                and not any(parent.iterdir())
            ):
                parent.rmdir()
                parent = parent.parent
            continue
        src = epub_book_dir / rel
        if not src.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    return copied, deleted


def find_conflicts(
    book_key: str,
    file_changes: dict[str, str],
    cache_root: Path,
    baseline: dict[str, str],
) -> list[str]:
    """List files whose cache copy has un-published edits that this flow would
    overwrite/delete. A file is safe to overwrite only when the cache copy
    still matches the manifest baseline (i.e. it has no un-published edits).
    """
    conflicts: list[str] = []
    for file_in_book, status in file_changes.items():
        cache_file = cache_root / book_key / file_in_book
        if not cache_file.is_file():
            continue
        baseline_hash = baseline.get(f"{book_key}/{file_in_book}")
        if baseline_hash is not None and compute_hash(cache_file) == baseline_hash:
            continue  # cache matches baseline; safe to overwrite/delete
        suffix = "（将删除，缓存含未发布修改）" if status == "deleted" else "（将被覆盖，缓存含未发布修改）"
        conflicts.append(f"{file_in_book} {suffix}")
    return conflicts


def publish_book_reverse(
    book_key: str,
    file_changes: dict[str, str],
    epub_root: Path,
    cache_root: Path,
    onedrive_dir: Path | None,
    no_upload: bool = False,
    full_mirror: bool = False,
) -> tuple[bool, str]:
    """Publish one book whose EPUB/ files changed. Returns (success, error)."""
    side, book = book_key.split("/", 1)
    epub_book_dir = epub_root / book
    packed_epub = cache_root / "packed-epubs" / side / f"{book}.epub"

    # 1. Package first, so a packaging error cannot touch the cache/upload.
    if not epub_book_dir.is_dir():
        if all(status == "deleted" for status in file_changes.values()):
            return False, (
                f"整本已从 EPUB/ 删除，无法自动打包上传 {book_key}；"
                "请手动同步缓存与 OneDrive（或恢复该目录后重跑）。"
            )
        return False, f"EPUB/ 书籍目录不存在: {epub_book_dir}"
    try:
        size = package_book(epub_book_dir, packed_epub)
    except (OSError, PackageError) as exc:
        return False, f"打包失败 {book_key}: {exc}"
    print(f"  [打包] {side}/{book}.epub ({size:,} bytes)")

    # 2. Upload to OneDrive, then keep pull-state in sync so the next
    #    pull.ps1 does not re-extract the old OneDrive file over the cache.
    if not no_upload:
        if onedrive_dir and onedrive_dir.is_dir():
            dest = onedrive_dir / f"{book}.epub"
            try:
                shutil.copy2(packed_epub, dest)
            except OSError as exc:
                return False, f"上传失败 {book_key}: {exc}"
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

    # 3. Overwrite the changed files into the cache (EPUB/ -> cache).
    copied, deleted = sync_changes_into_cache(
        book_key, file_changes, epub_root, cache_root, full_mirror
    )
    if full_mirror:
        print(f"  [缓存] {book}: 已全量重建 {copied} 个文件")
    elif copied or deleted:
        parts = [f"覆盖 {copied} 个文件"]
        if deleted:
            parts.append(f"删除 {deleted} 个文件")
        print(f"  [缓存] {book}: " + "，".join(parts))

    return True, ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish changed EPUB/ files to OneDrive and overwrite them into the cache.",
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--epub", type=Path, default=DEFAULT_EPUB)
    parser.add_argument(
        "--pattern", default="*", help="filter book names (case-insensitive glob)"
    )
    parser.add_argument("--dry-run", action="store_true", help="preview without writing")
    parser.add_argument(
        "--force",
        action="store_true",
        help="treat all EPUB/ files as changed and rebuild affected cache books fully",
    )
    parser.add_argument(
        "--no-upload", action="store_true", help="skip the OneDrive upload"
    )
    parser.add_argument(
        "--overwrite-cache",
        action="store_true",
        help="allow overwriting cache files that have un-published edits",
    )
    parser.add_argument(
        "--only-books",
        default="",
        help="comma-separated 'chinese-text/[book]' keys; only process these books",
    )
    parser.add_argument(
        "--chinese-onedrive",
        type=Path,
        default=ONEDRIVE_DEFAULTS["chinese-text"],
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

    onedrive_dir = args.chinese_onedrive.resolve() if args.chinese_onedrive else None

    # Baseline = manifest.json, which records the last-published cache/EPUB state.
    baseline = load_manifest(cache)
    if baseline is None:
        if args.force:
            print("警告: 未找到清单，--force 模式将把 EPUB/ 全部视为变更。")
            baseline = {}
        else:
            print(
                "错误: 未找到清单。请先运行 pull.ps1 建立基线，或使用 --force。",
                file=sys.stderr,
            )
            return 1
    elif args.force:
        print("警告: --force 模式，忽略已有清单，按整本全量重建缓存。")
        baseline = {}

    # Scan EPUB/ as the current (user-edited) state.
    print("扫描 EPUB/ ...")
    current = scan_epub(epub_root)
    print(f"  EPUB/: {len(current)} 个文件")
    print(f"  清单基线: {len(baseline)} 个文件")

    # Detect changes; EPUB/ only mirrors chinese-text, so drop anything else
    # (e.g. japanese-text entries from the baseline must not be treated as
    # deletions).
    changes = detect_changes(current, baseline)
    changes = {k: v for k, v in changes.items() if k.startswith("chinese-text/")}

    if not changes:
        print("\n没有检测到变更。")
        return 0

    # Filter by pattern (book name = second path component).
    pattern = args.pattern.casefold()
    changes = {
        k: v
        for k, v in changes.items()
        if fnmatch.fnmatch(k.split("/", 1)[1].casefold(), pattern)
    }

    # Restrict to explicitly listed books.
    if args.only_books:
        wanted = {item.strip() for item in args.only_books.split(",") if item.strip()}
        changes = {k: v for k, v in changes.items() if k in wanted}
        if not changes:
            print("\n没有检测到变更（--only-books 范围内）。")
            return 0

    if not changes:
        print("\n没有检测到变更（已应用筛选条件）。")
        return 0

    # Safety: refuse (by default) to overwrite cache files that have their own
    # un-published edits, unless the user explicitly opts in.
    conflicted: dict[str, list[str]] = {}
    if not args.force and not args.overwrite_cache:
        for book_key in sorted(changes):
            conflicts = find_conflicts(book_key, changes[book_key], cache, baseline)
            if conflicts:
                conflicted[book_key] = conflicts
        if conflicted:
            print("\n== 检测到缓存未发布修改（反向覆盖会丢失这些修改）==")
            for book_key, conflicts in conflicted.items():
                print(f"\n  {book_key}:")
                for entry in conflicts:
                    print(f"    {entry}")

    # Print detected changes.
    print(f"\n== 检测到 {len(changes)} 本书籍在 EPUB/ 中有变更 ==")
    for book_key in sorted(changes):
        file_changes = changes[book_key]
        _, book = book_key.split("/", 1)
        print(f"\n  中文 {book}:")
        for file_in_book, status in sorted(file_changes.items()):
            print(f"    {STATUS_LABELS[status]}: {file_in_book}")

    if args.dry_run:
        print("\n[dry-run] 未执行任何操作。")
        return 0

    # Drop conflicting books unless the user opted in to overwrite them.
    if conflicted and not args.overwrite_cache:
        print(
            "\n默认跳过以上冲突书籍。"
            "请先运行 publish.py 提交缓存修改，或使用 --overwrite-cache 强制覆盖。"
        )
        for book_key in conflicted:
            changes.pop(book_key, None)
        if not changes:
            print("\n没有可发布的书籍（全部因冲突被跳过）。")
            return 1

    print("\n== 发布（EPUB/ -> OneDrive + 缓存）==")
    successful: list[str] = []
    failed: list[tuple[str, str]] = []

    for book_key in sorted(changes):
        success, msg = publish_book_reverse(
            book_key,
            changes[book_key],
            epub_root,
            cache,
            onedrive_dir,
            no_upload=args.no_upload,
            full_mirror=args.force,
        )
        if success:
            successful.append(book_key)
        else:
            failed.append((book_key, msg))
            print(f"  [失败] {msg}", file=sys.stderr)

    # Update the manifest only for fully successful books; failed books stay
    # "changed" and are retried on the next run.
    if successful:
        print("\n== 更新清单 ==")
        for book_key in successful:
            update_manifest_for_book(baseline, book_key, current)
        save_manifest(cache, baseline)
        print(f"  已更新 {len(successful)} 本书的清单记录。")

    print("\n== 完成 ==")
    print(f"  成功: {len(successful)} 本")
    if failed:
        print(f"  失败: {len(failed)} 本")
        for book_key, msg in failed:
            print(f"    {book_key}: {msg}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
