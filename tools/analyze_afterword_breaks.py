#!/usr/bin/env python3
"""Find afterword pairs where Japanese lacks a break before the signature block."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ID_RE = re.compile(r"(S\d+_\d+-\d+)", re.I)


def index(root: Path) -> dict[str, Path]:
    result = {}
    for path in root.rglob("*.xhtml"):
        match = ID_RE.search(path.name)
        if match and ("Afterwords" in path.name or "あとがき" in path.read_text(encoding="utf-8", errors="ignore")[:1200] or ">后记<" in path.read_text(encoding="utf-8", errors="ignore")[:1200]):
            result.setdefault(match.group(1).upper(), path)
    return result


def signature_index(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        if "align-end" in line or 'class="right"' in line or "align-right" in line:
            return i
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".cache/epub-audit"))
    args = parser.parse_args()
    jp, cn = index(args.cache / "japanese-text"), index(args.cache / "chinese-text")
    candidates = []
    reverse = []
    for header in sorted(set(jp) & set(cn)):
        jl = jp[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        cl = cn[header].read_text(encoding="utf-8", errors="ignore").splitlines()
        ji, ci = signature_index(jl), signature_index(cl)
        if ji is None or ci is None:
            continue
        jp_before = jl[max(0, ji - 3):ji]
        cn_before = cl[max(0, ci - 3):ci]
        jp_br = sum(x.strip() == "<br/>" for x in jp_before)
        cn_br = sum(x.strip() == "<br/>" for x in cn_before)
        if cn_br > jp_br:
            candidates.append((header, len(jl), len(cl), cn_br - jp_br, jp[header], cn[header]))
        elif jp_br > cn_br:
            reverse.append((header, len(jl), len(cl), jp_br - cn_br, jp[header], cn[header]))
    out = args.cache / "afterword-break-candidates.tsv"
    out.write_text("表头\t日文行数\t中文行数\t署名前局部换行差\t日文文件\t中文文件\n" + "\n".join("\t".join(map(str, row)) for row in candidates) + "\n", encoding="utf-8")
    print(f"后记候选：{len(candidates)}")
    print(f"中文可能缺少换行：{len(reverse)}")
    print(f"报告：{out}")
    for row in candidates[:20]: print("\t".join(map(str, row[:4])))
    if reverse:
        print("中文可能缺少换行的示例：")
        for row in reverse[:20]: print("\t".join(map(str, row[:4])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
