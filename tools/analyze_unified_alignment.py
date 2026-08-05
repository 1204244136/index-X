#!/usr/bin/env python3
"""Coordinate XHTML line-count and image-position alignment in one report."""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

ID_RE = re.compile(r"(S\d+_\d+-\d+)", re.I)
IMAGE_RE = re.compile(r"<(?:img|svg)\b|data-image-continuation=", re.I)
SRC_RE = re.compile(r"(?:src|href|data-image-continuation)=['\"]([^'\"]+)['\"]", re.I)
TEXTUAL_IMAGE_EXCLUSIONS = {"S2_14-04", "S2_14-07", "S2_14-10", "S2_14-13"}


def index(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.rglob("*.xhtml"):
        match = ID_RE.search(path.name)
        if match:
            result.setdefault(match.group(1).upper(), path)
    return result


def is_layout_image(line: str) -> bool:
    lowered = line.lower()
    return bool(IMAGE_RE.search(line)) and "gaiji" not in lowered and "height-2em" not in lowered


def image_rows(path: Path) -> list[tuple[int, str]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if is_layout_image(line):
            source = SRC_RE.search(line)
            rows.append((number, source.group(1) if source else "<inline-svg>"))
    return rows


def shape_counts(lines: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in lines:
        stripped = line.strip()
        if stripped == "<br/>":
            counts["br"] += 1
        elif re.search(r"<h[12]\b", stripped, re.I):
            counts["heading"] += 1
        elif IMAGE_RE.search(stripped):
            counts["image"] += 1
        elif "align-end" in stripped or 'class="right"' in stripped:
            counts["align"] += 1
        elif stripped.startswith("<p"):
            counts["paragraph"] += 1
        elif "</body>" in stripped or "</html>" in stripped or stripped.startswith("</div"):
            counts["footer"] += 1
        else:
            counts["other"] += 1
    return counts


def delta_summary(jp: list[str], cn: list[str]) -> str:
    jc, cc = shape_counts(jp), shape_counts(cn)
    parts = []
    for key in sorted(set(jc) | set(cc)):
        diff = cc[key] - jc[key]
        if diff:
            parts.append(f"{key}:{diff:+d}")
    return ",".join(parts)


def classify(line_delta: int, header: str, jr: list[tuple[int, str]], cr: list[tuple[int, str]]) -> tuple[str, str, str]:
    if line_delta:
        line_status = "中文多" if line_delta > 0 else "中文少"
        image_status = "行数未对齐，图片暂不判定" if jr or cr else "无图片"
        priority = "先修行数" if jr or cr else "仅行数"
        return line_status, image_status, priority
    line_status = "一致"
    if header in TEXTUAL_IMAGE_EXCLUSIONS:
        return line_status, "文本化图片", "已确认例外"
    if not jr and not cr:
        return line_status, "无图片", "无"
    jrows, crows = [x[0] for x in jr], [x[0] for x in cr]
    if len(jr) != len(cr):
        return line_status, "图片数量差异", "图片复核"
    if jrows == crows:
        return line_status, "图片行已对齐", "无"
    return line_status, "图片行错位", "图片复核"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".cache/epub-audit"))
    args = parser.parse_args()
    jp, cn = index(args.cache / "japanese-text"), index(args.cache / "chinese-text")
    rows = []
    for header in sorted(set(jp) & set(cn)):
        jl = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        cl = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        jr, cr = image_rows(jp[header]), image_rows(cn[header])
        line_delta = len(cl) - len(jl)
        line_status, image_status, priority = classify(line_delta, header, jr, cr)
        rows.append({
            "表头": header,
            "日文行数": len(jl),
            "中文行数": len(cl),
            "中文-日文": line_delta,
            "行数状态": line_status,
            "日文图片数": len(jr),
            "中文图片数": len(cr),
            "日文图片行": ",".join(str(x[0]) for x in jr),
            "中文图片行": ",".join(str(x[0]) for x in cr),
            "图片状态": image_status,
            "处理优先级": priority,
            "行结构差异": delta_summary(jl, cl),
            "日文资源": ",".join(x[1] for x in jr),
            "中文资源": ",".join(x[1] for x in cr),
            "日文文件": str(jp[header]),
            "中文文件": str(cn[header]),
        })
    report = args.cache / "unified-alignment.tsv"
    report.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["表头"]
    with report.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    counts = Counter((row["行数状态"], row["图片状态"]) for row in rows)
    md = args.cache / "unified-alignment.md"
    lines = ["# 中日行数与图片统一对齐报告", "", "判定顺序：先处理中日总行数；只有行数一致时才判定图片行位置。", ""]
    lines.append(f"唯一对应表头：{len(rows)}；行数一致：{sum(r['中文-日文'] == 0 for r in rows)}；行数差异：{sum(r['中文-日文'] != 0 for r in rows)}。")
    lines.append(f"图片行错位/数量差异：{sum(r['处理优先级'] == '图片复核' for r in rows)}；行数未对齐而暂缓图片判定：{sum('暂不判定' in r['图片状态'] for r in rows)}。")
    lines.append("")
    lines.append("| 行数状态 | 图片状态 | 数量 |")
    lines.append("|---|---|---:|")
    for (line_status, image_status), count in sorted(counts.items()):
        lines.append(f"| {line_status} | {image_status} | {count} |")
    lines.append("")
    lines.append("详细逐文件数据见 `unified-alignment.tsv`。")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"统一对齐报告：{report}")
    print(f"摘要报告：{md}")
    print(f"行数差异：{sum(r['中文-日文'] != 0 for r in rows)}")
    print(f"图片需复核：{sum(r['处理优先级'] == '图片复核' for r in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
