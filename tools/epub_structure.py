"""Shared EPUB container, XML, naming and resource contracts (read-only)."""
from __future__ import annotations

import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlsplit
from alignment_rules import JP_WRAPPER_RE

XHTML_SUFFIXES = (".xhtml", ".html", ".htm")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".svg", ".tif", ".tiff")
XML_SUFFIXES = XHTML_SUFFIXES + (".opf", ".ncx", ".xml", ".svg")
CSS_URL_RE = re.compile(rb"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)

def resolve_reference(source: str, value: str, *, root_relative: bool = False) -> str | None:
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


def artifact_contract_issues(entries: dict[str, bytes], book_id: str | None) -> list[tuple[str, str]]:
    """校验 EPUB 容器、作品号表头、XML 语法和全部内部资源引用。"""
    book_id = book_id.upper() if book_id else None
    issues: list[tuple[str, str]] = []
    names = set(entries)
    manifest_targets: set[str] = set()

    for name in entries:
        basename = name.rsplit("/", 1)[-1]
        if name.lower().endswith(XHTML_SUFFIXES):
            if (book_id and basename.casefold() != "nav.xhtml"
                    and not JP_WRAPPER_RE.match(basename)
                    and not basename.upper().startswith(book_id + "-")):
                issues.append((name, f"XHTML 缺少作品号表头 {book_id}-"))
            sequence_match = re.match(
                rf"^{re.escape(book_id or '')}-(\d+)(?:_|\.(?:xhtml|html|htm)$)",
                basename,
                re.IGNORECASE,
            )
            if sequence_match and int(sequence_match.group(1)) == 0:
                issues.append((name, "内容序 -00 非法；数字内容序必须从 -01 开始"))
        if book_id and name.lower().endswith(IMAGE_SUFFIXES) and not basename.upper().startswith(
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
                    target = resolve_reference(
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
                    target = resolve_reference(name, href)
                    if target is not None:
                        manifest_targets.add(target)
                for element in root.iter():
                    tag = element.tag.rsplit("}", 1)[-1].casefold()
                    if tag == "itemref":
                        idref = element.attrib.get("idref", "")
                        if idref not in manifest_ids:
                            issues.append((name, f"OPF spine idref 不存在于 manifest：{idref}"))
        if lower.endswith(".css"):
            css = re.sub(rb"/\*.*?\*/", b"", data, flags=re.S)
            values = [match.group(2).decode("utf-8") for match in CSS_URL_RE.finditer(css)]
            values += re.findall(r"@import\s+['\"]([^'\"]+)['\"]", css.decode("utf-8"), re.I)
            for raw_value in values:
                target = resolve_reference(name, raw_value)
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


def container_contract_issues(entries: dict[str, bytes]) -> list[tuple[str, str]]:
    """Validate rootfiles and the OPF manifest/spine before packaging."""
    issues: list[tuple[str, str]] = []
    if entries.get("mimetype") != b"application/epub+zip":
        issues.append(("mimetype", "内容必须严格为 application/epub+zip"))
    try:
        container = ET.fromstring(entries["META-INF/container.xml"])
    except (KeyError, ET.ParseError) as exc:
        return issues + [("META-INF/container.xml", f"无效容器：{exc}")]
    rootfiles = [e for e in container.iter() if e.tag.rsplit("}", 1)[-1] == "rootfile"]
    if not rootfiles:
        issues.append(("META-INF/container.xml", "容器未声明 OPF rootfile"))
    for rootfile in rootfiles:
        name = rootfile.get("full-path", "")
        if not name or name.startswith("/") or ".." in name.split("/") or "\\" in name:
            issues.append(("META-INF/container.xml", f"不安全或空 rootfile：{name}"))
            continue
        try:
            opf = ET.fromstring(entries[name])
        except (KeyError, ET.ParseError) as exc:
            issues.append((name, f"无法解析 OPF：{exc}"))
            continue
        local = lambda tag: tag.rsplit("}", 1)[-1]
        if local(opf.tag) != "package":
            issues.append((name, "rootfile 不是 OPF package"))
        manifest = next((e for e in opf if local(e.tag) == "manifest"), None)
        spine = next((e for e in opf if local(e.tag) == "spine"), None)
        items = [] if manifest is None else [e for e in manifest if local(e.tag) == "item"]
        refs = [] if spine is None else [e for e in spine if local(e.tag) == "itemref"]
        if not items or not refs:
            issues.append((name, "OPF 缺少非空 manifest/spine"))
        ids: dict[str, str] = {}
        for item in items:
            item_id, href = item.get("id", ""), item.get("href", "")
            if not item_id or item_id in ids or not href or not item.get("media-type"):
                issues.append((name, f"无效或重复 manifest item：{item_id}"))
            ids[item_id] = item.get("media-type", "")
            target = resolve_reference(name, href)
            if target is None or target not in entries:
                issues.append((name, f"manifest 资源不存在：{href}"))
        for ref in refs:
            idref = ref.get("idref", "")
            if ids.get(idref) not in {"application/xhtml+xml", "image/svg+xml"}:
                issues.append((name, f"spine 引用不存在或不是内容文档：{idref}"))
    return issues

