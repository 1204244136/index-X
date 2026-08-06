#!/usr/bin/env python3
"""Classify remaining line-count differences by lightweight XHTML block shape."""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

ID_RE = re.compile(r"(S\d+_\d+(?:_\d+)?-\d+)", re.I)
SECTION_NUMBER_RE = re.compile(r"^<p>\s*[０-９0-9]+\s*</p>$")


def index(root: Path) -> dict[str, Path]:
    result = {}
    for path in root.rglob("*.xhtml"):
        match = ID_RE.search(path.name)
        if match:
            result.setdefault(match.group(1).upper(), path)
    return result


def kind(line: str) -> str:
    s = line.strip()
    if s == "<br/>": return "br"
    if SECTION_NUMBER_RE.fullmatch(s): return "heading"
    if s.lower() == "<!doctype html>": return "doctype"
    if "<img" in s or "<svg" in s: return "image"
    if "</body>" in s or "</html>" in s or "</div>" in s and s.startswith("</div>"): return "footer"
    if "align-end" in s or 'class="right"' in s or "align-right" in s: return "signature"
    if "<h1" in s or "<h2" in s: return "heading"
    if "<p" in s: return "paragraph"
    return "other"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".cache/epub-work"))
    args = parser.parse_args()
    jp, cn = index(args.cache / "japanese-text"), index(args.cache / "chinese-text")
    rows, totals = [], Counter()
    afterword_rows = []
    for header in sorted(set(jp) & set(cn)):
        jlines = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        clines = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        diff = len(clines) - len(jlines)
        if not diff:
            continue
        jc, cc = Counter(map(kind, jlines)), Counter(map(kind, clines))
        delta = {k: cc[k] - jc[k] for k in set(jc) | set(cc) if cc[k] != jc[k]}
        structural = ",".join(f"{k}:{v:+d}" for k, v in sorted(delta.items()))
        rows.append((header, len(jlines), len(clines), diff, structural, jp[header], cn[header]))
        if "Afterwords" in jp[header].name or "あとがき" in "".join(jlines[:8]) or ">后记<" in "".join(clines[:8]):
            afterword_rows.append((header, diff, delta.get("br", 0), structural))
        for k, v in delta.items(): totals[f"{k}:{'+' if v > 0 else '-'}"] += 1
    out = args.cache / "diff-structure.tsv"
    with out.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["表头", "日文行数", "中文行数", "差值", "结构计数差", "日文文件", "中文文件"])
        writer.writerows(rows)
    print(f"差异文件：{len(rows)}")
    print(f"其中后记：{len(afterword_rows)}")
    print("后记换行计数差：" + ", ".join(f"{r[0]}={r[2]:+d}" for r in afterword_rows[:50]))
    print("结构计数差：" + ", ".join(f"{k}={v}" for k, v in sorted(totals.items())))
    print(f"报告：{out}")
    for row in rows[:20]: print("\t".join(map(str, row[:5])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
