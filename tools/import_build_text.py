#!/usr/bin/env python3
"""计划文件 + 交稿 → 正文 XHTML（固定行模板，写盘前逐章断言行数）。

新书导入第 3 步，只写 `<书目录>/OEBPS/Text/*.xhtml`（含 Note 页），不碰容器、
导航与图片（分别由 `import_build_wrappers.py`、`import_images.py` 负责）。

**门禁是硬前置**：每个章节渲染出的物理行数必须与日文对齐工作源对应文件的行数
完全一致，任何一章不齐就整批不写、非零退出——不存在「先写一半再修」的中间态。
正文段首尾的 ASCII 空格／不换行空格／全角空格会被清掉（交稿排版噪声），
段内空白（含分字用全角空格）原样保留。

用法：
    python tools/import_build_text.py plan.json --out 暂存目录/书目录 --apply --staging
    python tools/import_build_text.py plan.json --out EPUB/[S4_04]… --apply
    python tools/import_build_text.py plan.json --report 预览.txt          # 只预览
"""
from __future__ import annotations

import argparse
from pathlib import Path

from docx_source import chapter_kind, esc, esc_ruby, extract_notes, read_docx, split_chapters
from edit_safety import EditSafetyError, add_edit_mode, require_edit_target
from file_transaction import atomic_write_bytes, rollback_paths
from import_plan import PlanError, apply_ops, body_images, load_plan

HEAD3 = ('<html xmlns="http://www.w3.org/1999/xhtml" '
         'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
         '<link href="../Styles/style.css" rel="stylesheet" type="text/css"/>'
         "<title></title></head><body>")

EDGE_WHITESPACE = " \u00a0"


def render_file(chapter: dict, rows: list[dict], notes: list[str], work_id: str,
                images: list[str]) -> tuple[str, int, int]:
    """渲染一个正文文件，返回 (内容, 小节数, 用掉的正文图片数)。"""
    lines = ["<?xml version='1.0' encoding='utf-8'?>", "<!DOCTYPE html>", HEAD3]
    main, sub = chapter.get("h1_main"), chapter.get("h1_sub")
    if main and sub:
        lines.append(f'<h1 class="heading-lines"><span class="heading-main">{esc(main)}</span>'
                     f'<span class="heading-subtitle font08">{esc(sub)}</span></h1>')
    elif main:
        lines.append(f"<h1>{esc(main)}</h1>")
    else:
        lines.append("")

    body = list(rows)
    sections = 0
    if body and body[0]["kind"] == "h2":
        sections = 1
        lines.append(f'<h2 id="toc_1">{esc(body[0]["text"])}</h2>')
        body = body[1:]
    else:
        lines.append("")

    used_images = 0
    for row in body:
        kind = row["kind"]
        if kind == "p":
            text = extract_notes(esc_ruby(row["text"].strip(EDGE_WHITESPACE)), notes, work_id)
            lines.append(f"<p>{text}</p>")
        elif kind == "br":
            lines.append("<br/>")
        elif kind == "h2":
            sections += 1
            lines.append(f'<h2 id="toc_{sections}">{esc(row["text"])}</h2>')
        elif kind == "img":
            if used_images >= len(images):
                raise PlanError(f"{chapter['cn_title']}：正文插图比计划里的 body 图片多")
            name = images[used_images]
            used_images += 1
            lines.append(f'<p><img alt="图片" class="fit" src="../Images/{name}"/></p>')
        else:
            raise PlanError(f"{chapter['cn_title']}：未知行类型 {kind}")
    lines.append("</body></html>")
    return "\n".join(lines) + "\n", sections, used_images


def render_notes(notes: list[str]) -> str:
    lines = ["<?xml version='1.0' encoding='utf-8'?>", "<!DOCTYPE html>", HEAD3,
             '<h1 class="center">译注</h1>', "<ul>"]
    for number, note in enumerate(notes, 1):
        lines.append(f'<li epub:type="footnote" id="note{number}">{esc_ruby(note)}</li>')
    lines += ["</ul>", "</body></html>", ""]
    return "\n".join(lines)


def jp_line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8-sig").splitlines())


