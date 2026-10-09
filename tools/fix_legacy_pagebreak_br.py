#!/usr/bin/env python3
"""删除中文归档中「旧合页方法」遗留的独立 <br/> 行（默认预览，--apply 才写盘）。

规范来源是 AGENTS.md；CLI 合同与判定行为见 tools/README.md。
判定由 find_legacy_br 实现，共享物理行类型与配对例外在 xhtml_structure.py。

用法：
    python tools/fix_legacy_pagebreak_br.py --jp-root 日文参考目录
    python tools/fix_legacy_pagebreak_br.py --jp-root 日文参考目录 --book S4_01 --apply
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from edit_safety import (EditSafetyError, add_content_roots, add_edit_mode,
                         content_roots, require_edit_target)
from xhtml_slots import LINE_BODY_FIRST
from xhtml_structure import BR_ONLY, BLANK, PB_RE as PB, body_start, iter_content_pairs, line_kind


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig", errors="strict").splitlines()


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
    jk = [line_kind(x) for x in japanese[body_start(japanese) + 1:]
          if not BR_ONLY.match(x) and not BLANK.match(x)]
    ck = [line_kind(x) for x in chinese[body_start(chinese) + 1:]
          if not BR_ONLY.match(x) and not BLANK.match(x)]
    if jk != ck:
        return []  # Structural drift cannot be repaired by deleting separators.
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
            # 中文侧超出日文侧的部分 = 旧合页遗留；L6 起才算正文，之前的 br 属模板槽位不得删
            for i in cn_run[len(jp_run):]:
                if i + 1 > LINE_BODY_FIRST:
                    doomed.append(i)
        j += 1
        c += 1
    return doomed


def collect(cache: Path, only_book: str | None, jp_root: Path | None = None):
    root = cache if jp_root is not None else cache / "chinese-text"
    jp_root = jp_root or cache / "japanese-text"
    result = []
    for cn_id, h, jp_p, cn_p in iter_content_pairs(root, jp_root, only_book):
        jl, cl = read_lines(jp_p), read_lines(cn_p)
        doomed = find_legacy_br(jl, cl)
        if doomed:
            result.append((cn_id, h, cn_p, jl, cl, doomed))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="删除中文侧旧合页遗留 <br/> 行")
    add_content_roots(ap, paired=True)
    ap.add_argument("--book", default=None, help="只处理指定作品号（如 S4_01）")
    add_edit_mode(ap)
    args = ap.parse_args()
    root, jp_root = content_roots(args, ap, paired=True)
    try:
        items = collect(root, args.book, jp_root)
        if args.apply:
            for item in items:
                require_edit_target(item[2], args.staging)
    except (EditSafetyError, ValueError) as exc:
        ap.error(str(exc))
    total = sum(len(x[5]) for x in items)
    refused = 0
    print(f"候选 {len(items)} 个配对文件，共 {total} 行旧合页 <br/>")
    for cn_id, header, cn_p, jl, cl, doomed in items:
        gap = len(jl) - len(cl)
        # 安全闸：只在「不会删过头」时动手。
        #   候选数 > 行数差 → 该处遗留多于总差，说明别处还缺行，属位置错配，交人工；
        #   候选数 <= 行数差 → 逐个删除，差值只会收窄不会反向。
        if gap >= 0 or len(doomed) > -gap:
            refused += 1
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
        original = cn_p.read_bytes()
        raw = original.decode("utf-8-sig")
        sep = "\r\n" if "\r\n" in raw else "\n"
        doomed_set = set(doomed)
        kept = [cl[k] for k in range(len(cl)) if k not in doomed_set]
        try:
            ET.fromstring("\n".join(kept))
        except ET.ParseError as exc:
            print(f"[拒绝] {header}: XML 解析失败：{exc}")
            refused += 1
            continue
        new_text = sep.join(kept)
        if raw.endswith("\n"):
            new_text += sep
        bom = b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b""
        cn_p.write_bytes(bom + new_text.encode("utf-8"))
    if not args.apply:
        print("\n（预览模式，未写盘；加 --apply 执行）")
    return 1 if refused and args.apply else 0


if __name__ == "__main__":
    raise SystemExit(main())
