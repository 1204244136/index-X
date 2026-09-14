#!/usr/bin/env python3
"""成分与页数分析：逐成分给出文字量、「页数（换算）」与书内实测印刷页区间，并导出 CSV。

与 `epub_char_count.py` 的关系：字数口径完全一致（同一套去标签/去注音/去空白规则、
同一批包装页过滤、同一套成分名规范化），本工具在此之上追加**印刷页**维度。

印刷页怎么来的：BookWalker 分页源的正文插图文件名带印刷页码
（`S3_13-i-045.jpg` → 第 45 页、`S3_13-i-314-315.jpg` → 第 314-315 页跨页图），
且这些图片在章节 XHTML 中保留着原始先后位置。于是「正文累计字符数 → 印刷页」
可以标定：

    1. 密度 = 相邻锚点「字符差 / 页差」的中位数（相邻页差是实测硬事实）；
    2. 锚点之间按字符比例在实测页差内插值，锚点之外用密度外推，保证页号单调；
    3. 每个成分/子成分按其字符累计位置起止取页区间。

估算边界（务必按此理解输出）：
    - 页区间是**推算值**：锚点页本身是实测的，锚点之间的分配按字数比例；
      书首（首个插图之前，通常 30~50 页）完全靠密度外推，误差最大；
    - 照片页、彩页、大字号页面会让局部密度偏离均值，单成分页数约有 ±10% 误差；
    - 「页数（换算）」是传统口径（`ceil(全字符 / --pages-per)`），与印刷页列相互独立。

用法：
    python tools/epub_composition_metrics.py <目录或epub> [...]
        [--csv 输出.csv] [--pages-per 400] [--all] [--json] [--chars-only]

    # 示例（日文分页源目录）
    python tools/epub_composition_metrics.py ".cache/epub-work/japanese-text/[S3_13]創約 とある魔術の禁書目録(13)"
    # 默认 CSV 写到 .cache/epub-work/composition-metrics/<书目录名>.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import statistics
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from epub_char_count import (  # noqa: E402
    CJK_RE,
    EpubSource,
    analyze,
    is_fixed_layout,
    is_wrapper,
    normalize_label,
    spine_xhtml_items,
    text_of,
)

# 图片引用：src="../image/S3_13-i-045.jpg"（含 SVG 内 xlink:href）
IMG_REF_RE = re.compile(
    r"""(?:src|xlink:href)\s*=\s*["']([^"']+\.(?:jpg|jpeg|png|gif|webp))["']""",
    re.I,
)
# 印刷页码位于文件名中最后一个连字号数字（或数字-数字）段：
#   S3_13-i-045.jpg → 45    S3_13-i-314-315.jpg → 314-315
#   S3_13-kuchie-003-005.jpg → 3-5（彩页区间，通常无印刷页码含义，仅作锚点）
PAGE_REF_RE = re.compile(r"-(\d{2,4})(?:-(\d{2,4}))?\.[A-Za-z0-9]+$")


def page_ref_of(href: str) -> tuple[int, int] | None:
    """从图片文件名解析印刷页码区间；无页码段（cover/titlepage 等）返回 None。"""
    name = href.replace("\\", "/").rsplit("/", 1)[-1]
    m = PAGE_REF_RE.search(name)
    if not m:
        return None
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    if end < start:
        start, end = end, start
    return start, end


def is_page_anchor(href: str) -> bool:
    """是否可当作印刷页码锚点：正文插图 `i-NNN`（彩页 kuchie 不算印刷正文页）。"""
    name = href.replace("\\", "/").rsplit("/", 1)[-1]
    return bool(re.search(r"-i-\d{2,4}(?:-\d{2,4})?\.[A-Za-z0-9]+$", name))


def image_anchors(raw: str) -> list[tuple[str, tuple[int, int] | None]]:
    """按出现顺序返回成分内全部图片引用及其可用的印刷页码区间。"""
    return [(href, page_ref_of(href)) for href in IMG_REF_RE.findall(raw)]


def classify_component(item: dict, raw: str, txt: str) -> str:
    """判定成分类型。"""
    stem = Path(item["path"]).stem
    if is_fixed_layout(item):
        if txt:
            return "固定版式文本"
        if any(is_page_anchor(h) for h, _ in image_anchors(raw)):
            return "插图页"
        if re.search(r"kuchie|allcover", stem, re.I):
            return "彩页"
        return "固定版式页"
    if not txt:
        return "无正文页"
    if is_wrapper(stem, item["path"]):
        return "包装页"
    return "正文"


def scan_book(source: EpubSource, pages_per: int, include_all: bool) -> dict:
    """扫描单本书：成分文字量 + 实际页区间 + 页数。"""
    items = spine_xhtml_items(source)
    comps: list[dict] = []
    skipped: list[str] = []
    for it in items:
        if it["media_type"] != "application/xhtml+xml":
            continue
        if "nav" in it["props_manifest"]:
            continue
        stem = Path(it["path"]).stem
        if not include_all and (is_fixed_layout(it) or is_wrapper(stem, it["path"])):
            skipped.append(stem)
            continue
        c = analyze(source, it, pages_per)
        raw = source.read(it["path"]).decode("utf-8", errors="replace")
        txt = text_of(raw)
        comps.append({
            "path": it["path"],
            "stem": stem,
            "label": c["label"],
            "kind": classify_component(it, raw, txt),
            "all_chars": c["all_chars"],
            "cjk_chars": c["cjk_chars"],
            "pages_char": c["pages"],
            "image_anchors": image_anchors(raw),
            "subs": split_sections(raw, pages_per),
            "_raw": raw,
        })
        if c["all_chars"] == 0 and not [r for _, r in image_anchors(raw) if r]:
            skipped.append(stem)

    # ---- 锚点整理：成分内锚点按出现顺序；子成分记录起始偏移 ----
    for c in comps:
        refs = [(pos, ref) for pos, (href, ref)
                in zip([m.start() for m in IMG_REF_RE.finditer(c["_raw"])],
                       c["image_anchors"])
                if ref and is_page_anchor(href)]
        c["anchors"] = [ref for _, ref in refs]
        c["anchor_pos"] = [pos for pos, _ in refs]
        if c["subs"]:
            for s, off in zip(c["subs"], sub_offsets(c["_raw"])):
                s["off"] = off

    # ---- 锚点定位：把「字符累计位置」与「印刷页码」做线性拟合 ----
    # 书内插图文件名带印刷页码（`S3_13-i-045.jpg` → 第 45 页），且这些图片在章节
    # XHTML 中保有原始先后位置，所以「锚点累计字符数 → 印刷页」是一条直线：
    #     印刷页 = 斜率(字符/页) × 累计字符 + 截距
    # 用最小二乘拟合全部锚点，再用同一套参数把每个成分/子成分的字符位置映射为
    # 页区间。这样既用到实测量的斜率（真实排版密度），又保证页区间严格单调不重叠。
    body = [c for c in comps if c["kind"] == "正文"]
    anchors: list[dict] = []          # 全书锚点序（按正文累计字符位置）：{page, cum}
    cum = 0
    for c in body:
        c["cum"] = cum
        if c["subs"]:
            for pos, ref in zip(c["anchor_pos"], c["anchors"]):
                cum_chars = cum + sum(s["all_chars"] for s in c["subs"]
                                      if pos >= s["off"])
                anchors.append({"page": ref[0], "page_end": ref[1], "cum": cum_chars})
            cum += sum(s["all_chars"] for s in c["subs"])
        else:
            if c["anchors"]:
                anchors.append({"page": c["anchors"][0][0],
                                "page_end": c["anchors"][0][1],
                                "cum": cum + c["all_chars"]})
            cum += c["all_chars"]
    anchors.sort(key=lambda a: (a["cum"], a["page"]))

    # 斜率 = 相邻锚点「字符差 / 页差」的中位数（相邻页差是实测的硬事实，
    # 比全场最小二乘更抗前后段排版密度差异）；截距取全部锚点残差的中位数，
    # 即 page = cum / density + intercept。斜率同时用于锚点区间外的外推。
    slope = None
    gaps = []
    for a, b in zip(anchors, anchors[1:]):
        pg = b["page"] - a["page"]
        ch = b["cum"] - a["cum"]
        if pg > 0 and ch > 0:
            gaps.append(ch / pg)
    if gaps:
        slope = statistics.median(gaps)
    intercept = None
    if slope:
        intercept = statistics.median(a["page"] - a["cum"] / slope for a in anchors)
    if slope and anchors:
        # 首锚点之前无实测锚点，只能用全局密度外推；若外推越过第 1 页则收在第 1 页
        intercept = max(intercept, 1 - anchors[0]["cum"] / slope)

    def page_at(cum_chars: int) -> float:
        """累计字符 -> 印刷页，保证单调。

        锚点之间按「字符比例」在实测页差内插值；锚点之外（首个插图之前、
        末个插图之后）用全局密度外推。区间内密度差异（照片页/大字号页）会
        保留在各区间内部，因此不会跨章累积漂移。
        """
        if slope is None:
            return 0.0
        prev = None
        for a in anchors:
            if cum_chars < a["cum"]:
                if prev is None:
                    return cum_chars / slope + intercept
                span_c = a["cum"] - prev["cum"]
                span_p = a["page"] - prev["page"]
                if span_c <= 0 or span_p <= 0:
                    return float(a["page"])
                return prev["page"] + (cum_chars - prev["cum"]) * span_p / span_c
            prev = a
        last = anchors[-1]
        return last["page"] + (cum_chars - last["cum"]) / slope

    # ---- 逐成分/子成分定页 ----
    density = slope
    for c in body:
        if c["subs"]:
            sections = c["subs"]
            # 子成分在全书正文中的起始累计字符
            start_cum = c["cum"]
            ends = []
            acc = start_cum
            for s in sections:
                ends.append(acc)
                acc += s["all_chars"]
            c["cum"] = acc
            for s, s_start in zip(sections, ends):
                s_anchors = [r for p, r in zip(c["anchor_pos"], c["anchors"])
                             if s["off"] <= p]
                s["anchors"] = s_anchors
                s["measured"] = bool(s_anchors)
                begin = page_at(s_start)
                finish = page_at(s_start + s["all_chars"] - 1) if s["all_chars"] else begin
                s["page_start"] = max(1, math.floor(begin + 1e-9))
                s["page_end"] = max(s["page_start"], math.ceil(finish - 1e-9))
            # 短小节在前置页密度不均时可能被算成空区间或与上一节重叠：
            # 按顺序压实，保证同一成分内子成分页区间严格递增、不重叠。
            prev_end = 0
            for s in sections:
                if s["page_start"] <= prev_end:
                    s["page_start"] = prev_end + 1
                if s["page_end"] < s["page_start"]:
                    s["page_end"] = s["page_start"]
                s["pages"] = s["page_end"] - s["page_start"] + 1
                prev_end = s["page_end"]
            c["page_start"] = sections[0]["page_start"]
            c["page_end"] = sections[-1]["page_end"]
            c["pages"] = c["page_end"] - c["page_start"] + 1
            c["measured"] = any(s["measured"] for s in sections)
        else:
            begin = page_at(c["cum"])
            finish = page_at(c["cum"] + c["all_chars"] - 1) if c["all_chars"] else begin
            c["page_start"] = max(1, math.floor(begin + 1e-9))
            c["page_end"] = max(c["page_start"], math.ceil(finish - 1e-9))
            c["pages"] = c["page_end"] - c["page_start"] + 1
            c["measured"] = bool(c["anchors"])
            c["cum"] += c["all_chars"]

    for c in comps:
        c.pop("_raw", None)
        c.pop("image_anchors", None)

    # 成分级压实：锚点页是整数，相邻成分在取整后可能重叠 1~2 页
    for prev, cur in zip(body, body[1:]):
        if cur["page_start"] <= prev["page_end"]:
            shift = prev["page_end"] + 1 - cur["page_start"]
            for key in ("page_start", "page_end"):
                cur[key] += shift
            for s in cur.get("subs", []):
                s["page_start"] += shift
                s["page_end"] += shift
            cur["pages"] = cur["page_end"] - cur["page_start"] + 1

    normalize_labels({"components": comps})

    all_refs = [r for c in comps for r in c["anchors"]]
    tot_all = sum(c["all_chars"] for c in body)
    tot_cjk = sum(c["cjk_chars"] for c in body)
    printed = (max(r[1] for r in all_refs) - min(r[0] for r in all_refs) + 1) if all_refs else 0
    return {
        "book": source.book_name,
        "source": source.origin,
        "pages_per": pages_per,
        "components": comps,
        "skipped": skipped,
        "totals": {
            "all_chars": tot_all,
            "cjk_chars": tot_cjk,
            "pages_char_sum": sum(c["pages_char"] for c in body),
            "pages_continuous": max(1, math.ceil(tot_all / pages_per)) if tot_all else 0,
            "pages_measured_sum": sum(c["pages"] for c in body),
            "printed_pages": printed,
            "printed_from": min((r[0] for r in all_refs), default=0),
            "printed_to": max((r[1] for r in all_refs), default=0),
            "span_from": min((c["page_start"] for c in body), default=0),
            "span_to": max((c["page_end"] for c in body), default=0),
            "density": density,
            "anchor_coverage": ((sum(c["all_chars"] for c in body if c["anchors"]) / tot_all)
                                if tot_all else 0.0),
        },
    }


def sub_offsets(raw: str) -> list[int]:
    """各子成分（<h2> 段）在 raw 中的起始偏移，顺序与 split_sections 一致。"""
    body_start = len(re.split(r"<h1[^>]*>.*?</h1>", raw, flags=re.S)[0])
    parts = re.split(r"(<h2[^>]*>.*?</h2>)", raw, flags=re.S)
    offsets = []
    pos = body_start + len(parts[0])
    for i in range(1, len(parts), 2):
        offsets.append(pos)
        pos += len(parts[i]) + len(parts[i + 1])
    return offsets


def split_sections(raw: str, pages_per: int = 400) -> list[dict]:
    """按 <h2> 切分子成分：返回 [{label, all_chars, cjk_chars, pages_char, refs}, ...]。

    与 `epub_char_count.split_sections` 口径一致：子成分段不含 h1 标题文字，
    h1 之前的开场文字并入第一节。
    """
    body = re.sub(r"<h1[^>]*>.*?</h1>", "", raw, flags=re.S)
    parts = re.split(r"(<h2[^>]*>.*?</h2>)", body, flags=re.S)
    if len(parts) < 3:
        return []
    fw = str.maketrans("０１２３４５６７８９", "0123456789")
    out = []
    for i in range(1, len(parts), 2):
        seg = (parts[0] if i == 1 else "") + parts[i] + parts[i + 1]
        label = re.sub(r"<rt[^>]*>.*?</rt>", "", parts[i], flags=re.S)
        label = re.sub(r"<[^>]+>", "", label)
        label = re.sub(r"\s+", " ", label).strip().translate(fw)
        txt = text_of(seg)
        out.append({"label": label, "all_chars": len(txt),
                    "cjk_chars": len(CJK_RE.findall(txt)),
                    "pages_char": max(1, math.ceil(len(txt) / pages_per)) if txt else 0,
                    "refs": []})
    return out


def normalize_labels(rep: dict) -> None:
    """成分名规范化（与 epub_char_count 同一套规则）。

    - 章节标题截断为「序章/第N章/终章」，去掉副标题；
    - 常用日文词替换为中文（行間→行间、終→终、あとがき→后记）；
    - 位置规则：第一个「序章」之前的成分 → 引子；第一个「后记」之后的成分 → 尾声。
    """
    comps = rep["components"]
    for c in comps:
        c["label"] = normalize_label(c["label"])
    labels = [c["label"] for c in comps]
    first_pro = next(
        (i for i, label in enumerate(labels) if label == "序章"),
        None,
    )
    if first_pro is not None:
        for c in comps[:first_pro]:
            c["label"] = "引子"
    first_af = next(
        (i for i, label in enumerate(labels) if label == "后记"),
        None,
    )
    if first_af is not None:
        for c in comps[first_af + 1:]:
            c["label"] = "尾声"
    for c in comps:
        if len(c["subs"]) > 1:
            for i, s in enumerate(c["subs"], 1):
                if not s["label"]:
                    s["label"] = f"（无标号{i}）"
        elif len(c["subs"]) == 1 and not c["subs"][0]["label"]:
            c["subs"][0]["label"] = "（无标号）"


def ref_str(start: int, end: int) -> str:
    """印刷页区间文本；无锚点时留空。"""
    if not start:
        return ""
    return f"p.{start}" if start == end else f"p.{start}-{end}"


def display_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def pad(s: str, width: int, right: bool = False) -> str:
    gap = max(0, width - display_width(s))
    return (" " * gap + s) if right else (s + " " * gap)


# CSV/表格列（与项目既有「成分 / 子成分 / 页数（换算）」口径一致，另附印刷页实测列）
HEAD = ("成分", "子成分", "全字符", "页数（换算）", "印刷页区间", "印刷页数")


def render_csv(reports: list[dict], granular: bool = True) -> str:
    """扁平 CSV：成分/子成分/全字符/页数（换算）/印刷页区间/印刷页数。"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    multi = len(reports) > 1
    w.writerow((["书籍"] if multi else []) + list(HEAD))
    for rep in reports:
        for r in render_rows(rep, granular):
            w.writerow(([rep["book"]] if multi else []) + list(r))
    return buf.getvalue()


