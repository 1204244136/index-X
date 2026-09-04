#!/usr/bin/env python3
"""把日文侧的场景分隔独占 <br/> 补回配对中文文件（只读预览，--apply 才写盘）。

背景：BW 制作源用独占一行的 <br/> 表达段落/场景分隔（旁白↔对话块、视角或时间
跳转）。部分中文出版管线把这些空行丢掉，中文样式又是 `p { margin: 0 }`，于是
同一位置中文渲染为平贴排版，且直接造成中日行数差。按 AGENTS.md「结构元素只要
在制作源中真实存在、仅被某侧制作管线丢失，允许在对应位置补回，属恢复源结构
而非对齐填充」处理。

安全前提（任一不满足即拒绝写入该文件）：
  1. 去掉 <br/> 后，两侧的**行类型序列逐位相等**（h1/h2/img/div/blank/p 都对得上）；
  2. 中文侧不得有日文侧没有的独占 <br/>（避免把中文自有分隔或位置搬错）；
  3. 补完后中文行数必须**恰好等于**日文行数。

另：跳过 MANUAL_ALIGNMENT_HEADERS 与不参与配对的文件；保留中文侧 BOM/换行风格。

用法：
    python tools/restore_cn_scene_breaks.py                      # 全缓存预览
    python tools/restore_cn_scene_breaks.py --book S6_22.06.10    # 指定卷预览
    python tools/restore_cn_scene_breaks.py --book S6_22.06.10 --apply
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
BODY_RE = re.compile(r"<body\b", re.I)
CLOSE_RE = re.compile(r"^\s*</body>", re.I)


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def body_start(lines: list[str]) -> int:
    return next((i for i, line in enumerate(lines) if BODY_RE.search(line)), 2)


def line_kind(line: str) -> str:
    if BR_ONLY.match(line):
        return "br"
    if BLANK.match(line):
        return "blank"
    if CLOSE_RE.match(line):
        return "close"
    low = line.lower()
    if "<h1" in low:
        return "h1"
    if "<h2" in low:
        return "h2"
    if re.search(r"<(?:img|svg)\b", low):
        return "img"
    if low.startswith("<div") or "</div" in low:
        return "div"
    return "p"


def plan(japanese: list[str], chinese: list[str]) -> tuple[list[str] | None, str]:
    """返回（补回后的中文行, 拒绝原因）。成功时原因为空串。"""
    jb = japanese[body_start(japanese) + 1:]
    cb = chinese[body_start(chinese) + 1:]
    jk = [line_kind(l) for l in jb]
    ck = [line_kind(l) for l in cb]
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
    rebuilt = ["<br/>" if k == "br" else None for k in jk]
    it = iter([l for l, k in zip(cb, ck) if k != "br"])
    merged = [next(it) if x is None else x for x in rebuilt]
    if list(it):
        return None, "中文内容行未被完全消费（内部不一致）"
    head = chinese[:body_start(chinese) + 1]
    out = head + merged
    if len(out) != len(japanese):
        return None, f"补回后 {len(out)} 行仍不等于日文 {len(japanese)} 行"
    return out, ""


def collect(cache: Path, only_book: str | None):
    cn_books = {book_id(d.name): d for d in (cache / "chinese-text").iterdir() if d.is_dir()}
    jp_books = {book_id(d.name): d for d in (cache / "japanese-text").iterdir() if d.is_dir()}
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
                header = pairing_header_of(p.name)
                if header and header not in idx:
                    idx[header] = p
        for header in sorted(set(cn_by) & set(jp_by)):
            if header in MANUAL_ALIGNMENT_HEADERS:
                continue
            yield cn_id, header, jp_by[header], cn_by[header]


def main() -> int:
    ap = argparse.ArgumentParser(description="把日文侧场景分隔 <br/> 补回中文侧")
    ap.add_argument("--cache", type=Path, default=Path(".cache/epub-work"))
    ap.add_argument("--book", default=None, help="只处理指定作品号（如 S6_22.06.10）")
    ap.add_argument("--apply", action="store_true", help="写盘（默认只预览）")
    args = ap.parse_args()

    done = skipped = 0
    added = 0
    for cn_id, header, jp_path, cn_path in collect(args.cache, args.book):
        jl, cl = read_lines(jp_path), read_lines(cn_path)
        if len(jl) == len(cl):
            continue  # 行数已等长，交给别的检查
        out, reason = plan(jl, cl)
        if out is None:
            print(f"[跳过] {cn_id} {header}: {reason}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
