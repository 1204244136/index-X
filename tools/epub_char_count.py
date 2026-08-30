#!/usr/bin/env python3
"""探测 EPUB 各正文成分的字数，并换算为页数（每个成分/子成分至少 1 页）。

用法：
    python tools/epub_char_count.py <epub或目录> [<epub或目录> ...] [--pages-per 400] [--all] [--csv|--json] [--label-map map.json] [--min-chars 1]

默认只统计「正文成分」：
    - 按 spine 顺序取含文字的 XHTML 页；
    - 跳过固定版式包装页（pre-paginated / svg，封面、扉页、卷首插画等）、导航文档，
      以及文件名或标题命中包装页关键词（cover / colophon / 奥付 / toc / 目次 / contents /
      fmatter / bmatter / bookwalker / titlepage / caution / 注意 / nav / 版权 / 広告 / banner 等）的页面；
    - 想连包装页一起统计时加 --all。

精确到子成分：
    - 成分内若含 <h2>，按 <h2> 切分为「子成分」（标签取自小节标题，全角数字转半角），
      h1 前的开场文字并入第一节；章级页数 = 子成分页数之和；
    - 子成分行不含 h1 标题文字，因此「子成分字数之和 + h1 标题字数 = 成分总字数」；
    - 无 <h2> 的成分按整体统计。

成分名规范化（默认开启，--raw-labels 关闭）：
    - 章节标题截断为「序章/第N章/终章」，去掉副标题（如「第一章 健全なる…」→「第一章」）；
    - 常用日文词替换为中文（行間→行间、終→终、あとがき→后记），并去掉标签内空白；
    - 位置规则：第一个「序章」之前的成分 → 引子；第一个「后记」之后的成分 → 尾声。

字数口径：
    - 去 HTML 标签、去注音假名（<rt>/<rb>/<rp>，注音不重复计数）、解实体、去全部空白；
    - 「全字符」= 剩余全部字符（含标点、数字、字母）；「占比」= 其中汉字与假名占全字符的比例（0.xx 两位小数）。

页数换算：
    - 每个成分/子成分页数 = max(1, ceil(全字符 / --pages-per))，--pages-per 默认 400（全字符含标点约 400 字/页）；
    - 章级（含子成分）页数 = 子成分页数之和；合计行同时给出「连续排版约 X 页」与「成分整体口径（每成分至少 1 页）」两种参考。
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import math
import posixpath
import re
import sys
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# 包装页关键词（对文件名与标题做不区分大小写的子串匹配）
WRAPPER_KEYWORDS = (
    "cover", "colophon", "奥付", "toc", "目次", "contents", "fmatter", "bmatter",
    "bookwalker", "titlepage", "caution", "注意", "nav", "版权", "広告", "banner",
    "backcover",
)

CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\u3005\u3006]")

# 全角数字 -> 半角（子成分编号如 １ → 1）
FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def disp_width(s: str) -> int:
    """按终端显示宽度计算字符串宽度（东亚全角字符记 2 列）。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def pad_field(s: str, width: int, align: str = "left") -> str:
    """按显示宽度补齐到 width 列；align=right 时右对齐数字。"""
    gap = width - disp_width(s)
    if gap <= 0:
        return s
    return (" " * gap + s) if align == "right" else (s + " " * gap)


def pct_str(all_chars: int, cjk_chars: int) -> str:
    """「占比」= 汉字假名占全字符的比例，0.xx 两位小数。"""
    if all_chars <= 0:
        return "0.00"
    return f"{cjk_chars / all_chars:.2f}"


# 成分名规范化用：章节头（序章/第N章/终章）与常用日文词
CHAPTER_RE = re.compile(r"^(序|終|第[一二三四五六七八九十百\d]+)\s*章")
JP_LABEL_TRANS = (("行間", "行间"), ("終", "终"), ("あとがき", "后记"))


def normalize_label(label: str) -> str:
    """成分名规范化：
    - 章节标题截断为「序章/第N章/终章」（去掉空间与副标题）；
    - 常用日文词替换为中文（行間→行间、終→终、あとがき→后记）；
    - 命中了上述规则的标签再去掉内部空白（行間 一 → 行间一）。
    """
    m = CHAPTER_RE.match(label)
    if m:
        head = re.sub(r"\s+", "", m.group(0))
        for src, dst in JP_LABEL_TRANS:
            head = head.replace(src, dst)
        return head
    changed = False
    for src, dst in JP_LABEL_TRANS:
        if src in label:
            label = label.replace(src, dst)
            changed = True
    return re.sub(r"\s+", "", label) if changed else label