def render_rows(rep: dict, granular: bool = True) -> list[tuple]:
    """逐行数据：granular=True 时正文按子成分展开，否则每个成分一行。

    子成分行只把「成分」列写在首行，其余行留空（与既有 CSV 版式一致）。
    """
    rows: list[tuple] = []
    for c in rep["components"]:
        first = True

        def mark(label: str) -> str:
            nonlocal first
            out = label if first else ""
            first = False
            return out

        if granular and c["subs"]:
            for s in c["subs"]:
                rows.append((mark(c["label"]), s["label"], s["all_chars"],
                             s["pages_char"], ref_str(s["page_start"], s["page_end"]),
                             s["pages"]))
        else:
            rows.append((mark(c["label"]), "", c["all_chars"], c["pages_char"],
                         ref_str(c["page_start"], c["page_end"]), c["pages"]))
    t = rep["totals"]
    rows.append(("合计", "", t["all_chars"], t["pages_char_sum"],
                 ref_str(t["span_from"], t["span_to"]), t["pages_measured_sum"]))
    return rows


def render_report(rep: dict) -> str:
    t = rep["totals"]
    rows = render_rows(rep)
    widths = [max([display_width(HEAD[i])] +
                  [display_width(str(r[i])) for r in rows]) for i in range(len(HEAD))]
    lines = [f"书籍：{rep['book']}",
             f"来源：{rep['source']}",
             f"换算标准：{rep['pages_per']} 字/页（全字符含标点、去注音假名）",
             f"印刷页锚点：p.{t['printed_from']}-p.{t['printed_to']}"
             f"（可见 {t['printed_pages']} 页）",
             (f"正文实测密度：{t['density']:.1f} 字符/页"
              f"（由相邻插图锚点的印刷页跨度反推）；"
              f"锚点字符覆盖率 {t['anchor_coverage'] * 100:.1f}%"
              if t["density"] else "正文实测密度：不可用（书内无插图页码锚点）"),
             f"全书正文印刷页推算：p.{t['span_from']}-p.{t['span_to']}"
             f"（共 {t['pages_measured_sum']} 页）", ""]
    lines.append("  ".join(pad(HEAD[i], widths[i], i >= 2) for i in range(len(HEAD))))
    for r in rows:
        lines.append("  ".join(pad(str(r[i]), widths[i], i >= 2) for i in range(len(HEAD))))
    return "\n".join(lines)


