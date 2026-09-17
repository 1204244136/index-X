#!/usr/bin/env python3
"""检查中日缓存 XHTML 是否符合统一固定行模板并保持对齐（只读）。

模板（AGENTS.md「中日正文行结构」）：
    1  <?xml …?>
    2  <!DOCTYPE html>
    3  <html …><head>…</head><body…>   ← 可并入篇首图片
    4  <h1>…</h1>                      ← 独占行；无 h1 则空行
    5  <h2>…</h2>                      ← 独占行；无 h2 则空行
    6  <p>正文首行</p>                 ← 永远在第 6 行

检查项：
- 逐文件：L1/L2/L3 头部结构、L4=h1 独占或空、L5=h2 独占或空、L6=正文；
- 正文行原子性：每条物理行只允许一个同级正文块，正文不得与 body/html 闭标签同行；
- 配对文件：总行数一致、h2 位置一致、图片行一致（gaiji/height-2em 字形不计；
  S2_14-02/04/07/10/13 为已确认的文本化图片例外，配对检查整体豁免）；
- 纯图片页/无正文页不适用；仅单侧存在的 EPUB、日文独有包装页不参与检查。

用法：
    python tools/check_alignment.py
    python tools/check_alignment.py --strict
    python tools/check_alignment.py --cache 路径
输出：控制台汇总 + `.cache/epub-work/alignment-check.tsv`
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from alignment_rules import (
    JP_WRAPPER_RE,
    MANUAL_ALIGNMENT_HEADERS,
    NON_PAIR_WORK_IDS,
    PAIR_RULES,
    TEXTUAL_IMAGE_HEADERS,
    pairing_header_of,
    template_exempt,
)
from epub_ids import book_id, content_sequence, is_packaging_header, japanese_book_id

TAG_RE = re.compile(r"<[^>]*>")
H_OPEN_RE = re.compile(r"<(h1|h2)\b", re.I)
BODY_RE = re.compile(r"<body\b", re.I)
IMG_RE = re.compile(r"<(?:img|svg)\b|data-image-continuation=", re.I)
BR_LINE_RE = re.compile(r"^\s*<br\s*/>\s*$", re.I)
LIST_WRAP_RE = re.compile(r"^\s*<(ul|ol)\b[^>]*>\s*$", re.I)
FLOW_SIBLING_RE = re.compile(
    r"(?:</(?:p|h[12]|li|ul|ol|blockquote|table|tr|td)>|"
    r"<(?:br|hr)\b[^>]*?/?>)\s*"
    r"<(?:p|h[12]|li|ul|ol|blockquote|table|tr|td|br|hr)\b",
    re.I,
)
CONTENT_BODY_CLOSE_RE = re.compile(
    r"</(?:p|h[12]|li|ul|ol|blockquote|table|tr|td)>\s*"
    r"(?:</div>\s*)*</body>",
    re.I,
)
HEADING_OPEN_RE = re.compile(r"<(?P<tag>h[12])\b[^>]*>", re.I)
HEADING_CONTENT_RE = re.compile(
    r"<(?P<tag>h[12])\b[^>]*>(?P<inner>.*?)</(?P=tag)>", re.I | re.S
)
HEADING_BR_RE = re.compile(r"<br\s*/?>", re.I)
HEADING_BLOCK_WRAP_RE = re.compile(r"<(?:div|p)\b", re.I)

def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def has_body(lines: list[str]) -> bool:
    head_end = next(
        (i for i, line in enumerate(lines, 1) if BODY_RE.search(line)), 0
    )
    return any(
        TAG_RE.sub("", line).strip()
        for i, line in enumerate(lines, 1)
        if i > head_end and not H_OPEN_RE.search(line)
    )


def check_file(lines: list[str], allow_list_wrap_slot: bool = False) -> list[str]:
    """模板逐文件检查，返回问题列表。

    allow_list_wrap_slot=True 时允许第 5 行用 <ul>/<ol> 列表包装占位（中文 Note 等包装页）。
    """
    errs: list[str] = []
    if not has_body(lines):
        return errs  # 纯图片页/无正文页：不适用
    if len(lines) < 6:
        errs.append("行数<6")
        return errs
    if "<?xml" not in lines[0]:
        errs.append("L1 非 XML 声明")
    if "<!DOCTYPE" not in lines[1]:
        errs.append("L2 非 DOCTYPE")
    if "<html" not in lines[2] or "<body" not in lines[2]:
        errs.append("L3 非头部合并行")
    l4, l5, l6 = lines[3], lines[4], lines[5]
    if l4.strip():
        if not re.match(r"^\s*<h1\b", l4) or not re.search(r"</h1>\s*$", l4):
            errs.append("L4 非 h1 独占行")
        if re.search(r"<(?:img|svg)\b", l4, re.I) and "gaiji" not in l4.lower():
            errs.append("L4 含图片")
    if l5.strip():
        is_h2 = re.match(r"^\s*<h2\b", l5) and re.search(r"</h2>\s*$", l5)
        is_list_wrap = allow_list_wrap_slot and bool(LIST_WRAP_RE.match(l5))
        if not is_h2 and not is_list_wrap:
            errs.append("L5 非 h2/列表包装独占行")
    if not l6.strip():
        errs.append("L6 为空")
    for idx, line in ((4, l4), (5, l5)):
        if line.strip() and not re.match(r"^\s*<h[12]\b", line):
            if idx == 5 and allow_list_wrap_slot and LIST_WRAP_RE.match(line):
                continue
            errs.append(f"L{idx} 非标题行却有内容")
    for lineno, line in enumerate(lines[5:], 6):
        if FLOW_SIBLING_RE.search(line):
            errs.append(f"L{lineno} 同一物理行包含多个正文块")
        if CONTENT_BODY_CLOSE_RE.search(line):
            errs.append(f"L{lineno} 正文与 body 闭标签同行")
    for lineno, line in enumerate(lines, 1):
        opening = HEADING_OPEN_RE.search(line)
        if not opening:
            continue
        heading = HEADING_CONTENT_RE.search(line)
        if not heading:
            errs.append(f"L{lineno} h1/h2 未独占一个物理行")
            continue
        if line.strip() != heading.group(0):
            errs.append(f"L{lineno} h1/h2 未独占一个物理行")
        inner = heading.group("inner")
        if HEADING_BR_RE.search(inner):
            errs.append(f"L{lineno} h1/h2 内嵌 <br/>")
        if HEADING_BLOCK_WRAP_RE.search(inner):
            errs.append(f"L{lineno} h1/h2 含 div/p 块级包装")
    return errs


def img_lines(lines: list[str]) -> list[int]:
    return [
        i + 1
        for i, line in enumerate(lines)
        if IMG_RE.search(line)
        and "gaiji" not in line.lower()
        and "height-2em" not in line.lower()
    ]


def h2_lines(lines: list[str]) -> list[int]:
    return [i + 1 for i, line in enumerate(lines) if re.search(r"<h2\b", line)]


def standalone_br_lines(lines: list[str]) -> list[int]:
    return [i + 1 for i, line in enumerate(lines) if BR_LINE_RE.match(line)]


PAIR_RULE_LABELS = {
    "afterword-moved": "中文侧后记移入合订卷内另一部作品（见 alignment_rules.PAIR_RULES）",
    "section-order": "中文侧小节标题在分页边界前、日文快照在后（见 alignment_rules.PAIR_RULES）",
}


def afterword_offset(japanese: list[str], chinese: list[str]) -> int | None:
    """日文末尾的「あとがき」整段（含空行与 `<br/>`）在中文侧本就不存在。

    返回「あとがき」独占行的行号（1 起）；形状不符返回 None。成立条件必须**完全**
    解释掉行数差异，否则不吃这条例外（日文的 `</body></html>` 在页尾，中文的也在
    页尾，所以两边都比到闭合行之前）：
      1. 日文某行独占 `<p>あとがき</p>`，且其后到页尾至少 10 行（整个后记）；
      2. 日文去掉该行及其后全部正文后，**行数与中文侧闭合行之前相等**；
      3. 截断后的 `<br/>` 位置与中文侧一致。

    中文侧的后记被有意合并到同一合订卷的另一部作品里
    （`S5_01_03-Information.xhtml` 明写「（后记在 [S5_01_01]…神裂火织篇X 中）」）。
    """
    def without_closing(lines: list[str]) -> list[str]:
        return lines[:-1] if lines and re.match(r"^\s*</body", lines[-1], re.I) else lines

    cn_head = without_closing(chinese)
    for index, line in enumerate(japanese, 1):
        if line.strip() != "<p>あとがき</p>":
            continue
        if len(japanese) - index < 10:
            return None
        jp_head = japanese[:index - 1]
        if len(jp_head) != len(cn_head):
            return None
        if standalone_br_lines(jp_head) != standalone_br_lines(cn_head):
            return None
        return index
    return None


def order_swap_offset(japanese: list[str], chinese: list[str]) -> int | None:
    """日文是「图片行 + `<h2>` 独占行」，中文是「`<h2>` + 图片行」——同一对行互换。

    返回发生互换的行号（1 起）。只按**结构与位置**判定，不比较行文本——两侧标题
    与正文本就是不同语言。成立条件：
      1. 两侧行数相同，`h2` 行数与图片行数相同，且各自位置只差这一处互换；
      2. 其余所有行的**类型**（空行 / `<h2>` 行 / 图片行 / `<br/>` 行 / 正文行）逐行一致。
    第 2 条是关键：真正的段落错位会让很多行的类型序列也变掉，只有「一对同类行
    换位」才会让类型序列除该处外完全相同。
    """
    if len(japanese) != len(chinese) or len(japanese) < 2:
        return None
    if len(h2_lines(japanese)) != len(h2_lines(chinese)):
        return None
    if len(img_lines(japanese)) != len(img_lines(chinese)):
        return None

    def kind(line: str) -> str:
        if not line.strip():
            return "blank"
        if re.search(r"<h2\b", line):
            return "h2"
        if re.search(r"<img\b", line):
            return "img"
        if BR_LINE_RE.match(line):
            return "br"
        return "text"

    jp_kinds = [kind(line) for line in japanese]
    cn_kinds = [kind(line) for line in chinese]
    for i in range(len(jp_kinds) - 1):
        if jp_kinds[i] != "img" or jp_kinds[i + 1] != "h2":
            continue
        if cn_kinds[i] != "h2" or cn_kinds[i + 1] != "img":
            continue
        swapped = list(cn_kinds)
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        if swapped == jp_kinds:
            return i + 1
    return None


def allowed_pair_differences(header: str, japanese: list[str],
                            chinese: list[str]) -> tuple[str, ...] | None:
    """该表头下**预先确认过的**合法结构差异；不是这些形状就返回 None。

    命中后由 `pair_problems` 抵消对应的问题项——只抵消这条规则解释得了的项，
    其余差异照报，避免规则变成「整表头豁免」。
    """
    rule = PAIR_RULES.get(header)
    if rule is None:
        return None
    if rule == "afterword-moved":
        return ("afterword-moved",) if afterword_offset(japanese, chinese) else None
    if rule == "section-order":
        return ("section-order",) if order_swap_offset(japanese, chinese) is not None else None
    return None


def apply_pair_rules(header: str, japanese: list[str], chinese: list[str],
                     problems: list[str]) -> tuple[list[str], str]:
    """按确认过的例外抵消问题项，返回 (剩余问题, 备注)。"""
    rules = allowed_pair_differences(header, japanese, chinese)
    if not rules:
        return problems, ""
    remaining = []
    for problem in problems:
        if "afterword-moved" in rules and (
                problem.startswith("行数") or problem.startswith("<br/> 位置")):
            continue
        if "section-order" in rules and (
                problem.startswith("h2 位置") or problem.startswith("图片行")):
            continue
        remaining.append(problem)
    note = "；".join(PAIR_RULE_LABELS[r] for r in rules)
    return remaining, note


def pair_problems_raw(header: str, japanese: list[str], chinese: list[str]) -> list[str]:
    """两侧结构差异的原始判定，不含任何例外抵消。"""
    if header in TEXTUAL_IMAGE_HEADERS:
        # 已确认的文本化图片例外（AGENTS.md）：中文侧把整页图片重排为样式文本行，
        # 行数/h2/图片行/<br/> 位置本就允许不同，配对检查整体豁免。
        return []
    problems: list[str] = []
    if len(japanese) != len(chinese):
        problems.append(f"行数 {len(japanese)} vs {len(chinese)}")
    japanese_h2, chinese_h2 = h2_lines(japanese), h2_lines(chinese)
    if japanese_h2 != chinese_h2:
        problems.append(f"h2 位置 JP{japanese_h2} vs CN{chinese_h2}")
    japanese_images, chinese_images = img_lines(japanese), img_lines(chinese)
    if japanese_images != chinese_images:
        problems.append(f"图片行 JP{japanese_images} vs CN{chinese_images}")
    japanese_br = standalone_br_lines(japanese)
    chinese_br = standalone_br_lines(chinese)
    if japanese_br != chinese_br:
        problems.append(f"<br/> 位置 JP{japanese_br} vs CN{chinese_br}")
    return problems


def pair_problems(header: str, japanese: list[str], chinese: list[str]) -> list[str]:
    """对外口径：原始判定抵消掉已确认的合法差异后的剩余问题。"""
    problems = pair_problems_raw(header, japanese, chinese)
    remaining, _note = apply_pair_rules(header, japanese, chinese, problems)
    return remaining


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="检查中日缓存统一固定行模板与对齐")
    ap.add_argument("--cache", type=Path, default=Path(".cache/epub-work"))
    ap.add_argument(
        "--strict",
        action="store_true",
        help="发现任何问题时返回非零状态，供发布前质量门禁使用",
    )
    args = ap.parse_args()
    cache = args.cache

    cn_root = cache / "chinese-text"
    jp_root = cache / "japanese-text"
    cn_books = (
        {book_id(d.name): d for d in cn_root.iterdir() if d.is_dir()}
        if cn_root.is_dir()
        else {}
    )
    jp_books = (
        {book_id(d.name): d for d in jp_root.iterdir() if d.is_dir()}
        if jp_root.is_dir()
        else {}
    )
    pairs = []
    for cn_id, cn_dir in sorted(cn_books.items()):
        if cn_id is None or cn_id in NON_PAIR_WORK_IDS:
            continue
        jp_dir = jp_books.get(japanese_book_id(cn_id))
        if jp_dir is not None:
            pairs.append((cn_id, cn_dir, jp_dir))

    rows: list[list[str]] = []
    bad: list[list[str]] = []
    checked = 0
    seen: set[Path] = set()

    def add(side, book, rel, header, paired, problems, extra=""):
        row = [side, book, rel, header or "-", "是" if paired else "否",
               "; ".join(problems), extra]
        rows.append(row)
        if problems:
            bad.append(row)

    def content_index(paths: list[Path], side: str, book: str) -> dict[str, Path]:
        """按表头索引配对单元。

        刻意**不**在这里按「有无正文」过滤：纯图片页也是合法的配对单元，而
        「一侧有正文另一侧无」正是要报告的差异。是否跳过留给调用点的
        `has_body(jl) and has_body(cl)`（两侧都无正文）与 `TEXTUAL_IMAGE_HEADERS`
        （已确认的文本化图片例外）判定。
        """
        index: dict[str, Path] = {}
        duplicates: set[str] = set()
        for path in paths:
            header = pairing_header_of(path.name)
            if content_sequence(path.name) == 0:
                add(
                    side,
                    book,
                    str(path.relative_to(cache)),
                    header,
                    False,
                    ["内容序 -00 非法；数字内容序必须从 -01 开始"],
                )
                seen.add(path)
                continue
            if not header or header in duplicates:
                continue
            if header in index:
                first = index.pop(header)
                duplicates.add(header)
                add(
                    side,
                    book,
                    f"{first.relative_to(cache)} | {path.relative_to(cache)}",
                    header,
                    False,
                    ["同侧重复表头，未自动选择配对文件"],
                )
                continue
            index[header] = path
        return index

    def check_side(book: str, paths: list[Path], side: str, allow_list) -> None:
        """逐文件模板检查未配对文件。allow_list 为 True 时允许中文 L5 列表占位。"""
        nonlocal checked
        for path in paths:
            if path in seen:
                continue
            header = pairing_header_of(path.name)
            if header is None or JP_WRAPPER_RE.match(path.name):
                continue
            lines = read_lines(path)
            if not has_body(lines):
                continue
            seen.add(path)
            checked += 1
            problems = [] if template_exempt(book) else check_file(lines, allow_list)
            add(side, book, str(path.relative_to(cache)), header, False, problems)

    paired_jp: set[str] = set()
    for cn_id, cn_dir, jp_dir in pairs:
        jp_id = japanese_book_id(cn_id)
        paired_jp.add(jp_id)
        cn_all = [p for p in cn_dir.rglob("*.xhtml") if p.name.lower() != "nav.xhtml"]
        jp_all = [p for p in jp_dir.rglob("*.xhtml") if p.name.lower() != "nav.xhtml"]
        cn_by = content_index(cn_all, "中", cn_id)
        jp_by = content_index(jp_all, "日", jp_id)
        for h in sorted(set(jp_by) & set(cn_by)):
            if h in MANUAL_ALIGNMENT_HEADERS:
                add("对", cn_id, "", h, True, [], "特例待判断（人工处理中）")
                continue
            jp_p, cn_p = jp_by[h], cn_by[h]
            jl, cl = read_lines(jp_p), read_lines(cn_p)
            if not has_body(jl) and not has_body(cl):
                continue  # 两侧都是纯图片页/无正文页：不适用
            if has_body(jl) != has_body(cl) and h not in TEXTUAL_IMAGE_HEADERS:
                # 只有一侧有正文：这是真实的结构差异，不能默默跳过。
                # 曾经这里写的是 `if not has_body(jl) or not has_body(cl): continue`，
                # 于是「日文整页图片 ↔ 中文正文页」这类配对既不做模板检查也不报差异，
                # S5 全部 7 部作品的扉页就这样在报告里完全消失。
                add("对", cn_id,
                    f"JP:{jp_p.relative_to(cache)} | CN:{cn_p.relative_to(cache)}",
                    h, True,
                    ["一侧有正文另一侧无：日文 %d 行（正文 %s）/ 中文 %d 行（正文 %s）"
                     % (len(jl), has_body(jl), len(cl), has_body(cl))],
                    "结构差异")
                continue
            checked += 1
            for p_, side_, lines_ in ((jp_p, "日", jl), (cn_p, "中", cl)):
                if p_ in seen:
                    continue
                seen.add(p_)
                work = jp_id if side_ == "日" else cn_id
                allow_list = side_ == "中" and is_packaging_header(h)
                problems = [] if template_exempt(work) else check_file(lines_, allow_list)
                add(side_, work, str(p_.relative_to(cache)), h, True, problems)
            # 配对检查（先算原始问题，再按已确认的例外抵消并给出备注）
            pair_probs = pair_problems_raw(h, jl, cl)
            if pair_probs:
                pair_probs, note = apply_pair_rules(h, jl, cl, pair_probs)
            else:
                note = ""
            if pair_probs:
                rel_pair = (
                    f"JP:{jp_p.relative_to(cache)} | CN:{cn_p.relative_to(cache)}"
                )
                add("对", cn_id, rel_pair, h, True, pair_probs, "配对差异")
            elif note:
                add("对", cn_id, f"JP:{jp_p.relative_to(cache)} | CN:{cn_p.relative_to(cache)}",
                    h, True, [], note)
        # 该作品内未配对的中文文件（中文侧单有的包装页等）
        check_side(cn_id, cn_all, "中", is_packaging_header)
        # 该作品内未配对的日文文件（如 S6 单文件作品）
        check_side(jp_id, jp_all, "日", False)

    # ---------------------------------------------------------------------
    # 未配对书籍：没有对应作品时仍要对**存在的那一侧**做模板检查。
    #
    # 这段必须放在配对循环**之外**。它曾经被嵌在 `for ... in pairs:` 里面，
    # 于是在缓存里没有日文对应的中文书永远不会被检查；而 S5 又因为
    # japanese_book_id 的错误折叠进不了 pairs，结果是「既没配对、也没单侧检查」——
    # 一层缺陷掩盖了另一层，两者都不报错。
    # ---------------------------------------------------------------------
    for cn_id, cn_dir in sorted(cn_books.items()):
        if cn_id is None or any(cn_id == p[0] for p in pairs):
            continue
        cn_all = [p for p in cn_dir.rglob("*.xhtml") if p.name.lower() != "nav.xhtml"]
        content_index(cn_all, "中", cn_id)      # 仍要报告 -00 / 重复表头
        before = len(bad)
        check_side(cn_id, cn_all, "中", is_packaging_header)
        if len(bad) == before:
            add("中", cn_id, str(cn_dir.relative_to(cache)), "-", False, [],
                "无日文对应作品，仅单侧模板检查")
    for jp_id, jp_dir in sorted(jp_books.items()):
        if jp_id is None or jp_id in paired_jp:
            continue
        jp_all = [p for p in jp_dir.rglob("*.xhtml") if p.name.lower() != "nav.xhtml"]
        content_index(jp_all, "日", jp_id)
        before = len(bad)
        check_side(jp_id, jp_all, "日", False)
        if len(bad) == before:
            add("日", jp_id, str(jp_dir.relative_to(cache)), "-", False, [],
                "无中文对应作品，仅单侧模板检查")

    tsv = cache / "alignment-check.tsv"
    with tsv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["侧", "书", "文件", "表头", "配对", "问题", "备注"])
        w.writerows(rows)
    print(f"已验证正文文件：{checked}；问题记录：{len(bad)}")
    print(f"报告：{tsv}")
    for r in bad:
        print(f"  [{r[0]}] {r[1]} | {r[2].split(chr(92))[-1]} | {r[5]}")
    return 1 if args.strict and bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
