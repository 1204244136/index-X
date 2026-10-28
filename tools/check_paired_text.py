#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中日对照文本完整性检查（只读）：整句截断阻断与注音覆盖报告。

两项检查：

- `truncation`（error）：中文对话行只剩短语，而日文对应行是完整长句。
  判据为中文行整行由一对引号包裹、引号内不含句末标点与拖长音、长度不超过
  `TRUNCATION_MAX_INNER`，且日文对应行可见长度不小于 `TRUNCATION_MIN_JP`。
  该形态在库内回测无误报，命中即阻断。
- `ruby-coverage`（报告项，不产生命中）：按配对单元统计日文术语型 ruby 行数
  与中文 ruby 行数。注音义务是术语级语义判断（`docs/translation-spec.md` 三.1：
  普通词、单纯外来语不注音），机器不做命中判定，只把比值低于
  `RUBY_COVERAGE_FLOOR` 的单元列进报告，供人工回原文复核。

只读、只报告，不修改书籍。命令合同见 `tools/README.md`「中日对照完整性」，
判据背景见 `docs/maintenance-records/paired-text-gate-2026-10-28.md`。

用法：
    python tools/check_paired_text.py
    python tools/check_paired_text.py --book S5_01_02 --strict
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output

from alignment_rules import (  # noqa: E402
    MANUAL_ALIGNMENT_HEADERS,
    NON_PAIR_WORK_IDS,
    PAIR_RULES,
    TEXTUAL_IMAGE_HEADERS,
)
from epub_ids import japanese_book_id  # noqa: E402
from xhtml_structure import books_by_id, header_index, pair_structure_problems  # noqa: E402
from xhtml_text import visible_text_of  # noqa: E402

DEFAULT_EPUB = REPO_ROOT / "EPUB"
DEFAULT_JP = REPO_ROOT / ".cache" / "epub-work" / "japanese-text"
DEFAULT_OUT = REPO_ROOT / ".cache" / "epub-work" / "paired-text-check.tsv"

# 截断判据：中文引号内长度上限、日文对应行可见长度下限。
TRUNCATION_MAX_INNER = 10
TRUNCATION_MIN_JP = 20

# 引号内出现即视为完整句或语气效果，不判截断。
SENTENCE_MARKS = frozenset("。？！…、，,.—―‐~～㊟♪☆★ \t\u3000")

# 注音覆盖报告：日文术语型 ruby 行数达到该值才参与比值统计。
RUBY_MIN_TERM_LINES = 10
RUBY_COVERAGE_FLOOR = 0.15

QUOTE_RE = re.compile(r"^[「『]([^」』]+)[」』]$")
TAG_RE = re.compile(r"<[^>]+>")
RUBY_RE = re.compile(r"<ruby\b[^>]*>(.*?)<rt\b[^>]*>(.*?)</rt\s*></ruby\s*>", re.I | re.S)
RUBY_OPEN_RE = re.compile(r"<ruby\b", re.I)
# 术语型注音：读音是片假名或拉丁（平假名读音属普通读音，不参与统计）。
KATA_RE = re.compile(r"^[\u30a0-\u30ff\u30fc\u30fbA-Za-z0-9！!？?・…\-\s]+$")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class PairedTextAudit:
    rows: list[dict] = field(default_factory=list)
    coverage: list[dict] = field(default_factory=list)
    checked: int = 0
    skipped: int = 0
    exempt_books: int = 0
    exempt_units: int = 0
    incomplete: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "完整覆盖" if not self.incomplete else "部分覆盖"

    def miss(self, note: str, units: int = 1) -> None:
        self.skipped += units
        self.incomplete.append(note)
        self.notes.append(note)


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig").splitlines()


def term_ruby_base(match: re.Match) -> tuple[str, str]:
    """返回 (基文, 读音)，基文已剥离内层标签。"""
    return TAG_RE.sub("", match.group(1)), TAG_RE.sub("", match.group(2))


