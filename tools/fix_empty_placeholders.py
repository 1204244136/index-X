#!/usr/bin/env python3
"""Remove empty numbered XHTML placeholders and close the filename gap."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

NAME_RE = re.compile(r"^(S\d+_\d+)-(\d+)(_p-(\d+)|_p-[^.]+)(\.xhtml)$", re.I)


def is_empty(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "<img" in text or "<svg" in text:
        return False
    body = re.sub(r"<head\b.*?</head>", "", text, flags=re.I | re.S)
    body = re.sub(r"<[^>]+>", "", body)
    return not re.sub(r"\s+", "", body)


def candidates(root: Path) -> list[Path]:
    result = []
    for directory in {p.parent for p in root.rglob("*.xhtml")}:
        numbered = {}
        for path in directory.glob("*.xhtml"):
            match = NAME_RE.match(path.name)
            if match:
                numbered[int(match.group(2))] = path
        for number, path in numbered.items():
            if number - 1 in numbered and number + 1 in numbered and is_empty(path):
                result.append(path)
    return sorted(result)


def shifted_name(path: Path) -> str:
    match = NAME_RE.match(path.name)
    if not match:
        return path.name
    sequence = int(match.group(2)) - 1
    suffix = match.group(3)
    page = match.group(4)
    if page is not None:
        suffix = f"_p-{int(page) - 1:03d}"
    return f"{match.group(1)}-{sequence:02d}{suffix}{match.group(5)}"


def apply_candidate(path: Path) -> list[tuple[Path, Path]]:
    match = NAME_RE.match(path.name)
    assert match
    prefix, deleted = match.group(1), int(match.group(2))
    later = []
    for sibling in path.parent.glob(f"{prefix}-*.xhtml"):
        sibling_match = NAME_RE.match(sibling.name)
        if sibling_match and int(sibling_match.group(2)) > deleted:
            later.append(sibling)
    path.unlink()
    renamed = []
    for sibling in sorted(later, key=lambda p: int(NAME_RE.match(p.name).group(2))):
        target = sibling.with_name(shifted_name(sibling))
        sibling.rename(target)
        renamed.append((sibling, target))
    return renamed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".cache/epub-audit/japanese-text"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    found = candidates(args.cache)
    print(f"空占位候选：{len(found)}")
    for path in found:
        print(path)
    if args.apply:
        # Work from the highest sequence number down in each directory so that
        # renaming a later page cannot invalidate another candidate path.
        ordered = sorted(found, key=lambda path: (str(path.parent), -int(NAME_RE.match(path.name).group(2))))
        for path in ordered:
            print(f"删除：{path}")
            for source, target in apply_candidate(path):
                print(f"重命名：{source.name} -> {target.name}")
        print(f"已处理：{len(found)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
