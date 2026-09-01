#!/usr/bin/env python3
"""DOCX → X版特色 EPUB 转换脚本（交稿稿 -> 成品）。

参考 tools/epub2docx.py（成品 EPUB -> 交稿 docx，把 <ruby> 反向还原为
|基文[注音] 交稿记号），本脚本做正向转换：读取交稿 .docx，把
|基文[注音] 还原为成品 <ruby>基文<rt>注音</rt></ruby>，并按 X 版特色的
统一固定行模板与文件命名规范生成 EPUB。

流程（每本）：
  1. 读取 .docx（zip），解析 word/document.xml 得到顺序化的段落流
     （章节标题、数字小节、正文、内嵌图片）；
  2. 正文中 |基文[注音] -> <ruby>基文<rt>注音</rt></ruby>；
  3. 以章节标题拆分文件，生成 <表头>-<内容序>_<语义后缀>.xhtml，
     套用统一固定行模板（L1-L6，LF 换行、无 BOM）；
  4. 提取 docx 内嵌图片（按字节去重）到 OEBPS/Images/；
  5. 生成 mimetype / META-INF/container.xml / OEBPS/content.opf /
     nav.xhtml / toc.ncx / OEBPS/Styles/style.css；
  6. 打包为 .epub（--unpacked 同时输出解包目录）。

结构识别约定（对照 epub2docx 产生的交稿 docx）：
  - "Heading 1" 段落：非纯数字者为章标题（序章/第N章/行間/終章/あとがき…），
    每个章标题生成一个正文文件；纯数字者为小节，生成 <h2>；
  - 第一章之前的正文（引言）并入第一章文件，图片生成封面/彩页；
  - 卷末非正文样式的奥付/版权文字自动丢弃并报告。

用法：
    python tools/docx2epub.py 某稿.docx
    python tools/docx2epub.py --out 输出目录/ 书1.docx 书2.docx
    python tools/docx2epub.py 交稿目录/ --pattern "*S1_01*"
    python tools/docx2epub.py --series S4 --volume 06 未带编号.docx
    python tools/docx2epub.py --title 书名 --author 作者 --language zh-CN 稿.docx
    python tools/docx2epub.py --unpacked 解包目录/ --no-pack 稿.docx
    python tools/docx2epub.py --dry-run 稿.docx
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import re
import sys
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from epub_ids import book_id

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

EPUB_MIMETYPE = b"application/epub+zip"

# 正文文件固定行模板的 L3 头部（可并入篇首图片，此处为纯头部）
HEAD3 = ('<html xmlns="http://www.w3.org/1999/xhtml" '
         'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
         '<link href="../Styles/style.css" rel="stylesheet" type="text/css"/>'
         "<title></title></head><body>")

# 交稿注音记号：|基文[注音] -> <ruby>基文<rt>注音</rt></ruby>
_RUBY = re.compile(r"\|([^|\n]+?)\[([^\]]+)\]")

# docx 正文里可信任的行内 HTML 标签（半校对稿直接以字面标签标注重点）
_HTML_TAG = re.compile(r"(</?[a-zA-Z][a-zA-Z0-9]*\s*[^>]*>)")
_HTML_KEEP = {"b", "i", "small", "sup", "sub", "strong", "em", "u"}

# 插图占位符：如 【插图-1】
_ILLUS_RE = re.compile(r"^【插图-(\d+)】$")

# 行内译注（交稿层面）：【*译注：...】 或 （*译注：...）
# 成品中提取为 Note 脚注页引用（优先方括号，内容可含圆括号）
_NOTE_BRACKET = re.compile(r"【\*?译注[：:](.*?)】", re.DOTALL)
_NOTE_PAREN = re.compile(r"（\*?译注[：:]([^）]*)）", re.DOTALL)

# 章标题识别：序章/第N章/行間/終章/あとがき 等（中日、简繁均可）
_CHAPTER_RE = re.compile(
    r"^(?:序\s*章|序(?=[\s　])|プロローグ|Prologue|"
    r"[終终]\s*章|[終终](?=[\s　])|尾声|エピローグ|Epilogue|"
    r"第[〇零一二三四五六七八九十百千0-9０-９]+章|"
    r"行[間间]|[間间]章|Interlude|"
    r"あとがき|後書き|後記|后记|跋|"
    r"巻末|特典|Special)",
    re.IGNORECASE,
)

_TOC_WORDS = {"table of contents", "contents", "目次", "toc"}

_CN_DIGITS = {
    "〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}

_CSS = """\
body {
  padding: 0%;
  margin-top: 0%;
  margin-bottom: 0%;
  margin-left: 1%;
  margin-right: 1%;
  line-height: 120%;
  text-align: justify;
}
p {
  text-indent: 2em;
  display: block;
  line-height: 1.6em;
  margin: 0em;
  word-wrap: break-word;
}
div {
  margin: 0;
  padding: 0;
  line-height: 120%;
  text-align: justify;
}
h1 {
  font-size: 1.6em;
  line-height: 1.2em;
  margin-top: 1em;
  margin-bottom: 1.8em;
  font-weight: bold;
  text-align: center;
}
h2 {
  font-size: 1.4em;
  line-height: 1.1em;
  margin-top: 1.8em;
  margin-bottom: 1em;
  font-weight: bold;
  text-align: center;
}
rt {
  font-size: 0.5em;
}
ruby {
  ruby-align: center;
}
.cover {
  margin: 0;
  padding: 0;
  text-indent: 0;
  text-align: center;
}
.fit {
  display: inline-block;
  page-break-inside: avoid;
  max-height: 100%;
  max-width: 100%;
}
.center {
  text-indent: 0;
  text-align: center;
}
.right {
  text-indent: 0;
  text-align: right;
}
.bold {
  font-weight: bold;
}
.italic {
  font-style: italic;
}
.nodeco {
  text-decoration: none;
  color: #879AC5;
}
.po {
  font-size: 0.9em;
  text-indent: -0.8em;
  padding: 0 0.1em 0.1em 1em;
  color: #960014;
}
.box2 {
  border-style: solid;
  border-color: #9d9b9c;
  border-radius: 8px;
  padding: 12px 6px;
  margin: 26px 1px;
  border-width: 2px;
}
.font06 { font-size: 0.6em; }
.font07 { font-size: 0.7em; }
.font08 { font-size: 0.8em; }
.font09 { font-size: 0.9em; }
.font10 { font-size: 1em; }
.font11 { font-size: 1.1em; }
.font12 { font-size: 1.2em; }
.font13 { font-size: 1.3em; }
.font14 { font-size: 1.4em; }
.font15 { font-size: 1.5em; }
.font16 { font-size: 1.6em; }
"""


def esc(text: str) -> str:
    """XML 文本转义（& < >），保留引号（元素文本无需转义引号）。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def esc_ruby(text: str) -> str:
    """先转义再还原 |基文[注音] -> <ruby>，保证注入的标签不被转义。

    同时保留 docx 中直接写出的可信行内标签（<b>/<i>/<small>/<sup> 等），
    其余尖括号内容一律转义，避免注入非法标签。
    """
    out: list[str] = []
    for piece in _HTML_TAG.split(text):
        if not piece:
            continue
        if _HTML_TAG.fullmatch(piece):
            name = re.match(r"</?([a-zA-Z][a-zA-Z0-9]*)", piece).group(1).lower()
            if name in _HTML_KEEP:
                out.append(piece)
                continue
        out.append(_RUBY.sub(r"<ruby>\1<rt>\2</rt></ruby>", esc(piece)))
    return "".join(out)


