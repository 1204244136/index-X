#!/usr/bin/env python3
"""Pure change detection, tree mirroring and pull-state helpers."""
from __future__ import annotations

import shutil
from pathlib import Path


STATUS_LABELS = {"added": "新增", "modified": "修改", "deleted": "删除"}
PULL_STATE_FILENAME = "pull-state.tsv"
UNIX_TO_DOTNET_TICKS_OFFSET = 621355968000000000
ONEDRIVE_DEFAULTS = {
    "chinese-text": Path.home() / "OneDrive" / "某系列" / "X系列" / "EPUB",
    "japanese-text": Path.home() / "OneDrive" / "某系列" / "日文原文",
}


def update_pull_state_record(
    cache_root: Path, book_key: str, mtime_ticks: int, size: int
) -> None:
    state_path = cache_root / PULL_STATE_FILENAME
    records: dict[str, str] = {}
    if state_path.is_file():
        for line in state_path.read_text(encoding="utf-8-sig").splitlines():
            parts = line.split("\t")
            if len(parts) == 4:
                records[f"{parts[0]}\t{parts[1]}"] = f"{parts[2]}\t{parts[3]}"
    records[book_key.replace("/", "\t", 1)] = f"{mtime_ticks}\t{size}"
    state_path.write_text(
        "".join(f"{key}\t{value}\n" for key, value in sorted(records.items())),
        encoding="utf-8",
    )


def parse_book_path(rel_path: str) -> tuple[str, str, str] | None:
    parts = rel_path.split("/", 2)
    if len(parts) < 3:
        return None
    return parts[0], parts[1], parts[2]


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
            if not source.is_file() or ".extract-" in source.name:
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
