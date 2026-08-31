#!/usr/bin/env python3
"""Shared Note parsing and reading-order rules for Note maintenance CLIs."""
from __future__ import annotations

import os
import re
from collections import OrderedDict
from pathlib import Path

from epub_ids import content_sequence


NOTEFILE_RE = re.compile(r"^(.*)-Note\.xhtml$")
LI_FULL_RE = re.compile(r"<li\b[^>]*>.*?</li>", re.S)
LI_ID_RE = re.compile(r"(<li\b[^>]*?\bid\s*=\s*['\"])([Nn]ote[^'\"]+)(['\"])")
ANCHOR_RE = re.compile(r"<a\b[^>]*>", re.I)
NOTEREF_RE = re.compile(r"\bepub:type\s*=\s*(['\"])noteref\1", re.I)
HREF_NOTE_RE = re.compile(
    r"\bhref\s*=\s*(['\"])([^'\"]*#([Nn]ote[^'\"]+))\1", re.I
)


def read_text(path: str | os.PathLike[str]) -> str:
    return Path(path).read_text(encoding="utf-8-sig")


def parse_note_entries(content: str) -> list[tuple[str, str]]:
    """Return ``(id, full_li_html)`` entries in their current file order."""
    entries: list[tuple[str, str]] = []
    for match in LI_FULL_RE.finditer(content):
        li = match.group(0)
        id_match = LI_ID_RE.search(li)
        if id_match:
            entries.append((id_match.group(2), li))
    return entries


def parse_note_ids(content: str) -> list[str]:
    return [note_id for note_id, _ in parse_note_entries(content)]


def book_order_key(filename: str, note_basename: str) -> tuple[int, int, str]:
    """Sort by the stable header sequence, never by a semantic ChapterN suffix."""
    if filename == note_basename:
        return (2, 0, filename)
    sequence = content_sequence(filename)
    if sequence is not None:
        return (0, sequence, filename)
    return (1, 0, filename)


def gather_refs(
    text_dir: str | os.PathLike[str], note_basename: str
) -> tuple[OrderedDict, OrderedDict]:
    """Collect every note reference and the first occurrence in reading order."""
    root = Path(text_dir)
    files = sorted(
        (path for path in root.iterdir() if path.suffix.casefold() == ".xhtml"),
        key=lambda path: book_order_key(path.name, note_basename),
    )
    appearance: OrderedDict[str, tuple[str, int, int]] = OrderedDict()
    all_refs: OrderedDict[str, list[tuple[str, int]]] = OrderedDict()
    for order_index, path in enumerate(files):
        if path.name == note_basename:
            continue
        try:
            lines = read_text(path).splitlines()
        except (OSError, UnicodeError):
            continue
        for line_number, line in enumerate(lines, 1):
            for anchor_match in ANCHOR_RE.finditer(line):
                tag = anchor_match.group(0)
                if not NOTEREF_RE.search(tag):
                    continue
                href_match = HREF_NOTE_RE.search(tag)
                if not href_match:
                    continue
                note_id = href_match.group(3)
                all_refs.setdefault(note_id, []).append((path.name, line_number))
                appearance.setdefault(note_id, (path.name, line_number, order_index))
    return appearance, all_refs