def is_number(text: str) -> bool:
    return bool(re.fullmatch(r"[0-9０-９]{1,4}", text))


def is_heading_style(style: str) -> bool:
    """识别 docx 标题段落样式：兼容 Heading 1 / Heading1 / 标题 1 等写法。"""
    return bool(re.match(r"heading\s*\d*$", style, re.IGNORECASE)) or style.casefold() == "标题"


def is_body_style(style: str) -> bool:
    """识别普通正文样式（大小写不敏感，兼容 Word 的 normal / Normal）。"""
    return style.casefold() in ("normal", "")


def is_chapter_title(text: str) -> bool:
    return bool(_CHAPTER_RE.match(text.strip()))


def resolve_suffix(title: str) -> str | None:
    """由章标题文本决定语义后缀；无法识别返回 None（调用方用 SectionN）。"""
    t = title.strip()
    if re.match(r"^序", t):
        return "Prologue"
    if re.match(r"^[終终]", t):
        return "Epilogue"
    if re.match(r"^第", t):
        m = re.match(r"^第([〇零一二三四五六七八九十百千0-9０-９]+)章", t)
        if m:
            return f"Chapter{cn_to_int(m.group(1))}"
        return None
    if re.match(r"^行[間间]|^[間间]章", t):
        return "Between_the_Lines"
    if re.match(r"^あとがき|^後書|^後記|^后记|^跋", t):
        return "Afterwords"
    if re.match(r"^巻末|^特典|^Special", t, re.IGNORECASE):
        return "Special"
    return None


def cn_to_int(s: str) -> int:
    """汉字/全角/阿拉伯数字转整数（支持 一~九十九、1、１２）。"""
    if s.isdigit():
        return int(s)
    total = 0
    num = 0
    for ch in s:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch == "十":
            total += (num or 1) * 10
            num = 0
        elif ch == "百":
            total += (num or 1) * 100
            num = 0
        elif ch == "千":
            total += (num or 1) * 1000
            num = 0
        elif "０" <= ch <= "９":
            num = ord(ch) - ord("０")
        else:
            num = 0
    return total + num


def detect_language(sample: str) -> str:
    """正文含日文假名 -> ja-JP，否则 zh-CN。"""
    if re.search(r"[ぁ-ゖァ-ヺ]", sample):
        return "ja-JP"
    return "zh-CN"


# ---------------------------------------------------------------------------
# docx 解析
# ---------------------------------------------------------------------------

