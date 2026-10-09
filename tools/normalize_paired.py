#!/usr/bin/env python3
"""Preview or normalize paired XHTML; the template contract lives in AGENTS.md.

Archive mode writes Chinese files only and reads the Japanese reference as-is.
Explicit --staging may normalize both temporary sides. Every candidate is
planned and validated before writing; ambiguity or a failed contract stops all
writes. Use normalize_single.py for a selected file without a paired reference.

    python tools/normalize_paired.py --jp-root 日文参考目录
    python tools/normalize_paired.py --jp-root 日文参考目录 --apply
    python tools/normalize_paired.py --staging --cache 临时中日目录 --apply
"""
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

from file_transaction import rollback_paths
from alignment_rules import (JP_H1_BY_HEADER, MANUAL_ALIGNMENT_HEADERS,
                             NON_PAIR_WORK_IDS, PAIR_RULES, TEXTUAL_IMAGE_HEADERS,
                             template_exempt)
from check_alignment import check_file
from edit_safety import (EditSafetyError, add_content_roots, add_edit_mode,
                         content_roots, require_edit_target)
from epub_ids import is_list_packaging_header, japanese_book_id
from xhtml_structure import books_by_id, header_index
from xhtml_template import has_body, rebuild, write_lines


def main() -> int:
    parser = argparse.ArgumentParser(description="配对 XHTML 固定模板规范化（默认预览）")
    add_content_roots(parser, paired=True)
    add_edit_mode(parser)
    args = parser.parse_args()
    root, jp_root = content_roots(args, parser, paired=True)
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
        cn_books, jp_books = books_by_id(root), books_by_id(jp_root)
        # Index every directory before planning. A duplicate cannot disappear
        # from a pair index and later re-enter through the Chinese-only branch.
        cn_indexes = {wid: header_index(book, include_packaging=True) for wid, book in cn_books.items()}
        jp_indexes = {wid: header_index(book, include_packaging=True) for wid, book in jp_books.items()}
        for wid, cn_by in sorted(cn_indexes.items()):
            if wid in NON_PAIR_WORK_IDS or japanese_book_id(wid) not in jp_indexes:
                continue
            jp_by = jp_indexes[japanese_book_id(wid)]
            for header, cn_path in sorted(cn_by.items()):
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
        print(f"[阻断] 规范化预检失败；没有写入任何文件：{exc}")
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
        print(f"[阻断] 写入失败，已回滚本次文件：{exc}")
        return 1
    print(f"已改写：{len(plans)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
