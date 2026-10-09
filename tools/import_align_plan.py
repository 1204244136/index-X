#!/usr/bin/env python3
"""交稿 × 日文工作源 → 结构缺口报告与导入计划骨架（只读预览，不写书）。

新书导入第 2 步。把交稿按 Heading 1 切章，与日文对齐工作源的内容文件一一对应，
再按**日文物理行**逐行比对，输出可直接照抄的缺口窗口与建议改动。对齐口径与
BetweenLines 的跨语言对齐同形（原日文一行 = 一个行单元，中文侧允许 1:2，
绝不允许多段日文并成一行）：

* 关系词表与动作集合取自 `BetweenLines/src/workbenches/translation-compare/align_jp.py`
  （`MOVES = (1,1) (1,2) (2,2) (1,0) (0,1)`，2:2 再拆成两个 1:1）；
* 带状 DP、互最佳锚点与合并罚项同 `row-alignment.js` 的 CPU 路径
  （`findLocalAnchors`／`alignGroupsCore`／`groupScore`）。

唯一差异是**打分**：BetweenLines 的跨语言对齐用多语言向量模型，本工具必须离线、
零依赖，因此改用「汉字重叠 + 长度比」；语义级复核仍由
`check_semantic_alignment.py --betweenlines-dir` 承担，本工具不宣称语义正确。

本工具只回答「这里中日两侧各是什么、差在哪一行」，不替读者裁定该怎么改：
`split`／`merge_prev`／`insert_br_after`／`drop`／`note_to_prev` 的取舍写进计划
文件，由 `import_build_text.py` 执行。计划骨架写显式 `--out`，不写 EPUB。

用法：
    python tools/import_align_plan.py 暗少4翻译.docx --work S4_04 \
        --book-dir "[S4_04]某暗部的少女共栖 4X" --out plan.json --report gaps.txt
    python tools/import_align_plan.py 暗少4翻译.docx --work S4_04 --plan plan.json --check
"""
from __future__ import annotations

import argparse
import collections
import re
from pathlib import Path

from docx_source import chapter_kind, read_docx, split_chapters
from epub_ids import content_sequence
from import_plan import PlanError, apply_ops, load_plan, sha256_file, write_plan
from xhtml_structure import header_index, line_kind

CJK_RE = re.compile(r"[\u3400-\u9fff]")
TAG_RE = re.compile(r"<[^>]+>")
RUBY_RE = re.compile(r"<ruby\b[^>]*>(.*?)<rt\b[^>]*>.*?</rt\s*>\s*</ruby\s*>", re.S | re.I)
NOTE_RE = re.compile(r"【\*?译注[：:].*?】", re.S)

# 与 BetweenLines 跨语言对齐一致：日文一行 = 一个行单元，中文侧最多 2 段
MOVES = ((1, 1), (1, 2), (2, 2), (1, 0), (0, 1))
EMPTY_SCORE = -0.22
MERGE_PENALTY = 0.03
BAND = 24
ANCHOR_RADIUS = 4
ANCHOR_MIN_CHARS = 10
ANCHOR_MIN_SHARED = 8
ANCHOR_MIN_JACCARD = 0.30

CN_NUMERALS = "〇一二三四五六七八九十"