def parse_docx(path: Path) -> tuple[list[dict], dict, dict, dict]:
    """读取 .docx，返回 (段落流, rId->media文件名, media文件名->字节, 核心元数据)。"""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "word/document.xml" not in names:
            raise ValueError("缺少 word/document.xml，不是有效 docx")
        doc_root = ET.fromstring(z.read("word/document.xml"))
        rel_map: dict[str, str] = {}
        if "word/_rels/document.xml.rels" in names:
            for rel in ET.fromstring(z.read("word/_rels/document.xml.rels")):
                rid = rel.get("Id")
                target = rel.get("Target")
                if rid and target:
                    rel_map[rid] = target
        media: dict[str, bytes] = {}
        for name in names:
            if name.startswith("word/media/"):
                media[Path(name).name] = z.read(name)
        core: dict[str, str] = {}
        if "docProps/core.xml" in names:
            try:
                core_root = ET.fromstring(z.read("docProps/core.xml"))
                dc = "{http://purl.org/dc/elements/1.1/}"
                for tag, key in ((dc + "title", "title"), (dc + "creator", "creator")):
                    el = core_root.find(tag)
                    if el is not None and el.text:
                        core[key] = el.text.strip()
            except ET.ParseError:
                pass

    paragraphs: list[dict] = []
    for idx, p_el in enumerate(doc_root.iter(_W + "p")):
        style = "Normal"
        ppr = p_el.find(_W + "pPr")
        if ppr is not None:
            ps = ppr.find(_W + "pStyle")
            if ps is not None:
                style = ps.get(_W + "val") or "Normal"
        parts: list[str] = []
        for r_el in p_el.iter(_W + "r"):
            for child in r_el:
                tag = child.tag
                if tag == _W + "t":
                    parts.append(child.text or "")
                elif tag == _W + "tab":
                    parts.append(" ")
                elif tag == _W + "br":
                    parts.append(" ")
        text = re.sub(r"\s+", " ", "".join(parts)).strip()
        imgs: list[str] = []
        for blip in p_el.iter(_A + "blip"):
            rid = blip.get(_R + "embed")
            if rid:
                imgs.append(rid)
        has_link = p_el.find(_W + "hyperlink") is not None
        paragraphs.append({
            "idx": idx, "style": style, "text": text,
            "imgs": imgs, "has_link": has_link,
        })
    return paragraphs, rel_map, media, core


# ---------------------------------------------------------------------------
# 章节装配
# ---------------------------------------------------------------------------

def build_chapters(paragraphs: list[dict]) -> tuple[list[dict], list[list[str]], list[str], list[str]]:
    """把段落流装配成章节。

    返回 (chapters, front_images, front_text, dropped)。
    - chapters: [{title, blocks, suffix}]，blocks 元素为
      ("p", text) / ("h2", text) / ("image", [rid, ...])
    - front_images: 第一章之前的图片段落 rid 列表（首张作封面，其余作彩页）
    - front_text: 第一章之前的正文文本（用于统计；若首章为序章则独立成引子）
    - dropped: 被丢弃的 TOC / 卷末奥付 / 注意事项文本
    """
    chapters: list[dict] = []
    front_images: list[list[str]] = []
    front_text: list[str] = []
    dropped: list[str] = []
    current: dict | None = None
    seen_first = False
    last_chapter_idx = -1

    def start_chapter(title: str, idx: int) -> None:
        nonlocal current, seen_first, last_chapter_idx
        chapters.append({"title": title, "blocks": [], "suffix": resolve_suffix(title)})
        current = chapters[-1]
        seen_first = True
        last_chapter_idx = idx

    for blk in paragraphs:
        if blk["imgs"]:
            if not seen_first:
                front_images.append(blk["imgs"])
            elif current is not None:
                current["blocks"].append(("image", blk["imgs"]))
            else:
                front_images.append(blk["imgs"])
            continue
        text = blk["text"]
        if not text:
            continue
        # 插图占位符：【插图-N】 -> ("illus", N)
        m = _ILLUS_RE.fullmatch(text)
        if m:
            if current is not None:
                current["blocks"].append(("illus", int(m.group(1))))
            else:
                dropped.append(text)
            continue
        style = blk["style"]
        if is_heading_style(style):
            if is_chapter_title(text):
                start_chapter(text, blk["idx"])
                continue
            if is_number(text):
                if current is None:
                    # 首个内容即数字小节（无章标题的极简稿）
                    start_chapter(text, blk["idx"])
                else:
                    current["blocks"].append(("h2", text))
                continue
            # 未识别 Heading 1：目录标题丢弃，其余视为新章节
            if not seen_first and text.casefold() in _TOC_WORDS:
                dropped.append(text)
            else:
                start_chapter(text, blk["idx"])
            continue
        # 非 Heading
        if not seen_first:
            if blk["has_link"] or not is_body_style(style):
                dropped.append(text)  # 目录超链接 / 注意事项 / 卷首版权
            else:
                front_text.append(text)  # 引言
            continue
        if blk["idx"] > last_chapter_idx and not is_body_style(style):
            dropped.append(text)  # 卷末奥付/版权
            continue
        if current is not None:
            current["blocks"].append(("p", text))
        elif chapters:
            chapters[-1]["blocks"].append(("p", text))
        else:  # pragma: no cover - 理论不可达
            front_text.append(text)

    if front_text and chapters:
        front_blocks = [("p", text) for text in front_text]
        if chapters[0]["suffix"] == "Prologue":
            chapters.insert(0, {
                "title": "",
                "nav_title": "引子",
                "blocks": front_blocks,
                "suffix": "Before_the_Prologue",
            })
        else:
            chapters[0]["blocks"] = front_blocks + chapters[0]["blocks"]
    return chapters, front_images, front_text, dropped


# ---------------------------------------------------------------------------
# 图片收集（去重命名）
# ---------------------------------------------------------------------------

