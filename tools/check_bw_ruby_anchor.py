#!/usr/bin/env python3
"""核对 BW 分页源中锚点词的 ruby（注音）形态（只读）。

为什么必须回源：缓存区的日文 XHTML 是**预处理产物**——`tools/bw_preprocess.py` 含
「多段 ruby 合并为单段」规则（如
`<ruby>検<rt>シリ</rt>体<rt>アル</rt>番<rt>ナン</rt>号<rt>バー</rt></ruby>`
→ `<ruby>検体番号<rt>シリアルナンバー</rt></ruby>`）。因此「某处原文是否带注音」
「注音内容是什么」不能只看缓存，必须读 BW 提取源目录下的 `.epub` 原文。

口径要点：BookWalker 源对多数汉字词都标读音
（`<ruby>学<rt>がく</rt>園<rt>えん</rt>都<rt>と</rt>市<rt>し</rt></ruby>`），缓存只保留
**特殊注音**。所以「日文有特殊注音则译文必须有注音」的锚点是源中的**特殊读音**
（当て字／外来语），普通读音不构成译文注音义务。

本工具把每个 `<ruby>` 归一化为 `base|rt1+rt2` 后聚合形态，输出：

  * 锚点词出现在 **base** 内的 ruby 形态与计数（= 该词的实际注音形态）；
  * 锚点词出现在 **rt** 内的 ruby 形态与计数（= 该注音标注了哪些汉字）；
  * 正文（去掉 ruby 段与全部标签）中的出现次数 → 与 base 计数之差即**裸写（无注音）**；
  * 裸写样例（标出是否疑似跨 ruby 边界）；
  * `--cache` 时对缓存日文目录做同样聚合并逐项对比。

显式传源目录，不写死任何个人环境路径。

用法：
    python tools/check_bw_ruby_anchor.py --bw "<BW 提取源目录>" --word 妹達
    python tools/check_bw_ruby_anchor.py --bw "<BW 提取源目录>" --word 妹達 ^
        --cache .cache/epub-work/japanese-text --tsv .cache/bw-ruby-anchor.tsv
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

RUBY_RE = re.compile(r"<ruby\b[^>]*>(.*?)</ruby>", re.S | re.I)
RT_RE = re.compile(r"<rt\b[^>]*>(.*?)</rt>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
SEG = "\x00"          # ruby 段的定界符
RUBY_MARK = "\x01"    # 正文中 ruby 段的占位符（用于识别裸写/跨边界）
XHTML_EXT = (".xhtml", ".html", ".htm")


def flatten(text: str) -> str:
    """把每个 <ruby> 归一化为 SEG base|rt1+rt2 SEG，其它标签一律去掉。"""

    def repl(m: re.Match) -> str:
        inner = m.group(1)
        rts = "+".join(RT_RE.findall(inner))
        base = TAG_RE.sub("", RT_RE.sub("", inner))
        return f"{SEG}{base}|{rts}{SEG}"

    return TAG_RE.sub("", RUBY_RE.sub(repl, text))


def split_flat(flat: str) -> tuple[list[str], str]:
    """拆出 ruby 段列表，以及把 ruby 段替换为占位符后的正文。"""
    segs: list[str] = []
    out: list[str] = []
    pos = 0
    while True:
        start = flat.find(SEG, pos)
        if start < 0:
            out.append(flat[pos:])
            break
        end = flat.find(SEG, start + 1)
        if end < 0:
            out.append(flat[pos:])
            break
        out.append(flat[pos:start])
        out.append(RUBY_MARK)
        segs.append(flat[start + 1:end])
        pos = end + 1
    return segs, "".join(out)


def new_stats(words: list[str]) -> dict:
    return {w: {"base_forms": Counter(), "rt_forms": Counter(), "body": 0,
                "bare_samples": []} for w in words}


def scan_text(text: str, words: list[str], stats: dict, origin: str = "") -> None:
    flat = flatten(text)
    segs, body = split_flat(flat)
    for seg in segs:
        base, _, rt = seg.partition("|")
        for w in words:
            if w in base:
                stats[w]["base_forms"][(base, rt)] += 1
            if w in rt:
                stats[w]["rt_forms"][(base, rt)] += 1
    for w in words:
        for m in re.finditer(re.escape(w), body):
            stats[w]["body"] += 1
            if len(stats[w]["bare_samples"]) < 6:
                left = body[m.start() - 1:m.start()]
                right = body[m.end():m.end() + 1]
                cross = "（疑似跨 ruby 边界）" if left == RUBY_MARK or right == RUBY_MARK else ""
                frag = body[max(0, m.start() - 45): m.end() + 60]
                frag = frag.replace(RUBY_MARK, "⟦ruby⟧").replace("\n", " ").strip()
                stats[w]["bare_samples"].append(f"{origin}: …{frag}…{cross}")


def scan_source(bw: Path, words: list[str]) -> tuple[dict, int]:
    stats = new_stats(words)
    epubs = sorted(p for p in bw.rglob("*.epub") if p.is_file())
    for ep in epubs:
        try:
            zf = zipfile.ZipFile(ep)
        except Exception as exc:
            print(f"[警告] 无法读取 {ep.name}: {exc}", file=sys.stderr)
            continue
        with zf:
            for name in zf.namelist():
                if not name.lower().endswith(XHTML_EXT):
                    continue
                try:
                    raw = zf.read(name).decode("utf-8", "replace")
                except Exception:
                    continue
                if not any(w in raw for w in words):
                    continue
                scan_text(raw, words, stats, f"{ep.name} / {Path(name).name}")
    return stats, len(epubs)


def scan_cache(cache: Path, words: list[str]) -> dict:
    stats = new_stats(words)
    for f in sorted(cache.rglob("*.xhtml")):
        raw = f.read_text(encoding="utf-8", errors="replace")
        if not any(w in raw for w in words):
            continue
        scan_text(raw, words, stats, f.name)
    return stats


def report(title: str, stats: dict, words: list[str]) -> int:
    bare_total = 0
    print(f"\n===== {title} =====")
    for w in words:
        s = stats[w]
        base_total = sum(s["base_forms"].values())
        rt_total = sum(s["rt_forms"].values())
        bare = s["body"]          # body 已排除 ruby base 内容，剩下的就是裸写
        bare_total += bare
        print(f"\n锚点词「{w}」")
        print(f"  带注音（ruby base 内含该词）：{base_total} 处 / {len(s['base_forms'])} 种形态")
        for (b, r), c in s["base_forms"].most_common(10):
            print(f"    {c:>5}  base=「{b}」 rt=「{r}」")
        if rt_total:
            print(f"  作为注音（rt 内含该词）：{rt_total} 处")
            for (b, r), c in s["rt_forms"].most_common(6):
                print(f"    {c:>5}  base=「{b}」 rt=「{r}」")
        print(f"  正文（去注音）中出现 {bare} 次 → 裸写（无注音）{bare} 处")
        print(f"  该词总出现处数 = 带注音 {base_total} + 裸写 {bare} = {base_total + bare}")
        for smp in s["bare_samples"]:
            print(f"    裸写: {smp}")
    return bare_total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="核对 BW 分页源中锚点词的 ruby 注音形态（只读）")
    ap.add_argument("--bw", required=True, help="BW 提取源目录（含 *.epub；显式传入，不写死路径）")
    ap.add_argument("--word", action="append", default=None, help="锚点词，可重复；默认 妹達")
    ap.add_argument("--cache", default=None, help="缓存日文目录，做同样聚合并逐项对比")
    ap.add_argument("--tsv", default=None, help="把形态计数写入 TSV")
    args = ap.parse_args(argv)

    words = args.word or ["妹達"]
    bw = Path(args.bw)
    if not bw.is_dir():
        print(f"[错误] BW 源目录不存在: {bw}", file=sys.stderr)
        return 2

    src, n_epub = scan_source(bw, words)
    report(f"BW 源：{bw}（{n_epub} 本 epub）", src, words)

    rows: list[str] = ["side\tword\tkind\tbase\trt\tcount"]
    for w in words:
        for (b, r), c in src[w]["base_forms"].items():
            rows.append(f"source\t{w}\tbase\t{b}\t{r}\t{c}")
        for (b, r), c in src[w]["rt_forms"].items():
            rows.append(f"source\t{w}\trt\t{b}\t{r}\t{c}")
        rows.append(f"source\t{w}\tbody\t\t\t{src[w]['body']}")

    rc = 0
    if args.cache:
        cache = Path(args.cache)
        if not cache.is_dir():
            print(f"[错误] 缓存目录不存在: {cache}", file=sys.stderr)
            return 2
        cst = scan_cache(cache, words)
        report(f"缓存：{cache}", cst, words)
        print("\n===== 对比（带注音处数 / 裸写处数）=====")
        for w in words:
            sb = sum(src[w]["base_forms"].values())
            cb = sum(cst[w]["base_forms"].values())
            sbare = src[w]["body"]
            cbare = cst[w]["body"]
            same = sb == cb and sbare == cbare
            print(f"  「{w}」源 {sb}/{sbare}  缓存 {cb}/{cbare}  → {'一致' if same else '★不一致'}")
            if not same:
                rc = 1
            for (b, r), c in cst[w]["base_forms"].items():
                rows.append(f"cache\t{w}\tbase\t{b}\t{r}\t{c}")
            rows.append(f"cache\t{w}\tbody\t\t\t{cst[w]['body']}")

    if args.tsv:
        Path(args.tsv).write_text("\n".join(rows) + "\n", encoding="utf-8")
        print(f"\nTSV 已写入: {args.tsv}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
