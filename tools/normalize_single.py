#!/usr/bin/env python3
"""Normalize one or more XHTML files with the shared fixed-line engine.

This CLI selects files only. All transformations are implemented in
``xhtml_template.py`` and are therefore identical to ``normalize_paired.py``.
"""
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

from xhtml_template import has_body, read_lines, rebuild, write_lines
from edit_safety import DEFAULT_EPUB, EditSafetyError, add_edit_mode, require_edit_target


def normalize_single(path: Path, dry_run: bool = False, side: str | None = None) -> bool:
    if not path.exists():
        print(f"[错误] 文件不存在：{path}")
        return False
    try:
        if not has_body(path):
            print(f"[跳过] 无正文：{path}")
            return True
        new, message = rebuild(path, None, side)
        if new is None:
            print(f"[失败] {path}: {message}")
            return False
        ET.fromstring("\n".join(new))
        old, bom, crlf = read_lines(path)
        if new == old:
            print(f"[无变化] {path}")
            return True
        if dry_run:
            print(f"[预览] {path}: {message}")
            return True
        write_lines(path, new, bom, crlf)
        print(f"[完成] {path}: {message}")
        return True
    except (OSError, UnicodeError, ET.ParseError) as exc:
        print(f"[异常] {path}: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="单文件/目录固定行模板规范化工具")
    parser.add_argument("paths", nargs="*", type=Path, help="要处理的文件")
    parser.add_argument("--dir", type=Path, help="批量处理目录")
    parser.add_argument("--pattern", default="*.xhtml", help="文件匹配模式（配合 --dir）")
    parser.add_argument("--side", choices=("cn", "jp"), default=None, help="语言侧；归档默认 cn，暂存未指定时沿用路径识别")
    add_edit_mode(parser)
    args = parser.parse_args()

    if args.dir:
        if not args.dir.exists():
            print(f"[错误] 目录不存在：{args.dir}")
            return 1
        files = sorted(args.dir.rglob(args.pattern))
    else:
        files = args.paths
    files = [path for path in files if path.name.casefold() != "nav.xhtml"]
    if not files:
        print("[错误] 没有找到要处理的文件")
        return 1

    if args.apply:
        try:
            for path in files:
                require_edit_target(path, args.staging)
        except EditSafetyError as exc:
            parser.error(str(exc))
    success = sum(normalize_single(path, not args.apply,
                  args.side or ("cn" if path.resolve().is_relative_to(DEFAULT_EPUB.resolve()) else None))
                  for path in files)
    failed = len(files) - success
    print(f"\n总计：{success} 个成功，{failed} 个失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
