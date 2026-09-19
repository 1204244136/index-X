#!/usr/bin/env python3
"""轻量级中日 XHTML 逐行对比与对齐诊断工具（纯 CPU，零外部依赖）。

适用场景：
    - 当 check_alignment.py 报错提示中日文件行数不一致时，快速排查具体在第几行发生漂移
    - 快速定位中日两侧漏掉的场景分隔空行、多余的段落合并/拆分、插图位置错位
    - 生成可交互的左右双栏 HTML 对比页面或终端彩色比对报告
    - 按作品分批做深度检查（--work），避免一次性跑全库

用法：
    # 方式 1：直接传表头（自动在 .cache/epub-work 下定位中日配对文件）
    python tools/diff_paired_lines.py S1_01-02

    # 方式 2：传入两个具体文件路径
    python tools/diff_paired_lines.py path/to/jp.xhtml path/to/cn.xhtml

    # 输出为单文件交互式 HTML
    python tools/diff_paired_lines.py S1_01-02 --html diff_S1_01-02.html

    # 仅查看发生漂移/差异的行区间（上下文 2 行）
    python tools/diff_paired_lines.py S1_01-02 --only-diff

    # 批量：全部配对单元，或只查指定作品（可重复，支持 * 通配）
    python tools/diff_paired_lines.py
    python tools/diff_paired_lines.py --work "S1_*" --work "S2_01"

输出分两类，口径不同：
    - 结构锚点冲突（问题列）：行号对齐下逐行比较图片/h1/h2/独立 <br/> 槽位，
      是仓库契约里的硬约束，属真问题。
    - 译文 DRIFT（译文DRIFT数列）：启发式相似度低的**导航信号**，不是错误判定。
      跨语言比较字符重合率与长度，无法判断译文对错（专名音译、正常扩写都会
      命中），需回原文人工判断。
"""

from __future__ import annotations

import argparse
import fnmatch
import html
import re
import sys
from pathlib import Path
from typing import NamedTuple

try:
    from tools.alignment_rules import (
        MANUAL_ALIGNMENT_HEADERS,
        NON_PAIR_WORK_IDS,
        PAIR_RULES,
        TEXTUAL_IMAGE_HEADERS,
        pairing_header_of,
    )
    from tools.epub_ids import book_id, japanese_book_id
except ImportError:
    try:
        from alignment_rules import (
            MANUAL_ALIGNMENT_HEADERS,
            NON_PAIR_WORK_IDS,
            PAIR_RULES,
            TEXTUAL_IMAGE_HEADERS,
            pairing_header_of,
        )
        from epub_ids import book_id, japanese_book_id
    except ImportError:
        MANUAL_ALIGNMENT_HEADERS = frozenset()
        NON_PAIR_WORK_IDS = frozenset()
        PAIR_RULES = {}
        TEXTUAL_IMAGE_HEADERS = frozenset()

        def pairing_header_of(name: str) -> str | None:
            m = re.match(r"^(S\d+_\d+-\d+|S5_\d+_\d+-\d+|S6_\d{2}\.\d{2}\.\d{2}-\d+)", name)
            return m.group(1) if m else None

        def book_id(name: str) -> str | None:
            m = re.search(r"\[([^\]]+)\]", name)
            return m.group(1).upper() if m else None

        def japanese_book_id(chinese_id: str) -> str:
            return chinese_id.upper()

# ---------------------------------------------------------------------------
# 文本与标签解析
# ---------------------------------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>")
KANJI_CHAR_RE = re.compile(r"[\u4e00-\u9fff0-9A-Za-z]")

# 比较可见文本前必须先整段剥离 <rt> 注音。日文侧把读音放进 <rt>
# （`<ruby>水<rt>みず</rt></ruby>`），中文侧放拼音或英文，两侧注音内容本就不同源；
# 不剥离会把注音字数算进长度，把 `水瓶座`(3 字) 与 `水みず瓶がめ座ざ`(9 字) 判成
# 长度比越界。仓库既有口径一致：check_translation_spec / epub_char_count /
# epub_composition_metrics 都是先剥 <rt> 再统计正文。
RT_RE = re.compile(r"<rt\b[^>]*>.*?</rt\s*>", re.S | re.I)

