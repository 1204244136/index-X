"""中文成品标题与目录合同；只读判定，供体检、生成入口共用。

规范见 docs/epub-structure-spec.md、docs/epub-artifact-spec.md。
不推断单层标题是否应当分层，也不核定标题译法。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlsplit

from epub_structure import resolve_reference
from xhtml_text import element_text_without_ruby

HEADING_TAGS = frozenset({"h1", "h2", "h3"})
HEADING_BLOCK = re.compile(r"<((?:[\w.-]+:)?h[123])\b[^>]*>.*?</\1\s*>", re.S | re.I)
INLINE_TAGS = frozenset({"span", "ruby", "rb", "rt", "rp", "sup", "sub", "em", "b", "i", "strong", "a"})
FUNCTION_ATTRS = frozenset({"id", "lang", "{http://www.w3.org/XML/1998/namespace}lang",
                            "{http://www.idpf.org/2007/ops}type"})
LAYER_CLASSES = {
    "heading-main": frozenset({"heading-main"}),
    "heading-subtitle": frozenset({"heading-subtitle", "font08"}),
    "heading-code": frozenset({"heading-code", "font06"}),
}
LAYER_ORDERS = {
    ("heading-main", "heading-subtitle"),
    ("heading-main", "heading-code"),
    ("heading-main", "heading-subtitle", "heading-code"),
}
CHAPTER_PREFIX = re.compile(r"^(序|终)([ \t\u3000]*)章(?=$|[\s（(])")


def normalize_chapter_main(text: str) -> str:
    """只规范作为章号的序／终章内部间距，不猜测标题层次。"""
    return CHAPTER_PREFIX.sub(lambda m: m[1] + "\u3000章", text)


def local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def base_text(element: ET.Element) -> str:
    """保留层内空白，按共享口径去读音和 XML 标记。"""
    return element_text_without_ruby(element).strip()


def heading_label(element: ET.Element) -> str:
    """目录投影：层内逐字保留，非空层以单个半角空格连接。"""
    if "heading-lines" in element.get("class", "").split():
        return " ".join(base_text(child) for child in element if base_text(child))
    return base_text(element)


def split_heading_markup(raw: str) -> tuple[str, str]:
    """按元素边界分开正文与 h1/h2/h3，保留 ruby，避免标题参与正文译名门禁。"""
    headings = [match.group(0) for match in HEADING_BLOCK.finditer(raw)]
    return HEADING_BLOCK.sub("\n", raw), "\n".join(headings)


def heading_problems(element: ET.Element) -> list[str]:
    """一个实际标题的样式、行内结构与层角色；class 按集合判定。"""
    problems: list[str] = []
    classes = set(element.get("class", "").split())
    layered = classes == {"heading-lines"}
    if classes and not layered:
        problems.append("标题样式只允许默认样式或 heading-lines")
    first = next(iter(element), None)
    numeric_main = layered and first is not None and base_text(first).isdigit()
    if local_tag(element) == "h2" and (base_text(element).isdigit() or numeric_main) and classes:
        problems.append("普通数字节号必须使用默认 h2")
    roles: list[str] = []
    layer_nodes: set[ET.Element] = set()
    if layered:
        if (element.text or "").strip() or any((c.tail or "").strip() for c in element):
            problems.append("分层标题的文字必须全部位于层 span 内")
        for child in element:
            role_classes = set(child.get("class", "").split())
            matches = [role for role, expected in LAYER_CLASSES.items() if role_classes == expected]
            if local_tag(child) != "span" or len(matches) != 1:
                problems.append("未知标题层或字号：主层 heading-main、副层 heading-subtitle font08、代码层 heading-code font06")
            else:
                roles.append(matches[0])
                layer_nodes.add(child)
            if not base_text(child):
                problems.append("标题层不得为空")
        if tuple(roles) not in LAYER_ORDERS:
            problems.append("标题层必须按主标题、副标题、代码顺序排列，且至少有两个实际层")
        main = next(iter(element), None)
    else:
        main = element
    for node in element.iter():
        if node is not element and local_tag(node) not in INLINE_TAGS:
            problems.append(f"未知标题行内结构 <{local_tag(node)}>，须人工确认")
        allowed = FUNCTION_ATTRS | ({"class"} if node is element or node in layer_nodes else set())
        if local_tag(node) == "a":
            allowed |= {"href"}
        unknown = set(node.attrib) - allowed
        if unknown:
            problems.append(f"标题中未覆盖的属性／样式：{', '.join(sorted(unknown))}")
    if not base_text(element):
        problems.append("标题不得为空")
    if main is not None:
        match = CHAPTER_PREFIX.match(base_text(main))
        if match and match[2] != "\u3000":
            problems.append("序／终章章号内部必须为一个全角空格：序　章／终　章")
    return problems


def _css_problems(css: str, need_code: bool) -> list[str]:
    rules: dict[str, str] = {}
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for selector in selectors.split(","):
            key = selector.strip()
            rules[key] = rules.get(key, "") + ";" + declarations
    problems = []

    def value(selector: str, prop: str) -> str:
        declarations = re.findall(r"(?:^|;)\s*" + re.escape(prop) + r"\s*:\s*([^;]+)",
                                  rules.get(selector, ""), flags=re.I)
        important = [v for v in declarations if re.search(r"!\s*important\s*$", v, re.I)]
        candidates = important or declarations
        return re.sub(r"!\s*important\s*$", "", candidates[-1], flags=re.I).strip().lower() if candidates else ""

    for role in LAYER_CLASSES:
        if value(f".heading-lines > .{role}", "display") != "block":
            problems.append(f"分层标题 CSS 缺少 .heading-lines > .{role} 的 display: block")
    for name, ratio in (("font08", 0.8), ("font06", 0.6)):
        if name == "font06" and not need_code:
            continue
        match = re.fullmatch(r"(\d*\.?\d+)(em|%)", value(f".{name}", "font-size"))
        if match is None or float(match[1]) / (100 if match[2] == "%" else 1) != ratio:
            problems.append(f"分层标题 CSS 的 .{name} 必须为相对字号 {ratio}em")
    return problems


def audit_title_contract(entries: dict[str, bytes]) -> list[tuple[str, str, int, str]]:
    """返回 (检查项, 书内路径, 行号, 说明)，无需日文或逐标题预期清单。"""
    problems: list[tuple[str, str, int, str]] = []
    documents: dict[str, ET.Element] = {}
    headings: dict[str, list[ET.Element]] = {}
    for name, data in entries.items():
        if not name.endswith((".xhtml", ".ncx")):
            continue
        try:
            documents[name] = ET.fromstring(data)
        except ET.ParseError as exc:
            problems.append(("title-style", name, 0, f"无法检查标题／目录：XML 解析失败：{exc}"))
            continue
        if name == "nav.xhtml" or name.endswith(".ncx"):
            continue
        nodes = [e for e in documents[name].iter() if local_tag(e) in HEADING_TAGS]
        headings[name] = nodes
        text = data.decode("utf-8-sig")
        starts = [text.count("\n", 0, m.start()) + 1 for m in
                  re.finditer(r"<(?:[\w.-]+:)?h[123]\b", text)]
        for index, node in enumerate(nodes):
            line = starts[index] if index < len(starts) else 0
            for message in heading_problems(node):
                problems.append(("title-style", name, line, message))
        packaging = name.endswith(("-Information.xhtml", "-Introduction.xhtml", "_Introduction.xhtml",
                                   "-Note.xhtml", "-Illustrations.xhtml", "-Special.xhtml"))
        first_h1 = next((e for e in nodes if local_tag(e) == "h1"), None)
        if packaging and first_h1 is not None and first_h1.get("class", "").split():
            problems.append(("title-style", name, 0, "包装／特典集合页首标题必须使用默认 h1，不能分层或附加样式"))
        if name.endswith("-Illustrations.xhtml"):
            h1 = [e for e in nodes if local_tag(e) == "h1"]
            if len(h1) != 1 or base_text(h1[0]) != "彩页":
                problems.append(("title-style", name, 0, "彩页文件必须有唯一的默认 h1「彩页」"))
        if name.endswith("-Special.xhtml"):
            h1 = [e for e in nodes if local_tag(e) == "h1"]
            if len(h1) != 1 or base_text(h1[0]) != "特典短篇":
                problems.append(("title-style", name, 0, "附属特典集合必须以默认 h1「特典短篇」为总标题"))
            if not any(local_tag(e) == "h2" for e in nodes):
                problems.append(("title-style", name, 0, "附属特典集合必须以 h2 标明至少一篇实际短篇"))
            for node in nodes:
                if local_tag(node) == "h2" and not node.get("class") and re.match(r"^\S+特典\s+\S", base_text(node)):
                    problems.append(("title-style", name, 0, "特典渠道名与独立篇名必须使用二层 h2"))
        layered = [e for e in nodes if "heading-lines" in e.get("class", "").split()]
        if layered:
            # 只检查该文档实际引用的样式表，不用未引用 CSS 抵消缺失。
            css_names = [resolve_reference(name, e.get("href", "")) for e in documents[name].iter()
                         if local_tag(e) == "link" and e.get("rel") == "stylesheet"]
            css = "\n".join(entries.get(n, b"").decode("utf-8-sig") for n in css_names if n)
            code = any("heading-code" in e.get("class", "").split() for h in layered for e in h)
            for message in _css_problems(css, code):
                problems.append(("title-style", name, 0, message))
    catalog: dict[str, list[tuple[str, str]]] = {}
    for name in ("nav.xhtml", "toc.ncx"):
        root = documents.get(name)
        if root is None:
            continue
        rows: list[tuple[str, ET.Element]] = []
        if name == "nav.xhtml":
            for nav in root.iter():
                if local_tag(nav) == "nav" and "toc" in nav.get("{http://www.idpf.org/2007/ops}type", "").split():
                    rows.extend((a.get("href", ""), a) for a in nav.iter() if local_tag(a) == "a")
        else:
            for point in root.iter():
                if local_tag(point) != "navPoint":
                    continue
                label = next((e for e in point if local_tag(e) == "navLabel"), None)
                src = next((e for e in point if local_tag(e) == "content"), None)
                if label is not None and src is not None:
                    label = next((e for e in label if local_tag(e) == "text"), None)
                    if label is not None:
                        rows.append((src.get("src", ""), label))
        catalog[name] = []
        for href, label in rows:
            plain = base_text(label)
            target = resolve_reference(name, href)
            fragment = unquote(urlsplit(href).fragment)
            catalog[name].append((f"{target}#{fragment}" if target is not None else href, plain))
            if list(label):
                problems.append(("title-catalog", name, 0, f"{href}：目录标签必须为纯文本，不能嵌入 ruby／样式标签"))
            if target not in documents:
                # 跳转存在性由 container/dangling 门禁负责。
                continue
            candidates = ([e for e in documents[target].iter() if e.get("id") == fragment]
                          if fragment else [e for e in headings.get(target, []) if local_tag(e) == "h1"][:1])
            for node in candidates:
                if local_tag(node) not in HEADING_TAGS:
                    continue
                expected = heading_label(node)
                if plain != expected:
                    problems.append(("title-catalog", name, 0,
                                     f"{href}：目录为「{plain}」，标题投影应为「{expected}」"))
                break
    if "nav.xhtml" in catalog and "toc.ncx" in catalog and catalog["nav.xhtml"] != catalog["toc.ncx"]:
        problems.append(("title-catalog", "toc.ncx", 0, "nav 与 NCX 的目录目标、标签及顺序必须一致"))
    return problems
