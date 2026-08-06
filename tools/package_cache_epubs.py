#!/usr/bin/env python3
"""Package extracted EPUB directories from the local audit cache."""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "epub-work"
SOURCE_DIRECTORIES = {
    "japanese": "japanese-text",
    "chinese": "chinese-text",
}
EPUB_MIMETYPE = b"application/epub+zip"


class PackageError(RuntimeError):
    pass


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_book(book: Path) -> None:
    mimetype = book / "mimetype"
    container = book / "META-INF" / "container.xml"
    if not mimetype.is_file():
        raise PackageError("missing root mimetype file")
    if mimetype.read_bytes() != EPUB_MIMETYPE:
        raise PackageError("mimetype must contain exactly application/epub+zip")
    if not container.is_file():
        raise PackageError("missing META-INF/container.xml")


def package_book(book: Path, destination: Path) -> int:
    validate_book(book)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")

    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            archive.write(book / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
            files = sorted(
                (path for path in book.rglob("*") if path.is_file() and path.name != "mimetype"),
                key=lambda path: path.relative_to(book).as_posix().casefold(),
            )
            for path in files:
                archive.write(
                    path,
                    path.relative_to(book).as_posix(),
                    compress_type=zipfile.ZIP_DEFLATED,
                )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    return destination.stat().st_size


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package extracted EPUB book directories.",
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="audit cache root")
    parser.add_argument(
        "--source",
        type=Path,
        help="direct root containing extracted EPUB book directories",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="output root (default: <cache>/packed-epubs)",
    )
    parser.add_argument(
        "--side",
        choices=("all", "japanese", "chinese"),
        default="all",
        help="which cache side to package",
    )
    parser.add_argument(
        "--pattern",
        default="*",
        help="case-insensitive glob matched against each book directory name",
    )
    parser.add_argument("--dry-run", action="store_true", help="list outputs without writing files")
    args = parser.parse_args()
    if args.source is not None and args.output is None:
        parser.error("--output is required when --source is used")
    if args.source is not None and args.side != "all":
        parser.error("--side cannot be combined with --source")
    return args


def main() -> int:
    args = parse_args()
    cache = args.cache.resolve()
    if args.source is not None:
        output = args.output.resolve()
        selected: list[tuple[str | None, Path]] = [(None, args.source.resolve())]
    else:
        output = (args.output or cache / "packed-epubs").resolve()
        directories = (
            SOURCE_DIRECTORIES
            if args.side == "all"
            else {args.side: SOURCE_DIRECTORIES[args.side]}
        )
        selected = [(directory, cache / directory) for directory in directories.values()]

    for _, source in selected:
        if is_within(output, source):
            print(f"error: output directory cannot be inside {source}", file=sys.stderr)
            return 2

    packaged = 0
    failed = 0
    total_bytes = 0
    pattern = args.pattern.casefold()

    for output_directory, source in selected:
        if not source.is_dir():
            print(f"error: source not found: {source}", file=sys.stderr)
            failed += 1
            continue

        destination_root = output if output_directory is None else output / output_directory
        books = sorted(
            (
                path
                for path in source.iterdir()
                if path.is_dir() and not path.name.startswith(".extract-") and fnmatch.fnmatch(path.name.casefold(), pattern)
            ),
            key=lambda path: path.name.casefold(),
        )
        for book in books:
            destination = destination_root / f"{book.name}.epub"
            if args.dry_run:
                print(f"[dry-run] {book} -> {destination}")
                packaged += 1
                continue
            try:
                size = package_book(book, destination)
            except (OSError, PackageError, zipfile.BadZipFile) as exc:
                print(f"failed: {book.name}: {exc}", file=sys.stderr)
                failed += 1
                continue
            packaged += 1
            total_bytes += size
            print(f"packed: {destination} ({size:,} bytes)")

    if packaged == 0 and failed == 0:
        print(f"no book directories matched pattern: {args.pattern}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"dry run complete: {packaged} book(s), {failed} failure(s)")
    else:
        print(f"complete: {packaged} EPUB(s), {failed} failure(s), {total_bytes:,} bytes")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
