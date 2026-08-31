#!/usr/bin/env python3
"""Pure XHTML fixed-line-template normalization shared by all CLIs."""
from __future__ import annotations

import re
from pathlib import Path

from epub_ids import is_list_packaging_path


TAG_RE = re.compile(r"<[^>]*>")
H1_RE = re.compile(r"<h1\b[^>]*>.*?</h1>", re.I | re.S)
H2_RE = re.compile(r"<h2\b[^>]*>.*?</h2>", re.I | re.S)
H_OPEN_RE = re.compile(r"<(h1|h2)\b", re.I)
BODY_RE = re.compile(r"<body\b", re.I)
IMG_ELEM_RE = re.compile(
    r"<p\b[^>]*>\s*<(?:img|image|svg)\b[^>]*/?>\s*</p>|"
    r"<(?:img|image)\b[^>]*/?>|<svg\b.*?</svg>", re.I | re.S)
P_TITLE_RE = re.compile(
    r'^\s*<p\b[^>]*class="[^"]*font-1em(?:10|30)[^"]*"[^>]*>(.*?)</p>\s*$',
    re.I | re.S)
P_SPAN_TITLE_RE = re.compile(
    r'^\s*<p\b[^>]*>\s*<span\b[^>]*class="[^"]*font-1em(?:10|30)[^"]*"[^>]*>'
    r'(.*?)</span>\s*</p>\s*$', re.I | re.S)
DIV_P_TITLE_RE = re.compile(
    r'^\s*<div\b[^>]*class="([^"]*font-1em(?:10|30)[^"]*)"[^>]*>\s*'
    r'<p\b[^>]*>(.*?)</p>\s*</div>\s*$', re.I | re.S)
PLAIN_TITLE_RE = re.compile(
    r'^\s*<p\b[^>]*>\s*[　\s]*(?:あとがき|序章|序|プロローグ|エピローグ|目次|译注)'
    r'[　\s]*</p>\s*$', re.I)
NUM_P_RE = re.compile(r'^\s*<p\b[^>]*>\s*[　\s]*[0-9０-９]+\s*</p>\s*$')
LIST_WRAP_RE = re.compile(r'^\s*<(ul|ol)\b[^>]*>\s*$', re.I)
P_LI_WRAP_RE = re.compile(r'^\s*<p\b[^>]*>\s*(<li\b.*?</li>)\s*</p>\s*$', re.I | re.S)
EMBED_RE = re.compile(
    r'<p\b([^>]*)>(.*?)<h1\b([^>]*)>(.*?)</h1>(.*?)</p>', re.I | re.S)
BR_LINE_RE = re.compile(r"^\s*<br\s*/?>\s*$", re.I)
BARE_DIV_RE = re.compile(r"^\s*</?div\s*>\s*$", re.I)
BARE_DIV_OPEN_RE = re.compile(r"^\s*<div\s*>\s*$", re.I)
BARE_DIV_CLOSE_RE = re.compile(r"^\s*</div\s*>\s*$", re.I)
BODY_CLOSE_RE = re.compile(r"^\s*</body\b", re.I)


def read_lines(path: Path) -> tuple[list[str], bool, bool]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig", errors="ignore")
    return text.splitlines(), bom, "\r\n" in text


def write_lines(path: Path, lines: list[str], bom: bool, crlf: bool) -> None:
    sep = "\r\n" if crlf else "\n"
    out = (sep.join(lines) + sep).encode("utf-8")
    if bom:
        out = b"\xef\xbb\xbf" + out
    path.write_bytes(out)


def strip_tags(line: str) -> str:
    return TAG_RE.sub("", line).strip()


def heading_text(line: str) -> str:
    headings = [strip_tags(match.group(0)) for match in H1_RE.finditer(line)]
    headings.extend(strip_tags(match.group(0)) for match in H2_RE.finditer(line))
    return "".join(headings)


