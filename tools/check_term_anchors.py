#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""术语锚点门禁（只读）：日文裁定锚点出现时，中文不得使用裁定表登记的误形。

中日逐行配对，只报「日文含裁定锚点、中文含误形且无裁定写法」；
书名、省略或改写也可能缺少裁定写法，因此仅缺写法不作为命中。
写法与误形从 `docs/translation-name-rulings.md` 读取，锚点取该表 §五「机检」列
标记的行（或用 --anchor 指定）；日文语境例外由 ANCHOR_CONTEXT_EXCEPTIONS 定义。

只读、只报告，不判定改写方案。命令合同见 `tools/README.md`「术语锚点门禁」，
建立背景与历史回测见 `docs/maintenance-records/term-anchor-gate-2026-10-27.md`。

用法：
    python tools/check_term_anchors.py
    python tools/check_term_anchors.py --book S5_01_02 --book S5_01_01 --strict
    python tools/check_term_anchors.py --anchor 魔術 --anchor 魔術師
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
from check_translation_table import body_markup, load_rulings, norm_anchor  # noqa: E402
from epub_ids import book_id, japanese_book_id  # noqa: E402
from xhtml_structure import books_by_id, header_index, pair_structure_problems  # noqa: E402
from xhtml_text import text_of_without_ruby_compact  # noqa: E402

DEFAULT_EPUB = REPO_ROOT / "EPUB"
DEFAULT_JP = REPO_ROOT / ".cache" / "epub-work" / "japanese-text"
DEFAULT_RULINGS = REPO_ROOT / "docs" / "translation-name-rulings.md"
DEFAULT_OUT = REPO_ROOT / ".cache" / "epub-work" / "term-anchor-check.tsv"

# 机检锚点由裁定表 §五 的「机检」列决定（该列填「是」的行纳入），本模块不再维护常量清单：
# 新增锚点只需在裁定表标记该行。纳入条件见裁定表 §四.8。

# 日文语境例外：锚点 → 命中即整行跳过的正则。
ANCHOR_CONTEXT_EXCEPTIONS = {
    # 塔罗牌大阿尔卡那 I：牌名按中文通行牌名译「魔术师」（裁定表 §五 牌名例外）。
    "魔術師": re.compile(r"タロット|大アルカナ|カード"),
}

# 可当误形用的短词：限定长度与字符集，把候选列里的说明性散文挡在外面。
CJK_FORM = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9·・\-〜]+$")
FORM_SPLIT = re.compile(r"[／/]")
PAREN = re.compile(r"（[^）]*）|\([^)]*\)")
TAG = re.compile(r"<[^>]+>")


def form_list(cell: str) -> list[str]:
    """把裁定表单元格拆成可识别的短词；散文说明与长句直接丢弃。"""
    out: list[str] = []
    for part in FORM_SPLIT.split(cell or ""):
        part = PAREN.sub("", part).replace("**", "").replace("`", "").strip()
        if 1 <= len(part) <= 10 and CJK_FORM.match(part):
            out.append(part)
    return list(dict.fromkeys(out))


def machine_anchors(rulings_path: Path) -> tuple[str, ...]:
    """按裁定表「机检」列取锚点，保持表内登记顺序；未标记的行不参与机检。"""
    anchors: list[str] = []
    for slot in load_rulings(rulings_path).values():
        if not slot.get("machine"):
            continue
        for anchor in slot["ori_raw"]:
            if anchor not in anchors:
                anchors.append(anchor)
    return tuple(anchors)


def load_rules(rulings_path: Path, anchors: tuple[str, ...]) -> list[dict]:
    """从裁定表读取锚点的应作写法与误形；缺锚点或解析不出写法时报错。

    同一锚点可能有多行登记（如 `魔術師` 的牌名例外行）。机检只取「机检」列为「是」的
    登记行：例外行的写法（牌名「魔术师」）按语境豁免，不能并进无条件写法，否则门禁
    会把该锚点的误形当成合规写法而永远不报（2026-11-04 查出）。
    """
    rulings = load_rulings(rulings_path)
    rules: list[dict] = []
    for anchor in anchors:
        slot = rulings.get(norm_anchor(anchor))
        if slot is None:
            raise ValueError(f"裁定表没有锚点：{anchor}")
        machine_rows = [row for row in slot.get("rows", []) if row.get("machine")]
        if machine_rows:
            accepted = [form for row in machine_rows for form in row["forms"]
                        if 1 <= len(form) <= 10 and CJK_FORM.match(form)]
            accepted = list(dict.fromkeys(accepted))
            rejected: list[str] = []
            for row in machine_rows:
                rejected.extend(form_list(row["alt_raw"]))
        else:
            accepted = [form for form in slot["forms"]
                        if 1 <= len(form) <= 10 and CJK_FORM.match(form)]
            rejected = []
            for raw in slot["alt_raw"]:
                rejected.extend(form_list(raw))
        rejected = [form for form in dict.fromkeys(rejected) if form not in accepted]
        if not accepted or not rejected:
            raise ValueError(f"锚点 {anchor} 解析不出裁定写法或误形")
        rules.append({
            "anchor": anchor,
            "accepted": accepted,
            "rejected": rejected,
            "exception": ANCHOR_CONTEXT_EXCEPTIONS.get(anchor),
        })
    # 长锚点先匹配：`魔術師` 必须在 `魔術` 之前吃掉，否则短锚点会重复计数。
    return sorted(rules, key=lambda rule: len(rule["anchor"]), reverse=True)


