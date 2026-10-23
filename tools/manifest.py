#!/usr/bin/env python3
"""Generate and load the EPUB cache manifest (SHA-256 file hashes).

Used by pull.ps1 (after extraction) and publish.py (for change detection).
Run directly to (re)generate the manifest:

    python tools/manifest.py
    python tools/manifest.py --cache path/to/cache
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output
from path_safety import is_extract_artifact
from file_transaction import atomic_write_bytes
from sync_lock import SyncLockBusy, cache_lock

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "epub-work"
MANIFEST_FILENAME = "manifest.json"
SIDE_DIRECTORIES = ("chinese-text", "japanese-text")


def compute_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_cache(cache_root: Path) -> dict[str, str]:
    """Walk chinese-text/ and japanese-text/, return {posix_rel_path: sha256}."""
    files: dict[str, str] = {}
    for side in SIDE_DIRECTORIES:
        side_root = cache_root / side
        if not side_root.is_dir():
            continue
        for path in side_root.rglob("*"):
            if not path.is_file():
                continue
            if is_extract_artifact(path, root=side_root):
                continue
            rel = path.relative_to(cache_root).as_posix()
            files[rel] = compute_hash(path)
    return files


def scan_epub(epub_root: Path) -> dict[str, str]:
    """Walk EPUB/ and return {manifest-style key: sha256}.

    EPUB/ stores one directory per (Chinese) book, so every file maps to the
    'chinese-text/<book>/<rel>' key used by manifest.json / publish.py.
    """
    files: dict[str, str] = {}
    for book_dir in sorted(p for p in epub_root.iterdir() if p.is_dir()):
        if is_extract_artifact(book_dir, root=epub_root):
            continue
        for path in book_dir.rglob("*"):
            if not path.is_file():
                continue
            if is_extract_artifact(path, root=epub_root):
                continue
            rel = path.relative_to(epub_root).as_posix()
            files[f"chinese-text/{rel}"] = compute_hash(path)
    return files


def save_manifest(cache_root: Path, files: dict[str, str] | None = None) -> tuple[int, Path]:
    if files is None:
        files = scan_cache(cache_root)
    manifest = {
        "version": 1,
        "generated_at": datetime.now().isoformat(),
        "files": files,
    }
    manifest_path = cache_root / MANIFEST_FILENAME
    atomic_write_bytes(manifest_path, json.dumps(
        manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    return len(files), manifest_path


def load_manifest(cache_root: Path) -> dict[str, str] | None:
    manifest_path = cache_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return data.get("files", {})


def update_manifest_books(
    cache_root: Path, book_keys: list[str], files: dict[str, str]
) -> None:
    """Re-hash only the given 'side/book' directories in place.

    Entries of those books are removed and rescanned; every other entry is
    left untouched so that unpublished cache edits keep their old baseline.
    """
    for key in book_keys:
        prefix = key.rstrip("/") + "/"
        for path in list(files):
            if path.startswith(prefix):
                del files[path]
        book_dir = cache_root / key
        if not book_dir.is_dir():
            continue
        if is_extract_artifact(book_dir, root=cache_root):
            continue
        for path in book_dir.rglob("*"):
            if not path.is_file():
                continue
            if is_extract_artifact(path, root=cache_root):
                continue
            rel = path.relative_to(cache_root).as_posix()
            files[rel] = compute_hash(path)


def main() -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="生成 EPUB 缓存清单（SHA-256 文件哈希）。")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--update-books",
        nargs="+",
        metavar="SIDE/BOOK",
        help="仅更新指定书籍目录的哈希（如 chinese-text/【S1_01】…），保留其他清单记录",
    )
    args = parser.parse_args()
    cache = args.cache.resolve()
    if not cache.is_dir():
        print(f"[错误] 缓存目录不存在：{cache}", file=sys.stderr)
        return 1

    try:
        with cache_lock(cache):
            if args.update_books:
                files = load_manifest(cache)
                if files is None:
                    print("[警告] 未找到清单，仅为指定书籍建立基线。", file=sys.stderr)
                    files = {}
                update_manifest_books(cache, args.update_books, files)
                print(f"已更新清单中的 {len(args.update_books)} 本书")
                count, path = save_manifest(cache, files)
            else:
                count, path = save_manifest(cache)
    except SyncLockBusy as exc:
        print(f"[阻断] {exc}", file=sys.stderr)
        return 1
    print(f"清单：{path}（{count} 个文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
