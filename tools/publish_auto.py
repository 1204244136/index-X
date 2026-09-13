#!/usr/bin/env python3
"""统一发布入口：判别改动出现在哪一处，再选择对应的发布方向。

三份副本各有固定角色（见 AGENTS.md「数据流与编辑边界」），对应三个发布方向：

- 流程 A：OneDrive 有外部更新 -> 解压回缓存并同步 EPUB/（pull.ps1 -SyncToEpub，不打包上传）
- 流程 B：缓存有未发布修改   -> 打包上传 OneDrive + 同步 EPUB/（publish.py）
- 流程 C：EPUB/ 有改动       -> 打包上传 OneDrive + 增量覆盖缓存（publish_epub.py）

本工具与 manifest.json 基线比对，判断改动只出现在哪一处，再调用上述既有工具，
因此日常只需记住这一条命令。判定口径：

- 只有一侧有改动时直接按该侧方向发布；两侧改动的书互不相交时两个方向都会执行。
- 同一本书在缓存与 EPUB/ 两侧都有改动时默认停止，不猜测方向；用 --from 决定以哪一侧为准。
- OneDrive 的 .epub 与 pull-state.tsv 不一致（外部更新）时报告并提示流程 A；
  若这本同时还存在缓存未发布修改，视为副本已分叉，同样停止并交人工决定。

Usage:
    python tools/publish_auto.py                      # 自动判别并发布
    python tools/publish_auto.py --dry-run            # 只预览方向、书籍与文件差异
    python tools/publish_auto.py --from epub          # 冲突书以 EPUB/ 为准（流程 C）
    python tools/publish_auto.py --from onedrive      # 以 OneDrive 为准（流程 A）
    python tools/publish_auto.py --side chinese --pattern "*S1_01*"
"""

from __future__ import annotations

import argparse
import fnmatch
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from manifest import load_manifest, scan_cache  # noqa: E402
from publish_epub import scan_epub  # noqa: E402
from sync_core import (  # noqa: E402
    ONEDRIVE_DEFAULTS,
    PULL_STATE_FILENAME,
    SIDE_DIRECTORIES,
    SIDE_LABELS,
    STATUS_LABELS,
    UNIX_TO_DOTNET_TICKS_OFFSET,
    detect_changes,
    missing_baseline_sides,
)

REPO_ROOT = TOOLS_DIR.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "epub-work"
DEFAULT_EPUB = REPO_ROOT / "EPUB"

