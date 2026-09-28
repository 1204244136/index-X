#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全库文本与术语检索工具（注音友好 + 中日双向联动）。

用于在 EPUB 缓存（.cache/epub-work/）或归档目录中进行精准的全文与术语检索。

核心特性：
1. 注音保全（Ruby-Preserving）：
   将 HTML 的 `<ruby>基文<rt>注音</rt></ruby>` 标签转化为清晰可读的 `基文(注音)` 格式，
   剥除排版 HTML 标签的同时，完整保留汉字及其注音假名/特殊读音（绝不粗暴丢弃注音信息）。
2. 三轨匹配引擎（Triple-Track Matching）：
   - 基文轨：剥除注音后匹配纯汉字/正文，彻底消除分散注音标签对长词的打断（如搜“超能力者”、“上条当麻”稳稳命中）；
   - 注音轨：专门针对 `<rt>` 注音假名/英文进行匹配（如搜“レールガン”、“イマジンブレイカー”直接命中）；
   - 综合轨：在带注音格式化文本中直接匹配完整句子与词汇。
3. 假名与英数折叠归一化（Kana & Full-Width Folding）：
   - 小字假名（ゃゅょっ等）与大字假名（ヤユヨツ等）互相折叠，完美解决 BookWalker 源注音 99.8% 写作大字的排印妥协；
   - 全角/半角英数及标点符号（如 ５ vs 5，＝ vs =）自动归一化，彻底打通《译名表》不妥协写法与源写法的检索鸿沟。
4. 中日双语自动联动（Bilingual Pair Linkage）：
   - 搜中文时，命中行后自动关联展示对应日文行的原文及注音；
   - 搜日文时，命中行后自动关联展示对应中文行的成品译文；
   - 一次搜索，原文、译文、读音全景呈现，术语统一与校对核查一步到位。
5. 结果高亮与安全输出：
   - 命中词精准加粗或高亮标记，一眼看清是命中汉字基文还是命中注音；
   - 支持 --max-matches、--work 通配符过滤、--side（cn/jp/both），防止刷屏撑爆模型上下文。

常用示例：
    # 1. 在日文侧检索特殊读音“レールガン”（自动联动中文译文）
    python tools/search_text.py "レールガン" --side jp

    # 2. 检索汉字“超電磁砲”（无论原 HTML 是否被注音打断，均能命中并展示注音）
    python tools/search_text.py "超電磁砲" --side jp

    # 3. 检索不妥协写法“カリキュラム”（自动命中源内大字写法“カリキユラム”）
    python tools/search_text.py "カリキュラム" --side jp

    # 4. 检索中文译名“幻想杀手”（自动联动日文原文对应行及注音）
    python tools/search_text.py "幻想杀手" --side cn

    # 5. 指定作品范围与上下文
    python tools/search_text.py "魔術サイド" --work "S1_*" -C 1

    # 6. 输出为 Markdown 或 JSON
    python tools/search_text.py "御坂美琴" --work "S1_01" --format markdown