def apply_label_rules(comps: list[dict]) -> list[dict]:
    """按出现位置补全成分名：
    - 第一个「序章」之前的成分 → 引子；
    - 第一个「后记」之后的成分 → 尾声。
    """
    labels = [c["label"] for c in comps]
    first_pro = next((i for i, l in enumerate(labels) if l == "序章"), None)
    if first_pro is not None:
        for c in comps[:first_pro]:
            c["label"] = "引子"
    first_af = next((i for i, l in enumerate(labels) if l == "后记"), None)
    if first_af is not None:
        for c in comps[first_af + 1:]:
            c["label"] = "尾声"
    return comps


def tag_local(tag: str) -> str:
    """去掉 XML 命名空间前缀，返回本地标签名。"""
    return tag.rsplit("}", 1)[-1]


def strip_ruby(text: str) -> str:
    """删除注音假名 <rt>/<rb>/<rp>，避免重复计数。"""
    text = re.sub(r"<rt[^>]*>.*?</rt>", "", text, flags=re.S)
    text = re.sub(r"<rt[^>]*/>", "", text)
    text = re.sub(r"<rb[^>]*>.*?</rb>", "", text, flags=re.S)
    text = re.sub(r"<rp[^>]*>.*?</rp>", "", text, flags=re.S)
    return text


