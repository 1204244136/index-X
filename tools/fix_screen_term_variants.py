#!/usr/bin/env python3
"""统一中文缓存中「大画面」术语的异译写法（默认预览，--apply 才写盘）。

背景：日文原文对飞船腹部、百货公司外墙上那块广告屏写作
`<ruby>大画面<rt>エキシビジヨン</rt></ruby>`（exhibition）。中文版在**有注音**的
16 处已逐点统一为 `<ruby>大屏幕<rt>Exhibition</rt></ruby>`；但在日文未注音的叙述句
里，中文出现了照搬日文汉字的「大画面」，以及「巨大荧幕 / 大银幕 / 巨大屏幕 /
巨型屏幕 / 巨大画面 / 大型显示屏 / 液晶屏幕 / 显示器」等异译，同一物件在中文里
有十余种写法。

本工具只处理**日文「大画面」锚点范围内**的异译，逐行精确改写：

  * 不做全局模糊替换。映射逐条显式记录（文件、行号、原串、新串），每条都要求
    「文件唯一、行号有效、原串在该行恰好出现一次」，任一条不满足即整次预检不写盘。
  * 只改中文缓存；日文侧与原作排版（含 `<ruby>` 注音）一律不动。
  * 不改变行数与行结构，因此中日行对齐不受影响。
  * 普通叙述里的「屏幕 / 画面」（电视画面、显示器、手机屏等）不在范围内，
    不会被本工具触碰。

用法：
    python tools/fix_screen_term_variants.py             # 预览
    python tools/fix_screen_term_variants.py --apply     # 写入中文缓存
    python tools/fix_screen_term_variants.py --cache 自定义/chinese-text
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_CACHE = Path(".cache/epub-work/chinese-text")

# (中文文件基名, 行号, 原串, 新串, 说明)
# 行号 = 该文件中的逻辑行号（1 起），与 check_alignment.py 的口径一致。
ENTRIES: list[tuple[str, int, str, str, str]] = [
    # —— 照搬日文汉字「大画面」，未翻译 ——
    ("S1_10-01_Chapter5.xhtml", 322,
     "飞船腹部的大画面上正在播放天气预报", "飞船腹部的大屏幕上正在播放天气预报",
     "照搬日文汉字"),
    ("S1_12-02_Chapter1.xhtml", 222,
     "百货公司墙壁上的大画面所播放的天气预报", "百货公司墙壁上的大屏幕所播放的天气预报",
     "照搬日文汉字"),
    ("S1_13-05_Chapter8.xhtml", 174,
     "那是装置在百货公司侧面的大画面", "那是装置在百货公司侧面的大屏幕",
     "照搬日文汉字"),
    ("S1_13-05_Chapter8.xhtml", 189,
     "风慢慢地将目光转向大画面", "风慢慢地将目光转向大屏幕",
     "照搬日文汉字"),
    ("S1_13-05_Chapter8.xhtml", 191,
     "轰声响起，大画面随着火花破裂四散", "轰声响起，大屏幕随着火花破裂四散",
     "照搬日文汉字"),
    # —— 「荧幕 / 银幕」异体字 ——
    ("S1_08-02_Chapter1.xhtml", 105,
     "飞船的腹侧上有个巨大荧幕", "飞船的腹侧上有个大屏幕",
     "异体字「巨大荧幕」"),
    ("S4_01-06_Chapter2.xhtml", 50,
     "飞船腹部的大荧幕播报着", "飞船腹部的大屏幕播报着",
     "异体字「大荧幕」"),
    ("S4_03-05_Chapter2.xhtml", 171,
     "一起用大荧幕痛痛快快地看", "一起用大屏幕痛痛快快地看",
     "异体字「大荧幕」"),
    ("S2_05-08_Chapter4.xhtml", 149,
     "飞船大银幕上", "飞船大屏幕上",
     "异体字「大银幕」"),
    # —— 缺「大」或多「巨大」的修饰变体 ——
    ("S3_02-09_Chapter4.xhtml", 403,
     "在那颗流星侧面的液晶屏幕上", "在那颗流星侧面的液晶大屏幕上",
     "缺「大」：液晶屏幕"),
    ("S5_01_03-05_Chapter4.xhtml", 129,
     "飞艇上的屏幕也坏掉了", "飞艇上的大屏幕也坏掉了",
     "缺「大」：屏幕"),
    ("S2_06-03_Chapter5.xhtml", 535,
     "设在空中飞船上的巨大屏幕", "设在空中飞船上的大屏幕",
     "冗余修饰「巨大屏幕」"),
    ("S3_05-03_Chapter1.xhtml", 121,
     "腹部上的巨大画面进行着这样的报道", "腹部上的大屏幕进行着这样的报道",
     "冗余修饰「巨大画面」"),
    ("S3_08-04_Chapter1.xhtml", 144,
     "装载巨型屏幕的飞船", "装载大屏幕的飞船",
     "冗余修饰「巨型屏幕」"),
    ("S4_02-06_Chapter2.xhtml", 38,
     "侧面有着巨大屏幕的飞艇", "侧面有着大屏幕的飞艇",
     "冗余修饰「巨大屏幕」"),
    # —— 比喻语境：整片风景＝一块屏幕（日文「一枚の巨大画面」）——
    ("S2_11-07_Chapter3.xhtml", 138,
     "眼前所见是一幅巨大的屏幕", "眼前所见是一块大屏幕",
     "量词与修饰归一"),
    # —— 同句内三词并用（显示屏 / 屏幕）——
    ("S5_01_03-05_Chapter4.xhtml", 125,
     "挂着的大型显示屏出了问题", "挂着的大屏幕出了问题",
     "同句内「大型显示屏」"),
    ("S5_01_03-05_Chapter4.xhtml", 125,
     "整块显示屏突然就黑屏了", "整块屏幕突然就黑屏了",
     "同句内「显示屏」与「屏幕」并用"),
]


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
        description="统一中文缓存中「大画面」术语的异译写法（默认预览）")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="中文缓存根目录")
    ap.add_argument("--apply", action="store_true", help="写入中文缓存；缺省只预览")
    args = ap.parse_args(argv)

    cache = Path(args.cache)
    if not cache.is_dir():
        print(f"[错误] 中文缓存目录不存在: {cache}", file=sys.stderr)
        return 2

    # 1) 定位并按文件归集
    by_file: dict[Path, list[tuple[int, str, str, str]]] = {}
    for name, ln, old, new, note in ENTRIES:
        path = find_file(cache, name)
        if path is None:
            print(f"[错误] 未找到唯一的中文正文文件: {name}", file=sys.stderr)
            return 2
        by_file.setdefault(path, []).append((ln, old, new, note))

    # 2) 预检 + 生成新内容（全部通过才写盘）
    planned: list[tuple[Path, list[str], bool]] = []
    applied = skipped = 0
    failed = False
    for path, items in by_file.items():
        raw = path.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        lines = raw.decode("utf-8-sig").splitlines(keepends=True)
        for ln, old, new, note in items:
            if ln < 1 or ln > len(lines):
                print(f"[失败] {path.name} L{ln}: 行号越界（共 {len(lines)} 行）", file=sys.stderr)
                failed = True
                continue
            body, eol = split_eol(lines[ln - 1])
            if body.count(old) == 1:
                lines[ln - 1] = body.replace(old, new) + eol
                applied += 1
                print(f"[改写] {path.name} L{ln}  {old} → {new}   ({note})")
            elif body.count(old) == 0 and new in body:
                skipped += 1
                print(f"[跳过] {path.name} L{ln}  已统一为「{new}」")
            else:
                print(f"[失败] {path.name} L{ln}: 原串出现 {body.count(old)} 次，"
                      f"期望 1 次：{old}", file=sys.stderr)
                failed = True
        planned.append((path, lines, has_bom))

    if failed:
        print("\n预检未通过，未写入任何文件。", file=sys.stderr)
        return 1

    print(f"\n待改写 {applied} 处，已统一 {skipped} 处。")
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
