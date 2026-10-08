#!/usr/bin/env python3
"""Normalize one or more XHTML files with the shared fixed-line engine.

This CLI selects files only. All transformations are implemented in
``xhtml_template.py`` and are therefore identical to ``normalize_paired.py``.
"""
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

from file_transaction import rollback_paths
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


def prepare(path: Path, side: str | None) -> tuple[Path, list[str], bytes, bool, bool, str] | None:
    """Validate one file and return its pending write without touching disk."""
    if not path.exists():
        raise OSError(f"文件不存在：{path}")
    if not has_body(path):
        return None
    new, message = rebuild(path, None, side)
    if new is None:
        raise ValueError(f"{path}: {message}")
    ET.fromstring("\n".join(new))
    raw = path.read_bytes()
    old, bom, crlf = read_lines(path)
    if new == old:
        return None
    return path, new, raw, bom, crlf, message


def apply_plans(plans: list[tuple[Path, list[str], bytes, bool, bool, str]]) -> None:
    """Apply a batch and restore every already-written file if one write fails."""
    with rollback_paths(path for path, *_ in plans):
        for path, new, raw, bom, crlf, _ in plans:
            write_lines(path, new, bom, crlf)


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
    side_for = lambda path: args.side or (
        "cn" if path.resolve().is_relative_to(DEFAULT_EPUB.resolve()) else None
    )
    plans = []
    try:
        for path in files:
            plan = prepare(path, side_for(path))
            if plan is not None:
                plans.append(plan)
    except (OSError, UnicodeError, ET.ParseError, ValueError) as exc:
        print(f"[阻断] 规范化预检失败；没有写入任何文件：{exc}")
        return 1

    if not args.apply:
        for path, _, _, _, _, message in plans:
            print(f"[预览] {path}: {message}")
        print(f"\n总计：{len(files)} 个成功，0 个失败")
        return 0

    try:
        apply_plans(plans)
    except (OSError, UnicodeError) as exc:
        print(f"[阻断] 写入失败，已回滚本次文件：{exc}")
        return 1
    for path, _, _, _, _, message in plans:
        print(f"[完成] {path}: {message}")
    print(f"\n总计：{len(files)} 个成功，0 个失败")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