def build(plan: dict, docx: Path) -> tuple[dict[str, str], list[str], list[str]]:
    paragraphs, _, _, _ = read_docx(docx, collapse_whitespace=False)
    chapters = split_chapters(paragraphs)
    if len(chapters) != len(plan["chapters"]):
        raise PlanError(f"交稿章数 {len(chapters)} 与计划章数 {len(plan['chapters'])} 不一致")
    work_id = plan["work_id"]
    images = body_images(plan)
    jp_dir = Path(plan.get("jp_root", "")) / plan.get("jp_dir", "")
    if not plan.get("jp_dir") or not jp_dir.is_dir():
        raise PlanError("计划缺少可用的 jp_root/jp_dir，无法校验日文行数")

    text_files: dict[str, str] = {}
    notes: list[str] = []
    report: list[str] = []
    image_cursor = 0
    for meta, chapter in zip(plan["chapters"], chapters):
        if not (chapter["title"] or "").startswith(meta["cn_title"][:2]):
            raise PlanError(f"交稿章标题与计划顺序不一致：{chapter['title']!r} vs {meta['cn_title']!r}")
        rows = apply_ops([{"idx": r["idx"], "kind": chapter_kind(r), "text": r["text"]}
                          for r in chapter["rows"]],
                         {"ops": meta.get("ops") or []}, where=meta["cn_title"])
        chapter_images = images[image_cursor:]
        content, sections, used = render_file(meta, rows, notes, work_id, chapter_images)
        image_cursor += used
        text_files[meta["fname"]] = content
        jp_path = jp_dir / meta["jp_file"]
        if not jp_path.is_file():
            raise PlanError(f"日文对齐文件不存在：{jp_path}")
        expected = jp_line_count(jp_path)
        actual = len(content.splitlines())
        report.append(f"{meta['fname']}: {actual} 行（日文 {expected}）"
                      f"／小节 {sections}／{len(rows)} 行内容")
        if actual != expected:
            raise PlanError(f"{meta['fname']} 行数 {actual} ≠ 日文 {expected}："
                            f"先补全 plan 的 ops，不要写盘")
    if image_cursor != len(images):
        raise PlanError(f"正文图片用掉 {image_cursor} 张，计划里登记了 {len(images)} 张 body 图片")
    if notes:
        text_files[f"{work_id}-Note.xhtml"] = render_notes(notes)
        report.append(f"{work_id}-Note.xhtml: 译注 {len(notes)} 条")
    return text_files, report, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="计划文件 + 交稿 → 正文 XHTML（固定行模板，写盘前断言行数）")
    parser.add_argument("plan", type=Path, help="导入计划 plan.json")
    parser.add_argument("--docx", type=Path, default=None, help="交稿 .docx；缺省用计划里的 source_docx")
    parser.add_argument("--out", type=Path, required=True, help="书目录（写入其 OEBPS/Text/）")
    parser.add_argument("--report", type=Path, help="渲染报告输出文件")
    add_edit_mode(parser)
    args = parser.parse_args(argv)

    try:
        plan = load_plan(args.plan)
    except PlanError as exc:
        print(f"[阻断] {exc}")
        return 2
    docx = args.docx or Path(plan.get("source_docx", ""))
    if not docx.is_file():
        print(f"[阻断] 交稿不存在：{docx}")
        return 2

    try:
        text_files, report, notes = build(plan, docx)
    except PlanError as exc:
        print(f"[阻断] {exc}")
        return 1

    print("\n".join(report))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")

    if not args.apply:
        print(f"[预览] 将写入 {len(text_files)} 个正文文件到 {args.out}/OEBPS/Text/；"
              f"译注 {len(notes)} 条；加 --apply 写盘")
        return 0

    try:
        target = require_edit_target(args.out, args.staging)
    except EditSafetyError as exc:
        print(f"[阻断] {exc}")
        return 2
    text_dir = target / "OEBPS" / "Text"
    text_dir.mkdir(parents=True, exist_ok=True)
    with rollback_paths([text_dir]):
        for name, content in sorted(text_files.items()):
            atomic_write_bytes(text_dir / name, content.encode("utf-8"))
    print(f"已写入 {len(text_files)} 个正文文件：{text_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
