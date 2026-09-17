#!/usr/bin/env python3
"""Shared parsing rules for index-X book ids, XHTML headers and file roles."""
from __future__ import annotations

import re
from pathlib import Path


S6_DATE = r"S6_\d{2}\.\d{2}\.\d{2}"
NUMBERED_BOOK = r"S\d+_\d+(?:_\d+)?"
BOOK_ID_RE = re.compile(rf"\[({S6_DATE}|{NUMBERED_BOOK})\]", re.I)

# These are explicit historical work-id aliases documented in AGENTS.md. They
# deliberately do not produce a pairing header: a file such as
# S5_02-03_coldgame_p-020.xhtml still needs an explicit content-level mapping.
WORK_ID_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"S5_02-03_coldgame", re.I), "S5_02_03"),
)

HEADER_PATTERNS = (
    re.compile(rf"({S6_DATE}-(?:\d+|[A-Za-z][A-Za-z0-9_.]*))", re.I),
    re.compile(rf"({NUMBERED_BOOK}-\d+)", re.I),
    re.compile(rf"({NUMBERED_BOOK}-[A-Za-z][A-Za-z0-9_.]*)", re.I),
    re.compile(rf"({S6_DATE})", re.I),
)

PACKAGING_SUFFIXES = frozenset({
    "cover", "back_cover", "illustrations", "information",
    "introduction", "note", "special",
})
LIST_PACKAGING_SUFFIXES = frozenset({"information", "introduction", "note", "special"})


def book_id(name: str) -> str | None:
    """Return the complete bracketed work id from a book directory/file name."""
    match = BOOK_ID_RE.search(name)
    return match.group(1).upper() if match else None


def japanese_book_id(chinese_id: str) -> str:
    """Chinese and Japanese sides use the same work id; this is the identity map.

    It used to collapse ``S5_AA_BB`` (Chinese independent work) to ``S5_AA``
    (Japanese collected volume, ``[S5_01]外典書庫(1)``). That intermediate form
    is not what the archive holds: ``tools/split_s5_epubs.py`` splits each
    collected volume into independent works and **names each output with the
    two-part id**, e.g. ``[S5_01_01]とある魔術の禁書目録SS 神裂火織編``. So both
    sides key on the same ``S5_AA_BB``.

    The old collapse did not fail loudly: lookup simply missed, and every caller
    silently treated the book as unpaired — eight S5 works were skipped by the
    pairing checks and by the paired normalization/repair tools. Keep this
    identity; if a real collected-volume directory ever appears, declare it as an
    explicit alias rather than deriving it.
    """
    return chinese_id.upper()


def header_of(name: str) -> str | None:
    """Return a standard stable pairing header; unresolved aliases return None."""
    candidate = re.sub(r"\.(?:xhtml|html)$", "", name, flags=re.I)
    for pattern, _ in WORK_ID_ALIASES:
        if pattern.search(candidate):
            return None
    for pattern in HEADER_PATTERNS:
        match = pattern.search(candidate)
        if match:
            return match.group(1).upper()
    return None


def work_id(name: str) -> str | None:
    """Return the complete work id from a book name or content filename."""
    bracketed = book_id(name)
    if bracketed:
        return bracketed
    for pattern, replacement in WORK_ID_ALIASES:
        if pattern.search(name):
            return replacement
    header = header_of(name)
    if not header:
        return None
    if re.fullmatch(S6_DATE, header, re.I) or re.fullmatch(NUMBERED_BOOK, header, re.I):
        return header.upper()
    return header.rsplit("-", 1)[0].upper()


def header_suffix(header: str | None) -> str | None:
    if not header or "-" not in header:
        return None
    return header.rsplit("-", 1)[1].casefold()


def is_packaging_header(header: str | None) -> bool:
    suffix = header_suffix(header)
    return suffix in PACKAGING_SUFFIXES if suffix else False


def is_list_packaging_path(path: Path) -> bool:
    """Whether a Chinese path may use a UL/OL opener in the L5 slot."""
    if "chinese-text" not in {part.casefold() for part in path.parts}:
        return False
    suffix = header_suffix(header_of(path.name))
    return suffix in LIST_PACKAGING_SUFFIXES if suffix else False


def content_sequence(name: str) -> int | None:
    """Return the numeric alignment sequence, never ChapterN or an S6 date part."""
    header = header_of(name)
    if not header or "-" not in header:
        return None
    suffix = header.rsplit("-", 1)[1]
    return int(suffix) if suffix.isdigit() else None
