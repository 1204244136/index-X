#!/usr/bin/env python3
"""删除中文缓存中「旧合页方法」遗留的独立 <br/> 行（只读预览，--apply 才写盘）。

背景：中文侧早期用独立 `<br/>` 行标记 BookWalker 分页边界；现行方案改由日文侧
在边界段落上注入 `class="pb"`（见 merge_bw_pages.add_class_pb），该 `<br/>` 行
已成为多余的物理行，直接造成中日行数差。

判定（必须同时满足，缺一即保留）：
  1. 中文侧该行是「独占一行的 `<br/>`」（无其他内容）；
  2. 与它紧邻的上一对中日已配对正文行中，日文行带 class="pb"；
  3. 该 pb 边界尚未被本单元内更早的中文 `<br/>` 消费（一处边界只删一行）；
  4. 行号 > 6，不破坏 L1-L6 固定模板。

正文场景分隔 `<br/>`（日文侧无 pb 边界）一律不处理。

用法：
    python tools/fix_legacy_pagebreak_br.py                 # 全缓存预览
    python tools/fix_legacy_pagebreak_br.py --book S4_01    # 指定卷预览
    python tools/fix_legacy_pagebreak_br.py --book S4_01 --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alignment_rules import (  # noqa: E402
    MANUAL_ALIGNMENT_HEADERS,
    NON_PAIR_WORK_IDS,
    pairing_header_of,
)
from epub_ids import book_id, japanese_book_id  # noqa: E402

BR_ONLY = re.compile(r"^\s*<br\s*/>\s*$", re.I)
BLANK = re.compile(r"^\s*$")
PB = re.compile(r'class="[^"]*\bpb\b', re.I)
BODY_RE = re.compile(r"<body\b", re.I)
FIRST_BODY_LINE = 6  # L6 必须是正文，其前的 br 属模板槽位，不得删


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def body_start(lines: list[str]) -> int:
    return next((i for i, l in enumerate(lines) if BODY_RE.search(l)), 2)


def _br_run(lines: list[str], start: int) -> list[int]:
    """从 start 起（跳过模板空行占位）统计连续的独占 <br/> 行号。"""
    out: list[int] = []
    i = start
    while i < len(lines):
        if BLANK.match(lines[i]):
            i += 1
            continue
        if BR_ONLY.match(lines[i]):
            out.append(i)
            i += 1
            continue
        break
    return out


def find_legacy_br(japanese: list[str], chinese: list[str]) -> list[int]:
    """返回中文侧应删除的 0-based 行号列表。

    中文侧的旧合页写法是紧跟在「该页最后一段」之后的 1~2 个独占 <br/>；
    同一边界在日文侧由 class="pb" 承载，不占行。因此对每个 class="pb" 边界，
    比较两侧的独占 <br/> 连段：两侧数量相同说明都是真场景分隔（一行都不删），
    中文多出来的那几行才是旧合页遗留。
    """
    j, c = body_start(japanese) + 1, body_start(chinese) + 1
    doomed: list[int] = []
    while j < len(japanese) and c < len(chinese):
        x, y = japanese[j], chinese[c]
        if BR_ONLY.match(x) or BLANK.match(x):
            j += 1
            continue
        if BR_ONLY.match(y) or BLANK.match(y):
            c += 1
            continue
        # 两侧都是内容行 → 一对已配对正文行；杂散行在前面各自跳过
        if PB.search(x):
            jp_run = _br_run(japanese, j + 1)
            cn_run = _br_run(chinese, c + 1)
            # 中文侧超出日文侧的部分 = 旧合页遗留
            for i in cn_run[len(jp_run):]:
                if i + 1 > FIRST_BODY_LINE:
                    doomed.append(i)
        j += 1
        c += 1
    return doomed


def collect(cache: Path, only_book: str | None):
    cn_books = {book_id(d.name): d for d in (cache / "chinese-text").iterdir() if d.is_dir()}
    jp_books = {book_id(d.name): d for d in (cache / "japanese-text").iterdir() if d.is_dir()}
    result = []
    for cn_id, cn_dir in sorted(cn_books.items()):
        if cn_id is None or cn_id in NON_PAIR_WORK_IDS:
            continue
        if only_book and cn_id.upper() != only_book.upper():
            continue
        jp_dir = jp_books.get(japanese_book_id(cn_id))
        if jp_dir is None:
            continue
        cn_by, jp_by = {}, {}
        for d, idx in ((cn_dir, cn_by), (jp_dir, jp_by)):
            for p in d.rglob("*.xhtml"):
                if p.name.lower() == "nav.xhtml":
                    continue
                h = pairing_header_of(p.name)
                if h and h not in idx:
                    idx[h] = p
        for h in sorted(set(cn_by) & set(jp_by)):
            if h in MANUAL_ALIGNMENT_HEADERS:
                continue
            jp_p, cn_p = jp_by[h], cn_by[h]
            jl, cl = read_lines(jp_p), read_lines(cn_p)
            doomed = find_legacy_br(jl, cl)
            if doomed:
                result.append((cn_id, h, cn_p, jl, cl, doomed))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="删除中文侧旧合页遗留 <br/> 行")
    ap.add_argument("--cache", type=Path, default=Path(".cache/epub-work"))
    ap.add_argument("--book", default=None, help="只处理指定作品号（如 S4_01）")
    ap.add_argument("--apply", action="store_true", help="写盘（默认只预览）")
    args = ap.parse_args()

    items = collect(args.cache, args.book)
    total = sum(len(x[5]) for x in items)
    print(f"候选 {len(items)} 个配对文件，共 {total} 行旧合页 <br/>")
    for cn_id, header, cn_p, jl, cl, doomed in items:
        gap = len(jl) - len(cl)
        # 安全闸：只在「不会删过头」时动手。
        #   候选数 > 行数差 → 该处遗留多于总差，说明别处还缺行，属位置错配，交人工；
        #   候选数 <= 行数差 → 逐个删除，差值只会收窄不会反向。
        if gap >= 0 or len(doomed) > -gap:
            print(f"\n[{cn_id}] {header}  行数 JP {len(jl)} / CN {len(cl)}（差 {gap:+d}）"
                  f" → 候选 {len(doomed)} 行，**不删除**"
                  f"（{'日文侧本来就更长' if gap >= 0 else '遗留数超过总差，别处尚缺行'}，需人工确认）")
            continue
        after = gap + len(doomed)
        mark = "对齐" if after == 0 else f"残差 {after:+d}"
        print(f"\n[{cn_id}] {header}  行数 JP {len(jl)} / CN {len(cl)}（差 {gap:+d}）"
              f" → 删 {len(doomed)} 行后 {mark}")
        for i in doomed:
            prev = next((k for k in range(i - 1, -1, -1) if not BLANK.match(cl[k])), None)
            ctx = cl[prev][:60] if prev is not None else "-"
            nxt = cl[i + 1][:60] if i + 1 < len(cl) else "-"
            print(f"    L{i+1:>5}: <br/>   上文「{ctx}」 / 下文「{nxt}」")
        if not args.apply:
            continue
        raw = cn_p.read_bytes().decode("utf-8")
        sep = "\r\n" if "\r\n" in raw else "\n"
        doomed_set = set(doomed)
        kept = [cl[k] for k in range(len(cl)) if k not in doomed_set]
        new_text = sep.join(kept)
        if raw.endswith("\n"):
            new_text += sep
        cn_p.write_bytes(new_text.encode("utf-8"))
    if not args.apply:
        print("\n（预览模式，未写盘；加 --apply 执行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