def collect_images(paragraphs: list[dict], rel_map: dict, media: dict, header: str,
                   first_idx_is_cover: bool) -> tuple[dict, dict, str | None]:
    """按段落顺序首次引用顺序给图片命名（去重），返回 (rid->名, 名->字节, 封面图名)。"""
    names: dict[str, str] = {}
    seen_sha: dict[str, str] = {}
    image_bytes: dict[str, bytes] = {}
    seq = 0
    cover_name: str | None = None
    for blk in paragraphs:
        for rid in blk["imgs"]:
            if rid in names:
                continue
            target = rel_map.get(rid)
            if not target:
                continue
            fname = Path(target).name
            data = media.get(fname)
            if data is None:
                continue
            sha = hashlib.sha256(data).hexdigest()
            existing = seen_sha.get(sha)
            if existing is not None:
                names[rid] = existing
                continue
            ext = (Path(fname).suffix or ".bin").lower()
            if first_idx_is_cover and cover_name is None:
                name = f"{header}-Cover{ext}"
                cover_name = name
            else:
                seq += 1
                name = f"{header}-{seq:03d}{ext}"
            seen_sha[sha] = name
            names[rid] = name
            image_bytes[name] = data
    return names, image_bytes, cover_name


# ---------------------------------------------------------------------------
# 源 EPUB 取图（封面/彩页/正文插图）
# ---------------------------------------------------------------------------

def extract_source_images(epub: Path, header: str) -> dict:
    """从源 EPUB（通常为日文原版）按 spine 顺序提取图片。

    返回 {"images": {名->字节}, "cover": 封面图名或 None,
          "illustrations": [彩页图名...], "body": [正文插图名...]}。

    分类规则：
    - p-cover* 页面引用的图 -> 封面；
    - p-fmatter* 页面引用的图 -> 彩页；
    - 其余正文页（文件名不以 p- 开头、非导航页，且含文本段落）引用的图
      -> 正文插图（按出现顺序）；纯图片标题页（如日文 m-* 章首图）不取。
    """
    out: dict = {"images": {}, "cover": None, "illustrations": [], "body": []}
    xlink = "{http://www.w3.org/1999/xlink}"
    opf_ns = "{http://www.idpf.org/2007/opf}"
    cont_ns = "{urn:oasis:names:tc:opendocument:xmlns:container}"
    image_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp")

    with zipfile.ZipFile(epub) as z:
        names = set(z.namelist())

        def _image(name: str) -> bytes | None:
            if name in names:
                return z.read(name)
            bn = Path(name).name
            for n in names:
                if Path(n).name == bn:
                    return z.read(n)
            return None

        # 定位 OPF
        opf_path = None
        if "META-INF/container.xml" in names:
            try:
                root = ET.fromstring(z.read("META-INF/container.xml"))
                for rf in root.iter(cont_ns + "rootfile"):
                    opf_path = rf.get("full-path")
                    break
            except ET.ParseError:
                opf_path = None
        if not opf_path:
            for n in sorted(names):
                if n.lower().endswith(".opf"):
                    opf_path = n
                    break
        if not opf_path:
            raise ValueError(f"源 EPUB 缺少 OPF：{epub}")
        opf_dir = str(Path(opf_path).parent).replace("\\", "/")

        def resolve(href: str) -> str:
            if href.startswith("/"):
                return href.lstrip("/")
            return f"{opf_dir}/{href}" if opf_dir else href

        try:
            opf = ET.fromstring(z.read(opf_path))
        except ET.ParseError as exc:
            raise ValueError(f"源 EPUB OPF 解析失败：{epub}") from exc

        spine = [ir.get("idref") for ir in opf.iter(opf_ns + "itemref")]
        items = {it.get("id"): it.get("href") for it in opf.iter(opf_ns + "item")}

        seen_sha: dict[str, str] = {}
        for iid in spine:
            href = items.get(iid)
            if not href or not href.lower().endswith((".xhtml", ".html", ".htm")):
                continue
            zp = resolve(href)
            if zp not in names:
                continue
            try:
                doc = ET.fromstring(z.read(zp))
            except ET.ParseError:
                doc = None  # 源文件可能标签不配对（BookWalker 偶发），用正则兜底
            # 收集该页图片引用
            refs: list[str] = []
            has_text = False
            if doc is not None:
                for el in doc.iter():
                    tag = el.tag.rsplit("}", 1)[-1]
                    if tag == "img" and el.get("src"):
                        refs.append(el.get("src"))
                    elif tag == "image" and el.get(xlink + "href"):
                        refs.append(el.get(xlink + "href"))
                    elif tag == "p" and (el.text or "").strip():
                        has_text = True
            else:
                text = z.read(zp).decode("utf-8", "replace")
                refs = (re.findall(r"<img[^>]*\bsrc=\"([^\"]+)\"", text)
                        + re.findall(r"<image[^>]*xlink:href=\"([^\"]+)\"", text))
                has_text = bool(re.search(r"<p[^>]*>[^<\s]", text))
            base = Path(zp).name
            low = base.lower()
            if "p-cover" in low:
                kind = "cover"
            elif "p-fmatter" in low:
                kind = "illustrations"
            elif "p-" in low or "navigation" in low or not has_text:
                continue  # 其他包装页 / 纯图片标题页
            else:
                kind = "body"
            for r in refs:
                if not r.lower().endswith(image_exts):
                    continue
                data = _image(resolve(r))
                if data is None:
                    continue
                sha = hashlib.sha256(data).hexdigest()
                if sha in seen_sha:
                    continue
                src_name = Path(r.split("/")[-1]).name
                ext = (Path(src_name).suffix or ".jpg").lower()
                if kind == "cover":
                    name = f"{header}-Cover{ext}"
                    out["cover"] = name
                elif kind == "illustrations":
                    name = f"{header}-Illustrations{len(out['illustrations']) + 1}{ext}"
                    out["illustrations"].append(name)
                else:
                    name = f"{header}-{src_name}"
                    out["body"].append(name)
                seen_sha[sha] = name
                out["images"][name] = data
    return out