# 固定行模板的 L1-L3（XML 声明 / DOCTYPE / html+head+body 头部行）不是正文行。
# 两侧 <title> 内容本就不同（日文填书名、中文留空），不排除会让每个文件的 L3
# 恒被判成漂移。按内容形态识别而非按行号，序列比对回退时同样成立。
TEMPLATE_XML_RE = re.compile(r"^\s*<\?xml\b", re.I)
TEMPLATE_DOCTYPE_RE = re.compile(r"^\s*<!DOCTYPE\b", re.I)
TEMPLATE_HTML_RE = re.compile(r"<html\b", re.I)

class LineInfo(NamedTuple):
    raw: str
    text: str
    char_set: set[str]
    length: int
    is_img: bool
    is_h1: bool
    is_h2: bool
    is_br: bool
    is_dialogue: bool
    is_template: bool

def parse_line(raw_line: str) -> LineInfo:
    stripped = raw_line.strip()
    # 内嵌字形（gaiji / height-2em）是**行内**语义标签，不是图片行。仓库契约与
    # check_alignment.img_lines 都把这两类排除在「图片行」之外；若在此计入，
    # 中日两侧任何一处字形还原方式不同（如日文用 <img class="gaiji">、中文直接
    # 写字符）都会被误报成图片槽位错位。实测这类假阳性占结构冲突的绝大多数。
    lowered = stripped.lower()
    is_inline_glyph = "gaiji" in lowered or "height-2em" in lowered
    is_img = bool(re.search(r"<(?:img|svg)\b|data-image-continuation=", stripped, re.I)) and not is_inline_glyph
    is_h1 = bool(re.search(r"<h1\b", stripped, re.I))
    is_h2 = bool(re.search(r"<h2\b", stripped, re.I))
    is_br = bool(re.search(r"^\s*<br\s*/?>\s*$", stripped, re.I)) or stripped == ""
    is_template = bool(
        TEMPLATE_XML_RE.match(stripped)
        or TEMPLATE_DOCTYPE_RE.match(stripped)
        or TEMPLATE_HTML_RE.search(stripped)
    )

    # 剔除 HTML 标签获取可见文本；**先整段剥离 <rt> 注音**再取文本，否则日文读音
    # 会混进可见文本与字符集，让长度比与重合率同时失真（详见 RT_RE 注释）。
    visible_text = TAG_RE.sub("", RT_RE.sub("", stripped)).strip()
    kanji_and_digits = set(KANJI_CHAR_RE.findall(visible_text))
    is_dialogue = visible_text.startswith(("「", "“", '"', "『", "（", "("))

    return LineInfo(
        raw=stripped,
        text=visible_text,
        char_set=kanji_and_digits,
        length=len(visible_text),
        is_img=is_img,
        is_h1=is_h1,
        is_h2=is_h2,
        is_br=is_br,
        is_dialogue=is_dialogue,
        is_template=is_template,
    )

# ---------------------------------------------------------------------------
# 启发式相似度计算
# ---------------------------------------------------------------------------

