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
from datetime import datetime
from pathlib import Path

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
            if ".extract-" in path.name:
                continue
            rel = path.relative_to(cache_root).as_posix()
            files[rel] = compute_hash(path)
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
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
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
        for path in book_dir.rglob("*"):
            if not path.is_file():
                continue
            if ".extract-" in path.name:
                continue
            rel = path.relative_to(cache_root).as_posix()
            files[rel] = compute_hash(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate EPUB cache manifest.")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--update-books",
        nargs="*",
        metavar="SIDE/BOOK",
        help="only re-hash these book directories (e.g. chinese-text/[S1_01]...), "
        "preserving all other manifest entries",
    )
    args = parser.parse_args()
    cache = args.cache.resolve()
    if not cache.is_dir():
        print(f"error: cache not found: {cache}", file=argparse.sys.stderr)
        return 1

    if args.update_books:
        files = load_manifest(cache)
        if files is None:
            print(
                "warning: manifest not found, generating a full manifest instead",
                file=argparse.sys.stderr,
            )
            files = scan_cache(cache)
        else:
            update_manifest_books(cache, args.update_books, files)
            print(f"updated {len(args.update_books)} book(s) in existing manifest")
        count, path = save_manifest(cache, files)
    else:
        count, path = save_manifest(cache)
    print(f"manifest: {path} ({count} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
