#!/usr/bin/env python3
"""把日文侧的场景分隔独占 <br/> 补回配对中文文件（只读预览，--apply 才写盘）。

规范来源是 AGENTS.md；CLI 合同与安全前提见 tools/README.md。
计划由 plan 实现，共享物理行类型与配对例外在 xhtml_structure.py。

用法：
    python tools/restore_cn_scene_breaks.py --jp-root 日文参考目录
    python tools/restore_cn_scene_breaks.py --jp-root 日文参考目录 --book S6_22.06.10 --apply
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from edit_safety import (EditSafetyError, add_content_roots, add_edit_mode,
                         content_roots, require_edit_target)
from xhtml_structure import body_start, iter_content_pairs, line_kind

def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig", errors="strict").splitlines()


def plan(japanese: list[str], chinese: list[str]) -> tuple[list[str] | None, str]:
    """返回（补回后的中文行, 拒绝原因）。成功时原因为空串。"""
    jb = japanese[body_start(japanese) + 1:]
    cb = chinese[body_start(chinese) + 1:]
    jk = [line_kind(line) for line in jb]
    ck = [line_kind(line) for line in cb]
    j_no_br = [k for k in jk if k != "br"]
    c_no_br = [k for k in ck if k != "br"]
    if j_no_br != c_no_br:
        first = next((i for i, (a, b) in enumerate(zip(j_no_br, c_no_br)) if a != b),
                     min(len(j_no_br), len(c_no_br)))
        return None, f"去 br 后行类型序列不同（首个差异 @内容行 {first}）"
    cn_br = ck.count("br")
    jp_br = jk.count("br")
    if cn_br > jp_br:
        return None, f"中文侧已有 {cn_br} 个 br，多于日文侧 {jp_br}，不擅自搬动"
    def br_boundaries(kinds):
        boundaries = {}
        position = 0
        for kind in kinds:
            if kind == "br":
                boundaries[position] = boundaries.get(position, 0) + 1
            else:
                position += 1
        return boundaries
    j_boundaries, c_boundaries = br_boundaries(jk), br_boundaries(ck)
    if any(count > j_boundaries.get(position, 0) for position, count in c_boundaries.items()):
        return None, "中文侧已有 br 在日文侧对应位置不存在，不擅自搬动"
    rebuilt = ["<br/>" if k == "br" else None for k in jk]
    it = iter([line for line, kind in zip(cb, ck) if kind != "br"])
    merged = [next(it) if x is None else x for x in rebuilt]
    if list(it):
        return None, "中文内容行未被完全消费（内部不一致）"
    head = chinese[:body_start(chinese) + 1]
    out = head + merged
    if len(out) != len(japanese):
        return None, f"补回后 {len(out)} 行仍不等于日文 {len(japanese)} 行"
    return out, ""


def collect(cache: Path, only_book: str | None, jp_root: Path | None = None):
    root = cache if jp_root is not None else cache / "chinese-text"
    yield from iter_content_pairs(root, jp_root or cache / "japanese-text", only_book)


def main() -> int:
    ap = argparse.ArgumentParser(description="把日文侧场景分隔 <br/> 补回中文侧")
    add_content_roots(ap, paired=True)
    ap.add_argument("--book", default=None, help="只处理指定作品号（如 S6_22.06.10）")
    add_edit_mode(ap)
    args = ap.parse_args()
    root, jp_root = content_roots(args, ap, paired=True)
    try:
        pairs = list(collect(root, args.book, jp_root))
        if args.apply:
            for _, _, _, path in pairs:
                require_edit_target(path, args.staging)
    except (EditSafetyError, ValueError) as exc:
        ap.error(str(exc))

    done = skipped = 0
    added = 0
    for cn_id, header, jp_path, cn_path in pairs:
        jl, cl = read_lines(jp_path), read_lines(cn_path)
        if len(jl) == len(cl):
            continue  # 行数已等长，交给别的检查
        out, reason = plan(jl, cl)
        if out is None:
            print(f"[跳过] {cn_id} {header}: {reason}")
            skipped += 1
            continue
        try:
            ET.fromstring("\n".join(out))
        except ET.ParseError as exc:
            print(f"[拒绝] {header}: XML 解析失败：{exc}")
            skipped += 1
            continue
        gain = len(out) - len(cl)
        print(f"[补回] {cn_id} {header}: {len(cl)} → {len(out)} 行（+{gain} 个 <br/>）")
        added += gain
        done += 1
        if args.apply:
            raw = cn_path.read_bytes()
            bom = raw.startswith(b"\xef\xbb\xbf")
            sep = "\r\n" if b"\r\n" in raw else "\n"
            text = sep.join(out) + (sep if raw.endswith(b"\n") else "")
            cn_path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    print(f"\n{'已写盘' if args.apply else '预览'}：{done} 个中文文件，补回 {added} 行 <br/>；"
          f"因不满足前提跳过 {skipped} 个")
    return 1 if skipped and args.apply else 0


if __name__ == "__main__":
    raise SystemExit(main())
