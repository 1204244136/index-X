#!/usr/bin/env python3
"""List XHTML files that contain only a standalone image/SVG content block."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

SEQ_RE = re.compile(r"^(S\d+_\d+)-(\d+)_p-(\d+)", re.I)


def is_orphan(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "<img" not in text and "<svg" not in text:
        return False
    body = re.sub(r"<\?xml[^>]*>|<!DOCTYPE[^>]*>|<html\b[^>]*>|</html>|<head\b.*?</head>|<body\b[^>]*>|</body>|<div\b[^>]*>|</div>|<p\b[^>]*>|</p>|<img\b[^>]*/>|<svg\b[^>]*>.*?</svg>|<br\s*/?>", "", text, flags=re.I | re.S)
    return not re.sub(r"\s+", "", body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".cache/epub-work"))
    args = parser.parse_args()
    found = []
    for lang in ("japanese-text", "chinese-text"):
        files = list((args.cache / lang).rglob("*.xhtml"))
        by_key = {}
        for path in files:
            match = SEQ_RE.match(path.stem)
            if match:
                by_key[(path.parent, match.group(1).upper(), int(match.group(2)))] = path
        for (parent, series, number), path in by_key.items():
            if not is_orphan(path):
                continue
            prev_path = by_key.get((parent, series, number - 1))
            next_path = by_key.get((parent, series, number + 1))
            next_text = next_path.read_text(encoding="utf-8", errors="ignore") if next_path else ""
            is_afterword = next_path and ("Afterwords" in next_path.name or "あとがき" in next_text[:1200] or ">后记<" in next_text[:1200])
            if prev_path and next_path and is_afterword and not is_orphan(prev_path) and not is_orphan(next_path):
                found.append((lang, path))
    out = args.cache / "orphan-image-pages.tsv"
    out.write_text("语言\t文件\n" + "\n".join(f"{lang}\t{path}" for lang, path in found) + "\n", encoding="utf-8")
    print(f"孤立图片文件：{len(found)}")
    print(f"报告：{out}")
    for lang, path in found[:50]: print(f"{lang}\t{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
