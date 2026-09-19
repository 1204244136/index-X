#!/usr/bin/env python3
"""Change detection, tree mirroring, upload and pull-state helpers."""
from __future__ import annotations

import shutil
from pathlib import Path

from path_safety import is_extract_artifact


STATUS_LABELS = {"added": "新增", "modified": "修改", "deleted": "删除"}
PULL_STATE_FILENAME = "pull-state.tsv"
UNIX_TO_DOTNET_TICKS_OFFSET = 621355968000000000
ONEDRIVE_DEFAULTS = {
    "chinese-text": Path.home() / "OneDrive" / "某系列" / "X系列" / "EPUB",
    "japanese-text": Path.home() / "OneDrive" / "某系列" / "日文原文",
}

SIDE_DIRECTORIES = ("chinese-text", "japanese-text")
SIDE_LABELS = {"chinese-text": "中文", "japanese-text": "日文"}


def read_pull_state(cache_root: Path) -> dict[str, tuple[str, str]]:
    state_path = cache_root / PULL_STATE_FILENAME
    records: dict[str, tuple[str, str]] = {}
    if not state_path.is_file():
        return records
    for line in state_path.read_text(encoding="utf-8-sig").splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            records[f"{parts[0]}/{parts[1]}"] = (parts[2], parts[3])
    return records


def update_pull_state_record(
    cache_root: Path, book_key: str, mtime_ticks: int, size: int
) -> None:
    state_path = cache_root / PULL_STATE_FILENAME
    records = read_pull_state(cache_root)
    records[book_key] = (str(mtime_ticks), str(size))
    lines = []
    for key, (ticks, length) in sorted(records.items()):
        side, book = key.split("/", 1)
        lines.append(f"{side}\t{book}\t{ticks}\t{length}\n")
    state_path.write_text(
        "".join(lines),
        encoding="utf-8",
    )


def upload_book(packed_epub: Path, destination: Path, cache_root: Path, book_key: str) -> None:
    """Copy a packaged book, then record the uploaded file's timestamp and size.

    The caller owns direction, preflight checks and logging. Failed copies must
    never advance pull-state; errors propagate so the manifest is not advanced.
    """
    shutil.copy2(packed_epub, destination)
    stat = destination.stat()
    update_pull_state_record(
        cache_root, book_key,
        stat.st_mtime_ns // 100 + UNIX_TO_DOTNET_TICKS_OFFSET,
        stat.st_size,
    )


def remove_pull_state_record(cache_root: Path, book_key: str) -> bool:
    """从 pull-state.tsv 移除一本书的记录；返回是否实际移除。

    用于书籍已从缓存整体删除（如外典合订卷拆分、目录改名）后，
    同步清理拉取状态记录。
    """
    state_path = cache_root / PULL_STATE_FILENAME
    if not state_path.is_file():
        return False
    side, book = book_key.split("/", 1)
    removed = False
    kept: list[str] = []
    for line in state_path.read_text(encoding="utf-8-sig").splitlines():
        parts = line.split("\t")
        if len(parts) == 4 and parts[0] == side and parts[1] == book:
            removed = True
            continue
        kept.append(line)
    if removed:
        state_path.write_text(
            "".join(f"{line}\n" for line in kept), encoding="utf-8"
        )
    return removed


def parse_book_path(rel_path: str) -> tuple[str, str, str] | None:
    parts = rel_path.split("/", 2)
    if len(parts) < 3:
        return None
    return parts[0], parts[1], parts[2]


def missing_baseline_sides(
    cache_root: Path,
    baseline: dict[str, str],
    sides: tuple[str, ...] = SIDE_DIRECTORIES,
) -> list[str]:
    """返回「缓存里有书、基线里却一条记录都没有」的侧。

    某一侧的清单记录整侧缺失时，`detect_changes` 会把该侧每个文件都判成
    `added`——发布于是把整侧重新打包并重传，内容却没有任何变化。该状态意味着
    基线从未建立，或缓存被 `pull.ps1` 之外的途径整批替换过，必须在发布前修复
    （用 `python tools/manifest.py --update-books` 重建该侧基线）。
    缓存里本来就没有书的侧不算缺失。
    """
    missing: list[str] = []
    for side in sides:
        root = cache_root / side
        if not root.is_dir() or not any(p.is_dir() for p in root.iterdir()):
            continue
        prefix = side + "/"
        if not any(path.startswith(prefix) for path in baseline):
            missing.append(side)
    return missing


