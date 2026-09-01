#!/usr/bin/env python3
"""BookWalker（bw）提取预处理：清理排版噪声并建立分页合并所需的固定模板。

本工具职责：
  - 正文页头部折叠为 L1-L3，L4/L5 固定为 h1/h2 或空行槽位
  - start-3em/font-1em30 章节标题转 h1，start-5em/数字小节转 h2
  - 多段 ruby 合并为单段
  - font-1em50 / em-sesame / tcy / line-break-loose 等排版 span 解包
  - 页首/页尾填充 <br/> 删除
  - <p><br/></p> 展平为 <br/>

默认只建立 ``merge_bw_pages.py`` 读取分页所需的 L1-L5 契约；显式提供
``--book-id`` 时还会建立分页 XHTML 与图片的作品号表头。合并后的最终语义
文件名、中日配对与完整规范化仍由后续流程处理。

规则集来源（逐条按 JSON 中顺序应用，与原始「查找/替换」列表行为一致）：
    tools/bw_extract_preprocess.json   ← 默认规则文件（可编辑，以此为准）
    --rules <path>                     ← 自定义规则文件（与 bw提取预处理.json 同格式）

输入：
    *.epub 文件   → 解包 → 改写全部 .xhtml/.html/.htm → 重新打包为
                    <原名>.preprocessed.epub（默认保留原文件；--out 指定输出目录）
    目录          → 就地改写目录下全部 .xhtml/.html/.htm（先 --dry-run 预览）

规则文件格式（与 bw提取预处理.json 一致）：
    { "searches": [ { "name": ..., "find": ..., "replace": ...,
                      "case_sensitive": bool, "dot_all": bool, "mode": "regex" } ] }

用法：
    python tools/bw_preprocess.py 某本bw提取.epub
    python tools/bw_preprocess.py --dry-run 某本bw提取.epub
    python tools/bw_preprocess.py --out 输出目录/ 某本bw提取.epub
    python tools/bw_preprocess.py 已解包的目录/
    python tools/bw_preprocess.py --rules 自定义.rules.json 某本bw提取.epub
    python tools/bw_preprocess.py --book-id S4_05 某本bw提取.epub
    python tools/bw_preprocess.py --check 某本bw提取.epub   # 校验模式，不写盘
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

import merge_bw_pages

XHTML_SUFFIXES = (".xhtml", ".html", ".htm")
IMAGE_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".svg",
    ".tif", ".tiff",
)
DEFAULT_RULES_JSON = "bw_extract_preprocess.json"
DEFAULT_HEADER_MAP_JSON = "bw_page_header_overrides.json"
REFERENCE_SUFFIXES = XHTML_SUFFIXES + (".opf", ".ncx", ".xml", ".css", ".svg")
XML_SUFFIXES = XHTML_SUFFIXES + (".opf", ".ncx", ".xml", ".svg")
NUMERIC_PAGE_RE = re.compile(r"^(?:.*/)?p-(\d{3})\.xhtml$", re.IGNORECASE)
HEADERED_PAGE_RE = re.compile(
    r"^(?:.*/)?S\d+_(?:\d+(?:_\d+)?|\d{2}(?:\.\d{2}){2})-"
    r"(?:\d+_)?p-(\d{3})\.xhtml$",
    re.IGNORECASE,
)
BOOK_ID_RE = re.compile(r"S\d+_(?:\d+(?:_\d+)?|\d{2}(?:\.\d{2}){2})", re.IGNORECASE)
BODY_TAG_RE = re.compile(r"<body\b[^>]*>", re.IGNORECASE | re.DOTALL)
CSS_URL_RE = re.compile(rb"url\(\s*(['\"]?)([^)'\"]+)\1\s*\)", re.IGNORECASE)
CLASS_ATTR_RE = re.compile(
    r'''\bclass\s*=\s*(?:"([^"]*)"|'([^']*)')''',
    re.IGNORECASE | re.DOTALL,
)


def load_rules(rules_path: Path | None) -> list[dict]:
    """读取并编译规则。默认取脚本同目录下的 DEFAULT_RULES_JSON。"""
    if rules_path is None:
        rules_path = Path(__file__).resolve().parent / DEFAULT_RULES_JSON
    if not rules_path.exists():
        sys.exit(
            f"找不到规则文件：{rules_path}\n"
            f"请用 --rules 指定，或把 {DEFAULT_RULES_JSON} 放在脚本同目录。")
    data = json.loads(rules_path.read_text(encoding="utf-8-sig"))
    searches = data.get("searches")
    if not isinstance(searches, list) or not searches:
        sys.exit("规则文件缺少非空 searches 列表")
    compiled: list[dict] = []
    for r in searches:
        if not isinstance(r, dict) or "find" not in r or "replace" not in r:
            sys.exit(f"规则条目缺少 find/replace：{r!r}")
        flags = re.MULTILINE  # 让 ^ $ 按行匹配（对应裸数字小节等行级规则）
        if not r.get("case_sensitive", False):
            flags |= re.IGNORECASE
        if r.get("dot_all"):
            flags |= re.DOTALL
        find = r["find"]
        if r.get("mode", "regex") != "regex":
            find = re.escape(find)
        compiled.append({
            "name": r.get("name", f"规则{len(compiled) + 1}"),
            "pat": re.compile(find, flags),
            "repl": r["replace"],
            "iterative": bool(r.get("iterative", False)),
        })
    return compiled


def load_header_map(book_id: str | None, map_path: Path | None) -> dict[str, int | None] | None:
    """读取已审计的分页表头映射；无对应作品时返回 None。"""
    if book_id is None:
        return None
    explicit = map_path is not None
    if map_path is None:
        map_path = Path(__file__).resolve().parent / DEFAULT_HEADER_MAP_JSON
    if not map_path.exists():
        if explicit:
            sys.exit(f"找不到分页表头映射：{map_path}")
        return None
    data = json.loads(map_path.read_text(encoding="utf-8-sig"))
    raw_pages = data.get("books", {}).get(book_id.upper(), {}).get("pages")
    if raw_pages is None:
        return None
    if not isinstance(raw_pages, dict) or not raw_pages:
        sys.exit(f"分页表头映射 {book_id.upper()} 的 pages 必须是非空对象")
    result: dict[str, int | None] = {}
    for raw_name, raw_sequence in raw_pages.items():
        if not NUMERIC_PAGE_RE.fullmatch(raw_name):
            sys.exit(f"分页表头映射含无效源文件名：{raw_name}")
        if raw_sequence is not None and (
                not isinstance(raw_sequence, int) or isinstance(raw_sequence, bool)
                or raw_sequence < 1):
            sys.exit(f"分页表头映射序号必须为正整数或 null：{raw_name}={raw_sequence!r}")
        result[raw_name] = raw_sequence
    return result


def apply_rules(text: str, rules: list[dict]) -> str:
    """按顺序应用全部规则。标记 iterative 的规则循环应用至稳定。

    ruby 修正每次只合并相邻一对 <rt>（4 段→3 段→…），需迭代到不动点
    才能把多段 ruby 完全合并成单段，且保证重复运行幂等。
    """
    for r in rules:
        if r["iterative"]:
            while True:
                nxt = r["pat"].sub(r["repl"], text)
                if nxt == text:
                    break
                text = nxt
        else:
            text = r["pat"].sub(r["repl"], text)
    return text


def tag_has_class(tag: str, class_name: str) -> bool:
    """标签的 class 属性是否包含指定的完整 class token。"""
    match = CLASS_ATTR_RE.search(tag)
    if match is None:
        return False
    value = match.group(1) if match.group(1) is not None else match.group(2)
    return class_name.casefold() in {token.casefold() for token in value.split()}


def is_content(text: str) -> bool:
    """是否为正文内容文件（body 的 class 包含 p-text）。"""
    body = BODY_TAG_RE.search(text)
    return body is not None and tag_has_class(body.group(0), "p-text")


def template_issues(lines: list[str]) -> list[str]:
    """固定行模板 L1-L6 校验；空列表表示可安全交给分页合并器。

    L1 XML，L2 DOCTYPE，L3 折叠后的 html/head/body/main，L4 h1 或空槽，
    L5 h2 或空槽，L6 正文 p。另做完整 XML 语法检查，防止结构合法性被行模板
    检查掩盖。
    """
    issues: list[str] = []
    if len(lines) < 6:
        return [f"行数 {len(lines)} < 6，无法满足 L1-L6 模板"]
    if not lines[0].startswith("<?xml"):
        issues.append(f"L1 非 XML 声明：{lines[0][:40]}")
    if not lines[1].startswith("<!DOCTYPE"):
        issues.append(f"L2 非 DOCTYPE：{lines[1][:40]}")
    if not (lines[2].startswith("<html") and '<div class="main">' in lines[2]):
        issues.append('L3 未折叠为单行头部（需含 <div class="main">）')
    l4, l5, l6 = lines[3], lines[4], lines[5]
    if l4 and not re.match(r"^<h1\b[^>]*>.*</h1>$", l4):
        issues.append(f"L4 应为单行 <h1> 或空行：{l4[:40]}")
    if l5 and not re.match(r"^<h2\b[^>]*>.*</h2>$", l5):
        issues.append(f"L5 应为单行 <h2> 或空行：{l5[:40]}")
    if not re.match(r"^\s*<p\b", l6):
        issues.append(f"L6 应为正文 <p>：{l6[:40]}")
    try:
        ET.fromstring("\n".join(lines))
    except ET.ParseError as exc:
        issues.append(f"XML 解析失败：{exc}")
    return issues


def verify_text(text: str) -> list[str]:
    """内容文件的模板校验；非内容（图片页/包装页）返回空列表。"""
    if not is_content(text):
        return []
    return template_issues(text.splitlines())


def transform_bytes(data: bytes, rules: list[dict]) -> tuple[bytes, bool]:
    """解码（保留 BOM/CRLF 风格）→ 应用规则 → 编码，返回 (新字节, 是否变化)。"""
    bom = data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig", errors="replace")
    crlf = "\r\n" in text
    if crlf:
        # 归一化换行：先折叠 CRLF，再清除孤立 \r（如 \r\r\n 双重 CR 的脏文件）
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    new_text = apply_rules(text, rules)
    changed = new_text != text
    if crlf:
        new_text = new_text.replace("\n", "\r\n")
    out = new_text.encode("utf-8")
    if bom:
        out = b"\xef\xbb\xbf" + out
    return out, changed


def _with_basename(path: str, basename: str) -> str:
    """替换 ZIP POSIX 路径的 basename，不改变所在目录。"""
    prefix, separator, _ = path.rpartition("/")
    return f"{prefix}{separator}{basename}" if separator else basename


def pairing_header_renames(
        entries: dict[str, bytes], book_id: str,
        page_map: dict[str, int | None] | None = None) -> dict[str, str]:
    """为 BookWalker XHTML 和图片分配稳定表头，返回 ZIP 条目重命名映射。

    第一个分页单元使用 ``-01``；此后每遇到一个新的 L4 ``h1``，内容序加一。
    没有 h1 的续页和全页插图 XHTML 沿用当前内容序。其他 XHTML 和图片只加
    完整作品号，保留原稳定 basename；图片不得根据所在分页猜测内容序。标准
    ``nav.xhtml`` 是唯一不加作品号的 XHTML。
    """
    if not BOOK_ID_RE.fullmatch(book_id):
        raise ValueError(f"无效作品号：{book_id}")
    book_id = book_id.upper()
    renames: dict[str, str] = {}
    numeric = sorted(
        ((int(match.group(1)), name) for name in entries
         if (match := NUMERIC_PAGE_RE.match(name))),
        key=lambda item: item[0],
    )
    if page_map is not None and numeric:
        actual_pages = {name.rsplit("/", 1)[-1] for _, name in numeric}
        expected_pages = set(page_map)
        if actual_pages != expected_pages:
            missing = sorted(expected_pages - actual_pages)
            unexpected = sorted(actual_pages - expected_pages)
            raise ValueError(
                f"分页表头映射与 EPUB 不一致：缺少 {missing or '无'}；"
                f"未登记 {unexpected or '无'}")
    sequence = 0
    for _, name in numeric:
        basename = name.rsplit("/", 1)[-1]
        if page_map is not None:
            mapped_sequence = page_map[basename]
            if mapped_sequence is None:
                renames[name] = _with_basename(name, f"{book_id}-{basename}")
            else:
                renames[name] = _with_basename(
                    name, f"{book_id}-{mapped_sequence:02d}_{basename}")
            continue
        text = entries[name].decode("utf-8-sig", errors="replace")
        lines = text.splitlines()
        if sequence == 0 or (
                is_content(text) and len(lines) > 3
                and lines[3].lstrip().startswith("<h1")):
            sequence += 1
        renames[name] = _with_basename(
            name, f"{book_id}-{sequence:02d}_{basename}")

    for name in entries:
        if not name.lower().endswith(XHTML_SUFFIXES) or name in renames:
            continue
        basename = name.rsplit("/", 1)[-1]
        if basename.casefold() == "nav.xhtml" or basename.upper().startswith(book_id + "-"):
            continue
        renames[name] = _with_basename(name, f"{book_id}-{basename}")

    for name in entries:
        if not name.lower().endswith(IMAGE_SUFFIXES):
            continue
        basename = name.rsplit("/", 1)[-1]
        if not basename.upper().startswith(book_id + "-"):
            renames[name] = _with_basename(name, f"{book_id}-{basename}")

    targets = [renames.get(name, name) for name in entries]
    if len(targets) != len(set(targets)):
        raise ValueError("表头重命名产生文件名冲突")
    return renames


def page_map_contract_issues(
        entries: dict[str, bytes], book_id: str,
        page_map: dict[str, int | None] | None) -> list[tuple[str, str]]:
    """确认已审计分页映射在最终 ZIP 条目中被逐项、且仅逐项落实。"""
    if page_map is None:
        return []
    book_id = book_id.upper()
    expected = {
        (f"{book_id}-{sequence:02d}_{raw_name}"
         if sequence is not None else f"{book_id}-{raw_name}")
        for raw_name, sequence in page_map.items()
    }
    actual = {
        name.rsplit("/", 1)[-1] for name in entries
        if HEADERED_PAGE_RE.fullmatch(name)
    }
    issues: list[tuple[str, str]] = []
    for missing in sorted(expected - actual):
        issues.append((missing, "已审计分页映射的目标 XHTML 不存在"))
    for unexpected in sorted(actual - expected):
        issues.append((unexpected, "分页 XHTML 未登记或表头序号不符合已审计映射"))
    return issues


def apply_entry_renames(entries: dict[str, bytes], renames: dict[str, str]) -> dict[str, bytes]:
    """重命名 ZIP 条目，并同步改写 XML/XHTML/OPF/NCX/CSS/SVG 引用。"""
    replacements = [
        (old.rsplit("/", 1)[-1].encode("utf-8"),
         new.rsplit("/", 1)[-1].encode("utf-8"))
        for old, new in renames.items()
    ]
    rewritten: dict[str, bytes] = {}
    for old_name, data in entries.items():
        if old_name.lower().endswith(REFERENCE_SUFFIXES):
            for old, new in replacements:
                data = data.replace(old, new)
        rewritten[renames.get(old_name, old_name)] = data
    return rewritten


def _resolved_reference(source: str, value: str, *, root_relative: bool = False) -> str | None:
    """把 EPUB 内部引用解析为 ZIP POSIX 路径；外部 URL/纯锚点返回 None。"""
    value = unquote(value.strip()).replace("\\", "/")
    if not value or value.startswith("#") or value.startswith("//"):
        return None
    parsed = urlsplit(value)
    if parsed.scheme:
        return None
    path = parsed.path
    if not path:
        return None
    if root_relative or path.startswith("/"):
        return posixpath.normpath(path.lstrip("/"))
    return posixpath.normpath(posixpath.join(posixpath.dirname(source), path))


def artifact_contract_issues(entries: dict[str, bytes], book_id: str) -> list[tuple[str, str]]:
    """校验 EPUB 容器、作品号表头、XML 语法和全部内部资源引用。"""
    book_id = book_id.upper()
    issues: list[tuple[str, str]] = []
    names = set(entries)
    manifest_targets: set[str] = set()

    for name in entries:
        basename = name.rsplit("/", 1)[-1]
        if name.lower().endswith(XHTML_SUFFIXES):
            if basename.casefold() != "nav.xhtml" and not basename.upper().startswith(
                    book_id + "-"):
                issues.append((name, f"XHTML 缺少作品号表头 {book_id}-"))
            sequence_match = re.match(
                rf"^{re.escape(book_id)}-(\d+)(?:_|\.(?:xhtml|html|htm)$)",
                basename,
                re.IGNORECASE,
            )
            if sequence_match and int(sequence_match.group(1)) == 0:
                issues.append((name, "内容序 -00 非法；数字内容序必须从 -01 开始"))
        if name.lower().endswith(IMAGE_SUFFIXES) and not basename.upper().startswith(
                book_id + "-"):
            issues.append((name, f"图片缺少作品号表头 {book_id}-"))

    if "META-INF/container.xml" not in entries:
        issues.append(("EPUB", "缺少 META-INF/container.xml"))

    for name, data in entries.items():
        lower = name.lower()
        if lower.endswith(XML_SUFFIXES):
            try:
                root = ET.fromstring(data)
            except ET.ParseError as exc:
                issues.append((name, f"XML 解析失败：{exc}"))
                continue
            for element in root.iter():
                for raw_attr, raw_value in element.attrib.items():
                    attr = raw_attr.rsplit("}", 1)[-1].casefold()
                    if attr not in {"href", "src", "poster", "full-path"}:
                        continue
                    target = _resolved_reference(
                        name, raw_value, root_relative=(attr == "full-path"))
                    if target is not None and target not in names:
                        issues.append((name, f"资源引用不存在：{raw_value} -> {target}"))
            if lower.endswith(".opf"):
                manifest_ids: dict[str, str] = {}
                for element in root.iter():
                    tag = element.tag.rsplit("}", 1)[-1].casefold()
                    if tag != "item":
                        continue
                    item_id = element.attrib.get("id", "")
                    href = element.attrib.get("href", "")
                    if item_id in manifest_ids:
                        issues.append((name, f"OPF manifest id 重复：{item_id}"))
                    elif item_id:
                        manifest_ids[item_id] = href
                    target = _resolved_reference(name, href)
                    if target is not None:
                        manifest_targets.add(target)
                for element in root.iter():
                    tag = element.tag.rsplit("}", 1)[-1].casefold()
                    if tag == "itemref":
                        idref = element.attrib.get("idref", "")
                        if idref not in manifest_ids:
                            issues.append((name, f"OPF spine idref 不存在于 manifest：{idref}"))
        if lower.endswith(".css"):
            for match in CSS_URL_RE.finditer(data):
                raw_value = match.group(2).decode("utf-8", errors="replace")
                target = _resolved_reference(name, raw_value)
                if target is not None and target not in names:
                    issues.append((name, f"CSS 资源引用不存在：{raw_value} -> {target}"))
    for image_name in sorted(
            candidate for candidate in names
            if candidate.lower().endswith(IMAGE_SUFFIXES)):
        if image_name not in manifest_targets:
            issues.append(("OPF", f"图片未在任何 manifest 声明：{image_name}"))
    return issues


def epub_zip_issues(infos: list[zipfile.ZipInfo], entries: dict[str, bytes]) -> list[tuple[str, str]]:
    """校验 OCF 对 ZIP 容器的基本硬性要求。"""
    issues: list[tuple[str, str]] = []
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        issues.append(("EPUB", "ZIP 中存在重复条目名"))
    if not infos or infos[0].filename != "mimetype":
        issues.append(("EPUB", "mimetype 必须是 ZIP 第一个条目"))
    else:
        if infos[0].compress_type != zipfile.ZIP_STORED:
            issues.append(("mimetype", "mimetype 必须使用 ZIP_STORED，不得压缩"))
        if infos[0].extra:
            issues.append(("mimetype", "mimetype ZIP 条目不得带 extra field"))
    if "mimetype" not in entries:
        issues.append(("EPUB", "缺少 mimetype 条目"))
    elif entries["mimetype"] != b"application/epub+zip":
        issues.append(("mimetype", "内容必须严格为 application/epub+zip"))
    return issues


PB_CSS_SNIPPET = b"""
.pb {
  page-break-before: always;           /* \xe7\x9c\x9f\xe5\x88\x86\xe9\xa1\xb5\xe5\xaa\x92\xe4\xbd\x93\xe7\x9a\x84\xe9\x98\x85\xe8\xaf\xbb\xe5\x99\xa8\xef\xbc\x88\xe6\x89\x93\xe5\x8d\xb0/\xe9\x83\xa8\xe5\x88\x86 iOS\xef\xbc\x89 */
  -webkit-column-break-before: always; /* \xe8\x80\x81 WebKit / calibre \xe8\x87\xaa\xe7\x94\xa8\xe5\x85\xbc\xe5\xae\xb9 */
  break-before: column;                /* \xe5\xbf\x85\xe9\xa1\xbb\xe6\x9c\x80\xe5\x90\x8e\xef\xbc\x9a\xe8\xa6\x86\xe7\x9b\x96\xe4\xb8\x8a\xe9\x9d\xa2\xe5\xb1\x95\xe5\xbc\x80\xe7\x9a\x84 page\xef\xbc\x8cChromium \xe5\xa4\x9a\xe6\xa0\x8f\xe7\x94\x9f\xe6\x95\x88 */
}
"""


def inject_pb_css(entries: dict[str, bytes]) -> None:
    """在 EPUB 的全部 CSS 文件末尾注入 .pb 换页样式规则。"""
    for name, data in list(entries.items()):
        if name.lower().endswith(".css"):
            if b".pb" not in data:
                entries[name] = data.rstrip() + b"\n" + PB_CSS_SNIPPET.lstrip()


def merge_epub_pages(
        entries: dict[str, bytes],
        book_id: str,
        infos: list[zipfile.ZipInfo]) -> tuple[dict[str, bytes], list[zipfile.ZipInfo], list[str]]:
    """在 EPUB 内存条目中执行分页合并：把同一单元的分页合并为单一章节文件，并更新 OPF/NCX/nav。"""
    notes: list[str] = []
    # 收集全部待合并的分页
    page_candidates = []
    for name, data in entries.items():
        if not name.lower().endswith(XHTML_SUFFIXES):
            continue
        basename = name.rsplit("/", 1)[-1]
        m = merge_bw_pages.PAGE_RE.match(basename)
        if m:
            page_candidates.append((int(m.group("page")), name, data))

    if not page_candidates:
        return entries, infos, notes

    # 解析全部页面
    parsed_pages = []
    for _, name, data in sorted(page_candidates):
        text = data.decode("utf-8-sig", errors="replace")
        bom = data.startswith(b"\xef\xbb\xbf")
        pg = merge_bw_pages.parse_page_content(
            name.rsplit("/", 1)[-1], text, bom, "\r\n" in text)
        if pg is not None:
            pg["entry_path"] = name
            parsed_pages.append(pg)

    if not parsed_pages:
        return entries, infos, notes

    units = merge_bw_pages.group_units(parsed_pages, notes)
    if not units:
        return entries, infos, notes

    # 生成合并后的章节文件
    dir_prefix = posixpath.dirname(parsed_pages[0]["entry_path"])
    merged_entries: dict[str, bytes] = {}
    page_to_merged: dict[str, str] = {}  # old_basename -> new_basename
    page_paths_to_remove: set[str] = set()

    for u in units:
        seq = u["sequence"]
        merged_filename = f"{book_id}-{seq:02d}.xhtml"
        merged_path = posixpath.join(dir_prefix, merged_filename) if dir_prefix else merged_filename
        merged_lines = merge_bw_pages.merge_unit(u, notes)
        if merged_lines:
            content_bytes = ("\n".join(merged_lines) + "\n").encode("utf-8")
            merged_entries[merged_path] = content_bytes
            for pg in u["pages"]:
                page_to_merged[pg["name"]] = merged_filename
                page_paths_to_remove.add(pg["entry_path"])

    # 替换 entries 中的分页文件为合并后的章节文件
    new_entries: dict[str, bytes] = {}
    for name, data in entries.items():
        if name in page_paths_to_remove:
            continue
        new_entries[name] = data
    new_entries.update(merged_entries)

    # 更新 OPF 的 manifest 与 spine
    opf_name = next((name for name in new_entries if name.lower().endswith(".opf")), None)
    if opf_name is not None:
        opf_data = new_entries[opf_name].decode("utf-8-sig", errors="replace")
        try:
            # 匹配 manifest 块
            manifest_match = re.search(r"<manifest\b[^>]*>(.*?)</manifest>", opf_data, re.S)
            spine_match = re.search(r"<spine\b[^>]*>(.*?)</spine>", opf_data, re.S)
            if manifest_match and spine_match:
                manifest_content = manifest_match.group(1)
                spine_content = spine_match.group(1)

                old_id_to_unit: dict[str, str] = {}
                manifest_lines = manifest_content.splitlines(keepends=True)
                new_manifest_lines = []
                for line in manifest_lines:
                    m = re.search(r'<item\b([^>]*)/?>', line, re.I)
                    if m:
                        attrs = m.group(1)
                        id_m = re.search(r'\bid="([^"]+)"', attrs, re.I)
                        href_m = re.search(r'\bhref="([^"]+)"', attrs, re.I)
                        if id_m and href_m:
                            item_id = id_m.group(1)
                            href_base = href_m.group(1).rsplit("/", 1)[-1]
                            if href_base in page_to_merged:
                                target_merged = page_to_merged[href_base]
                                unit_stem = target_merged.rsplit(".", 1)[0]
                                old_id_to_unit[item_id] = unit_stem
                                continue
                    new_manifest_lines.append(line)

                # 添加合并后的章节 item
                added_items = []
                xhtml_subdir = posixpath.relpath(dir_prefix, posixpath.dirname(opf_name)) if dir_prefix else ""
                for u in units:
                    seq = u["sequence"]
                    unit_id = f"{book_id}-{seq:02d}"
                    unit_filename = f"{unit_id}.xhtml"
                    unit_href = f"{xhtml_subdir}/{unit_filename}" if xhtml_subdir and xhtml_subdir != "." else unit_filename
                    added_items.append(
                        f'    <item id="{unit_id}" href="{unit_href}" media-type="application/xhtml+xml"/>\n')

                new_manifest_str = "".join(new_manifest_lines) + "".join(added_items)
                opf_data = opf_data[:manifest_match.start(1)] + new_manifest_str + opf_data[manifest_match.end(1):]

                # 更新 spine 块
                spine_match = re.search(r"<spine\b[^>]*>(.*?)</spine>", opf_data, re.S)
                if spine_match:
                    spine_lines = spine_match.group(1).splitlines(keepends=True)
                    new_spine_lines = []
                    seen_units_in_spine: set[str] = set()
                    for line in spine_lines:
                        m = re.search(r'<itemref\b[^>]*idref="([^"]+)"', line, re.I)
                        if m:
                            idref = m.group(1)
                            if idref in old_id_to_unit:
                                unit_id = old_id_to_unit[idref]
                                if unit_id not in seen_units_in_spine:
                                    seen_units_in_spine.add(unit_id)
                                    new_spine_lines.append(f'    <itemref idref="{unit_id}"/>\n')
                                continue
                        new_spine_lines.append(line)

                    new_spine_str = "".join(new_spine_lines)
                    opf_data = opf_data[:spine_match.start(1)] + new_spine_str + opf_data[spine_match.end(1):]

                new_entries[opf_name] = opf_data.encode("utf-8")
        except Exception as exc:
            notes.append(f"[OPF更新警告] {exc}")

    # 同步更新 XML / NCX / nav / CSS 中的文件引用
    replacements = [
        (old.encode("utf-8"), new.encode("utf-8"))
        for old, new in page_to_merged.items()
    ]
    for name in list(new_entries):
        if name != opf_name and name.lower().endswith(REFERENCE_SUFFIXES):
            data = new_entries[name]
            for old, new in replacements:
                data = data.replace(old, new)
            new_entries[name] = data

    # 更新 infos
    new_infos = []
    for info in infos:
        if info.filename in page_paths_to_remove:
            continue
        new_infos.append(info)
    for merged_path in merged_entries:
        merged_info = zipfile.ZipInfo(merged_path)
        merged_info.compress_type = zipfile.ZIP_DEFLATED
        new_infos.append(merged_info)

    return new_entries, new_infos, notes


def process_epub(epub_path: Path, rules: list[dict], out_path: Path,
                 dry_run: bool, book_id: str | None = None,
                 page_map: dict[str, int | None] | None = None,
                 merge_pages: bool = True) -> dict:
    """处理 .epub：解包改写、分页合并后重新打包。返回统计 dict。"""
    with zipfile.ZipFile(epub_path) as zin:
        infos = zin.infolist()
        entries = {i.filename: zin.read(i.filename) for i in infos}
    stats = {"total": 0, "changed": 0, "renamed": 0,
             "renamed_xhtml": 0, "renamed_images": 0,
             "content": 0, "issues": []}
    stats["issues"].extend(epub_zip_issues(infos, entries))
    for name in entries:
        if name.lower().endswith(XHTML_SUFFIXES):
            stats["total"] += 1
            new_data, ch = transform_bytes(entries[name], rules)
            if ch:
                stats["changed"] += 1
            # dry-run 也必须在内存中基于转换结果分配表头和执行完整验证。
            entries[name] = new_data
            if is_content(new_data.decode("utf-8-sig", errors="replace")):
                stats["content"] += 1
            issues = verify_text(new_data.decode("utf-8-sig", errors="replace"))
            for it in issues:
                stats["issues"].append((name, it))
    renames = pairing_header_renames(entries, book_id, page_map) if book_id else {}
    stats["renamed"] = len(renames)
    stats["renamed_xhtml"] = sum(
        name.lower().endswith(XHTML_SUFFIXES) for name in renames)
    stats["renamed_images"] = sum(
        name.lower().endswith(IMAGE_SUFFIXES) for name in renames)
    if renames:
        entries = apply_entry_renames(entries, renames)
        new_infos = []
        for info in infos:
            new_name = renames.get(info.filename, info.filename)
            new_info = zipfile.ZipInfo(new_name, date_time=info.date_time)
            new_info.compress_type = info.compress_type
            new_info.external_attr = info.external_attr
            new_info.comment = info.comment
            new_info.extra = info.extra
            new_infos.append(new_info)
        infos = new_infos

    if book_id and merge_pages:
        entries, infos, merge_notes = merge_epub_pages(entries, book_id, infos)
        stats["merge_notes"] = merge_notes
        inject_pb_css(entries)

    if book_id:
        stats["issues"].extend(artifact_contract_issues(entries, book_id))
    if dry_run:
        return stats
    if stats["issues"]:
        stats["blocked"] = True
        return stats
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w") as zout:
        for info in infos:
            data = entries[info.filename]
            new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new_info.compress_type = (
                zipfile.ZIP_STORED
                if info.filename == "mimetype" or info.compress_type == zipfile.ZIP_STORED
                else zipfile.ZIP_DEFLATED)
            new_info.external_attr = info.external_attr
            new_info.comment = info.comment
            new_info.extra = info.extra
            zout.writestr(new_info, data)
    return stats


def process_dir(dir_path: Path, rules: list[dict], dry_run: bool) -> dict:
    """就地处理目录下全部 XHTML。返回统计 dict。"""
    files = sorted(p for p in dir_path.rglob("*")
                   if p.is_file() and p.suffix.lower() in XHTML_SUFFIXES)
    stats = {"total": 0, "changed": 0, "renamed": 0,
             "content": 0, "issues": []}
    for p in files:
        stats["total"] += 1
        data = p.read_bytes()
        new_data, ch = transform_bytes(data, rules)
        text = new_data.decode("utf-8-sig", errors="replace")
        if is_content(text):
            stats["content"] += 1
        if ch:
            stats["changed"] += 1
            if not dry_run:
                p.write_bytes(new_data)
        for it in verify_text(text):
            stats["issues"].append((p.name, it))
    return stats


def check_dir(dir_path: Path, rules: list[dict]) -> dict:
    """--check：内存中应用规则并校验 L1-L6 固定模板，不写盘。"""
    files = sorted(p for p in dir_path.rglob("*")
                   if p.is_file() and p.suffix.lower() in XHTML_SUFFIXES)
    stats = {"total": 0, "content": 0, "issues": []}
    for p in files:
        stats["total"] += 1
        text = apply_rules(
            p.read_bytes().decode("utf-8-sig", errors="replace"), rules)
        if is_content(text):
            stats["content"] += 1
            for it in template_issues(text.splitlines()):
                stats["issues"].append((p.name, it))
    return stats


def check_epub(
        epub_path: Path, rules: list[dict], book_id: str | None = None,
        page_map: dict[str, int | None] | None = None,
        merge_pages: bool = True) -> dict:
    """--check：在内存中模拟全部转换与分页合并，再校验模板与 EPUB 产物契约。"""
    with zipfile.ZipFile(epub_path) as zin:
        infos = zin.infolist()
        entries = {info.filename: zin.read(info.filename) for info in infos}
        stats = {"total": 0, "content": 0, "renamed": 0,
                 "renamed_xhtml": 0, "renamed_images": 0, "issues": []}
        stats["issues"].extend(epub_zip_issues(infos, entries))
        for info in infos:
            if not info.filename.lower().endswith(XHTML_SUFFIXES):
                continue
            stats["total"] += 1
            new_data, _ = transform_bytes(entries[info.filename], rules)
            entries[info.filename] = new_data
            text = new_data.decode("utf-8-sig", errors="replace")
            if is_content(text):
                stats["content"] += 1
                for it in template_issues(text.splitlines()):
                    stats["issues"].append((info.filename, it))
        renames = pairing_header_renames(entries, book_id, page_map) if book_id else {}
        stats["renamed"] = len(renames)
        stats["renamed_xhtml"] = sum(
            name.lower().endswith(XHTML_SUFFIXES) for name in renames)
        stats["renamed_images"] = sum(
            name.lower().endswith(IMAGE_SUFFIXES) for name in renames)
        if renames:
            entries = apply_entry_renames(entries, renames)
            new_infos = []
            for info in infos:
                new_name = renames.get(info.filename, info.filename)
                new_info = zipfile.ZipInfo(new_name, date_time=info.date_time)
                new_info.compress_type = info.compress_type
                new_info.external_attr = info.external_attr
                new_info.comment = info.comment
                new_info.extra = info.extra
                new_infos.append(new_info)
            infos = new_infos

        if book_id and merge_pages:
            entries, infos, merge_notes = merge_epub_pages(entries, book_id, infos)
            stats["merge_notes"] = merge_notes
            inject_pb_css(entries)

        if book_id:
            stats["issues"].extend(artifact_contract_issues(entries, book_id))
        return stats


def clean_book_title(raw_title: str, book_id: str | None = None) -> str:
    """清理下载站噪声，并严格对齐 OneDrive\\某系列\\日文原文 既有命名格式。"""
    title = raw_title
    # 移除下载站等括号
    title = re.sub(r"\([^\)]*(?:z-library|1lib|libgen|z-lib)[^\)]*\)", "", title, flags=re.I)
    # 移除出版文库括号
    title = re.sub(r"\([^\)]*(?:電撃文庫|角川|MF文庫|スニーカー文庫)[^\)]*\)", "", title, flags=re.I)
    # 移除作者/插画括号
    title = re.sub(r"\([^\)]*(?:鎌池|はいむら|ニリツ|冬川|近木)[^\)]*\)", "", title, flags=re.I)
    title = re.sub(r"\.preprocessed", "", title, flags=re.I)
    # 移除已有的 [S...] 前缀
    title = re.sub(r"^\[S\d+[^\]]*\]\s*", "", title.strip(), flags=re.I)
    # 压缩多余空格
    title = re.sub(r"\s+", " ", title).strip()

    if book_id:
        m = re.match(r"^S(\d+)_(\d+)", book_id, re.I)
        if m:
            series_num, vol_num = int(m.group(1)), int(m.group(2))
            if series_num == 4:
                return f"とある暗部の少女共棲({vol_num})"
            elif series_num == 3:
                return f"創約 とある魔術の禁書目録({vol_num:02d})"
            elif series_num == 2:
                return f"新約 とある魔術の禁書目録({vol_num:02d})"
            elif series_num == 1:
                return f"とある魔術の禁書目録({vol_num:02d})"
    return title


def report_stats(label: str, stats: dict, dry_run: bool, check: bool,
                 out=None) -> None:
    non_content = stats["total"] - stats["content"]
    base = (f"XHTML {stats['total']} 个：内容 {stats['content']}，"
            f"非内容 {non_content}")
    if not check:
        base += f"；改写 {stats['changed']}"
        if stats.get("renamed"):
            base += (f"；表头重命名 {stats['renamed']}"
                     f"（XHTML {stats.get('renamed_xhtml', 0)}，"
                     f"图片 {stats.get('renamed_images', 0)}）")
    elif stats.get("renamed"):
        base += (f"；内存模拟表头重命名 {stats['renamed']}"
                 f"（XHTML {stats.get('renamed_xhtml', 0)}，"
                 f"图片 {stats.get('renamed_images', 0)}）")
    if check:
        base += "（校验，未写盘）"
    elif dry_run:
        base += "（预览，未写盘）"
    elif out and not stats.get("blocked"):
        base += f"（输出：{out}）"
    if stats.get("blocked"):
        base += "（验证失败，已阻止写盘）"
    print(f"[{label}] {base}")
    for name, it in stats["issues"][:30]:
        print(f"  ! {name}: {it}")
    if len(stats["issues"]) > 30:
        print(f"  …另有 {len(stats['issues']) - 30} 条问题未列出")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="按 BookWalker 提取预处理规则改写 .epub / 目录中的 XHTML")
    ap.add_argument("paths", nargs="+", help="一个或多个 .epub 文件或含 .xhtml 的目录")
    ap.add_argument("--rules", type=Path, default=None,
                    help=f"规则 JSON 路径（默认脚本同目录 {DEFAULT_RULES_JSON}）")
    ap.add_argument("--book-id", default=None,
                    help="显式作品号（如 S4_05）；为 EPUB 内 XHTML/图片分配表头并更新引用")
    ap.add_argument("--header-map", type=Path, default=None,
                    help=f"已审计分页映射 JSON（默认 {DEFAULT_HEADER_MAP_JSON}）")
    ap.add_argument("--out", type=Path, default=None,
                    help="epub 模式输出目录（默认写在源文件同目录）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写文件")
    ap.add_argument("--check", action="store_true",
                    help="内存校验 L1-L6；配合 --book-id 检查完整 EPUB 产物契约")
    args = ap.parse_args()

    if args.book_id and not BOOK_ID_RE.fullmatch(args.book_id):
        ap.error(f"--book-id 不是有效作品号：{args.book_id}")
    if args.book_id and any(Path(raw).is_dir() for raw in args.paths):
        ap.error("--book-id 当前只支持 .epub 输入；目录模式请先打包或人工重命名")
    if args.header_map and not args.book_id:
        ap.error("--header-map 必须与 --book-id 同时使用")

    rules = load_rules(args.rules)
    page_map = load_header_map(args.book_id, args.header_map)
    print(f"加载规则：{len(rules)} 条（{args.rules or DEFAULT_RULES_JSON}）")
    for r in rules:
        print(f"  - {r['name']}")
    if page_map is not None:
        wrapper_count = sum(sequence is None for sequence in page_map.values())
        print(f"加载已审计分页映射：{args.book_id.upper()}，正文分页 "
              f"{len(page_map) - wrapper_count}，包装分页 {wrapper_count}")

    has_issues = False
    for raw in args.paths:
        stats = None
        p = Path(raw)
        if not p.exists():
            print(f"[跳过] 不存在：{p}")
            continue
        if p.is_dir():
            if args.check:
                stats = check_dir(p, rules)
                report_stats(f"目录 {p}", stats, False, True)
            else:
                stats = process_dir(p, rules, args.dry_run)
                report_stats(f"目录 {p}", stats, args.dry_run, False)
        elif p.is_file() and p.suffix.lower() == ".epub":
            if args.check:
                stats = check_epub(p, rules, args.book_id, page_map)
                report_stats(f"epub {p}", stats, False, True)
            else:
                target_dir = args.out if args.out and args.out.is_dir() else (args.out.parent if args.out and not args.out.is_dir() else p.parent)
                if args.out is None or args.out.is_dir():
                    if args.book_id:
                        clean_title = clean_book_title(p.stem)
                        out = target_dir / f"[{args.book_id}]{clean_title}.epub"
                    else:
                        out = target_dir / (p.stem + ".preprocessed" + p.suffix)
                else:
                    out = args.out
                stats = process_epub(
                    p, rules, out, args.dry_run, args.book_id, page_map)
                report_stats(f"epub {p}", stats, args.dry_run, False,
                             None if args.dry_run else out)
        else:
            print(f"[跳过] 不是 .epub 或目录：{p}")
        if stats is not None and stats.get("issues"):
            has_issues = True
    return 1 if has_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
