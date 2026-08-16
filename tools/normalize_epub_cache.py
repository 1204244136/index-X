#!/usr/bin/env python3
"""按统一固定行模板规范化本地 EPUB 缓存，不触碰版本化的 EPUB/ 源。

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
    python tools/normalize_epub_cache.py            # 应用规范化（默认）
    python tools/normalize_epub_cache.py --dry-run  # 只预览
    python tools/normalize_epub_cache.py --cache 路径
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

PACKAGING_SUFFIX = ("cover", "back_cover", "illustrations", "information",
                    "introduction", "note", "special")
BOOK_EXCLUSIONS = {"S6_24.12.10"}           # 两侧非同一作品（画集 vs SS）
JUDGE_PAIRS = {"S1_25-STIYL_MAGNUS"}  # 内容级特例，需人工处理
# S1_25-STIYL_MAGNUS：已手工完成模板对齐（补 h1/h2、修复缺 <body> 的 XML、
#   中日 2019 行一致且 check_alignment 通过）；规范化重建可能破坏手工对齐，保持跳过。
JP_WRAPPER_RE = re.compile(
    r"^(p-|navigation-documents|Anotherworld|S\d+_\d+-(?:p-|navigation))", re.I)
# SP 篇目日文侧补 h1：标题取自日文原版目录
JP_H1_MAP = {
    "S1_25-UHARU_KAZARI": "初春飾利",
    "S1_25-KAMIJOU_TOUMA": "上条当麻",
    "S1_25-MARK_SPACE": "マーク＝スペース",
}

TAG_RE = re.compile(r"<[^>]*>")
H1_RE = re.compile(r"<h1\b[^>]*>.*?</h1>", re.I | re.S)
H2_RE = re.compile(r"<h2\b[^>]*>.*?</h2>", re.I | re.S)
H_OPEN_RE = re.compile(r"<(h1|h2)\b", re.I)
BODY_RE = re.compile(r"<body\b", re.I)
IMG_ELEM_RE = re.compile(r"<p\b[^>]*>\s*<(?:img|svg)\b[^>]*/?>\s*</p>|"
                         r"<(?:img|svg)\b[^>]*/?>", re.I)
P_TITLE_RE = re.compile(
    r'^\s*<p\b[^>]*class="[^"]*font-1em(?:10|30)[^"]*"[^>]*>(.*?)</p>\s*$',
    re.I | re.S)
P_SPAN_TITLE_RE = re.compile(
    r'^\s*<p\b[^>]*>\s*<span\b[^>]*class="[^"]*font-1em(?:10|30)[^"]*"[^>]*>(.*?)</span>\s*</p>\s*$',
    re.I | re.S)
DIV_P_TITLE_RE = re.compile(
    r'^\s*<div\b[^>]*class="([^"]*font-1em(?:10|30)[^"]*)"[^>]*>\s*<p\b[^>]*>(.*?)</p>\s*</div>\s*$',
    re.I | re.S)
PLAIN_TITLE_RE = re.compile(
    r'^\s*<p\b[^>]*>\s*[　\s]*(?:あとがき|序章|序|プロローグ|エピローグ|目次|译注)[　\s]*</p>\s*$', re.I)
NUM_P_RE = re.compile(r'^\s*<p\b[^>]*>\s*[　\s]*[0-9０-９]+\s*</p>\s*$')
EMBED_RE = re.compile(
    r'<p\b([^>]*)>(.*?)<h1\b([^>]*)>(.*?)</h1>(.*?)</p>', re.I | re.S)

HEADER_PATTERNS = [
    re.compile(r"(S\d+_\d+(?:_\d+)?-\d+)", re.I),
    re.compile(r"(S\d+_\d+_\d+-[A-Za-z][A-Za-z0-9_]*)", re.I),
    re.compile(r"(S\d+_\d+-[A-Za-z][A-Za-z0-9_]*)", re.I),
    re.compile(r"(S6_\d+\.\d+\.\d+-(?:\d+|[A-Za-z][A-Za-z0-9_]*))", re.I),
    re.compile(r"(S6_\d+\.\d+\.\d+)", re.I),
]
BOOK_RE = re.compile(r"\[(S\d+_\d+(?:_\d+)?|S6_\d+\.\d+\.\d+)\]")


def header_of(name: str) -> str | None:
    for pat in HEADER_PATTERNS:
        m = pat.search(name)
        if m:
            h = m.group(1)
            if h.rsplit("-", 1)[-1].lower().endswith("_p"):
                h = h[: -2]
            return h.upper()
    return None


def is_packaging(h: str | None) -> bool:
    return bool(h) and h.rsplit("-", 1)[-1].lower() in PACKAGING_SUFFIX


def book_id(name: str) -> str | None:
    m = BOOK_RE.match(name)
    return m.group(1) if m else None


def jp_book_id(cn_id: str) -> str:
    if cn_id.startswith("S5_"):
        parts = cn_id.split("_")
        if len(parts) == 3:
            return f"S5_{parts[1]}"
    return cn_id


def read_lines(path: Path):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig", errors="ignore")
    return text.splitlines(), bom, "\r\n" in text


def write_lines(path: Path, lines, bom: bool, crlf: bool) -> None:
    sep = "\r\n" if crlf else "\n"
    out = (sep.join(lines) + sep).encode("utf-8")
    if bom:
        out = b"\xef\xbb\xbf" + out
    path.write_bytes(out)


def strip(l: str) -> str:
    return TAG_RE.sub("", l).strip()


def h_inner(l: str) -> str:
    out = []
    for m in H1_RE.finditer(l):
        out.append(strip(m.group(0)))
    for m in H2_RE.finditer(l):
        out.append(strip(m.group(0)))
    return "".join(out)


def p_id_attr(p_attrs: str) -> str:
    m = re.search(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", p_attrs, re.I)
    return f'id="{m.group(1)}"' if m else ""


def has_body(path: Path) -> bool:
    lines, _, _ = read_lines(path)
    head_end = next((i for i, l in enumerate(lines, 1) if BODY_RE.search(l)), 0)
    return any(strip(l)
               for i, l in enumerate(lines, 1) if i > head_end and not H_OPEN_RE.search(l))


def rebuild(path: Path, jp_h1: str | None = None):
    """按模板重建文件头部。返回 (新行列表, 说明) 或 (None, 原因)。"""
    lines, _, _ = read_lines(path)
    n = len(lines)
    head_end = next((i for i, l in enumerate(lines, 1) if BODY_RE.search(l)), 0)
    if head_end != 3:
        if head_end > 3 and not any(
                re.match(r"^\s*<(?:p|div|ul|ol|h1|h2|table)\b", l, re.I)
                for l in lines[2:head_end]):
            folded = re.sub(r"<br\s*/?>", "", "".join(lines[2:head_end]))
            lines = lines[:2] + [folded] + lines[head_end:]
            head_end = 3
        else:
            return None, f"头部行数={head_end}≠3"
    l3 = lines[2]

    # 折叠跨行 h1/h2
    merged: list[str] = []
    i = 0
    while i < len(lines):
        l = lines[i]
        m = re.match(r"^\s*<(h1|h2)\b", l, re.I)
        if m:
            tag = m.group(1).lower()
            if f"</{tag}>" not in l.lower():
                buf, j = l, i
                while j + 1 < len(lines) and f"</{tag}>" not in buf.lower() and j - i <= 3:
                    j += 1
                    buf += lines[j]
                if f"</{tag}>" in buf.lower():
                    merged.append(buf)
                    i = j + 1
                    continue
        merged.append(l)
        i += 1
    lines, n = merged, len(merged)
    l3 = lines[2]

    # 头部行内的 h1：提取（包装页）或语义重建（日文嵌入标题）
    h1_from_head = None
    l3_new = l3
    if H_OPEN_RE.search(l3):
        text3, inner3 = strip(l3), h_inner(l3)
        if inner3 and text3 == inner3 and "<h1" in l3.lower():
            m = H1_RE.search(l3)
            h1_from_head = m.group(0)
            l3_new = l3.replace(m.group(0), "")
        else:
            m = EMBED_RE.search(l3)
            if m:
                pre, h1_open, inner, post = m.group(2), m.group(3), m.group(4), m.group(5)
                attrs = (h1_open.strip() or p_id_attr(m.group(1))).strip()
                h1_from_head = f"<h1 {attrs}>{pre}{inner}{post}</h1>" if attrs else \
                    f"<h1>{pre}{inner}{post}</h1>"
                l3_new = re.sub(r"<div\b[^>]*class=\"start-[35]em\"[^>]*>.*?</div>", "", l3,
                                flags=re.S | re.I)
                l3_new = re.sub(r"<br\s*/?>", "", l3_new, flags=re.I)
            else:
                return None, "头部行 h1 无法重建"

    # 扫描顶部区（第 4 行起）直到正文
    h1_slot, h2_slot = None, None
    imgs: list[str] = []
    fb = None
    for i in range(3, n):
        l = lines[i].strip()
        if not l:
            continue
        if H_OPEN_RE.search(l):
            text, inner = strip(l), h_inner(l)
            if text == inner and text:
                if IMG_ELEM_RE.search(l) and "gaiji" not in l.lower() and \
                        "height-2em" not in l.lower():
                    if "<h1" in l.lower() and h1_slot is None:
                        m = H1_RE.search(l)
                        if m:
                            h1_slot = m.group(0)
                            rest = l.replace(m.group(0), "")
                            for im in IMG_ELEM_RE.finditer(rest):
                                imgs.append(im.group(0))
                            if TAG_RE.sub("", rest).strip():
                                return None, f"第{i+1}行 h1 旁有多余文本"
                            continue
                if "<h1" in l.lower() and h1_slot is None:
                    h1_slot = l
                    continue
                if "<h2" in l.lower() and h2_slot is None:
                    h2_slot = l
                    continue
            m = EMBED_RE.search(l)
            if m and h1_slot is None and "</p>" not in m.group(2).lower():
                pre, h1_open, inner2, post = m.group(2), m.group(3), m.group(4), m.group(5)
                attrs = (h1_open.strip() or p_id_attr(m.group(1))).strip()
                h1_slot = f"<h1 {attrs}>{pre}{inner2}{post}</h1>" if attrs else \
                    f"<h1>{pre}{inner2}{post}</h1>"
                continue
            if h1_slot is None and "<h1" in l.lower():
                m = H1_RE.search(l)
                if m:
                    h1_slot = m.group(0)
                    rest = l.replace(m.group(0), "")
                    for im in IMG_ELEM_RE.finditer(rest):
                        imgs.append(im.group(0))
                    if TAG_RE.sub("", rest).strip():
                        return None, f"第{i+1}行 h1 旁有多余文本"
                    continue
            if h2_slot is None and "<h2" in l.lower():
                m = H2_RE.search(l)
                if m:
                    h2_slot = m.group(0)
                    continue
            return None, f"第{i+1}行标题结构异常"
        m = P_TITLE_RE.match(l) or P_SPAN_TITLE_RE.match(l)
        if m and h1_slot is None:
            h1_slot = re.sub(r"^\s*<p\b([^>]*)>(.*?)</p>\s*$", r"<h1\1>\2</h1>", l, flags=re.S)
            continue
        m = DIV_P_TITLE_RE.match(l)
        if m and h1_slot is None:
            cls, inner = m.group(1), m.group(2)
            h1_slot = f'<h1 class="{cls}">{inner}</h1>'
            continue
        if PLAIN_TITLE_RE.match(l) and h1_slot is None:
            h1_slot = re.sub(r"^\s*<p\b([^>]*)>(.*?)</p>\s*$", r"<h1\1>\2</h1>", l)
            continue
        if NUM_P_RE.match(l) and h1_slot is not None and h2_slot is None:
            m = re.search(r"<p\b([^>]*)>", l, re.I)
            inner = re.sub(r"</?p\b[^>]*>", "", l).strip()
            h2_slot = f"<h2 {m.group(1)}>{inner}</h2>" if m and m.group(1) else f"<h2>{inner}</h2>"
            continue
        if IMG_ELEM_RE.search(l) and "gaiji" not in l.lower() and "height-2em" not in l.lower():
            for im in IMG_ELEM_RE.finditer(l):
                imgs.append(im.group(0))
            if TAG_RE.sub("", l).strip():
                return None, f"第{i+1}行图片行有文字"
            continue
        if strip(l):
            fb = i
            break
        if re.match(r"^\s*<br\s*/?>\s*$", l, re.I):
            continue
        fb = i
        break
    if fb is None:
        return None, "无正文"

    if h1_slot is None:
        h1_slot = h1_from_head
    if jp_h1 and h1_slot is None:
        h1_slot = f"<h1>{jp_h1}</h1>"

    new = lines[:2] + [l3_new]
    for im in imgs:
        new[2] += im
    new.append(h1_slot or "")
    new.append(h2_slot or "")
    new.extend(lines[fb:])
    return new, f"{n}→{len(new)}行"


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
        if cn_id is None or cn_id in BOOK_EXCLUSIONS:
            continue
        jp_id = jp_book_id(cn_id)
        if jp_id in jp_books:
            pairs.append((cn_id, jp_id, cn_dir, jp_books[jp_id]))

    jobs: list[tuple[Path, str | None]] = []
    judged: list[tuple[str, str]] = []
    for cn_id, jp_id, cn_dir, jp_dir in pairs:
        cn_all = [(p, header_of(p.name)) for p in cn_dir.rglob("*.xhtml")
                  if p.name.lower() != "nav.xhtml"]
        jp_all = [(p, header_of(p.name)) for p in jp_dir.rglob("*.xhtml")
                  if p.name.lower() != "nav.xhtml"]
        cn_by, jp_by = {}, {}
        for p, h in cn_all:
            if h:
                cn_by.setdefault(h, p)
        for p, h in jp_all:
            if h:
                jp_by.setdefault(h, p)
        for h in sorted(set(jp_by) & set(cn_by)):
            if h in JUDGE_PAIRS:
                judged.append((h, "内容级特例"))
                continue
            if not has_body(jp_by[h]) or not has_body(cn_by[h]):
                continue
            jp_h1 = JP_H1_MAP.get(h)
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
