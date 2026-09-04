#!/usr/bin/env python3
"""Publish changed cache files to EPUB/ and OneDrive (incremental).

Workflow:
  1. ./tools/pull.ps1           -- extract changed OneDrive EPUBs to cache + update manifest
  2. (agent modifies cache)
  3. python tools/publish.py     -- detect changes, sync EPUB/, package, upload

Only books with changed files (vs the manifest) are processed, and only the
changed files are written into EPUB/; a full directory rebuild happens only
with --force. OneDrive upload granularity is one .epub per changed book.
Books removed entirely from the cache (e.g. the S5 omnibus volumes after
being split into individual works) are retired instead of re-packaged:
their EPUB/ directory, OneDrive .epub and pull-state record are deleted,
and the manifest baseline drops the book on success.

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
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
from manifest import scan_cache, load_manifest, save_manifest  # noqa: E402
from package_cache_epubs import package_book, PackageError  # noqa: E402
from sync_core import (  # noqa: E402
    ONEDRIVE_DEFAULTS,
    STATUS_LABELS,
    UNIX_TO_DOTNET_TICKS_OFFSET,
    detect_changes,
    remove_pull_state_record,
    sync_file_changes,
    update_manifest_for_book,
    update_pull_state_record,
)

REPO_ROOT = TOOLS_DIR.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "epub-work"
DEFAULT_EPUB = REPO_ROOT / "EPUB"

SIDE_MAP = {
    "chinese": "chinese-text",
    "japanese": "japanese-text",
}


def alignment_preflight(cache_root: Path) -> bool:
    """Run the strict alignment audit before mutating EPUB/ or OneDrive."""
    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS_DIR / "check_alignment.py"),
            "--cache",
            str(cache_root),
            "--strict",
        ],
        check=False,
    )
    return result.returncode == 0


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

    return sync_file_changes(
        cache_root / book_key,
        epub_root / book,
        file_changes,
        full_mirror=full_mirror,
    )


def retire_removed_book(
    book_key: str,
    cache_root: Path,
    epub_root: Path,
    onedrive_dirs: dict[str, Path | None],
    no_upload: bool = False,
    sync_only: bool = False,
) -> tuple[bool, str]:
    """清理一本已从缓存整体移除的书（拆分、改名等场景）。

    不再打包：缓存目录已不存在，打包必然失败。清理动作：
    - 中文侧删除 EPUB/ 下的归档目录（删除传播）；
    - OneDrive 上旧 `<书名>.epub` 一并删除（不再期望以该书形式分发，
      如 S5 外典合订卷已拆分为独立作品）；
    - pull-state 记录同步移除。
    成功返回后，清单基线随 update_manifest_for_book 自动清掉该书记录，
    变更列表不再反复出现。
    """
    side, book = book_key.split("/", 1)
    removed: list[str] = []

    epub_book_dir = epub_root / book
    if epub_book_dir.is_dir():
        shutil.rmtree(epub_book_dir)
        removed.append(f"EPUB/{book}")

    if not sync_only and not no_upload:
        onedrive_dir = onedrive_dirs.get(side)
        if onedrive_dir is None:
            return False, "未配置 OneDrive 目录；若只需本地同步请显式使用 --no-upload"
        if not onedrive_dir.is_dir():
            return False, f"OneDrive 目录不存在: {onedrive_dir}"
        dest = onedrive_dir / f"{book}.epub"
        if dest.is_file():
            dest.unlink()
            removed.append(f"OneDrive:{dest.name}")

    if remove_pull_state_record(cache_root, book_key):
        removed.append("pull-state")

    detail = "、".join(removed) if removed else "无残留产物"
    print(f"  [清理] {book}: {detail}")
    return True, ""


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
    if not book_dir.is_dir():
        # 整本书已从缓存移除（全部文件为 deleted）：走清理路径而非打包。
        return retire_removed_book(
            book_key,
            cache_root,
            epub_root,
            onedrive_dirs,
            no_upload=no_upload,
            sync_only=sync_only,
        )
    packed_epub = cache_root / "packed-epubs" / side / f"{book}.epub"

    if not sync_only and not no_upload:
        onedrive_dir = onedrive_dirs.get(side)
        if onedrive_dir is None:
            return False, "未配置 OneDrive 目录；若只需本地同步请显式使用 --no-upload"
        if not onedrive_dir.is_dir():
            return False, f"OneDrive 目录不存在: {onedrive_dir}"

    # 1. Package first, so a packaging error cannot leave EPUB/ half-updated
    if not sync_only:
        try:
            size = package_book(book_dir, packed_epub)
        except (OSError, PackageError) as exc:
            return False, f"打包失败 {book_key}: {exc}"
        print(f"  [打包] {side}/{book}.epub ({size:,} bytes)")

    # 2. Sync only changed files to EPUB/ (Chinese only)
    if side == "chinese-text":
        try:
            copied, deleted = sync_book_changes(
                book_key, file_changes, cache_root, epub_root, full_mirror
            )
        except OSError as exc:
            return False, f"同步 EPUB/ 失败 {book_key}: {exc}"
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
        if onedrive_dir:
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

    return True, ""


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

    print("\n== 发布前严格对齐检查 ==")
    if not alignment_preflight(cache):
        print(
            "错误: 对齐检查未通过，已停止发布；请修复 alignment-check.tsv 中的问题。",
            file=sys.stderr,
        )
        return 1

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
    print("\n== 完成 ==")
    print(f"  成功: {len(successful)} 本")
    if failed:
        print(f"  失败: {len(failed)} 本")
        for book_key, msg in failed:
            print(f"    {book_key}: {msg}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
