#!/usr/bin/env python3
"""中日换页标记 (pb) 同步工具。

根据 AGENTS.md 规约：「中日两侧同一位置的换页标记与视觉间隔数量一致」。
分页源合并时在日文侧段落追加了 `class="pb"`，中文侧相应对齐行若缺失 `pb`，
应在中文侧对应段落追加 `class="pb"`。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PB_RE = re.compile(r'\bclass=[\"\'][^\"\']*\bpb\b[^\"\']*[\"\']')
P_TAG_RE = re.compile(r'<p\b', re.I)


def add_class_pb(line: str) -> str:
    """在段落标签上追加 class="pb" 用于跨文件分页。"""
    if re.search(r'\bclass\s*=\s*"([^"]*)"', line):
        return re.sub(
            r'\bclass\s*=\s*"([^"]*)"',
            lambda m: f'class="{m.group(1)} pb"' if "pb" not in m.group(1).split() else m.group(0),
            line,
            count=1,
        )
    elif re.search(r"\bclass\s*=\s*'([^']*)'", line):
        return re.sub(
            r"\bclass\s*=\s*'([^']*)'",
            lambda m: f"class='{m.group(1)} pb'" if "pb" not in m.group(1).split() else m.group(0),
            line,
            count=1,
        )
    else:
        return re.sub(r"<p\b", '<p class="pb"', line, count=1, flags=re.I)


def extract_header(filename: str) -> str | None:
    # Match S1_01-02 or S5_01_03-02 or S6_22.06.10-06
    m = re.match(r"^(S\d+_(?:\d+(?:_\d+)?|\d{2}(?:\.\d{2}){2})-[A-Za-z0-9_.-]+?)(?:_[^.]+)?\.xhtml$", filename, re.I)
    if m:
        return m.group(1)
    return None


def main():
    parser = argparse.ArgumentParser(description="同步中日 XHTML 中的 pb 标签")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写盘")
    parser.add_argument("--apply", action="store_true", help="实际写入修改")
    args = parser.parse_args()

    jp_root = Path(".cache/epub-work/japanese-text")
    zh_root = Path(".cache/epub-work/chinese-text")

    if not jp_root.exists() or not zh_root.exists():
        print("未找到 .cache/epub-work 目录")
        return 1

    jp_files = list(jp_root.rglob("*.xhtml"))
    zh_files = list(zh_root.rglob("*.xhtml"))

    # Map header -> zh_file
    zh_by_header: dict[str, Path] = {}
    for zf in zh_files:
        h = extract_header(zf.name)
        if h:
            zh_by_header[h] = zf

    total_jp_pb = 0
    synced_count = 0
    already_synced = 0
    mismatch_count = 0

    files_modified: dict[Path, list[str]] = {}

    for jf in jp_files:
        h = extract_header(jf.name)
        if not h:
            continue
        jp_text = jf.read_text(encoding="utf-8")
        if "pb" not in jp_text:
            continue
        jp_lines = jp_text.splitlines()

        zf = zh_by_header.get(h)
        if not zf:
            continue

        zh_lines = files_modified.get(zf)
        if zh_lines is None:
            zh_lines = zf.read_text(encoding="utf-8").splitlines()

        modified = False
        for idx, jline in enumerate(jp_lines):
            if PB_RE.search(jline):
                total_jp_pb += 1
                if idx >= len(zh_lines):
                    print(f"[越界] {jf.name}:{idx+1} 日文有 pb，但中文 {zf.name} 只有 {len(zh_lines)} 行")
                    mismatch_count += 1
                    continue
                zline = zh_lines[idx]
                if PB_RE.search(zline):
                    already_synced += 1
                else:
                    if P_TAG_RE.search(zline):
                        new_zline = add_class_pb(zline)
                        zh_lines[idx] = new_zline
                        modified = True
                        synced_count += 1
                        print(f"[补全 pb] {zf.name}:{idx+1}")
                        print(f"  JP: {jline[:70]}")
                        print(f"  ZH 旧: {zline[:70]}")
                        print(f"  ZH 新: {new_zline[:70]}")
                    else:
                        print(f"[非段落] {zf.name}:{idx+1} 中文行非 <p> 标签: {zline[:70]}")
                        mismatch_count += 1

        if modified:
            files_modified[zf] = zh_lines

    print("\n--- 统计 ---")
    print(f"日文 pb 总数: {total_jp_pb}")
    print(f"中文已有 pb: {already_synced}")
    print(f"本次补充 pb: {synced_count}")
    print(f"异常/不匹配: {mismatch_count}")
    print(f"涉及修改文件数: {len(files_modified)}")

    if args.apply:
        for zf, lines in files_modified.items():
            zf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"已成功写入 {len(files_modified)} 个文件！")
    else:
        print("当前为预览模式，使用 --apply 写入修改。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
