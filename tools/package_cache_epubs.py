#!/usr/bin/env python3
"""Package extracted EPUB directories from the local audit cache."""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
import zipfile
from pathlib import Path

if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output
from epub_ids import book_id
from epub_structure import artifact_contract_issues, container_contract_issues
from path_safety import is_extract_artifact


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
    entries = {}
    for path in book.rglob("*"):
        if not path.is_file() or is_extract_artifact(path, root=book):
            continue
        if not path.resolve().is_relative_to(book.resolve()):
            raise PackageError(f"resource escapes book directory: {path}")
        entries[path.relative_to(book).as_posix()] = path.read_bytes()
    issues = container_contract_issues(entries) + artifact_contract_issues(entries, book_id(book.name))
    if issues:
        raise PackageError("; ".join(f"{name}: {message}" for name, message in issues[:10]))


def package_book(book: Path, destination: Path) -> int:
    validate_book(book)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")

    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            archive.write(book / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
            files = sorted(
                (path for path in book.rglob("*") if path.is_file()
                 and path != book / "mimetype" and not is_extract_artifact(path, root=book)),
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
        description="将解包书籍目录打包为 EPUB。",
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="参考缓存根目录")
    parser.add_argument(
        "--source",
        type=Path,
        help="直接包含解包书籍目录的源根目录",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="输出根目录（默认 <cache>/packed-epubs）",
    )
    parser.add_argument(
        "--side",
        choices=("all", "japanese", "chinese"),
        default="all",
        help="需要打包的语言侧",
    )
    parser.add_argument(
        "--pattern",
        default="*",
        help="按书目录名筛选（不区分大小写的通配符）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只预览输出，不生成文件")
    args = parser.parse_args()
    if args.source is not None and args.output is None:
        parser.error("使用 --source 时必须指定 --output")
    if args.source is not None and args.side != "all":
        parser.error("--side 不能与 --source 合用")
    return args


def main() -> int:
    configure_output()
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
            print(f"[错误] 输出目录不能位于源目录内：{source}", file=sys.stderr)
            return 2

    packaged = 0
    failed = 0
    total_bytes = 0
    pattern = args.pattern.casefold()

    for output_directory, source in selected:
        if not source.is_dir():
            print(f"[错误] 源目录不存在：{source}", file=sys.stderr)
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
                print(f"[预览] {book} -> {destination}")
                packaged += 1
                continue
            try:
                size = package_book(book, destination)
            except (OSError, PackageError, zipfile.BadZipFile) as exc:
                print(f"[失败] {book.name}：{exc}", file=sys.stderr)
                failed += 1
                continue
            packaged += 1
            total_bytes += size
            print(f"已打包：{destination}（{size:,} 字节）")

    if packaged == 0 and failed == 0:
        print(f"[错误] 没有匹配的书籍目录：{args.pattern}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"预览完成：待打包 {packaged} 本，失败 {failed} 本；未生成 EPUB。")
    else:
        print(f"完成：已打包 {packaged} 本，失败 {failed} 本，共 {total_bytes:,} 字节")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