def compute_similarity(jp: LineInfo, cn: LineInfo) -> float:
    """计算中日单行相似度得分 [-1.0, 1.0]"""
    # 1. 硬结构锚点判定
    if jp.is_img and cn.is_img:
        return 1.0
    if jp.is_h1 and cn.is_h1:
        return 1.0
    if jp.is_h2 and cn.is_h2:
        return 1.0
    if jp.is_br and cn.is_br:
        return 1.0

    # 结构类型严重冲突惩罚
    if any([
        jp.is_img != cn.is_img,
        jp.is_h1 != cn.is_h1,
        jp.is_h2 != cn.is_h2,
        jp.is_br != cn.is_br,
    ]):
        return -0.8

    # 2. 固定行模板区（L1-L3：XML 声明 / DOCTYPE / html+head+body 头部行）。
    #    两侧 <title> 内容本就不同源（日文填书名、中文留空），不排除会让**每个**
    #    文件的 L3 恒判漂移（实测 739 条）。这不是译文差异，按等价处理。
    #    刻意放在结构冲突判定**之后**：篇首插图并在这类头部行的 body 开头，
    #    若一侧缺图，上面的图片锚点仍会正常报冲突，不被本捷径吞掉。
    if jp.is_template and cn.is_template:
        return 1.0

    # 两侧均为空
    if jp.length == 0 and cn.length == 0:
        return 1.0
    if jp.length == 0 or cn.length == 0:
        return -0.5

    # 两侧都没有实义字符（纯标点/省略号/符号行，如「……」对「…………」）。
    # 行号配对已保证它们是同一行，而两侧都无 CJK/字母数字可比，省略号个数差异
    # 属排印差异而非漏译或错位（实测 99 条）；无可比内容时按等价处理。
    if not jp.char_set and not cn.char_set:
        return 1.0

    # 2. 对话状态匹配度
    dialogue_match = 0.2 if (jp.is_dialogue == cn.is_dialogue) else -0.15

    # 3. 汉字、数字、英文字符重合率（Jaccard）
    token_sim = 0.0
    if jp.char_set and cn.char_set:
        intersection = len(jp.char_set & cn.char_set)
        union = len(jp.char_set | cn.char_set)
        token_sim = intersection / union if union > 0 else 0.0

    # 4. 长度差异（剥离 <rt> 后按**绝对字数差**判定，不用纯比例）。
    #    纯比例在短行上会被放大成噪声：`と、`(2 字) → `接着……`(4 字) 比例 2.0，
    #    但只差 2 个字，属正常译法。实测旧口径 0.4~1.25 的命中里 51.6% 是
    #    日文不足 10 字的短行，全是假阳性。改为「绝对差 > max(8, 0.6×日文字数)」：
    #    短行给 8 字绝对宽容度，长行按 60% 相对宽容度，命中率 0.70%→0.57% 且
    #    短行占比 51.6%→13.5%，同时长行的大段合并/拆分（差 100+ 字）更醒目。
    diff = abs(cn.length - jp.length)
    len_penalty = 0.0 if diff <= max(8.0, 0.6 * jp.length) else -0.2

    # 比例只用于下面的**软**加分（越接近 0.8 越像同一句），不再作为越界判据。
    ratio = cn.length / max(jp.length, 1)
    score = dialogue_match + (0.5 * token_sim) + (0.3 * (1.0 - min(abs(ratio - 0.8), 1.0))) + len_penalty
    return max(min(score, 1.0), -1.0)

# ---------------------------------------------------------------------------
# 全局对齐算法（Needleman-Wunsch）
# ---------------------------------------------------------------------------

class AlignedPair(NamedTuple):
    jp_idx: int | None
    cn_idx: int | None
    jp: LineInfo | None
    cn: LineInfo | None
    status: str  # "MATCH", "DRIFT", "EXTRA_JP", "EXTRA_CN"
    score: float

def align_lines(jp_lines: list[LineInfo], cn_lines: list[LineInfo]) -> list[AlignedPair]:
    """对齐中日两侧的行。

    仓库契约（AGENTS.md「中日正文行结构」）保证配对文件两侧总行数一致，行号即
    配对身份。因此**行数相等时直接按行号 1:1 对齐**，不再跑序列比对：

    - 正确性：Needleman-Wunsch 在行数相等时仍可能用「一个 gap + 一处错位匹配」
      换到更高总分，于是凭空造出成对的 EXTRA_JP/EXTRA_CN。实测 747 个配对文件里
      59 个文件出现这种假 gap（共 105 对），全部是比对算法自身的产物，不是文件
      问题——行号对齐下它们本应是 MATCH/DRIFT。
    - 性能：DP 是 O(n×m)，单文件上万行时既慢又吃内存；按行号对齐是 O(n)。

    只有两侧行数确实不等时（真实结构差异）才回退到序列比对，此时 gap 才有意义。
    """
    if len(jp_lines) == len(cn_lines):
        return [
            AlignedPair(
                i,
                i,
                jp,
                cn,
                "MATCH" if (sim := compute_similarity(jp, cn)) >= 0.15 else "DRIFT",
                sim,
            )
            for i, (jp, cn) in enumerate(zip(jp_lines, cn_lines), 1)
        ]
    return _align_lines_nw(jp_lines, cn_lines)


