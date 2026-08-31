#!/usr/bin/env python3
"""按统一固定行模板规范化本地 EPUB 缓存（配对批量处理模式）

⚠️ 注意：本工具用于中日配对批量处理，依赖配对关系。
对于单文件处理或不依赖配对的场景，请使用 normalize_single.py。

模板（AGENTS.md「中日正文行结构」）：
    1  <?xml …?>
    2  <!DOCTYPE html>
    3  <html …><head>…</head><body…>   ← 可并入篇首图片（body 开头）
    4  <h1>…</h1>                      ← 独占行；无 h1 则空行
    5  <h2>…</h2>                      ← 独占行；无 h2 则空行
    6  <p>正文首行</p>                 ← 永远在第 6 行

处理内容：
- 头部标签跨行折叠；填充 <br/> 删除；跨行 h1/h2 折叠为单行；
- 日文 p 型标题（font-1em10/30、裸 <p>あとがき/译注 等）→ <h1>；
- 数字小节 <p>N</p> → <h2>；start-3em/start-5em 包装内嵌标题按语义重建为 <h1>；
- 中文包装页（Information/Note/Introduction 等）头部行内 h1 提取到第 4 行；
- 篇首图片并入第 3 行头部行；SP 篇目日文侧补 h1（标题取自日文原版目录）；
- 中日配对文件两侧行数必须一致：某侧无法套用模板或会造成行数不对称时跳过并报告。

用法：
    python tools/normalize_paired.py            # 应用规范化（默认）
    python tools/normalize_paired.py --dry-run  # 只预览
    python tools/normalize_paired.py --cache 路径
"""
from __future__ import annotations

import argparse
from pathlib import Path

from alignment_rules import (
    JP_H1_BY_HEADER,
    JP_WRAPPER_RE,
    MANUAL_ALIGNMENT_HEADERS,
    NON_PAIR_WORK_IDS,
    pairing_header_of,
)
from epub_ids import book_id, japanese_book_id
from xhtml_template import has_body, read_lines, rebuild, write_lines

# S1_25-STIYL_MAGNUS：已手工完成模板对齐（补 h1/h2、修复缺 <body> 的 XML、
#   中日 2019 行一致且 check_alignment 通过）；规范化重建可能破坏手工对齐，保持跳过。


def main() -> int:
    ap = argparse.ArgumentParser(description="按统一固定行模板规范化缓存 XHTML")
    ap.add_argument("--cache", type=Path, default=Path(".cache/epub-work"))
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写文件")
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

    jobs: list[tuple[Path, str | None]] = []
    judged: list[tuple[str, str]] = []

    def content_index(entries: list[tuple[Path, str | None]], side: str) -> dict[str, Path]:
        index: dict[str, Path] = {}
        duplicates: set[str] = set()
        for path, header in entries:
            if not header or not has_body(path) or header in duplicates:
                continue
            if header in index:
                first = index.pop(header)
                duplicates.add(header)
                judged.append((header, f"{side}同侧重复表头: {first.name} / {path.name}"))
                continue
            index[header] = path
        return index

    for cn_id, jp_id, cn_dir, jp_dir in pairs:
        cn_all = [(p, pairing_header_of(p.name)) for p in cn_dir.rglob("*.xhtml")
                  if p.name.lower() != "nav.xhtml"]
        jp_all = [(p, pairing_header_of(p.name)) for p in jp_dir.rglob("*.xhtml")
                  if p.name.lower() != "nav.xhtml"]
        cn_by = content_index(cn_all, "CN")
        jp_by = content_index(jp_all, "JP")
        for h in sorted(set(jp_by) & set(cn_by)):
            if h in MANUAL_ALIGNMENT_HEADERS:
                judged.append((h, "内容级特例"))
                continue
            if not has_body(jp_by[h]) or not has_body(cn_by[h]):
                continue
            jp_h1 = JP_H1_BY_HEADER.get(h)
            rj = rebuild(jp_by[h], jp_h1)
            rc = rebuild(cn_by[h])
            if rj[0] is None or rc[0] is None:
                judged.append((h, f"JP:{rj[1]} / CN:{rc[1]}"))
                continue
            if len(rj[0]) != len(rc[0]):
                judged.append((h, f"行数不对称 {len(rj[0])} vs {len(rc[0])}"))
                continue
            jobs.append((jp_by[h], jp_h1))
            jobs.append((cn_by[h], None))
        for p, h in cn_all:
            if h in cn_by and h in jp_by:
                continue
            if h is None or JP_WRAPPER_RE.match(p.name):
                continue
            if not has_body(p):
                continue
            r = rebuild(p)
            if r[0] is None:
                judged.append((h, f"CN独:{r[1]}"))
                continue
            jobs.append((p, None))

    print(f"待规范化文件：{len(jobs)}；跳过（待判断）：{len(judged)}")
    for h, why in judged:
        print(f"  跳过 {h}: {why}")
    if args.dry_run:
        print("（--dry-run，未写文件）")
        return 0
    changed = 0
    for p, jp_h1 in jobs:
        new, _ = rebuild(p, jp_h1)
        if new is None:
            continue
        lines, bom, crlf = read_lines(p)
        if len(new) == len(lines) and new == lines:
            continue
        write_lines(p, new, bom, crlf)
        changed += 1
    print(f"已改写：{changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
