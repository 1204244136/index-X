#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""术语锚点门禁（只读）：日文裁定锚点出现时，中文不得使用裁定表登记的误形。

## 为什么需要它

2026-09-17 全库把 `魔術` 统一为「魔法」；2026-10-05 的整卷复审重写把 98 处改回
「魔术」，随后 10-19 只补了同一裁定行的 `魔術師`，剩下的裸 `魔術` 一直留到
2026-10-27 读者反馈才被发现。既有门禁都查不到这一类：

- `text_norm` 是字符级规范化，`check_alignment`／`check_epub_health` 查结构；
- `check_translation_spec` 查标点、注音、单位；
- `check_translation_table` 用译名表的原始写法当锚，表里是 `【魔術】`（带括号），
  正文 441 处裸 `魔術` 一处也匹配不到；
- `audit_risk` 的受控术语只覆盖少量硬编码条目。

本工具补的就是这一步：**中日逐行配对，日文侧出现裁定锚点、中文侧没有裁定写法却
含裁定表登记的误形时阻断**。它不是“任何缺写法都报”——实测「日文含 `魔術` 而中文
无「魔法」」全库 728 行，绝大多数是书名、省略或改写；真正可判定的信号是**误形**
（裁定表「被否决或并存的候选」列）出现。因此默认只报「误形命中且无裁定写法」。

## 规则来源

`docs/translation-name-rulings.md`（只读解析，格式见裁定表 §12）：

- 锚点：`DEFAULT_ANCHORS` 指定的日文写法（`魔術`、`魔術師`）；
- 应作：该行「裁定」列的可接受写法；
- 误形：该行「被否决或并存的候选」列里可识别的短词。

新增锚点只改 `DEFAULT_ANCHORS`（或用 `--anchor` 临时指定），写法与误形始终从裁定表
读取，不在工具里复制第二份映射。

## 例外

`ANCHOR_CONTEXT_EXCEPTIONS` 是**日文语境**例外：塔罗牌大阿尔卡那 I 的牌名
`魔術師` 按牌名译「魔术师」，不套用术语层。例外只对指定锚点生效，且要命中日文行
（`タロット`／`大アルカナ`／`カード`）才跳过。

## 边界

只读、只报告；不判定改写方案、不写书籍、不改裁定表。命中项须回原文确认后由
术语统一流程回改（显式映射 + 逐条预检）。

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
from check_translation_table import load_rulings, norm_anchor  # noqa: E402
from epub_ids import book_id, japanese_book_id  # noqa: E402
from xhtml_structure import books_by_id, header_index  # noqa: E402
from xhtml_text import strip_ruby_annotations, text_of  # noqa: E402

DEFAULT_EPUB = REPO_ROOT / "EPUB"
DEFAULT_JP = REPO_ROOT / ".cache" / "epub-work" / "japanese-text"
DEFAULT_RULINGS = REPO_ROOT / "docs" / "translation-name-rulings.md"
DEFAULT_OUT = REPO_ROOT / ".cache" / "epub-work" / "term-anchor-check.tsv"

# 需要严格执行的裁定锚点。新增时确认该行「被否决或并存的候选」列可以直接当误形用，
# 且没有大量合法的并存义项；否则先补例外或另立裁定行。
DEFAULT_ANCHORS = ("魔術", "魔術師")

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


def load_rules(rulings_path: Path, anchors: tuple[str, ...]) -> list[dict]:
    """从裁定表读取锚点的应作写法与误形；缺锚点或解析不出写法时报错。"""
    rulings = load_rulings(rulings_path)
    rules: list[dict] = []
    for anchor in anchors:
        slot = rulings.get(norm_anchor(anchor))
        if slot is None:
            raise ValueError(f"裁定表没有锚点：{anchor}")
        accepted = [form for form in slot["forms"]
                    if 1 <= len(form) <= 10 and CJK_FORM.match(form)]
        rejected: list[str] = []
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


