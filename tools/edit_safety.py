"""CLI guards for explicit EPUB edits and temporary staging work."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EPUB = REPO_ROOT / "EPUB"


class EditSafetyError(ValueError):
    """The requested content write is outside the permitted edit boundary."""


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _forbidden(path: Path) -> bool:
    if _inside(path, REPO_ROOT / ".cache") or _inside(path, (REPO_ROOT / ".cache").resolve()):
        return True
    # Check both configured locations and folder names, including OneDrive - Org.
    if any(part.casefold() == "onedrive" or part.casefold().startswith("onedrive - ")
           for part in path.parts):
        return True
    for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        location = os.environ.get(name)
        if location and _inside(path, Path(location).resolve()):
            return True
    return False


def require_edit_target(path: Path | str, staging: bool = False,
                        epub_root: Path | str | None = None) -> Path:
    """Resolve a CLI write target; EPUB is the default, staging is explicit.

    Both the supplied path and resolved destination are checked so aliases,
    symlinks and Windows junctions cannot turn cache/OneDrive into edit targets.
    Pure transformation helpers deliberately do not call this CLI guard.
    """
    supplied = Path(path).absolute()
    resolved = supplied.resolve()
    if _forbidden(supplied) or _forbidden(resolved):
        raise EditSafetyError(f"禁止写入缓存或 OneDrive：{path}")
    allowed = Path(epub_root).resolve() if epub_root is not None else DEFAULT_EPUB.resolve()
    if not staging and not _inside(resolved, allowed):
        raise EditSafetyError(f"内容写入必须位于 {allowed}；临时处理请显式使用 --staging：{path}")
    if staging and resolved == REPO_ROOT:
        raise EditSafetyError("--staging 必须指向明确的临时目录，不能使用仓库根目录")
    return resolved


def add_edit_mode(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="执行写入；默认只读预览")
    mode.add_argument("--dry-run", action="store_true", help="显式只读预览（与 --apply 互斥）")
    parser.add_argument("--staging", action="store_true",
                        help="允许显式临时处理目录；仍禁止缓存与 OneDrive 写入")


def add_content_roots(parser: argparse.ArgumentParser, paired: bool = False) -> None:
    parser.add_argument("--root", type=Path, default=None, help="中文归档根目录（默认 EPUB/）")
    parser.add_argument("--cache", type=Path, default=None,
                        help="兼容旧参数：单侧为目标根；配对为显式 staging 的中日根")
    if paired:
        parser.add_argument("--jp-root", type=Path, default=None, help="日文只读参考根目录（必须显式指定）")


def content_roots(args: argparse.Namespace, parser: argparse.ArgumentParser,
                  paired: bool = False) -> tuple[Path, Path | None]:
    if args.root is not None and args.cache is not None:
        parser.error("--root 与兼容参数 --cache 不能同时使用")
    if args.staging and args.root is None and args.cache is None:
        parser.error("--staging 必须显式指定 --root 或 --cache 临时目录")
    if paired and args.cache is not None:
        if not args.staging:
            parser.error("配对 --cache 只用于 --staging 显式临时目录；归档请用 --root 与 --jp-root")
        if args.jp_root is not None:
            parser.error("--cache 与 --jp-root 不能同时使用")
        root, jp_root = args.cache / "chinese-text", args.cache / "japanese-text"
    else:
        root = args.root or args.cache or DEFAULT_EPUB
        jp_root = args.jp_root if paired else None
    if not root.is_dir():
        parser.error(f"中文目录不存在：{root}")
    if paired and (jp_root is None or not jp_root.is_dir()):
        parser.error("必须用 --jp-root 指定存在的日文只读参考目录")
    if args.apply:
        try:
            require_edit_target(root, args.staging)
        except EditSafetyError as exc:
            parser.error(str(exc))
    return root, jp_root
