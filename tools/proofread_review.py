#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 git 提交里的译文改动片段化并按重要度分级。只读分析，不改 `EPUB/`、不改缓存正文。

用法：

    python tools/proofread_review.py b7515335 2d44cb26 821c46b9 7a218119
    python tools/proofread_review.py --worktree
    python tools/proofread_review.py b7515335 --path EPUB --out .cache/epub-work/proofread-review

产物（默认 `.cache/epub-work/proofread-review/`）：

- `changes.tsv`  全部片段：`commit / 作品 / 文件 / 行号 / 级别 / 子类 / 旧 / 新`
- `semantic.tsv` 需要回原文判断的片段（`tiny` / `local` / `rewrite`）
- `spec.tsv`     规范确定性改动（`spec`）：可批量放行，不进 semantic
- `groups.txt`   语义级按「最小差异」聚类，样例只给差异上下文

分级口径：

- `spec`     改动由 `docs/translation-spec.md` 的规范条款决定，回原文也只会得到同一结论：
             `punct`（只动标点/空白）、`quote`（引号体例）、`glyph`（数字/字母全半角）、
             `erhua`（去儿化音）、`particle`（规范示例语气词）。**复核时不需要逐条回原文**。
- `tiny`     最小差异 <= 2 字 -> 虚词级微调（仍需回原文，但一眼能看完）
- `local`    最小差异 <= 12 字 -> 局部替换（术语、用词、数字）
- `rewrite`  最小差异 > 12 字，或某处整段增删（两侧片段数不等）-> 整句/整段重写

「规范级」这一层是本工具的关键前提：**校对产出物本身遵循规范**，所以旧文本的不规范写法
（弯引号、半角标点、儿化音、非规范语气词）被改写成规范写法是规范化的必然结果，不是语义改动。
把它们混进 `semantic.tsv` 会让真正需要人工判断的改动被淹没。归类判据只认规范里能确定性判定的
形状（见 `spec_kind`），拿不准一律留给 `local` / `rewrite`，不做宽松猜测。

回查原文：`semantic.tsv` / `groups.txt` 只给「旧 => 新」，判定对错要回日文原文。
日文缓存 `S3_01-NN.xhtml` 与中文 `S3_01-NN_*.xhtml` 按内容序 NN 一一对应
（01=序章 / 02=行间一 / 03=第一章 … 11=终章）；文件内部不是逐行对齐，按关键字检索。
需要把日文抽成纯文本时用 `xhtml_text.text_of`，本工具不重复实现。

依赖：`epub_ids.work_id`（作品号解析）、`xhtml_text.text_of`（XHTML -> 纯文本）。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

from xhtml_text import text_of
from epub_ids import work_id

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, ".cache", "epub-work", "proofread-review")

OLD_RE = re.compile(r"\[-(.*?)-\]", re.S)
NEW_RE = re.compile(r"\{\+(.*?)\+\}", re.S)
OCTAL_RE = re.compile(r"\\([0-7]{3})")

# 标点/空白：两侧剥离后相同即视为「只改了标点排版」。
# 覆盖全角与半角标点、各类引号、破折号/波浪号/省略号/间隔号变体——
# 旧版只列了全角标点，半角标点与弯引号会漏判成 local（规范要求它们必须被改写，属于噪音）。
# **数字与字母不是标点**：旧版把它们也剥掉，会让「删掉/改掉数字」被静默判成 punct 放行，
# 而数字恰恰是事实性纠错的高发区。全半角写法差异另由 `glyph` 子类处理（见 spec_kind）。
PUNCT_RE = re.compile(
    r"[\s　"                    # 空白（含全角空格）
    r"!-/:-@\[-`{-~"            # ASCII 标点全体
    r"。，、！？；：「」『』（）〔〕【】〖〗〈〉《》"
    r"…⋯—–―−〜～·・‧•“”‘’〝〟﹁﹂‹›«»"
    r"]+"
)
# 全角 ASCII（数字、字母与标点）折成半角，用于识别「只差全半角写法」。
# 键必须是码位（int）——`str.translate` 传 dict 时按码位查表，用字符做键会静默不替换。
FULLWIDTH_FOLD = {c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}
# 引号体例归一：把不同体例映射到同一对引号，用于识别「只换了引号」
QUOTE_FOLD = str.maketrans({"『": "「", "』": "」", "“": "「", "”": "」",
                            "‘": "『", "’": "』", "﹁": "「", "﹂": "」"})