"""
from __future__ import annotations

import argparse
import fnmatch
import html
import io
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CN_CACHE = REPO_ROOT / ".cache" / "epub-work" / "chinese-text"
DEFAULT_JP_CACHE = REPO_ROOT / ".cache" / "epub-work" / "japanese-text"
DEFAULT_EPUB_DIR = REPO_ROOT / "EPUB"

# 小字假名映射到大字假名
KANA_SMALL_TO_LARGE = str.maketrans({
    "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お",
    "っ": "つ", "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "ゎ": "わ",
    "ァ": "ア", "ィ": "イ", "ゥ": "ウ", "ェ": "エ", "ォ": "オ",
    "ッ": "ツ", "ャ": "ヤ", "ュ": "ユ", "ョ": "ヨ", "ヮ": "ワ",
    "ヵ": "カ", "ヶ": "ケ",
})


def _ensure_utf8_stdout() -> None:
    """确保在 Windows 终端中输出 UTF-8 文本而不发生编码报错。"""
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def fold_text(text: str) -> str:
    """对文本进行全半角折叠、小字假名折叠以及大小写归一化。"""
    # 1. NFKC 归一化（全角英数、全角标点转半角 ASCII）
    s = unicodedata.normalize("NFKC", text)
    # 2. 小字假名映射为大字假名
    s = s.translate(KANA_SMALL_TO_LARGE)
    # 3. 统一转小写
    return s.lower()


@dataclass
class ParsedRubyLine:
    raw: str  # 原始 HTML
    formatted: str  # 带注音的可读文本，如 基文(注音)
    base: str  # 纯基文（剥除 rt 及所有标签）
    rubies: list[str]  # 提取出的所有注音文本
    line_no: int


_RUBY_PATTERN = re.compile(
    r"<ruby\b[^>]*>(.*?)</ruby>",
    flags=re.IGNORECASE | re.DOTALL,
)
_RT_TAG_PATTERN = re.compile(
    r"<rt\b[^>]*>(.*?)</rt>",
    flags=re.IGNORECASE | re.DOTALL,
)
_RP_TAG_PATTERN = re.compile(
    r"<rp\b[^>]*>.*?</rp>",
    flags=re.IGNORECASE | re.DOTALL,
)
_TAG_PATTERN = re.compile(r"<[^>]+>")


def parse_ruby_line(raw_line: str, line_no: int) -> ParsedRubyLine:
    """解析一行 HTML，生成带注音格式化文本、纯基文本和注音列表。"""
    rubies_found: list[str] = []

    # 1. 提取所有 <rt> 的内容，并构建 formatted_text
    def replace_ruby(match: re.Match) -> str:
        inner = match.group(1)
        # 去除 rp 标签
        inner = _RP_TAG_PATTERN.sub("", inner)

        # 查找所有 rt
        rt_matches = list(_RT_TAG_PATTERN.finditer(inner))
        if not rt_matches:
            # 没有 rt，直接去标签返回
            clean_base = _TAG_PATTERN.sub("", inner).strip()
            return clean_base

        # 提取各个 rt 及其前面的基文
        parts = []
        last_end = 0
        for rtm in rt_matches:
            base_part = inner[last_end:rtm.start()]
            clean_base = _TAG_PATTERN.sub("", base_part).strip()
            clean_rt = _TAG_PATTERN.sub("", rtm.group(1)).strip()
            if clean_rt:
                rubies_found.append(clean_rt)
            if clean_base and clean_rt:
                parts.append(f"{clean_base}({clean_rt})")
            elif clean_base:
                parts.append(clean_base)
            elif clean_rt:
                parts.append(f"({clean_rt})")
            last_end = rtm.end()

        # 处理最后一个 rt 之后的基文（如果有）
        trailing_base = inner[last_end:]
        clean_trailing = _TAG_PATTERN.sub("", trailing_base).strip()
        if clean_trailing:
            parts.append(clean_trailing)

        return "".join(parts)

    # 替换 ruby 为 基文(注音)
    formatted_step1 = _RUBY_PATTERN.sub(replace_ruby, raw_line)
    formatted_text = html.unescape(_TAG_PATTERN.sub("", formatted_step1)).strip()

    # 2. 构建纯基文本（剥离 rt、rp 及所有 HTML 标签）
    no_rt = _RT_TAG_PATTERN.sub("", raw_line)
    no_rp = _RP_TAG_PATTERN.sub("", no_rt)
    base_text = html.unescape(_TAG_PATTERN.sub("", no_rp)).strip()

    # 规范化 rubies 列表中的字符实体
    rubies_found = [html.unescape(r) for r in rubies_found if r]

    return ParsedRubyLine(
        raw=raw_line,
        formatted=formatted_text,
        base=base_text,
        rubies=rubies_found,
        line_no=line_no,
    )


@dataclass
class SearchMatch:
    work_id: str
    file_path: Path
    file_rel_name: str
    line_no: int
    side: str  # "cn" 或 "jp"
    parsed_line: ParsedRubyLine
    matched_track: str  # "base" | "ruby" | "formatted"
    highlighted_text: str
    paired_line: Optional[ParsedRubyLine] = None
    paired_file_name: Optional[str] = None
    context_before: list[ParsedRubyLine] = None  # type: ignore
    context_after: list[ParsedRubyLine] = None  # type: ignore


def highlight_match(formatted_text: str, query: str, exact: bool = False) -> str:
    """在格式化文本中加粗高亮匹配项。"""
    if not query:
        return formatted_text

    if exact:
        pattern = re.escape(query)
        return re.sub(pattern, lambda m: f"**{m.group(0)}**", formatted_text)

    # 折叠匹配时，在原串中定位匹配区间
    folded_q = fold_text(query)
    folded_text = fold_text(formatted_text)

    idx = folded_text.find(folded_q)
    if idx != -1:
        # 在折叠串中找到，由于单字折叠（NFKC + 大字映射）大致长度一致，寻找对应字符
        # 最稳妥的方式是在 formatted_text 中通过不区分大小写的字符正则匹配
        pattern_chars = []
        for ch in query:
            ch_folded = fold_text(ch)
            if ch_folded:
                pattern_chars.append(f"[{re.escape(ch)}{re.escape(ch_folded)}]")
            else:
                pattern_chars.append(re.escape(ch))
        flexible_pat = "".join(pattern_chars)
        try:
            return re.sub(flexible_pat, lambda m: f"**{m.group(0)}**", formatted_text, flags=re.IGNORECASE)
        except re.error:
            pass

    # 若综合格式化文本未直接包含，但命中发生在基文或注音，尝试将 query 本身加粗
    if query in formatted_text:
        return formatted_text.replace(query, f"**{query}**")

    return formatted_text


def match_line(
    parsed: ParsedRubyLine,
    query: str,
    regex_obj: Optional[re.Pattern] = None,
    exact: bool = False,
) -> Optional[tuple[str, str]]:
    """检查单行是否命中查询。

    返回: (matched_track, highlighted_text) 或 None
    """
    # 1. 正则模式
    if regex_obj is not None:
        # 先试 formatted
        if regex_obj.search(parsed.formatted):
            hl = regex_obj.sub(lambda m: f"**{m.group(0)}**", parsed.formatted)
            return ("formatted", hl)
        # 再试 base
        if regex_obj.search(parsed.base):
            return ("base", highlight_match(parsed.formatted, query, exact=True))
        # 再试 rubies
        for rb in parsed.rubies:
            if regex_obj.search(rb):
                return ("ruby", highlight_match(parsed.formatted, query, exact=True))
        return None

    # 2. 精确模式
    if exact:
        if query in parsed.formatted:
            hl = parsed.formatted.replace(query, f"**{query}**")
            return ("formatted", hl)
        if query in parsed.base:
            return ("base", highlight_match(parsed.formatted, query, exact=True))
        for rb in parsed.rubies:
            if query in rb:
                return ("ruby", highlight_match(parsed.formatted, query, exact=True))
        return None

    # 3. 智能折叠三轨匹配（默认）
    folded_q = fold_text(query)
    if not folded_q:
        return None

    # 检查是否命中注音 (Track: ruby)
    is_ruby_match = False
    for rb in parsed.rubies:
        if folded_q in fold_text(rb):
            is_ruby_match = True
            break
    if not is_ruby_match and parsed.rubies:
        joined_rubies = "".join(parsed.rubies)
        if folded_q in fold_text(joined_rubies):
            is_ruby_match = True

    # 检查是否命中基文 (Track: base)
    folded_base = fold_text(parsed.base)
    is_base_match = folded_q in folded_base

    # 检查是否命中完整带注音文本 (Track: formatted)
    folded_fmt = fold_text(parsed.formatted)
    is_fmt_match = folded_q in folded_fmt

    if is_ruby_match and not is_base_match:
        hl = highlight_match(parsed.formatted, query)
        return ("ruby", hl)
    elif is_base_match and not is_ruby_match:
        hl = highlight_match(parsed.formatted, query)
        return ("base", hl)
    elif is_fmt_match or is_base_match or is_ruby_match:
        hl = highlight_match(parsed.formatted, query)
        track = "base" if is_base_match else ("ruby" if is_ruby_match else "formatted")
        return (track, hl)

    return None


class BilingualCorpus:
    """中日双语语料库加载与行对齐查询器。"""

    def __init__(
        self,
        cn_dir: Path = DEFAULT_CN_CACHE,
        jp_dir: Path = DEFAULT_JP_CACHE,
        epub_dir: Path = DEFAULT_EPUB_DIR,
        use_cache: bool = True,
    ):
        self.cn_dir = cn_dir
        self.jp_dir = jp_dir
        self.epub_dir = epub_dir
        self.use_cache = use_cache

        # 缓存文件行：file_path -> list[ParsedRubyLine]
        self._parsed_file_cache: dict[Path, list[ParsedRubyLine]] = {}
        # 缓存作品目录映射：side -> {work_id: dir_path}
        self._work_dirs: dict[str, dict[str, Path]] = {"cn": {}, "jp": {}}
        self._scan_work_dirs()

    def _find_text_dir(self, entry: Path) -> Path:
        """寻找解包书籍中的 XHTML 正文目录（支持 OEBPS/Text、item/xhtml 等）。"""
        candidates = [
            entry / "OEBPS" / "Text",
            entry / "item" / "xhtml",
            entry / "item" / "text",
            entry / "Text",
            entry / "xhtml",
        ]
        for c in candidates:
            if c.is_dir():
                return c
        return entry

    def _scan_work_dirs(self) -> None:
        """扫描中日缓存目录下的所有作品子目录（若中文缓存缺失则自动回退到 EPUB/）。"""
        # 1. 扫描日文
        if self.jp_dir.is_dir():
            for entry in self.jp_dir.iterdir():
                if entry.is_dir():
                    m = re.search(r"\[([A-Za-z0-9_.]+)\]", entry.name)
                    w_id = m.group(1) if m else entry.name
                    self._work_dirs["jp"][w_id] = self._find_text_dir(entry)

        # 2. 扫描中文（优先 .cache，若无则读 EPUB）
        cn_source = self.cn_dir if self.cn_dir.is_dir() else self.epub_dir
        if cn_source.is_dir():
            for entry in cn_source.iterdir():
                if entry.is_dir():
                    m = re.search(r"\[([A-Za-z0-9_.]+)\]", entry.name)
                    w_id = m.group(1) if m else entry.name
                    text_dir = self._find_text_dir(entry)
                    # 如果该目录有 xhtml 文件，记录
                    if list(text_dir.glob("*.xhtml")):
                        self._work_dirs["cn"][w_id] = text_dir

    def get_parsed_lines(self, file_path: Path) -> list[ParsedRubyLine]:
        """读取并缓存文件的 ParsedRubyLine 列表。"""
        if file_path in self._parsed_file_cache:
            return self._parsed_file_cache[file_path]

        if not file_path.is_file():
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

        lines = content.splitlines()
        parsed_list = [parse_ruby_line(line, idx + 1) for idx, line in enumerate(lines)]
        self._parsed_file_cache[file_path] = parsed_list
        return parsed_list

    def extract_header_tag(self, filename: str) -> str:
        """从文件名提取对齐表头，例如 S1_01-02_Chapter1.xhtml -> S1_01-02。"""
        # S5 系列
        m5 = re.search(r"(S5_\d+_\d+-\d+)", filename)
        if m5:
            return m5.group(1)
        # 普通系列 S1_01-02
        m = re.search(r"([A-Za-z0-9_.]+-\d+)", filename)
        if m:
            return m.group(1)
        # SP 等稳定名称 S1_25-Uiharu_Kazari
        m_sp = re.search(r"(S\d+_\d+-[A-Za-z0-9_]+)", filename)
        if m_sp:
            return m_sp.group(1)
        return Path(filename).stem

    def find_paired_line(
        self,
        current_work_id: str,
        current_filename: str,
        line_no: int,
        source_side: str,
    ) -> tuple[Optional[ParsedRubyLine], Optional[str]]:
        """查找对应语言侧同表头文件的对应行。"""
        target_side = "jp" if source_side == "cn" else "cn"
        target_work_dir = self._work_dirs.get(target_side, {}).get(current_work_id)
        if not target_work_dir or not target_work_dir.is_dir():
            return None, None

        header = self.extract_header_tag(current_filename)

        # 查找目标目录下表头匹配的 xhtml 文件
        target_file = None
        for candidate in target_work_dir.glob("*.xhtml"):
            cand_header = self.extract_header_tag(candidate.name)
            if cand_header == header:
                target_file = candidate
                break

        if not target_file:
            return None, None

        target_lines = self.get_parsed_lines(target_file)
        if 1 <= line_no <= len(target_lines):
            return target_lines[line_no - 1], target_file.name

        return None, target_file.name


def search_corpus(
    corpus: BilingualCorpus,
    query: str,
    work_filter: str | None = None,
    side: str = "both",
    exact: bool = False,
    is_regex: bool = False,
    max_matches: int = 50,
    context_lines: int = 0,
    enable_pair: bool = True,
) -> list[SearchMatch]:
    """在语料库中执行检索。"""
    regex_obj = None
    if is_regex:
        flags = 0 if exact else re.IGNORECASE
        regex_obj = re.compile(query, flags)

    matches: list[SearchMatch] = []

    # 确定要检索的侧
    sides_to_search: list[str] = []
    side_lower = side.lower()
    if side_lower in ("cn", "chinese"):
        sides_to_search = ["cn"]
    elif side_lower in ("jp", "japanese"):
        sides_to_search = ["jp"]
    else:
        sides_to_search = ["cn", "jp"]

    for cur_side in sides_to_search:
        work_dict = corpus._work_dirs.get(cur_side, {})
        for w_id, w_dir in sorted(work_dict.items()):
            # 作品号过滤
            if work_filter:
                if not fnmatch.fnmatch(w_id, work_filter) and not fnmatch.fnmatch(w_id.lower(), work_filter.lower()):
                    continue

            # 遍历该作品下的所有 xhtml 文件
            xhtml_files = sorted(w_dir.glob("*.xhtml"))
            for xfile in xhtml_files:
                # 跳过部分非正文文件如 nav, style
                if xfile.name in ("nav.xhtml", "toc.xhtml"):
                    continue

                lines = corpus.get_parsed_lines(xfile)
                for idx, pline in enumerate(lines):
                    res = match_line(pline, query, regex_obj=regex_obj, exact=exact)
                    if res is None:
                        continue

                    matched_track, highlighted_text = res

                    # 获取上下文
                    ctx_before = []
                    ctx_after = []
                    if context_lines > 0:
                        start_c = max(0, idx - context_lines)
                        end_c = min(len(lines), idx + context_lines + 1)
                        ctx_before = lines[start_c:idx]
                        ctx_after = lines[idx + 1:end_c]

                    # 获取配对行
                    paired_pline = None
                    paired_fname = None
                    if enable_pair:
                        paired_pline, paired_fname = corpus.find_paired_line(
                            w_id, xfile.name, pline.line_no, cur_side
                        )

                    match_item = SearchMatch(
                        work_id=w_id,
                        file_path=xfile,
                        file_rel_name=xfile.name,
                        line_no=pline.line_no,
                        side=cur_side,
                        parsed_line=pline,
                        matched_track=matched_track,
                        highlighted_text=highlighted_text,
                        paired_line=paired_pline,
                        paired_file_name=paired_fname,
                        context_before=ctx_before,
                        context_after=ctx_after,
                    )
                    matches.append(match_item)

                    if max_matches > 0 and len(matches) >= max_matches:
                        return matches

    return matches


def format_search_results(
    matches: list[SearchMatch],
    output_format: str = "text",
    query: str = "",
) -> str:
    """将检索结果格式化为指定文本。"""
    if not matches:
        return f"未找到与 '{query}' 相关的匹配内容。"

    out_fmt = output_format.lower()

    # JSON 格式
    if out_fmt == "json":
        records = []
        for m in matches:
            item: dict[str, Any] = {
                "work": m.work_id,
                "side": m.side,
                "file": m.file_rel_name,
                "line": m.line_no,
                "track": m.matched_track,
                "text": m.parsed_line.formatted,
                "base": m.parsed_line.base,
                "rubies": m.parsed_line.rubies,
            }
            if m.paired_line:
                paired_side = "jp" if m.side == "cn" else "cn"
                item["paired"] = {
                    "side": paired_side,
                    "file": m.paired_file_name,
                    "line": m.paired_line.line_no,
                    "text": m.paired_line.formatted,
                    "base": m.paired_line.base,
                    "rubies": m.paired_line.rubies,
                }
            records.append(item)
        return json.dumps(records, ensure_ascii=False, indent=2)

    # TSV 格式
    if out_fmt == "tsv":
        lines = ["Work\tSide\tFile\tLine\tTrack\tFormatted_Text\tPaired_Text"]
        for m in matches:
            paired_txt = m.paired_line.formatted if m.paired_line else ""
            lines.append(
                f"{m.work_id}\t{m.side}\t{m.file_rel_name}\t{m.line_no}\t{m.matched_track}\t"
                f"{m.parsed_line.formatted}\t{paired_txt}"
            )
        return "\n".join(lines)

    # Markdown 格式
    if out_fmt in ("markdown", "md"):
        lines = [f"### 检索结果: `{query}` (共 {len(matches)} 处匹配)\n"]
        for m in matches:
            side_label = "中文" if m.side == "cn" else "日文"
            track_label = {"base": "基文", "ruby": "注音", "formatted": "综合"}.get(m.matched_track, m.matched_track)
            lines.append(f"#### [{m.work_id}] `{m.file_rel_name}` L{m.line_no} ({side_label} · 命中:{track_label})")

            # 上下文前
            if m.context_before:
                for c in m.context_before:
                    lines.append(f"- L{c.line_no}: {c.formatted}")

            # 命中行
            lines.append(f"- **L{m.line_no}**: {m.highlighted_text}")

            # 上下文后
            if m.context_after:
                for c in m.context_after:
                    lines.append(f"- L{c.line_no}: {c.formatted}")

            # 对照行
            if m.paired_line:
                paired_label = "对应日文" if m.side == "cn" else "对应中文"
                lines.append(f"> **{paired_label} (L{m.paired_line.line_no})**: {m.paired_line.formatted}")
            lines.append("")
        return "\n".join(lines)

    # 默认纯文本 (text) 格式
    out_lines = [f"=== 检索词: '{query}' | 命中数: {len(matches)} ==="]
    for m in matches:
        side_tag = "CN" if m.side == "cn" else "JP"
        track_tag = {"base": "基文", "ruby": "注音", "formatted": "综合"}.get(m.matched_track, m.matched_track)
        out_lines.append(f"[{m.work_id}] {m.file_rel_name}:{m.line_no} [{side_tag}|{track_tag}]")

        if m.context_before:
            for c in m.context_before:
                out_lines.append(f"    L{c.line_no}: {c.formatted}")

        out_lines.append(f"  > L{m.line_no}: {m.highlighted_text}")

        if m.context_after:
            for c in m.context_after:
                out_lines.append(f"    L{c.line_no}: {c.formatted}")

        if m.paired_line:
            p_side = "JP" if m.side == "cn" else "CN"
            out_lines.append(f"  = [{p_side}] L{m.paired_line.line_no}: {m.paired_line.formatted}")

        out_lines.append("")
    return "\n".join(out_lines).rstrip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="全库文本与术语检索工具（注音友好 + 三轨匹配 + 假名折叠 + 中日双向联动）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="?", help="要搜索的文本、关键词或正则表达式")
    parser.add_argument(
        "-w", "--work",
        default=None,
        help="按作品号过滤（支持通配符，如 'S1_*', 'S3_01', 'S5_01_*'）",
    )
    parser.add_argument(
        "-s", "--side",
        choices=["both", "cn", "jp"],
        default="both",
        help="指定检索侧：both (中日都搜, 默认) / cn (仅中文) / jp (仅日文)",
    )
    parser.add_argument(
        "-C", "--context",
        type=int,
        default=0,
        help="显示命中行前后各 N 行的上下文（默认: 0）",
    )
    parser.add_argument(
        "-m", "--max-matches",
        type=int,
        default=50,
        help="最大匹配返回数量（默认: 50，传 0 为无限制）",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="启用严格精确匹配（禁用小字假名折叠与全半角归一化，且区分大小写）",
    )
    parser.add_argument(
        "-r", "--regex",
        action="store_true",
        help="将 query 视为正则表达式",
    )
    parser.add_argument(
        "--no-pair",
        action="store_true",
        help="禁用中日配对行自动联动展示",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["text", "markdown", "md", "json", "tsv"],
        default="text",
        help="输出格式：text (易读终端格式) / markdown / json / tsv（默认: text）",
    )
    parser.add_argument(
        "-o", "--out",
        default=None,
        help="输出到目标文件，默认打印到控制台 (stdout)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.query:
        parser.print_help()
        return 1

    corpus = BilingualCorpus()
    matches = search_corpus(
        corpus=corpus,
        query=args.query,
        work_filter=args.work,
        side=args.side,
        exact=args.exact,
        is_regex=args.regex,
        max_matches=args.max_matches,
        context_lines=args.context,
        enable_pair=not args.no_pair,
    )

    formatted_output = format_search_results(
        matches=matches,
        output_format=args.format,
        query=args.query,
    )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(formatted_output, encoding="utf-8")
        print(f"检索完成，找到 {len(matches)} 处匹配，已保存至: {out_path}")
    else:
        print(formatted_output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