# ---------------------------------------------------------------------------
# XHTML 渲染（固定行模板）
# ---------------------------------------------------------------------------

def render_content(ch: dict, names: dict, body_illus: dict | None = None) -> str:
    """按统一固定行模板渲染正文文件：L4=h1、L5=h2或空行、L6 起正文。

    body_illus: {占位符编号: 图片名}，把 【插图-N】 占位符替换为图片行；
    未提供对应图时保留占位符原样（便于人工补图）。
    """
    title = ch["title"]
    blocks = ch["blocks"]
    body_illus = body_illus or {}
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        "<!DOCTYPE html>",
        HEAD3,
        f"<h1>{esc_ruby(title)}</h1>" if title else "",
    ]
    h2_idx = 0
    first_is_h2 = bool(blocks) and blocks[0][0] == "h2"
    if first_is_h2:
        h2_idx += 1
        lines.append(f'<h2 id="toc_{h2_idx}">{esc(blocks[0][1])}</h2>')
        body = blocks[1:]
    else:
        lines.append("")  # 无 h2 空行占位
        body = blocks
    for kind, payload in body:
        if kind == "p":
            lines.append(f"<p>{esc_ruby(payload)}</p>")
        elif kind == "h2":
            h2_idx += 1
            lines.append(f'<h2 id="toc_{h2_idx}">{esc(payload)}</h2>')
        elif kind == "image":
            for rid in payload:
                name = names.get(rid)
                if name:
                    lines.append(f'<p><img alt="图片" class="fit" src="../Images/{name}"/></p>')
        elif kind == "illus":
            name = body_illus.get(payload)
            if name:
                lines.append(f'<p><img alt="图片" class="fit" src="../Images/{name}"/></p>')
            else:
                lines.append(f"<p>{esc('【插图-{}】'.format(payload))}</p>")
    lines.append("</body></html>")
    return "\n".join(lines) + "\n"


def render_cover(name: str) -> str:
    if not name:
        return ""
    return "\n".join([
        "<?xml version='1.0' encoding='utf-8'?>",
        "<!DOCTYPE html>",
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head>',
        "<br/>",
        '<link href="../Styles/style.css" rel="stylesheet" type="text/css"/>',
        "<title></title>",
        "</head>",
        '<body epub:type="cover">',
        f'<p><img alt="图片" class="fit" src="../Images/{name}"/></p>',
        "</body></html>",
        "",
    ])


def render_illustrations(name_list: list[str]) -> str:
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        "<!DOCTYPE html>",
        ('<html xmlns="http://www.w3.org/1999/xhtml" '
         'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
         '<link href="../Styles/style.css" rel="stylesheet" type="text/css"/>'
         "<title></title></head><body><h1>彩页</h1>"),
    ]
    for name in name_list:
        if name:
            lines.append(f'<p><img alt="图片" class="fit" src="../Images/{name}"/></p>')
    lines.append("</body></html>")
    return "\n".join(lines) + "\n"


def extract_notes(text: str, notes: list[str], header: str) -> str:
    """把行内译注【*译注：...】提取为 Note 脚注页引用，返回替换后的文本。

    notes 用于收集译注内容（顺序即 note 编号）；引用形如
    <a class="nodeco" epub:type="noteref" href="{header}-Note.xhtml#noteN"><sup>㊟</sup></a>。
    """
    def repl(m: re.Match) -> str:
        n = len(notes) + 1
        notes.append(m.group(1).strip())
        return (f'<a class="nodeco" epub:type="noteref" '
                f'href="{header}-Note.xhtml#note{n}"><sup>㊟</sup></a>')

    text = _NOTE_BRACKET.sub(repl, text)
    text = _NOTE_PAREN.sub(repl, text)
    return text


def render_note_file(notes: list[str], header: str) -> str:
    """生成译注页 Note.xhtml（列表型包装页：h1 占 L4，ul 占 L5，条目自 L6 起）。"""
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        "<!DOCTYPE html>",
        HEAD3,
        '<h1 class="center">译注</h1>',
        "<ul>",
    ]
    for i, note in enumerate(notes, 1):
        lines.append(f'<li epub:type="footnote" id="note{i}">{esc(note)}</li>')
    lines += ["</ul>", "</body></html>", ""]
    return "\n".join(lines)


def render_nav(entries: list[tuple[str, str, list[str]]]) -> str:
    """entries: [(文件名, 标题, [h2 小节文本...])]。"""
    lines = [
        "<!DOCTYPE html>",
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">',
        "<head>",
        "<title>Navigation</title>",
        "</head>",
        "<body>",
        '<nav epub:type="toc">',
        "<ol>",
    ]
    for fname, title, h2s in entries:
        href = f"OEBPS/Text/{fname}"
        lines.append(f'<li><a href="{href}">{title}</a>')
        if h2s:
            lines.append("<ol>")
            for i, h2 in enumerate(h2s, 1):
                lines.append(f'<li><a href="{href}#toc_{i}">{h2}</a></li>')
            lines.append("</ol>")
        lines.append("</li>")
    lines += ["</ol>", "</nav>", "</body></html>", ""]
    return "\n".join(lines)


