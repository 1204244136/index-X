#!/usr/bin/env python3
"""Preview or normalize paired XHTML; the template contract lives in
`docs/epub-structure-spec.md`.

Archive mode writes Chinese files only and reads the Japanese reference as-is.
Explicit --staging may normalize both temporary sides. Every candidate is
planned and validated before writing; ambiguity or a failed contract stops all
writes within the selected scope. Library and single-book roots are accepted;
repeatable --book and --file selectors intersect before checking content.
Use normalize_single.py for a selected file without a paired reference.

    python tools/normalize_paired.py --jp-root 日文参考目录
    python tools/normalize_paired.py --jp-root 日文参考目录 --book S1_01 --apply
    python tools/normalize_paired.py --staging --cache 临时中日目录 --apply
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output
from file_transaction import rollback_paths
from alignment_rules import (JP_H1_BY_HEADER, MANUAL_ALIGNMENT_HEADERS,
                             NON_PAIR_WORK_IDS, PAIR_RULES, TEXTUAL_IMAGE_HEADERS,
                             pairing_header_of, template_exempt)
from check_alignment import check_file
from edit_safety import (EditSafetyError, add_content_roots, add_edit_mode,
                         content_roots, require_edit_target)
from epub_ids import book_id, is_list_packaging_header, japanese_book_id, work_id
from xhtml_structure import books_by_id, header_index
from xhtml_template import has_body, rebuild, write_lines


def selected_books(root: Path, work_ids: set[str] | None = None) -> dict[str, Path]:
    """Accept a library root or one explicitly named book without changing shared discovery."""
    wid = book_id(root.name)
    if wid:
        return {wid: root} if work_ids is None or wid in work_ids else {}
    return books_by_id(root, work_ids)


def selected_files(root: Path, paths: list[Path]) -> dict[str, set[Path]]:
    """Validate explicit Chinese files before discovering or checking other books."""
    selected: dict[str, set[Path]] = {}
    for supplied in paths:
        path = supplied.resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"--file 超出中文 --root：{supplied}")
        if not path.is_file() or path.suffix != ".xhtml":
            raise ValueError(f"--file 必须是存在的中文 XHTML 文件：{supplied}")
        relative = path.relative_to(root)
        wid = book_id(root.name) or (book_id(relative.parts[0]) if len(relative.parts) > 1 else None)
        if (not wid or path.name.casefold() == "nav.xhtml"
                or not pairing_header_of(path.name) or work_id(path.name) != wid):
            raise ValueError(f"--file 不是中文书目录内可识别的 XHTML：{supplied}")
        selected.setdefault(wid, set()).add(path)
    return selected


def selected_header_index(book: Path, headers: set[str] | None = None) -> dict[str, Path]:
    """Ignore unrelated headers while retaining duplicate checks for selected pairs."""
    if headers is None:
        return header_index(book, include_packaging=True)
    index: dict[str, Path] = {}
    for path in sorted(book.rglob("*.xhtml")):
        header = pairing_header_of(path.name)
        if path.name.casefold() == "nav.xhtml" or header not in headers:
            continue
        if header in index:
            raise ValueError(f"同侧重复表头 {header}：{index[header]} / {path}")
        index[header] = path
    return index


def main() -> int:
    configure_output()
    parser = argparse.ArgumentParser(
        description="配对 XHTML 固定模板规范化（默认预览）",
        epilog="--root 与 --jp-root 均可指定库根或单书目录；不加 --book/--file 时处理所给根目录。")
    add_content_roots(parser, paired=True)
    add_edit_mode(parser)
    parser.add_argument("--book", action="append", default=[], metavar="作品号",
                        help="仅处理完整作品号，可重复指定；默认处理根目录内全部书籍")
    parser.add_argument("--file", action="append", type=Path, default=[], metavar="中文XHTML",
                        help="仅处理显式中文 XHTML 路径，可重复；相对当前目录，与 --book 取交集")
    args = parser.parse_args()
    root, jp_root = content_roots(args, parser, paired=True)
    root, jp_root = root.resolve(), jp_root.resolve()
    plans: list[tuple[Path, list[str], bytes, bool, bool]] = []
    skipped: list[str] = []

    def read_source(path: Path) -> tuple[list[str], bytes, bool, bool]:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        return text.splitlines(), raw, raw.startswith(b"\xef\xbb\xbf"), "\r\n" in text

    def validate(path: Path, lines: list[str], wid: str, side: str, header: str) -> None:
        ET.fromstring("\n".join(lines))
        if not template_exempt(wid):
            issues = check_file(lines, allow_list_wrap_slot=side == "cn" and is_list_packaging_header(header))
            if issues:
                raise ValueError(f"{path}: {'; '.join(issues)}")

    def normalized(path: Path, wid: str, side: str, header: str):
        old, raw, bom, crlf = read_source(path)
        new, reason = rebuild(path, JP_H1_BY_HEADER.get(header) if side == "jp" else None, side)
        if new is None:
            raise ValueError(f"{path}: {reason}")
        validate(path, new, wid, side, header)
        return new, old, raw, bom, crlf

    def queue(path: Path, result) -> None:
        new, old, raw, bom, crlf = result
        if new != old:
            plans.append((path, new, raw, bom, crlf))

    try:
        work_ids = {value.strip().upper() for value in args.book} or None
        for wid in work_ids or ():
            if book_id(f"【{wid}】") != wid:
                raise ValueError(f"--book 必须是完整作品号：{wid}")
        files_by_book = selected_files(root, args.file)
        # Verify explicit IDs by directory names, then intersect selectors before
        # duplicate or XHTML checks so excluded books cannot block this batch.
        known_ids = ({book_id(root.name)} if book_id(root.name) else
                     {book_id(path.name) for path in root.iterdir() if path.is_dir()})
        unknown = (work_ids or set()) - known_ids
        if unknown:
            raise ValueError(f"未知中文作品号：{', '.join(sorted(unknown))}")
        scope_ids = work_ids
        if args.file:
            scope_ids = set(files_by_book) if scope_ids is None else scope_ids & files_by_book.keys()
        if scope_ids == set():
            raise ValueError("选择范围为空：--book 与 --file 没有交集")
        cn_books = selected_books(root, scope_ids)
        chosen_ids = set(cn_books)
        scoped = bool(args.book or args.file or book_id(root.name))
        jp_books = selected_books(jp_root, {japanese_book_id(wid) for wid in chosen_ids} if scoped else None)
        file_headers = {wid: {pairing_header_of(path.name) for path in paths}
                        for wid, paths in files_by_book.items()}
        # Check ambiguity inside the selected scope before planning. A duplicate
        # cannot disappear and re-enter through the Chinese-only branch.
        cn_indexes = {wid: selected_header_index(book, file_headers.get(wid))
                      for wid, book in cn_books.items()}
        jp_indexes = {wid: selected_header_index(book, file_headers.get(wid))
                      for wid, book in jp_books.items()}
        for wid, cn_by in sorted(cn_indexes.items()):
            if wid in NON_PAIR_WORK_IDS or japanese_book_id(wid) not in jp_indexes:
                continue
            jp_by = jp_indexes[japanese_book_id(wid)]
            for header, cn_path in sorted(cn_by.items()):
                if args.file and cn_path not in files_by_book[wid]:
                    continue
                if header in MANUAL_ALIGNMENT_HEADERS or header in TEXTUAL_IMAGE_HEADERS or header in PAIR_RULES:
                    skipped.append(f"{header}: 已确认结构特例，保持原样")
                    continue
                if not has_body(cn_path):
                    continue
                chinese = normalized(cn_path, wid, "cn", header)
                jp_path = jp_by.get(header)
                if jp_path is not None and has_body(jp_path):
                    if args.staging:
                        japanese = normalized(jp_path, wid, "jp", header)
                        jp_lines = japanese[0]
                    else:
                        jp_lines = read_source(jp_path)[0]
                        validate(jp_path, jp_lines, wid, "jp", header)
                    if len(jp_lines) != len(chinese[0]):
                        raise ValueError(f"{header}: 行数不对称 JP {len(jp_lines)} / CN {len(chinese[0])}")
                    if args.staging:
                        queue(jp_path, japanese)
                queue(cn_path, chinese)
        if args.apply:
            for path, _, _, _, _ in plans:
                require_edit_target(path, args.staging)
    except (EditSafetyError, ValueError, OSError, UnicodeError, ET.ParseError) as exc:
        print(f"[阻断] 规范化预检失败；没有写入任何文件：{exc}", file=sys.stderr)
        return 1

    print(f"待改写文件：{len(plans)}；结构特例跳过：{len(skipped)}")
    for message in skipped:
        print(f"  跳过 {message}")
    if not args.apply:
        print("预览模式，未写文件；加 --apply 执行。")
        return 0
    try:
        with rollback_paths(path for path, *_ in plans):
            for path, new, _, bom, crlf in plans:
                write_lines(path, new, bom, crlf)
    except OSError as exc:
        print(f"[阻断] 写入失败，已回滚本次文件：{exc}", file=sys.stderr)
        return 1
    print(f"已改写：{len(plans)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
