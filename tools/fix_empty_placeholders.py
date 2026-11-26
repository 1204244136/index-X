#!/usr/bin/env python3
"""Remove empty numbered XHTML placeholders and close the filename gap."""
from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output
from epub_ids import NUMBERED_BOOK, S6_DATE
from epub_structure import METADATA_SUFFIXES, replace_reference_names
from edit_safety import (EditSafetyError, add_content_roots, add_edit_mode,
                         content_roots, require_edit_target)
from file_transaction import atomic_write_bytes, rollback_paths

NAME_RE = re.compile(
    rf"^({S6_DATE}|{NUMBERED_BOOK})-(\d+)(_p-(\d+)|_p-[^.]+)(\.xhtml)$",
    re.I,
)


def is_empty(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "<img" in text or "<svg" in text:
        return False
    body = re.sub(r"<head\b.*?</head>", "", text, flags=re.I | re.S)
    body = re.sub(r"<[^>]+>", "", body)
    return not re.sub(r"\s+", "", body)


def candidates(root: Path) -> list[Path]:
    result = []
    for directory in {p.parent for p in root.rglob("*.xhtml")}:
        numbered = {}
        for path in directory.glob("*.xhtml"):
            match = NAME_RE.match(path.name)
            if match:
                numbered[int(match.group(2))] = path
        for number, path in numbered.items():
            if number - 1 in numbered and number + 1 in numbered and is_empty(path):
                result.append(path)
    return sorted(result)


def shifted_name(path: Path) -> str:
    match = NAME_RE.match(path.name)
    if not match:
        return path.name
    sequence_text = match.group(2)
    sequence = int(sequence_text) - 1
    suffix = match.group(3)
    page = match.group(4)
    if page is not None:
        suffix = f"_p-{int(page) - 1:03d}"
    width = max(2, len(sequence_text))
    return f"{match.group(1)}-{sequence:0{width}d}{suffix}{match.group(5)}"


def find_book_root(path: Path) -> Path:
    for parent in path.parents:
        if (parent / "mimetype").is_file() and (parent / "META-INF" / "container.xml").is_file():
            return parent
    return path.parent


def _remove_innermost_blocks(
    raw: bytes, tag_name: str, anchor_pattern: re.Pattern[bytes]
) -> bytes:
    """删除包含 anchor_pattern 的最小完整闭合 `<tag_name>...</tag_name>` 块，兼容嵌套标签。"""
    tag_re = re.compile(
        rb"<\s*(/?)\s*" + tag_name.encode("ascii") + rb"(?:\s[^>]*)?>",
        re.I,
    )
    stack: list[int] = []
    spans: list[tuple[int, int]] = []
    for match in tag_re.finditer(raw):
        token = match.group(0)
        if match.group(1):
            if stack:
                spans.append((stack.pop(), match.end()))
        elif not token.rstrip().endswith(b"/>"):
            stack.append(match.start())

    to_delete: list[tuple[int, int]] = []
    for anchor in anchor_pattern.finditer(raw):
        pos = anchor.start()
        enclosing = [(s, e) for s, e in spans if s <= pos < e]
        if enclosing:
            best = min(enclosing, key=lambda pair: pair[1] - pair[0])
            to_delete.append(best)

    if not to_delete:
        return raw

    # 按起始位置升序合并，去掉各自独立的最外层被选中区间
    to_delete.sort()
    merged: list[tuple[int, int]] = []
    for s, e in to_delete:
        if merged and s < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    chunks: list[bytes] = []
    cursor = 0
    for s, e in merged:
        # 一并清理同一行上紧跟块后的单个换行与行首缩进（仅当整行只含该块时）
        line_start = raw.rfind(b"\n", cursor, s)
        prefix_start = line_start + 1 if line_start != -1 else cursor
        if prefix_start >= cursor and not raw[prefix_start:s].strip(b" \t"):
            trim_s = prefix_start
        else:
            trim_s = s
        trim_e = e
        if raw[trim_e:trim_e + 2] == b"\r\n":
            trim_e += 2
        elif raw[trim_e:trim_e + 1] in (b"\n", b"\r"):
            trim_e += 1
        chunks.append(raw[cursor:trim_s])
        cursor = trim_e
    chunks.append(raw[cursor:])
    return b"".join(chunks)


def rewrite_references(book_root: Path, renamed: list[tuple[Path, Path]]) -> set[Path]:
    """Update OPF/NCX/nav/XHTML references without changing encoding or newlines."""
    name_map = {source.name: target.name for source, target in renamed}
    changed: set[Path] = set()
    for candidate in book_root.rglob("*"):
        if not candidate.is_file() or candidate.suffix.casefold() not in METADATA_SUFFIXES:
            continue
        raw = candidate.read_bytes()
        updated = replace_reference_names(raw, name_map)
        if updated != raw:
            ET.fromstring(updated)
            atomic_write_bytes(candidate, updated)
            changed.add(candidate)
    return changed


def remove_deleted_metadata_references(book_root: Path, deleted_name: str) -> set[Path]:
    """Remove the deleted page's own OPF/spine/NCX/nav entries.

    This runs before later files are renamed into the vacated filename, so the
    old empty-page entry cannot become a duplicate reference to its successor.
    """
    old = re.escape(deleted_name.encode("utf-8"))
    changed: set[Path] = set()
    for candidate in book_root.rglob("*"):
        if not candidate.is_file() or candidate.suffix.casefold() not in METADATA_SUFFIXES:
            continue
        raw = candidate.read_bytes()
        updated = raw
        if candidate.suffix.casefold() == ".opf":
            item_pattern = re.compile(
                rb"<item\b(?=[^>]*\bhref\s*=\s*['\"](?:[^'\"]*/)?(" + old
                + rb")(?:#[^'\"]*)?['\"])[^>]*/?>",
                re.I,
            )
            item_ids: list[bytes] = []
            for match in item_pattern.finditer(updated):
                id_match = re.search(rb"\bid\s*=\s*['\"]([^'\"]+)['\"]", match.group(0), re.I)
                if id_match:
                    item_ids.append(id_match.group(1))
            updated = item_pattern.sub(b"", updated)
            for item_id in item_ids:
                updated = re.sub(
                    rb"<itemref\b(?=[^>]*\bidref\s*=\s*['\"]"
                    + re.escape(item_id) + rb"['\"])[^>]*/?>",
                    b"",
                    updated,
                    flags=re.I,
                )
        elif candidate.suffix.casefold() == ".ncx":
            content_re = re.compile(
                rb"<content\b[^>]*\bsrc\s*=\s*['\"](?:[^'\"]*/)?" + old
                + rb"(?:#[^'\"]*)?['\"][^>]*/?>",
                re.I,
            )
            updated = _remove_innermost_blocks(updated, "navPoint", content_re)
        elif candidate.name.casefold() == "nav.xhtml":
            href_re = re.compile(
                rb"<a\b[^>]*\bhref\s*=\s*['\"](?:[^'\"]*/)?" + old
                + rb"(?:#[^'\"]*)?['\"][^>]*>",
                re.I,
            )
            updated = _remove_innermost_blocks(updated, "li", href_re)
        if updated != raw:
            ET.fromstring(updated)
            atomic_write_bytes(candidate, updated)
            changed.add(candidate)
    return changed


def apply_candidate(path: Path) -> tuple[list[tuple[Path, Path]], int]:
    match = NAME_RE.match(path.name)
    assert match
    prefix, deleted = match.group(1), int(match.group(2))
    later = []
    for sibling in path.parent.glob(f"{prefix}-*.xhtml"):
        sibling_match = NAME_RE.match(sibling.name)
        if sibling_match and int(sibling_match.group(2)) > deleted:
            later.append(sibling)
    ordered_later = sorted(later, key=lambda p: int(NAME_RE.match(p.name).group(2)))
    rename_plan = [(sibling, sibling.with_name(shifted_name(sibling))) for sibling in ordered_later]
    book_root = find_book_root(path)
    metadata_paths = [
        p for p in book_root.rglob("*")
        if p.is_file() and p.suffix.casefold() in METADATA_SUFFIXES
    ]
    managed_paths = [
        path,
        *[src for src, _ in rename_plan],
        *[dst for _, dst in rename_plan],
        *metadata_paths,
    ]
    with rollback_paths(managed_paths):
        referenced_files = remove_deleted_metadata_references(book_root, path.name)
        path.unlink()
        for sibling, target in rename_plan:
            sibling.rename(target)
        referenced_files.update(rewrite_references(book_root, rename_plan))
    return rename_plan, len(referenced_files)


def main() -> int:
    configure_output()
    parser = argparse.ArgumentParser()
    add_content_roots(parser)
    add_edit_mode(parser)
    args = parser.parse_args()
    root, _ = content_roots(args, parser)
    found = candidates(root)
    print(f"空占位候选：{len(found)}")
    for path in found:
        print(path)
    if args.apply:
        try:
            # Deletion also renames later pages and rewrites metadata throughout
            # the book, so validate every possible destination before any write.
            for book in {find_book_root(path) for path in found}:
                for path in [book, *book.rglob("*")]:
                    require_edit_target(path, args.staging)
        except EditSafetyError as exc:
            parser.error(str(exc))
        # Work from the highest sequence number down in each directory so that
        # renaming a later page cannot invalidate another candidate path.
        ordered = sorted(found, key=lambda path: (str(path.parent), -int(NAME_RE.match(path.name).group(2))))
        for path in ordered:
            print(f"删除：{path}")
            renamed, referenced_files = apply_candidate(path)
            for source, target in renamed:
                print(f"重命名：{source.name} -> {target.name}")
            print(f"更新引用文件：{referenced_files} 个")
        print(f"已处理：{len(found)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
