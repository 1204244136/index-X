#!/usr/bin/env python3
"""交稿 docx → 导入清单（只读诊断，新书导入第 1 步）。

把交稿的段落流摊平成可核对、可机器判定的清单：章标题、小节标题、正文段、空段、
插图占位、独占译注段，以及每段的行内记号统计（`|基文[注音]`、`<b>`、`【*译注】`、
段内换行/制表符/可疑空白）。后续 `import_align_plan.py` 与 `import_build_text.py`
都吃同一份清单口径，本工具是这条链的**材料门禁**：交稿形状不合格时非零退出，
不允许下游继续。

只写显式 `--out`／`--summary`，不碰 EPUB、缓存与 OneDrive。

用法：
    python tools/import_docx_outline.py 暗少4翻译.docx --check
    python tools/import_docx_outline.py 暗少4翻译.docx --out .cache/epub-work/outline.tsv
    python tools/import_docx_outline.py 暗少4翻译.docx --out 清单.json --format json
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from docx_source import (ILLUS_RE, NOTE_BRACKET_RE, NOTE_PAREN_RE, RUBY_RE,
                         SUSPECT_WHITESPACE, chapter_kind, read_docx)

# 交稿层面的阻断形状：固定行模板无法表达，必须先人工处理
BLOCKING = "阻断"
WARNING = "提示"


def paragraph_markers(paragraph: dict) -> dict:
    text = paragraph["text"]
    markers = {
        "ruby": len(RUBY_RE.findall(text)),
        "bold": len(re.findall(r"<b\b", text, re.I)),
        "note": len(NOTE_BRACKET_RE.findall(text)) + len(NOTE_PAREN_RE.findall(text)),
        "unclosed_marks": unclosed_marks(text),
        "tabs": paragraph.get("tabs", 0),
        "breaks": paragraph.get("breaks", 0),
        "ws": sum(text.count(char) for char in SUSPECT_WHITESPACE),
        "edge_ws": bool(text != text.strip()),
    }
    return markers


def unclosed_marks(text: str) -> list[str]:
    """检测交稿记号的开闭不配对（导入前必须修）。"""
    problems: list[str] = []
    for match in re.finditer(r"\|", text):
        if not re.match(r"\|[^|\n]*?\[[^\]\n]*\]", text[match.start():]):
            problems.append("注音记号 |基文[注音] 未闭合")
            break
    if text.count("[") != text.count("]"):
        problems.append("方括号不配对")
    opened = text.count("【*译注") + text.count("【译注")
    if opened > len(NOTE_BRACKET_RE.findall(text)):
        problems.append("译注记号【译注：…】未闭合")
    return problems


def collect(paragraphs: list[dict]) -> dict:
    rows = []
    for paragraph in paragraphs:
        kind = chapter_kind(paragraph)
        markers = paragraph_markers(paragraph)
        rows.append({
            "idx": paragraph["idx"],
            "style": paragraph["style"],
            "kind": kind,
            "markers": markers,
            "text": paragraph["text"],
        })
    return {"rows": rows}


def audit(rows: list[dict]) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    warnings: list[str] = []
    kinds = collections.Counter(row["kind"] for row in rows)
    if kinds["h1"] == 0:
        blocking.append("交稿没有 Heading 1 章标题，无法按章分文件")
    if any(row["markers"]["breaks"] for row in rows):
        offenders = [row["idx"] for row in rows if row["markers"]["breaks"]][:10]
        blocking.append(f"存在段内换行（w:br）的段落：{offenders}；固定行模板要求一段一行，须人工拆段")
    for row in rows:
        for problem in row["markers"]["unclosed_marks"]:
            blocking.append(f"段 {row['idx']}：{problem}")
    first_h1 = next((i for i, row in enumerate(rows) if row["kind"] == "h1"), len(rows))
    early_h2 = [row["idx"] for row in rows[:first_h1] if row["kind"] == "h2"]
    if early_h2:
        warnings.append(f"首个章标题之前出现小节标题：{early_h2}")
    if any(row["kind"] == "h2" for row in rows) is False and kinds["p"]:
        warnings.append("交稿没有 Heading 2 小节，章节文件将没有小节标题槽位")
    tabs = [row["idx"] for row in rows if row["markers"]["tabs"]]
    if tabs:
        warnings.append(f"段内制表符（w:tab）：{tabs[:10]}；转义后可能改变行内空白")
    ws = [row["idx"] for row in rows if row["markers"]["ws"] or row["markers"]["edge_ws"]]
    if ws:
        warnings.append(f"段内出现全角空格/不换行空格/首尾空白：{ws[:10]}；逐字导入前须确认是否原意")
    note_only = [row["idx"] for row in rows if row["kind"] == "note-only"]
    if note_only:
        warnings.append(f"独占成段的译注：{note_only}；成品须在计划里用 note_to_prev 挂到上一段")
    unnumbered = [row["idx"] for row in rows if row["kind"] == "img" and ILLUS_RE.match(row["text"].strip())
                  and ILLUS_RE.match(row["text"].strip()).group(1) is None]
    if unnumbered and kinds["img"] > len(unnumbered):
        warnings.append("插图占位混用带编号与不带编号两种写法，须在计划里显式给出图片顺序")
    return blocking, warnings


def format_tsv(rows: list[dict]) -> str:
    lines = ["idx\tstyle\tkind\truby\tbold\tnote\tbreaks\ttabs\tws\ttext"]
    for row in rows:
        m = row["markers"]
        text = row["text"].replace("\t", " ").replace("\n", " ")
        lines.append("\t".join(str(value) for value in (
            row["idx"], row["style"], row["kind"], m["ruby"], m["bold"], m["note"],
            m["breaks"], m["tabs"], m["ws"])) + "\t" + text)
    return "\n".join(lines) + "\n"


def summary_text(rows: list[dict], chapters: list[tuple[str, int]], blocking: list[str],
                 warnings: list[str]) -> str:
    kinds = collections.Counter(row["kind"] for row in rows)
    out = [
        f"段落 {len(rows)}（章标题 {kinds['h1']}／小节 {kinds['h2']}／正文 {kinds['p']}／"
        f"空段 {kinds['blank']}／插图占位 {kinds['img']}／独占译注 {kinds['note-only']}）",
        f"行内记号：注音 {sum(r['markers']['ruby'] for r in rows)} 处、"
        f"加粗 {sum(r['markers']['bold'] for r in rows)} 处、"
        f"译注 {sum(r['markers']['note'] for r in rows)} 处",
    ]
    for title, count in chapters:
        out.append(f"  · {title}：{count} 段")
    if blocking:
        out.append(f"{BLOCKING} {len(blocking)} 条：")
        out += [f"  - {item}" for item in blocking]
    if warnings:
        out.append(f"{WARNING} {len(warnings)} 条：")
        out += [f"  - {item}" for item in warnings]
    if not blocking and not warnings:
        out.append("交稿形状没有阻断项。")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="交稿 docx → 导入清单与材料门禁（只读）")
    parser.add_argument("docx", type=Path, help="交稿 .docx")
    parser.add_argument("--out", type=Path, help="清单输出文件（.tsv 或 .json）")
    parser.add_argument("--format", choices=("tsv", "json"), default=None,
                        help="清单格式；默认按 --out 扩展名")
    parser.add_argument("--summary", type=Path, help="摘要输出文件；缺省打印到终端")
    parser.add_argument("--check", action="store_true", help="只做材料门禁，不写清单")
    parser.add_argument("--top", type=int, default=5, help="终端样例条数")
    args = parser.parse_args(argv)

    if not args.docx.is_file():
        print(f"[{BLOCKING}] 交稿不存在：{args.docx}")
        return 2
    try:
        paragraphs, _, _, _ = read_docx(args.docx, collapse_whitespace=False)
    except (OSError, ValueError, KeyError) as exc:
        print(f"[{BLOCKING}] 交稿无法解析：{exc}")
        return 2

    rows = collect(paragraphs)["rows"]
    blocking, warnings = audit(rows)
    chapters = []
    for row in rows:
        if row["kind"] == "h1":
            chapters.append([row["text"].strip(), 0])
        elif chapters:
            chapters[-1][1] += 1
    text = summary_text(rows, [(title, count) for title, count in chapters], blocking, warnings)

    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(text, encoding="utf-8", newline="\n")
    print(text, end="")

    if args.out and not args.check:
        fmt = args.format or ("json" if args.out.suffix.casefold() == ".json" else "tsv")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            payload = {"docx": str(args.docx), "rows": rows,
                       "chapters": [{"title": t, "rows": c} for t, c in chapters],
                       "blocking": blocking, "warnings": warnings}
            args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8", newline="\n")
        else:
            args.out.write_text(format_tsv(rows), encoding="utf-8", newline="\n")
        print(f"清单：{args.out}")

    for row in rows[:args.top]:
        if row["kind"] in ("h1", "h2"):
            print(f"  [{row['kind']}] {row['idx']}: {row['text'][:60]}")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
