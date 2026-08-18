#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按正文首次出现顺序重排 Note 文件并重编号，同步更新正文引用。

- 对每本 *-Note.xhtml：计算正文 noteref 首次出现顺序；
- 按该顺序重排 <li> 条目并重编号为 note1..noteN；
- 单遍映射更新正文引用。
只读检查/写盘前先备份。--dry-run 只预览。
"""
import os
import re
import sys
import shutil
import argparse
from collections import OrderedDict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE = os.path.join(REPO_ROOT, ".cache", "epub-work", "chinese-text")
DEFAULT_BACKUP = os.path.join(REPO_ROOT, ".cache", "reorder-backup")

NOTEFILE_RE = re.compile(r"^(.*)-Note\.xhtml$")
LI_FULL_RE = re.compile(r"<li\b[^>]*>.*?</li>", re.S)
LI_ID_RE = re.compile(r'(<li\b[^>]*?\bid=")(note[^"]+)(")')
ANCHOR_RE = re.compile(r"<a\b[^>]*>", re.I)
HREF_NOTE_RE = re.compile(r'href="([^"]*#(note[^"]+))"', re.I)
CONTENTSEQ_RE = re.compile(r"-(\d+)(?:_|[A-Za-z])")


def read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def backup_file(path, backup_dir, rel):
    if not backup_dir:
        return
    bpath = os.path.join(backup_dir, rel)
    os.makedirs(os.path.dirname(bpath), exist_ok=True)
    if not os.path.exists(bpath):
        shutil.copy2(path, bpath)


def parse_note_entries(content):
    """返回 [(old_id, full_li_html), ...] 按 Note 文件当前顺序，仅含带 id 的注释条目。"""
    out = []
    for m in LI_FULL_RE.finditer(content):
        li = m.group(0)
        im = LI_ID_RE.search(li)
        if im is None:
            continue
        out.append((im.group(2), li))
    return out


def book_order_key(filename, note_basename):
    if filename == note_basename:
        return (2, 0, filename)
    m = CONTENTSEQ_RE.search(filename)
    if m:
        return (0, int(m.group(1)), filename)
    return (1, 0, filename)


def gather_refs(text_dir, note_basename):
    """返回 (appearance, all_refs)。"""
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


def process_book(book, text_dir, nf, dry_run, backup_dir):
    note_path = os.path.join(text_dir, nf)
    note_text = read(note_path)
    entries = parse_note_entries(note_text)
    total_li = len(LI_FULL_RE.findall(note_text))
    if total_li != len(entries):
        return None, "Note 文件含非注释 <li> 条目（%d 个 li，%d 个带 id），跳过" % (total_li, len(entries))
    by_id = {old: li for old, li in entries}
    appearance, _ = gather_refs(text_dir, os.path.basename(nf))
    appear_order = list(appearance.keys())

    if set(by_id) != set(appear_order):
        # 有孤儿或悬空引用时不自动处理，交给人工
        return None, "定义集合与引用集合不一致（含孤儿/悬空），跳过"

    if list(by_id.keys()) == appear_order:
        # 已经有序
        return None, None

    mapping = {old: "note%d" % (i + 1) for i, old in enumerate(appear_order)}

    # 重排 Note 文件
    new_lis = []
    for old in appear_order:
        li = by_id[old]
        new_li = LI_ID_RE.sub(lambda m: m.group(1) + mapping[old] + m.group(3), li, count=1)
        new_lis.append(new_li)
    ul_start = note_text.index("<ul>")
    ul_end = note_text.index("</ul>") + len("</ul>")
    new_note = note_text[:ul_start] + "<ul>\n" + "\n".join(new_lis) + "\n</ul>" + note_text[ul_end:]

    # 更新正文引用（单遍）
    ref_pat = re.compile(r"(%s#)(note[\d.]+)" % re.escape(os.path.basename(nf)))
    ref_total = 0
    touched = [nf]

    if not dry_run:
        backup_file(note_path, backup_dir, os.path.join(book, nf))
        write(note_path, new_note)

    for fn in sorted(os.listdir(text_dir)):
        if fn == nf or not fn.endswith(".xhtml"):
            continue
        p = os.path.join(text_dir, fn)
        c = read(p)
        def repl(m):
            nonlocal ref_total
            old = m.group(2)
            new = mapping.get(old)
            if new and new != old:
                ref_total += 1
                return m.group(1) + new
            return m.group(0)
        nc = ref_pat.sub(repl, c)
        if nc != c:
            touched.append(fn)
            if not dry_run:
                backup_file(p, backup_dir, os.path.join(book, fn))
                write(p, nc)

    return {
        "book": book,
        "note_file": nf,
        "n_notes": len(entries),
        "old_order": list(by_id.keys()),
        "new_order": appear_order,
        "mapping": mapping,
        "ref_rewrites": ref_total,
        "files_touched": touched,
    }, None


def main():
    ap = argparse.ArgumentParser(description="按正文出现顺序重排 Note 文件并重编号（可 --dry-run）")
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--backup", default=DEFAULT_BACKUP)
    ap.add_argument("--pattern", default=None, help="按书名子串筛选，如 *S1_01*")
    ap.add_argument("--dry-run", action="store_true", help="只预览不写盘")
    args = ap.parse_args()

    root = args.cache
    results = []
    skipped = []
    books = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    if args.pattern:
        pat = args.pattern.replace("*", ".*")
        books = [b for b in books if re.search(pat, b)]

    for book in books:
        text_dir = os.path.join(root, book, "OEBPS", "Text")
        if not os.path.isdir(text_dir):
            continue
        for nf in os.listdir(text_dir):
            if not NOTEFILE_RE.match(nf):
                continue
            r, msg = process_book(book, text_dir, nf, args.dry_run, args.backup)
            if msg:
                skipped.append((book, nf, msg))
            elif r:
                results.append(r)

    mode = "预览（未写盘）" if args.dry_run else "已写盘"
    print("%s，共 %d 本需要重排：\n" % (mode, len(results)))
    for r in results:
        print("=" * 70)
        print("%s（%s） 共 %d 条注释" % (r["book"], r["note_file"], r["n_notes"]))
        print("  旧顺序: %s" % ", ".join(r["old_order"]))
        print("  新顺序: %s" % ", ".join(r["new_order"]))
        print("  正文引用改写 %d 处，涉及文件 %d 个" % (r["ref_rewrites"], len(r["files_touched"])))
        changed = [old for old, new in r["mapping"].items() if old != new]
        if changed:
            print("  映射（旧 -> 新）：")
            for old in changed:
                print("    %s -> %s" % (old, r["mapping"][old]))
    if skipped:
        print("\n跳过 %d 本（需人工）：" % len(skipped))
        for book, nf, msg in skipped:
            print("  %s（%s）: %s" % (book, nf, msg))
    print("\n共扫描 %d 本书。" % len(books))


if __name__ == "__main__":
    sys.exit(main())
