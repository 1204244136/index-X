#!/usr/bin/env python3
"""统一中文缓存中「科学サイド／魔術サイド」的中文术语为「阵营」（默认预览，--apply 才写盘）。

背景：日文原文用**注音**区分两层——

  * 「サイド」全库 973 处裸写（仅 3 处带注音），是术语，指科学与魔法的两大阵营；
  * 「側」全部带指示代词注音（こちら／あちら／むこう／こっち／そちら／かれら／
    おれたち／あなたがた／がわ），是指示代词，指"这一方／那边"。

中文版却把术语层「サイド」译成了 阵营／势力／侧／方／世界 等多种写法，并跨卷成段漂移
（旧约 10–18 卷"势力"段、创约 8–11 卷"侧"段等）。本工具把术语层统一到覆盖率最高的
「阵营」，不动指示层。

本工具只处理**日文「サイド」锚点范围内**的术语异译，逐行精确改写：

  * 不做全局模糊替换。映射逐条显式记录在 `tools/side_term_overrides.json`
    （中文文件基名、行号、原串、新串），每条都要求「文件唯一、行号有效、原串在该行
    恰好出现一次」，任一条不满足即整次预检不写盘。同一行同一术语出现多次时，
    原串带上下文以保持唯一（如「一半的科学势力＋魔法」）。
  * 日文同一行若写的是汉字「側」，中文「X侧」视为对应「側」而**保留**，不在表中。
  * 带「符号 + ruby 注音」的风格化行（创约 11 卷 CRC 口吻等）默认跳过，需 `--include-style`。
  * 只改中文缓存；日文侧与原作排版一律不动。
  * 不改变行数与行结构，因此中日行对齐不受影响。

用法：
    python tools/fix_side_term_variants.py                  # 预览
    python tools/fix_side_term_variants.py --apply          # 写入中文缓存
    python tools/fix_side_term_variants.py --include-style  # 一并处理风格化行
    python tools/fix_side_term_variants.py --cache 自定义/chinese-text
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "epub-work" / "chinese-text"
DEFAULT_TABLE = Path(__file__).resolve().parent / "side_term_overrides.json"


def load_entries(table: Path) -> list[dict]:
    if not table.is_file():
        raise SystemExit(f"[错误] 映射表不存在: {table}")
    data = json.loads(table.read_text(encoding="utf-8"))
    entries = data["entries"] if isinstance(data, dict) else data
    return list(entries)


def find_file(cache: Path, name: str) -> Path | None:
    """在缓存中定位唯一的正文文件（限定在 Text 目录内）。"""
    if not cache.is_dir():
        return None
    hits = [p for p in cache.rglob(name) if p.is_file() and p.parent.name == "Text"]
    return hits[0] if len(hits) == 1 else None


def split_eol(line: str) -> tuple[str, str]:
    body = line.rstrip("\r\n")
    return body, line[len(body):]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="统一中文缓存中「科学サイド／魔術サイド」的中文术语为「阵营」（默认预览）")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="中文缓存根目录")
    ap.add_argument("--table", default=str(DEFAULT_TABLE), help="映射表 JSON 路径")
    ap.add_argument("--include-style", action="store_true",
                    help="一并处理「符号 + ruby 注音」的风格化行（默认跳过）")
    ap.add_argument("--apply", action="store_true", help="写入中文缓存；缺省只预览")
    args = ap.parse_args(argv)

    cache = Path(args.cache)
    if not cache.is_dir():
        print(f"[错误] 中文缓存目录不存在: {cache}", file=sys.stderr)
        return 2

    entries = load_entries(Path(args.table))
    skipped_style = [e for e in entries if e.get("style_sensitive") and not args.include_style]
    active = [e for e in entries if not (e.get("style_sensitive") and not args.include_style)]

    # 1) 定位并按文件归集
    by_file: dict[Path, list[dict]] = {}
    for e in active:
        path = find_file(cache, e["file"])
        if path is None:
            print(f"[错误] 未找到唯一的中文正文文件: {e['file']}", file=sys.stderr)
            return 2
        by_file.setdefault(path, []).append(e)

    # 2) 预检 + 生成新内容（全部通过才写盘）
    planned: list[tuple[Path, list[str], bool]] = []
    applied = skipped = 0
    failed = False
    for path, items in sorted(by_file.items(), key=lambda kv: kv[0].name):
        raw = path.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        lines = raw.decode("utf-8-sig").splitlines(keepends=True)
        for e in sorted(items, key=lambda x: x["line"]):
            ln, old, new = e["line"], e["old"], e["new"]
            if ln < 1 or ln > len(lines):
                print(f"[失败] {path.name} L{ln}: 行号越界（共 {len(lines)} 行）", file=sys.stderr)
                failed = True
                continue
            body, eol = split_eol(lines[ln - 1])
            if body.count(old) == 1:
                lines[ln - 1] = body.replace(old, new) + eol
                applied += 1
                print(f"[改写] {path.name} L{ln}  {old} → {new}")
            elif body.count(old) == 0 and new in body:
                skipped += 1
                print(f"[跳过] {path.name} L{ln}  已统一")
            else:
                print(f"[失败] {path.name} L{ln}: 原串出现 {body.count(old)} 次，期望 1 次：{old}",
                      file=sys.stderr)
                failed = True
        planned.append((path, lines, has_bom))

    if failed:
        print("\n预检未通过，未写入任何文件。", file=sys.stderr)
        return 1

    print(f"\n待改写 {applied} 处，已统一 {skipped} 处，风格化跳过 {len(skipped_style)} 处，"
          f"涉及 {len(planned)} 个文件。")
    if not args.apply:
        print("（预览模式，未写盘。确认后加 --apply）")
        return 0

    # 3) 写盘：保留原 BOM 与换行风格
    for path, lines, has_bom in planned:
        data = "".join(lines).encode("utf-8")
        if has_bom:
            data = b"\xef\xbb\xbf" + data
        path.write_bytes(data)
    print(f"已写入 {len(planned)} 个文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