def scan_pair(jp_lines: list[str], cn_lines: list[str]) -> tuple[list[tuple[int, str, str]], int, int]:
    """逐行扫描一对文件，返回 (截断命中, 日文术语型 ruby 行数, 中文 ruby 行数)。"""
    truncations: list[tuple[int, str, str]] = []
    jp_term_lines = 0
    cn_ruby_lines = 0
    for line_no, (jp, cn) in enumerate(zip(jp_lines, cn_lines), 1):
        if RUBY_OPEN_RE.search(cn):
            cn_ruby_lines += 1
        if any(
            KATA_RE.match(rt) and HAN_RE.search(base)
            for base, rt in (term_ruby_base(m) for m in RUBY_RE.finditer(jp))
        ):
            jp_term_lines += 1

        cn_text = visible_text_of(cn)
        quoted = QUOTE_RE.match(cn_text)
        if not quoted:
            continue
        inner = quoted.group(1)
        if len(inner) > TRUNCATION_MAX_INNER or (set(inner) & SENTENCE_MARKS):
            continue
        jp_text = visible_text_of(jp)
        if len(jp_text) >= TRUNCATION_MIN_JP:
            truncations.append((line_no, jp_text, cn_text))
    return truncations, jp_term_lines, cn_ruby_lines


def audit_coverage(cn_root: Path, jp_root: Path, work_ids: set[str] | None = None) -> PairedTextAudit:
    """遍历配对单元，返回截断命中与注音覆盖统计；只读。"""
    jp_ids = {japanese_book_id(wid) for wid in work_ids} if work_ids is not None else None
    cn_books = books_by_id(cn_root, work_ids)
    jp_books = books_by_id(jp_root, jp_ids)
    if not cn_books:
        raise ValueError("没有匹配的中文书籍，未执行对照完整性检查")
    unknown = (work_ids or set()) - cn_books.keys()
    if unknown:
        raise ValueError(f"中文作品不存在：{', '.join(sorted(unknown))}")

    result = PairedTextAudit()
    exceptions = MANUAL_ALIGNMENT_HEADERS | TEXTUAL_IMAGE_HEADERS | PAIR_RULES.keys()
    for wid, cn_dir in sorted(cn_books.items()):
        if wid in NON_PAIR_WORK_IDS:
            result.exempt_books += 1
            result.notes.append(f"{wid}: 已登记非同一形态作品，配对不适用")
            continue
        try:
            cn_by = header_index(cn_dir)
        except ValueError as exc:
            result.miss(f"{wid}: {exc}；该作品未核对")
            continue
        exempt_headers = cn_by.keys() & exceptions
        for header in sorted(exempt_headers):
            result.exempt_units += 1
            result.notes.append(f"{wid}/{header}: 已登记结构例外，逐行核验不适用")
        cn_by = {header: path for header, path in cn_by.items() if header not in exceptions}
        if not cn_by:
            if not exempt_headers and header_index(cn_dir, include_packaging=True):
                result.exempt_books += 1
                result.notes.append(f"{wid}: 仅有包装页，无适用正文配对单元")
            elif not exempt_headers:
                result.miss(f"{wid}: 没有可识别的正文表头，未核对")
            continue
        jp_dir = jp_books.get(japanese_book_id(wid))
        if jp_dir is None:
            result.miss(f"{wid}: 缺日文参考，未核对", len(cn_by))
            continue
        try:
            jp_by = header_index(jp_dir)
        except ValueError as exc:
            result.miss(f"{wid}: {exc}；该作品未核对", len(cn_by))
            continue
        for header, cn_path in sorted(cn_by.items()):
            jp_path = jp_by.get(header)
            if jp_path is None:
                result.miss(f"{wid}/{header}: 缺日文表头，未核对", 1)
                continue
            cn_lines = read_lines(cn_path)
            jp_lines = read_lines(jp_path)
            if not cn_lines or not jp_lines:
                result.miss(f"{wid}/{header}: 配对文件为空，未核对", 1)
                continue
            if len(cn_lines) != len(jp_lines):
                result.miss(f"{wid}/{header}: 行数不等（cn={len(cn_lines)} jp={len(jp_lines)}），未核对", 1)
                continue
            structure = pair_structure_problems(jp_lines, cn_lines)
            if structure:
                result.miss(f"{wid}/{header}: {'；'.join(structure)}，未核对", 1)
                continue
            result.checked += 1
            truncations, jp_term_lines, cn_ruby_lines = scan_pair(jp_lines, cn_lines)
            for line_no, jp_text, cn_text in truncations:
                result.rows.append({
                    "book": wid, "file": cn_path.name, "line": line_no,
                    "kind": "truncation",
                    "detail": f"日文 {len(jp_text)} 字，中文仅 {len(cn_text)} 字",
                    "jp": jp_text, "cn": cn_text,
                })
            if jp_term_lines >= RUBY_MIN_TERM_LINES:
                ratio = cn_ruby_lines / jp_term_lines
                if ratio < RUBY_COVERAGE_FLOOR:
                    result.coverage.append({
                        "book": wid, "header": header,
                        "jp_term_lines": jp_term_lines, "cn_ruby_lines": cn_ruby_lines,
                        "ratio": ratio,
                    })
    return result


