#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EPUB/ 中文成品的字符级规范化（`docs/translation-spec.md` 的可机械执行子集）。

只做字符替换，不碰结构：不改行数、不改模板、不改文件名、不动 OPF/NCX/nav 引用
与图片资源。所有规则都不增删物理行，因此不改变中日行数对齐。

规则准入门槛（「宁愿不改，也不乱改」）三条同时满足才纳入：
  1. 替换值唯一确定，不需要判断语境或断句；
  2. 1:1 或缩短的字符替换，不插入新字符、不改变行结构；
  3. 全库全量命中已逐条人工核对，无一处例外。

反过来，遇到本工具没有把握的结构（跨行注释、CDATA、额外行分隔符）时按 fail-safe
拒绝处理该文件并报告，不猜测、不部分替换。

规则表 RULES 是唯一事实来源，每条标注 `translation-spec.md` 条款；改动规范时需
同步本文件与 `tools/check_translation_spec.py` 的检查项。

另有一条行级规则不放进 RULES（它的处理单位是整行内的 `<b>` 段，不是标签外文本）：
  bold-punct    把 `<b>` 段内的标点移到加粗外（一.8「加粗落在标点上」）
判定标准取自日文傍点自身的字符构成，见下方 BOLD_* 常量。所有规则都只做字符
级重写——`bold-punct` 会增删 `<b>` 标签，但绝不增删物理行、不改变可见文字与标点
顺序（移动后去掉标签，纯文本完全一致）。

用法：
    python tools/text_norm.py                          # 只读报告（默认根目录 EPUB/）
    python tools/text_norm.py --apply                  # 写盘
    python tools/text_norm.py --pattern "*S4_*"        # 按书目录名筛选
    python tools/text_norm.py --apply --report r.md --summary s.txt

只写 `EPUB/`；`.cache/` 是只读参考副本，本工具不写入。
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "EPUB"

# 中文/全角语境字符类：表意文字 + 全角标点 + CJK 符号 + 全角空格区
CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef\u3000-\u303f"

# ---------------------------------------------------------------------------
# 规则表：(id, 匹配, 替换, 依据, 显示用说明)
#
# 每条都在全库全量命中上逐条核对过。刻意比 check_translation_spec.py 的 P1–P14
# 窄：只纳入零误报项，其余一律留在检查器里报告、不自动写盘。
# ---------------------------------------------------------------------------
RULES: tuple[tuple[str, re.Pattern[str], str, str, str], ...] = (
    # 问叹顺序：问号始终在感叹号左边。含半角问号变体「！?」。
    ("interrobang", re.compile(r"！[？?]"), "？！", "一.4", "！？ → ？！"),
    # 省略号后不保留句号。(?!…) 排除「……。……」这类两段独立停顿——删掉会改变
    # 节奏，属判断而非替换，交人工。
    ("ellipsis-period", re.compile(r"(…+)。(?!…)"), r"\1", "一.5", "删省略号后的句号"),
    # 同上，半角句点变体。(?!\d) 避开「….5」这类。
    ("ellipsis-ascii-dot", re.compile(r"(…+)\.(?!\d)"), r"\1", "一.5", "删省略号后的半角句点"),
    # U+2500 BOX DRAWINGS LIGHT HORIZONTAL 被误用作破折号，与全书 U+2014 同形异码。
    ("dash-codepoint", re.compile("\u2500"), "\u2014", "一.1", "─ (U+2500) → — (U+2014)"),
    # 中文语境半角逗号全角化。限「中文后、中文或省略号前」，只吞 ASCII 空格；
    # 前导字符必须是中文，故千分位「1,000」天然不匹配。
    ("halfwidth-comma", re.compile(r"([%s]), *(?=[%s…])" % (CJK, CJK)), r"\1，", "一.1",
     "中文后半角逗号 → ，"),
)

# ---------------------------------------------------------------------------
# 明确排除、不要加进来的规则（原因见全库扫描结论）：
#   儿化音              355 处，正则不可能可靠（不一会儿 / 婴儿 / 那儿）
#   NBSP U+00A0         162 处，有意排版（制作信息列对齐、御坂网络电波间隔）
#   半角括号            157 处，多为 (953679671)、(Level 5)，规范允许半角在数字/英文里
#   弯引号 “”‘’          52 处，英文引语 + S0_00 讨论引号本身的元文本
#   半角 ! / ? 单独      39 处，拉丁文咒语与英文句
#   半角句号             17 处，.50/.22/.38 枪械口径，点号在数字前
#   系列名「某魔法的禁书目录」 10 处，全是专名：百度魔法禁书目录吧、中文维基、动画名
#   破折号变体 — / --     7 处，拟声延长（沙沙沙沙沙-----、唔——唔—）
#   全角 ＆％＝＊＋／      300+ 处，体例问题，规范无条文
#   ・ U+30FB             3 处，全在 Note 页，2 处为日文原文引用（规范豁免）
#   ‧ U+2027             1 处，位于标题行内，可能是刻意的视觉分隔
#   !？？ 混合            2 处，刻意双问号，改成 ？！？ 会变语气
#   连续 ASCII 空格       4 处，规范明示「断断续续用空格示意」属规范做法
#   引号不配对            16 文件，补在哪/删哪个需判断，非唯一替换值
# ---------------------------------------------------------------------------