def _align_lines_nw(jp_lines: list[LineInfo], cn_lines: list[LineInfo]) -> list[AlignedPair]:
    """行数不等时的全局序列比对（Needleman-Wunsch），用于定位插入/缺失。"""
    n, m = len(jp_lines), len(cn_lines)
    gap_penalty = -0.35

    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    backtrack = [[0] * (m + 1) for _ in range(n + 1)]  # 1: 匹配, 2: 日文Gap, 3: 中文Gap

    for i in range(1, n + 1):
        dp[i][0] = i * gap_penalty
        backtrack[i][0] = 3
    for j in range(1, m + 1):
        dp[0][j] = j * gap_penalty
        backtrack[0][j] = 2

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sim = compute_similarity(jp_lines[i - 1], cn_lines[j - 1])
            match_score = dp[i - 1][j - 1] + sim
            cn_gap = dp[i - 1][j] + gap_penalty
            jp_gap = dp[i][j - 1] + gap_penalty

            best = max(match_score, cn_gap, jp_gap)
            dp[i][j] = best
            if best == match_score:
                backtrack[i][j] = 1
            elif best == cn_gap:
                backtrack[i][j] = 3
            else:
                backtrack[i][j] = 2

    # 回溯
    i, j = n, m
    pairs: list[AlignedPair] = []
    while i > 0 or j > 0:
        op = backtrack[i][j]
        if op == 1 or (i > 0 and j > 0 and op == 0):
            sim = compute_similarity(jp_lines[i - 1], cn_lines[j - 1])
            status = "MATCH" if sim >= 0.15 else "DRIFT"
            pairs.append(AlignedPair(i, j, jp_lines[i - 1], cn_lines[j - 1], status, sim))
            i -= 1
            j -= 1
        elif op == 3 or j == 0:
            pairs.append(AlignedPair(i, None, jp_lines[i - 1], None, "EXTRA_JP", gap_penalty))
            i -= 1
        else:
            pairs.append(AlignedPair(None, j, None, cn_lines[j - 1], "EXTRA_CN", gap_penalty))
            j -= 1

    pairs.reverse()
    return pairs

# ---------------------------------------------------------------------------
# 结果输出与呈现
# ---------------------------------------------------------------------------

def render_cli(pairs: list[AlignedPair], only_diff: bool = False, max_display: int = 100) -> None:
    diff_count = sum(1 for p in pairs if p.status != "MATCH")
    print(f"\n{'='*95}")
    print(f"中日逐行对齐诊断报告 | JP行数: {sum(1 for p in pairs if p.jp)} | CN行数: {sum(1 for p in pairs if p.cn)} | 差异/漂移: {diff_count}")
    print(f"{'='*95}\n")

    show_mask = [True] * len(pairs)
    if only_diff:
        show_mask = [False] * len(pairs)
        for idx, p in enumerate(pairs):
            if p.status != "MATCH":
                for k in range(max(0, idx - 2), min(len(pairs), idx + 3)):
                    show_mask[k] = True

    displayed = 0
    for idx, p in enumerate(pairs):
        if not show_mask[idx]:
            continue

        jp_no = f"L{p.jp_idx:04d}" if p.jp_idx else "     "
        cn_no = f"L{p.cn_idx:04d}" if p.cn_idx else "     "

        jp_text = (p.jp.text if p.jp and p.jp.text else (p.jp.raw if p.jp else ""))[:35]
        cn_text = (p.cn.text if p.cn and p.cn.text else (p.cn.raw if p.cn else ""))[:35]

        status_flag = {
            "MATCH": "  ",
            "DRIFT": "!? ",
            "EXTRA_JP": "+J ",
            "EXTRA_CN": "+C ",
        }.get(p.status, "  ")

        print(f"{status_flag}{jp_no} | {jp_text:<37} || {cn_no} | {cn_text}")
        displayed += 1
        if not only_diff and displayed >= max_display:
            remaining = len(pairs) - displayed
            if remaining > 0:
                print(f"\n... (已省略剩余 {remaining} 行，可使用 --only-diff 仅看差异，或使用 --html 导出完整视图)")
            break