def write_tsv(result: PairedTextAudit, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["作品", "文件", "行", "类型", "说明", "日文", "中文"])
        for row in result.rows:
            writer.writerow([row["book"], row["file"], row["line"], row["kind"],
                             row["detail"], row["jp"], row["cn"]])
        for row in result.coverage:
            writer.writerow([row["book"], f"{row['header']}（单元）", 0, "ruby-coverage",
                             f"日文术语行 {row['jp_term_lines']}，中文 ruby 行 {row['cn_ruby_lines']}，"
                             f"比值 {row['ratio']:.2f}", "", ""])


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(
        description="中日对照文本完整性：整句截断阻断与注音覆盖报告（只读）",
    )
    parser.add_argument("--epub", type=Path, default=DEFAULT_EPUB, help="中文成品根目录")
    parser.add_argument("--jp-dir", type=Path, default=DEFAULT_JP, help="日文参考根目录")
    parser.add_argument("--book", action="append", default=[], help="作品号筛选，可重复")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="TSV 报告路径")
    parser.add_argument("--top", type=int, default=20, help="终端最多列出的命中数")
    parser.add_argument("--strict", action="store_true",
                        help="截断命中或适用范围未完整核对时非零退出")
    args = parser.parse_args(argv)

    work_ids = {book.upper() for book in args.book} if args.book else None
    try:
        result = audit_coverage(args.epub, args.jp_dir, work_ids)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"[阻断] 对照完整性检查未完成：{exc}", file=sys.stderr)
        return 2

    rows = result.rows
    print(f"中日对照完整性检查：已核对配对单元 {result.checked}；未核对 {result.skipped}；"
          f"豁免作品 {result.exempt_books}／单元 {result.exempt_units}；"
          f"{result.status}；截断命中 {len(rows)} 行；注音覆盖异常单元 {len(result.coverage)} 个")
    for note in result.notes:
        print(f"  [跳过] {note}")
    for row in rows[:max(0, args.top)]:
        print(f"  {row['book']} {row['file']}:{row['line']}  {row['detail']}")
        print(f"    JP: {row['jp']}")
        print(f"    CN: {row['cn']}")
    if len(rows) > args.top > 0:
        print(f"  ……另有 {len(rows) - args.top} 行，见报告 {args.out}")
    if result.coverage:
        print("  注音覆盖低于 %.2f 的单元（人工复核，不阻断）：" % RUBY_COVERAGE_FLOOR)
        for row in result.coverage[:max(0, args.top)]:
            print(f"    {row['book']}/{row['header']}  日文术语行 {row['jp_term_lines']}"
                  f"，中文 ruby 行 {row['cn_ruby_lines']}，比值 {row['ratio']:.2f}")
    try:
        write_tsv(result, args.out)
    except OSError as exc:
        print(f"[阻断] 对照完整性报告未写出：{exc}", file=sys.stderr)
        return 2
    print(f"报告：{args.out}")
    if result.incomplete:
        print(f"对照完整性检查未完成：{result.status}，{len(result.incomplete)} 项缺少可靠配对。",
              file=sys.stderr)
        if args.strict:
            return 2
    if rows:
        print("[阻断] 存在疑似整句截断，回原文确认后按内容维护流程修复。", file=sys.stderr)
    return 1 if (args.strict and rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