def paragraph_id(attrs: str) -> str:
    match = re.search(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", attrs, re.I)
    return f'id="{match.group(1)}"' if match else ""


def has_body(path: Path) -> bool:
    lines, _, _ = read_lines(path)
    head_end = next((i for i, line in enumerate(lines, 1) if BODY_RE.search(line)), 0)
    return any(
        strip_tags(line)
        for i, line in enumerate(lines, 1)
        if i > head_end and not H_OPEN_RE.search(line)
    )


def _fold_multiline_headings(lines: list[str]) -> list[str]:
    merged: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r"^\s*<(h1|h2)\b", line, re.I)
        if match:
            tag = match.group(1).lower()
            if f"</{tag}>" not in line.lower():
                buf, j = line, i
                while j + 1 < len(lines) and f"</{tag}>" not in buf.lower() and j - i <= 3:
                    j += 1
                    buf += lines[j]
                if f"</{tag}>" in buf.lower():
                    merged.append(buf)
                    i = j + 1
                    continue
        merged.append(line)
        i += 1
    return merged


def rebuild(path: Path, jp_h1: str | None = None) -> tuple[list[str] | None, str]:
    """Return normalized lines without writing, or ``(None, reason)``."""
    lines, _, _ = read_lines(path)
    original_count = len(lines)
    head_end = next((i for i, line in enumerate(lines, 1) if BODY_RE.search(line)), 0)
    if head_end != 3:
        if head_end > 3 and not any(
            re.match(r"^\s*<(?:p|div|ul|ol|h1|h2|table)\b", line, re.I)
            for line in lines[2:head_end]
        ):
            folded = re.sub(r"<br\s*/?>", "", "".join(lines[2:head_end]))
            lines = lines[:2] + [folded] + lines[head_end:]
        else:
            return None, f"头部行数={head_end}≠3"

    lines = _fold_multiline_headings(lines)
    line3 = lines[2]
    line3_new = line3
    h1_from_head: str | None = None

    if H_OPEN_RE.search(line3):
        text3, inner3 = strip_tags(line3), heading_text(line3)
        if inner3 and text3 == inner3 and "<h1" in line3.lower():
            match = H1_RE.search(line3)
            if not match:
                return None, "头部行 h1 无法提取"
            h1_from_head = match.group(0)
            line3_new = line3.replace(match.group(0), "")
        else:
            match = EMBED_RE.search(line3)
            if not match:
                return None, "头部行 h1 无法重建"
            pre, h1_attrs, inner, post = match.group(2), match.group(3), match.group(4), match.group(5)
            attrs = (h1_attrs.strip() or paragraph_id(match.group(1))).strip()
            h1_from_head = f"<h1 {attrs}>{pre}{inner}{post}</h1>" if attrs else f"<h1>{pre}{inner}{post}</h1>"
            line3_new = re.sub(
                r'<div\b[^>]*class="[^"]*start-[35]em[^"]*"[^>]*>.*?</div>',
                "", line3, flags=re.S | re.I)
            line3_new = re.sub(r"<br\s*/?>", "", line3_new, flags=re.I)

    h1_slot: str | None = None
    h2_slot: str | None = None
    images: list[str] = []
    first_body: int | None = None

    for i in range(3, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        if H_OPEN_RE.search(line):
            text, inner = strip_tags(line), heading_text(line)
            if text == inner and text:
                if "<h1" in line.lower() and h1_slot is None:
                    match = H1_RE.search(line)
                    if match:
                        h1_slot = match.group(0)
                        rest = line.replace(match.group(0), "")
                        images.extend(match.group(0) for match in IMG_ELEM_RE.finditer(rest))
                        if TAG_RE.sub("", rest).strip():
                            return None, f"第{i + 1}行 h1 旁有多余文本"
                        continue
                if "<h2" in line.lower() and h2_slot is None:
                    match = H2_RE.search(line)
                    if match:
                        h2_slot = match.group(0)
                        continue
            match = EMBED_RE.search(line)
            if match and h1_slot is None and "</p>" not in match.group(2).lower():
                pre, attrs_raw, inner2, post = match.group(2), match.group(3), match.group(4), match.group(5)
                attrs = (attrs_raw.strip() or paragraph_id(match.group(1))).strip()
                h1_slot = f"<h1 {attrs}>{pre}{inner2}{post}</h1>" if attrs else f"<h1>{pre}{inner2}{post}</h1>"
                continue
            return None, f"第{i + 1}行标题结构异常"

        match = P_TITLE_RE.match(line) or P_SPAN_TITLE_RE.match(line)
        if match and h1_slot is None:
            inner = match.group(1)
            attrs_match = re.match(r"^\s*<p\b([^>]*)>", line, re.I)
            attrs = attrs_match.group(1) if attrs_match else ""
            h1_slot = f"<h1{attrs}>{inner}</h1>"
            continue
        match = DIV_P_TITLE_RE.match(line)
        if match and h1_slot is None:
            h1_slot = f'<h1 class="{match.group(1)}">{match.group(2)}</h1>'
            continue
        if PLAIN_TITLE_RE.match(line) and h1_slot is None:
            h1_slot = re.sub(r"^\s*<p\b([^>]*)>(.*?)</p>\s*$", r"<h1\1>\2</h1>", line)
            continue
        if NUM_P_RE.match(line) and h1_slot is not None and h2_slot is None:
            attrs_match = re.search(r"<p\b([^>]*)>", line, re.I)
            inner = re.sub(r"</?p\b[^>]*>", "", line).strip()
            attrs = attrs_match.group(1).strip() if attrs_match else ""
            h2_slot = f"<h2 {attrs}>{inner}</h2>" if attrs else f"<h2>{inner}</h2>"
            continue
        if IMG_ELEM_RE.search(line) and "gaiji" not in line.lower() and "height-2em" not in line.lower():
            images.extend(match.group(0) for match in IMG_ELEM_RE.finditer(line))
            if TAG_RE.sub("", line).strip():
                return None, f"第{i + 1}行图片行有文字"
            continue
        if LIST_WRAP_RE.match(line) and h2_slot is None and is_list_packaging_path(path):
            h2_slot = line
            continue
        if BR_LINE_RE.match(line):
            continue
        first_body = i
        break

    if first_body is None:
        return None, "无正文"
    if h1_slot is None:
        h1_slot = h1_from_head
    if jp_h1 and h1_slot is None:
        h1_slot = f"<h1>{jp_h1}</h1>"

    new = lines[:2] + [line3_new + "".join(images), h1_slot or "", h2_slot or ""]
    body = lines[first_body:]
    if is_list_packaging_path(path):
        body = [P_LI_WRAP_RE.sub(r"\1", line) for line in body]
    # Preserve classed body wrappers. If their closing tag occupied a source-only
    # line, fold it into </body> so the fixed line model stays valid and stable.
    unclosed_line3_divs = (
        len(re.findall(r"<div\b", line3_new, re.I))
        - len(re.findall(r"</div\s*>", line3_new, re.I))
    )
    if unclosed_line3_divs > 0:
        for i in range(len(body) - 1):
            if BARE_DIV_CLOSE_RE.match(body[i]) and BODY_CLOSE_RE.match(body[i + 1]):
                body[i + 1] = body[i].strip() + body[i + 1].lstrip()
                del body[i]
                break
    elif "chinese-text" in {part.casefold() for part in path.parts}:
        # Chinese layout-only bare wrappers may be removed only as balanced pairs;
        # a lone closing tag can belong to a semantic/classed wrapper in L3.
        bare_opens = sum(bool(BARE_DIV_OPEN_RE.match(line)) for line in body)
        bare_closes = sum(bool(BARE_DIV_CLOSE_RE.match(line)) for line in body)
        if bare_opens and bare_opens == bare_closes:
            body = [line for line in body if not BARE_DIV_RE.match(line)]
    new.extend(body)
    return new, f"{original_count}→{len(new)}行"
