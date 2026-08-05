#!/usr/bin/env python3
"""Normalize local EPUB caches without touching the versioned EPUB source."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ID_RE = re.compile(r"(S\d+_\d+-\d+)", re.I)
SECTION_NUMBER_RE = re.compile(r"^<p>\s*[０-９0-9]+\s*</p>$")


def join_text_continuations(lines: list[str]) -> list[str]:
    """Join accidental XHTML line breaks inside book paragraph/inline markup."""
    out: list[str] = []
    code_depth = 0
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("<") and out and code_depth == 0:
            previous = out[-1]
            if "<p" in previous or re.search(r"<(?:rt|a|sup|span|ruby)\b[^>]*>$", previous):
                out[-1] = previous + stripped
                continue
        out.append(line)
        code_depth += len(re.findall(r"<code\b", line, flags=re.I))
        code_depth -= len(re.findall(r"</code\s*>", line, flags=re.I))
        code_depth = max(code_depth, 0)
    return out


def merge_split_div_paragraphs(lines: list[str]) -> list[str]:
    """Merge a div containing one paragraph when its tags were split across lines."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        current = lines[i].strip()
        if re.fullmatch(r"<div\b[^>]*>", current, re.I) and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if re.fullmatch(r"<p>.*</p></div>", next_line, re.I | re.S):
                out.append(current + next_line)
                i += 2
                continue
            if (i + 2 < len(lines)
                    and re.fullmatch(r"<p>.*</p>", next_line, re.I | re.S)
                    and lines[i + 2].strip() == "</div>"):
                out.append(current + next_line + "</div>")
                i += 3
                continue
        out.append(lines[i])
        i += 1
    return out


def collapse_wrapped_h2(lines: list[str]) -> list[str]:
    """Remove redundant start-5em wrappers around standalone section headings."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        current = lines[i].strip()
        if (re.fullmatch(r"(?:<br/>)*<div class=\"start-5em\"><p>", current)
                and i + 2 < len(lines)
                and re.fullmatch(r"<h2\b[^>]*>.*</h2>", lines[i + 1].strip(), re.I)
                and lines[i + 2].strip() == "</p></div><br/>"):
            out.append(lines[i + 1].strip())
            i += 3
            continue
        numeric = re.fullmatch(
            r'<div class="start-5em"><p>\s*([0-9０-９]+)\s*</p></div>',
            current,
            re.I,
        )
        if numeric:
            out.append(f"<h2>{numeric.group(1)}</h2>")
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return out


def collapse_consecutive_breaks(lines: list[str]) -> list[str]:
    """Collapse consecutive break tags, including tags split across lines."""
    text = "\n".join(lines)
    text = re.sub(r"(?:<br/>\s*){2,}", "<br/>", text)
    return text.splitlines()


def split_inline_breaks(lines: list[str]) -> list[str]:
    """Put non-heading ``<br/>`` tags on their own logical line.

    EPUB files commonly glue a break to the following block element (for
    example ``<br/><p>...</p>``).  Keep level-one headings untouched, but
    split boundary breaks and preserve complete paragraph/div elements when a
    break occurs inside one.
    """
    out: list[str] = []
    block_re = re.compile(r"^(?P<open><(?P<tag>p|div)\b[^>]*>)(?P<body>.*?)(?:<br/>)(?P<tail>.*)(?P<close></(?P=tag)>)$", re.I)
    for line in lines:
        stripped = line.strip()
        if "<br/>" not in stripped or "<h1" in stripped.lower() or stripped == "<br/>":
            out.append(line)
            continue
        match = block_re.match(stripped)
        if match:
            before = match.group("body")
            tail = match.group("tail")
            opening = match.group("open")
            closing = match.group("close")
            out.append(opening + before + closing)
            out.append("<br/>")
            if tail:
                out.append(opening + tail + closing)
            continue
        parts = stripped.split("<br/>")
        for index, part in enumerate(parts):
            if part:
                out.append(part)
            if index < len(parts) - 1:
                out.append("<br/>")
    return out


def join_body_main(lines: list[str]) -> list[str]:
    """Keep the main container on the body line when an empty break precedes it."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        current = lines[i]
        if ("<body" in current and current.rstrip().endswith(">")
                and i + 2 < len(lines)
                and lines[i + 1].strip() == "<br/>"
                and lines[i + 2].strip() == '<div class="main">'):
            out.append(current.rstrip() + '<div class="main">')
            out.append(lines[i + 1])
            i += 3
            continue
        out.append(current)
        i += 1
    return out