def render_html(pairs: list[AlignedPair], output_path: Path, title: str) -> None:
    html_lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)} - 中日对齐对比</title>",
        "<style>",
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 20px; background: #f8f9fa; color: #212529; }",
        "table { width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }",
        "th, td { padding: 6px 10px; font-size: 13px; border-bottom: 1px solid #e9ecef; vertical-align: top; }",
        "th { background: #e2e8f0; position: sticky; top: 0; text-align: left; }",
        ".num { width: 55px; color: #6c757d; font-family: Consolas, monospace; }",
        ".tag { width: 65px; font-weight: bold; font-size: 11px; text-align: center; border-radius: 3px; }",
        "tr.MATCH:hover { background: #f1f3f5; }",
        "tr.DRIFT { background: #fff3cd; }",
        "tr.EXTRA_JP { background: #ffe3e3; }",
        "tr.EXTRA_CN { background: #d3f9d8; }",
        ".status-MATCH { color: #868e96; }",
        ".status-DRIFT { background: #ffe066; color: #856404; }",
        ".status-EXTRA_JP { background: #ff8787; color: #fff; }",
        ".status-EXTRA_CN { background: #69db7c; color: #fff; }",
        ".text-col { width: 45%; word-break: break-word; }",
        "</style></head><body>",
        f"<h2>中日对齐对比报告: {html.escape(title)}</h2>",
        "<table><thead><tr><th>状态</th><th>JP行</th><th class='text-col'>日文原文</th><th>CN行</th><th class='text-col'>中文译文</th></tr></thead><tbody>",
    ]

    for p in pairs:
        jp_no = str(p.jp_idx) if p.jp_idx else "-"
        cn_no = str(p.cn_idx) if p.cn_idx else "-"
        jp_txt = html.escape(p.jp.raw if p.jp else "")
        cn_txt = html.escape(p.cn.raw if p.cn else "")

        html_lines.append(
            f"<tr class='{p.status}'>"
            f"<td class='tag status-{p.status}'>{p.status}</td>"
            f"<td class='num'>{jp_no}</td><td class='text-col'>{jp_txt}</td>"
            f"<td class='num'>{cn_no}</td><td class='text-col'>{cn_txt}</td>"
            f"</tr>"
        )

    html_lines.extend(["</tbody></table></body></html>"])
    output_path.write_text("\n".join(html_lines), encoding="utf-8")
    print(f"[OK] HTML 报告已输出到: {output_path.resolve()}")

# ---------------------------------------------------------------------------
# 主流程与配对定位
# ---------------------------------------------------------------------------

def locate_pair_by_header(header: str, cache_dir: Path) -> tuple[Path, Path]:
    cn_dir = cache_dir / "chinese-text"
    jp_dir = cache_dir / "japanese-text"

    if not cn_dir.exists() or not jp_dir.exists():
        raise FileNotFoundError(f"缓存目录不存在或未解包: {cache_dir}")

    cn_match = None
    jp_match = None

    for p in cn_dir.rglob("*.xhtml"):
        if pairing_header_of(p.name) == header or header in p.name:
            cn_match = p
            break

    for p in jp_dir.rglob("*.xhtml"):
        if pairing_header_of(p.name) == header or header in p.name:
            jp_match = p
            break

    if not cn_match or not jp_match:
        raise FileNotFoundError(f"在缓存区未完整找到表头 [{header}] 的中日配对文件 (CN: {cn_match}, JP: {jp_match})")
    return jp_match, cn_match


# ---------------------------------------------------------------------------
# 批量模式：全部中日配对文件
# ---------------------------------------------------------------------------

def index_by_header(paths: list[Path]) -> tuple[dict[str, Path], set[str]]:
    """按配对表头索引文件；同侧重复表头不自动选择，交由 check_alignment.py 报告。"""
    index: dict[str, Path] = {}
    duplicates: set[str] = set()
    for path in paths:
        header = pairing_header_of(path.name)
        if not header or header in duplicates:
            continue
        if header in index:
            index.pop(header)
            duplicates.add(header)
            continue
        index[header] = path
    return index, duplicates


def has_body(lines: list[LineInfo]) -> bool:
    """是否有正文行（与 check_alignment.has_body 同口径）。

    纯图片页/无正文页不适用固定行模板，两侧行数天然可以不同；不排除的话，
    封面、纯插图页会持续产生「行数不等」噪声。
    """
    body_started = False
    for info in lines:
        if "<body" in info.raw.lower():
            body_started = True
            continue
        if not body_started:
            continue
        if info.is_h1 or info.is_h2:
            continue
        if info.text:
            return True
    return False


