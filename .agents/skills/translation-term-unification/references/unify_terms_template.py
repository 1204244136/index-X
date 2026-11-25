#!/usr/bin/env python3
"""译名／术语统一：显式映射 + 逐条预检的一次性执行器模板（index-X）。

配套 `.agents/skills/translation-term-unification/SKILL.md`。这是**模板**，不是仓库工具：
按任务填好 `MAPPINGS` 后复制到 `.cache/`（或临时目录）运行，跑完删除，不提交。

用法：
    Copy-Item .agents/skills/translation-term-unification/references/unify_terms_template.py .cache/_unify_terms.py
    # 填 MAPPINGS 后：
    python .cache/_unify_terms.py                  # 预检：只打印，不写盘
    python .cache/_unify_terms.py --apply           # 预检全过才写 EPUB/
    python .cache/_unify_terms.py --apply --tsv .cache/_unify.tsv

MAPPINGS 每项 = (作品号, 文件名, 行号, 原串, 新串)
    作品号   如 "S3_05"、"S5_01_03"、"S6_14.09.10"（与 `【S3_05】…` 目录名内一致）
    文件名   如 "S3_05-05_Chapter2.xhtml"（EPUB/<书>/OEBPS/Text/ 下的实际文件名）
    行号     EPUB/ 中该文件的物理行号，1 起
    原串/新串 行内文字片段，**不含标签**

不变式（任一不满足 → 整批不写盘）：
    1. 文件按作品号 + 文件名在 EPUB/ 下唯一定位；
    2. 行号在范围内；
    3. 原串在该行恰好出现一次（0 次且该行已有新串 = 已统一，幂等跳过；其余情形拒绝）；
    4. 改动后行数不变、XML 仍可解析。

只改行内文字，不增删物理行、不动标签/属性/注音/资源引用，逐字节保留 BOM 与换行风格。
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# ── 按任务填写 ────────────────────────────────────────────────────────────────
# (作品号, 文件名, 行号, 原串, 新串)
MAPPINGS: list[tuple[str, str, int, str, str]] = [
    # ("S3_05", "S3_05-05_Chapter2.xhtml", 604, "别呀", "可别啦"),
]
# ─────────────────────────────────────────────────────────────────────────────


def locate(epub_root: Path, book: str, name: str) -> list[Path]:
    """按作品号 + 文件名在 EPUB/ 下定位，返回全部命中（要求恰好 1 个）。"""
    hits: list[Path] = []
    for book_dir in sorted(epub_root.iterdir()):
        if not book_dir.is_dir() or f"【{book}】" not in book_dir.name:
            continue
        candidate = book_dir / "OEBPS" / "Text" / name
        if candidate.is_file():
            hits.append(candidate)
    return hits


def read_keep(path: Path) -> tuple[str, bool]:
    """读文本并记住是否带 BOM；换行风格原样保留（只在 \\n 处切分）。"""
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8-sig" if bom else "utf-8"), bom


def context(line: str, old: str, new: str, width: int = 14) -> str:
    """替换位置前后各 width 字的上下文，用于人工核对方向没译反。"""
    idx = line.find(old)
    length = len(old)
    if idx < 0:
        idx = line.find(new)
        length = len(new)
    if idx < 0:
        return ""
    head = line[max(0, idx - width) : idx]
    tail = line[idx + length : idx + length + width]
    return f"{head}【{old}→{new}】{tail}"


_ILLU_COLUMNS = (
    "卷号", "日文图片", "日文图片文字", "日文正文文件", "日文行号", "日文正文原句",
    "中文图片", "中文图片文字", "中文正文文件", "中文行号", "中文正文原句", "嵌字状态", "备注",
)


def _load_illustration_anchors(doc_path: Path) -> dict[tuple[str, str, int], list[tuple[str, str, str]]]:
    """独立解析映射表，避免复制到临时目录运行时依赖仓库模块路径。"""
    if not doc_path.is_file():
        return {}
    anchors: dict[tuple[str, str, int], list[tuple[str, str, str]]] = {}
    in_table = False
    for raw in doc_path.read_text(encoding="utf-8-sig").splitlines():
        s = raw.strip()
        if not s.startswith("|"):
            in_table = False
            continue
        cells = [c.strip().strip("`") for c in s.strip("|").split("|")]
        if not in_table:
            in_table = tuple(cells) == _ILLU_COLUMNS
            continue
        if len(cells) != len(_ILLU_COLUMNS) or all(set(c) <= {"-", ":"} for c in cells):
            continue
        vol, _ji, _jt, _jf, _jl, _js, cn_img, cn_txt, cn_file, cn_line, _cs, state, _note = cells
        if cn_file in {"", "—", "-"} or cn_line in {"", "—", "-"}:
            continue
        parts = cn_line.replace("–", "-").split("-")
        if len(parts) > 2 or not all(p.isdigit() for p in parts):
            continue
        a = int(parts[0])
        b = int(parts[-1])
        for ln in range(a, b + 1):
            anchors.setdefault((vol, Path(cn_file).name, ln), []).append((cn_img, cn_txt, state))
    return anchors


def _print_illustration_alerts(
    changed: list[tuple[str, str, int, str, str, str]],
    doc_path: Path,
) -> None:
    """命中插图正文行时打印显著提醒，提示同步映射表并在答复中告知用户。"""
    anchors = _load_illustration_anchors(doc_path)
    if not anchors:
        return
    hits: list[tuple[str, str, int, str, str, str, str, str]] = []
    for book, name, line_no, old, new, _ctx in changed:
        for cn_img, cn_txt, state in anchors.get((book, Path(name).name, int(line_no)), []):
            hits.append((book, name, line_no, cn_img, cn_txt, state, old, new))
    if not hits:
        return
    print(f"\n【插图文本联动提醒】本次替换命中 {len(hits)} 条插图对应正文行：")
    for book, name, line_no, cn_img, cn_txt, state, old, new in hits:
        print(f"  - {book} {cn_img} ({Path(name).name}:{line_no})｜状态={state}｜图上「{cn_txt}」｜{old} -> {new}")
    print("  [重要] 若执行 --apply，请同步更新 docs/illustration-text-mapping.md 对应正文行号／原句，并在最终回复末尾额外提醒用户受影响的中文插图！")


def main() -> int:
    # 模板可复制到任意临时目录独立运行，不依赖仓库内工具的导入路径。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass
    parser = argparse.ArgumentParser(description="译名统一：显式映射 + 逐条预检")
    parser.add_argument("--apply", action="store_true", help="预检全过后写盘（默认只预览）")
    parser.add_argument("--epub", default="EPUB", help="EPUB 归档根目录（默认 EPUB/）")
    parser.add_argument("--tsv", help="把修订明细写成 TSV，供本地核验与汇总提交信息")
    parser.add_argument("--illustration-doc", default=None, help="插图文字映射表路径（默认自动查同级 docs/illustration-text-mapping.md）")
    args = parser.parse_args()

    epub_root = Path(args.epub)
    if not epub_root.is_dir():
        print(f"[拒绝] EPUB 根目录不存在：{epub_root}")
        return 2
    if not MAPPINGS:
        print("[拒绝] MAPPINGS 为空：先按任务填写 (作品号, 文件名, 行号, 原串, 新串)")
        return 2

    by_file: dict[tuple[str, str], list[tuple[int, str, str]]] = {}
    for book, name, line_no, old, new in MAPPINGS:
        if not old or not new or old == new:
            print(f"[拒绝] 映射非法（原串／新串为空或相同）：{book} {name}:{line_no} {old!r}→{new!r}")
            return 2
        by_file.setdefault((book, name), []).append((line_no, old, new))

    errors: list[str] = []
    changed: list[tuple[str, str, int, str, str, str]] = []  # + 上下文
    already: list[tuple[str, str, int, str, str]] = []
    writes: list[tuple[Path, bytes]] = []

    for (book, name), entries in sorted(by_file.items()):
        hits = locate(epub_root, book, name)
        if len(hits) != 1:
            errors.append(f"文件定位不唯一（{len(hits)} 命中）：[{book}] {name}")
            continue
        path = hits[0]
        text, bom = read_keep(path)
        lines = text.split("\n")
        for line_no, old, new in sorted(entries):
            if not 1 <= line_no <= len(lines):
                errors.append(f"行号越界：{name}:{line_no}（共 {len(lines)} 行）")
                continue
            line = lines[line_no - 1]
            count = line.count(old)
            if count == 1:
                changed.append((book, name, line_no, old, new, context(line, old, new)))
                lines[line_no - 1] = line.replace(old, new)
            elif count == 0 and new in line:
                already.append((book, name, line_no, old, new))
            elif count == 0:
                errors.append(f"原串未命中：{name}:{line_no} {old!r}｜{line.strip()[:60]}")
            else:
                errors.append(f"原串不唯一（{count} 次）：{name}:{line_no} {old!r}")
        new_text = "\n".join(lines)
        if len(lines) != len(text.split("\n")):
            errors.append(f"行数变化：{name}")
            continue
        try:
            ET.fromstring(new_text)
        except ET.ParseError as exc:
            errors.append(f"XML 解析失败：{name}｜{exc}")
            continue
        writes.append((path, (b"\xef\xbb\xbf" if bom else b"") + new_text.encode("utf-8")))

    if errors:
        print(f"[拒绝] 预检未通过 {len(errors)} 项，整批不写盘：")
        for item in errors:
            print(f"  - {item}")
        return 1

    for book, name, line_no, old, new, ctx in changed:
        print(f"{'写入' if args.apply else '待改'} {name}:{line_no}  {old} → {new}")
        print(f"      {ctx}")
    for book, name, line_no, old, new in already:
        print(f"已统一 {name}:{line_no}  已是「{new}」，跳过")

    if args.tsv and changed:
        rows = ["作品\t文件\t行\t修订"]
        rows += [f"{b}\t{n}\t{ln}\t{o} → {x}" for b, n, ln, o, x, _ in changed]
        Path(args.tsv).write_text("\n".join(rows) + "\n", encoding="utf-8")
        print(f"明细已写入 {args.tsv}")

    illu_doc = (
        Path(args.illustration_doc)
        if args.illustration_doc
        else (epub_root.parent / "docs" / "illustration-text-mapping.md")
    )
    print(f"\n预检通过：待改 {len(changed)} 处／已统一 {len(already)} 处／涉及文件 {len(writes)} 个")
    _print_illustration_alerts(changed, illu_doc)
    if not args.apply:
        print("（预览模式，未写盘。确认无误后加 --apply）")
        return 0

    for path, payload in writes:
        path.write_bytes(payload)
    print(f"已写入 {len(writes)} 个文件（仅 {epub_root}/）。"
          f"下一步：check_alignment.py --strict → check_illustration_mapping.py → publish_auto.py")
    _print_illustration_alerts(changed, illu_doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
