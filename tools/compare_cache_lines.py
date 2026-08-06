#!/usr/bin/env python3
"""Compare line counts for matching Sx_yy-zz XHTML files in local caches."""
from __future__ import annotations

import argparse
import csv
import os
import re
from pathlib import Path

ID_RE = re.compile(r"(S\d+_\d+(?:_\d+)?-\d+)", re.I)


def markdown_link(path: Path, label: str, report_dir: Path) -> str:
    target = Path(os.path.relpath(path.resolve(), report_dir.resolve())).as_posix()
    return f"[{label}](<{target}>)"


def index(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.rglob("*.xhtml"):
        match = ID_RE.search(path.name)
        if match:
            result.setdefault(match.group(1).upper(), path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".cache/epub-work"))
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    japanese = index(args.cache / "japanese-text")
    chinese = index(args.cache / "chinese-text")
    rows = []
    for header in sorted(set(japanese) & set(chinese)):
        jp_path, cn_path = japanese[header], chinese[header]
        jp_lines = len(jp_path.read_text(encoding="utf-8", errors="ignore").splitlines())
        cn_lines = len(cn_path.read_text(encoding="utf-8", errors="ignore").splitlines())
        rows.append({"表头": header, "日文行数": jp_lines, "中文行数": cn_lines,
                     "中文-日文": cn_lines - jp_lines,
                     "日文文件": str(jp_path), "中文文件": str(cn_path)})
    tsv = args.cache / "normalized-line-diff.tsv"
    with tsv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys() if rows else ["表头"], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    different = [row for row in rows if row["中文-日文"]]
    report = args.cache / "normalized-line-diff.md"
    lines = ["# 规范化缓存行数差异", "", f"唯一对应表头：{len(rows)}；行数一致：{len(rows) - len(different)}；存在差异：{len(different)}。", ""]
    lines.extend(
        f"- `{row['表头']}`：日文 {row['日文行数']} 行，中文 {row['中文行数']} 行，差值 {row['中文-日文']:+d}；"
        f"{markdown_link(Path(row['日文文件']), '日文文件', report.parent)}，{markdown_link(Path(row['中文文件']), '中文文件', report.parent)}"
        for row in different
    )
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"唯一对应表头：{len(rows)}")
    print(f"行数一致：{len(rows) - len(different)}")
    print(f"存在差异：{len(different)}")
    print(f"报告：{report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