def normalize_file(path: Path) -> bool:
    raw = path.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n")
    text = raw.replace("?>\n<!DOCTYPE html>", "?>\n<!DOCTYPE html>")
    text = text.replace("?><!DOCTYPE html>", "?>\n<!DOCTYPE html>\n")
    text = text.replace("?><html", "?>\n<html")
    text = text.replace("<!DOCTYPE html><html", "<!DOCTYPE html>\n<html")
    lines = text.splitlines()
    lines = [line for line in lines if line.strip().lower() != "<!doctype html>"]
    xml_index = next((i for i, line in enumerate(lines[:4]) if line.lstrip().startswith("<?xml")), None)
    lines.insert(xml_index + 1 if xml_index is not None else 0, "<!DOCTYPE html>")
    text = "\n".join(lines)
    text = text.replace("</p></div></div></body></html>", "</p>\n</div></div></body></html>")
    text = text.replace("</p></div></body></html>", "</p>\n</div></body></html>")
    if "<svg" in text:
        text = text.replace("</div></body></html>", "</div>\n</body></html>")
    text = text.replace("</div>\n</body></html>", "</div></body></html>")
    lines = [line for line in text.splitlines() if line.strip()]
    joined: list[str] = []
    i = 0
    while i < len(lines):
        if (lines[i].lstrip().startswith("<p><img") and i + 1 < len(lines)
                and lines[i + 1].strip() == "</p>"):
            joined.append(lines[i].rstrip() + "</p>")
            i += 2
            continue
        joined.append(lines[i])
        i += 1
    lines = joined
    lines = join_text_continuations(lines)
    lines = merge_split_div_paragraphs(lines)
    lines = split_inline_breaks(lines)
    lines = join_body_main(lines)
    lines = collapse_wrapped_h2(lines)
    out = []
    html_index = None
    for line in lines:
        if "<html" in line:
            html_index = len(out)
        title_line = "<h1" in line or 'class="start-3em"' in line
        if (title_line and "<html" not in line and html_index is not None
                and all(item.strip() == "<br/>" for item in out[html_index + 1:])):
            out[html_index] += line.strip()
            continue
        out.append(line)
    lines = out
    out = []
    for line in lines:
        if "<h2" in line and not line.strip().startswith("<h2"):
            before, rest = line.split("<h2", 1)
            if before.strip():
                out.append(before.rstrip())
            if "</h2>" in rest:
                heading, after = rest.split("</h2>", 1)
                out.append("<h2" + heading + "</h2>")
                if after.strip():
                    out.append(after.lstrip())
            else:
                out.append("<h2" + rest)
        else:
            out.append(line)
    lines = out
    out = []
    for line in lines:
        if ("<h1" in line or 'id="toc-' in line or 'class="start-3em"' in line) and line.rstrip().endswith("<br/>"):
            out.append(line.rstrip()[:-5].rstrip())
            out.append("<br/>")
        else:
            out.append(line)
    lines = out
    out = []
    standalone_indent = 0
    for line in lines:
        if line.strip() == '<div class="h-indent-1em">':
            standalone_indent += 1
            continue
        if standalone_indent and "</div>" in line:
            line = line.replace("</div>", "", 1)
            standalone_indent -= 1
        out.append(line)
    lines = out
    def is_content_line(line: str) -> bool:
        stripped = line.strip()
        if not stripped or stripped == "<br/>":
            return False
        if SECTION_NUMBER_RE.fullmatch(stripped):
            return False
        if "<h1" in stripped or "<h2" in stripped:
            return False
        if 'id="toc-' in stripped or 'class="start-3em"' in stripped:
            return False
        if stripped == '<div class="main">':
            return False
        if stripped.startswith(("<?xml", "<!DOCTYPE", "<html", "</html", "</body", "</div")):
            return False
        return True

    if len(lines) > 4:
        first_content = next((i for i, line in enumerate(lines[3:], 3) if is_content_line(line)), None)
        while first_content is not None and first_content > 4:
            break_index = next((i for i in range(3, first_content) if lines[i].strip() == "<br/>"), None)
            if break_index is None:
                break
            del lines[break_index]
            first_content -= 1
        while first_content is not None and first_content < 4:
            lines.insert(first_content, "<br/>")
            first_content += 1
        while first_content is not None and first_content > 4:
            break_index = next((i for i in range(3, first_content) if lines[i].strip() == "<br/>"), None)
            if break_index is None:
                break
            del lines[break_index]
            first_content -= 1
    out: list[str] = []
    def is_image_layout(line: str) -> bool:
        if "<svg" in line:
            return True
        if "<img" not in line:
            return False
        residual = re.sub(r"<[^>]+>", "", line).strip()
        return not residual

    for i, line in enumerate(lines):
        if "<svg" in line and "</div></body></html>" in line:
            left, _ = line.split("</div></body></html>", 1)
            out.extend([left + "</div>", "</body></html>"])
            continue
        if "</body></html>" in line and "</div></body></html>" not in line and not line.strip().startswith("</body></html>"):
            left, _ = line.split("</body></html>", 1)
            out.extend([left, "</body></html>"])
            continue
        if "</p><div" in line and "<h1" not in line and "<h2" not in line:
            left, right = line.split("</p><div", 1)
            out.extend([left + "</p>", "<div" + right])
            continue
        if "</p><p>" in line and "<h1" not in line and "<h2" not in line:
            parts = line.split("</p><p>", 1)
            out.extend([parts[0] + "</p>", "<p>" + parts[1]])
            continue
        if line.strip() == "<br/>":
            prev = lines[i - 1] if i else ""
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            prev_is_title = "<h1" in prev or 'id="toc-' in prev or 'class="start-3em"' in prev
            next_is_title = "<h1" in nxt or 'id="toc-' in nxt or 'class="start-3em"' in nxt
            preserve_cross_page_breaks = "s2_19-13" in path.name.lower()
            if not preserve_cross_page_breaks and ((is_image_layout(prev) and not prev_is_title) or is_image_layout(prev) or (is_image_layout(nxt) and not next_is_title) or is_image_layout(nxt)):
                continue
        out.append(line)
    lines = out
    name = path.name.lower()
    afterword = (
        "after_the_afterword" not in name
        and (
            "afterword" in name
            or any(
                ("あとがき" in x or ">后记<" in x)
                and ("<h1" in x or "<h2" in x or "<title" in x)
                for x in lines[:20]
            )
        )
    )
    if afterword:
        lines = collapse_consecutive_breaks(lines)
        lines = [
            line for i, line in enumerate(lines)
            if not (line.strip() == "<br/>" and i + 1 < len(lines)
                    and ("align-end" in lines[i + 1] or 'class="right"' in lines[i + 1]))
        ]
        signature = next(
            (i for i, line in enumerate(lines) if "align-end" in line or 'class="right"' in line),
            None,
        )
        if signature is not None:
            tail = "".join(line.strip() for line in lines[signature:])
            if "</p>" in tail:
                author, endings = tail.split("</p>", 1)
                lines = lines[:signature] + [author + "</p>", endings]
    new = "\n".join(lines) + "\n"
    if new != raw:
        path.write_text(new, encoding="utf-8", newline="")
        return True
    return False


