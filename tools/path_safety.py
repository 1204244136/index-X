#!/usr/bin/env python3
"""Shared path-safety helpers for extraction, cache scans, and reports."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from collections.abc import Iterable


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


def require_report_target(
    path: Path | str,
    *,
    protected_files: Iterable[Path | str] = (),
    protected_dirs: Iterable[Path | str] = (),
) -> Path:
    """Validate a report path without writes; return its resolved destination.

    Reports must be outside input/output trees and cannot alias protected files.
    Both supplied paths and resolved symlink targets participate in the checks.
    """
    supplied = Path(path).absolute()
    try:
        target = supplied.resolve()
        if target.is_dir():
            raise ValueError(f"报告目标是目录：{path}")
        for item in protected_files:
            source = Path(item).resolve()
            if target == source or (target.exists() and source.exists() and target.samefile(source)):
                raise ValueError(f"报告不能覆盖输入文件：{item}")
        for item in protected_dirs:
            directory = Path(item).absolute()
            resolved = directory.resolve()
            if (supplied.is_relative_to(directory) or target.is_relative_to(resolved)
                    or directory.is_relative_to(supplied) or resolved.is_relative_to(target)):
                raise ValueError(f"报告必须位于受保护目录之外：{item}")
        for parent in target.parents:
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"报告父路径不是目录：{parent}")
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"无法检查报告路径 {path}：{exc}") from exc
    return target
