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

sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
from xhtml_text import strip_ruby_annotations  # noqa: E402  注音剥除规则的唯一实现


_RUBY_PATTERN = re.compile(r"<ruby\b[^>]*>(.*?)</ruby>", re.I | re.S)
_RT_PATTERN = re.compile(r"<rt\b[^>]*>(.*?)</rt>", re.I | re.S)
_RP_PATTERN = re.compile(r"<rp\b[^>]*>.*?</rp>", re.I | re.S)
_TAG_PATTERN = re.compile(r"<[^>]+>")


def _clean_text(s: str) -> str:
    return html.unescape(_TAG_PATTERN.sub("", s)).strip()


def render_ruby_to_markup(inner: str) -> str:
    """把 <ruby> 的 inner 渲染为汉化组标准的 |基文[注音] 格式。

    - <rt> 内容（支持多段拼接）提取为 [注音]；<rp> 丢弃；
    - 无 <rt> 或注音为空时只输出基文；
    - 汉化组与项目规约标准记号：|基文[注音]（参考 docs/translation-spec.md §三.1）。
    """
    annos = [_clean_text(m.group(1)) for m in _RT_PATTERN.finditer(inner)]
    base_raw = _RP_PATTERN.sub("", inner)
    base_raw = _RT_PATTERN.sub("", base_raw)
    base = _clean_text(base_raw)
    if not annos:
        return base
    anno = "".join(annos)
    if not base:
        return anno
    if not anno:
        return base
    return f"|{base}[{anno}]"


def to_ruby_markup(html_text: str) -> str:
    """将 HTML 中的 <ruby> 结构转换为汉化组标准的 |基文[注音] 格式，并剥除其它 HTML 标签。"""
    text = _RUBY_PATTERN.sub(lambda m: render_ruby_to_markup(m.group(1)), html_text)
    text = _TAG_PATTERN.sub("", text)
    return html.unescape(text).strip()


def strip_ruby_markup(text: str) -> str:
    """把 |基文[注音] 记号快速剥除注文，还原为纯基文。"""
    return re.sub(r"\|([^|\[\n]+)\[[^\]\n]*\]", r"\1", text)


def strip_rt_and_tags(html_text: str) -> str:
    """剥除 <rt>/<rp>...</rt> 及所有 HTML 标签，返回干净纯文本。

    注音剥除规则唯一实现在 `xhtml_text.strip_ruby_annotations`。
    """
    text = _TAG_PATTERN.sub("", strip_ruby_annotations(html_text))
    return html.unescape(text).strip()


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

    def get_line(
        self,
        work: str,
        file_or_seq: str,
        line_num: int,
        strip_ruby: bool = True,
        ruby_mode: str | None = None,
    ) -> str | None:
        """获取指定行（1-based）的内容。超出范围或文件不存在返回 None。

        `ruby_mode` 选项：
          - "markup": 将 <ruby> 结构转为汉化组标准的 |基文[注音] 格式，剥除其它标签（复审/对照推荐）
          - "strip": 彻底剥除注音与所有 HTML 标签，返回干净基文纯文本
          - "raw": 保留原始 HTML
        未显式指定 `ruby_mode` 时，遵循向后兼容参数 `strip_ruby`（True 走 strip，False 走 raw）。
        """
        lines = self.get_lines(work, file_or_seq)
        if not lines or line_num < 1 or line_num > len(lines):
            return None

        raw = lines[line_num - 1]
        if ruby_mode == "markup":
            return to_ruby_markup(raw)
        if ruby_mode == "strip":
            return strip_rt_and_tags(raw)
        if ruby_mode == "raw":
            return raw.strip()

        if strip_ruby:
            return strip_rt_and_tags(raw)
        return raw.strip()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="查询日文缓存中对应行文本（支持汉化组 |基文[注音] 记号）")
    parser.add_argument("work", help="作品号，如 S3_03")
    parser.add_argument("file", help="中文文件名或内容序，如 S3_03-04_Chapter2.xhtml 或 04")
    parser.add_argument("line", type=int, help="行号（1-based）")
    parser.add_argument(
        "--mode",
        choices=["markup", "strip", "raw"],
        default="markup",
        help="注音呈现模式：markup (|基文[注音], 默认), strip (剥除注音), raw (原始HTML)",
    )
    parser.add_argument("--raw", action="store_true", help="保留完整 HTML 标签（等价于 --mode raw）")
    parser.add_argument("--strip", action="store_true", help="彻底剥除注音（等价于 --mode strip）")
    parser.add_argument("--jp-base", default=DEFAULT_JP_BASE, help="日文解包缓存基础目录")
    args = parser.parse_args(argv)

    mode = args.mode
    if args.raw:
        mode = "raw"
    elif args.strip:
        mode = "strip"

    lookup = JapaneseSourceLookup(REPO_ROOT, args.jp_base)
    text = lookup.get_line(args.work, args.file, args.line, ruby_mode=mode)
    if text is None:
        print(f"[未找到] 作品 {args.work} 文件 {args.file} 第 {args.line} 行", file=sys.stderr)
        return 1

    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