def structural_conflicts(pairs: list[AlignedPair]) -> list[tuple[int, AlignedPair]]:
    """行号对齐下**硬结构锚点**冲突：图片/标题/独立 <br/> 槽位不对应。

    这是本工具相对 `check_alignment.py` 的增量价值。`check_alignment.py` 比较的是
    两侧**集合**（h2 行号列表、图片行号列表、<br/> 行号列表），因此两侧各有错位、
    集合却相同的情形它发现不了；这里按行号逐行比较类型，能抓到真正的槽位错位。

    只看结构锚点，不看译文相似度：相似度是启发式的，译文长度/用词差异会持续产生
    噪声，而结构锚点是仓库契约里的硬约束。
    """
    found = []
    for idx, p in enumerate(pairs, 1):
        if p.jp is None or p.cn is None:
            continue
        jp, cn = p.jp, p.cn
        if (jp.is_img != cn.is_img or jp.is_h1 != cn.is_h1
                or jp.is_h2 != cn.is_h2 or jp.is_br != cn.is_br):
            found.append((idx, p))
    return found


def section_order_swap(pairs: list[AlignedPair]) -> bool:
    """是否为已确认的 section-order 例外形状：中日仅「图片行 ↔ h2 行」一处互换。

    与 `check_alignment.order_swap_offset` 同口径：除该处互换外，逐行类型完全一致。
    """
    if len(pairs) < 2:
        return False
    kinds = [
        ("gap" if p.jp is None or p.cn is None else _kind(p.jp))
        for p in pairs
    ]
    cn_kinds = [
        ("gap" if p.jp is None or p.cn is None else _kind(p.cn))
        for p in pairs
    ]
    for i in range(len(kinds) - 1):
        if kinds[i] != "img" or kinds[i + 1] != "h2":
            continue
        if cn_kinds[i] != "h2" or cn_kinds[i + 1] != "img":
            continue
        swapped = list(cn_kinds)
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        if swapped == kinds:
            return True
    return False


def afterword_moved(jp_raw: list[str], cn_raw: list[str]) -> bool:
    """是否为已确认的 afterword-moved 例外形状。

    直接复用 `check_alignment.afterword_offset`，避免两处各写一份判定而漂移；
    该模块不可用时保守返回 False（照常报告差异，不静默吞掉）。
    """
    try:
        from check_alignment import afterword_offset
    except ImportError:
        try:
            from tools.check_alignment import afterword_offset
        except ImportError:
            return False
    return afterword_offset(jp_raw, cn_raw) is not None