def audit_roots(cn_root: Path, jp_root: Path, work_ids: set[str] | None = None,
                *, anchors: tuple[str, ...] = DEFAULT_ANCHORS,
                rulings_path: Path = DEFAULT_RULINGS) -> tuple[list[dict], int, int, list[str]]:
    """配对扫描；返回 (命中行, 已核对文件数, 跳过文件数, 说明)。

    只扫描中日两侧都有、表头一致、行数一致且不在人工例外表里的正文文件。
    跳过不是“通过”：说明里会记录未配对/行数不等，统计时单列。
    """
    if not cn_root.is_dir():
        raise FileNotFoundError(f"中文成品目录不存在：{cn_root}")
    if not jp_root.is_dir():
        raise FileNotFoundError(f"日文参考目录不存在：{jp_root}")
    rules = load_rules(rulings_path, anchors)

    jp_ids = {japanese_book_id(wid) for wid in work_ids} if work_ids is not None else None
    cn_books = books_by_id(cn_root, work_ids)
    jp_books = books_by_id(jp_root, jp_ids)

    rows: list[dict] = []
    notes: list[str] = []
    checked = 0
    skipped = 0
    for wid, cn_dir in sorted(cn_books.items()):
        if wid in NON_PAIR_WORK_IDS:
            notes.append(f"{wid}: 非同一形态作品，跳过配对")
            continue
        jp_dir = jp_books.get(japanese_book_id(wid))
        if jp_dir is None:
            notes.append(f"{wid}: 缺日文参考，未核对")
            continue
        try:
            cn_by = header_index(cn_dir)
            jp_by = header_index(jp_dir)
        except ValueError as exc:
            notes.append(f"{wid}: {exc}；跳过该作品")
            continue
        for header in sorted(cn_by.keys() & jp_by.keys()):
            if header in MANUAL_ALIGNMENT_HEADERS or header in TEXTUAL_IMAGE_HEADERS or header in PAIR_RULES:
                continue
            cn_path, jp_path = cn_by[header], jp_by[header]
            cn_lines = read_lines(cn_path)
            jp_lines = read_lines(jp_path)
            if len(cn_lines) != len(jp_lines):
                skipped += 1
                notes.append(f"{wid}/{header}: 行数不等（cn={len(cn_lines)} jp={len(jp_lines)}），未核对")
                continue
            checked += 1
            for line_no, (cn_line, jp_line) in enumerate(zip(cn_lines, jp_lines), 1):
                jp_text = text_of(strip_ruby_annotations(jp_line).encode())
                if not jp_text:
                    continue
                cn_text = text_of(cn_line.encode())
                for hit in match_line(jp_text, cn_text, rules):
                    rows.append({
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
    return rows, checked, skipped, notes


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
                        help=f"锚点筛选，可重复；默认为 {'、'.join(DEFAULT_ANCHORS)}")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="TSV 报告路径")
    parser.add_argument("--top", type=int, default=20, help="终端最多列出的命中数")
    parser.add_argument("--strict", action="store_true", help="有命中时非零退出")
    args = parser.parse_args(argv)

    anchors = tuple(args.anchor) if args.anchor else DEFAULT_ANCHORS
    work_ids = {book.upper() for book in args.book} if args.book else None
    try:
        rows, checked, skipped, notes = audit_roots(
            args.epub, args.jp_dir, work_ids, anchors=anchors, rulings_path=args.rulings,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"[阻断] 术语锚点检查未完成：{exc}", file=sys.stderr)
        return 2

    print(f"术语锚点检查：锚点 {'、'.join(anchors)}；已核对文件 {checked}；跳过 {skipped}；命中 {len(rows)} 行")
    for note in notes:
        print(f"  [跳过] {note}")
    for row in rows[:max(0, args.top)]:
        print(f"  {row['book']} {row['file']}:{row['line']}  "
              f"{row['anchor']}→{row['expected']}｜现含「{row['found']}」")
        print(f"    JP: {row['jp']}")
        print(f"    CN: {row['cn']}")
    if len(rows) > args.top > 0:
        print(f"  ……另有 {len(rows) - args.top} 行，见报告 {args.out}")
    write_tsv(rows, args.out)
    print(f"报告：{args.out}")
    if rows:
        print("[阻断] 存在术语锚点误形，回原文确认后按术语统一流程回改。", file=sys.stderr)
    return 1 if (args.strict and rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
