#!/usr/bin/env python3
"""分页源合并为章节文件：按 AGENTS.md「换页衔接处理」规则合并。

输入 bw_preprocess 处理后的分页目录（p-NNN.xhtml），按章节标题（<h1>）分组，
把分页合并为章节文件。页边界按衔接处两侧的页型定间距：
  - 文本 + 文本（连续两页正文）→ 在前一页末尾段落追加 class="pb"
  - 跨整页插图（文本 + 图片 + 文本）→ 图片包裹的 <p> 标签中追加 class="pb"，
    图片与前后文本无缝衔接且前后文本段落不额外追加换页标记
  - 若前一页末段与后一页首段是同一段落的断续，须按语义拼回完整段落（工具无法
    自动判断，输出「待确认清单」供人工核对，不再套用换页标记）

- 全页插图页（`body.p-image` 或 SVG）保留为图片行，并入其前一章节单元末尾；
- 章名整页图片扉页（非正文页且 main 容器带导航锚点 id，如 `toc-NNN`）开启新的
  章节单元，章名由导航文档补回（`attach_nav_titles`）；带表头输入仍以内容序
  变化优先；
- 无标题引子页（第一个 <h1> 之前的内容）合并为从 01 开始的独立「引子」单元；
- 整页无文本且无图/SVG 的空占位页跳过并报告；
- 每个 <h1> 起一个章节单元，其后无 <h1> 的页续入当前单元。

用法：
    python tools/merge_bw_pages.py 分页目录 --book S4_05 [--out 输出目录]
    python tools/merge_bw_pages.py 分页目录 --book S4_05 --dry-run   # 只预览
    python tools/merge_bw_pages.py 分页目录 --book S4_05 --out .cache/epub-work/

输出文件名 `<book>-<NN>.xhtml`，NN 为章节单元临时序号（引子/序章/各章/后记依次
递增），最终内容序表头（S<系列>_<卷序>-<内容序>）需在对齐时按中文侧人工确认。
"""
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

# 处理 p-001.xhtml 及 S4_05-01_p-001.xhtml / 历史的 -p-001 形式，
# 跳过 p-fmatter/p-toc/p-cover 等包装页。
PAGE_RE = re.compile(
    r"^(?:(?P<book>S\d+_(?:\d+(?:_\d+)?|\d{2}(?:\.\d{2}){2}))-"
    r"(?P<sequence>\d+)[-_])?p-(?P<page>\d{3})\.xhtml$",
    re.I,
)
H1_RE = re.compile(r"^\s*<h1\b", re.I)
H1_INNER_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)
H2_RE = re.compile(r"^\s*<h2\b", re.I)
H2_INNER_RE = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.I | re.S)
IMG_TAG_RE = re.compile(r"<(?:img|image)\b", re.I)
SVG_RE = re.compile(r"<svg\b|</svg>", re.I)
P_TAG_RE = re.compile(r"<p\b", re.I)
BODY_CLASS_RE = re.compile(r"<body\b([^>]*)>", re.I)
BODY_RE = re.compile(r"<body\b", re.I)
HTML_BODY_RE = re.compile(r"(<html\b.*?<body\b[^>]*>)", re.I | re.S)
MAIN_DIV_RE = re.compile(r'<div\b[^>]*class=["\'][^"\']*main[^"\']*["\']', re.I)
CLOSE_DIV_RE = re.compile(r"</div>")
# 数字小节：单独一行的 <p>N</p>（N 为数字）
NUM_P_RE = re.compile(r"^\s*<p\b[^>]*>\s*\d+\s*</p>\s*$", re.I)
TAG_RE = re.compile(r"<[^>]*>")
AFTERWORD_RE = re.compile(
    r"(?:あとがき|後書き|後記|后记|跋|Afterword)",
    re.IGNORECASE,
)
# 原版导航（目录）文档：用于给「章名以整页图片承载」的单元补回 h1 文本。
# 允许 bw_preprocess 加过作品号前缀的名字（S6_22.06.10-navigation-documents.xhtml）。
# 注意：调用方用 re.match（头部锚定），所以前缀必须写成显式可选组，
# 不能用 (?:^|[-_]) —— 那种写法在 match 下永远只在串首生效。
NAV_FILE_RE = re.compile(r"^(?:[\w.-]*[-_])?navigation[^/]*\.xhtml$", re.IGNORECASE)
NAV_ANCHOR_RE = re.compile(
    r'<a\b[^>]*href="(?P<href>[^"#]+)#(?P<anchor>[^"]+)"[^>]*>(?P<label>.*?)</a>',
    re.IGNORECASE | re.S,
)


