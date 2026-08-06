#!/usr/bin/env python3
"""Extract and compare Japanese/Chinese EPUB terminology locally.

All generated files live below .cache/epub-work and are intentionally ignored.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from collections import defaultdict
from pathlib import Path

CN_LOCAL = Path(__file__).resolve().parents[1] / "EPUB"
CACHE = Path(__file__).resolve().parents[1] / ".cache" / "epub-work"

JP_TERM = "風力発電"
CN_TERM = "风力发电"
VOL_RE = re.compile(r"S\d+_\d+", re.I)
CN_VARIANTS = (
    "风力发电螺旋叶片", "风力发电螺旋桨", "风力发电叶片", "风力发电机组",
    "风力发电机", "风力发电柱", "风力发电系统", "风力发电",
)


def volume_id(name: str) -> str:
    m = VOL_RE.search(name)
    return m.group(0).upper() if m else name


def text_of(data: bytes) -> str:
    s = data.decode("utf-8", errors="ignore")
    s = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def records(text: str, term: str, file_name: str, volume: str) -> list[dict]:
    out = []
    for i, m in enumerate(re.finditer(re.escape(term), text), 1):
        out.append({"volume": volume, "file": file_name, "index": i,
                    "context": text[max(0, m.start() - 180):m.end() + 260]})
    return out


def read_chinese(source: Path) -> tuple[list[dict], list[str]]:
    hits, failures = [], []
    for book in sorted(source.iterdir() if source.exists() else []):
        if not book.is_dir():
            continue
        vol = volume_id(book.name)
        for f in sorted(book.rglob("*.xhtml")):
            try:
                hits.extend(records(text_of(f.read_bytes()), CN_TERM, str(f.relative_to(source)), vol))
            except Exception as exc:
                failures.append(f"{f}: {exc}")
    return hits, failures


def read_cached_japanese(source: Path) -> tuple[list[dict], list[str]]:
    hits, failures = [], []
    for f in sorted(source.rglob("*.xhtml")):
        try:
            hits.extend(records(text_of(f.read_bytes()), JP_TERM, str(f.relative_to(source)), volume_id(f.name)))
        except Exception as exc:
            failures.append(f"{f}: {exc}")
    return hits, failures


def categories(context: str) -> list[str]:
    found = [x for x in CN_VARIANTS if x != CN_TERM and x in context]
    # The bare term is only a category when no more specific noun follows it.
    return found or ([CN_TERM] if CN_TERM in context else [])


def build_report(jp: list[dict], cn: list[dict], failures: list[str]) -> dict:
    jp_by = defaultdict(list); cn_by = defaultdict(list)
    for r in jp: jp_by[r["volume"]].append(r)
    for r in cn: cn_by[r["volume"]].append(r)
    mixed = []
    for vol in sorted(set(jp_by) | set(cn_by)):
        c = cn_by[vol]
        cats = sorted({v for r in c for v in categories(r["context"])})
        if len(cats) > 1:
            mixed.append({"volume": vol, "variants": cats,
                          "japanese_hits": len(jp_by[vol]), "chinese_hits": len(c)})
    return {"japanese_hits": jp, "chinese_hits": cn, "mixed_by_volume": mixed,
            "failures": failures}


def markdown(report: dict) -> str:
    lines = ["# 风力发电术语对照报告", "", f"日文命中：{len(report['japanese_hits'])}；中文命中：{len(report['chinese_hits'])}", ""]
    lines += ["## 同卷出现多个中文译法", ""]
    if not report["mixed_by_volume"]:
        lines.append("未发现同卷多译法（仅按命中上下文归类，仍建议查看逐条上下文）。")
    else:
        lines += [f"- `{x['volume']}`：{', '.join(x['variants'])}（日文 {x['japanese_hits']} 处，中文 {x['chinese_hits']} 处）" for x in report["mixed_by_volume"]]
    lines += ["", "## 中文命中示例", ""]
    for r in report["chinese_hits"]:
        lines.append(f"- `{r['volume']}` `{r['file']}` #{r['index']}：{r['context']}")
    if report["failures"]:
        lines += ["", "## 无法读取", ""] + [f"- {x}" for x in report["failures"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cn", type=Path, default=CN_LOCAL)
    args = p.parse_args()
    extracted = CACHE / "japanese-text"
    if not extracted.exists():
        raise SystemExit("日文缓存不存在；请先手动准备 .cache/epub-work/japanese-text")
    jp, jp_fail = read_cached_japanese(extracted)
    cn, cn_fail = read_chinese(args.cn)
    report = build_report(jp, cn, jp_fail + cn_fail)
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (CACHE / "report.md").write_text(markdown(report), encoding="utf-8")
    print(f"报告：{CACHE / 'report.md'}")
    print(f"JSON：{CACHE / 'report.json'}")
    print(f"日文命中 {len(jp)}，中文命中 {len(cn)}，同卷多译法 {len(report['mixed_by_volume'])} 卷")
    if report["failures"]:
        print(f"无法读取 {len(report['failures'])} 项，详情见报告")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
