#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查中文缓存 Note 文件：注释列表顺序/编号是否与书中首次出现顺序一致。只读。

判定标准：
- Note 文件（如 S1_01-Note.xhtml）中的 <li epub:type="footnote" id="noteN"> 条目
  应按正文中 noteref 首次引用顺序排列，编号应与之对应；
- 报告以下问题：列表顺序 != 正文首次出现顺序、被引用但未定义、
  已定义但正文未引用（孤儿注释）、id 数值顺序乱序。

正文文件按表头内容序（如 S1_01-02 < S1_01-03）排序后逐行扫描，
取每个注释 id 的首次引用位置作为“书中出现顺序”。只读，不修改缓存。
"""
import os
import re
import sys
import json
import argparse
from collections import OrderedDict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE = os.path.join(REPO_ROOT, ".cache", "epub-work", "chinese-text")
DEFAULT_OUTPUT = os.path.join(REPO_ROOT, ".cache", "epub-work")

NOTEFILE_RE = re.compile(r"^(.*)-Note\.xhtml$")
LI_RE = re.compile(r'<li\b[^>]*\bid="(note[^"]+)"', re.S)
ANCHOR_RE = re.compile(r"<a\b[^>]*>", re.I)
HREF_NOTE_RE = re.compile(r'href="([^"]*#(note[^"]+))"', re.I)
CONTENTSEQ_RE = re.compile(r"-(\d+)(?:_|[A-Za-z])")


def read(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def parse_note_file(path):
    """返回 Note 文件中的定义列表 (id 顺序)。"""
    content = read(path)
    return [m.group(1) for m in LI_RE.finditer(content)]


def book_order_key(filename, note_basename):
    """排序键：有内容序的按 (0, seq, name)，无内容序的按 (1, 0, name)。"""
    if filename == note_basename:
        return (2, 0, filename)
    m = CONTENTSEQ_RE.search(filename)
    if m:
        return (0, int(m.group(1)), filename)
    return (1, 0, filename)


def gather_refs(text_dir, note_basename):
    """在阅读顺序下收集每个 note id 的首次引用位置。

    返回 (appearance, all_refs)：
    - appearance: OrderedDict {note_id: (file, line, order_index)}
    - all_refs:   OrderedDict {note_id: [(file, line), ...]}
    """
    files = [f for f in os.listdir(text_dir) if f.endswith(".xhtml")]
    files.sort(key=lambda f: book_order_key(f, note_basename))
    appearance = OrderedDict()
    all_refs = OrderedDict()
    for order_idx, fn in enumerate(files):
        if fn == note_basename:
            continue
        path = os.path.join(text_dir, fn)
        try:
            lines = read(path).splitlines()
        except Exception:
            continue
        for ln, line in enumerate(lines, 1):
            for am in ANCHOR_RE.finditer(line):
                tag = am.group(0)
                if 'epub:type="noteref"' not in tag.lower():
                    continue
                hm = HREF_NOTE_RE.search(tag)
                if not hm:
                    continue
                note_id = hm.group(2)
                all_refs.setdefault(note_id, []).append((fn, ln))
                if note_id not in appearance:
                    appearance[note_id] = (fn, ln, order_idx)
    return appearance, all_refs


def parse_order_index(note_id):
    """把 note2.1 / note10 这类 id 解析成可排序数值。"""
    m = re.match(r"^note(\d+)(?:\.(\d+))?$", note_id)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2) or 0))


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

    def_numeric = [parse_order_index(i) for i in def_order]
    id_unsorted = any(a is not None and b is not None and a > b
                      for a, b in zip(def_numeric, def_numeric[1:]))
    ref_numeric = [parse_order_index(i) for i in appear_order]
    ref_id_unsorted = any(a is not None and b is not None and a > b
                          for a, b in zip(ref_numeric, ref_numeric[1:]))

    issues = []
    if order_mismatch:
        issues.append("note 文件列表顺序 != 书中首次出现顺序")
    if missing_defs:
        issues.append("被引用但 Note 文件未定义: " + ", ".join(missing_defs))
    if orphan_defs:
        issues.append("Note 文件已定义但正文未引用: " + ", ".join(orphan_defs))
    if id_unsorted:
        issues.append("Note 文件内 id 数值顺序乱序")
    if ref_id_unsorted:
        issues.append("正文首次出现顺序与 id 数值顺序不一致")

    entry = {
        "note_file": nf,
        "defined_order": def_order,
        "appearance_order": appear_order,
        "first_appearance": {k: {"file": v[0], "line": v[1]} for k, v in appearance.items()},
        "issues": issues,
    }
    return entry, issues


def main():
    ap = argparse.ArgumentParser(description="检查中文缓存 Note 注释顺序/编号是否与正文首次出现顺序一致（只读）")
    ap.add_argument("--cache", default=DEFAULT_CACHE,
                    help="中文缓存根目录（默认 .cache/epub-work/chinese-text）")
    ap.add_argument("--output", default=DEFAULT_OUTPUT,
                    help="报告输出目录（默认 .cache/epub-work）")
    ap.add_argument("--pattern", default=None,
                    help="按书名子串筛选要检查的书，如 '*S1_01*'")
    args = ap.parse_args()

    root = args.cache
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
        print("所有 Note 文件的顺序与 ID 均与正文首次出现顺序一致。")
    print("\n共检查 %d 本书。" % len(per_book))

    # JSON 详细结果
    json_path = os.path.join(args.output, "note-order-check.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(per_book, f, ensure_ascii=False, indent=2)
    print("详细结果已写入: %s" % json_path)

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
        lines.append("所有 Note 文件的顺序与 ID 均与正文首次出现顺序一致。\n")
    lines.append("\n共检查 %d 本书。\n" % len(per_book))
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("文本报告已写入: %s" % md_path)


if __name__ == "__main__":
    sys.exit(main())