TAG_SPLIT = re.compile(r"(<[^>]*>)")
SKIP_OPEN_RE = re.compile(r"<\s*(rt|style|script)\b", re.I)
SKIP_CLOSE_RE = re.compile(r"<\s*/\s*(rt|style|script)\s*>", re.I)
EXTRA_SEPARATORS = "\u2028\u2029\x0b\x0c\x85"

# ---------------------------------------------------------------------------
# 加粗规则：`<b>` 段内不得含标点（translation-spec 一.8「加粗落在标点上」）。
#
# 判定标准从日文傍点自身的字符构成反推（实测日文 8397 个傍点段）：
#   允许在加粗内 —— 汉字假名、ー(568)、＝(99)、〇 々、全角英数字、％＆♯＃×、
#                    / 及空白；中文侧对应地保留「·」（≈＝）与「～」（≈ー）
#   从不包含     —— ，！：；「」『』）—～・ 及半角 ,.;:?()[] 等
# 故下列字符一旦出现在 `<b>` 段内，即在该处断段、把标点留在加粗外；
# 文字（含中文增译）一律留在加粗内。
# ---------------------------------------------------------------------------
BOLD_DISALLOWED = set("，。、？！：；「」『』（）〔〕【】《》〈〉…—"
                      ",.;:?!()[]{}\u201c\u201d\u2018\u2019")

# 需整体保留、不得当作标点拆开的片段：
#   XML 实体     —— &amp; 的分号若被拆开会得到 `&amp`，XML 直接报废
#   作品号        —— 中文项目的本地化标识，方括号是标识符一部分
#   缩写点/小数字  —— Mr. / A.A.A. / .50，点是内容的一部分
BOLD_KEEP_PATTERNS = (
    re.compile(r"&(?:[a-zA-Z]+|#\d+|#x[0-9a-fA-F]+);"),
    re.compile(r"\[S\d+_[0-9A-Za-z_.]*\]"),
    re.compile(r"[A-Za-z]\."),
    re.compile(r"\d\.|\.\d"),
)
_BOLD_KEEP_ALL = re.compile("|".join(p.pattern for p in BOLD_KEEP_PATTERNS))
B_BLOCK_RE = re.compile(r"<b\b([^>]*)>(.*?)</b\s*>", re.S | re.I)
_BOLD_PLACEHOLDER = "\u0001%d\u0002"

# 报告用：行级规则的标识与展示名（不进 RULES，见模块 docstring）
BOLD_RULE_ID = "bold-punct"
BOLD_RULE_SPEC = "一.8"
BOLD_RULE_DISPLAY = "加粗段内标点移到加粗外"


def split_bold_punct(line: str):
    """把行内 `<b>` 段中的标点移到加粗外，返回 (新行, 命中山列表)。

    标点一到即在该处闭合 `</b>`、写出标点、另起 `<b>`；`<rt>` 注音内容与
    XML 实体、作品号、缩写点整体保留，不参与切分。
    """
    prot: list[str] = []

    def _stash(m):
        prot.append(m.group(0))
        return _BOLD_PLACEHOLDER % (len(prot) - 1)

    work = _BOLD_KEEP_ALL.sub(_stash, line)
    hits: list[tuple[str, str, str]] = []

    def _rebuild(attrs: str, inner: str):
        toks = TAG_SPLIT.split(inner)
        out: list[str] = []
        buf: list[str] = []
        skip: str | None = None
        changed = False

        def flush():
            nonlocal buf
            content = "".join(buf)
            if content:
                out.append("<b%s>%s</b>" % (attrs, content))
            buf = []

        for tok in toks:
            if not tok:
                continue
            if tok.startswith("<"):
                if SKIP_CLOSE_RE.match(tok):
                    skip = None
                elif SKIP_OPEN_RE.match(tok):
                    skip = skip or SKIP_OPEN_RE.match(tok).group(1).casefold()
                buf.append(tok)
                continue
            if skip is not None:
                buf.append(tok)
                continue
            seg = ""
            for ch in tok:
                if ch in BOLD_DISALLOWED:
                    if seg:
                        buf.append(seg)
                        seg = ""
                    flush()
                    out.append(ch)
                    changed = True
                else:
                    seg += ch
            if seg:
                buf.append(seg)
        flush()
        return "".join(out), changed

    def _repl(m):
        new, changed = _rebuild(m.group(1), m.group(2))
        if changed:
            hits.append(("bold-punct", m.group(0), new))
            return new
        return m.group(0)

    work = B_BLOCK_RE.sub(_repl, work)
    for i, s in enumerate(prot):
        work = work.replace(_BOLD_PLACEHOLDER % i, s)
    return work, hits