def render_skipped(rep: dict) -> str:
    if not rep["skipped"]:
        return ""
    names = rep["skipped"]
    return (f"已跳过 {len(names)} 个包装/无正文页："
            + "、".join(names[:24]) + (" …" if len(names) > 24 else ""))


def collect_sources(paths: list[Path]) -> list[EpubSource]:
    out: list[EpubSource] = []
    for p in paths:
        if p.is_dir():
            out.append(EpubSource.from_path(p))
        elif p.is_file():
            out.append(EpubSource.from_path(p))
        else:
            raise SystemExit(f"路径不存在：{p}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="EPUB 成分与页数分析（含实际印刷页区间）")
    ap.add_argument("paths", nargs="+", type=Path, help="已解包书籍目录或 .epub 文件")
    ap.add_argument("--pages-per", type=int, default=400,
                    help="每页字数（换算页数用），默认 400")
    ap.add_argument("--all", action="store_true",
                    help="连包装页/固定版式页一起统计")
    ap.add_argument("--csv", type=Path, metavar="OUT.csv",
                    help="CSV 输出路径（默认 .cache/epub-work/composition-metrics/<书目录名>.csv）")
    ap.add_argument("--no-csv", action="store_true", help="只打印，不写 CSV")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--chars-only", action="store_true",
                    help="CSV 只按成分输出（正文不展开子成分），用于总览")
    args = ap.parse_args()

    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    reports = [scan_book(s, args.pages_per, args.all) for s in collect_sources(args.paths)]

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2, default=str))
    else:
        for rep in reports:
            print(render_report(rep))
            note = render_skipped(rep)
            if note:
                print(note)
            print()

    if not args.no_csv:
        out = args.csv or default_csv_path(reports)
        out.parent.mkdir(parents=True, exist_ok=True)
        data = "\ufeff" + render_csv(reports, granular=not args.chars_only)
        out.write_text(data, encoding="utf-8", newline="\r\n")
        print(f"CSV 已写入：{out}")
    return 0


def default_csv_path(reports: list[dict]) -> Path:
    """默认输出路径：缓存书目录写到同级 `composition-metrics/<书>.csv`。

    分析产物不放进书籍目录，避免被 `package_cache_epubs.py` 打进 EPUB。
    """
    if len(reports) != 1:
        raise SystemExit("多本书请用 --csv 指定输出路径")
    base = Path(reports[0]["source"])
    if base.is_dir():
        if base.parent.name in ("japanese-text", "chinese-text"):
            return base.parent.parent / "composition-metrics" / f"{base.name}.csv"
        return base / "composition-metrics.csv"
    return base.with_suffix(".composition-metrics.csv")


if __name__ == "__main__":
    raise SystemExit(main())
