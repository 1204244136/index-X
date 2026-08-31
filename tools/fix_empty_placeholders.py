#!/usr/bin/env python3
"""Remove empty numbered XHTML placeholders and close the filename gap."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from epub_ids import NUMBERED_BOOK, S6_DATE

NAME_RE = re.compile(
    rf"^({S6_DATE}|{NUMBERED_BOOK})-(\d+)(_p-(\d+)|_p-[^.]+)(\.xhtml)$",
    re.I,
)
REFERENCE_SUFFIXES = {".opf", ".ncx", ".xhtml", ".html"}


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


def rewrite_references(book_root: Path, renamed: list[tuple[Path, Path]]) -> set[Path]:
    """Update OPF/NCX/nav/XHTML references without changing encoding or newlines."""
    replacements = [(source.name.encode("ascii"), target.name.encode("ascii"))
                    for source, target in renamed]
    changed: set[Path] = set()
    for candidate in book_root.rglob("*"):
        if not candidate.is_file() or candidate.suffix.casefold() not in REFERENCE_SUFFIXES:
            continue
        raw = candidate.read_bytes()
        updated = raw
        for old, new in replacements:
            updated = updated.replace(old, new)
        if updated != raw:
            candidate.write_bytes(updated)
            changed.add(candidate)
    return changed


def remove_deleted_metadata_references(book_root: Path, deleted_name: str) -> set[Path]:
    """Remove the deleted page's own OPF/spine/NCX/nav entries.

    This runs before later files are renamed into the vacated filename, so the
    old empty-page entry cannot become a duplicate reference to its successor.
    """
    old = re.escape(deleted_name.encode("ascii"))
    changed: set[Path] = set()
    for candidate in book_root.rglob("*"):
        if not candidate.is_file() or candidate.suffix.casefold() not in REFERENCE_SUFFIXES:
            continue
        raw = candidate.read_bytes()
        updated = raw
        if candidate.suffix.casefold() == ".opf":
            item_pattern = re.compile(
                rb"<item\b(?=[^>]*\bhref\s*=\s*['\"][^'\"]*" + old
                + rb"(?:#[^'\"]*)?['\"])[^>]*/?>",
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
            updated = re.sub(
                rb"<navPoint\b[^>]*>(?:(?!<navPoint\b).)*?<content\b[^>]*\bsrc\s*=\s*['\"][^'\"]*"
                + old + rb"(?:#[^'\"]*)?['\"][^>]*/?>(?:(?!<navPoint\b).)*?</navPoint>",
                b"",
                updated,
                flags=re.I | re.S,
            )
        elif candidate.name.casefold() == "nav.xhtml":
            updated = re.sub(
                rb"<li\b[^>]*>(?:(?!<li\b).)*?<a\b[^>]*\bhref\s*=\s*['\"][^'\"]*"
                + old + rb"(?:#[^'\"]*)?['\"][^>]*>.*?</a>\s*</li>",
                b"",
                updated,
                flags=re.I | re.S,
            )
        if updated != raw:
            candidate.write_bytes(updated)
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
    book_root = find_book_root(path)
    referenced_files = remove_deleted_metadata_references(book_root, path.name)
    path.unlink()
    renamed = []
    for sibling in sorted(later, key=lambda p: int(NAME_RE.match(p.name).group(2))):
        target = sibling.with_name(shifted_name(sibling))
        sibling.rename(target)
        renamed.append((sibling, target))
    referenced_files.update(rewrite_references(book_root, renamed))
    return renamed, len(referenced_files)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".cache/epub-work/japanese-text"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    found = candidates(args.cache)
    print(f"空占位候选：{len(found)}")
    for path in found:
        print(path)
    if args.apply:
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