def apply_afterword_breaks(cache: Path) -> int:
    def find(root: Path) -> dict[str, Path]:
        result = {}
        for path in root.rglob("*.xhtml"):
            match = ID_RE.search(path.name)
            if match:
                result.setdefault(match.group(1).upper(), path)
        return result
    jp, cn = find(cache / "japanese-text"), find(cache / "chinese-text")
    changed = 0
    for header in set(jp) & set(cn):
        if "Afterwords" not in jp[header].name and "あとがき" not in jp[header].read_text(encoding="utf-8", errors="ignore")[:1200]:
            continue
        jl = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        cl = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        ji = next((i for i, x in enumerate(jl) if "align-end" in x or 'class="right"' in x), None)
        ci = next((i for i, x in enumerate(cl) if "align-end" in x or 'class="right"' in x), None)
        if ji is None or ci is None or ci < 2 or ji < 1:
            continue
        if cl[ci - 2].strip() == "<br/>" and jl[ji - 2].strip() != "<br/>":
            jl.insert(ji - 1, "<br/>")
            jp[header].write_text("\n".join(jl) + "\n", encoding="utf-8", newline="")
            changed += 1
    return changed


def balance_afterword_breaks(cache: Path) -> int:
    """Align afterword section breaks when they alone explain the pair delta."""
    def find(root: Path) -> dict[str, Path]:
        result = {}
        for path in root.rglob("*.xhtml"):
            match = ID_RE.search(path.name)
            if match:
                result.setdefault(match.group(1).upper(), path)
        return result

    jp, cn = find(cache / "japanese-text"), find(cache / "chinese-text")
    changed = 0
    for header in set(jp) & set(cn):
        if "after_the_afterword" in jp[header].name.lower():
            continue
        if "afterword" not in jp[header].name.lower() and "あとがき" not in jp[header].read_text(encoding="utf-8", errors="ignore")[:1200]:
            continue
        jl = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        cl = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        delta = len(jl) - len(cl)
        jb = [i for i, x in enumerate(jl) if x.strip() == "<br/>"]
        cb = [i for i, x in enumerate(cl) if x.strip() == "<br/>"]
        br_delta = len(jb) - len(cb)
        if delta == 0 or delta != br_delta or abs(delta) > 3:
            continue
        target = jl if delta > 0 else cl
        candidates = [i for i, x in enumerate(target) if x.strip() == "<br/>"]
        for i in reversed(candidates):
            del target[i]
            if len(candidates) - candidates.index(i) == abs(delta):
                path = jp[header] if delta > 0 else cn[header]
                path.write_text("\n".join(target) + "\n", encoding="utf-8", newline="")
                changed += 1
                break
    return changed