def render_ncx(entries: list[tuple[str, str, list[str]]], doc_title: str, uid: str) -> str:
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="zh">',
        "  <head>",
        f'    <meta name="dtb:uid" content="{uid}"/>',
        '    <meta name="dtb:depth" content="3"/>',
        "  </head>",
        "  <docTitle>",
        f"    <text>{esc(doc_title)}</text>",
        "  </docTitle>",
        "  <navMap>",
    ]
    order = 0
    for fname, title, h2s in entries:
        order += 1
        lines.append(f'    <navPoint id="num_{order}" playOrder="{order}">')
        lines.append("      <navLabel>")
        lines.append(f"        <text>{esc(title)}</text>")
        lines.append("      </navLabel>")
        lines.append(f'      <content src="OEBPS/Text/{fname}"/>')
        for i, h2 in enumerate(h2s, 1):
            order += 1
            lines.append(f'    <navPoint id="num_{order}" playOrder="{order}">')
            lines.append("      <navLabel>")
            lines.append(f"        <text>{esc(h2)}</text>")
            lines.append("      </navLabel>")
            lines.append(f'      <content src="OEBPS/Text/{fname}#toc_{i}"/>')
            lines.append("    </navPoint>")
        lines.append("    </navPoint>")
    lines += ["  </navMap>", "</ncx>", ""]
    return "\n".join(lines)


def render_opf(meta: dict, text_files: list[str], image_names: list[str],
               cover_name: str | None, uid: str) -> str:
    """meta: {title, creator, language, uuid}。text_files 为 spine 顺序的正文文件名。"""
    manifest: list[str] = []
    spine: list[str] = []
    item_id = 0
    cover_img_id = None

    def add_item(href: str, media_type: str, properties: str | None = None,
                 in_spine: bool = False) -> str:
        nonlocal item_id, cover_img_id
        item_id += 1
        iid = f"id{item_id}"
        props = f' properties="{properties}"' if properties else ""
        manifest.append(f'    <item id="{iid}" href="{href}" media-type="{media_type}"{props}/>')
        if in_spine:
            spine.append(f'    <itemref idref="{iid}"/>')
        if properties == "cover-image":
            cover_img_id = iid
        return iid

    for fname in text_files:
        add_item(f"Text/{fname}", "application/xhtml+xml", in_spine=True)
    for name in image_names:
        ext = Path(name).suffix.lower()
        mtype = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                 ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "application/octet-stream")
        props = "cover-image" if name == cover_name else None
        add_item(f"Images/{name}", mtype, props)
    add_item("Styles/style.css", "text/css")
    add_item("../nav.xhtml", "application/xhtml+xml", "nav")
    ncx_id = add_item("../toc.ncx", "application/x-dtbncx+xml")

    title = meta.get("title", "")
    creator = meta.get("creator", "")
    language = meta.get("language", "zh-CN")
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="BookId">',
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">',
        f'    <dc:title id="id">{esc(title)}</dc:title>',
    ]
    if creator:
        lines.append(f'    <dc:creator id="id-1">{esc(creator)}</dc:creator>')
    lines += [
        f'    <dc:identifier id="BookId">uuid:{uid}</dc:identifier>',
        f"    <dc:language>{language}</dc:language>",
        '    <meta refines="#id" property="title-type">main</meta>',
    ]
    if cover_img_id:
        lines.append(f'    <meta name="cover" content="{cover_img_id}"/>')
    # spine 需要 toc 属性指向 NCX（EPUB2 兼容，Calibre Check Book 会校验）
    lines += ["  </metadata>", "  <manifest>", *manifest,
              "  </manifest>", f'  <spine toc="{ncx_id}">',
              *spine, "  </spine>", "</package>", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 输出与打包
# ---------------------------------------------------------------------------

def build_book_files(book: dict) -> dict[str, str | bytes]:
    """把 book 渲染为 路径(相对根)->内容 的映射。"""
    files: dict[str, str | bytes] = {}
    text_root = "OEBPS/Text"
    files["mimetype"] = EPUB_MIMETYPE
    files["META-INF/container.xml"] = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "    <rootfiles>\n"
        '        <rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/>\n'
        "   </rootfiles>\n"
        "</container>\n")
    files["OEBPS/Styles/style.css"] = book["css"]
    files["nav.xhtml"] = book["nav"]
    files["toc.ncx"] = book["ncx"]
    files["OEBPS/content.opf"] = book["opf"]
    for fname, content in book["text_files"].items():
        files[f"{text_root}/{fname}"] = content
    for name, data in book["images"].items():
        files[f"OEBPS/Images/{name}"] = data
    return files


def write_unpacked(book: dict, dest_dir: Path) -> None:
    for relpath, content in book["files"].items():
        target = dest_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            # 强制 LF 换行，不随 Windows 平台翻译为 CRLF
            target.write_bytes(content.encode("utf-8"))


def write_epub(book: dict, dest_path: Path) -> int:
    """按 EPUB 规范打包：mimetype 首项不压缩，其余按路径排序压缩。"""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_path, "w") as zout:
        zout.writestr("mimetype", book["files"]["mimetype"], zipfile.ZIP_STORED)
        for relpath in sorted(
            (p for p in book["files"] if p != "mimetype"),
            key=lambda p: p.casefold(),
        ):
            content = book["files"][relpath]
            if isinstance(content, bytes):
                zout.writestr(relpath, content, zipfile.ZIP_DEFLATED)
            else:
                zout.writestr(relpath, content.encode("utf-8"), zipfile.ZIP_DEFLATED)
    return dest_path.stat().st_size


# ---------------------------------------------------------------------------
# 单本处理
# ---------------------------------------------------------------------------

