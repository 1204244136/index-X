#!/usr/bin/env python3
"""Report Japanese/Chinese XHTML image line alignment candidates.

This tool is intentionally read-only: image misalignment requires manual
semantic review before any cache edit is proposed or applied.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ID_RE = re.compile(r"(S\d+_\d+-\d+)", re.I)
IMAGE_RE = re.compile(r"<(?:img|svg)\b|data-image-continuation=", re.I)
SRC_RE = re.compile(r"(?:src|href|data-image-continuation)=['\"]([^'\"]+)['\"]", re.I)

# Reviewed cases where the Japanese image is a textual list/annotation and
# the Chinese cache intentionally translates it into ordinary XHTML text.
TEXTUAL_IMAGE_EXCLUSIONS = {
    "S2_14-04",
    "S2_14-07",
    "S2_14-10",
    "S2_14-13",
}

def is_layout_image(line: str) -> bool:
    """Return true for full-page/layout images, excluding inline glyph art."""
    lowered = line.lower()
    return bool(IMAGE_RE.search(line)) and "gaiji" not in lowered and "height-2em" not in lowered


def index(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.rglob("*.xhtml"):
        match = ID_RE.search(path.name)
        if match:
            result.setdefault(match.group(1).upper(), path)
    return result


def image_rows(path: Path) -> list[tuple[int, str]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if is_layout_image(line):
            source = SRC_RE.search(line)
            rows.append((number, source.group(1) if source else "<inline-svg>"))
    return rows


def snippet(path: Path, intervals: list[tuple[int, int]]) -> str:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not intervals:
        return ""
    pieces = []
    for start, end in intervals:
        start = max(0, start - 2)
        end = min(len(lines), end + 1)
        pieces.extend(f"{i + 1}:{lines[i].strip()}" for i in range(start, end))
    return " ".join(dict.fromkeys(pieces))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".cache/epub-audit"))
    args = parser.parse_args()
    cache = args.cache
    jp, cn = index(cache / "japanese-text"), index(cache / "chinese-text")
    report = cache / "image-alignment.tsv"
    lines = ["表头\t日文行数\t中文行数\t日文图片行\t中文图片行\t日文资源\t中文资源\t状态\t日文片段\t中文片段\t建议"]
    candidates = 0
    for header in sorted(set(jp) & set(cn)):
        jp_line_count = len(jp[header].read_text(encoding="utf-8", errors="ignore").splitlines())
        cn_line_count = len(cn[header].read_text(encoding="utf-8", errors="ignore").splitlines())
        jr, cr = image_rows(jp[header]), image_rows(cn[header])
        image_lines_aligned = len(jr) == len(cr) and [x[0] for x in jr] == [x[0] for x in cr]
        if jp_line_count != cn_line_count:
            status = "行数未对齐"
        elif header in TEXTUAL_IMAGE_EXCLUSIONS:
            status = "文本化图片"
        else:
            status = "一致" if image_lines_aligned else "人工复核"
        if status in {"人工复核", "行数未对齐"}:
            candidates += 1
        jp_rows = [row for row, _ in jr]
        cn_rows = [row for row, _ in cr]
        intervals = []
        for idx in range(max(len(jp_rows), len(cn_rows))):
            paired = [x for x in (jp_rows[idx] if idx < len(jp_rows) else None,
                                  cn_rows[idx] if idx < len(cn_rows) else None) if x is not None]
            if paired:
                intervals.append((min(paired), max(paired)))
        jp_context = snippet(jp[header], intervals)
        cn_context = snippet(cn[header], intervals)
        if status == "人工复核":
            advice = "以日文图片相对位置为准，优先调整中文"
        elif status == "行数未对齐":
            advice = "先修复中日总行数差异，再复核图片位置"
        elif status == "文本化图片":
            advice = "日文图片内容已由中文文本承载，排除人工复核"
        else:
            advice = ""
        lines.append(
            f"{header}\t{jp_line_count}\t{cn_line_count}\t"
            f"{','.join(str(x[0]) for x in jr)}\t{','.join(str(x[0]) for x in cr)}\t"
            f"{','.join(x[1] for x in jr)}\t{','.join(x[1] for x in cr)}\t{status}\t"
            f"{jp_context}\t{cn_context}\t{advice}"
        )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    print(f"图片人工复核候选：{candidates}")
    print(f"报告：{report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
