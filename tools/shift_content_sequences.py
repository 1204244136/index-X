#!/usr/bin/env python3
"""整体平移一个作品的 XHTML 内容序，并同步改写书内引用。

用于规则迁移等已经确认需要整体顺移的场景。默认只预览；显式 ``--apply``
才写入。文件名替换采用单次匹配，避免 ``00 -> 01 -> 02`` 级联误改。
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


REFERENCE_SUFFIXES = frozenset({
    ".xhtml", ".html", ".htm", ".opf", ".ncx", ".xml", ".css", ".svg",
})
WORK_ID_RE = re.compile(
    r"S\d+_(?:\d+(?:_\d+)?|\d{2}(?:\.\d{2}){2})",
    re.IGNORECASE,
)


def plan_shift(root: Path, work_id: str, offset: int) -> dict[Path, Path]:
    """生成待重命名文件映射；目标序号小于 01 或发生冲突时拒绝。"""
    work_id = work_id.upper()
    if not WORK_ID_RE.fullmatch(work_id):
        raise ValueError(f"无效作品号：{work_id}")
    if offset == 0:
        raise ValueError("--offset 不能为 0")
    pattern = re.compile(
        rf"^{re.escape(work_id)}-(?P<sequence>\d+)"
        rf"(?P<tail>_.*\.(?:xhtml|html|htm)|\.(?:xhtml|html|htm))$",
        re.IGNORECASE,
    )
    renames: dict[Path, Path] = {}
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        match = pattern.fullmatch(path.name)
        if match is None:
            continue
        new_sequence = int(match.group("sequence")) + offset
        if new_sequence < 1:
            raise ValueError(
                f"{path.name} 平移后为 {new_sequence:02d}，数字内容序必须从 01 开始"
            )
        target = path.with_name(
            f"{work_id}-{new_sequence:02d}{match.group('tail')}"
        )
        renames[path] = target

    sources = set(renames)
    targets = list(renames.values())
    if len(targets) != len(set(targets)):
        raise ValueError("平移后存在重复目标文件名")
    for target in targets:
        if target.exists() and target not in sources:
            raise ValueError(f"目标文件已存在且不在本次平移范围：{target}")
    return renames


def reference_rewrites(root: Path, renames: dict[Path, Path]) -> dict[Path, bytes]:
    """返回需要改写的引用文件及其新字节，不写盘。"""
    by_name = {old.name.encode("utf-8"): new.name.encode("utf-8")
               for old, new in renames.items()}
    if not by_name:
        return {}
    existing_names = {
        path.name.casefold() for path in root.rglob("*") if path.is_file()
    }
    raw_page_targets: dict[bytes, set[bytes]] = {}
    for old, new in renames.items():
        match = re.search(r"_(p-\d{3}\.xhtml)$", old.name, re.IGNORECASE)
        if match is None or match.group(1).casefold() in existing_names:
            continue
        raw = match.group(1).encode("utf-8")
        raw_page_targets.setdefault(raw, set()).add(new.name.encode("utf-8"))
    # 只修复目标唯一、且目录中不存在同名真实文件的旧裸分页引用。
    raw_by_name = {
        raw: next(iter(targets))
        for raw, targets in raw_page_targets.items()
        if len(targets) == 1
    }
    pattern = re.compile(
        b"|".join(re.escape(name) for name in sorted(by_name, key=len, reverse=True))
    )
    raw_pattern = (
        re.compile(
            rb"(?<![A-Za-z0-9_.-])(?:"
            + b"|".join(
                re.escape(name) for name in sorted(raw_by_name, key=len, reverse=True)
            )
            + rb")"
        )
        if raw_by_name else None
    )
    rewritten: dict[Path, bytes] = {}
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if path.suffix.casefold() not in REFERENCE_SUFFIXES:
            continue
        original = path.read_bytes()
        updated = pattern.sub(lambda match: by_name[match.group(0)], original)
        if raw_pattern is not None:
            updated = raw_pattern.sub(
                lambda match: raw_by_name[match.group(0)], updated
            )
        if updated != original:
            rewritten[path] = updated
    return rewritten


def apply_shift(root: Path, renames: dict[Path, Path], rewrites: dict[Path, bytes]) -> None:
    """先改引用，再用两阶段重命名安全处理相邻序号冲突。"""
    staged = [
        (source, source.with_name(f".shift-sequence-{index:04d}-{source.name}"), target)
        for index, (source, target) in enumerate(renames.items(), 1)
    ]
    for _, temporary, _ in staged:
        if temporary.exists():
            raise ValueError(f"临时文件已存在：{temporary}")
    originals = {path: path.read_bytes() for path in rewrites}
    for path, data in rewrites.items():
        path.write_bytes(data)

    moved: list[tuple[Path, Path, Path]] = []
    try:
        for source, temporary, target in staged:
            source.rename(temporary)
            moved.append((source, temporary, target))
        for _, temporary, target in moved:
            temporary.rename(target)
    except Exception:
        for source, temporary, target in reversed(moved):
            if target.exists() and not source.exists():
                target.rename(source)
            elif temporary.exists() and not source.exists():
                temporary.rename(source)
        for path, data in originals.items():
            path.write_bytes(data)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="整体平移一个作品的 XHTML 内容序并同步改写 OPF/NCX/nav 等引用"
    )
    parser.add_argument("root", type=Path, help="一本 EPUB 的解包根目录")
    parser.add_argument("--work-id", required=True, help="完整作品号，如 S4_05 或 S5_01_01")
    parser.add_argument("--offset", required=True, type=int, help="内容序增量，如 1")
    parser.add_argument("--apply", action="store_true", help="写入；默认只预览")
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"目录不存在：{root}")
    try:
        renames = plan_shift(root, args.work_id, args.offset)
        rewrites = reference_rewrites(root, renames)
    except ValueError as exc:
        parser.error(str(exc))

    mode = "写入" if args.apply else "预览"
    print(f"[{mode}] XHTML 重命名 {len(renames)} 个；引用文件改写 {len(rewrites)} 个")
    for source, target in renames.items():
        print(f"  {source.relative_to(root)} -> {target.name}")
    if args.apply:
        apply_shift(root, renames, rewrites)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