def run_batch(cache: Path, only_diff: bool, progress: bool, tsv_path: Path | None,
              works: list[str] | None = None) -> int:
    """遍历缓存区中日配对文件，逐文件报告结构锚点冲突与行数差异。

    works 为作品号 glob 列表（如 ``S1_*``、``S5_01_02``）；给出时只检查命中
    的作品，便于按批次分次深检，避免一次性跑全库。
    """
    cn_root = cache / "chinese-text"
    jp_root = cache / "japanese-text"
    if not cn_root.is_dir() or not jp_root.is_dir():
        raise FileNotFoundError(f"缓存目录不存在或未解包: {cache}")

    cn_books = {book_id(d.name): d for d in cn_root.iterdir() if d.is_dir()}
    jp_books = {book_id(d.name): d for d in jp_root.iterdir() if d.is_dir()}

    # 先收集全部配对单元，才能给出准确的总数与百分比进度
    units: list[tuple[str, str, Path, Path]] = []
    skipped_books: list[str] = []
    for cn_id, cn_dir in sorted(cn_books.items()):
        if cn_id is None or cn_id in NON_PAIR_WORK_IDS:
            continue
        if works and not any(fnmatch.fnmatch(cn_id, pat) for pat in works):
            continue
        jp_dir = jp_books.get(japanese_book_id(cn_id))
        if jp_dir is None:
            skipped_books.append(f"{cn_id}（无日文对应作品）")
            continue
        cn_all = [p for p in cn_dir.rglob("*.xhtml") if p.name.lower() != "nav.xhtml"]
        jp_all = [p for p in jp_dir.rglob("*.xhtml") if p.name.lower() != "nav.xhtml"]
        cn_by, _ = index_by_header(cn_all)
        jp_by, _ = index_by_header(jp_all)
        for h in sorted(set(cn_by) & set(jp_by)):
            if h in MANUAL_ALIGNMENT_HEADERS:
                continue
            units.append((cn_id, h, jp_by[h], cn_by[h]))

    total = len(units)
    print(f"缓存：{cache}")
    if works:
        print(f"作品筛选：{', '.join(works)}")
    print(f"待检查配对单元：{total}（涉及作品 {len({u[0] for u in units})} 个）")
    if skipped_books:
        print(f"跳过无日文对应的作品 {len(skipped_books)} 个：{', '.join(skipped_books)}")
    print("-" * 95)

    rows: list[list[str]] = []
    bad = 0
    for i, (cn_id, header, jp_p, cn_p) in enumerate(units, 1):
        if progress:
            # 实时进度：\r 原地刷新，避免长时间静默
            print(f"\r  [{i}/{total}] {i/total:5.1%}  {cn_id} {header:<24}",
                  end="", flush=True)
        jp_raw = jp_p.read_text(encoding="utf-8", errors="ignore").splitlines()
        cn_raw = cn_p.read_text(encoding="utf-8", errors="ignore").splitlines()
        jl = [parse_line(l) for l in jp_raw]
        cl = [parse_line(l) for l in cn_raw]
        problems: list[str] = []
        notes: list[str] = []
        # 纯图片页/无正文页不适用固定行模板：两侧行数天然可以不同（封面、整页插图）。
        if not has_body(jl) and not has_body(cl):
            pairs = align_lines(jl, cl)
            rows.append([
                cn_id, header, str(jp_p.relative_to(cache)), str(cn_p.relative_to(cache)),
                str(len(jl)), str(len(cl)), "", "0",
            ])
            continue
        # 已确认的文本化图片例外（S2_14 / S5 扉页）：中文侧把整页图片重排为文本行，
        # 行数/h2/图片行本就允许不同，配对检查整体豁免（同 check_alignment 口径）。
        if header in TEXTUAL_IMAGE_HEADERS:
            rows.append([
                cn_id, header, str(jp_p.relative_to(cache)), str(cn_p.relative_to(cache)),
                str(len(jl)), str(len(cl)), "",
                str(sum(1 for p in align_lines(jl, cl) if p.status == "DRIFT")),
            ])
            continue
        if len(jl) != len(cl):
            # afterword-moved 例外：中文侧后记被有意合并到同一合订卷的另一部作品，
            # 日文末尾的「あとがき」整段在中文侧本就不该有（同 check_alignment 口径）。
            if header in PAIR_RULES and PAIR_RULES[header] == "afterword-moved" and afterword_moved(jp_raw, cn_raw):
                notes.append(f"已确认例外：{PAIR_RULES[header]}")
            else:
                problems.append(f"行数不等 JP{len(jl)} vs CN{len(cl)}")
        pairs = align_lines(jl, cl)
        conflicts = structural_conflicts(pairs)
        # section-order 例外：中日仅「图片行 ↔ h2 行」一处互换，属已确认的合法差异。
        if conflicts and header in PAIR_RULES and section_order_swap(pairs):
            notes.append(f"已确认例外：{PAIR_RULES[header]}")
            conflicts = []
        if conflicts:
            kinds = []
            for _, p in conflicts[:5]:
                kinds.append(f"L{p.jp_idx}({_kind(p.jp)}/{_kind(p.cn)})")
            more = f" 等{len(conflicts)}处" if len(conflicts) > 5 else ""
            problems.append("结构锚点冲突 " + "、".join(kinds) + more)
        drift = sum(1 for p in pairs if p.status == "DRIFT")
        if problems:
            bad += 1
            if progress:
                print("\r" + " " * 95 + "\r", end="")
            print(f"[{cn_id}] {header}")
            for prob in problems:
                print(f"    {prob}")
            if only_diff:
                _print_conflicts(pairs, conflicts)
        rows.append([
            cn_id, header,
            str(jp_p.relative_to(cache)), str(cn_p.relative_to(cache)),
            str(len(jl)), str(len(cl)),
            "; ".join(problems),
            str(drift),
            "; ".join(notes),
        ])
    if progress:
        print("\r" + " " * 95 + "\r", end="")

    print("-" * 95)
    print(f"已检查配对单元：{total}；行数/结构问题：{bad}")

    if tsv_path:
        import csv as _csv
        tsv_path.parent.mkdir(parents=True, exist_ok=True)
        with tsv_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = _csv.writer(f, delimiter="\t")
            w.writerow(["书", "表头", "日文文件", "中文文件", "日文行数", "中文行数", "问题", "译文DRIFT数", "备注"])
            w.writerows(rows)
        print(f"报告：{tsv_path}")
    return 1 if bad else 0