def nav_page_titles(text: str) -> dict[str, str]:
    """解析 EPUB 导航文档，返回「目标分页文件名 → 目录条目文本」。

    只收 `p-NNN.xhtml#…` 形式的条目（包装页与纯锚点不计），用于确定性地补回
    图片扉页单元的 h1；不做任何模糊匹配，映射不上就留空槽。
    """
    out: dict[str, str] = {}
    for m in NAV_ANCHOR_RE.finditer(text):
        base = html.unescape(m.group("href")).rsplit("/", 1)[-1]
        label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group("label"))).strip()
        if not label or not PAGE_RE.match(base) or base in out:
            continue
        out[base] = label
    return out


def read_lines(path: Path):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig", errors="replace")
    return text.splitlines(), bom, "\r\n" in text


def is_image_line(line: str) -> bool:
    """行是否为图片行（img/image/svg 图片行，无正文文字）。"""
    if not (IMG_TAG_RE.search(line) or SVG_RE.search(line)):
        return False
    inner = re.sub(r"</?p\b[^>]*>", "", line)                   # 剥 <p> 包装
    cleaned = re.sub(r"<(?:img|image)\b[^>]*/?>", "", inner, flags=re.I)
    cleaned = re.sub(r"<svg\b.*?</svg>", "", cleaned, flags=re.I | re.S)
    return not re.sub(r"<[^>]*>", "", cleaned).strip()


def parse_page_content(name: str, text: str, bom: bool = False, crlf: bool = False) -> dict | None:
    """解析单个分页内容：p-text 页取 L4/L5 表头 + L6 起正文；插图页(SVG/p-image)取整块为图片行。"""
    name_match = PAGE_RE.match(name)
    if name_match is None:
        return None
    lines = text.splitlines()
    main_idx = next(
        (i for i, line in enumerate(lines) if MAIN_DIV_RE.search(line)), None
    )
    if main_idx is None:
        return None
    # main 容器的闭合 </div> 是文件末尾/最后一个（正文页可能有 align-end 等嵌套 div）
    div_idx = next((i for i in range(len(lines) - 1, main_idx, -1)
                    if CLOSE_DIV_RE.search(lines[i])), None)
    if div_idx is None:
        return None
    body_class = ""
    for line in lines:
        m = BODY_CLASS_RE.search(line)
        if m:
            body_class = m.group(1)
            break
    is_p_text = bool(re.search(r'class=["\'][^"\']*\bp-text\b', body_class, re.I))
    if is_p_text:
        header = lines[main_idx + 1: main_idx + 3]          # L4/L5（h1/h2 或空行）
        body = [
            line for line in lines[main_idx + 3: div_idx] if line.strip()
        ]  # 排除 main 闭合标签
    else:
        header = []
        body = [
            line for line in lines[main_idx + 1: div_idx] if line.strip()
        ]  # 排除 main 闭合标签

    joined = "\n".join(body)
    is_svg = bool(SVG_RE.search(joined) and not P_TAG_RE.search(joined))
    has_p_image = bool(re.search(r'class=["\'][^"\']*\bp-image\b', body_class, re.I))
    is_image_page = has_p_image or is_svg or bool(
        body and all(is_image_line(line) for line in body)) or bool(
            not is_p_text and (IMG_TAG_RE.search(joined) or SVG_RE.search(joined))
        )
    if is_svg:
        # 全页 SVG 插图折叠为单行图片行
        body = [" ".join(line.strip() for line in body)]
    elif is_image_page and len(body) > 1:
        # 非 SVG 插图页（如多行 <p>\n<img/>\n</p>）折叠为单行图片行
        body = [re.sub(r">\s+<", "><", " ".join(line.strip() for line in body))]
    h1 = None
    if is_p_text and header and H1_RE.match(header[0]):
        m = H1_INNER_RE.search(header[0])
        h1 = m.group(1).strip() if m else header[0].strip()
    head_source = "".join(lines[2:main_idx + 1])
    head_match = HTML_BODY_RE.search(head_source)
    if not head_match:
        return None
    head3 = re.sub(r">\s+<", "><", head_match.group(1)).strip()
    # main 容器自带的 id（如 BW 章名扉页的 toc-NNN 导航锚点）：
    # 「章名以整页图片承载」的确定性章节边界信号。
    main_id = None
    m_main = MAIN_DIV_RE.search(lines[main_idx])
    if m_main:
        seg = lines[main_idx][m_main.start():]
        seg = seg[: seg.find(">") + 1]
        m_id = re.search(r'\bid=["\']([^"\']+)["\']', seg)
        if m_id:
            main_id = m_id.group(1)
    return {
        "name": name,
        "book_id": name_match.group("book"),
        "sequence": (int(name_match.group("sequence"))
                     if name_match.group("sequence") is not None else None),
        "lines": lines,
        "header": header,
        "body": body,
        "body_class": body_class,
        "is_p_text": is_p_text,
        "is_image_page": is_image_page,
        "is_empty": not body,
        "has_h1": h1 is not None,
        "h1": h1,
        "main_id": main_id,
        "head3": head3,
        "bom": bom,
        "crlf": crlf,
    }