def apply_deleted_image_breaks(cache: Path) -> int:
    """Fill Japanese line slots replaced by one image for deleted CN text."""
    def find(root: Path) -> dict[str, Path]:
        result = {}
        for path in root.rglob("*.xhtml"):
            match = ID_RE.search(path.name)
            if match:
                result.setdefault(match.group(1).upper(), path)
        return result

    jp, cn = find(cache / "japanese-text"), find(cache / "chinese-text")
    changed = 0
    for header in set(jp) & set(cn):
        jp_lines = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        cn_lines = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        diff = len(cn_lines) - len(jp_lines)
        if diff <= 0 or not any("<del" in line.lower() for line in cn_lines):
            continue
        image_lines = [
            i for i, line in enumerate(jp_lines)
            if re.fullmatch(r"\s*<p>\s*<img[^>]+>\s*</p>\s*", line, re.I)
        ]
        if not image_lines:
            continue
        for image_index in image_lines:
            if image_index > 12:
                continue
            if not any("<del" in cn_lines[i].lower() for i in range(max(0, image_index - 2), min(len(cn_lines), image_index + 3))):
                continue
            jp_lines[image_index + 1:image_index + 1] = ["<br/>"] * diff
            jp[header].write_text("\n".join(jp_lines) + "\n", encoding="utf-8", newline="")
            changed += 1
            break
    return changed


def apply_gaiji_breaks(cache: Path) -> int:
    """Restore a missing Japanese break after a gaiji-containing paragraph."""
    def find(root: Path) -> dict[str, Path]:
        result = {}
        for path in root.rglob("*.xhtml"):
            match = ID_RE.search(path.name)
            if match:
                result.setdefault(match.group(1).upper(), path)
        return result

    jp, cn = find(cache / "japanese-text"), find(cache / "chinese-text")
    changed = 0
    for header in set(jp) & set(cn):
        jl = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        cl = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        if len(jl) >= len(cl):
            continue
        for i, line in enumerate(jl):
            if "gaiji" not in line.lower() or not line.lstrip().startswith("<p"):
                continue
            if i + 1 < len(jl) and jl[i + 1].strip() == "<br/>":
                continue
            nearby = cl[max(0, i - 2):min(len(cl), i + 4)]
            if "<br/>" not in [x.strip() for x in nearby]:
                continue
            jl.insert(i + 1, "<br/>")
            jp[header].write_text("\n".join(jl) + "\n", encoding="utf-8", newline="")
            changed += 1
            break
    return changed


