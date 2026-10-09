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
from edit_safety import (EditSafetyError, add_content_roots, add_edit_mode,
                         content_roots, require_edit_target)
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alignment_rules import NON_PAIR_WORK_IDS, pairing_header_of  # noqa: E402
from epub_ids import book_id  # noqa: E402

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


def jp_headers(cache: Path, *, direct: bool = False) -> set[str]:
    out = set()
    jp_dir = cache if direct else cache / "japanese-text"
    if not jp_dir.is_dir():
        return out
    for d in jp_dir.iterdir():
        if not d.is_dir():
            continue
        for p in d.rglob("*.xhtml"):
            if p.name.lower() == "nav.xhtml":
                continue
            h = pairing_header_of(p.name)
            if h:
                out.add(h.upper())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="中文侧裸图片行包 <p>")
    add_content_roots(ap)
    ap.add_argument("--jp-root", type=Path, default=None, help="日文只读参考根；允许删除结构行时必须指定")
    ap.add_argument("--wrap-only", action="store_true", help="仅包装裸 <img> 行，禁止删除任何结构行（保证物理行数 100% 不变）")
    ap.add_argument("--book", default=None, help="只处理指定作品号（如 S1_25）")
    add_edit_mode(ap)
    args = ap.parse_args()
    root, _ = content_roots(args, ap)
    if not args.wrap_only and (args.jp_root is None or not args.jp_root.is_dir()):
        ap.error("非 --wrap-only 模式必须显式指定 --jp-root 日文参考目录")

    jph = jp_headers(args.jp_root, direct=True) if args.jp_root is not None else set()
    total_wrapped = total_dropped = total_files = 0
    refused = []
    
    cn_dirs = [d for d in sorted(root.iterdir()) if d.is_dir()]
    if args.apply:
        try:
            for cn_dir in cn_dirs:
                if args.book and book_id(cn_dir.name) != args.book.upper():
                    continue
                for path in cn_dir.rglob("*.xhtml"):
                    require_edit_target(path, args.staging)
        except EditSafetyError as exc:
            ap.error(str(exc))

    for cn_dir in cn_dirs:
        bid = book_id(cn_dir.name)
        if bid is None or bid in NON_PAIR_WORK_IDS:
            continue
        if args.book and bid.upper() != args.book.upper():
            continue
        for path in sorted(cn_dir.rglob("*.xhtml")):
            if path.name.lower() == "nav.xhtml":
                continue
            raw = path.read_bytes()
            bom = raw.startswith(b"\xef\xbb\xbf")
            text = raw.decode("utf-8-sig", errors="replace")
            crlf = "\r\n" in text
            lines = text.splitlines()
            new, wrapped, dropped = normalize(lines)
            if wrapped == 0 and dropped == 0:
                continue
            header = (pairing_header_of(path.name) or "").upper()
            issue = check_xml(new)
            if not issue and args.wrap_only and dropped:
                issue = f"wrap-only 模式禁止删除结构行（涉及 {dropped} 行）"
            if not issue and dropped and header in jph:
                issue = f"该表头在日文侧有对应文件，删除 {dropped} 行会改变行数"
            if not issue and len(new) - sum(1 for x in new if x == "") != len(lines):
                pass
            if issue:
                refused.append((bid, path.name, issue))
                continue
            total_files += 1
            total_wrapped += wrapped
            total_dropped += dropped
            print(f"[规范] {bid} {path.name}: 包 <p> {wrapped} 行"
                  + (f"，删除纯结构行 {dropped}" if dropped else "")
                  + ("   （行数不变）" if not dropped else ""))
            if args.apply:
                sep = "\r\n" if crlf else "\n"
                out_text = sep.join(new) + sep
                path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + out_text.encode("utf-8"))
    print(f"\n{'已写盘' if args.apply else '预览'}：{total_files} 个文件，"
          f"包 <p> {total_wrapped} 行，删除结构行 {total_dropped} 行")
    if refused:
        print(f"拒绝写入 {len(refused)} 个：")
        for bid, name, why in refused[:10]:
            print(f"   {bid} {name}: {why}")
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
