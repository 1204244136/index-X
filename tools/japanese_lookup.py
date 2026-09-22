#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日文原文对应行定位与提取工具（原子模块）。

职责：
  给定作品号（如 S3_03）、中文文件名（如 S3_03-04_Chapter2.xhtml）与行号，
  在日文缓存目录（.cache/epub-work/japanese-text/）中定位对应文件并提取该行纯文本（自动剥除 <rt>/<rp> 注音）。

用法：
    # 作为 CLI：
    python tools/japanese_lookup.py S3_03 S3_03-04_Chapter2.xhtml 55
    python tools/japanese_lookup.py S3_03 04 55

    # 作为 Python 模块：
    from japanese_lookup import JapaneseSourceLookup
    lookup = JapaneseSourceLookup(repo_root)
    text = lookup.get_line("S3_03", "S3_03-04_Chapter2.xhtml", 55)
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_JP_BASE = os.path.join(REPO_ROOT, ".cache", "epub-work", "japanese-text")


def strip_rt_and_tags(html_text: str) -> str:
    """剥除 <rt>...</rt>、<rp>...</rp> 及所有 HTML 标签，返回干净纯文本。"""
    # 先剥除 rt 和 rp 注音内容，避免注音被混入正文
    text = re.sub(r"<(rt|rp)\b[^>]*>.*?</\1>", "", html_text, flags=re.I | re.S)
    # 剥除所有 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)
    # 还原字符实体并整理空白
    text = html.unescape(text)
    return text.strip()


class JapaneseSourceLookup:
    """日文原文章节文件与行内容查询器（带内存行缓存）。"""

    def __init__(self, repo_root: str = REPO_ROOT, jp_base_dir: str = DEFAULT_JP_BASE) -> None:
        self.repo_root = repo_root
        self.jp_base_dir = jp_base_dir
        self._work_dir_cache: dict[str, Path | None] = {}
        self._file_lines_cache: dict[str, list[str]] = {}

    def find_work_dir(self, work: str) -> Path | None:
        """根据作品号（如 S3_03）查找对应的日文解包目录。"""
        if work in self._work_dir_cache:
            return self._work_dir_cache[work]

        base = Path(self.jp_base_dir)
        if not base.is_dir():
            self._work_dir_cache[work] = None
            return None

        # 匹配包含 [S3_03] 或 S3_03 的目录
        target_dir = None
        for entry in base.iterdir():
            if entry.is_dir() and work in entry.name:
                item_xhtml = entry / "item" / "xhtml"
                if item_xhtml.is_dir():
                    target_dir = item_xhtml
                else:
                    target_dir = entry
                break

        self._work_dir_cache[work] = target_dir
        return target_dir

    def resolve_jp_filename(self, work: str, file_or_seq: str) -> str:
        """根据中文文件名或内容序号，返回对应的日文文件名（如 S3_03-04.xhtml）。"""
        # 如果直接给了完整文件名如 S3_03-04_Chapter2.xhtml
        m = re.search(r"(S\d+_\d+-\d+)", file_or_seq)
        if m:
            return f"{m.group(1)}.xhtml"

        # 如果给了两段内容序如 S5_01_03-02
        m5 = re.search(r"(S5_\d+_\d+-\d+)", file_or_seq)
        if m5:
            return f"{m5.group(1)}.xhtml"

        # 如果只给了纯数字如 04 或 4
        m_num = re.match(r"^0*(\d+)$", file_or_seq.strip())
        if m_num:
            seq_num = int(m_num.group(1))
            return f"{work}-{seq_num:02d}.xhtml"

        return file_or_seq

    def get_lines(self, work: str, file_or_seq: str) -> list[str]:
        """获取指定日文文件的全部原始行（行缓存）。"""
        work_dir = self.find_work_dir(work)
        if not work_dir:
            return []

        jp_name = self.resolve_jp_filename(work, file_or_seq)
        cache_key = f"{work}:{jp_name}"
        if cache_key in self._file_lines_cache:
            return self._file_lines_cache[cache_key]

        target_file = work_dir / jp_name
        if not target_file.is_file():
            self._file_lines_cache[cache_key] = []
            return []

        try:
            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            lines = []

        self._file_lines_cache[cache_key] = lines
        return lines

    def get_line(self, work: str, file_or_seq: str, line_num: int, strip_ruby: bool = True) -> str | None:
        """获取指定行（1-based）的内容。超出范围或文件不存在返回 None。"""
        lines = self.get_lines(work, file_or_seq)
        if not lines or line_num < 1 or line_num > len(lines):
            return None

        raw = lines[line_num - 1]
        if strip_ruby:
            return strip_rt_and_tags(raw)
        return raw.strip()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="查询日文缓存中对应行纯文本（自动剥除注音）")
    parser.add_argument("work", help="作品号，如 S3_03")
    parser.add_argument("file", help="中文文件名或内容序，如 S3_03-04_Chapter2.xhtml 或 04")
    parser.add_argument("line", type=int, help="行号（1-based）")
    parser.add_argument("--raw", action="store_true", help="保留完整 HTML 标签（不剥除 <rt>）")
    parser.add_argument("--jp-base", default=DEFAULT_JP_BASE, help="日文解包缓存基础目录")
    args = parser.parse_args(argv)

    lookup = JapaneseSourceLookup(REPO_ROOT, args.jp_base)
    text = lookup.get_line(args.work, args.file, args.line, strip_ruby=not args.raw)
    if text is None:
        print(f"[未找到] 作品 {args.work} 文件 {args.file} 第 {args.line} 行", file=sys.stderr)
        return 1

    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
