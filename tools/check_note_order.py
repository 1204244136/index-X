#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查 Note 文件的阅读顺序和稳定 ID 引用完整性。只读。

判定标准：
- Note 文件（如 S1_01-Note.xhtml）中的 <li epub:type="footnote" id="noteN"> 条目
  应按正文中 noteref 首次引用顺序排列，已有 ID 保持不变；
- 报告以下问题：列表顺序 != 正文首次出现顺序、被引用但未定义、
  已定义但正文未引用（孤儿注释）、ID 重复定义。
  ID 不要求连续或按数值递增。

正文文件按表头内容序（如 S1_01-02 < S1_01-03）排序后逐行扫描，
取每个注释 id 的首次引用位置作为“书中出现顺序”。只读，不修改缓存。
"""
import os
import re
import sys
import json
import argparse
import csv
from collections import Counter

if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output
from notes_core import (
    NOTEFILE_RE,
    gather_refs,
    parse_note_ids,
    read_text,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE = os.path.join(REPO_ROOT, ".cache", "epub-work", "chinese-text")
DEFAULT_OUTPUT = os.path.join(REPO_ROOT, ".cache", "epub-work")

def read(path):
    return read_text(path)


def parse_note_file(path):
    """返回 Note 文件中的定义列表 (id 顺序)。"""
    return parse_note_ids(read(path))


def check_book(book, text_dir, nf):
    """检查单本 Note 文件，返回 (per_book_entry, issues)。"""
    note_basename = os.path.basename(nf)
    note_path = os.path.join(text_dir, nf)
    def_order = parse_note_file(note_path)
    appearance, all_refs = gather_refs(text_dir, note_basename)
    appear_order = list(appearance.keys())

    defined = set(def_order)
    referenced = set(all_refs.keys())
    missing_defs = [i for i in appear_order if i not in defined]
    orphan_defs = [i for i in def_order if i not in referenced]
    order_mismatch = def_order != appear_order

    duplicate_defs = [note_id for note_id, count in Counter(def_order).items() if count > 1]

    issues = []
    if duplicate_defs:
        issues.append("Note 文件重复定义 ID: " + ", ".join(duplicate_defs))
    if order_mismatch:
        issues.append("note 文件列表顺序 != 书中首次出现顺序")
    if missing_defs:
        issues.append("被引用但 Note 文件未定义: " + ", ".join(missing_defs))
    if orphan_defs:
        issues.append("Note 文件已定义但正文未引用: " + ", ".join(orphan_defs))

    entry = {
        "note_file": nf,
        "defined_order": def_order,
        "appearance_order": appear_order,
        "first_appearance": {k: {"file": v[0], "line": v[1]} for k, v in appearance.items()},
        "issues": issues,
    }
    return entry, issues


def main():
    configure_output()
    ap = argparse.ArgumentParser(description="检查 Note 条目首引顺序与稳定 ID 引用完整性（只读）")
    ap.add_argument("--root", default=None,
                    help="EPUB 根目录或中文缓存根目录（若指定则优先使用）")
    ap.add_argument("--cache", default=DEFAULT_CACHE,
                    help="中文缓存根目录（默认 .cache/epub-work/chinese-text）")
    ap.add_argument("--output", default=DEFAULT_OUTPUT,
                    help="报告输出目录（默认 .cache/epub-work）")
    ap.add_argument("--pattern", default=None,
                    help="按书名子串筛选要检查的书，如 '*S1_01*'")
    args = ap.parse_args()

    root = args.root or args.cache
    if not os.path.isdir(root):
        print(f"[错误] 中文输入根目录不存在或不是目录：{root}", file=sys.stderr)
        return 2
    problems = []
    per_book = {}
    books = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    if args.pattern:
        pat = args.pattern.replace("*", ".*")
        books = [b for b in books if re.search(pat, b)]

    for book in books:
        text_dir = os.path.join(root, book, "OEBPS", "Text")
        if not os.path.isdir(text_dir):
            continue
        note_files = [f for f in os.listdir(text_dir) if NOTEFILE_RE.match(f)]
        if not note_files:
            continue
        for nf in note_files:
            entry, issues = check_book(book, text_dir, nf)
            per_book[book] = entry
            if issues:
                problems.append((book, nf, issues))

    # 终端输出
    if problems:
        print("发现 %d 本存在 Note 顺序/ID 问题：\n" % len(problems))
        for book, nf, issues in problems:
            print("=" * 70)
            print("书: %s  文件: %s" % (book, nf))
            for it in issues:
                print("  - " + it)
            data = per_book[book]
            print("  Note 文件定义顺序: %s" % ", ".join(data["defined_order"]))
            print("  正文首次出现顺序: %s" % ", ".join(data["appearance_order"]))
            print("  首次出现位置:")
            for k, v in data["first_appearance"].items():
                print("    %s -> %s:%s" % (k, v["file"], v["line"]))
    else:
        print("所有 Note 条目均按正文首次引用顺序排列，ID 引用完整且无重复定义。")
    print("\n共检查 %d 本书。" % len(per_book))

    # 报告写入
    if args.output:
        try:
            os.makedirs(args.output, exist_ok=True)
            # JSON 详细结果
            json_path = os.path.join(args.output, "note-order-check.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(per_book, f, ensure_ascii=False, indent=2)
            print("详细结果已写入: %s" % json_path)

            tsv_path = os.path.join(args.output, "note-order-check.tsv")
            with open(tsv_path, "w", encoding="utf-8", newline="") as f:
                fields = ["book", "note_file", "defined_order", "appearance_order", "first_appearance", "issues"]
                writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
                writer.writeheader()
                for book, entry in per_book.items():
                    writer.writerow({
                        "book": book,
                        "note_file": entry["note_file"],
                        **{key: json.dumps(entry[key], ensure_ascii=False) for key in fields[2:]},
                    })
            print("TSV 报告已写入: %s" % tsv_path)

            # Markdown 文本报告
            md_path = os.path.join(args.output, "note-order-check.md")
            lines = ["# 中文 Note 注释顺序/ID 检查报告\n"]
            if problems:
                lines.append("发现 **%d** 本存在 Note 顺序/ID 问题：\n" % len(problems))
                for book, nf, issues in problems:
                    lines.append("## %s（%s）\n" % (book, nf))
                    for it in issues:
                        lines.append("- " + it)
                    data = per_book[book]
                    lines.append("\n- Note 文件定义顺序：`%s`" % ", ".join(data["defined_order"]))
                    lines.append("- 正文首次出现顺序：`%s`" % ", ".join(data["appearance_order"]))
                    lines.append("\n首次出现位置：")
                    for k, v in data["first_appearance"].items():
                        lines.append("- %s → `%s:%s`" % (k, v["file"], v["line"]))
                    lines.append("")
            else:
                lines.append("所有 Note 条目均按正文首次引用顺序排列，ID 引用完整且无重复定义。\n")
            lines.append("\n共检查 %d 本书。\n" % len(per_book))
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            print("文本报告已写入: %s" % md_path)
        except OSError as e:
            print("[错误] 无法写入报告文件：%s" % e, file=sys.stderr)
            return 2

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
