#!/usr/bin/env python3
"""Shared path-safety helpers for archive extraction and cache scans."""
from __future__ import annotations

from pathlib import Path, PurePosixPath


EXTRACT_DIR_PREFIX = ".extract-"


class UnsafeArchivePath(ValueError):
    """Raised when a ZIP member cannot be extracted under the destination."""


def is_extract_artifact(path: Path | str, *, root: Path | None = None) -> bool:
    """Return whether any relative path component is an internal .extract-* item."""
    candidate = Path(path)
    if root is not None:
        try:
            candidate = candidate.relative_to(root)
        except ValueError:
            pass
    return any(
        part.casefold().startswith(EXTRACT_DIR_PREFIX)
        for part in candidate.parts
    )


def validate_archive_member_name(member_name: str) -> PurePosixPath:
    """Validate one ZIP member name and return its normalized POSIX path."""
    if not member_name:
        raise UnsafeArchivePath("ZIP 条目名为空")
    if "\x00" in member_name:
        raise UnsafeArchivePath("ZIP 条目名包含 NUL")
    if member_name.startswith(("/", "\\")):
        raise UnsafeArchivePath("ZIP 条目使用绝对路径")
    if "\\" in member_name:
        raise UnsafeArchivePath("ZIP 条目包含反斜杠")

    is_directory = member_name.endswith("/")
    raw_name = member_name[:-1] if is_directory else member_name
    raw_parts = raw_name.split("/")
    if not raw_name or any(part in ("", ".", "..") for part in raw_parts):
        raise UnsafeArchivePath("ZIP 条目包含空路径段或 ..")
    if any(":" in part for part in raw_parts):
        raise UnsafeArchivePath("ZIP 条目包含冒号或盘符")
    return PurePosixPath(raw_name)


def archive_member_destination(root: Path, member_name: str) -> Path:
    """Resolve a safe ZIP member destination under root."""
    member = validate_archive_member_name(member_name)
    root_resolved = root.resolve()
    destination = root_resolved.joinpath(*member.parts).resolve()
    try:
        destination.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafeArchivePath("ZIP 条目越过输出目录") from exc
    return destination
