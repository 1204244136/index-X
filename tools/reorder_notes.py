#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按正文首次引用顺序重排 Note 条目，保留已有 ID 和正文引用。

- 对每本 *-Note.xhtml：计算正文 noteref 首次出现顺序；
- 只按该顺序移动完整 <li> 条目；
- 不改写注释 ID、条目内容或正文文件。
默认预览，--apply 才写盘；写前可备份，--no-backup 禁用备份。
规范来源是 `docs/epub-structure-spec.md` 与 docs/translation-spec.md；CLI 合同见 tools/README.md。
"""
import os
import re
import sys
import shutil
import argparse
import tempfile
if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output
from file_transaction import rollback_paths
from edit_safety import (EditSafetyError, add_content_roots, add_edit_mode,
                         content_roots, require_edit_target)

from notes_core import (
    LI_FULL_RE,
    NOTEFILE_RE,
    gather_refs,
    parse_note_entries,
    read_text,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE = os.path.join(REPO_ROOT, ".cache", "epub-work", "chinese-text")
DEFAULT_BACKUP = os.path.join(REPO_ROOT, ".cache", "reorder-backup")

def read(path):
    return read_text(path)


def write(path, text):
    directory = os.path.dirname(path) or "."
    fd, temporary = tempfile.mkstemp(
        prefix="." + os.path.basename(path) + ".",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def backup_file(path, backup_dir, rel):
    if not backup_dir:
        return
    bpath = os.path.join(backup_dir, rel)
    os.makedirs(os.path.dirname(bpath), exist_ok=True)
    if not os.path.exists(bpath):
        shutil.copy2(path, bpath)


def process_book(book, text_dir, nf, dry_run, backup_dir):
    note_path = os.path.join(text_dir, nf)
    note_text = read(note_path)
    entries = parse_note_entries(note_text)
    total_li = len(LI_FULL_RE.findall(note_text))
    if total_li != len(entries):
        return None, "Note 文件含非注释 <li> 条目（%d 个 li，%d 个带 id），跳过" % (total_li, len(entries))
    by_id = {old: li for old, li in entries}
    if len(by_id) != len(entries):
        return None, "Note 文件重复定义注释 ID，跳过"
    appearance, _ = gather_refs(text_dir, os.path.basename(nf))
    appear_order = list(appearance.keys())

    if set(by_id) != set(appear_order):
        # 有孤儿或悬空引用时不自动处理，交给人工
        return None, "定义集合与引用集合不一致（含孤儿/悬空），跳过"

    # 容器必须是 <ul>…</ul>（见 `docs/epub-structure-spec.md`「译注页（Note）结构规约」）。
    # 用 find 而非 index：`<ol>` 或结构异常时给出可读的拒绝理由，不抛未捕获异常
    # ——CI 的 normalize-epub-text.yml 每日会跑到本函数。
    ul_start = note_text.find("<ul>")
    ul_end = note_text.find("</ul>")
    if ul_start == -1 or ul_end == -1:
        return None, "Note 文件容器不是 <ul>…</ul>（规范要求容器必须是 <ul>，不得用 <ol>），跳过"
    ul_end += len("</ul>")

    if list(by_id) == appear_order:
        return None, None

    new_lis = [by_id[note_id] for note_id in appear_order]
    new_note = note_text[:ul_start] + "<ul>\n" + "\n".join(new_lis) + "\n</ul>" + note_text[ul_end:]

    writes = {note_path: new_note}

    if not dry_run:
        with rollback_paths(writes):
            for path in writes:
                backup_file(path, backup_dir, os.path.join(book, os.path.basename(path)))
            for path, content in writes.items():
                write(path, content)

    return {
        "book": book,
        "note_file": nf,
        "n_notes": len(entries),
        "old_order": list(by_id.keys()),
        "new_order": appear_order,
        # 保留旧报告字段；重排只改变物理顺序，映射恒等、正文改写恒为零。
        "mapping": {note_id: note_id for note_id in appear_order},
        "ref_rewrites": 0,
        "files_touched": [nf],
    }, None


def main():
    configure_output()
    ap = argparse.ArgumentParser(description="按正文首次引用顺序重排 Note 条目，保留 ID 与正文引用（可 --dry-run）")
    add_content_roots(ap)
    ap.add_argument("--backup", default=DEFAULT_BACKUP, help="备份目录")
    ap.add_argument("--no-backup", action="store_true", help="不生成备份文件（CI 或自动化环境推荐）")
    ap.add_argument("--pattern", default=None, help="按书名子串筛选，如 *S1_01*")
    add_edit_mode(ap)
    args = ap.parse_args()
    root, _ = content_roots(args, ap)
    backup_dir = None if args.no_backup else args.backup
    results = []
    skipped = []
    if not os.path.exists(root):
        print("目录不存在：%s" % root, file=sys.stderr)
        return 0
    books = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    if args.pattern:
        pat = args.pattern.replace("*", ".*")
        books = [b for b in books if re.search(pat, b)]

    if args.apply:
        try:
            for book in books:
                for path in (root / book).rglob("*.xhtml"):
                    require_edit_target(path, args.staging)
        except EditSafetyError as exc:
            ap.error(str(exc))

    for book in books:
        text_dir = os.path.join(root, book, "OEBPS", "Text")
        if not os.path.isdir(text_dir):
            continue
        for nf in os.listdir(text_dir):
            if not NOTEFILE_RE.match(nf):
                continue
            r, msg = process_book(book, text_dir, nf, not args.apply, backup_dir)
            if msg:
                skipped.append((book, nf, msg))
            elif r:
                results.append(r)

    mode = "已写盘" if args.apply else "预览（未写盘）"
    print("%s，共 %d 本需要重排：\n" % (mode, len(results)))
    for r in results:
        print("=" * 70)
        print("%s（%s） 共 %d 条注释" % (r["book"], r["note_file"], r["n_notes"]))
        print("  旧顺序: %s" % ", ".join(r["old_order"]))
        print("  新顺序: %s" % ", ".join(r["new_order"]))
        print("  仅重排译注页，保留 ID 与正文引用；涉及文件 %d 个" % len(r["files_touched"]))
    if skipped:
        print("\n跳过 %d 本（需人工）：" % len(skipped), file=sys.stderr)
        for book, nf, msg in skipped:
            print("  %s（%s）: %s" % (book, nf, msg), file=sys.stderr)
    print("\n共扫描 %d 本书。" % len(books))
    return 0  # Non-note lists and unresolved references are reported, never guessed.


if __name__ == "__main__":
    sys.exit(main())