def parse_page(path: Path) -> dict | None:
    """解析单个分页文件。"""
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig", errors="replace")
    return parse_page_content(path.name, text, bom, "\r\n" in text)


def collect_pages(dir_path: Path) -> list[dict]:
    """递归收集并排序分页 p-NNN.xhtml（兼容 epub 解包顶层的 item/xhtml 子目录）。"""
    found = []
    for p in dir_path.rglob("*.xhtml"):
        m = PAGE_RE.match(p.name)
        if m:
            found.append((int(m.group("page")), p))
    out = []
    for _, p in sorted(found):
        pg = parse_page(p)
        if pg is not None:
            out.append(pg)
    return out


def group_units(pages: list[dict], notes: list[str]) -> list[dict]:
    """按 <h1> 分组为章节单元；无标题引子单独成单元。"""
    units: list[dict] = []
    cur: dict | None = None

    def append_to_current(pg: dict) -> None:
        assert cur is not None
        current_sequence = cur["sequence"]
        page_sequence = pg["sequence"]
        if (current_sequence is not None and page_sequence is not None
                and current_sequence != page_sequence):
            raise ValueError(
                f"同一合并单元出现冲突表头：{cur['pages'][0]['name']} 为 "
                f"-{current_sequence:02d}，{pg['name']} 为 -{page_sequence:02d}")
        cur["pages"].append(pg)

    for pg in pages:
        if pg["is_empty"]:
            notes.append(f"[空占位页] {pg['name']} 无文本无图，已跳过（规范：删除并前移后续序号）")
            continue
        if (cur and cur["sequence"] is not None and pg["sequence"] is not None
                and cur["sequence"] != pg["sequence"]):
            # 带表头输入以稳定内容序为最高优先级；允许无 h1 的尾声等显式单元。
            units.append(cur)
            cur = None
        if pg["has_h1"]:
            if cur:
                units.append(cur)
            h2 = pg["header"][1].strip() if len(pg["header"]) > 1 else ""
            cur = {"title": pg["h1"], "h1": pg["h1"],
                   "h2": h2, "pages": [pg], "image_pages": 0,
                   "sequence": pg["sequence"]}
            continue
        if pg["is_image_page"]:
            if pg.get("main_id") and pg["sequence"] is None:
                # 章名整页图片扉页：main 带原版导航锚点 id（如 toc-NNN），是
                # 确定性的章节边界信号——章名以整页图片承载、正文再无 h1 的书
                # （如 S6_22.06.10）必须在此切分单元，章名由导航补回
                # （attach_nav_titles）。带表头输入以内容序变化切分，不走此分支，
                # 避免与逐页显式映射（bw_page_header_overrides.json）冲突。
                if cur:
                    units.append(cur)
                cur = {"title": None, "h1": None, "h2": None,
                       "pages": [pg], "image_pages": 1,
                       "sequence": pg["sequence"]}
                notes.append(
                    f"[章名扉页] {pg['name']}（main id={pg['main_id']}）"
                    f"开启新章节单元，章名由导航补回")
                continue
            if cur:
                if cur.get("h1") and AFTERWORD_RE.search(cur["h1"]):
                    units.append(cur)
                    cur = {"title": None, "h1": None, "h2": None,
                           "pages": [pg], "image_pages": 1,
                           "sequence": pg["sequence"]}
                    notes.append(f"[后记边界] {pg['name']}（全页插图）位于后记后，不并入后记")
                    continue
                append_to_current(pg)
                cur["image_pages"] += 1
                notes.append(f"[插图归属] {pg['name']}（全页插图）并入「{cur['title'] or '引子'}」末尾，请核对")
            else:
                cur = {"title": None, "h1": None, "h2": None,
                       "pages": [pg], "image_pages": 1,
                       "sequence": pg["sequence"]}
                notes.append(f"[插图归属] {pg['name']} 位于首章前，归入引子单元，请核对")
            continue
        if cur:
            if cur.get("h1") and AFTERWORD_RE.search(cur["h1"]):
                units.append(cur)
                cur = {"title": None, "h1": None, "h2": None,
                       "pages": [pg], "image_pages": 0,
                       "sequence": pg["sequence"]}
                notes.append(f"[后记边界] {pg['name']}（正文）位于后记后，作为独立单元，请核对")
            else:
                append_to_current(pg)
        else:
            # 最前面的无标题页 → 引子单元
            if not units or units[-1].get("title") is not None:
                cur = {"title": None, "h1": None, "h2": None,
                       "pages": [pg], "image_pages": 0,
                       "sequence": pg["sequence"]}
            else:
                previous = units[-1]
                if (previous["sequence"] is not None and pg["sequence"] is not None
                        and previous["sequence"] != pg["sequence"]):
                    raise ValueError(
                        f"同一引子单元出现冲突表头：{previous['pages'][0]['name']} 与 "
                        f"{pg['name']}")
                previous["pages"].append(pg)
    if cur:
        units.append(cur)
    return units