def _skip_state_after(tag: str, skip: str | None) -> str | None:
    """按标签更新「跳过内容」状态：<rt>/<style>/<script> 的内容不参与替换。"""
    t = tag.strip()
    if SKIP_CLOSE_RE.match(t):
        return None
    m = SKIP_OPEN_RE.match(t)
    if m and not t.endswith("/>"):
        return m.group(1).casefold()
    return skip


def transform_line(line: str, skip: str | None):
    """对一行做标签感知替换，返回 (新行, 命中山列表, 新 skip 状态)。

    只替换标签之外的文本；标签自身（含属性里的 class/href/style）与 <rt> 注音、
    <style>/<script> 块内容一律原样保留——否则会改坏 XML 属性与 CSS。
    """
    out: list[str] = []
    hits: list[tuple[str, str, str]] = []
    for part in TAG_SPLIT.split(line):
        if not part:
            continue
        if part.startswith("<"):
            skip = _skip_state_after(part, skip)
            out.append(part)
            continue
        if skip is not None:
            out.append(part)
            continue
        new = part
        for rid, rx, rep, _spec, _disp in RULES:
            for m in rx.finditer(new):
                s = max(0, m.start() - 24)
                e = min(len(new), m.end() + 24)
                hits.append((rid, m.group(0), new[s:e]))
            if rx.search(new):
                new = rx.sub(rep, new)
        out.append(new)
    return "".join(out), hits, skip


def split_lines(text: str):
    """按 \\n 分割并保留行尾（CRLF/LF/CR）。不用 str.splitlines()：它会把
    U+2028/U+2029/\\x0b/\\x0c/\\x85 也当分隔符，可能破坏 XHTML 结构。"""
    raw = text.split("\n")
    out: list[tuple[str, str]] = []
    for i, body in enumerate(raw):
        eol = "\n" if i < len(raw) - 1 else ""
        if body.endswith("\r"):
            body, eol = body[:-1], "\r" + eol
        out.append((body, eol))
    return out


def unsupported_structure(text: str) -> str | None:
    """fail-safe：遇到没有把握的跨行结构就拒绝处理该文件，不猜测、不部分替换。"""
    if any(ch in text for ch in EXTRA_SEPARATORS):
        return "含额外行分隔符（U+2028/U+2029/\\x0b/\\x0c/\\x85）"
    if "<![CDATA[" in text:
        return "含 CDATA 段"
    for lineno, (body, _eol) in enumerate(split_lines(text), 1):
        if body.count("<!--") != body.count("-->"):
            return "第 %d 行含跨行注释" % lineno
    return None


def process_file(path: Path, apply_changes: bool):
    """处理单个 XHTML。返回 (命中列表, 是否写盘, 拒绝原因)。逐字节保留 BOM 与换行风格。"""
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    if not text:
        return [], False, None
    reason = unsupported_structure(text)
    if reason:
        return [], False, reason

    skip: str | None = None
    out_lines: list[str] = []
    file_hits: list[tuple[int, str, str, str]] = []
    for lineno, (body, eol) in enumerate(split_lines(text), 1):
        new_body, hits, skip = transform_line(body, skip)
        new_body, b_hits = split_bold_punct(new_body)
        for rid, matched, ctx in hits + b_hits:
            file_hits.append((lineno, rid, matched, ctx))
        out_lines.append(new_body + eol)

    new_text = "".join(out_lines)
    written = False
    if apply_changes and new_text != text:
        path.write_bytes((b"\xef\xbb\xbf" if has_bom else b"") + new_text.encode("utf-8"))
        written = True
    return file_hits, written, None