def split_forms(values: list[str]) -> str:
    return "／".join(values)


def excerpt(text: str, width: int = 40) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= width else text[:width] + "…"


def match_line(jp_text: str, cn_text: str, rules: list[dict]) -> list[dict]:
    """一行内逐锚点判定；返回命中（未命中时返回空列表）。"""
    remaining = jp_text
    hits: list[dict] = []
    for rule in rules:
        anchor = rule["anchor"]
        count = remaining.count(anchor)
        if not count:
            continue
        remaining = remaining.replace(anchor, "\u3000" * len(anchor))
        if rule["exception"] is not None and rule["exception"].search(jp_text):
            continue
        if any(form in cn_text for form in rule["accepted"]):
            continue
        found = [form for form in rule["rejected"] if form in cn_text]
        if not found:
            continue
        hits.append({
            "anchor": anchor,
            "expected": split_forms(rule["accepted"]),
            "found": split_forms(found),
            "count": count,
        })
    return hits


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig").splitlines()


@dataclass
class TermAnchorAudit:
    """Findings and coverage are independent: no findings do not prove coverage."""

    rows: list[dict] = field(default_factory=list)
    checked: int = 0
    skipped: int = 0
    exempt_books: int = 0
    exempt_units: int = 0
    notes: list[str] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)

    def miss(self, message: str, files: int = 0) -> None:
        self.notes.append(message)
        self.incomplete.append(message)
        self.skipped += files

    @property
    def status(self) -> str:
        if self.incomplete:
            return "部分覆盖" if self.checked else "零覆盖"
        return "完整覆盖" if self.checked else "无适用配对单元"


def audit_coverage(cn_root: Path, jp_root: Path, work_ids: set[str] | None = None,
                   *, anchors: tuple[str, ...] | None = None,
                   rulings_path: Path = DEFAULT_RULINGS) -> TermAnchorAudit:
    """Audit Chinese content units and retain every reason for missing coverage.

    Packaging is outside the line-pair scan. Reviewed structural exceptions are
    distinct from missing references, duplicate headers and unequal line counts.
    `anchors=None` 取裁定表「机检」列标记的锚点。
    """
    if not cn_root.is_dir():
        raise FileNotFoundError(f"中文成品目录不存在：{cn_root}")
    if not jp_root.is_dir():
        raise FileNotFoundError(f"日文参考目录不存在：{jp_root}")
    if anchors is None:
        anchors = machine_anchors(rulings_path)
    if not anchors:
        raise ValueError("裁定表没有标记「机检」的锚点")
    rules = load_rules(rulings_path, anchors)

    jp_ids = {japanese_book_id(wid) for wid in work_ids} if work_ids is not None else None
    cn_books = books_by_id(cn_root, work_ids)
    jp_books = books_by_id(jp_root, jp_ids)
    if not cn_books:
        raise ValueError("没有匹配的中文书籍，未执行术语锚点检查")
    unknown = (work_ids or set()) - cn_books.keys()
    if unknown:
        raise ValueError(f"中文作品不存在：{', '.join(sorted(unknown))}")

    result = TermAnchorAudit()
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
            result.notes.append(f"{wid}/{header}: 已登记结构例外，逐行术语核验不适用")
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
            cn_body = body_markup("\n".join(cn_lines), preserve_lines=True)
            jp_body = body_markup("\n".join(jp_lines), preserve_lines=True)
            cn_text = text_of_without_ruby_compact(cn_body.encode())
            jp_text = text_of_without_ruby_compact(jp_body.encode())
            if not cn_text and not jp_text and all(
                    re.search(r"<(?:[\w.-]+:)?(?:img|svg)\b", markup, re.I)
                    for markup in (cn_body, jp_body)):
                result.exempt_units += 1
                result.notes.append(f"{wid}/{header}: 非文字配对（纯图片），逐行术语核验不适用")
                continue
            if not cn_text or not jp_text:
                result.miss(f"{wid}/{header}: 配对文件缺少可核验正文文字，未核对", 1)
                continue
            if len(cn_lines) != len(jp_lines):
                result.miss(f"{wid}/{header}: 行数不等（cn={len(cn_lines)} jp={len(jp_lines)}），未核对", 1)
                continue
            structure = pair_structure_problems(jp_lines, cn_lines)
            if structure:
                result.miss(f"{wid}/{header}: {'；'.join(structure)}，未核对", 1)
                continue
            result.checked += 1
            for line_no, (cn_line, jp_line) in enumerate(zip(cn_body.split("\n"), jp_body.split("\n")), 1):
                jp_text = text_of_without_ruby_compact(jp_line.encode())
                if not jp_text:
                    continue
                cn_text = text_of_without_ruby_compact(cn_line.encode())
                for hit in match_line(jp_text, cn_text, rules):
                    result.rows.append({
                        "book": wid,
                        "file": cn_path.name,
                        "line": line_no,
                        "anchor": hit["anchor"],
                        "expected": hit["expected"],
                        "found": hit["found"],
                        "count": hit["count"],
                        "jp": excerpt(jp_text),
                        "cn": excerpt(cn_text),
                    })
    return result


