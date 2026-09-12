#!/usr/bin/env python3
"""检查「科学サイド／魔術サイド」中文术语的一致性（中日配对扫描，默认只报告）。

判定口径与 tools/fix_side_term_variants.py 一致：

  * **术语层**：日文写「サイド」（973 处裸写，术语：两大阵营）时，中文应为「科学阵营／
    魔法阵营」。出现「科学势力／魔法势力／科学侧／魔法侧／科学方／魔法方／科学世界／
    魔法世界／科学营／魔法营／科学那边」等异译即报 **error**。
  * **指示层**：日文写汉字「側」（全部带指示代词注音 こちら／あちら／むこう／がわ 等）
    时，中文不应升格为「阵营」。报 **warning**。
  * 带「符号 + ruby 注音」的风格化行（创约 11 卷 CRC 口吻等）跳过，不计入。
  * 日文锚点若无中文配对文件（中文未收录），只统计不报错。

用法：
    python tools/check_side_terms.py                 # 报告并返回退出码
    python tools/check_side_terms.py --no-fail       # 只报告，始终返回 0
    python tools/check_side_terms.py --out 报告.tsv
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "epub-work"
DEFAULT_OUT = DEFAULT_CACHE / "side-term-check.tsv"

HDR = re.compile(r'^(S\d+(?:_\d+)*?(?:\.\d{2}\.\d{2})?(?:-\d+|-[A-Za-z][\w.]*))')
SCI_ALT = re.compile(r'科学(?:势力|侧|方(?!面|法)|世界|一方|那边|营(?!阵)|界)')
MAG_ALT = re.compile(r'魔法(?:势力|侧|方(?!面|法)|世界|那边|营(?!阵)|派)')
STYLE_RE = re.compile(r'<ruby>[^\w\s<]{1,2}<rt>')


def strip_tags(s: str) -> str:
    # 先去掉 <rt> 注音内容，否则「魔術サイド」被注音拆开（魔術まじゆつサイド）时会漏检
    s = re.sub(r'<rt\b[^>]*>.*?</rt>', '', s, flags=re.S)
    return re.sub(r'<[^>]+>', '', s).strip()


def header(p: Path) -> str | None:
    m = HDR.match(p.name)
    return m.group(1) if m else None


def readlines(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8", errors="replace").splitlines()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="检查科学サイド/魔術サイド 中文术语一致性")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="epub-work 根目录")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="报告 TSV 路径")
    ap.add_argument("--no-fail", action="store_true", help="只报告，不返回失败退出码")
    args = ap.parse_args(argv)

    cache = Path(args.cache)
    jp_root, cn_root = cache / "japanese-text", cache / "chinese-text"
    if not jp_root.is_dir() or not cn_root.is_dir():
        print(f"[错误] 缓存目录不存在: {jp_root} / {cn_root}", file=sys.stderr)
        return 2

    jp_by_h: dict[str, list[Path]] = collections.defaultdict(list)
    for p in sorted(jp_root.rglob("*.xhtml")):
        h = header(p)
        if h:
            jp_by_h[h].append(p)
    cn_by_h: dict[str, list[Path]] = collections.defaultdict(list)
    for p in sorted(cn_root.rglob("*.xhtml")):
        h = header(p)
        if h:
            cn_by_h[h].append(p)

    rows: list[tuple[str, str, str, int, str, str, str]] = []
    unpaired = collections.Counter()
    stats = collections.Counter()

    for h, jps in sorted(jp_by_h.items()):
        cps = cn_by_h.get(h)
        for jp in jps:
            for i, jline in enumerate(readlines(jp), 1):
                jt = strip_tags(jline)
                has_side = "科学サイド" in jt or "魔術サイド" in jt
                has_kana = "科学側" in jt or "魔術側" in jt
                if not (has_side or has_kana):
                    continue
                if not cps:
                    unpaired[h] += 1
                    continue
                for cp in cps:
                    cl = readlines(cp)
                    if i - 1 >= len(cl):
                        continue
                    cbody = cl[i - 1]
                    if STYLE_RE.search(cbody):
                        stats["style-skipped"] += 1
                        continue
                    ct = strip_tags(cbody)
                    # 按日文侧分别判定：只有日文写了对应侧的「サイド」才要求中文用「阵营」
                    if "科学サイド" in jt:
                        for m in SCI_ALT.finditer(ct):
                            if "科学側" in jt and m.group(0).endswith("侧"):
                                continue
                            rows.append(("error", h, cp.name, i, m.group(0), "科学阵营", jp.name))
                            stats["error-sci"] += 1
                    if "魔術サイド" in jt:
                        for m in MAG_ALT.finditer(ct):
                            if "魔術側" in jt and m.group(0).endswith("侧"):
                                continue
                            rows.append(("error", h, cp.name, i, m.group(0), "魔法阵营", jp.name))
                            stats["error-mag"] += 1
                    if has_kana:
                        for w in ("科学阵营", "魔法阵营"):
                            if w in ct and not ("科学サイド" in jt or "魔術サイド" in jt):
                                rows.append(("warning", h, cp.name, i, w, "侧/那边（指示层）", jp.name))
                                stats["warn"] += 1

    lines = ["level\theader\tfile\tline\tfound\texpect\tjp_file"]
    lines += ["\t".join(str(x) for x in r) for r in rows]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")

    errors = sum(1 for r in rows if r[0] == "error")
    warns = sum(1 for r in rows if r[0] == "warning")
    print(f"术语层不一致（error）：{errors} 处")
    print(f"指示层升格（warning）：{warns} 处")
    print(f"风格化行跳过：{stats['style-skipped']} 行")
    print(f"中文未收录（跳过）：{len(unpaired)} 个作品，共 {sum(unpaired.values())} 行")
    if unpaired:
        top = ", ".join(f"{k}({v})" for k, v in unpaired.most_common(8))
        print(f"  未收录作品：{top}")
    print(f"报告：{args.out}")
    if errors and not args.no_fail:
        print("\n门禁未通过：术语层仍有不一致（见报告）。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
