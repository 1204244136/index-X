#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校对复核的原文查证工具（skill 附带，复核时反复使用；不是针对某次任务的一次性脚本）。

配套 `.agents/skills/proofread-review/SKILL.md` §六。解决复核时三个易错点：
中日目录结构不同、文件内不逐行对齐（要按关键字检索）、`epub_audit.text_of` 不剥 `<rt>`
（带注音的词会被拆成「魔術 まじゆつ」而检索不到）。

用法：

    # 日文：某作品某内容序里含关键词的行及上下文（纯文本、已剥注音）
    python lookup_source.py jp S3_01 07 火花 -C 2

    # 日文：列出该作品全部内容序文件（确认 NN 与实际文件对应）
    python lookup_source.py jp S3_01 --list

    # 中文：某文件某一行的纯文本（核对译文现状）
    python lookup_source.py cn S3_01-07_Chapter3.xhtml --line 56

    # 中文：在某个 EPUB 文件里按关键词检索
    python lookup_source.py cn S3_01-07_Chapter3.xhtml --grep "小货车|旅行车"

约定：日文工作源在 `.cache/epub-work/japanese-text/`，中文归档在 `EPUB/`；
`[S3_01]` 这类目录名含方括号，**不能用 glob**（方括号会被当字符类），本脚本用 pathlib 遍历。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]  # .agents/skills/proofread-review/references/ -> 仓库根
sys.path.insert(0, str(REPO / "tools"))
from epub_audit import text_of  # noqa: E402  复用既有剥离口径，不重复实现

JP_ROOT = REPO / ".cache" / "epub-work" / "japanese-text"
CN_ROOT = REPO / "EPUB"


def find_book(root: Path, work: str) -> Path:
    if not root.is_dir():
        sys.exit(f"目录不存在：{root}（日文侧先跑 tools/pull.ps1）")
    hits = [d for d in sorted(root.iterdir()) if d.is_dir() and f"[{work}]" in d.name]
    if len(hits) != 1:
        sys.exit(f"作品 [{work}] 命中 {len(hits)} 个目录：{[d.name for d in hits]}")
    return hits[0]


def line_texts(path: Path) -> list[str]:
    """逐行转纯文本：先剥 <rt>/<rp> 注音，再用 epub_audit.text_of 剥标签解实体。"""
    raw = path.read_text(encoding="utf-8", errors="ignore")
    stripped = re.sub(r"<(rt|rp)\b[^>]*>.*?</\1>", "", raw, flags=re.S | re.I)
    return [text_of(ln.encode("utf-8")) for ln in stripped.split("\n")]


def jp_targets(book_dir: Path, work: str, seq: str) -> list[Path]:
    pattern = re.compile(rf"^{re.escape(work)}-{re.escape(seq)}(?!\d)")
    return [p for p in sorted(book_dir.rglob("*.xhtml")) if pattern.match(p.name)]


def show_jp(args) -> int:
    book_dir = find_book(JP_ROOT, args.work)
    if args.list:
        for p in sorted(book_dir.rglob("*.xhtml")):
            print(p.relative_to(book_dir))
        return 0
    if not (args.seq and args.keyword):
        sys.exit("jp 模式需要：<作品号> <内容序> <关键词>，或用 --list")
    targets = jp_targets(book_dir, args.work, args.seq)
    if not targets:
        sys.exit(f"[{args.work}] 下没有内容序 {args.seq} 的日文文件")
    total = 0
    for path in targets:
        lines = line_texts(path)
        hits = [i for i, t in enumerate(lines) if args.keyword in t]
        if not hits:
            continue
        print(f"\n=== {path.relative_to(REPO)}（{len(lines)} 行）")
        shown: set[int] = set()
        for i in hits:
            for j in range(max(0, i - args.context), min(len(lines), i + args.context + 1)):
                if j in shown:
                    continue
                shown.add(j)
                mark = ">" if j in hits else " "
                print(f"{mark} {j + 1:5d}: {lines[j]}")
            print("  ---")
            total += 1
    if not total:
        print(f"[{args.work}-{args.seq}] 未命中「{args.keyword}」（已剥注音；试试更短的关键词）")
    return 0 if total else 1


def show_cn(args) -> int:
    hits = [p for p in CN_ROOT.rglob(args.name)] if CN_ROOT.is_dir() else []
    if len(hits) != 1:
        sys.exit(f"中文文件 {args.name} 命中 {len(hits)} 个：{[str(p) for p in hits]}")
    path = hits[0]
    lines = line_texts(path)
    print(f"=== {path.relative_to(REPO)}（{len(lines)} 行）")
    if args.line:
        if not 1 <= args.line <= len(lines):
            sys.exit(f"行号越界：{args.line}（共 {len(lines)} 行）")
        print(f"> {args.line:5d}: {lines[args.line - 1]}")
    if args.grep:
        pattern = re.compile(args.grep)
        for i, t in enumerate(lines):
            if pattern.search(t):
                print(f"> {i + 1:5d}: {t}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="校对复核的原文查证（临时工具）")
    sub = p.add_subparsers(dest="mode", required=True)

    jp = sub.add_parser("jp", help="查日文工作源")
    jp.add_argument("work", help="作品号，如 S3_01、S5_01_03、S6_14.09.10")
    jp.add_argument("seq", nargs="?", help="内容序，如 07（或 --list 时省略）")
    jp.add_argument("keyword", nargs="?", help="检索关键词")
    jp.add_argument("-C", "--context", type=int, default=1, help="上下文行数（默认 1）")
    jp.add_argument("--list", action="store_true", help="列出该作品全部 XHTML")

    cn = sub.add_parser("cn", help="查中文归档")
    cn.add_argument("name", help="文件名，如 S3_01-07_Chapter3.xhtml")
    cn.add_argument("--line", type=int, help="打印该行纯文本")
    cn.add_argument("--grep", help="按正则检索")

    args = p.parse_args()
    return show_jp(args) if args.mode == "jp" else show_cn(args)


if __name__ == "__main__":
    sys.exit(main())