def detect_changes(
    current: dict[str, str], baseline: dict[str, str]
) -> dict[str, dict[str, str]]:
    changes: dict[str, dict[str, str]] = {}
    for path, hash_value in current.items():
        parsed = parse_book_path(path)
        if parsed is None:
            continue
        side, book, file_in_book = parsed
        if path not in baseline:
            status = "added"
        elif baseline[path] != hash_value:
            status = "modified"
        else:
            continue
        changes.setdefault(f"{side}/{book}", {})[file_in_book] = status

    for path in baseline.keys() - current.keys():
        parsed = parse_book_path(path)
        if parsed is None:
            continue
        side, book, file_in_book = parsed
        changes.setdefault(f"{side}/{book}", {})[file_in_book] = "deleted"
    return changes


def find_conflicts(
    book_key: str,
    cache_current: dict[str, str],
    epub_current: dict[str, str],
    baseline: dict[str, str],
) -> list[str]:
    """List cache edits that would be lost by an EPUB/ -> cache overwrite.

    A cache-vs-baseline change is not a conflict when EPUB/ already contains
    the same bytes. That happens when a one-off fix was applied to both copies
    without advancing manifest.json first.
    """
    prefix = book_key + "/"
    cache_book = {
        path.removeprefix(prefix): digest
        for path, digest in cache_current.items()
        if path.startswith(prefix)
    }
    epub_book = {
        path.removeprefix(prefix): digest
        for path, digest in epub_current.items()
        if path.startswith(prefix)
    }
    baseline_book = {
        path.removeprefix(prefix): digest
        for path, digest in baseline.items()
        if path.startswith(prefix)
    }
    conflicts: list[str] = []
    for file_in_book in sorted(cache_book.keys() | baseline_book.keys()):
        cache_hash = cache_book.get(file_in_book)
        baseline_hash = baseline_book.get(file_in_book)
        if cache_hash == baseline_hash:
            continue
        if cache_hash == epub_book.get(file_in_book):
            continue
        if baseline_hash is None:
            status = "added"
        elif cache_hash is None:
            status = "deleted"
        else:
            status = "modified"
        suffix = {
            "added": "（缓存有未发布新增）",
            "deleted": "（缓存有未发布删除）",
            "modified": "（缓存有未发布修改）",
        }[status]
        conflicts.append(f"{file_in_book} {suffix}")
    return conflicts


def sync_file_changes(
    source_book_dir: Path,
    destination_book_dir: Path,
    file_changes: dict[str, str],
    *,
    full_mirror: bool = False,
) -> tuple[int, int]:
    """Apply one book's explicit delta from source to destination.

    Missing added/modified sources are errors rather than silent skips, so a
    caller cannot advance its manifest after an incomplete mirror.
    """
    if not source_book_dir.is_dir():
        raise FileNotFoundError(f"源书籍目录不存在: {source_book_dir}")

    if full_mirror:
        if destination_book_dir.is_dir():
            shutil.rmtree(destination_book_dir)
        copied = 0
        for source in source_book_dir.rglob("*"):
            if not source.is_file():
                continue
            if is_extract_artifact(source.relative_to(source_book_dir)):
                continue
            relative = source.relative_to(source_book_dir)
            destination = destination_book_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied += 1
        return copied, 0

    copied = 0
    deleted = 0
    for file_in_book, status in file_changes.items():
        relative = Path(file_in_book)
        destination = destination_book_dir / relative
        if status == "deleted":
            if destination.is_file():
                destination.unlink()
                deleted += 1
            parent = destination.parent
            while (
                parent != destination_book_dir
                and parent.is_dir()
                and not any(parent.iterdir())
            ):
                parent.rmdir()
                parent = parent.parent
            continue

        source = source_book_dir / relative
        if not source.is_file():
            raise FileNotFoundError(f"待同步源文件不存在: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    return copied, deleted


def update_manifest_for_book(
    manifest: dict[str, str], book_key: str, current: dict[str, str]
) -> None:
    prefix = book_key + "/"
    for path in list(manifest):
        if path.startswith(prefix):
            del manifest[path]
    manifest.update(
        (path, hash_value)
        for path, hash_value in current.items()
        if path.startswith(prefix)
    )
