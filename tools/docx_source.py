#!/usr/bin/env python3
"""交稿 docx 的段落流与行内记号解析（`docx2epub.py` 与 `import_*.py` 共用实现）。

只读：本模块不写任何文件，也不决定书籍结构；章节装配与模板渲染由调用方负责。

对外提供两类能力：
1. **段落流**：`read_docx()` 按 `word/document.xml` 的文档顺序返回
   `{idx, style, text, imgs, has_link, tabs, breaks}`。`idx` 是文档顺序里
   `w:p` 的序号（含表格内段落），是新书导入改动表的唯一定位键。
2. **交稿记号 ↔ 产物标记**：`|基文[注音]` → `<ruby>`、`【*译注：…】` → Note
   页脚注引用，以及转义。同一规则只在这里实现一份。

`collapse_whitespace` 默认 `True`（沿用 `docx2epub.py` 既有行为：折叠连续空白
并 strip）。新书导入要求逐字保真，必须显式传 `False`，再由
`import_docx_outline.py` 报告空白异常。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# 交稿注音记号：|基文[注音] -> <ruby>基文<rt>注音</rt></ruby>
RUBY_RE = re.compile(r"\|([^|\n]+?)\[([^\]]+)\]")

# docx 正文里可信任的行内 HTML 标签（半校对稿直接以字面标签标注重点）
HTML_TAG_RE = re.compile(r"(</?[a-zA-Z][a-zA-Z0-9]*\s*[^>]*>)")
HTML_KEEP = frozenset({"b", "i", "small", "sup", "sub", "strong", "em", "u"})

# 行内译注（交稿层面）：【*译注：...】 或 （*译注：...）
NOTE_BRACKET_RE = re.compile(r"【\*?译注[：:](.*?)】", re.DOTALL)
NOTE_PAREN_RE = re.compile(r"（\*?译注[：:]([^）]*)）", re.DOTALL)

# 插图占位符：如 【插图-1】/【*插图】(outline 报告用，编号可为空)
ILLUS_RE = re.compile(r"^【\*?插图(?:-(\d+))?】$")

# 空行以外还可能代表排版意图的字符（导入前必须人工确认，不静默折叠）
SUSPECT_WHITESPACE = ("\u3000", "\u00a0", "\t")


def read_docx(path: Path | str, *, collapse_whitespace: bool = True
              ) -> tuple[list[dict], dict[str, str], dict[str, bytes], dict[str, str]]:
    """读取 .docx，返回 (段落流, rId→media 文件名, media 文件名→字节, 核心元数据)。

    `collapse_whitespace=False` 时保留段落原文（含首尾空白与段内换行标记），
    交稿逐字导入使用该模式。
    """
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "word/document.xml" not in names:
            raise ValueError("缺少 word/document.xml，不是有效 docx")
        document = ET.fromstring(archive.read("word/document.xml"))
        rel_map: dict[str, str] = {}
        if "word/_rels/document.xml.rels" in names:
            for rel in ET.fromstring(archive.read("word/_rels/document.xml.rels")):
                rid, target = rel.get("Id"), rel.get("Target")
                if rid and target:
                    rel_map[rid] = target
        media: dict[str, bytes] = {}
        for name in names:
            if name.startswith("word/media/"):
                media[Path(name).name] = archive.read(name)
        core: dict[str, str] = {}
        if "docProps/core.xml" in names:
            try:
                core_root = ET.fromstring(archive.read("docProps/core.xml"))
                dc = "{http://purl.org/dc/elements/1.1/}"
                for tag, key in ((dc + "title", "title"), (dc + "creator", "creator")):
                    element = core_root.find(tag)
                    if element is not None and element.text:
                        core[key] = element.text.strip()
            except ET.ParseError:
                pass

    paragraphs: list[dict] = []
    for idx, element in enumerate(document.iter(W + "p")):
        paragraphs.append({
            "idx": idx,
            "style": paragraph_style(element),
            "text": paragraph_text(element, collapse_whitespace=collapse_whitespace),
            "imgs": paragraph_images(element),
            "has_link": element.find(W + "hyperlink") is not None,
            "tabs": sum(1 for node in element.iter() if node.tag == W + "tab"),
            "breaks": sum(1 for node in element.iter() if node.tag == W + "br"),
        })
    return paragraphs, rel_map, media, core


def paragraph_style(element: ET.Element) -> str:
    properties = element.find(W + "pPr")
    if properties is None:
        return "Normal"
    style = properties.find(W + "pStyle")
    return (style.get(W + "val") if style is not None else None) or "Normal"


def paragraph_text(element: ET.Element, *, collapse_whitespace: bool = True) -> str:
    parts: list[str] = []
    for run in element.iter(W + "r"):
        for child in run:
            if child.tag == W + "t":
                parts.append(child.text or "")
            elif child.tag == W + "tab":
                parts.append(" ")
            elif child.tag == W + "br":
                parts.append(" ")
    text = "".join(parts)
    if collapse_whitespace:
        return re.sub(r"\s+", " ", text).strip()
    return text


def paragraph_images(element: ET.Element) -> list[str]:
    found: list[str] = []
    for blip in element.iter(A + "blip"):
        rid = blip.get(R + "embed")
        if rid:
            found.append(rid)
    return found


# ---------------------------------------------------------------------------
# 章节与分类（只做机械判定，语义由调用方裁定）
# ---------------------------------------------------------------------------

def is_heading_style(style: str, level: int | None = None) -> bool:
    """识别 docx 标题段落样式：兼容 Heading 1 / Heading1 / 标题 1 等写法。"""
    if level is None:
        return bool(re.match(r"heading\s*\d*$", style, re.IGNORECASE)) or style.casefold() == "标题"
    return bool(re.fullmatch(rf"heading\s*{level}", style, re.IGNORECASE)) or (
        style.casefold() == "标题" and level == 1)


def is_body_style(style: str) -> bool:
    """识别普通正文样式（大小写不敏感，兼容 Word 的 normal / Normal）。"""
    return style.casefold() in ("normal", "")


def is_number(text: str) -> bool:
    return bool(re.fullmatch(r"[0-9０-９]{1,4}", text.strip()))


def chapter_kind(paragraph: dict) -> str:
    """把段落归入导入层面的行类型：h1/h2/p/blank/img/note-only。"""
    text = paragraph["text"]
    stripped = text.strip()
    if is_heading_style(paragraph["style"], 1):
        return "h1"
    if ILLUS_RE.match(stripped):
        return "img"
    if is_heading_style(paragraph["style"], 2):
        return "h2"
    if not stripped:
        return "blank"
    if NOTE_BRACKET_RE.sub("", stripped).strip() == "" and NOTE_BRACKET_RE.search(stripped):
        return "note-only"
    if NOTE_PAREN_RE.sub("", stripped).strip() == "" and NOTE_PAREN_RE.search(stripped):
        return "note-only"
    return "p"


def split_chapters(paragraphs: list[dict]) -> list[dict]:
    """按 Heading 1 切分段落流；第一节之前的内容归入 ``title=None`` 的首段。"""
    chapters: list[dict] = []
    for paragraph in paragraphs:
        if chapter_kind(paragraph) == "h1":
            chapters.append({"title": paragraph["text"].strip(), "heading": paragraph,
                             "rows": []})
            continue
        if not chapters:
            chapters.append({"title": None, "heading": None, "rows": []})
        chapters[-1]["rows"].append(paragraph)
    return [chapter for chapter in chapters if chapter["rows"] or chapter["title"]]


# ---------------------------------------------------------------------------
# 行内记号
# ---------------------------------------------------------------------------

def esc(text: str) -> str:
    """XML 文本转义（& < >），保留引号（元素文本无需转义引号）。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def esc_ruby(text: str) -> str:
    """先转义再还原 `|基文[注音]` -> `<ruby>`，保证注入的标签不被转义。

    同时保留 docx 中直接写出的可信行内标签（`<b>`/`<i>`/`<small>`/`<sup>` 等），
    其余尖括号内容一律转义，避免注入非法标签。
    """
    out: list[str] = []
    for piece in HTML_TAG_RE.split(text):
        if not piece:
            continue
        if HTML_TAG_RE.fullmatch(piece):
            name = re.match(r"</?([a-zA-Z][a-zA-Z0-9]*)", piece).group(1).lower()
            if name in HTML_KEEP:
                out.append(piece)
                continue
        out.append(RUBY_RE.sub(r"<ruby>\1<rt>\2</rt></ruby>", esc(piece)))
    return "".join(out)


def extract_notes(text: str, notes: list[str], header: str) -> str:
    """把行内译注提取为 Note 脚注页引用，返回替换后的文本。

    `notes` 按阅读顺序收集译注正文（顺序即 note 编号）；引用形如
    `<a class="nodeco" epub:type="noteref" href="{header}-Note.xhtml#noteN"><sup>㊟</sup></a>`。
    """
    note_header = header if header.endswith("-Note") else f"{header}-Note"

    def repl(match: re.Match) -> str:
        notes.append(match.group(1).strip())
        number = len(notes)
        return (f'<a class="nodeco" epub:type="noteref" '
                f'href="{note_header}.xhtml#note{number}"><sup>㊟</sup></a>')

    return NOTE_PAREN_RE.sub(repl, NOTE_BRACKET_RE.sub(repl, text))