BR_LINE_RE = re.compile(r"^\s*<br\s*/?>\s*$", re.I)
HEADING_RE = re.compile(r"^\s*<(h1|h2)\b", re.I)


def check_edge_br(body: list[str], page_name: str, notes: list[str]) -> list[str]:
    """检查页首/页尾是否有残留填充 <br/>，若有则报告警告并去除。

    语义：页首/页尾的填充 <br/> 属排版噪声（AGENTS.md「换页衔接处理」），
    应由 bw_preprocess 清理。本函数检测残留，报告警告但仍予以删除，
    避免跨页间隔被残留 <br/> 叠加为 4+ 行。
    """
    if not body:
        return body
    start = 0
    while start < len(body) and BR_LINE_RE.match(body[start]):
        start += 1
    end = len(body)
    while end > start and BR_LINE_RE.match(body[end - 1]):
        end -= 1

    if start > 0 or end < len(body):
        notes.append(
            f"[预处理残留] {page_name} 页首/页尾有 {start + (len(body) - end)} 个填充 <br/>，"
            f"已删除（应由 bw_preprocess 清理）")

    return body[start:end]


def semantic_edge(body: list[str]) -> tuple[str | None, str | None]:
    """返回页首/页尾的语义内容行（跳过 <br/> 填充，不报告警告）。"""
    start = 0
    while start < len(body) and BR_LINE_RE.match(body[start]):
        start += 1
    end = len(body)
    while end > start and BR_LINE_RE.match(body[end - 1]):
        end -= 1
    b = body[start:end]
    return (b[0] if b else None, b[-1] if b else None)


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


def gap_for(prev_last: str | None, next_first: str | None) -> list[str]:
    """按衔接处两侧页型定间距：换页直接在末段上标记 class="pb"，不再插入独立空白行。"""
    return []


def leading_image_pages(unit: dict) -> list[int]:
    """单元开头「整页插图且非文本页」的下标。

    BW 有些书把章名做成整页图片（图片扉页），这类单元没有 `<h1>` 文本，扉页
    必须按「篇首插图并入第 3 行头部行」处理，而不是留在正文区占行。
    """
    if unit.get("h1"):
        return []
    out: list[int] = []
    for i, pg in enumerate(unit["pages"]):
        if pg["is_image_page"] and not pg["is_p_text"]:
            out.append(i)
            continue
        break
    return out


