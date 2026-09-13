#!/usr/bin/env python3
"""统一中文缓存中「妹達（シスターズ）」的汉字写法为「妹妹／妹妹们」（默认预览，--apply 才写盘）。

背景：日文原文 `<ruby>妹達<rt>シスターズ</rt></ruby>` 全库 389 处（362 行、94 文件、36 部）。
两侧的特殊注音必须对应（中文一律 `<rt>Sisters</rt>`），差别只在**汉字**写「妹妹」还是
「妹妹们」，判定以原文指代为锚（逐处核对，规则见
`docs/maintenance-records/sisters-plural-number-ruling-2026-09-12.md`）：

  * 单数指代 38 处（场内只有一名个体、或「妹達の一人」「妹達＋検体番号」）→ 保持「妹妹」；
  * 复数但带数量·集合修饰 82 处（一万人の／全ての／他の／全妹達 等）→ 保持「妹妹」
    （中文「们」不与数量词共现，避免出现「两万名妹妹们」）；
  * 其余复数指代 269 处 → 汉字写「妹妹们」。

本工具只按**显式映射**改写，不做关键词批量替换：映射逐条记录在
`tools/sisters_plural_overrides.json`（中文文件基名、行号、第几处、原串、新串、
日文行内「妹達」处数）。任一条预检不通过即整次不写盘：

  1. 文件基名必须在缓存中唯一；
  2. 行号必须有效；
  3. 该行「妹妹<Sisters>」+「妹妹们<Sisters>」总数必须等于 `jp_occurrences`；
  4. 第 `occ` 处当前必须恰为 `old`。

日文侧与原作排版一律不动；只替换行内指定处的标签，行数与行结构不变，
中日行对齐不受影响。

用法：
    python tools/fix_sisters_plural.py                 # 预览
    python tools/fix_sisters_plural.py --apply         # 写入中文缓存
    python tools/fix_sisters_plural.py --cache 自定义/chinese-text --table 映射.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "epub-work" / "chinese-text"
DEFAULT_TABLE = Path(__file__).resolve().parent / "sisters_plural_overrides.json"
PAT = re.compile(r"妹妹(?:们)?<rt>Sisters</rt>")


def load_entries(table: Path) -> list[dict]:
    if not table.is_file():
        raise SystemExit(f"[错误] 映射表不存在: {table}")
    data = json.loads(table.read_text(encoding="utf-8"))
    entries = data["entries"] if isinstance(data, dict) else data
    return list(entries)


def find_file(cache: Path, name: str) -> Path | None:
    """在缓存中定位唯一的正文文件。"""
    hits = [p for p in cache.rglob(name) if p.is_file()]
    return hits[0] if len(hits) == 1 else None


def split_eol(line: str) -> tuple[str, str]:
    body = line.rstrip("\r\n")
    return body, line[len(body):]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="统一中文缓存中「妹達（シスターズ）」的汉字写法（默认预览）")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="中文缓存根目录")
    ap.add_argument("--table", default=str(DEFAULT_TABLE), help="映射表 JSON 路径")
    ap.add_argument("--apply", action="store_true", help="写入中文缓存；缺省只预览")
    ap.add_argument("--show", type=int, default=10, help="预览时打印的样例条数")
    args = ap.parse_args(argv)

    cache = Path(args.cache)
    if not cache.is_dir():
        print(f"[错误] 中文缓存目录不存在: {cache}", file=sys.stderr)
        return 2

    entries = load_entries(Path(args.table))
    by_file: dict[Path, list[dict]] = {}
    for e in entries:
        path = find_file(cache, e["file"])
        if path is None:
            print(f"[错误] 未找到唯一的中文正文文件: {e['file']}", file=sys.stderr)
            return 2
        by_file.setdefault(path, []).append(e)

    total = len(entries)
    changed = 0
    already = 0
    samples: list[str] = []
    problems: list[str] = []

    for path, items in sorted(by_file.items(), key=lambda kv: str(kv[0])):
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        file_edits: dict[int, dict[int, str]] = {}
        for e in items:
            ln = int(e["line"])
            occ = int(e["occ"])
            if ln < 1 or ln > len(lines):
                problems.append(f"{path.name}:{ln} 行号越界（共 {len(lines)} 行）")
                continue
            body, _ = split_eol(lines[ln - 1])
            matches = list(PAT.finditer(body))
            expect = e.get("jp_occurrences")
            if expect is not None and len(matches) != int(expect):
                problems.append(
                    f"{path.name}:{ln} 处数不符（映射要求 {expect}，实际 {len(matches)}）")
                continue
            if len(matches) < occ:
                problems.append(f"{path.name}:{ln} 第 {occ} 处不存在（仅 {len(matches)} 处）")
                continue
            cur = matches[occ - 1].group(0)
            if cur == e["new"]:
                already += 1
                continue
            if cur != e["old"]:
                problems.append(f"{path.name}:{ln} 第 {occ} 处原串不符：{cur!r} != {e['old']!r}")
                continue
            file_edits.setdefault(ln - 1, {})[occ] = e["new"]

        for idx, edits in file_edits.items():
            body, eol = split_eol(lines[idx])
            matches = list(PAT.finditer(body))
            out: list[str] = []
            last = 0
            for i, m in enumerate(matches, 1):
                out.append(body[last:m.start()])
                out.append(edits.get(i, m.group(0)))
                last = m.end()
            out.append(body[last:])
            new_body = "".join(out)
            if len(samples) < args.show:
                samples.append(f"  {path.name}:{idx + 1}\n    - {body.strip()[:180]}\n    + {new_body.strip()[:180]}")
            lines[idx] = new_body + eol
            changed += len(edits)

        if file_edits and args.apply:
            path.write_text("".join(lines), encoding="utf-8")

    print(f"映射条目 {total} 条，涉及中文文件 {len(by_file)} 个")
    print(f"待改写 {changed} 处，已符合规则 {already} 处，预检异常 {len(problems)} 条")
    if samples:
        print("\n样例（前 %d 条）：" % len(samples))
        for s in samples:
            print(s)
    if problems:
        print("\n预检异常：", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        print("[未写盘] 存在预检异常，请先修正映射表。", file=sys.stderr)
        return 2
    print("\n[写入中文缓存]" if args.apply else "\n[预览] 加 --apply 写入中文缓存")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
