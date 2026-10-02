#!/usr/bin/env python3
"""Preview or apply Japanese page-break markers to aligned Chinese EPUB files."""
from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from alignment_rules import pairing_header_of
from edit_safety import (EditSafetyError, add_content_roots, add_edit_mode,
                         content_roots, require_edit_target)
from merge_bw_pages import add_class_pb
from xhtml_structure import PB_RE, iter_content_pairs, pair_structure_problems

P_TAG_RE = re.compile(r"^\s*<p\b", re.I)
P_OPEN_RE = re.compile(r"^\s*<p\b[^>]*>", re.I)


def extract_header(filename: str) -> str | None:
    """Compatibility alias; pairing uses the shared complete-header parser."""
    return pairing_header_of(filename)


def plan_sync(japanese: list[str], chinese: list[str]) -> tuple[list[str] | None, str, int, int]:
    """Refuse structural drift before adding any marker; leave source untouched."""
    problems = pair_structure_problems(japanese, chinese)
    if problems:
        return None, "; ".join(problems[:3]), 0, 0
    out = list(chinese)
    existing = added = 0
    for idx, (jline, cline) in enumerate(zip(japanese, chinese)):
        jp_pb, cn_pb = bool(PB_RE.search(jline)), bool(PB_RE.search(cline))
        if cn_pb and not jp_pb:
            return None, f"L{idx + 1} 中文侧存在无日文对应的 pb，不擅自搬动", 0, 0
        if not jp_pb:
            continue
        if not P_TAG_RE.match(jline) or not P_TAG_RE.match(cline):
            return None, f"L{idx + 1} pb 不是配对的独立 p 段落", 0, 0
        jp_open, cn_open = P_OPEN_RE.match(jline), P_OPEN_RE.match(cline)
        if not jp_open or not cn_open or not PB_RE.search(jp_open.group(0)):
            return None, f"L{idx + 1} 日文 pb 不在 p 开标签上，需人工确认", 0, 0
        if cn_pb:
            if not PB_RE.search(cn_open.group(0)):
                return None, f"L{idx + 1} 中文 pb 不在 p 开标签上，需人工确认", 0, 0
            existing += 1
        else:
            # Restrict the existing shared helper to the p opener, so an img/span
            # class inside the paragraph cannot accidentally receive the marker.
            out[idx] = add_class_pb(cn_open.group(0)) + cline[cn_open.end():]
            added += 1
    try:
        ET.fromstring("\n".join(out))
    except ET.ParseError as exc:
        return None, f"中文 XML 解析失败：{exc}", 0, 0
    return out, "", existing, added


def main() -> int:
    parser = argparse.ArgumentParser(description="同步已对齐中日 XHTML 的 pb 标签（默认预览）")
    add_content_roots(parser, paired=True)
    add_edit_mode(parser)
    parser.add_argument("--book", help="只处理指定作品号")
    args = parser.parse_args()
    root, jp_root = content_roots(args, parser, paired=True)
    plans: list[tuple[Path, bytes, list[str]]] = []
    refused: list[str] = []
    existing = added = 0
    try:
        pairs = list(iter_content_pairs(root, jp_root, args.book))
        for wid, header, jp_path, cn_path in pairs:
            japanese = jp_path.read_text(encoding="utf-8-sig").splitlines()
            raw = cn_path.read_bytes()
            chinese = raw.decode("utf-8-sig").splitlines()
            if not any(PB_RE.search(line) for line in [*japanese, *chinese]):
                continue
            out, reason, already, gain = plan_sync(japanese, chinese)
            if out is None:
                refused.append(f"{wid} {header}: {reason}")
                continue
            existing += already
            added += gain
            if gain:
                print(f"[补全 pb] {wid} {cn_path.name}: {gain} 处")
                plans.append((cn_path, raw, out))
        if args.apply:
            for path, _, _ in plans:
                require_edit_target(path, args.staging)
    except (EditSafetyError, ValueError) as exc:
        parser.error(str(exc))
    if refused:
        for issue in refused:
            print(f"[拒绝] {issue}")
        print("预检未通过；没有写入任何文件。")
        return 1
    if args.apply:
        for path, raw, lines in plans:
            sep = "\r\n" if b"\r\n" in raw else "\n"
            text = sep.join(lines) + (sep if raw.endswith(b"\n") else "")
            bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
            path.write_bytes(bom + text.encode("utf-8"))
    print(f"{'已写盘' if args.apply else '预览'}：已有 pb {existing}；补全 {added}；文件 {len(plans)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