def process_one(docx_path: Path, args: argparse.Namespace) -> int:
    label = str(docx_path)
    stem = docx_path.stem
    out_dir = (args.out if args.out else docx_path.parent).resolve()

    # 表头与书名：文件名 [S4_06]某书(6).docx -> header=S4_06, title=某书(6)
    # 支持 S6 日期表头 [S6_22.06.10]xxx.docx -> header=S6_22.06.10
    parsed_header = book_id(stem)
    if parsed_header:
        header = parsed_header
        title = (re.sub(r"^\[[^\]]+\]", "", stem, count=1) or stem).strip()
    else:
        if not (args.series and args.volume):
            print(f"[跳过] {label}：文件名不含 [S..] 表头，请用 --series/--volume 指定",
                  file=sys.stderr)
            return 1
        header = f"{args.series}_{args.volume}"
        title = stem

    title = args.title or title
    creator = args.author or ""
    try:
        paragraphs, rel_map, media, core = parse_docx(docx_path)
    except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError) as exc:
        print(f"[失败] {label}：{exc}", file=sys.stderr)
        return 1

    chapters, front_images, front_text, dropped = build_chapters(paragraphs)
    ruby_count = sum(len(_RUBY.findall(blk["text"])) for blk in paragraphs)

    if args.dry_run:
        print(f"[{label}] 段落 {len(paragraphs)}，章节 {len(chapters)}，"
              f"前置图片 {len(front_images)}，引言 {len(front_text)} 段，"
              f"ruby 记号 {ruby_count} 处，丢弃 {len(dropped)} 段")
        for it in dropped[:10]:
            print(f"  ! 丢弃：{it[:50]}")
        if len(dropped) > 10:
            print(f"  …另有 {len(dropped) - 10} 条丢弃未列出")
        return 0

    # docx 内嵌图片命名（封面/正文图）
    first_par = paragraphs[0] if paragraphs else {}
    first_idx_is_cover = bool(first_par.get("imgs"))
    names, image_bytes, cover_name = collect_images(
        paragraphs, rel_map, media, header, first_idx_is_cover)

    # 源 EPUB 取图（正文插图/封面/彩页）+ 用户指定封面/彩页
    src = {"images": {}, "cover": None, "illustrations": [], "body": []}
    if args.images_from:
        try:
            src = extract_source_images(args.images_from, header)
        except (OSError, zipfile.BadZipFile, ValueError) as exc:
            print(f"[失败] {label}：源取图失败：{exc}", file=sys.stderr)
            return 1
        if not args.quiet:
            print(f"        源图：封面 {bool(src['cover'])}，彩页 {len(src['illustrations'])}，"
                  f"正文插图 {len(src['body'])}")
    if args.cover:
        p = Path(args.cover)
        name = f"{header}-Cover{p.suffix.lower() or '.jpg'}"
        src["images"][name] = p.read_bytes()
        src["cover"] = name
    illu_before: list[str] = []
    for f in args.illustrations_before or []:
        p = Path(f)
        src["images"][p.name] = p.read_bytes()
        illu_before.append(p.name)
    illu_after: list[str] = []
    for f in args.illustrations_after or []:
        p = Path(f)
        src["images"][p.name] = p.read_bytes()
        illu_after.append(p.name)
    src["illustrations"] = illu_before + src["illustrations"] + illu_after
    image_bytes.update(src["images"])
    if not cover_name:
        cover_name = src["cover"]

    # 【插图-N】占位符 -> 源正文插图（按出现顺序）
    body_illus: dict[int, str] = {}
    for n, name in enumerate(src["body"], 1):
        body_illus[n] = name

    # 命名：内容序与语义后缀
    bt = 0
    seq = 0
    entries: list[tuple[str, str, list[str]]] = []
    text_files: dict[str, str] = {}
    notes: list[str] = []  # 行内译注 -> Note 页
    for ch in chapters:
        suffix = ch["suffix"]
        seq += 1
        content_seq = seq
        if suffix == "Between_the_Lines":
            bt += 1
            suffix = f"Between_the_Lines{bt}"
        elif suffix is None:
            suffix = f"Section{content_seq}"
        fname = f"{header}-{content_seq:02d}_{suffix}.xhtml"
        h2s = [p[1] for p in ch["blocks"] if p[0] == "h2"]
        entries.append((fname, ch.get("nav_title", ch["title"]), h2s))
        rendered = render_content(ch, names, body_illus)
        text_files[fname] = extract_notes(rendered, notes, header)

    # 封面/彩页（docx 内嵌 + 源/用户提供）
    cover_text = ""
    illustrations_text = ""
    illustration_names: list[str] = []
    if front_images:
        cover_rid = front_images[0][0]
        if names.get(cover_rid):
            cover_text = render_cover(names[cover_rid])
            if len(front_images[0]) > 1:
                illustration_names += [names[r] for r in front_images[0][1:] if names.get(r)]
            for rids in front_images[1:]:
                illustration_names += [names[r] for r in rids if names.get(r)]
    elif src["cover"]:
        cover_text = render_cover(src["cover"])
    illustration_names += src["illustrations"]
    if illustration_names:
        illustrations_text = render_illustrations(illustration_names)

    text_file_order: list[str] = []
    nav_entries: list[tuple[str, str, list[str]]] = []
    cover_fname = ""
    illu_fname = ""
    if cover_text:
        cover_fname = f"{header}-Cover.xhtml"
        text_files[cover_fname] = cover_text
        text_file_order.append(cover_fname)
        nav_entries.append((cover_fname, "封面", []))
    if illustrations_text:
        illu_fname = f"{header}-Illustrations.xhtml"
        text_files[illu_fname] = illustrations_text
        text_file_order.append(illu_fname)
        nav_entries.append((illu_fname, "彩页", []))
    nav_entries.extend(entries)
    text_file_order.extend(fname for fname, _, _ in entries)
    # 译注页（正文之后，spine 末尾）
    if notes:
        note_fname = f"{header}-Note.xhtml"
        text_files[note_fname] = render_note_file(notes, header)
        text_file_order.append(note_fname)
        nav_entries.append((note_fname, "译注", []))

    # 语言与元数据
    sample = "".join(blk["text"] for blk in paragraphs)
    language = args.language or detect_language(sample)
    book_name = title or stem
    out_stem = f"[{header}]{book_name}"
    uid = str(uuid.uuid4())
    meta = {"title": book_name, "creator": creator or core.get("creator", ""),
            "language": language, "uuid": uid}

    css = _CSS
    if args.css:
        css = Path(args.css).read_text(encoding="utf-8")

    book = {
        "header": header,
        "stem": out_stem,
        "title": book_name,
        "text_files": text_files,
        "images": image_bytes,
        "cover_name": cover_name,
        "css": css,
        "nav": render_nav(nav_entries),
        "ncx": render_ncx(nav_entries, book_name, uid),
        "opf": render_opf(meta, text_file_order, sorted(image_bytes), cover_name, uid),
    }
    book["files"] = build_book_files(book)

    # 输出
    if not args.no_pack:
        epub_path = out_dir / f"{out_stem}.epub"
        try:
            size = write_epub(book, epub_path)
        except OSError as exc:
            print(f"[失败] {label}：{exc}", file=sys.stderr)
            return 1
        if not args.quiet:
            print(f"[{label}] -> {epub_path}（{size:,} bytes）")
    if args.unpacked:
        dest = args.unpacked.resolve() / out_stem
        try:
            write_unpacked(book, dest)
        except OSError as exc:
            print(f"[失败] {label}：{exc}", file=sys.stderr)
            return 1
        if not args.quiet:
            print(f"[{label}] 解包目录 -> {dest}")

    if not args.quiet:
        print(f"        XHTML {len(text_files)} 个，图片 {len(image_bytes)} 张，"
              f"ruby 还原 {ruby_count} 处，丢弃 {len(dropped)} 段")
    return 0


