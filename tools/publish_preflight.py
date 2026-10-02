"""Read-only gates shared by synchronization and release builds."""
from __future__ import annotations

import argparse
import sys
import subprocess
from pathlib import Path

from check_alignment import audit_roots
from check_epub_health import audit_book, CHECK_ORDER
from check_note_order import check_book
from epub_ids import book_id
from notes_core import NOTEFILE_RE
from package_cache_epubs import PackageError, validate_book


def validate_publication(cn_root: Path, jp_root: Path | None = None,
                         book_keys: list[str] | None = None, *, allow_removed: bool = False) -> bool:
    """Validate the selected current copies before any mirror/upload mutation.

    book_keys use side/book identities. Deleted books have no container to check;
    deletion policy remains the caller's responsibility.
    """
    selected = set(book_keys) if book_keys is not None else None
    roots = {"chinese-text": cn_root, "japanese-text": jp_root}
    problems: list[str] = []
    work_ids: set[str] = set()
    requested_ids = ({book_id(key.split("/", 1)[-1]) for key in selected}
                     if selected is not None else None)
    checked = 0
    for side, root in roots.items():
        if root is None or not root.is_dir():
            continue
        seen: set[str] = set()
        for book in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".extract-")):
            key = f"{side}/{book.name}"
            if selected is not None and key not in selected and book_id(book.name) not in requested_ids:
                continue
            wid = book_id(book.name)
            if not wid or wid in seen:
                problems.append(f"{key}: 缺少或重复作品号")
                continue
            seen.add(wid)
            work_ids.add(wid)
            checked += 1
            try:
                validate_book(book)
                if side == "chinese-text":
                    checks = set(CHECK_ORDER) - {"template"} if jp_root is not None else None
                    findings, _counts, _exempt, _covered = audit_book(book, checks)
                    problems.extend(f"{key}: {f[0]} {f[2]} {f[5]}" for f in findings if f[4] == "error")
                    text = book / "OEBPS" / "Text"
                    if text.is_dir():
                        for note in sorted(p for p in text.iterdir() if p.is_file() and NOTEFILE_RE.match(p.name)):
                            _entry, issues = check_book(book.name, str(text), note.name)
                            problems.extend(f"{key}: {note.name} {issue}" for issue in issues)
            except (OSError, UnicodeError, PackageError, ValueError) as exc:
                problems.append(f"{key}: {exc}")
    if checked == 0 and not allow_removed:
        problems.append("没有匹配的书籍，未执行发布验证")
    if jp_root is not None:
        if not jp_root.is_dir():
            problems.append(f"日文参考目录不存在：{jp_root}")
        else:
            try:
                _rows, bad, _checked = audit_roots(cn_root, jp_root, work_ids if selected is not None else None)
                problems.extend(f"{r[1]} {r[2]}: {r[5]}" for r in bad)
            except (OSError, UnicodeError, ValueError) as exc:
                problems.append(f"中日对齐检查失败：{exc}")
    scope = "容器/资源/单侧成品/译注" + ("/中日模板与对齐" if jp_root is not None else "（无日文参考）")
    print(f"发布预检：{checked} 本；{scope}；问题 {len(problems)} 条")
    for problem in problems:
        print(f"  [阻断] {problem}", file=sys.stderr)
    return not problems


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="发布前只读预检，任一硬失败即阻断")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "EPUB")
    parser.add_argument("--jp-root", type=Path, help="可选日文参考；缺省仅检查中文成品")
    parser.add_argument("--only-books", help="逗号分隔 side/book，同步入口内部使用")
    parser.add_argument("--calibre", action="store_true", help="追加 calibre 完整结构校验，需要本机安装")
    args = parser.parse_args(argv)
    if not args.source.is_dir():
        print(f"中文成品目录不存在：{args.source}", file=sys.stderr)
        return 2
    keys = args.only_books.split(",") if args.only_books else None
    if not validate_publication(args.source, args.jp_root, keys):
        return 1
    if args.calibre:
        if keys:
            parser.error("--calibre 不与 --only-books 同用；请直接对选定书籍运行 check_epub_validity")
        return subprocess.run([sys.executable, str(Path(__file__).with_name("check_epub_validity.py")),
                               str(args.source), "--structural", "--strict"], check=False).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