def apply_direct_image_reorders(cache: Path) -> int:
    """Reorder Chinese image lines when row alignment is otherwise direct.

    A single missing standalone ``<br/>`` is also recoverable when it is the
    only reason later image rows are offset by one. Text lines are kept in
    their original order; only the image insertion slots (and that break) are
    changed.
    """
    def find(root: Path) -> dict[str, Path]:
        result = {}
        for path in root.rglob("*.xhtml"):
            match = ID_RE.search(path.name)
            if match:
                result.setdefault(match.group(1).upper(), path)
        return result

    def rows(lines: list[str]) -> list[int]:
        return [i for i, line in enumerate(lines)
                if re.search(r"<(?:img|svg)\b", line, re.I)
                and 'class="gaiji"' not in line.lower()
                and "height-2em" not in line.lower()]

    def is_layout_image(line: str) -> bool:
        lowered = line.lower()
        return bool(re.search(r"<(?:img|svg)\b", line, re.I)) and 'class="gaiji"' not in lowered and "height-2em" not in lowered

    def standalone_breaks(lines: list[str]) -> list[int]:
        return [i for i, line in enumerate(lines) if line.strip().lower() == "<br/>"]

    jp, cn = find(cache / "japanese-text"), find(cache / "chinese-text")
    changed = 0
    for header in set(jp) & set(cn):
        jl = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        cl = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        jr, cr = rows(jl), rows(cl)
        if not jr or len(jr) != len(cr) or jr == cr:
            continue
        if len(jl) == len(cl):
            working = cl
        elif len(jl) == len(cl) + 1:
            jp_breaks = standalone_breaks(jl)
            cn_breaks = standalone_breaks(cl)
            if len(jp_breaks) != len(cn_breaks) + 1:
                continue
            missing_break = next(
                (
                    jp_breaks[index]
                    for index in range(len(jp_breaks))
                    if jp_breaks[:index]
                    + [row - 1 for row in jp_breaks[index + 1:]]
                    == cn_breaks
                ),
                None,
            )
            if missing_break is None:
                continue
            working = cl.copy()
            working.insert(missing_break, "<br/>")
        else:
            continue
        working_rows = rows(working)
        image_lines = [working[i] for i in working_rows]
        text_lines = [line for line in working if not is_layout_image(line)]
        reordered: list[str] = []
        text_index = image_index = 0
        for japanese_line in jl:
            if is_layout_image(japanese_line):
                reordered.append(image_lines[image_index])
                image_index += 1
            else:
                reordered.append(text_lines[text_index])
                text_index += 1
        if rows(reordered) != jr:
            continue
        cn[header].write_text("\n".join(reordered) + "\n", encoding="utf-8", newline="")
        changed += 1
    return changed


def count_inline_breaks(path: Path) -> int:
    """Count non-heading lines whose ``<br/>`` is not already standalone."""
    return sum(
        line.lower().count("<br/>")
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if "<br/>" in line and "<h1" not in line.lower() and line.strip() != "<br/>"
    )


