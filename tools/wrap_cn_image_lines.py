#!/usr/bin/env python3
"""把中文侧「独占一行的裸 <img/>」规范为 <p> 包裹的图片行（只读预览，--apply 写盘）。

规范来源是 `docs/epub-structure-spec.md`；CLI 合同与安全前提见 tools/README.md。
--wrap-only 保证不删除物理行；允许清理容器时必须提供 --jp-root 日文参考。

用法：
    python tools/wrap_cn_image_lines.py --wrap-only
    python tools/wrap_cn_image_lines.py --jp-root 日文参考目录 --book S1_25 --apply
"""
from __future__ import annotations

import argparse
if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output
from edit_safety import (EditSafetyError, add_content_roots, add_edit_mode,
                         content_roots, require_edit_target)
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alignment_rules import NON_PAIR_WORK_IDS, pairing_header_of  # noqa: E402
from epub_ids import is_packaging_header, japanese_book_id  # noqa: E402
from file_transaction import rollback_paths  # noqa: E402
from xhtml_structure import books_by_id, header_index, pair_structure_problems  # noqa: E402

IMG = re.compile(r"<img\b[^>]*/?>", re.I)
DIV_OPEN = re.compile(r"<div\b[^>]*>", re.I)
DIV_CLOSE = re.compile(r"</div>", re.I)
CLASS_RE = re.compile(r'class="([^"]*)"', re.I)
INNER_SVG = re.compile(r"<(?:svg|image)\b|</svg>", re.I)
BARE_IMG_LINE = re.compile(r"^\s*<img\b[^>]*/?>\s*$", re.I)
BODY_RE = re.compile(r"<body\b", re.I)


def _img_only(line: str) -> bool:
    """该行内容是否只有 <img/> 与 div 标签（可含零或多个 img）。"""
    if INNER_SVG.search(line):
        return False
    stripped = re.sub(r"</?div\b[^>]*>", "", line, flags=re.I)
    stripped = IMG.sub("", stripped)
    return not stripped.strip()


def _classes(line: str) -> list[str]:
    return CLASS_RE.findall(line)


def normalize(lines: list[str]) -> tuple[list[str], int, int]:
    """返回（新行, 包 <p> 的图片行数, 删除的结构行数）。"""
    out: list[str] = []
    wrapped = dropped = 0
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if INNER_SVG.search(line):
            out.append(line)
            i += 1
            continue
        # 纯 div 结构行或含图的 div 行 → 尝试收集一个「图片区段」
        if _img_only(line) and (DIV_OPEN.search(line) or DIV_CLOSE.search(line)
                                 or BARE_IMG_LINE.match(line)):
            j = i
            opens = closes = 0
            while j < n and _img_only(lines[j]):
                opens += len(DIV_OPEN.findall(lines[j]))
                closes += len(DIV_CLOSE.findall(lines[j]))
                j += 1
            if opens == closes and opens + closes > 0:
                # 区段内 div 配平：整段都是被 div 包着的图片 → 按令牌出现顺序解包装，
                # 保证图片用的是「它当时所在的那层 div」的 class（闭标签之后的令牌才弹栈）。
                emitted: list[str] = []
                stack: list[str] = []
                for k in range(i, j):
                    for tok in re.finditer(
                            r"<div\b[^>]*>|</div>|<img\b[^>]*/?>", lines[k], re.I):
                        t = tok.group(0)
                        low = t.lower()
                        if low.startswith("<div"):
                            cls = _classes(t)
                            stack.append(cls[0].strip() if cls else "")
                        elif low.startswith("</div"):
                            if stack:
                                stack.pop()
                        else:
                            cls = next((c for c in reversed(stack) if c), "")
                            emitted.append(
                                f'<p class="{cls}">{t}</p>' if cls else f"<p>{t}</p>")
                            wrapped += 1
                out.extend(emitted)
                dropped += (j - i) - len(emitted)
                i = j
                continue
            if opens == closes == 0 and BARE_IMG_LINE.match(line):
                out.append(f"<p>{IMG.search(line).group(0)}</p>")
                wrapped += 1
                i += 1
                continue
        if BARE_IMG_LINE.match(line):
            out.append(f"<p>{IMG.search(line).group(0)}</p>")
            wrapped += 1
            i += 1
            continue
        out.append(line)
        i += 1
    return out, wrapped, dropped


def check_xml(lines: list[str]) -> str:
    try:
        ET.fromstring("\n".join(lines))
    except ET.ParseError as exc:
        return f"XML 解析失败：{exc}"
    return ""