def expand_inputs(paths: list[str], pattern: str) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            print(f"[跳过] 不存在：{p}", file=sys.stderr)
            continue
        if p.is_file():
            if p.suffix.lower() == ".docx":
                out.append(p)
            else:
                print(f"[跳过] 不是 .docx：{p}", file=sys.stderr)
            continue
        pat = pattern.casefold()
        found = sorted(
            (c for c in p.iterdir()
             if c.is_file() and c.suffix.lower() == ".docx"
             and fnmatch.fnmatch(c.name.casefold(), pat)),
            key=lambda c: c.name.casefold(),
        )
        out.extend(found)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="把交稿 .docx 转成 X 版特色 EPUB，|基文[注音] 还原为 <ruby>")
    ap.add_argument("paths", nargs="+", help="一个或多个 .docx 文件或目录")
    ap.add_argument("--out", type=Path, default=None,
                    help="epub 输出目录（默认与输入同目录）")
    ap.add_argument("--pattern", default="*",
                    help="目录输入时按文件名 glob 筛选（大小写不敏感）")
    ap.add_argument("--series", default=None, help="系列号（如 S4；文件名不含 [S..] 时需要）")
    ap.add_argument("--volume", default=None, help="卷序（如 06；文件名不含 [S..] 时需要）")
    ap.add_argument("--title", default=None, help="书名覆盖")
    ap.add_argument("--author", default=None, help="作者覆盖")
    ap.add_argument("--language", default=None, help="语言代码覆盖（默认按正文内容自动判断）")
    ap.add_argument("--css", type=Path, default=None, help="用指定 style.css 替代内置样式")
    ap.add_argument("--images-from", type=Path, default=None,
                    help="从源 EPUB（通常为日文原版）提取正文插图/封面/彩页，"
                         "并把正文中的【插图-N】占位符替换为对应图片")
    ap.add_argument("--cover", type=Path, default=None,
                    help="用指定图片文件作封面（覆盖源封面）")
    ap.add_argument("--illustrations-before", action="append", default=[],
                    help="追加到彩页最前的图片文件（可多次，如中文版副封面）")
    ap.add_argument("--illustrations-after", action="append", default=[],
                    help="追加到彩页最后的图片文件（可多次，如中文版目录页）")
    ap.add_argument("--unpacked", type=Path, default=None,
                    help="额外输出解包书籍目录（每本一个子目录）")
    ap.add_argument("--no-pack", action="store_true", help="只输出解包目录，不打包 .epub")
    ap.add_argument("--dry-run", action="store_true", help="只统计与预览，不写文件")
    ap.add_argument("--quiet", action="store_true", help="只打印错误与汇总")
    args = ap.parse_args()

    if args.no_pack and args.unpacked is None:
        ap.error("--no-pack 需要配合 --unpacked 使用")

    inputs = expand_inputs(args.paths, args.pattern)
    if not inputs:
        print("没有匹配到任何输入", file=sys.stderr)
        return 1

    ok = failed = 0
    for docx in inputs:
        if process_one(docx, args) == 0:
            ok += 1
        else:
            failed += 1
    print(f"完成：{ok} 本成功，{failed} 本失败")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
