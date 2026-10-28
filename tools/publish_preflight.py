"""Read-only gates shared by synchronization and release builds."""
from __future__ import annotations

import argparse
import sys
import subprocess
from pathlib import Path

if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output
from check_alignment import audit_roots
from check_epub_health import audit_book, CHECK_ORDER, exempt, find_identifier_duplicates
from check_note_order import check_book
from check_paired_text import audit_coverage as audit_paired_text
from check_term_anchors import audit_coverage as audit_term_coverage
from check_translation_spec import audit_book as audit_translation_spec
from epub_ids import book_id
from notes_core import NOTEFILE_RE
from package_cache_epubs import PackageError, validate_book


def validate_publication(cn_root: Path, jp_root: Path | None = None,
                         book_keys: list[str] | None = None, *, allow_removed: bool = False,
                         require_reference: bool = False) -> bool:
    """Validate the selected current copies before any mirror/upload mutation.

    book_keys use side/book identities. Deleted books have no container to check;
    deletion policy remains the caller's responsibility. Optional references
    retain single-sided publication; require_reference makes incomplete coverage
    blocking for callers explicitly requesting bilingual validation.
    """
    selected = set(book_keys) if book_keys is not None else None
    roots = {"chinese-text": cn_root, "japanese-text": jp_root}
    problems: list[str] = []
    work_ids: set[str] = set()
    requested_ids = ({book_id(key.split("/", 1)[-1]) for key in selected}
                     if selected is not None else None)
    checked = 0
    cn_books: list[Path] = []
    found_selected: set[str] = set()
    for side, root in roots.items():
        if root is None or not root.is_dir():
            continue
        seen: set[str] = set()
        for book in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".extract-")):
            key = f"{side}/{book.name}"
            if selected is not None and key not in selected and book_id(book.name) not in requested_ids:
                continue
            if selected is not None and key in selected:
                found_selected.add(key)
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
                    cn_books.append(book)
                    checks = set(CHECK_ORDER) - {"template"} if jp_root is not None else None
                    findings, _counts, _exempt, _covered = audit_book(book, checks)
                    problems.extend(f"{key}: {f[0]} {f[2]} {f[5]}" for f in findings if f[4] == "error")
                    text = book / "OEBPS" / "Text"
                    if text.is_dir():
                        for note in sorted(p for p in text.iterdir() if p.is_file() and NOTEFILE_RE.match(p.name)):
                            _entry, issues = check_book(book.name, str(text), note.name)
                            problems.extend(f"{key}: {note.name} {issue}" for issue in issues)
                        # 翻译规范 error 级接入阻断（`docs/translation-spec.md` 七的
                        # P1–P25）。warning／info 只报告、不阻断：P7／P9／P15／P16 一类
                        # 属提示级，P23（译注起句）等存量批次项也在此列。
                        for fn, ln, cat, sev, msg, ex in audit_translation_spec(text):
                            if sev == "error":
                                problems.append(f"{key}: {fn}:{ln} {cat} {msg}{ex}")
            except (OSError, UnicodeError, PackageError, ValueError) as exc:
                problems.append(f"{key}: {exc}")
    if checked == 0 and not allow_removed:
        problems.append("没有匹配的书籍，未执行发布验证")
    if selected is not None and not allow_removed:
        problems.extend(f"显式请求的书籍不存在，未执行发布验证：{key}"
                        for key in sorted(selected - found_selected))
    # 跨书项：`unique-identifier` 唯一（要跨书汇总，逐本的 `audit_book` 判不了）。
    for name, msg in find_identifier_duplicates(cn_books):
        if exempt(book_id(name), "identifier-unique"):
            continue
        problems.append(f"chinese-text/{name}: identifier-unique {msg}")
    term_result = None
    if require_reference and jp_root is None:
        problems.append("完整双语预检需要日文参考，请指定 --jp-root")
    if jp_root is not None:
        if not jp_root.is_dir():
            problems.append(f"日文参考目录不存在：{jp_root}")
        else:
            try:
                _rows, bad, _checked = audit_roots(cn_root, jp_root, work_ids if selected is not None else None)
                problems.extend(f"{r[1]} {r[2]}: {r[5]}" for r in bad)
            except (OSError, UnicodeError, ValueError) as exc:
                problems.append(f"中日对齐检查失败：{exc}")
            # 结构与字符检查不覆盖术语回落；按配对原文与裁定表另查误形。
            try:
                cn_ids = {book_id(book.name) for book in cn_books}
                if cn_ids:
                    term_result = audit_term_coverage(cn_root, jp_root, cn_ids)
                term_rows = term_result.rows if term_result is not None else []
                problems.extend(
                    f"{r['book']} {r['file']}:{r['line']} 术语锚点 {r['anchor']} "
                    f"应作「{r['expected']}」，现含「{r['found']}」"
                    for r in term_rows)
                if require_reference and term_result is not None:
                    problems.extend(f"双语覆盖未完成：{message}" for message in term_result.incomplete)
            except (OSError, UnicodeError, ValueError) as exc:
                problems.append(f"术语锚点检查失败：{exc}")
            # 术语与注音格式都不覆盖「整句只剩术语」的截断形态，另查对话行。
            try:
                cn_ids = {book_id(book.name) for book in cn_books}
                if cn_ids:
                    paired_result = audit_paired_text(cn_root, jp_root, cn_ids)
                    problems.extend(
                        f"{r['book']} {r['file']}:{r['line']} 疑似整句截断（{r['detail']}）"
                        for r in paired_result.rows)
            except (OSError, UnicodeError, ValueError) as exc:
                problems.append(f"对照完整性检查失败：{exc}")
    scope = "容器/资源/单侧成品/译注/翻译规范 error 级"
    if term_result is not None:
        print(f"日文参考覆盖：已核对文件 {term_result.checked}；未核对文件 {term_result.skipped}；"
              f"豁免作品 {term_result.exempt_books}／单元 {term_result.exempt_units}；{term_result.status}")
        for note in term_result.notes:
            print(f"  [参考范围] {note}")
        if term_result.checked:
            scope += f"/中日模板与对齐/术语锚点/对照完整性（{term_result.status}）"
        else:
            scope += "（仅单侧；无适用日文逐行核验结果）"
    else:
        scope += "（仅单侧；无日文参考）" if jp_root is None else "（仅单侧；日文逐行核验未执行）"
    print(f"发布预检：{checked} 本；{scope}；问题 {len(problems)} 条")
    for problem in problems:
        print(f"  [阻断] {problem}", file=sys.stderr)
    return not problems


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="发布前只读预检，任一硬失败即阻断")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "EPUB")
    parser.add_argument("--jp-root", type=Path, help="完整双语预检的日文参考；缺省仅检查中文成品")
    parser.add_argument("--only-books", help="逗号分隔 side/book，同步入口内部使用")
    parser.add_argument("--calibre", action="store_true", help="追加 calibre 完整结构校验，需要本机安装")
    args = parser.parse_args(argv)
    if not args.source.is_dir():
        print(f"中文成品目录不存在：{args.source}", file=sys.stderr)
        return 2
    if args.jp_root is not None and not args.jp_root.is_dir():
        print(f"日文参考目录不存在：{args.jp_root}；请指定已解包的日文工作源。", file=sys.stderr)
        return 2
    keys = args.only_books.split(",") if args.only_books else None
    if not validate_publication(args.source, args.jp_root, keys, require_reference=args.jp_root is not None):
        return 1
    if args.calibre:
        if keys:
            parser.error("--calibre 不与 --only-books 同用；请直接对选定书籍运行 check_epub_validity")
        return subprocess.run([sys.executable, str(Path(__file__).with_name("check_epub_validity.py")),
                               str(args.source), "--structural", "--strict"], check=False).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