# 规范示例语气词的确定性替换（`docs/translation-spec.md` 一.7）。
# 只收规范里点名、且替换方向唯一的条目；拟声词类的自由统一不在此列，留给 local 由人工判断。
SPEC_PARTICLES = frozenset({
    ("切", "啧"),        # チッ -> 啧，而不是「切」
    ("啊啦", ""),        # あら 不译「啊啦」
    ("呀嘞呀嘞", ""),     # やれやれ 不译「呀嘞呀嘞」
})

LONG_DIFF = 12  # 最小差异超过这个字数算整句/整段重写
TINY_DIFF = 2   # 最小差异不超过这个字数才可能算虚词级微调
CLIP_WIDTH = 14  # groups.txt 样例的差异上下文宽度（差异前后各留这么多字）

# 虚词级微调的白名单：**差异两侧的每个字都必须在这里**才算 tiny。
# 单看字数不行——「念动力 -> 念动能力」「第10位 -> 第位」的最小差异都只有 2 字，却是术语与
# 事实改动，降级成 tiny 会让复核者以为可以跳过。清单外一律按 local 处理（宁可多看一眼）。
TINY_WORDS = frozenset(
    "的地得了着过就也而都与和及又还才便却则即乃其之是在把被让给对向从由以为"
    "吗呢吧啊呀哇嘛哦喔嗯哎唉喂诶唔呃唷哟咯喽啦个些了"
)


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def git(repo: str, *args: str) -> str:
    cmd = ["git", "-c", "core.quotePath=false"] + list(args)
    p = subprocess.run(cmd, cwd=repo, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("git %s 失败: %s"
                           % (" ".join(args), p.stderr.decode("utf-8", "replace")))
    return p.stdout.decode("utf-8", "replace")


def unquote_git_path(path: str) -> str:
    """还原 git 对路径的八进制转义（如 \\345\\210\\233）。

    git 按字节转义，还原后是 latin-1 码位串，需要再按 UTF-8 解码才是原字符。
    """
    if "\\" not in path:
        return path
    restored = OCTAL_RE.sub(lambda m: chr(int(m.group(1), 8)), path)
    try:
        return restored.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return restored


def parse_diff_file(line: str) -> str:
    """从 `diff --git` 行取出 b 侧路径。"""
    if ' "b/' in line:  # 路径含空格或非 ASCII 时 git 会加引号
        path = line.split(' "b/', 1)[1]
        path = path[:-1] if path.endswith('"') else path
    else:
        path = line.split(' b/', 1)[-1]
    return unquote_git_path(path)


# --------------------------------------------------------------------------
# 片段化
# --------------------------------------------------------------------------

def to_text(fragment: str) -> str:
    """XHTML 片段 -> 纯文本。复用 xhtml_text.text_of，保持与既有工具同一口径。"""
    return text_of(fragment.encode("utf-8"))


def core_of(text: str) -> str:
    return PUNCT_RE.sub("", text)


def minimal_diff(old: str, new: str) -> tuple[str, str]:
    """剥掉公共前后缀，返回 (旧差异, 新差异)。"""
    i = 0
    while i < min(len(old), len(new)) and old[i] == new[i]:
        i += 1
    j = 0
    while j < min(len(old), len(new)) - i and old[len(old) - 1 - j] == new[len(new) - 1 - j]:
        j += 1
    return old[i:len(old) - j], new[i:len(new) - j]


def clip(text: str, frag: str, width: int = CLIP_WIDTH) -> str:
    """只截取差异点前后的上下文。

    样例里给整片段前 70 字等于把差异埋进长句里：复核者要逐字比对才能看出改了什么。
    这里定位最小差异在片段中的位置，只保留差异前后各 width 字。
    """
    if not text:
        return ""
    i = text.find(frag) if frag else -1
    if i < 0:  # 差异片段不在文本里（多段合并行）时退回截断
        return text[:width * 2] + ("…" if len(text) > width * 2 else "")
    s = max(0, i - width)
    e = min(len(text), i + len(frag) + width)
    return ("…" if s > 0 else "") + text[s:e] + ("…" if e < len(text) else "")


def parse_word_diff(text: str, label: str) -> list[dict]:
    """解析 `git diff -U0 --word-diff=plain` 输出。

    每个 hunk 内 `[-x-]` 与 `{+y+}` 数量相同时逐条配对；数量不同说明有整段增删，
    整段合并为一条，避免错位配对。
    """
    rows: list[dict] = []
    cur_file, cur_line = "?", "?"
    olds: list[str] = []
    news: list[str] = []

    def flush() -> None:
        if not olds and not news:
            return
        o_list = [to_text(x) for x in olds]
        n_list = [to_text(x) for x in news]
        pairs = (list(zip(o_list, n_list)) if len(o_list) == len(n_list)
                 else [(" ‖ ".join(o_list), " ‖ ".join(n_list))])
        for old, new in pairs:
            if not old and not new:
                continue
            rows.append({"commit": label, "file": cur_file, "line": cur_line,
                         "old": old, "new": new})

    for line in text.split("\n"):
        if line.startswith("diff --git"):
            flush()
            olds, news = [], []
            cur_file = os.path.basename(parse_diff_file(line))
        elif line.startswith("@@"):
            flush()
            olds, news = [], []
            m = re.match(r"@@ -(\d+)", line)
            cur_line = m.group(1) if m else "?"
        elif line.startswith(("---", "+++", "index ")):
            continue
        else:
            olds.extend(OLD_RE.findall(line))
            news.extend(NEW_RE.findall(line))
    flush()
    return rows


def collect(repo: str, commits: list[str], path: str, worktree: bool) -> list[dict]:
    rows: list[dict] = []
    targets = ["worktree"] if worktree else commits
    for c in targets:
        if worktree:
            args = ["diff", "-U0", "--no-color", "--word-diff=plain"]
            label = "worktree"
        else:
            args = ["diff", "-U0", "--no-color", "--word-diff=plain", "%s~1" % c, c]
            label = c[:8]
        if path:
            args += ["--", path]
        rows.extend(parse_word_diff(git(repo, *args), label))
    return rows


# --------------------------------------------------------------------------
# 分级
# --------------------------------------------------------------------------

def spec_kind(old: str, new: str) -> str:
    """规范确定性改动的子类；不属于规范级时返回空串。

    判据只认能确定性判定的形状，且要求**最小差异整体**落在规范条款内：
    只要差异里还掺着语义成分（改词、增删实义、改写句式），就交给 local / rewrite 由人工判断。
    """
    # 剥掉标点/空白后相同 -> 只动了标点排版
    if core_of(old) == core_of(new):
        # 差异只在引号体例（「」/『』/弯引号互相转写）时单列，便于按条款核对
        return "quote" if old.translate(QUOTE_FOLD) == new.translate(QUOTE_FOLD) else "punct"
    # 折成全半角后相同 -> 只差了全角/半角写法（数字、字母、标点）
    if core_of(old.translate(FULLWIDTH_FOLD)) == core_of(new.translate(FULLWIDTH_FOLD)):
        return "glyph"
    mo, mn = minimal_diff(old, new)
    # 去儿化音：差异就是删掉一个「儿」（规范要求正文不出现儿化音）
    if core_of(mo) == "儿" and not core_of(mn):
        return "erhua"
    if (mo, mn) in SPEC_PARTICLES:
        return "particle"
    return ""


def is_tiny_change(mo: str, mn: str) -> bool:
    """虚词级微调：差异不超过 TINY_DIFF 字，且两侧差异全是虚词/语气词字。"""
    if max(len(mo), len(mn)) > TINY_DIFF:
        return False
    return all(c in TINY_WORDS for c in mo + mn)


def grade(row: dict) -> tuple[str, str]:
    """返回 (级别, 规范子类)。规范级优先于幅度分级。"""
    old, new = row["old"], row["new"]
    kind = spec_kind(old, new)
    if kind:
        return "spec", kind
    mo, mn = minimal_diff(old, new)
    if is_tiny_change(mo, mn):
        return "tiny", ""
    return ("local", "") if len(mo) <= LONG_DIFF and len(mn) <= LONG_DIFF else ("rewrite", "")


def render_groups(rows: list[dict]) -> str:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    long_rows: list[dict] = []
    for r in rows:
        mo, mn = minimal_diff(r["old"], r["new"])
        if len(mo) <= LONG_DIFF and len(mn) <= LONG_DIFF:
            groups[(mo, mn)].append(r)
        else:
            long_rows.append(r)

    out = []
    for (mo, mn), vs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        out.append("### [%s] -> [%s]   count=%d" % (mo, mn, len(vs)))
        for r in vs[:3]:
            out.append("    %s %s L%s | %s => %s"
                       % (r["commit"], r["file"], r["line"],
                          clip(r["old"], mo), clip(r["new"], mn)))
        out.append("")
    if long_rows:
        out.append("========== 整句/整段重写  count=%d ==========" % len(long_rows))
        for r in long_rows:
            mo, mn = minimal_diff(r["old"], r["new"])
            out.append("%s\t%s\tL%s\t-%s\t+%s"
                       % (r["commit"], r["file"], r["line"],
                          clip(r["old"], mo), clip(r["new"], mn)))
    return "\n".join(out)


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------

COLUMNS = ["commit", "work", "file", "line", "grade", "kind", "old", "new"]


def write_tsv(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            cells = [str(r[k]).replace("\t", " ").replace("\n", " ") for k in COLUMNS]
            f.write("\t".join(cells) + "\n")


def summarize(rows: list[dict], out_dir: str) -> None:
    grades = Counter(r["grade"] for r in rows)
    kinds = Counter(r["kind"] for r in rows if r["grade"] == "spec")
    # 增删统计看**净长度变化**（整片段），并把规范级排除在外：
    # 规范级改动（去儿化音、标点宽度）本来就会带来 1-2 字长度变化，算进实义增删是噪音。
    semantic = [r for r in rows if r["grade"] != "spec"]
    grown = [r for r in semantic if len(r["new"]) - len(r["old"]) >= 5]
    shrunk = [r for r in semantic if len(r["old"]) - len(r["new"]) >= 5]
    print("改动片段 %d 条 -> %s" % (len(rows), out_dir))
    for k in ("rewrite", "local", "tiny", "spec"):
        print("  %-8s %d" % (k, grades.get(k, 0)))
    if kinds:
        print("    规范级明细 %s" % " ".join("%s=%d" % (k, n) for k, n in kinds.most_common()))
    print("  明显增补(new-old>=5) %d" % len(grown))
    print("  明显删减(old-new>=5) %d  <- 误删实义成分的高发区" % len(shrunk))
    print("  需要回原文的片段 %d（semantic.tsv）" % len(semantic))
    print("按作品：")
    for name, n in Counter(r["work"] for r in rows).most_common():
        print("  %-10s %d" % (name, n))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="把 git 提交里的译文改动片段化并按重要度分级（只读）")
    p.add_argument("commits", nargs="*", help="提交号；用 --worktree 时省略")
    p.add_argument("--worktree", action="store_true", help="分析未提交的工作区改动")
    p.add_argument("--path", default="EPUB", help="限制 diff 路径（默认 EPUB）")
    p.add_argument("--repo", default=REPO_ROOT, help="仓库根目录")
    p.add_argument("--out", default=DEFAULT_OUT_DIR, help="产物输出目录")
    args = p.parse_args(argv)

    if not args.worktree and not args.commits:
        p.error("至少给出一个提交号，或使用 --worktree")

    rows = collect(args.repo, args.commits, args.path, args.worktree)
    for r in rows:
        r["work"] = work_id(r["file"]) or "-"
        r["grade"], r["kind"] = grade(r)

    os.makedirs(args.out, exist_ok=True)
    write_tsv(os.path.join(args.out, "changes.tsv"), rows)
    write_tsv(os.path.join(args.out, "semantic.tsv"),
              [r for r in rows if r["grade"] in ("tiny", "local", "rewrite")])
    write_tsv(os.path.join(args.out, "spec.tsv"),
              [r for r in rows if r["grade"] == "spec"])
    with open(os.path.join(args.out, "groups.txt"), "w", encoding="utf-8") as f:
        f.write(render_groups([r for r in rows if r["grade"] in ("tiny", "local", "rewrite")]))

    summarize(rows, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