def cn_numeral(value: int) -> str:
    if value <= 0:
        return str(value)
    if value <= 10:
        return CN_NUMERALS[value]
    if value < 20:
        return "十" + CN_NUMERALS[value - 10]
    return CN_NUMERALS[value // 10] + "十" + (CN_NUMERALS[value % 10] if value % 10 else "")


def cn_to_int(text: str) -> int | None:
    """汉字数字（一~九十九）与阿拉伯数字转整数。"""
    text = text.strip()
    if text.isdigit():
        return int(text)
    total, current = 0, 0
    for char in text:
        if char in CN_NUMERALS:
            current = CN_NUMERALS.index(char)
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char in "百千":
            total += (current or 1) * (100 if char == "百" else 1000)
            current = 0
        else:
            return None
    return total + current


# ---------------------------------------------------------------------------
# 章节建议（可为空；空值必须由人工在计划里补）
# ---------------------------------------------------------------------------

def split_title(title: str) -> tuple[str, str | None]:
    parts = re.split(r"[\s\u3000]+", title.strip(), maxsplit=1)
    return parts[0], (parts[1].strip() if len(parts) > 1 and parts[1].strip() else None)


def suggest_chapter(title: str, sequence: int, interlude: int) -> dict:
    """由章标题给出文件后缀与 h1 层建议；识别不了返回空字段。"""
    head, sub = split_title(title)
    base = {"suffix": None, "h1_main": None, "h1_sub": sub, "nav": None}
    if re.match(r"^引子|^プロローグ前|^Before", head):
        return {**base, "suffix": "Before_the_Prologue", "h1_sub": None}
    if re.match(r"^尾声|^エピローグ後", head):
        return {**base, "suffix": "After_the_Epilogue", "h1_sub": None}
    if re.match(r"^序\s*章$|^序$|^プロローグ$", head):
        main = "序　章"
    elif re.match(r"^[终終]\s*章$|^[终終]$|^エピローグ$", head):
        main = "终　章"
    elif re.match(r"^第[〇零一二三四五六七八九十百千0-9０-９]+章$", head):
        main = head
    elif re.match(r"^行[间間]", head):
        numeral = head[1:] or (sub or "")
        value = cn_to_int(numeral) or interlude or sequence
        main = f"行间　{cn_numeral(value)}"
        return {**base, "suffix": f"Between_the_Lines{value}", "h1_main": main,
                "h1_sub": None, "nav": main}
    elif re.match(r"^后记$|^後記$|^あとがき$|^跋$", head):
        return {**base, "suffix": "Afterwords", "h1_main": "后记", "h1_sub": None, "nav": "后记"}
    elif re.match(r"^特典|^番外|^Special", head, re.I):
        return {**base, "suffix": "Special", "h1_main": head, "h1_sub": None, "nav": title.strip()}
    else:
        return base
    suffix = ("Prologue" if main.startswith("序") else
              "Epilogue" if main.startswith("终") else
              f"Chapter{cn_to_int(head[1:-1])}")
    nav = f"{main} {sub}" if sub else main
    return {**base, "suffix": suffix, "h1_main": main, "nav": nav}


# ---------------------------------------------------------------------------
# 两侧行单元
# ---------------------------------------------------------------------------

def jp_content_lines(path: Path) -> list[dict]:
    """日文内容行（跳过 L1–L5 槽位与闭标签行）：{line, kind, text}。"""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    body = next((i for i, line in enumerate(lines) if re.search(r"<body\b", line, re.I)), 2)
    rows: list[dict] = []
    for number, line in enumerate(lines, 1):
        if number <= 5 or number <= body + 1:
            continue
        kind = line_kind(line)
        if kind in ("close", "head"):
            continue
        rows.append({"line": number, "kind": kind, "text": line.strip()})
    return rows


def cn_rows_of_chapter(rows: list[dict]) -> list[dict]:
    """章内清单行；首个小节标题属 L5 槽位，不进入内容序列。"""
    items = [{"idx": r["idx"], "kind": chapter_kind(r), "text": r["text"]} for r in rows]
    if items and items[0]["kind"] == "h2":
        items = items[1:]
    return items


def kind_class(kind: str) -> str:
    """比对口径：中文空段与日文 `<br/>` 是同一类结构行。"""
    return "gap" if kind in ("br", "blank") else kind


def plain_jp(text: str) -> str:
    return TAG_RE.sub("", RUBY_RE.sub(r"\1", text))


def plain_cn(text: str) -> str:
    return NOTE_RE.sub("", TAG_RE.sub("", RUBY_RE.sub(r"\1", text))).strip()


# 行特征缓存：同一轮比对里同一行会被反复打分，特征只算一次
_FEATURES: dict[tuple[str, int], tuple[str, str, frozenset]] = {}


def features(side: str, row: dict) -> tuple[str, frozenset]:
    key = (side, id(row))
    hit = _FEATURES.get(key)
    if hit is not None and hit[0] == row["text"]:
        return hit[1], hit[2]
    text = plain_jp(row["text"]) if side == "jp" else plain_cn(row["text"])
    value = (text, frozenset(CJK_RE.findall(text)))
    _FEATURES[key] = (row["text"], value[0], value[1])
    return value


# ---------------------------------------------------------------------------
# 打分与全局比对（结构同 row-alignment.js 的 CPU 路径）
# ---------------------------------------------------------------------------

def paragraph_score(cn: dict, jp: dict) -> float:
    """跨语言替代打分：汉字重叠 0.72 + 长度比 0.28（对应 `paragraphScore`）。"""
    left_class, right_class = kind_class(cn["kind"]), kind_class(jp["kind"])
    if left_class != right_class:
        # 结构行／独占译注与正文行错配时明显低于两个空档（-0.44），逼 DP 用 1:0／0:1 说清楚
        if {left_class, right_class} <= {"p", "gap", "note-only"}:
            return -0.6
        return -0.9
    if left_class == "h2":
        return 1.0 if plain_cn(cn["text"]) == plain_jp(jp["text"]) else 0.2
    left, left_set = features("cn", cn)
    right, right_set = features("jp", jp)
    if left_class in ("gap", "img"):
        return 0.9
    overlap = len(left_set & right_set) / len(left_set | right_set) if (left_set | right_set) else 0.0
    ratio = min(len(left), len(right)) / max(len(left), len(right)) if max(len(left), len(right)) else 1.0
    return 0.72 * overlap + 0.28 * ratio


def content_overlap(cn: dict, jp: dict) -> tuple[int, float]:
    """只用内容重叠（共享汉字数与 Jaccard），不含长度项。"""
    first, second = features("cn", cn)[1], features("jp", jp)[1]
    shared = len(first & second)
    union = len(first | second)
    return shared, (shared / union if union else 0.0)


def mergeable(jp_rows: list[dict], cn_rows: list[dict]) -> bool:
    """结构行与独占译注行不参与合并组：它们只能是 1:1、1:0 或 0:1。"""
    if len(jp_rows) <= 1 and len(cn_rows) <= 1:
        return True
    return all(kind_class(row["kind"]) not in ("gap", "note-only") for row in jp_rows + cn_rows)


def group_score(jp_rows: list[dict], cn_rows: list[dict]) -> float:
    if not jp_rows or not cn_rows:
        return EMPTY_SCORE
    if len(jp_rows) == 1 and len(cn_rows) == 1:
        return paragraph_score(cn_rows[0], jp_rows[0])
    joined_cn = {"kind": cn_rows[0]["kind"],
                 "text": "\n".join(plain_cn(row["text"]) for row in cn_rows)}
    joined_jp = {"kind": jp_rows[0]["kind"],
                 "text": "\n".join(plain_jp(row["text"]) for row in jp_rows)}
    penalty = MERGE_PENALTY * max(0, len(jp_rows) + len(cn_rows) - 2)
    return paragraph_score(joined_cn, joined_jp) - penalty


def length_of(text: str) -> int:
    return len(text)


def find_anchors(jp: list[dict], cn: list[dict], radius: int = ANCHOR_RADIUS) -> list[tuple[int, int]]:
    """互最佳锚点：短行与非互最佳一律不作锚，避免把漂移固定成假对应。

    锚点判定**只看内容重叠**（共享汉字数与 Jaccard），不吃长度项——跨语言下
    同长但不同内容的行会靠长度项刷到 0.34 以上（BetweenLines 的同语言
    口径可用长度项，本工具的替代打分不可以）。
    """
    anchors: list[tuple[int, int]] = []
    last_i = last_j = -1
    for i, row in enumerate(jp):
        if length_of(features("jp", row)[0]) < ANCHOR_MIN_CHARS:
            continue
        best = None
        for j in range(max(0, i - radius), min(len(cn), i + radius + 1)):
            shared, jaccard = content_overlap(cn[j], row)
            if shared < ANCHOR_MIN_SHARED or jaccard < ANCHOR_MIN_JACCARD:
                continue
            score = jaccard + shared / 100
            if best is None or score > best[1]:
                best = (j, score)
        if best is None:
            continue
        j = best[0]
        if length_of(features("cn", cn[j])[0]) < ANCHOR_MIN_CHARS:
            continue
        back = None
        for i2 in range(max(0, j - radius), min(len(jp), j + radius + 1)):
            shared, jaccard = content_overlap(cn[j], jp[i2])
            if shared < ANCHOR_MIN_SHARED or jaccard < ANCHOR_MIN_JACCARD:
                continue
            score = jaccard + shared / 100
            if back is None or score > back[1]:
                back = (i2, score)
        if back is None or back[0] != i:
            continue
        if i <= last_i or j <= last_j:
            continue
        anchors.append((i, j))
        last_i, last_j = i, j
    return anchors


def align_core(jp: list[dict], cn: list[dict], band: int = BAND) -> list[dict]:
    """带状 DP：只走 MOVES 允许的关系组合（同 alignGroupsCore）。"""
    n, m = len(jp), len(cn)
    negative = -1e9
    dp = [[negative] * (m + 1) for _ in range(n + 1)]
    trace: list[list[tuple | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        expected = round((i / max(1, n)) * m)
        for j in range(max(0, expected - band), min(m, expected + band) + 1):
            if dp[i][j] <= negative / 2:
                continue
            for step_jp, step_cn in MOVES:
                ni, nj = i + step_jp, j + step_cn
                if ni > n or nj > m:
                    continue
                if abs(nj - round((ni / max(1, n)) * m)) > band:
                    continue
                if not mergeable(jp[i:ni], cn[j:nj]):
                    continue
                score = group_score(jp[i:ni], cn[j:nj])
                candidate = dp[i][j] + score
                if candidate > dp[ni][nj]:
                    dp[ni][nj] = candidate
                    trace[ni][nj] = (step_jp, step_cn, score)
    groups: list[dict] = []
    i, j = n, m
    while i > 0 or j > 0:
        step = trace[i][j]
        if step is None:
            if i > 0 and j > 0:
                step = (1, 1, group_score(jp[i - 1:i], cn[j - 1:j]))
            elif i > 0:
                step = (1, 0, group_score(jp[i - 1:i], []))
            else:
                step = (0, 1, group_score([], cn[j - 1:j]))
        step_jp, step_cn, score = step
        groups.append({"jp": jp[i - step_jp:i], "cn": cn[j - step_cn:j],
                       "jp_range": (i - step_jp, i), "cn_range": (j - step_cn, j),
                       "score": round(float(score), 4),
                       "relation": f"{step_jp}:{step_cn}"})
        i, j = i - step_jp, j - step_cn
    groups.reverse()
    return split_reordered_groups(groups)


def split_reordered_groups(groups: list[dict], jp: list[dict] | None = None,
                           cn: list[dict] | None = None) -> list[dict]:
    """2:2 只作为换序暂存组：按逐段相似度配成两个 1:1（同 split_reordered_groups）。"""
    import itertools
    out: list[dict] = []
    for group in groups:
        size = len(group["jp"])
        if size <= 1:
            out.append(group)
            continue
        if len(group["cn"]) != size:
            raise PlanError(f"对齐组 {group['relation']} 无法保证一段日文一行")
        best = max(itertools.permutations(range(size)),
                   key=lambda order: sum(
                       paragraph_score(group["cn"][offset], group["jp"][position])
                       for position, offset in enumerate(order)))
        offsets = sorted(range(size), key=lambda position: best[position])
        for position in offsets:
            cn_at = group["cn_range"][0] + best[position]
            jp_at = group["jp_range"][0] + position
            out.append({
                "jp": [group["jp"][position]], "cn": [group["cn"][best[position]]],
                "jp_range": (jp_at, jp_at + 1), "cn_range": (cn_at, cn_at + 1),
                "score": 0.0, "relation": "1:1",
                "reordered": cn_at != jp_at,
            })
    out.sort(key=lambda group: (group["jp_range"][0], group["cn_range"][0]))
    return out


def align(jp: list[dict], cn: list[dict]) -> list[dict]:
    """锚点切段 + 段内带状 DP（同 alignGroups）。"""
    anchors = find_anchors(jp, cn)
    if not anchors:
        return align_core(jp, cn)
    groups: list[dict] = []
    jp_start = cn_start = 0
    for jp_at, cn_at in anchors:
        if jp_at > jp_start or cn_at > cn_start:
            groups.extend(align_core(jp[jp_start:jp_at], cn[cn_start:cn_at]))
        groups.append({"jp": [jp[jp_at]], "cn": [cn[cn_at]],
                       "jp_range": (jp_at, jp_at + 1), "cn_range": (cn_at, cn_at + 1),
                       "score": 0.0, "relation": "1:1"})
        jp_start, cn_start = jp_at + 1, cn_at + 1
    if jp_start < len(jp) or cn_start < len(cn):
        groups.extend(align_core(jp[jp_start:], cn[cn_start:]))
    return groups


# ---------------------------------------------------------------------------
# 报告：把关系翻成可执行的建议改动
# ---------------------------------------------------------------------------

def propose(group: dict) -> tuple[str, str]:
    """返回 (建议 op, 说明)。日文一行是行单元，中文侧只可能多、不可能少一行。"""
    relation = group["relation"]
    if relation == "1:1":
        return "", "已对应"
    if group.get("reordered"):
        return "（人工）", "顺序与日文相反：须确认是译文换序还是对齐误配"
    jp_kinds = {kind_class(row["kind"]) for row in group["jp"]}
    cn_kinds = {row["kind"] for row in group["cn"]}
    if relation == "1:0":
        if jp_kinds == {"gap"}:
            return "insert_br_after", "日文有独占分隔行，中文侧没有；补在该行之前的正文段之后"
        return "split", "日文此段在中文侧没有独立行：多是被并进相邻段（按语义边界拆回）或漏译"
    if relation == "0:1":
        if cn_kinds == {"note-only"}:
            return "note_to_prev", "独占成段的译注：改挂到上一段末尾（若确认是制作指示则用 drop）"
        if cn_kinds == {"blank"}:
            return "drop", "中文侧多出一个空段（插图前后或章末的排版空段）"
        return "merge_prev", "中文侧多出一行：并入上一段"
    if relation == "1:2":
        return "merge_prev", "中文侧多出一行：并入上一段"
    if relation == "2:2":
        return "split", "日文两段对应中文一段：拆成两段"
    return "（人工）", "关系未覆盖"


def format_jp(row: dict) -> str:
    return f"{row['line']:>5} [{row['kind']:5s}] {plain_jp(row['text'])[:118]}"


def format_cn(row: dict) -> str:
    return f"{row['idx']:>5} [{'blank' if row['kind'] == 'blank' else row['kind']:5s}] {plain_cn(row['text'])[:118]}"


def chapter_report(title: str, jp_file: str, jp: list[dict], cn: list[dict],
                   window: int = 3) -> tuple[list[str], int, int]:
    """返回 (报告行, 非 1:1 关系数, 计划改动后应有行数)。"""
    groups = align(jp, cn)
    relations = collections.Counter(group["relation"] for group in groups)
    lines = [
        f"########## {title}（{jp_file}）  日文 {len(jp)} 行／中文 {len(cn)} 段／差 {len(cn) - len(jp):+d}",
        f"  日文行类型：{kind_tally([row['kind'] for row in jp])}",
        f"  中文行类型：{kind_tally([row['kind'] for row in cn])}",
        "  关系分布：" + "，".join(f"{name} {relations[name]}"
                                  for name in ("1:1", "1:2", "2:1", "2:2", "1:0", "0:1")
                                  if relations[name]),
    ]
    odd = 0
    for position, group in enumerate(groups):
        op, note = propose(group)
        if not op:
            continue
        odd += 1
        lines.append(f"  ---- 关系 {group['relation']}（第 {len(group['jp'])}×{len(group['cn'])} 组）"
                     f"建议 {op}：{note}")
        for row in group["jp"]:
            lines.append(f"       JP {format_jp(row)}")
        for row in group["cn"]:
            lines.append(f"       CN {format_cn(row)}")
        for neighbour in groups[max(0, position - 1):position] + groups[position + 1:position + 2]:
            for row in neighbour["jp"][-window:]:
                lines.append(f"       · 邻近 JP {format_jp(row)}")
            for row in neighbour["cn"][-window:]:
                lines.append(f"       · 邻近 CN {format_cn(row)}")
    return lines, odd, len(jp)


def kind_tally(kinds: list[str]) -> str:
    counter = collections.Counter(kinds)
    return "／".join(f"{name} {counter[name]}" for name in ("p", "br", "blank", "h2", "img")
                     if counter[name])


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def locate_jp_dir(jp_root: Path, work_id: str) -> Path | None:
    from epub_ids import book_id
    for child in sorted(jp_root.iterdir()):
        if child.is_dir() and (book_id(child.name) or "").upper() == work_id.upper():
            return child
    return None


def build(jp_dir: Path, plan: dict, docx: Path, report_path: Path | None):
    paragraphs, _, _, _ = read_docx(docx, collapse_whitespace=False)
    chapters = split_chapters(paragraphs)
    plan_chapters = plan["chapters"]
    if len(chapters) != len(plan_chapters):
        raise PlanError(f"交稿章数 {len(chapters)} 与计划章数 {len(plan_chapters)} 不一致")
    report: list[str] = []
    deltas: list[int] = []
    odd_total = 0
    for meta, chapter in zip(plan_chapters, chapters):
        jp_path = jp_dir / meta["jp_file"]
        if not jp_path.is_file():
            raise PlanError(f"日文文件不存在：{jp_path}")
        jp = jp_content_lines(jp_path)
        cn = cn_rows_of_chapter(chapter["rows"])
        lines, odd, expected = chapter_report(meta["cn_title"], meta["jp_file"], jp, cn)
        odd_total += odd
        product = None
        try:
            product = apply_ops(cn, {"ops": meta.get("ops") or []}, where=meta["cn_title"])
        except PlanError as exc:
            lines.append(f"  [计划改动不成立] {exc}")
        delta = (len(product) if product is not None else len(cn)) - expected
        deltas.append(delta)
        lines.insert(1, f"  计划改动后 {len(product) if product is not None else len(cn)} 行（差 {delta:+d}）")
        report.extend(lines)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    return report, odd_total, deltas


def skeleton(docx: Path, work_id: str, book_dir: str, jp_root: Path, jp_dir: Path) -> dict:
    paragraphs, _, _, _ = read_docx(docx, collapse_whitespace=False)
    chapters = split_chapters(paragraphs)
    index = header_index(jp_dir)
    jp_files = sorted(index.items(), key=lambda item: (content_sequence(item[0]) or 0, item[0]))
    entries = []
    interlude = 0
    for sequence, (chapter, (_, path)) in enumerate(zip(chapters, jp_files), 1):
        title = chapter["title"] or ""
        head, _ = split_title(title)
        if re.match(r"^行[间間]", head):
            interlude += 1
        suggestion = suggest_chapter(title, sequence, interlude)
        suffix = suggestion["suffix"] or ""
        entries.append({
            "cn_title": title,
            "jp_file": path.relative_to(jp_dir).as_posix(),
            "fname": f"{work_id}-{sequence:02d}_{suffix}.xhtml" if suffix else "",
            "h1_main": suggestion["h1_main"],
            "h1_sub": suggestion["h1_sub"],
            "nav": suggestion["nav"],
            "ops": [],
        })
    return {
        "work_id": work_id.upper(),
        "book_dir": book_dir,
        "source_docx": str(docx),
        "source_docx_sha256": sha256_file(docx),
        "jp_root": str(jp_root),
        "jp_dir": jp_dir.name,
        "images_source": "",
        "images": [],
        "chapters": entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="交稿 × 日文工作源 → 缺口报告与导入计划骨架（只读预览）")
    parser.add_argument("docx", type=Path, help="交稿 .docx")
    parser.add_argument("--work", required=True, help="作品号，如 S4_04")
    parser.add_argument("--book-dir", default="", help="中文书目录名，如 [S4_04]某暗部的少女共栖 4X")
    parser.add_argument("--jp-root", type=Path, default=Path(".cache/epub-work/japanese-text"),
                        help="日文只读参考根目录")
    parser.add_argument("--jp-dir", type=Path, default=None, help="日文书目录；缺省按 --work 在 --jp-root 下查找")
    parser.add_argument("--out", type=Path, help="计划骨架输出文件（只写该文件）")
    parser.add_argument("--report", type=Path, help="缺口报告输出文件")
    parser.add_argument("--plan", type=Path, help="已有计划；配合 --check 验证其改动能否对齐")
    parser.add_argument("--check", action="store_true", help="只做门禁：章节对应与缺口是否为 0")
    parser.add_argument("--summary", action="store_true", help="只在终端打印每章差值与关系数")
    args = parser.parse_args(argv)

    if not args.docx.is_file():
        print(f"[阻断] 交稿不存在：{args.docx}")
        return 2
    jp_dir = args.jp_dir
    if jp_dir is None:
        if not args.jp_root.is_dir():
            print(f"[阻断] 日文参考根目录不存在：{args.jp_root}")
            return 2
        jp_dir = locate_jp_dir(args.jp_root, args.work)
    if jp_dir is None or not jp_dir.is_dir():
        print(f"[阻断] 找不到 {args.work} 的日文工作源目录：{args.jp_root}")
        return 2

    try:
        if args.plan:
            plan = load_plan(args.plan)
        else:
            plan = skeleton(args.docx, args.work, args.book_dir, args.jp_root, jp_dir)
        report, odd, deltas = build(jp_dir, plan, args.docx, args.report)
    except PlanError as exc:
        print(f"[阻断] {exc}")
        return 2

    if args.summary:
        for line in report:
            if line.startswith("##########") or line.startswith("  计划改动后") or \
                    line.startswith("  [计划改动不成立]"):
                print(line)
    else:
        print("\n".join(report))

    if not args.plan and args.out and not args.check:
        write_plan(args.out, plan)
        print(f"计划骨架：{args.out}")
        missing = [chapter["cn_title"] for chapter in plan["chapters"] if not chapter["fname"]]
        if missing:
            print(f"[提示] 以下章节未能自动命名，需人工在计划里补 fname：{missing}")

    if args.check:
        aligned = all(delta == 0 for delta in deltas)
        print(f"章节数 {len(plan['chapters'])}；非 1:1 关系 {odd} 处；"
              f"行数{'全部对齐' if aligned else '尚未对齐'}")
        return 0 if aligned and all(chapter.get("fname") for chapter in plan["chapters"]) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