def _kind(info: LineInfo | None) -> str:
    if info is None:
        return "gap"
    if info.is_img:
        return "img"
    if info.is_h1:
        return "h1"
    if info.is_h2:
        return "h2"
    if info.is_br:
        return "br"
    return "text"


def _print_conflicts(pairs: list[AlignedPair], conflicts: list[tuple[int, AlignedPair]]) -> None:
    for _, p in conflicts[:5]:
        jp_txt = (p.jp.raw if p.jp else "")[:88]
        cn_txt = (p.cn.raw if p.cn else "")[:88]
        print(f"      JP L{p.jp_idx} [{_kind(p.jp)}] {jp_txt}")
        print(f"      CN L{p.cn_idx} [{_kind(p.cn)}] {cn_txt}")


def main():
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="中日 XHTML 逐行对比与对齐诊断工具")
    parser.add_argument("target", nargs="?", default=None,
                        help="表头编号（如 S1_01-02）或日文文件路径；省略则批量检查全部配对文件")
    parser.add_argument("cn_path", nargs="?", default=None, help="中文文件路径（仅在第一个参数为文件路径时提供）")
    parser.add_argument("--cache", default=".cache/epub-work", help="缓存根目录（默认 .cache/epub-work）")
    parser.add_argument("--html", type=Path, default=None, help="导出 HTML 报告文件路径")
    parser.add_argument("--only-diff", action="store_true", help="仅在控制台显示存在差异/漂移的行及其上下文")
    parser.add_argument("--all", action="store_true", help="在控制台打印所有行，不进行最大行数截断")
    parser.add_argument("--batch", action="store_true", help="批量检查全部中日配对文件（省略 target 时自动启用）")
    parser.add_argument("--no-progress", action="store_true", help="关闭实时进度输出")
    parser.add_argument("--tsv", type=Path, default=None, help="批量模式报告输出路径（TSV）")
    parser.add_argument("--work", action="append", default=None, metavar="GLOB",
                        help="批量模式只检查指定作品号（可重复，支持 * 通配，如 --work 'S1_*'）")
    args = parser.parse_args()

    batch = args.batch or args.target is None
    if batch:
        if args.target is not None:
            parser.error("批量模式不接受表头参数")
        tsv = args.tsv or (Path(args.cache) / "diff-paired-lines.tsv")
        return run_batch(Path(args.cache), args.only_diff, not args.no_progress, tsv,
                         args.work)

    if args.cn_path:
        jp_file = Path(args.target)
        cn_file = Path(args.cn_path)
        title = f"{jp_file.name} vs {cn_file.name}"
    else:
        cache_path = Path(args.cache)
        jp_file, cn_file = locate_pair_by_header(args.target, cache_path)
        title = args.target

    jp_lines = [parse_line(line) for line in jp_file.read_text(encoding="utf-8", errors="ignore").splitlines()]
    cn_lines = [parse_line(line) for line in cn_file.read_text(encoding="utf-8", errors="ignore").splitlines()]

    pairs = align_lines(jp_lines, cn_lines)
    max_disp = len(pairs) if args.all else 60
    render_cli(pairs, only_diff=args.only_diff, max_display=max_disp)

    if args.html:
        render_html(pairs, args.html, title)
    return 0

if __name__ == "__main__":
    sys.exit(main())