SIDE_MAP = {"chinese": "chinese-text", "japanese": "japanese-text"}
DIRECTION_LABELS = {
    "A": "流程 A：OneDrive -> 缓存 + EPUB/",
    "B": "流程 B：缓存 -> EPUB/ + OneDrive",
    "C": "流程 C：EPUB/ -> OneDrive + 缓存",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="统一发布入口：判别改动位置并选择发布方向。",
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--epub", type=Path, default=DEFAULT_EPUB)
    parser.add_argument(
        "--from",
        dest="source",
        choices=("auto", "cache", "epub", "onedrive"),
        default="auto",
        help="冲突时以哪一份副本为准（默认 auto：冲突即停止并报告）",
    )
    parser.add_argument(
        "--side", choices=("all", "chinese", "japanese"), default="all"
    )
    parser.add_argument(
        "--pattern", default="*", help="按书名筛选（不区分大小写的通配符）"
    )
    parser.add_argument(
        "--only-books",
        default="",
        help="逗号分隔的 'side/book'，只处理这些书",
    )
    parser.add_argument("--dry-run", action="store_true", help="只预览，不执行任何写入")
    parser.add_argument("--no-upload", action="store_true", help="跳过 OneDrive 上传")
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略清单基线，按 --from 指定的方向全量重做",
    )
    parser.add_argument(
        "--overwrite-cache",
        action="store_true",
        help="流程 C / 流程 A 允许覆盖缓存中尚未发布的修改",
    )
    parser.add_argument(
        "--chinese-onedrive", type=Path, default=ONEDRIVE_DEFAULTS["chinese-text"]
    )
    parser.add_argument(
        "--japanese-onedrive", type=Path, default=ONEDRIVE_DEFAULTS["japanese-text"]
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------- 筛选与展示


def in_scope(book_key: str, args: argparse.Namespace) -> bool:
    """与 --side / --pattern / --only-books 完全一致地判断一本书是否在本次范围内。"""
    side, book = book_key.split("/", 1)
    if args.side != "all" and side != SIDE_MAP[args.side]:
        return False
    if not fnmatch.fnmatch(book.casefold(), args.pattern.casefold()):
        return False
    if args.only_books and book_key not in parse_only_books(args.only_books):
        return False
    return True


def parse_only_books(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def summarize(file_changes: dict[str, str]) -> str:
    counts = {"added": 0, "modified": 0, "deleted": 0}
    for status in file_changes.values():
        counts[status] += 1
    return "、".join(
        f"{STATUS_LABELS[status]} {counts[status]}"
        for status in ("added", "modified", "deleted")
        if counts[status]
    )


def describe_book(book_key: str) -> str:
    side, book = book_key.split("/", 1)
    return f"{SIDE_LABELS[side]} {book}"


def print_deltas(title: str, changes: dict[str, dict[str, str]], verbose: bool) -> None:
    if not changes:
        print(f"  {title}：无改动")
        return
    print(f"  {title}：{len(changes)} 本")
    for book_key in sorted(changes):
        print(f"    {describe_book(book_key)}：{summarize(changes[book_key])}")
        if verbose:
            for file_in_book, status in sorted(changes[book_key].items()):
                print(f"      {STATUS_LABELS[status]}: {file_in_book}")


def display_command(cmd: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in cmd)


def newline_only_diffs(
    epub_changes: dict[str, dict[str, str]], epub_root: Path, cache: Path
) -> list[str]:
    """找出「EPUB/ 与缓存只差换行符」的文件（疑似归档检出的换行转换）。

    manifest.json 按字节哈希比较，Windows 上的 core.autocrlf 等设置会让归档目录
    相对基线整体变成 CRLF，从而被误判成真实编辑并触发反向覆盖缓存。
    """
    suspects: list[str] = []
    for book_key, files in epub_changes.items():
        side, book = book_key.split("/", 1)
        for file_in_book, status in sorted(files.items()):
            if status == "deleted":
                continue
            epub_file = epub_root / book / file_in_book
            cache_file = cache / side / book / file_in_book
            if not epub_file.is_file() or not cache_file.is_file():
                continue
            epub_bytes = epub_file.read_bytes()
            cache_bytes = cache_file.read_bytes()
            if epub_bytes == cache_bytes:
                continue
            if epub_bytes.replace(b"\r\n", b"\n") == cache_bytes.replace(b"\r\n", b"\n"):
                suspects.append(f"{book_key}/{file_in_book}")
    return suspects


# ------------------------------------------------------------ OneDrive 侧检测


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


def detect_onedrive_drift(
    cache_root: Path,
    source_dirs: dict[str, Path | None],
    args: argparse.Namespace,
) -> tuple[list[str], list[str]]:
    """比对 pull-state.tsv 与 OneDrive 的 .epub，返回（有外部更新的书, 说明行）。

    与 pull.ps1 使用同一判定：OneDrive 文件的 mtime ticks 与 size 与状态记录不同，
    即视为该侧有外部更新（pull.ps1 下次运行会重新解压这本书）。
    """
    records = read_pull_state(cache_root)
    drifted: list[str] = []
    notes: list[str] = []
    for side in SIDE_DIRECTORIES:
        source = source_dirs.get(side)
        if source is None:
            continue
        if not source.is_dir():
            notes.append(f"未找到 OneDrive 目录（{SIDE_LABELS[side]}）：{source}，跳过流程 A 检测")
            continue
        for epub_file in sorted(source.glob("*.epub")):
            book_key = f"{side}/{epub_file.stem}"
            if not in_scope(book_key, args):
                continue
            stat = epub_file.stat()
            ticks = str(stat.st_mtime_ns // 100 + UNIX_TO_DOTNET_TICKS_OFFSET)
            record = records.get(book_key)
            if record is None:
                drifted.append(book_key)
            elif record != (ticks, str(stat.st_size)):
                drifted.append(book_key)
    return drifted, notes


# -------------------------------------------------------------------- 命令构造


def find_powershell() -> str | None:
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def build_pull_command(
    args: argparse.Namespace, cache: Path, epub_root: Path, dry_run: bool
) -> list[str] | None:
    host = find_powershell()
    if host is None:
        return None
    cmd = [
        host,
        "-NoProfile",
        "-File",
        str(TOOLS_DIR / "pull.ps1"),
        "-SyncToEpub",
        "-CacheDirectory",
        str(cache),
        "-EpubDirectory",
        str(epub_root),
    ]
    if args.side != "all":
        cmd += ["-Side", args.side]
    if args.pattern != "*":
        cmd += ["-Pattern", args.pattern]
    if args.force:
        cmd.append("-Force")
    if dry_run:
        cmd.append("-WhatIf")
    if args.chinese_onedrive.resolve() != ONEDRIVE_DEFAULTS["chinese-text"].resolve():
        cmd += ["-ChineseSourceDirectory", str(args.chinese_onedrive)]
    if args.japanese_onedrive.resolve() != ONEDRIVE_DEFAULTS["japanese-text"].resolve():
        cmd += ["-JapaneseSourceDirectory", str(args.japanese_onedrive)]
    return cmd


def build_publish_command(
    args: argparse.Namespace, cache: Path, epub_root: Path, books: list[str]
) -> list[str]:
    cmd = [
        sys.executable,
        str(TOOLS_DIR / "publish.py"),
        "--cache",
        str(cache),
        "--epub",
        str(epub_root),
        "--only-books",
        ",".join(books),
    ]
    if args.no_upload:
        cmd.append("--no-upload")
    if args.force:
        cmd.append("--force")
    return cmd


def build_reverse_command(
    args: argparse.Namespace, cache: Path, epub_root: Path, books: list[str]
) -> list[str]:
    cmd = [
        sys.executable,
        str(TOOLS_DIR / "publish_epub.py"),
        "--cache",
        str(cache),
        "--epub",
        str(epub_root),
        "--only-books",
        ",".join(books),
    ]
    if args.no_upload:
        cmd.append("--no-upload")
    if args.force:
        cmd.append("--force")
    if args.overwrite_cache:
        cmd.append("--overwrite-cache")
    return cmd


def run_command(cmd: list[str]) -> int:
    print(f"\n$ {display_command(cmd)}")
    return subprocess.run(cmd, check=False).returncode


# ---------------------------------------------------------------------- 主流程


def report_conflict(conflicts: list[str], cache_changes, epub_changes) -> None:
    print("\n== 冲突：同一本书在缓存与 EPUB/ 两侧都有改动 ==")
    for book_key in conflicts:
        print(f"  {describe_book(book_key)}")
        print(f"    缓存：{summarize(cache_changes.get(book_key, {}))}")
        print(f"    EPUB/：{summarize(epub_changes.get(book_key, {}))}")
    print("\n  两侧内容不一致，未自动选择方向。请确认以哪一侧为准后重跑：")
    print("    以缓存为准  ：python tools/publish_auto.py --from cache")
    print(
        "    以 EPUB/ 为准：python tools/publish_auto.py --from epub --overwrite-cache"
        "（会丢弃缓存中这些书的未发布修改）"
    )


def report_diverged(diverged: list[str]) -> None:
    print("\n== OneDrive 与本地对同一本书都有改动 ==")
    for book_key in diverged:
        print(f"  {describe_book(book_key)}")
    print(
        "\n  这些书的 OneDrive .epub 已被外部更新（pull-state 不一致），"
        "本地也有未发布修改；两份副本已分叉，未自动选择方向。请确认以哪一份为准后重跑："
    )
    print(
        "    以本地为准：python tools/publish_auto.py --from cache"
        "（发布本地内容，覆盖 OneDrive 上的外部更新）"
    )
    print(
        "    以 OneDrive 为准：python tools/publish_auto.py --from onedrive --overwrite-cache"
        "（会丢弃缓存中这些书的未发布修改）"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cache = args.cache.resolve()
    epub_root = args.epub.resolve()

    if args.force and args.source == "auto":
        print(
            "错误: --force 需要配合 --from 指定方向（cache / epub / onedrive）；"
            "忽略基线后没有可判别的改动位置。",
            file=sys.stderr,
        )
        return 1
    if not cache.is_dir():
        print(f"错误: 缓存目录不存在: {cache}", file=sys.stderr)
        return 1
    if not epub_root.is_dir():
        print(f"错误: EPUB 目录不存在: {epub_root}", file=sys.stderr)
        return 1

    source_dirs: dict[str, Path | None] = {
        "chinese-text": args.chinese_onedrive,
        "japanese-text": args.japanese_onedrive,
    }

    # 清单基线：改动判别的唯一参照
    baseline = load_manifest(cache)
    if baseline is None:
        if args.force:
            print("警告: 未找到清单，--force 模式按方向全量重做。")
            baseline = {}
        else:
            print(
                "错误: 未找到清单。请先运行 ./tools/pull.ps1，或使用 --force --from 指定方向。",
                file=sys.stderr,
            )
            return 1
    elif args.force:
        print("警告: --force 模式，忽略已有清单。")
        baseline = {}

    # 与 publish.py / publish_epub.py 同一项前置检查：某一侧基线整侧缺失时，
    # 该侧全部文件都会被判成新增。这里先拦，避免把整侧误判成一个方向的改动。
    scope_sides = SIDE_DIRECTORIES if args.side == "all" else (SIDE_MAP[args.side],)
    if baseline:
        missing = missing_baseline_sides(cache, baseline, scope_sides)
        if missing:
            labels = "、".join(f"{SIDE_LABELS[m]}（{m}）" for m in missing)
            print(
                f"错误: 清单基线缺少整侧记录: {labels}。"
                "该侧全部文件都会被判为新增，无法判别真实改动位置。",
                file=sys.stderr,
            )
            print(
                "  修复: python tools/manifest.py --cache "
                f"{cache} --update-books "
                + " ".join(f"{m}/<书籍名>" for m in missing)
                + "（确认该侧缓存已是已发布状态后再重建基线）",
                file=sys.stderr,
            )
            print("  若确实要整侧重发，使用 --force --from cache。", file=sys.stderr)
            return 1

    print("扫描缓存与 EPUB/ ...")
    cache_current = scan_cache(cache)
    epub_current = scan_epub(epub_root)
    print(f"  缓存 {len(cache_current)} 个文件 | EPUB/ {len(epub_current)} 个文件"
          f" | 清单基线 {len(baseline)} 个文件")

    if args.force:
        return run_forced(args, cache, epub_root, cache_current, epub_current)

    cache_changes = {
        key: value
        for key, value in detect_changes(cache_current, baseline).items()
        if in_scope(key, args)
    }
    # EPUB/ 只镜像中文书；日文条目不在反向发布范围内。
    epub_changes = {
        key: value
        for key, value in detect_changes(epub_current, baseline).items()
        if key.startswith("chinese-text/") and in_scope(key, args)
    }

    drifted, drift_notes = detect_onedrive_drift(cache, source_dirs, args)
    conflicts = sorted(set(cache_changes) & set(epub_changes))
    # 分叉：OneDrive 的 .epub 被外部更新，而本地对同一本书也有未发布改动
    diverged = sorted(set(drifted) & (set(cache_changes) | set(epub_changes)))

    print("\n== 改动判别 ==")
    print_deltas("缓存有未发布修改", cache_changes, args.dry_run)
    print_deltas("EPUB/ 有改动", epub_changes, args.dry_run)
    if drifted:
        print(f"  OneDrive 有外部更新（pull-state 不一致）：{len(drifted)} 本")
        for book_key in drifted:
            print(f"    {describe_book(book_key)}")
    else:
        print("  OneDrive 有外部更新（pull-state 不一致）：无")
    for note in drift_notes:
        print(f"  提示: {note}")

    suspects = newline_only_diffs(epub_changes, epub_root, cache)
    if suspects:
        print(
            f"\n  警告: EPUB/ 的 {len(suspects)} 个变化文件与缓存只差换行符（CRLF/LF），"
            "可能是归档检出时的换行转换而非真实编辑："
        )
        for item in suspects[:5]:
            print(f"    {item}")
        if len(suspects) > 5:
            print(f"    …（另有 {len(suspects) - 5} 个）")
        print("  若只是换行转换，请先还原归档（git restore EPUB/）再重跑。")

    # 冲突：同一本书两侧都有改动，方向必须由用户决定
    if conflicts and args.source == "auto":
        report_conflict(conflicts, cache_changes, epub_changes)
        return 1
    if conflicts and args.source == "epub" and not args.overwrite_cache:
        print(
            "\n错误: 已指定以 EPUB/ 为准，但这些书的缓存里还有未发布修改，"
            "反向覆盖会丢失它们。",
            file=sys.stderr,
        )
        for book_key in conflicts:
            print(f"  {describe_book(book_key)}", file=sys.stderr)
        print(
            "  确认要丢弃缓存修改时加上 --overwrite-cache；"
            "或先用 --from cache 把缓存修改发布出去。",
            file=sys.stderr,
        )
        return 1

    # 分叉：OneDrive 与本地对同一本书都有改动
    if diverged and args.source == "auto":
        report_diverged(diverged)
        return 1
    if diverged and args.source == "onedrive" and not args.overwrite_cache:
        report_diverged(diverged)
        return 1

    if conflicts:
        if args.source == "cache":
            print(
                f"\n  冲突书共 {len(conflicts)} 本，以缓存为准：缓存内容将覆盖 EPUB/ 中对应文件。"
            )
        elif args.source == "epub":
            print(
                f"\n  冲突书共 {len(conflicts)} 本，以 EPUB/ 为准：EPUB/ 内容将覆盖缓存（含未发布修改）。"
            )

    # 方向分配：非冲突书按检测结果各自归位，冲突书按 --from 决定归属。
    # --from cache：冲突书只走流程 B（缓存覆盖 EPUB/），不再反向覆盖缓存。
    # --from epub ：冲突书只走流程 C（EPUB/ 覆盖缓存，需 --overwrite-cache）。
    cache_books = set(cache_changes)
    epub_books = set(epub_changes)
    if args.source == "cache":
        epub_books -= set(conflicts)
    elif args.source == "epub":
        cache_books -= set(conflicts)
    elif args.source == "onedrive":
        if cache_books or epub_books:
            print(
                f"\n  注意: --from onedrive 只执行流程 A，本地 {len(cache_books)} 本缓存改动与 "
                f"{len(epub_books)} 本 EPUB/ 改动本次不发布，仍保持未发布状态。"
            )
        cache_books, epub_books = set(), set()
    cache_books, epub_books = sorted(cache_books), sorted(epub_books)

    # 流程 A 只在 auto / --from onedrive 下执行：显式指定本地方向时不做隐式的反向拉取。
    commands: list[tuple[str, list[str]]] = []
    run_pull = bool(drifted) and args.source in ("auto", "onedrive")
    if run_pull and args.only_books:
        # pull.ps1 以整本书为单位解压，没有单本参数；用 --only-books 时宁可不拉，也不越界写入。
        run_pull = False
        print(
            "\n  提示: --only-books 无法约束流程 A（pull.ps1 按整本书解压），已跳过 OneDrive 拉取；"
            "如需拉回，请用 ./tools/pull.ps1 -SyncToEpub -Pattern 指定范围。"
        )
    if run_pull:
        pull_command = build_pull_command(args, cache, epub_root, args.dry_run)
        if pull_command is None:
            print(
                "错误: 未找到 pwsh/powershell，无法执行流程 A；"
                "请手动运行 ./tools/pull.ps1 -SyncToEpub。",
                file=sys.stderr,
            )
            return 1
        commands.append(("A", pull_command))
    if cache_books:
        commands.append(("B", build_publish_command(args, cache, epub_root, cache_books)))
    if epub_books:
        commands.append(
            ("C", build_reverse_command(args, cache, epub_root, epub_books))
        )

    if drifted and args.source in ("cache", "epub"):
        print(
            f"\n  提示: OneDrive 有 {len(drifted)} 本外部更新。"
            "先发布本地改动，再运行 ./tools/pull.ps1 -SyncToEpub 拉回；"
            "或直接用 python tools/publish_auto.py --from onedrive。"
        )

    if not commands:
        if drifted:
            print(
                f"\n没有检测到需要发布的本地改动；OneDrive 有 {len(drifted)} 本外部更新，"
                "用 --from onedrive 执行流程 A 拉回。"
            )
        else:
            print("\n没有检测到需要发布的内容。")
        return 0

    print("\n== 发布计划 ==")
    for direction, cmd in commands:
        scope = "OneDrive 外部更新" if direction == "A" else "本地改动"
        print(f"  [{DIRECTION_LABELS[direction]}] {scope}")

    if args.dry_run:
        for _, cmd in commands:
            print(f"\n[dry-run] 将执行:\n  $ {display_command(cmd)}")
        print("\n[dry-run] 未执行任何操作。")
        return 0

    print("\n== 发布 ==")
    failed: list[str] = []
    for direction, cmd in commands:
        if run_command(cmd) != 0:
            failed.append(DIRECTION_LABELS[direction])
            print(f"  [失败] {DIRECTION_LABELS[direction]}", file=sys.stderr)
            break

    print("\n== 完成 ==")
    if failed:
        print(f"  失败: {'、'.join(failed)}")
        return 1
    print("  全部方向执行成功。")
    return 0


def run_forced(
    args: argparse.Namespace,
    cache: Path,
    epub_root: Path,
    cache_current: dict[str, str],
    epub_current: dict[str, str],
) -> int:
    """--force：忽略基线，只按 --from 指定方向全量重做。"""
    def books_of(paths: dict[str, str]) -> list[str]:
        keys = {path.split("/", 2)[0] + "/" + path.split("/", 2)[1] for path in paths
                if len(path.split("/", 2)) == 3}
        return sorted(key for key in keys if in_scope(key, args))

    if args.source == "cache":
        books = books_of(cache_current)
        if not books:
            print("\n没有检测到需要发布的内容（范围内没有书籍）。")
            return 0
        commands = [("B", build_publish_command(args, cache, epub_root, books))]
    elif args.source == "epub":
        books = books_of({k: v for k, v in epub_current.items()
                          if k.startswith("chinese-text/")})
        if not books:
            print("\n没有检测到需要发布的内容（范围内没有书籍）。")
            return 0
        commands = [("C", build_reverse_command(args, cache, epub_root, books))]
    else:
        pull_command = build_pull_command(args, cache, epub_root, args.dry_run)
        if pull_command is None:
            print(
                "错误: 未找到 pwsh/powershell，无法执行流程 A；"
                "请手动运行 ./tools/pull.ps1 -SyncToEpub -Force。",
                file=sys.stderr,
            )
            return 1
        commands = [("A", pull_command)]

    print("\n== 发布计划 ==")
    for direction, _ in commands:
        print(f"  [{DIRECTION_LABELS[direction]}] 全量重做（--force）")
    if args.dry_run:
        for _, cmd in commands:
            print(f"\n[dry-run] 将执行:\n  $ {display_command(cmd)}")
        print("\n[dry-run] 未执行任何操作。")
        return 0

    print("\n== 发布 ==")
    for direction, cmd in commands:
        if run_command(cmd) != 0:
            print(f"  [失败] {DIRECTION_LABELS[direction]}", file=sys.stderr)
            return 1
    print("\n== 完成 ==\n  全部方向执行成功。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
