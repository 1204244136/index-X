#!/usr/bin/env python3
"""Generate and load the EPUB cache manifest (SHA-256 file hashes).

Used by pull.ps1 (after extraction) and publish.py (for change detection).
Run directly to (re)generate the manifest:

    python tools/manifest.py
    python tools/manifest.py --cache path/to/cache
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output
from path_safety import is_extract_artifact  # noqa: E402
from file_transaction import atomic_write_bytes  # noqa: E402
from sync_lock import SyncLockBusy, cache_lock  # noqa: E402

REPO_ROOT = TOOLS_DIR.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "epub-work"
MANIFEST_FILENAME = "manifest.json"
SIDE_DIRECTORIES = ("chinese-text", "japanese-text")
_BOOK_KEY_RE = re.compile(r"^(chinese-text|japanese-text)/[^/\\]+$")


def compute_hash(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _has_book_files(directory: Path, extract_root: Path) -> bool:
    if not directory.is_dir() or is_extract_artifact(directory, root=extract_root):
        return False
    for path in directory.rglob("*"):
        if path.is_file() and not is_extract_artifact(path, root=extract_root):
            return True
    return False


def existing_book_keys(
    cache_root: Path, epub_root: Path, candidates: set[str]
) -> set[str]:
    """Return subset of candidate 'side/book' keys present in cache or EPUB/."""
    found: set[str] = set()
    for key in candidates:
        side, _, book = key.partition("/")
        if not book or side not in SIDE_DIRECTORIES:
            continue
        if _has_book_files(cache_root / side / book, cache_root / side):
            found.add(key)
            continue
        if side == "chinese-text" and _has_book_files(epub_root / book, epub_root):
            found.add(key)
    return found


def scan_cache(
    cache_root: Path,
    *,
    sides: tuple[str, ...] | None = None,
    pattern: str = "*",
    only_books: set[str] | None = None,
) -> dict[str, str]:
    """Walk chinese-text/ and japanese-text/, return {posix_rel_path: sha256}."""
    files: dict[str, str] = {}
    target_sides = SIDE_DIRECTORIES if sides is None else sides
    pattern_cf = pattern.casefold()
    for side in target_sides:
        side_root = cache_root / side
        if not side_root.is_dir():
            continue
        for book_dir in side_root.iterdir():
            if not book_dir.is_dir():
                continue
            if is_extract_artifact(book_dir, root=side_root):
                continue
            book_name = book_dir.name
            if only_books is not None and f"{side}/{book_name}" not in only_books:
                continue
            if pattern != "*" and not fnmatch.fnmatch(book_name.casefold(), pattern_cf):
                continue
            for path in book_dir.rglob("*"):
                if not path.is_file():
                    continue
                if is_extract_artifact(path, root=side_root):
                    continue
                rel = path.relative_to(cache_root).as_posix()
                files[rel] = compute_hash(path)
    return files


def scan_epub(
    epub_root: Path,
    *,
    pattern: str = "*",
    only_books: set[str] | None = None,
) -> dict[str, str]:
    """Walk EPUB/ and return {manifest-style key: sha256}.

    EPUB/ stores one directory per (Chinese) book, so every file maps to the
    'chinese-text/<book>/<rel>' key used by manifest.json / publish.py.
    """
    files: dict[str, str] = {}
    pattern_cf = pattern.casefold()
    for book_dir in sorted(p for p in epub_root.iterdir() if p.is_dir()):
        if is_extract_artifact(book_dir, root=epub_root):
            continue
        book_name = book_dir.name
        if only_books is not None and f"chinese-text/{book_name}" not in only_books:
            continue
        if pattern != "*" and not fnmatch.fnmatch(book_name.casefold(), pattern_cf):
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
        if not _BOOK_KEY_RE.fullmatch(key) or key.endswith(("/.", "/..")):
            raise ValueError(f"非法书籍键：{key}")
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