def collect_targets(root: Path, pattern: str | None):
    """产出 (path, 是否为 nav.xhtml)。nav 单独计数，便于核对标题一致性。"""
    if not root.is_dir():
        raise SystemExit("根目录不存在：%s" % root)
    pat = re.compile(pattern.replace("*", ".*")) if pattern else None
    for book in sorted(root.iterdir()):
        if not book.is_dir():
            continue
        if pat and not pat.search(book.name):
            continue
        for p in sorted(book.rglob("*.xhtml")):
            yield p, p.name.lower() == "nav.xhtml"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="EPUB/ 中文成品字符级规范化（translation-spec 可机械执行子集）")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="EPUB 根目录")
    ap.add_argument("--apply", action="store_true", help="写盘（默认只读报告）")
    ap.add_argument("--pattern", default=None, help="按书目录名筛选，如 '*S4_*'")
    ap.add_argument("--report", type=Path, default=None, help="Markdown 报告输出路径")
    ap.add_argument("--summary", type=Path, default=None, help="单行摘要输出路径（供 commit message）")
    ap.add_argument("--top", type=int, default=200, help="报告中每规则最多列出的样例数")
    args = ap.parse_args()

    root = args.root.resolve()
    rule_counts: Counter[str] = Counter()
    rule_files: dict[str, set[str]] = {}
    rule_samples: dict[str, list[str]] = {}
    nav_counts: Counter[str] = Counter()
    line_hits: Counter[str] = Counter()   # 命中所在的 (文件,行) 数，比字符数更贴近「处」
    touched: set[str] = set()
    skipped: list[tuple[str, str]] = []
    written_files = 0
    scanned = 0

    for path, is_nav in collect_targets(root, args.pattern):
        scanned += 1
        hits, written, reason = process_file(path, args.apply)
        rel = str(path.relative_to(root))
        if reason:
            skipped.append((rel, reason))
            continue
        if written:
            written_files += 1
        if not hits:
            continue
        touched.add(rel)
        for lineno, rid, matched, ctx in hits:
            rule_counts[rid] += 1
            rule_files.setdefault(rid, set()).add(rel)
            line_hits["%s|%s|%d" % (rel, rid, lineno)] += 1
            if is_nav:
                nav_counts[rid] += 1
            samples = rule_samples.setdefault(rid, [])
            if len(samples) < args.top:
                samples.append("%s:%d  …%s…" % (rel, lineno, ctx))

    total = sum(rule_counts.values())
    spots = len(line_hits)
    mode = "已写盘" if args.apply else "只读"

    # 报告口径统一到一张表：RULES（标签外文本替换）+ 行级 bold-punct
    report_rules = [(rid, disp, spec) for rid, _rx, _rep, spec, disp in RULES]
    report_rules.append((BOLD_RULE_ID, BOLD_RULE_DISPLAY, BOLD_RULE_SPEC))

    def rule_lines(rid: str) -> int:
        return len([k for k in line_hits if "|%s|" % rid in k])

    print("字符级规范化（%s）：%d 行命中、%d 个字符替换，涉及 %d 个文件（扫描 %d 个 XHTML）"
          % (mode, spots, total, len(touched), scanned))
    if not total:
        print("  无命中。")
    for rid, disp, spec in report_rules:
        n = rule_counts.get(rid, 0)
        if n:
            print("  %-20s 字符 %4d / 行 %3d / 文件 %3d   %s  [%s]"
                  % (rid, n, rule_lines(rid), len(rule_files.get(rid, ())), disp, spec))
    if nav_counts:
        print("  其中 nav.xhtml：%s"
              % ", ".join("%s=%d" % (k, v) for k, v in sorted(nav_counts.items())))
    if args.apply:
        print("  实际写入文件：%d" % written_files)
    if skipped:
        print("  拒绝处理 %d 个文件（fail-safe）：" % len(skipped))
        for rel, reason in skipped[:10]:
            print("    %s — %s" % (rel, reason))

    if args.summary:
        args.summary.write_text(
            "style(epub): 自动规范化 EPUB 文本 %d 处\n" % spots, encoding="utf-8")

    if args.report:
        lines = ["# EPUB 文本字符级规范化报告", "",
                 "- 模式：%s" % mode,
                 "- 根目录：`%s`" % root.name,
                 "- 扫描 XHTML：%d" % scanned,
                 "- 命中：**%d** 行 / %d 个字符替换，涉及 %d 个文件" % (spots, total, len(touched)),
                 "- 写盘文件：%d" % written_files, "",
                 "规则来源：`docs/translation-spec.md`（可机械执行子集）。", "",
                 "| 规则 | 替换 | 依据 | 命中数 | 涉及文件 |", "| --- | --- | --- | --- | --- |"]
        for rid, disp, spec in report_rules:
            lines.append("| `%s` | %s | %s | %d | %d |"
                         % (rid, disp, spec, rule_counts.get(rid, 0),
                            len(rule_files.get(rid, ()))))
        lines.append("")
        for rid, disp, spec in report_rules:
            if not rule_samples.get(rid):
                continue
            lines += ["## `%s` — %s（%d 处）" % (rid, disp, rule_counts[rid]), ""]
            lines += ["- %s" % s for s in rule_samples[rid]]
            lines.append("")
        if skipped:
            lines += ["## 拒绝处理（fail-safe）", ""]
            lines += ["- `%s` — %s" % (rel, reason) for rel, reason in skipped]
            lines.append("")
        if not total:
            lines.append("无命中，未修改任何文件。")
        args.report.write_text("\n".join(lines), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
