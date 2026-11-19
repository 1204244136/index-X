#!/usr/bin/env python3
"""Package extracted EPUB directories from the local audit cache."""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output
from epub_ids import book_id
from epub_structure import XML_SUFFIXES, artifact_contract_issues, container_contract_issues
from path_safety import EXTRACT_DIR_PREFIX


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "epub-work"
SOURCE_DIRECTORIES = {
    "japanese": "japanese-text",
    "chinese": "chinese-text",
}
EPUB_MIMETYPE = b"application/epub+zip"
# 已自带压缩格式的位图资源不再二次 DEFLATE，避免纯烧 CPU 且几乎无压缩收益。
_STORED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"})


class PackageError(RuntimeError):
    pass


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _collect_book_entries(book: Path) -> dict[str, bytes]:
    """收集书目录内条目；仅读取文本类 XML/CSS 与 mimetype，二进制资源只登记键名。"""
    book_root = book.resolve()
    entries: dict[str, bytes] = {}
    stack: list[tuple[Path, str]] = [(book, "")]
    while stack:
        current_dir, rel_prefix = stack.pop()
        with os.scandir(current_dir) as it:
            for entry in it:
                name = entry.name
                if name.casefold().startswith(EXTRACT_DIR_PREFIX):
                    continue
                rel = f"{rel_prefix}{name}"
                is_link = entry.is_symlink()
                is_junction = entry.is_junction() if hasattr(entry, "is_junction") else False
                if entry.is_dir(follow_symlinks=False):
                    if is_link or is_junction:
                        resolved = Path(entry.path).resolve()
                        if not resolved.is_relative_to(book_root):
                            raise PackageError(f"resource escapes book directory: {entry.path}")
                    stack.append((Path(entry.path), f"{rel}/"))
                    continue
                if is_link or is_junction:
                    resolved = Path(entry.path).resolve()
                    if not resolved.is_relative_to(book_root):
                        raise PackageError(f"resource escapes book directory: {entry.path}")
                if not entry.is_file():
                    continue
                lower = name.lower()
                if rel == "mimetype" or lower.endswith(XML_SUFFIXES) or lower.endswith(".css"):
                    entries[rel] = Path(entry.path).read_bytes()
                else:
                    entries[rel] = b""
    return entries


def validate_book(book: Path, *, entries: dict[str, bytes] | None = None) -> None:
    if entries is None:
        mimetype = book / "mimetype"
        container = book / "META-INF" / "container.xml"
        if not mimetype.is_file():
            raise PackageError("missing root mimetype file")
        if mimetype.read_bytes() != EPUB_MIMETYPE:
            raise PackageError("mimetype must contain exactly application/epub+zip")
        if not container.is_file():
            raise PackageError("missing META-INF/container.xml")
        entries = _collect_book_entries(book)
    else:
        if "mimetype" not in entries:
            raise PackageError("missing root mimetype file")
        if entries["mimetype"] != EPUB_MIMETYPE:
            raise PackageError("mimetype must contain exactly application/epub+zip")
        if "META-INF/container.xml" not in entries:
            raise PackageError("missing META-INF/container.xml")
    issues = container_contract_issues(entries) + artifact_contract_issues(entries, book_id(book.name))
    if issues:
        raise PackageError("; ".join(f"{name}: {message}" for name, message in issues[:10]))


def package_book(book: Path, destination: Path) -> int:
    entries = _collect_book_entries(book)
    validate_book(book, entries=entries)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")

    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            archive.write(book / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
            for rel in sorted((name for name in entries if name != "mimetype"), key=str.casefold):
                path = book / rel
                compress = (
                    zipfile.ZIP_STORED
                    if path.suffix.lower() in _STORED_SUFFIXES
                    else zipfile.ZIP_DEFLATED
                )
                archive.write(path, rel, compress_type=compress)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    return destination.stat().st_size


def _package_book_worker(task: tuple[Path, Path]) -> tuple[str, Path, int | None, str | None]:
    book, destination = task
    try:
        return book.name, destination, package_book(book, destination), None
    except (OSError, PackageError, zipfile.BadZipFile) as exc:
        return book.name, destination, None, str(exc)


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
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="并发进程数（0 表示自动，1 表示单进程）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只预览输出，不生成文件")
    args = parser.parse_args()
    if args.jobs < 0:
        parser.error("--jobs 不能为负数")
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
    jobs = args.jobs if args.jobs > 0 else min(os.cpu_count() or 1, 8)

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
                if path.is_dir() and not path.name.startswith(EXTRACT_DIR_PREFIX) and fnmatch.fnmatch(path.name.casefold(), pattern)
            ),
            key=lambda path: path.name.casefold(),
        )
        if args.dry_run:
            for book in books:
                destination = destination_root / f"{book.name}.epub"
                print(f"[预览] {book} -> {destination}")
                packaged += 1
            continue

        tasks = [(book, destination_root / f"{book.name}.epub") for book in books]
        if jobs > 1 and len(tasks) >= 4:
            with ProcessPoolExecutor(max_workers=min(jobs, len(tasks))) as executor:
                results = list(executor.map(_package_book_worker, tasks))
        else:
            results = [_package_book_worker(task) for task in tasks]

        for book_name, destination, size, error in results:
            if error is not None or size is None:
                print(f"[失败] {book_name}：{error}", file=sys.stderr)
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