def attach_nav_titles(units: list[dict], nav_text: str | None,
                      notes: list[str]) -> None:
    """给无文本 h1 的图片扉页单元补回原版目录标题（就地写 `nav_title`）。

    只在导航条目与单元首页文件名精确相等时补；对不上就留空槽并报告，
    不做任何模糊猜测。
    """
    titles = nav_page_titles(nav_text) if nav_text else {}
    for u in units:
        if u.get("h1"):
            continue
        first = u["pages"][0]["name"]
        if first in titles:
            u["nav_title"] = titles[first]
            notes.append(f"[补回目录标题] {first} → 「{titles[first]}」放入 L4")
        elif leading_image_pages(u):
            notes.append(
                f"[缺目录标题] {first} 单元无文本 h1 且导航无对应条目，L4 留空槽")


def merge_unit(unit: dict, notes: list[str]) -> list[str] | None:
    """合并一个章节单元，返回输出行；无法合并返回 None。"""
    pages = unit["pages"]
    if not pages:
        return None
    # 图片扉页单元：头部必须取自首个文本页，否则正文会套用图片页的
    # fixed-layout 样式并丢掉 body class / html vrtl。
    lead = leading_image_pages(unit)
    text_first = next((i for i, pg in enumerate(pages) if pg["is_p_text"]), None)
    fold = bool(lead) and text_first is not None
    head_page = pages[text_first] if fold else pages[0]
    lines = head_page["lines"]
    # 固定模板 L1-L3；main 仅是分页源排版包装，不进入输出。
    head = [lines[0], lines[1], head_page["head3"]]

    # 准备 h1 标题（提取 id 属性）；无文本 h1 时可用原版目录标题补回
    h1_text = unit["h1"] or (unit.get("nav_title") or "")
    h1_id = ""
    if unit["h1"]:
        # 从原始 h1 提取 id；标题可能已经由预处理器重建，不再依赖旧 class。
        for pg in pages:
            source_h1 = pg["header"][0] if pg["header"] else ""
            if H1_RE.match(source_h1):
                id_match = re.search(r'\bid="([^"]+)"', source_h1, re.I)
                if id_match:
                    h1_id = f' id="{id_match.group(1)}"'
                if h1_id:
                    break
    l4 = f'<h1{h1_id}>{h1_text}</h1>' if h1_text else ''

    l5 = (unit["h2"] or "") if h1_text else ""

    cleaned_bodies = []
    for i, pg in enumerate(pages):
        body = check_edge_br(pg["body"], pg["name"], notes)
        if i > 0 and pg.get("header"):
            extra_headers = [
                h for h in pg["header"] if h and HEADING_RE.match(h)
            ]
            if extra_headers:
                body = extra_headers + body
        cleaned_bodies.append(body)
    for i in range(1, len(pages)):
        prev_body = cleaned_bodies[i - 1]
        body = cleaned_bodies[i]
        prev_last = prev_body[-1] if prev_body else None
        next_first = body[0] if body else None
        if not (prev_last and next_first):
            continue
        if HEADING_RE.match(prev_last) or HEADING_RE.match(next_first):
            notes.append(
                f"[标题边界] {pages[i-1]['name']} → {pages[i]['name']} 边界含小节/章节标题，"
                f"未追加 class=\"pb\"，请核对")
        elif not is_image_line(prev_last) and not is_image_line(next_first):
            prev_body[-1] = add_class_pb(prev_last)
            notes.append(
                f"[同段核对] {pages[i-1]['name']} → {pages[i]['name']} 边界为文本+文本，"
                f"已在末段追加 class=\"pb\"；若为同一段落断续请按语义拼回（勿套换页标记）")
        elif is_image_line(prev_last):
            prev_body[-1] = add_class_pb(prev_last)
            notes.append(
                f"[插图跨页] {pages[i-1]['name']} → {pages[i]['name']} 边界前侧为图片，"
                f"已在图片段落追加 class=\"pb\"")

    if fold:
        # 图片扉页并入 L3 头部行（body 开头、标题之前），不再于正文区占行。
        images = [line for i in lead for line in cleaned_bodies[i]]
        for i in lead:
            cleaned_bodies[i] = []
        head = [head[0], head[1], head[2] + "".join(images)]
        notes.append(
            f"[篇首插图] {pages[lead[0]]['name']} 的 {len(images)} 行整页插图并入 L3 头部行")
    if not l5:
        # 图片扉页单元的「首小节」来自后续页头部，须提回 L5 槽位，正文才落在 L6。
        for body in cleaned_bodies:
            if not body:
                continue
            if H2_RE.match(body[0]):
                l5 = body.pop(0)
                notes.append(
                    f"[首小节归位] {pages[0]['name']} 单元的首个 <h2> 提到 L5 槽位")
            break

    out = list(head) + [l4, l5]
    for body in cleaned_bodies:
        out.extend(body)
    out.append("</body></html>")
    return out