def text_of(raw: str) -> str:
    """提取正文纯文本：去 script/style、去标签、解实体、去全部空白。"""
    t = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", raw, flags=re.I | re.S)
    t = strip_ruby(t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return re.sub(r"\s+", "", t)


def h1_of(raw: str) -> str | None:
    """取 <h1> 标题（去标签、去注音、折叠空白）；无则返回 None。"""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", raw, flags=re.S)
    if not m:
        return None
    s = strip_ruby(m.group(1))
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def h2_label_of(tag_html: str) -> str:
    """取 <h2> 小节标题文本（去标签、去注音、全角数字转半角）。"""
    m = re.search(r"<h2[^>]*>(.*?)</h2>", tag_html, flags=re.S)
    if not m:
        return ""
    s = strip_ruby(m.group(1))
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.translate(FW_DIGITS)


def split_sections(raw: str) -> list[tuple[str, str]]:
    """按 <h2> 切分子成分。

    返回 [(小节标签, HTML 段), ...]。每段的 HTML 含自身 <h2> 标题、不含 h1；
    h1 之前的开场文字并入第一节。由此保证：
        「子成分字数之和 + h1 标题字数 = 成分总字数」。
    无 <h2> 时返回 []（整成分视为一个整体，不分级）。
    """
    body = re.sub(r"<h1[^>]*>.*?</h1>", "", raw, flags=re.S)
    parts = re.split(r"(<h2[^>]*>.*?</h2>)", body, flags=re.S)
    if len(parts) < 3:
        return []
    h2_tags = parts[1::2]
    contents = parts[2::2]
    pre = parts[0]
    segs = [t + c for t, c in zip(h2_tags, contents)]
    if pre.strip():
        segs[0] = pre + segs[0]
    return [(h2_label_of(t), seg) for t, seg in zip(h2_tags, segs)]


def is_wrapper(label: str, path: str) -> bool:
    """文件名或标题命中包装页关键词，判定为包装页。"""
    hay = f"{Path(path).stem} {label}".lower()
    return any(k in hay for k in WRAPPER_KEYWORDS)


def spine_xhtml_items(z: zipfile.ZipFile) -> list[dict]:
    """解析 OPF，返回按 spine 顺序排列的正文 XHTML 项。

    每项：{path, media_type, props_manifest, props_itemref}
    解析失败时抛 SystemExit。
    """
    try:
        cont = ET.fromstring(z.read("META-INF/container.xml"))
    except KeyError as exc:
        raise SystemExit("缺少 META-INF/container.xml，不是合法 EPUB") from exc
    rootfile = next((e for e in cont.iter() if tag_local(e.tag) == "rootfile"), None)
    if rootfile is None:
        raise SystemExit("container.xml 中找不到 rootfile")
    opf_path = rootfile.get("full-path")
    root = ET.fromstring(z.read(opf_path))
    opf_dir = posixpath.dirname(opf_path)

    manifest: dict[str, dict] = {}
    for it in root.iter():
        if tag_local(it.tag) == "item":
            manifest[it.get("id")] = {
                "href": it.get("href", ""),
                "media_type": it.get("media-type", ""),
                "props": it.get("properties", "") or "",
            }

    items: list[dict] = []
    for sr in root.iter():
        if tag_local(sr.tag) != "itemref":
            continue
        if sr.get("linear") == "no":
            continue
        it = manifest.get(sr.get("idref"))
        if it is None:
            continue
        full = posixpath.normpath(posixpath.join(opf_dir, it["href"]))
        items.append({
            "path": full,
            "media_type": it["media_type"],
            "props_manifest": it["props"],
            "props_itemref": sr.get("properties", "") or "",
        })
    return items


def is_fixed_layout(item: dict) -> bool:
    """固定版式包装页：svg 属性或 pre-paginated 版式标记。"""
    return "svg" in item["props_manifest"] or "pre-paginated" in item["props_itemref"]


def analyze(z: zipfile.ZipFile, item: dict, pages_per: int) -> dict:
    raw = z.read(item["path"]).decode("utf-8", errors="replace")
    stem = Path(item["path"]).stem
    h1 = h1_of(raw)
    txt = text_of(raw)
    sub_components = []
    for slabel, seg in split_sections(raw):
        n = len(text_of(seg))
        sub_components.append({
            "label": slabel,
            "all_chars": n,
            "cjk_chars": len(CJK_RE.findall(text_of(seg))),
            "pages": max(1, math.ceil(n / pages_per)),
        })
    all_chars = len(txt)
    pages = (sum(s["pages"] for s in sub_components)
             if sub_components else max(1, math.ceil(all_chars / pages_per)))
    return {
        "path": item["path"],
        "stem": stem,
        "label": h1 or stem,
        "h1_chars": len(text_of(re.search(r"(<h1[^>]*>.*?</h1>)", raw, flags=re.S).group(1)))
                    if "<h1" in raw else 0,
        "all_chars": all_chars,
        "cjk_chars": len(CJK_RE.findall(txt)),
        "pages": pages,
        "sub_components": sub_components,
    }


def scan_book(path: Path, pages_per: int, include_wrapper: bool,
              min_chars: int, label_map: dict, normalize: bool = True) -> dict:
    with zipfile.ZipFile(path) as z:
        items = spine_xhtml_items(z)
        comps, skipped = [], []
        for it in items:
            if it["media_type"] != "application/xhtml+xml":
                continue
            if "nav" in it["props_manifest"]:
                continue
            stem = Path(it["path"]).stem
            if not include_wrapper and (is_fixed_layout(it) or is_wrapper(stem, it["path"])):
                skipped.append(stem)
                continue
            c = analyze(z, it, pages_per)
            if c["all_chars"] == 0:
                skipped.append(stem)
                continue
            if c["all_chars"] < min_chars:
                skipped.append(stem)
                continue
            if label_map:
                c["label"] = label_map.get(stem) or label_map.get(it["path"]) or c["label"]
            comps.append(c)
    if normalize:
        for c in comps:
            c["label"] = normalize_label(c["label"])
        apply_label_rules(comps)
    tot_all = sum(c["all_chars"] for c in comps)
    tot_cjk = sum(c["cjk_chars"] for c in comps)
    return {
        "book": path.name,
        "pages_per": pages_per,
        "components": comps,
        "skipped": skipped,
        "totals": {
            "all_chars": tot_all,
            "cjk_chars": tot_cjk,
            "pages_sum": sum(c["pages"] for c in comps),
            "pages_components": sum(max(1, math.ceil(c["all_chars"] / pages_per)) for c in comps),
            "pages_continuous": max(1, math.ceil(tot_all / pages_per)),
        },
    }


def collect_paths(args: argparse.Namespace) -> list[Path]:
    out: list[Path] = []
    for p in args.paths:
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out.extend(sorted(p.rglob("*.epub")))
        else:
            raise SystemExit(f"路径不存在：{p}")
    if not out:
        raise SystemExit("未找到任何 .epub 文件")
    return out


def render_report(rep: dict) -> str:
    """按对齐表格输出（成分 / 子成分 / 全字符 / 占比 / 换算页数）。

    扁平结构：每个子成分各占一行（成分名重复），无子成分的成分占一行且子成分留空；
    不做缩进折叠。含子成分的章不单独出小计行，章级字数 = 子成分之和（不含 h1 标题）。
    「占比」= 汉字假名占全字符的比例（0.xx 两位小数）。
    """
    t = rep["totals"]
    head = ("成分", "子成分", "全字符", "占比", "换算页数")
    rows = []  # (label, sub, all_str, pct_str, pages_str)
    for c in rep["components"]:
        if c["sub_components"]:
            for s in c["sub_components"]:
                rows.append((c["label"], s["label"], str(s["all_chars"]),
                             pct_str(s["all_chars"], s["cjk_chars"]), str(s["pages"])))
        else:
            rows.append((c["label"], "", str(c["all_chars"]),
                         pct_str(c["all_chars"], c["cjk_chars"]), str(c["pages"])))
    total = ("合计", "", str(t["all_chars"]),
             pct_str(t["all_chars"], t["cjk_chars"]), str(t["pages_sum"]))

    w_label = max([disp_width(head[0])] + [disp_width(r[0]) for r in rows]
                  + [disp_width(total[0])])
    w_sub = max([disp_width(head[1])] + [disp_width(r[1]) for r in rows])
    w_all = max([len(head[2])] + [len(r[2]) for r in rows] + [len(total[2])])
    w_pct = max([disp_width(head[3])] + [disp_width(r[3]) for r in rows]
                + [disp_width(total[3])])
    w_pg = max([len(head[4])] + [len(r[4]) for r in rows] + [len(total[4])])

    def fmt(label: str, sub: str, all_: str, pct: str, pg: str) -> str:
        return (pad_field(label, w_label) + "  "
                + pad_field(sub, w_sub) + "  "
                + pad_field(all_, w_all, "right") + "  "
                + pad_field(pct, w_pct, "right") + "  "
                + pad_field(pg, w_pg, "right"))

    lines = [f"书籍：{rep['book']}",
             f"换算标准：{rep['pages_per']} 字/页（全字符，含标点，去注音假名）", ""]
    lines.append(fmt(*head))
    for r in rows:
        lines.append(fmt(*r))
    lines.append("-" * 32)
    lines.append(fmt(*total) + f"  （连续排版约 {t['pages_continuous']} 页，成分整体口径 {t['pages_components']} 页）")
    if rep["skipped"]:
        lines.append(f"已跳过 {len(rep['skipped'])} 个包装/空文本页：{', '.join(rep['skipped'][:20])}"
                     + (" …" if len(rep["skipped"]) > 20 else ""))
    return "\n".join(lines)


def render_csv(reports: list[dict]) -> str:
    """扁平结构转 CSV（含表头与每本书的合计行）。

    单本书：列 = 成分/子成分/全字符/占比/换算页数（占比为 0.xx 两位小数，无百分号）；
    多本书：首列追加「书籍」以合并为一张表。
    """
    multi = len(reports) > 1
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    header = (["书籍"] if multi else []) + ["成分", "子成分", "全字符", "占比", "换算页数"]
    w.writerow(header)
    for rep in reports:
        t = rep["totals"]
        for c in rep["components"]:
            if c["sub_components"]:
                for s in c["sub_components"]:
                    row = ([rep["book"]] if multi else []) + [
                        c["label"], s["label"], s["all_chars"],
                        pct_str(s["all_chars"], s["cjk_chars"]), s["pages"]]
                    w.writerow(row)
            else:
                row = ([rep["book"]] if multi else []) + [
                    c["label"], "", c["all_chars"],
                    pct_str(c["all_chars"], c["cjk_chars"]), c["pages"]]
                w.writerow(row)
        row = ([rep["book"]] if multi else []) + [
            "合计", "", t["all_chars"],
            pct_str(t["all_chars"], t["cjk_chars"]), t["pages_sum"]]
        w.writerow(row)
    return buf.getvalue()


def main() -> int:
    p = argparse.ArgumentParser(description="探测 EPUB 各正文成分字数并换算页数")
    p.add_argument("paths", nargs="+", type=Path, help="EPUB 文件或目录")
    p.add_argument("--pages-per", type=int, default=400,
                   help="每页字数（全字符含标点），默认 400")
    p.add_argument("--all", action="store_true",
                   help="连包装页（封面/奥付/目次/广告等）一起统计")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--csv", action="store_true",
                   help="输出 CSV（UTF-8 带 BOM，Excel 可直接打开；扁平结构，每本书一个合计行）")
    p.add_argument("--min-chars", type=int, default=1,
                   help="忽略全字符数低于该值的页面，默认 1")
    p.add_argument("--raw-labels", action="store_true",
                   help="不做成分名规范化（保留原 h1/文件名标签）")
    p.add_argument("--label-map", type=Path, metavar="MAP.JSON",
                   help="可选的成分名映射 JSON，如 {\"S4_03-01-p-001\": \"引子\"}")
    args = p.parse_args()

    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    label_map: dict = {}
    if args.label_map:
        label_map = json.loads(args.label_map.read_text(encoding="utf-8"))

    reports = [scan_book(f, args.pages_per, args.all, args.min_chars, label_map,
                         normalize=not args.raw_labels)
               for f in collect_paths(args)]

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    elif args.csv:
        sys.stdout.write("\ufeff" + render_csv(reports))  # BOM：Excel 识别 UTF-8
    else:
        for rep in reports:
            print(render_report(rep))
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