def balance_split_breaks(cache: Path, before: dict[str, dict[str, int]]) -> int:
    """Remove only breaks that alone account for a split-induced line mismatch."""
    def find(root: Path) -> dict[str, Path]:
        result = {}
        for path in root.rglob("*.xhtml"):
            match = ID_RE.search(path.name)
            if match:
                result.setdefault(match.group(1).upper(), path)
        return result

    jp, cn = find(cache / "japanese-text"), find(cache / "chinese-text")
    changed = 0
    for header in set(jp) & set(cn):
        jp_extra = before.get("japanese-text", {}).get(header, 0)
        cn_extra = before.get("chinese-text", {}).get(header, 0)
        delta = jp_extra - cn_extra
        if not delta:
            continue
        jp_lines = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        cn_lines = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        line_delta = len(jp_lines) - len(cn_lines)
        if line_delta != delta:
            continue
        target = jp_lines if delta > 0 else cn_lines
        removed = 0
        for i in range(len(target) - 1, -1, -1):
            if target[i].strip() == "<br/>":
                del target[i]
                removed += 1
                if removed == abs(delta):
                    break
        if removed == abs(delta):
            path = jp[header] if delta > 0 else cn[header]
            path.write_text("\n".join(target) + "\n", encoding="utf-8", newline="")
            changed += 1
    return changed


def balance_heading_adjacent_breaks(cache: Path) -> int:
    """Delete a heading-adjacent break only when it explains the whole pair delta."""
    def find(root: Path) -> dict[str, Path]:
        result = {}
        for path in root.rglob("*.xhtml"):
            match = ID_RE.search(path.name)
            if match:
                result.setdefault(match.group(1).upper(), path)
        return result

    jp, cn = find(cache / "japanese-text"), find(cache / "chinese-text")
    changed = 0
    for header in set(jp) & set(cn):
        jl = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        cl = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        delta = len(jl) - len(cl)

        def is_special_marker(line: str) -> bool:
            stripped = line.strip()
            return bool(
                re.search(r"<h[12]\b", stripped, re.I)
                or SECTION_NUMBER_RE.fullmatch(stripped)
                or "class=\"right\"" in stripped
                or "class=\"align-end\"" in stripped
            )

        def candidates(lines: list[str]) -> list[int]:
            return [
                i for i, line in enumerate(lines)
                if line.strip() == "<br/>"
                and ((i > 0 and is_special_marker(lines[i - 1]))
                     or (i + 1 < len(lines) and is_special_marker(lines[i + 1])))
            ]

        jc, cc = candidates(jl), candidates(cl)
        if delta > 0 and len(jc) - len(cc) == delta:
            target, path = jl, jp[header]
        elif delta < 0 and len(cc) - len(jc) == -delta:
            target, path = cl, cn[header]
        else:
            continue
        remove = abs(delta)
        for i in reversed(candidates(target)):
            del target[i]
            remove -= 1
            if remove == 0:
                path.write_text("\n".join(target) + "\n", encoding="utf-8", newline="")
                changed += 1
                break
    return changed


def balance_body_break_runs(cache: Path) -> int:
    """Match Japanese break runs to a Chinese three-break run when it explains the delta."""
    def find(root: Path) -> dict[str, Path]:
        result = {}
        for path in root.rglob("*.xhtml"):
            match = ID_RE.search(path.name)
            if match:
                result.setdefault(match.group(1).upper(), path)
        return result

    def runs(lines: list[str]) -> list[tuple[int, int, int]]:
        result = []
        i = 0
        while i < len(lines):
            if lines[i].strip() != "<br/>":
                i += 1
                continue
            j = i
            while j < len(lines) and lines[j].strip() == "<br/>":
                j += 1
            if j - i >= 3:
                result.append((i, j, j - i))
            i = j
        return result

    jp, cn = find(cache / "japanese-text"), find(cache / "chinese-text")
    changed = 0
    for header in set(jp) & set(cn):
        jl = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        cl = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        delta = len(jl) - len(cl)
        jr, cr = runs(jl), runs(cl)
        if delta <= 0 or not any(n > 3 for _, _, n in jr) or not any(n == 3 for _, _, n in cr):
            continue
        difference = next((jn - 3 for _, _, jn in jr if jn > 3), None)
        if difference != delta:
            continue
        start, end, size = next((a, b, n) for a, b, n in jr if n > 3)
        del jl[start + 3:end]
        jp[header].write_text("\n".join(jl) + "\n", encoding="utf-8", newline="")
        changed += 1
    return changed