def write_output(out_path: Path, lines: list[str], bom: bool, crlf: bool) -> None:
    sep = "\r\n" if crlf else "\n"
    data = (sep.join(lines) + sep).encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    out_path.write_bytes(data)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="按换页衔接处理规则合并 bw_preprocess 处理后的分页为章节文件")
    ap.add_argument("dir", type=Path, help="分页目录（bw_preprocess 处理后）")
    ap.add_argument("--book", default="BOOK", help="作品号前缀，用于输出文件名（如 S4_05）")
    ap.add_argument("--out", type=Path, default=None,
                    help="输出目录（默认 = 输入目录同级 merge-out/）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写文件")
    args = ap.parse_args()

    pages = collect_pages(args.dir)
    if not pages:
        print(f"[跳过] 目录中没有 p-NNN.xhtml 分页：{args.dir}")
        return 1
    notes: list[str] = []
    page_books = {pg["book_id"].upper() if pg["book_id"] else None for pg in pages}
    if len(page_books) > 1:
        print("[错误] 分页同时包含有表头与无表头文件，或包含多个作品号；拒绝猜测合并")
        return 1
    detected_book = next(iter(page_books))
    invalid_zero_pages = [
        pg["name"] for pg in pages if pg["sequence"] == 0
    ]
    if invalid_zero_pages:
        print(
            "[错误] 分页含非法内容序 -00；数字内容序必须从 -01 开始："
            + "、".join(invalid_zero_pages)
        )
        return 1
    output_book = args.book
    if detected_book is not None:
        if args.book == "BOOK":
            output_book = detected_book
        elif args.book.upper() != detected_book:
            print(f"[错误] --book {args.book} 与分页表头作品号 {detected_book} 不一致")
            return 1
        output_book = detected_book
    try:
        units = group_units(pages, notes)
    except ValueError as exc:
        print(f"[错误] {exc}")
        return 1
    header_sequences = [unit["sequence"] for unit in units
                        if unit["sequence"] is not None]
    if len(header_sequences) != len(set(header_sequences)):
        print("[错误] 多个合并单元使用了相同内容序；拒绝覆盖输出")
        return 1
    nav_text = None
    for cand in sorted(args.dir.rglob("*.xhtml")):
        if NAV_FILE_RE.match(cand.name):
            nav_text = cand.read_text(encoding="utf-8", errors="replace")
            break
    attach_nav_titles(units, nav_text, notes)
    out_dir = args.out or (args.dir.parent / "merge-out")
    written = 0
    for idx, unit in enumerate(units, 1):
        lines = merge_unit(unit, notes)
        if lines is None:
            continue
        sequence = unit["sequence"] if unit["sequence"] is not None else idx
        name = f"{output_book}-{sequence:02d}.xhtml"
        body_paras = sum(1 for line in lines if re.match(r"^\s*<p\b", line))
        img_rows = sum(1 for line in lines if is_image_line(line))
        display_title = unit["title"] or ("引子" if idx == 1 else "无标题单元")
        print(f"[单元 {idx:02d}] {display_title}：页 {len(unit['pages'])}，"
              f"插图页 {unit['image_pages']}，正文段 {body_paras}，图片行 {img_rows} → {name}")
        if args.dry_run:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        bom = unit["pages"][0]["bom"]
        crlf = unit["pages"][0]["crlf"]
        write_output(out_dir / name, lines, bom, crlf)
        written += 1

    print(f"分页 {len(pages)} 个 → 章节单元 {len(units)} 个"
          + ("（预览，未写盘）" if args.dry_run else f"（输出：{out_dir}，已写 {written}）"))
    if notes:
        print("=== 待人工确认清单 ===")
        for n in notes:
            print(f"  ! {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
