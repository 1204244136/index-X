#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 git 提交里的译文改动片段化并按重要度分级。只读分析，不改 `EPUB/`、不改缓存正文。

用法：

    python tools/proofread_review.py b7515335 2d44cb26 821c46b9 7a218119
    python tools/proofread_review.py --worktree
    python tools/proofread_review.py b7515335 --path EPUB --out .cache/epub-work/proofread-review

产物（默认 `.cache/epub-work/proofread-review/`）：

- `changes.tsv`  全部片段：`commit / 作品 / 文件 / 行号 / 旧 / 新`
- `semantic.tsv` 语义级片段（已剔除纯标点与虚词改动）
- `groups.txt`   语义级按「最小差异」聚类，重复模式一眼可见

分级口径：

- `punct`    去掉标点/空白后两侧相同 -> 只动了标点排版
- `tiny`     两侧都不超过 2 字 -> 虚词级微调
- `local`    最小差异 <= 12 字 -> 局部替换（术语、用词、数字）
- `rewrite`  最小差异 > 12 字，或增删行数不一致 -> 整句/整段重写

回查原文：`semantic.tsv` / `groups.txt` 只给「旧 => 新」，判定对错要回日文原文。
日文缓存 `S3_01-NN.xhtml` 与中文 `S3_01-NN_*.xhtml` 按内容序 NN 一一对应
（01=序章 / 02=行间一 / 03=第一章 … 11=终章）；文件内部不是逐行对齐，按关键字检索。
需要把日文抽成纯文本时用 `epub_audit.text_of`，本工具不重复实现。

依赖：`epub_ids.work_id`（作品号解析）、`epub_audit.text_of`（XHTML -> 纯文本）。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

from epub_audit import text_of
from epub_ids import work_id

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, ".cache", "epub-work", "proofread-review")

OLD_RE = re.compile(r"\[-(.*?)-\]", re.S)
NEW_RE = re.compile(r"\{\+(.*?)\+\}", re.S)
OCTAL_RE = re.compile(r"\\([0-7]{3})")
# 标点/空白/数字字母：两侧剥离后相同即视为「只改了标点排版」
PUNCT_RE = re.compile(
    r"[\s　。，、！？；：「」『』（）《》〈〉…—～·\"'()\[\]<>0-9a-zA-Z・]+"
)
LONG_DIFF = 12  # 最小差异超过这个字数算整句/整段重写


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
    """XHTML 片段 -> 纯文本。复用 epub_audit.text_of，保持与既有工具同一口径。"""
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

def grade(row: dict) -> str:
    old, new = row["old"], row["new"]
    if core_of(old) == core_of(new):
        return "punct"
    if len(old) <= 2 and len(new) <= 2:
        return "tiny"
    mo, mn = minimal_diff(old, new)
    return "local" if len(mo) <= LONG_DIFF and len(mn) <= LONG_DIFF else "rewrite"


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
                       % (r["commit"], r["file"], r["line"], r["old"][:70], r["new"][:70]))
        out.append("")
    if long_rows:
        out.append("========== 整句/整段重写  count=%d ==========" % len(long_rows))
        for r in long_rows:
            mo, mn = minimal_diff(r["old"], r["new"])
            out.append("%s\t%s\tL%s\t-%s\t+%s"
                       % (r["commit"], r["file"], r["line"], mo, mn))
    return "\n".join(out)


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------

def write_tsv(path: str, header: list[str], rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            cells = [str(r[k]).replace("\t", " ").replace("\n", " ") for k in header]
            f.write("\t".join(cells) + "\n")


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
        r["grade"] = grade(r)

    os.makedirs(args.out, exist_ok=True)
    write_tsv(os.path.join(args.out, "changes.tsv"),
              ["commit", "work", "file", "line", "grade", "old", "new"], rows)
    semantic = [r for r in rows if r["grade"] in ("local", "rewrite")]
    write_tsv(os.path.join(args.out, "semantic.tsv"),
              ["commit", "work", "file", "line", "grade", "old", "new"], semantic)
    with open(os.path.join(args.out, "groups.txt"), "w", encoding="utf-8") as f:
        f.write(render_groups(semantic))

    grades = Counter(r["grade"] for r in rows)
    print("改动片段 %d 条 -> %s" % (len(rows), args.out))
    for k in ("rewrite", "local", "punct", "tiny"):
        print("  %-8s %d" % (k, grades.get(k, 0)))
    print("  明显增补(new-old>=5) %d" % sum(1 for r in rows if len(r["new"]) - len(r["old"]) >= 5))
    print("  明显删减(old-new>=5) %d  <- 误删实义成分的高发区"
          % sum(1 for r in rows if len(r["old"]) - len(r["new"]) >= 5))
    print("按作品：")
    for name, n in Counter(r["work"] for r in rows).most_common():
        print("  %-10s %d" % (name, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