def align_main_footer_structure(cache: Path) -> int:
    """Match deterministic main-container/footer structure from Japanese.

    Some Chinese cache files omit the ``main`` wrapper and collapse
    ``</body></html>`` onto one line.  When the Japanese counterpart clearly
    uses the wrapper, add it without changing content ordering and split the
    closing tags so the logical line count matches.
    """
    def find(root: Path) -> dict[str, Path]:
        result = {}
        for path in root.rglob("*.xhtml"):
            match = ID_RE.search(path.name)
            if match:
                result.setdefault(match.group(1).upper(), path)
        return result

    jp, cn = find(cache / "japanese-text"), find(cache / "chinese-text")
    changed = 0
    for header in set(jp) & set(cn):
        if "after_the_afterword" in jp[header].name.lower() or "after_the_afterword" in cn[header].name.lower():
            continue
        jl = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        cl = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        if not any('<div class="main">' in line for line in jl):
            continue
        # Only apply to pairs where the remaining mismatch is attributable to
        # the known footer/container shape.
        if len(jl) <= len(cl) or len(jl) - len(cl) > 4:
            continue
        body_idx = next((i for i, line in enumerate(cl) if "<body" in line.lower()), None)
        if body_idx is None:
            continue
        local_changed = False
        has_chinese_wrapper = any(
            re.search(r"<body\b[^>]*>.*<div(?:\s[^>]*)?>", line, re.I)
            for line in cl
        )
        if not has_chinese_wrapper:
            # The Chinese stylesheets do not define the Japanese ``main``
            # class. Keep only the structural wrapper needed for alignment.
            cl[body_idx] = cl[body_idx].rstrip() + '<div>'
            local_changed = True
        close_idx = next((i for i, line in enumerate(cl) if line.strip() == "</body></html>"), None)
        if close_idx is not None:
            # Attach the missing wrapper close to the preceding logical line;
            # this adds no extra content line, then split the body/html tags.
            if close_idx > 0 and "</div>" not in cl[close_idx - 1]:
                cl[close_idx - 1] = cl[close_idx - 1].rstrip() + "</div>"
                local_changed = True
            cl[close_idx:close_idx + 1] = ["</body>", "</html>"]
            local_changed = True
        if local_changed:
            cn[header].write_text("\n".join(cl) + "\n", encoding="utf-8", newline="")
            changed += 1
    return changed


def align_footer_close_line(cache: Path) -> int:
    """Match whether the main-container close occupies its own line."""
    def find(root: Path) -> dict[str, Path]:
        result = {}
        for path in root.rglob("*.xhtml"):
            match = ID_RE.search(path.name)
            if match:
                result.setdefault(match.group(1).upper(), path)
        return result

    jp, cn = find(cache / "japanese-text"), find(cache / "chinese-text")
    changed = 0
    for header in set(jp) & set(cn):
        if "after_the_afterword" in jp[header].name.lower() or "after_the_afterword" in cn[header].name.lower():
            continue
        jl = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        cl = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        ji = next((i for i, x in enumerate(jl) if x.strip() == "</body>"), None)
        ci = next((i for i, x in enumerate(cl) if x.strip() == "</body>"), None)
        if ji is None or ci is None or ji >= 2 and cl == jl:
            continue
        jp_own = ji > 0 and jl[ji - 1].strip() == "</div>"
        cn_prev = cl[ci - 1] if ci > 0 else ""
        cn_inline = "</div>" in cn_prev and cn_prev.strip() != "</div>"
        if jp_own and cn_inline:
            left, right = cn_prev.rsplit("</div>", 1)
            cl[ci - 1:ci] = [left, "</div>"]
            cn[header].write_text("\n".join(cl) + "\n", encoding="utf-8", newline="")
            changed += 1
    return changed



def merge_footer_close_tags(cache: Path) -> int:
    """Merge `</div>`, `</body>`, `</html>` onto one line whenever possible.

    Both Japanese and Chinese cache files sometimes split the three closing
    tags across three separate lines.  Keeping them on one line reduces
    unnecessary line-count differences while preserving the same DOM
    structure.
    """
    changed = 0
    for lang in ("japanese-text", "chinese-text"):
        for path in (cache / lang).rglob("*.xhtml"):
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if len(lines) < 3:
                continue
            if (lines[-3].strip() == "</div>" and lines[-2].strip() == "</body>" and lines[-1].strip() == "</html>"):
                lines[-3:] = ["</div></body></html>"]
                path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
                changed += 1
            elif (lines[-2].strip() == "</body>" and lines[-1].strip() == "</html>" and "</div>" not in lines[-3]):
                lines[-2:] = ["</body></html>"]
                path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
                changed += 1
    return changed