def main() -> int:
    configure_output()
    ap = argparse.ArgumentParser(description="中文侧裸图片行包 <p>")
    add_content_roots(ap)
    ap.add_argument("--jp-root", type=Path, default=None, help="日文只读参考根；允许删除结构行时必须指定")
    ap.add_argument("--wrap-only", action="store_true", help="仅包装裸 <img> 行，禁止删除任何结构行（保证物理行数 100%% 不变）")
    ap.add_argument("--book", default=None, help="只处理指定作品号（如 S1_25）")
    add_edit_mode(ap)
    args = ap.parse_args()
    root, _ = content_roots(args, ap)
    if not args.wrap_only and (args.jp_root is None or not args.jp_root.is_dir()):
        ap.error("非 --wrap-only 模式必须显式指定 --jp-root 日文参考目录")

    total_wrapped = total_dropped = total_files = 0
    refused = []
    plans = []
    try:
        selected = {args.book.upper()} if args.book else None
        cn_dirs = books_by_id(root, selected)
        if not cn_dirs:
            raise ValueError("没有匹配的中文书籍，请核对 --root 与 --book")
        jp_dirs = (books_by_id(args.jp_root,
                              {japanese_book_id(wid) for wid in cn_dirs})
                   if args.jp_root is not None and not args.wrap_only else {})
        for bid, cn_dir in cn_dirs.items():
            if bid in NON_PAIR_WORK_IDS:
                print(f"[不适用] {bid}: 已登记非同一形态作品")
                continue
            paths = [p for p in sorted(cn_dir.rglob("*.xhtml")) if p.name.lower() != "nav.xhtml"]
            if not paths:
                raise ValueError(f"{bid}: 没有可检查的 XHTML 文件")
            # Resolve reference ambiguity before planning any content writes.
            jp_dir = jp_dirs.get(japanese_book_id(bid))
            jp_by = header_index(jp_dir) if jp_dir is not None else {}
            for path in paths:
                raw = path.read_bytes()
                text = raw.decode("utf-8-sig")
                lines = text.splitlines()
                new, wrapped, dropped = normalize(lines)
                if wrapped == 0 and dropped == 0:
                    continue
                header = (pairing_header_of(path.name) or "").upper()
                issue = check_xml(new)
                if not issue and args.wrap_only and dropped:
                    issue = f"wrap-only 模式禁止删除结构行（涉及 {dropped} 行）"
                if not issue and dropped and not is_packaging_header(header):
                    jp_path = jp_by.get(header)
                    if jp_path is None:
                        issue = "缺少对应日文参考文件，不能验证删除结构行后的配对"
                    else:
                        jp_lines = jp_path.read_text(encoding="utf-8-sig").splitlines()
                        if not any(line.strip() for line in jp_lines):
                            issue = "日文参考文件为空，未执行配对验证"
                        else:
                            issue = "; ".join(pair_structure_problems(jp_lines, new)[:3])
                if issue:
                    refused.append((bid, path.name, issue))
                    continue
                if args.apply:
                    require_edit_target(path, args.staging)
                plans.append((path, raw, new))
                total_files += 1
                total_wrapped += wrapped
                total_dropped += dropped
                print(f"[规范] {bid} {path.name}: 包 <p> {wrapped} 行"
                      + (f"，删除纯结构行 {dropped}" if dropped else "")
                      + ("   （行数不变）" if not dropped else ""))
    except (EditSafetyError, OSError, UnicodeError, ValueError) as exc:
        print(f"图片规范化未完成；没有写入任何文件：{exc}", file=sys.stderr)
        return 2
    if refused:
        print(f"\n预览（未写盘）：{total_files} 个可修改文件，拒绝 {len(refused)} 个文件")
        print(f"拒绝写入 {len(refused)} 个：", file=sys.stderr)
        for bid, name, why in refused[:10]:
            print(f"   {bid} {name}: {why}", file=sys.stderr)
        print("预检未完成；没有写入任何文件。", file=sys.stderr)
        return 1
    if args.apply:
        try:
            with rollback_paths(path for path, _, _ in plans):
                for path, raw, new in plans:
                    sep = "\r\n" if b"\r\n" in raw else "\n"
                    out_text = sep.join(new) + sep
                    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
                    path.write_bytes(bom + out_text.encode("utf-8"))
        except OSError as exc:
            print(f"图片规范化写入失败，已回滚本批次：{exc}", file=sys.stderr)
            return 2
    print(f"\n{'已写盘' if args.apply else '预览'}：{total_files} 个文件，"
          f"包 <p> {total_wrapped} 行，删除结构行 {total_dropped} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