def audit_roots(cn_root: Path, jp_root: Path, work_ids: set[str] | None = None,
                *, anchors: tuple[str, ...] | None = None,
                rulings_path: Path = DEFAULT_RULINGS) -> tuple[list[dict], int, int, list[str]]:
    """Compatibility tuple: findings, checked files, uncovered files, notes."""
    result = audit_coverage(cn_root, jp_root, work_ids, anchors=anchors, rulings_path=rulings_path)
    return result.rows, result.checked, result.skipped, result.notes


def write_tsv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["作品", "文件", "行", "锚点", "应作", "现含", "日文", "中文"])
        for row in rows:
            writer.writerow([row["book"], row["file"], row["line"], row["anchor"],
                             row["expected"], row["found"], row["jp"], row["cn"]])


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(
        description="裁定表锚点门禁：日文出现锚点、中文却用裁定表登记的误形时报出（只读）",
    )
    parser.add_argument("--epub", type=Path, default=DEFAULT_EPUB, help="中文成品根目录")
    parser.add_argument("--jp-dir", type=Path, default=DEFAULT_JP, help="日文参考根目录")
    parser.add_argument("--rulings", type=Path, default=DEFAULT_RULINGS, help="译名裁定总表")
    parser.add_argument("--book", action="append", default=[], help="作品号筛选，可重复")
    parser.add_argument("--anchor", action="append", default=[],
                        help="锚点筛选，可重复；默认为裁定表 §五「机检」列标记的锚点")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="TSV 报告路径")
    parser.add_argument("--top", type=int, default=20, help="终端最多列出的命中数")
    parser.add_argument("--strict", action="store_true", help="误形命中或适用范围未完整核对时非零退出")
    args = parser.parse_args(argv)

    work_ids = {book.upper() for book in args.book} if args.book else None
    try:
        anchors = tuple(args.anchor) if args.anchor else machine_anchors(args.rulings)
        result = audit_coverage(
            args.epub, args.jp_dir, work_ids, anchors=anchors, rulings_path=args.rulings,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"[阻断] 术语锚点检查未完成：{exc}", file=sys.stderr)
        return 2

    rows = result.rows
    print(f"术语锚点检查：锚点 {'、'.join(anchors)}；已核对文件 {result.checked}；"
          f"未核对文件 {result.skipped}；豁免作品 {result.exempt_books}／单元 {result.exempt_units}；"
          f"{result.status}；命中 {len(rows)} 行")
    for note in result.notes:
        print(f"  [跳过] {note}")
    for row in rows[:max(0, args.top)]:
        print(f"  {row['book']} {row['file']}:{row['line']}  "
              f"{row['anchor']}→{row['expected']}｜现含「{row['found']}」")
        print(f"    JP: {row['jp']}")
        print(f"    CN: {row['cn']}")
    if len(rows) > args.top > 0:
        print(f"  ……另有 {len(rows) - args.top} 行，见报告 {args.out}")
    try:
        write_tsv(rows, args.out)
    except OSError as exc:
        print(f"[阻断] 术语锚点报告未写出：{exc}", file=sys.stderr)
        return 2
    print(f"报告：{args.out}")
    if result.incomplete:
        print(f"术语锚点检查未完成：{result.status}，{len(result.incomplete)} 项缺少可靠配对。", file=sys.stderr)
        if args.strict:
            return 2
    if rows:
        print("[阻断] 存在术语锚点误形，回原文确认后按术语统一流程回改。", file=sys.stderr)
    return 1 if (args.strict and rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