def restore_after_the_afterword_break(cache: Path) -> int:
    """Preserve the known six-break page transition in S2_19-13."""
    target = next((p for p in (cache / "chinese-text").rglob("S2_19-13*.xhtml")), None)
    if target is None:
        return 0
    lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
    image = next((i for i, line in enumerate(lines) if "S2_19-p7" in line), None)
    if image is None:
        return 0
    j = image + 1
    while j < len(lines) and lines[j].strip() == "<br/>":
        j += 1
    jp_target = next((p for p in (cache / "japanese-text").rglob("S2_19-13*.xhtml")), None)
    target_breaks = 6
    if jp_target is not None:
        jl = jp_target.read_text(encoding="utf-8", errors="ignore").splitlines()
        ji = next((i for i, line in enumerate(jl) if "p375.jpg" in line), None)
        if ji is not None:
            k = ji + 1
            while k < len(jl) and jl[k].strip() == "<br/>":
                k += 1
            # The Japanese page transition intentionally keeps six breaks
            # after the image's closing page marker.
            target_breaks = max(6, k - ji - 1)
    current = j - image - 1
    if current == target_breaks:
        return 0
    if current < target_breaks:
        lines[image + 1:image + 1] = ["<br/>"] * (target_breaks - current)
    else:
        del lines[image + 1 + target_breaks:image + 1 + current]
    # Keep this file's original page-transition footer shape: the closing
    # container/body/html tags are intentionally one logical line.
    for i in range(len(lines) - 2):
        if lines[i].strip() == "</div>" and lines[i + 1].strip() == "</body>" and lines[i + 2].strip() == "</html>":
            lines[i:i + 3] = ["</div></body></html>"]
            break
    target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".cache/epub-audit"))
    args = parser.parse_args()
    inline_before: dict[str, dict[str, int]] = {}
    for lang in ("japanese-text", "chinese-text"):
        inline_before[lang] = {}
        for path in (args.cache / lang).rglob("*.xhtml"):
            match = ID_RE.search(path.name)
            if match:
                inline_before[lang][match.group(1).upper()] = count_inline_breaks(path)
    total = 0
    for lang in ("japanese-text", "chinese-text"):
        files = list((args.cache / lang).rglob("*.xhtml"))
        changed = sum(normalize_file(path) for path in files)
        total += changed
        print(f"{lang}: 修改 {changed} 个文件，共 {len(files)} 个")
    print(f"后记署名前补齐：{apply_afterword_breaks(args.cache)} 个文件")
    print(f"后记分段换行平衡：{balance_afterword_breaks(args.cache)} 个文件")
    print(f"删除文本图片占位补齐：{apply_deleted_image_breaks(args.cache)} 个文件")
    print(f"gaiji 段落后换行补齐：{apply_gaiji_breaks(args.cache)} 个文件")
    print(f"图片位置直接重排修复：{apply_direct_image_reorders(args.cache)} 个文件")
    print(f"拆分换行造成的不平衡回补：{balance_split_breaks(args.cache, inline_before)} 个文件")
    print(f"h1/h2 前后换行不平衡回补：{balance_heading_adjacent_breaks(args.cache)} 个文件")
    print(f"正文三连换行差异回补：{balance_body_break_runs(args.cache)} 个文件")
    print(f"main 容器与页尾结构对齐：{align_main_footer_structure(args.cache)} 个文件")
    print(f"页尾闭合标签行形态对齐：{align_footer_close_line(args.cache)} 个文件")
    print(f"收尾闭合标签单行合并：{merge_footer_close_tags(args.cache)} 个文件")
    print(f"S2_19-13 跨页换行恢复：{restore_after_the_afterword_break(args.cache)} 个文件")
    print(f"总计修改 {total} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
