"""Shared physical-line structure and conservative bilingual pairing."""
from __future__ import annotations

import re
from pathlib import Path

from alignment_rules import (MANUAL_ALIGNMENT_HEADERS, NON_PAIR_WORK_IDS,
                             TEXTUAL_IMAGE_HEADERS, PAIR_RULES, pairing_header_of)
from epub_ids import book_id, japanese_book_id, is_packaging_header

BR_ONLY = re.compile(r"^\s*<br\s*/?>\s*$", re.I)
BLANK = re.compile(r"^\s*$")
BODY_RE = re.compile(r"<body\b", re.I)
PB_RE = re.compile(r"\bclass\s*=\s*(['\"])(?:[^'\"]*\s)?pb(?:\s[^'\"]*)?\1")


def body_start(lines: list[str]) -> int:
    return next((i for i, line in enumerate(lines) if BODY_RE.search(line)), 2)


def line_kind(line: str) -> str:
    if BR_ONLY.match(line):
        return "br"
    if BLANK.match(line):
        return "blank"
    if BODY_RE.search(line):
        return "head"
    if re.match(r"^\s*</(?:body|html)\b", line, re.I):
        return "close"
    for tag in ("h1", "h2"):
        if re.search(rf"<{tag}\b", line, re.I):
            return tag
    if re.search(r"<(?:img|svg)\b|data-image-continuation=", line, re.I) and not re.search(
            r"gaiji|height-2em", line, re.I):
        return "img"
    for tag in ("div", "ul", "ol", "li", "p", "hr", "table", "blockquote"):
        if re.match(rf"^\s*</?{tag}\b", line, re.I):
            return tag
    return "other"


def pair_structure_problems(japanese: list[str], chinese: list[str]) -> list[str]:
    if len(japanese) != len(chinese):
        return [f"行数不同：JP {len(japanese)} / CN {len(chinese)}"]
    return [f"L{i} 行类型错位：JP {line_kind(j)} / CN {line_kind(c)}"
            for i, (j, c) in enumerate(zip(japanese, chinese), 1)
            if line_kind(j) != line_kind(c)]


def header_index(directory: Path, *, include_packaging: bool = False) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in sorted(directory.rglob("*.xhtml")):
        header = pairing_header_of(path.name)
        if path.name.casefold() == "nav.xhtml" or not header or (is_packaging_header(header) and not include_packaging):
            continue
        if header in index:
            raise ValueError(f"同侧重复表头 {header}：{index[header]} / {path}")
        index[header] = path
    return index


def books_by_id(base: Path, work_ids: set[str] | None = None) -> dict[str, Path]:
    books = {}
    for directory in sorted(base.iterdir()):
        wid = book_id(directory.name) if directory.is_dir() else None
        if not wid:
            continue
        if work_ids is not None and wid not in work_ids:
            continue
        if wid in books:
            raise ValueError(f"同侧重复作品号 {wid}：{books[wid]} / {directory}")
        books[wid] = directory
    return books


def iter_content_pairs(root: Path, jp_root: Path, only_book: str | None = None,
                       *, require_reference: bool = False):
    """Yield reviewed pairs; repair callers require every selected source unit.

    The complete scope is checked before yielding so an unavailable reference
    cannot leave an earlier Chinese file partially repaired.
    """
    selected = {only_book.upper()} if only_book else None
    cn_books = books_by_id(root, selected)
    jp_ids = {japanese_book_id(wid) for wid in selected} if selected else None
    jp_books = books_by_id(jp_root, jp_ids)
    if require_reference and not cn_books:
        raise ValueError("没有匹配的中文作品；请核对 --root 与 --book")
    pairs = []
    missing = []
    for wid, cn_dir in sorted(cn_books.items(), key=lambda item: item[0] or ""):
        if not wid or wid in NON_PAIR_WORK_IDS or (only_book and wid != only_book.upper()):
            continue
        cn_by = header_index(cn_dir)
        if not cn_by:
            has_packaging = any(
                is_packaging_header(pairing_header_of(path.name))
                for path in cn_dir.rglob("*.xhtml") if path.name.casefold() != "nav.xhtml")
            if not has_packaging:
                missing.append(f"{wid}: 没有可识别的正文文件，未执行配对修复")
            continue
        eligible = {h: p for h, p in cn_by.items()
                    if h not in MANUAL_ALIGNMENT_HEADERS
                    and h not in TEXTUAL_IMAGE_HEADERS and h not in PAIR_RULES}
        jp_dir = jp_books.get(japanese_book_id(wid))
        if jp_dir is None:
            if eligible:
                missing.append(f"{wid}: 缺日文参考作品")
            continue
        jp_by = header_index(jp_dir)
        missing.extend(f"{wid}/{header}: 缺日文参考文件" for header in sorted(eligible.keys() - jp_by.keys()))
        for header in sorted(eligible.keys() & jp_by.keys()):
            if require_reference:
                for side, path in (("中文", cn_by[header]), ("日文", jp_by[header])):
                    try:
                        source = path.read_text(encoding="utf-8-sig")
                    except (OSError, UnicodeError) as exc:
                        missing.append(f"{wid}/{header}: {side}文件无法读取：{exc}")
                    else:
                        if not source.strip():
                            missing.append(f"{wid}/{header}: {side}文件内容为空，未执行配对修复")
            pairs.append((wid, header, jp_by[header], cn_by[header]))
    if require_reference and missing:
        raise ValueError("配对修复未完成：" + "；".join(missing)
                         + "。请补齐 --jp-root 的对应工作源；单侧模板处理请用 normalize_single.py")
    yield from pairs
