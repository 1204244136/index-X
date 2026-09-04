#!/usr/bin/env python3
"""检查中日缓存 XHTML 是否符合统一固定行模板并保持对齐（只读）。

模板（AGENTS.md「中日正文行结构」）：
    1  <?xml …?>
    2  <!DOCTYPE html>
    3  <html …><head>…</head><body…>   ← 可并入篇首图片
    4  <h1>…</h1>                      ← 独占行；无 h1 则空行
    5  <h2>…</h2>                      ← 独占行；无 h2 则空行
    6  <p>正文首行</p>                 ← 永远在第 6 行

检查项：
- 逐文件：L1/L2/L3 头部结构、L4=h1 独占或空、L5=h2 独占或空、L6=正文；
- 正文行原子性：每条物理行只允许一个同级正文块，正文不得与 body/html 闭标签同行；
- 配对文件：总行数一致、h2 位置一致、图片行一致（gaiji/height-2em 字形不计；
  S2_14-02/04/07/10/13 为已确认的文本化图片例外，配对检查整体豁免）；
- 纯图片页/无正文页不适用；仅单侧存在的 EPUB、日文独有包装页不参与检查。

用法：
    python tools/check_alignment.py
    python tools/check_alignment.py --strict
    python tools/check_alignment.py --cache 路径
输出：控制台汇总 + `.cache/epub-work/alignment-check.tsv`
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from alignment_rules import (
    JP_WRAPPER_RE,
    MANUAL_ALIGNMENT_HEADERS,
    NON_PAIR_WORK_IDS,
    TEXTUAL_IMAGE_HEADERS,
    pairing_header_of,
)
from epub_ids import book_id, content_sequence, is_packaging_header, japanese_book_id

TAG_RE = re.compile(r"<[^>]*>")
H_OPEN_RE = re.compile(r"<(h1|h2)\b", re.I)
BODY_RE = re.compile(r"<body\b", re.I)
IMG_RE = re.compile(r"<(?:img|svg)\b|data-image-continuation=", re.I)
BR_LINE_RE = re.compile(r"^\s*<br\s*/>\s*$", re.I)
LIST_WRAP_RE = re.compile(r"^\s*<(ul|ol)\b[^>]*>\s*$", re.I)
FLOW_SIBLING_RE = re.compile(
    r"(?:</(?:p|h[12]|li|ul|ol|blockquote|table|tr|td)>|"
    r"<(?:br|hr)\b[^>]*?/?>)\s*"
    r"<(?:p|h[12]|li|ul|ol|blockquote|table|tr|td|br|hr)\b",
    re.I,
)
CONTENT_BODY_CLOSE_RE = re.compile(
    r"</(?:p|h[12]|li|ul|ol|blockquote|table|tr|td)>\s*"
    r"(?:</div>\s*)*</body>",
    re.I,
)
HEADING_OPEN_RE = re.compile(r"<(?P<tag>h[12])\b[^>]*>", re.I)
HEADING_CONTENT_RE = re.compile(
    r"<(?P<tag>h[12])\b[^>]*>(?P<inner>.*?)</(?P=tag)>", re.I | re.S
)
HEADING_BR_RE = re.compile(r"<br\s*/?>", re.I)
HEADING_BLOCK_WRAP_RE = re.compile(r"<(?:div|p)\b", re.I)

def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def has_body(lines: list[str]) -> bool:
    head_end = next(
        (i for i, line in enumerate(lines, 1) if BODY_RE.search(line)), 0
    )
    return any(
        TAG_RE.sub("", line).strip()
        for i, line in enumerate(lines, 1)
        if i > head_end and not H_OPEN_RE.search(line)
    )


def check_file(lines: list[str], allow_list_wrap_slot: bool = False) -> list[str]:
    """模板逐文件检查，返回问题列表。

    allow_list_wrap_slot=True 时允许第 5 行用 <ul>/<ol> 列表包装占位（中文 Note 等包装页）。
    """
    errs: list[str] = []
    if not has_body(lines):
        return errs  # 纯图片页/无正文页：不适用
    if len(lines) < 6:
        errs.append("行数<6")
        return errs
    if "<?xml" not in lines[0]:
        errs.append("L1 非 XML 声明")
    if "<!DOCTYPE" not in lines[1]:
        errs.append("L2 非 DOCTYPE")
    if "<html" not in lines[2] or "<body" not in lines[2]:
        errs.append("L3 非头部合并行")
    l4, l5, l6 = lines[3], lines[4], lines[5]
    if l4.strip():
        if not re.match(r"^\s*<h1\b", l4) or not re.search(r"</h1>\s*$", l4):
            errs.append("L4 非 h1 独占行")
        if re.search(r"<(?:img|svg)\b", l4, re.I) and "gaiji" not in l4.lower():
            errs.append("L4 含图片")
    if l5.strip():
        is_h2 = re.match(r"^\s*<h2\b", l5) and re.search(r"</h2>\s*$", l5)
        is_list_wrap = allow_list_wrap_slot and bool(LIST_WRAP_RE.match(l5))
        if not is_h2 and not is_list_wrap:
            errs.append("L5 非 h2/列表包装独占行")
    if not l6.strip():
        errs.append("L6 为空")
    for idx, line in ((4, l4), (5, l5)):
        if line.strip() and not re.match(r"^\s*<h[12]\b", line):
            if idx == 5 and allow_list_wrap_slot and LIST_WRAP_RE.match(line):
                continue
            errs.append(f"L{idx} 非标题行却有内容")
    for lineno, line in enumerate(lines[5:], 6):
        if FLOW_SIBLING_RE.search(line):
            errs.append(f"L{lineno} 同一物理行包含多个正文块")
        if CONTENT_BODY_CLOSE_RE.search(line):
            errs.append(f"L{lineno} 正文与 body 闭标签同行")
    for lineno, line in enumerate(lines, 1):
        opening = HEADING_OPEN_RE.search(line)
        if not opening:
            continue
        heading = HEADING_CONTENT_RE.search(line)
        if not heading:
            errs.append(f"L{lineno} h1/h2 未独占一个物理行")
            continue
        if line.strip() != heading.group(0):
            errs.append(f"L{lineno} h1/h2 未独占一个物理行")
        inner = heading.group("inner")
        if HEADING_BR_RE.search(inner):
            errs.append(f"L{lineno} h1/h2 内嵌 <br/>")
        if HEADING_BLOCK_WRAP_RE.search(inner):
            errs.append(f"L{lineno} h1/h2 含 div/p 块级包装")
    return errs


def img_lines(lines: list[str]) -> list[int]:
    return [
        i + 1
        for i, line in enumerate(lines)
        if IMG_RE.search(line)
        and "gaiji" not in line.lower()
        and "height-2em" not in line.lower()
    ]


def h2_lines(lines: list[str]) -> list[int]:
    return [i + 1 for i, line in enumerate(lines) if re.search(r"<h2\b", line)]


def standalone_br_lines(lines: list[str]) -> list[int]:
    return [i + 1 for i, line in enumerate(lines) if BR_LINE_RE.match(line)]


def pair_problems(header: str, japanese: list[str], chinese: list[str]) -> list[str]:
    if header in TEXTUAL_IMAGE_HEADERS:
        # 已确认的文本化图片例外（AGENTS.md）：中文侧把整页图片重排为样式文本行，
        # 行数/h2/图片行/<br/> 位置本就允许不同，配对检查整体豁免。
        return []
    problems: list[str] = []
    if len(japanese) != len(chinese):
        problems.append(f"行数 {len(japanese)} vs {len(chinese)}")
    japanese_h2, chinese_h2 = h2_lines(japanese), h2_lines(chinese)
    if japanese_h2 != chinese_h2:
        problems.append(f"h2 位置 JP{japanese_h2} vs CN{chinese_h2}")
    japanese_images, chinese_images = img_lines(japanese), img_lines(chinese)
    if japanese_images != chinese_images:
        problems.append(f"图片行 JP{japanese_images} vs CN{chinese_images}")
    japanese_br = standalone_br_lines(japanese)
    chinese_br = standalone_br_lines(chinese)
    if japanese_br != chinese_br:
        problems.append(f"<br/> 位置 JP{japanese_br} vs CN{chinese_br}")
    return problems


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="检查中日缓存统一固定行模板与对齐")
    ap.add_argument("--cache", type=Path, default=Path(".cache/epub-work"))
    ap.add_argument(
        "--strict",
        action="store_true",
        help="发现任何问题时返回非零状态，供发布前质量门禁使用",
    )
    args = ap.parse_args()
    cache = args.cache

    cn_books = {book_id(d.name): d for d in (cache / "chinese-text").iterdir() if d.is_dir()}
    jp_books = {book_id(d.name): d for d in (cache / "japanese-text").iterdir() if d.is_dir()}
    pairs = []
    for cn_id, cn_dir in sorted(cn_books.items()):
        if cn_id is None or cn_id in NON_PAIR_WORK_IDS:
            continue
        jp_id = japanese_book_id(cn_id)
        if jp_id in jp_books:
            pairs.append((cn_id, jp_id, cn_dir, jp_books[jp_id]))

    rows: list[list[str]] = []
    bad: list[list[str]] = []
    checked = 0
    seen: set[Path] = set()

    def add(side, book, rel, header, paired, problems, extra=""):
        row = [side, book, rel, header or "-", "是" if paired else "否",
               "; ".join(problems), extra]
        rows.append(row)
        if problems:
            bad.append(row)

    def content_index(paths: list[Path], side: str, book: str) -> dict[str, Path]:
        index: dict[str, Path] = {}
        duplicates: set[str] = set()
        for path in paths:
            header = pairing_header_of(path.name)
            if content_sequence(path.name) == 0:
                add(
                    side,
                    book,
                    str(path.relative_to(cache)),
                    header,
                    False,
                    ["内容序 -00 非法；数字内容序必须从 -01 开始"],
                )
                seen.add(path)
                continue
            if not header or header in duplicates or not has_body(read_lines(path)):
                continue
            if header in index:
                first = index.pop(header)
                duplicates.add(header)
                add(
                    side,
                    book,
                    f"{first.relative_to(cache)} | {path.relative_to(cache)}",
                    header,
                    False,
                    ["同侧重复表头，未自动选择配对文件"],
                )
                continue
            index[header] = path
        return index

    for cn_id, jp_id, cn_dir, jp_dir in pairs:
        cn_all = [p for p in cn_dir.rglob("*.xhtml") if p.name.lower() != "nav.xhtml"]
        jp_all = [p for p in jp_dir.rglob("*.xhtml") if p.name.lower() != "nav.xhtml"]
        cn_by = content_index(cn_all, "中", cn_id)
        jp_by = content_index(jp_all, "日", jp_id)
        for h in sorted(set(jp_by) & set(cn_by)):
            if h in MANUAL_ALIGNMENT_HEADERS:
                add("对", cn_id, "", h, True, [], "特例待判断（人工处理中）")
                continue
            jp_p, cn_p = jp_by[h], cn_by[h]
            jl, cl = read_lines(jp_p), read_lines(cn_p)
            if not has_body(jl) or not has_body(cl):
                continue  # 纯图片页/无正文页
            checked += 1
            for p_, side_, lines_ in ((jp_p, "日", jl), (cn_p, "中", cl)):
                if p_ in seen:
                    continue
                seen.add(p_)
                allow_list = side_ == "中" and is_packaging_header(h)
                add(side_, jp_id if side_ == "日" else cn_id,
                    str(p_.relative_to(cache)), h, True, check_file(lines_, allow_list))
            # 配对检查
            pair_probs = pair_problems(h, jl, cl)
            if pair_probs:
                rel_pair = (
                    f"JP:{jp_p.relative_to(cache)} | CN:{cn_p.relative_to(cache)}"
                )
                add("对", cn_id, rel_pair, h, True, pair_probs, "配对差异")
        # 未配对 CN 正文/包装
        for p in cn_all:
            h = pairing_header_of(p.name)
            if h is None or JP_WRAPPER_RE.match(p.name):
                continue
            if h in cn_by and h in jp_by:
                continue
            if p in seen:
                continue
            lines = read_lines(p)
            if not has_body(lines):
                continue
            seen.add(p)
            checked += 1
            add("中", cn_id, str(p.relative_to(cache)), h, False, check_file(lines, is_packaging_header(h)))
        # 未配对 JP 正文（如 S6 单文件作品）
        for p in jp_all:
            h = pairing_header_of(p.name)
            if h is None or JP_WRAPPER_RE.match(p.name):
                continue
            if h in cn_by and h in jp_by:
                continue
            if p in seen:
                continue
            lines = read_lines(p)
            if not has_body(lines):
                continue
            seen.add(p)
            checked += 1
            add("日", jp_id, str(p.relative_to(cache)), h, False, check_file(lines))

    tsv = cache / "alignment-check.tsv"
    with tsv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["侧", "书", "文件", "表头", "配对", "问题", "备注"])
        w.writerows(rows)
    print(f"已验证正文文件：{checked}；问题记录：{len(bad)}")
    print(f"报告：{tsv}")
    for r in bad:
        print(f"  [{r[0]}] {r[1]} | {r[2].split(chr(92))[-1]} | {r[5]}")
    return 1 if args.strict and bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
