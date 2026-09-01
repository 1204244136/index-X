from __future__ import annotations

import argparse
import fnmatch
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

DEFAULT_CACHE = (
    Path(__file__).resolve().parents[1] / ".cache" / "epub-work" / "chinese-text"
)
HEADING_RE = re.compile(
    r"<(?P<tag>h[12])\b[^>]*>.*?</(?P=tag)>", re.I | re.S
)
HEADING_LINE_RE = re.compile(
    r"^(?P<indent>\s*)<(?P<tag>h[12])(?P<attrs>[^>]*)>"
    r"(?P<inner>.*)</(?P=tag)>(?P<trail>\s*)$",
    re.I,
)
DIV_RE = re.compile(r"^<div\b(?P<attrs>[^>]*)>(?P<inner>.*)</div>$", re.I | re.S)
SPAN_RE = re.compile(r"<span\b(?P<attrs>[^>]*)>(?P<inner>.*?)</span>", re.I | re.S)
FULL_SPAN_RE = re.compile(
    r"^<span\b(?P<attrs>[^>]*)>(?P<inner>.*)</span>$", re.I | re.S
)
FULL_SUP_RE = re.compile(r"^<sup\b[^>]*>.*</sup>$", re.I | re.S)
BR_RE = re.compile(r"<br\s*/?>", re.I)
TRAILING_BR_RE = re.compile(r"\s*<br\s*/?>\s*$", re.I)
LINK_CSS_RE = re.compile(
    r"<link\b[^>]*\bhref\s*=\s*([\"'])(?P<href>[^\"']+\.css(?:[?#][^\"']*)?)\1",
    re.I,
)
CLASS_RE = re.compile(r"(?P<prefix>\sclass\s*=\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)", re.I)
HEADING_CSS = (
    ".heading-lines > .heading-main,\n"
    ".heading-lines > .heading-subtitle,\n"
    ".heading-lines > .heading-code {\n"
    "  display: block;\n"
    "}\n"
)


class MigrationError(ValueError):
    pass


@dataclass(frozen=True)
class HeadingResult:
    line: str
    kind: str
    layered: bool
    layers: tuple[str, ...]


@dataclass
class BookPlan:
    book: Path
    changes: dict[Path, bytes] = field(default_factory=dict)
    originals: dict[Path, bytes] = field(default_factory=dict)
    kinds: Counter[str] = field(default_factory=Counter)
    xhtml_files: set[Path] = field(default_factory=set)
    css_files: set[Path] = field(default_factory=set)

    @property
    def heading_count(self) -> int:
        return sum(self.kinds.values())


def add_class(attrs: str, class_name: str) -> str:
    match = CLASS_RE.search(attrs)
    if not match:
        return f'{attrs} class="{class_name}"'
    classes = match.group("value").split()
    if class_name in classes:
        return attrs
    value = " ".join([class_name, *classes])
    return f"{attrs[:match.start('value')]}{value}{attrs[match.end('value'):]}"


def fragment_text(fragment: str) -> str:
    try:
        root = ET.fromstring(f"<root>{fragment}</root>")
    except ET.ParseError as exc:
        raise MigrationError(f"标题片段不是有效 XML：{exc}") from exc
    return "".join(root.itertext()).strip()


def strip_terminal_br(fragment: str, *, required: bool) -> str:
    cleaned, count = TRAILING_BR_RE.subn("", fragment, count=1)
    if required and count != 1:
        raise MigrationError("标题层之间缺少预期的尾随 <br/>")
    if BR_RE.search(cleaned):
        raise MigrationError("标题层中存在非尾随或多个 <br/>")
    return cleaned.rstrip()


def render_span(attrs: str, inner: str, role: str) -> str:
    return f"<span{add_class(attrs, role)}>{inner}</span>"


def nested_components(inner: str) -> list[tuple[str, str]] | None:
    div = DIV_RE.fullmatch(inner)
    if not div:
        return None
    if not re.search(r"\btext-align\s*:\s*center\b", div.group("attrs"), re.I):
        raise MigrationError("只支持 text-align:center 的历史标题 div")

    body = div.group("inner")
    matches = list(SPAN_RE.finditer(body))
    if len(matches) not in {2, 3}:
        raise MigrationError("历史标题 div 必须只含 2 或 3 个直接 span")
    cursor = 0
    for match in matches:
        if body[cursor:match.start()].strip():
            raise MigrationError("历史标题 div 的 span 之间含有未知内容")
        cursor = match.end()
    if body[cursor:].strip():
        raise MigrationError("历史标题 div 尾部含有未知内容")
    return [(match.group("attrs"), match.group("inner")) for match in matches]


def migrate_nested(
    tag: str, attrs: str, inner: str, indent: str, trail: str
) -> HeadingResult | None:
    components = nested_components(inner)
    if components is None:
        return None

    roles = ["heading-main", "heading-subtitle"]
    if len(components) == 3:
        roles.append("heading-code")
    rendered: list[str] = []
    layers: list[str] = []
    for index, ((span_attrs, span_inner), role) in enumerate(zip(components, roles)):
        cleaned = strip_terminal_br(span_inner, required=index < len(components) - 1)
        text = fragment_text(cleaned)
        if not text:
            raise MigrationError("标题层为空")
        layers.append(text)
        rendered.append(render_span(span_attrs, cleaned, role))

    outer_attrs = add_class(attrs, "heading-lines")
    line = f"{indent}<{tag}{outer_attrs}>{''.join(rendered)}</{tag}>{trail}"
    return HeadingResult(line, f"layered-{len(components)}", True, tuple(layers))


def migrate_direct(
    tag: str, attrs: str, inner: str, indent: str, trail: str
) -> HeadingResult:
    breaks = list(BR_RE.finditer(inner))
    if not breaks:
        raise MigrationError("标题中没有 <br/>")
    first = breaks[0]
    main = inner[:first.start()].rstrip()
    rest = inner[first.end():].lstrip()
    if BR_RE.search(main):
        raise MigrationError("主标题中存在未知 <br/> 结构")

    if not rest.strip():
        text = fragment_text(main)
        if not text:
            raise MigrationError("删除尾随 <br/> 后标题为空")
        line = f"{indent}<{tag}{attrs}>{main}</{tag}>{trail}"
        return HeadingResult(line, "trailing-noise", False, (text,))

    main_text = fragment_text(main)
    if not main_text:
        raise MigrationError("多层标题的主标题为空")

    span = FULL_SPAN_RE.fullmatch(rest)
    if span:
        sub_inner = strip_terminal_br(span.group("inner"), required=False)
        class_match = CLASS_RE.search(span.group("attrs"))
        existing_classes = f" {class_match.group('value') if class_match else ''} "
        role = "heading-code" if " font06 " in existing_classes else "heading-subtitle"
        secondary = render_span(span.group("attrs"), sub_inner, role)
        secondary_text = fragment_text(sub_inner)
    elif FULL_SUP_RE.fullmatch(rest):
        if BR_RE.search(rest):
            raise MigrationError("sup 标题层中存在未知 <br/> 结构")
        role = "heading-code"
        secondary = render_span("", rest.rstrip(), role)
        secondary_text = fragment_text(rest)
    elif "<" not in rest and ">" not in rest:
        rest = strip_terminal_br(rest, required=False)
        role = "heading-subtitle"
        secondary = render_span("", rest, role)
        secondary_text = fragment_text(rest)
    else:
        raise MigrationError("直接内嵌标题的次级结构不在白名单中")

    if not secondary_text:
        raise MigrationError("多层标题的次级标题为空")
    if len(breaks) > 1 and BR_RE.search(secondary):
        raise MigrationError("次级标题仍含 <br/>")

    outer_attrs = add_class(attrs, "heading-lines")
    main_span = render_span("", main, "heading-main")
    line = f"{indent}<{tag}{outer_attrs}>{main_span}{secondary}</{tag}>{trail}"
    return HeadingResult(line, f"direct-{role.removeprefix('heading-')}", True, (main_text, secondary_text))


def migrate_heading_line(line: str) -> HeadingResult:
    match = HEADING_LINE_RE.fullmatch(line)
    if not match or not BR_RE.search(match.group("inner")):
        raise MigrationError("内嵌 <br/> 的 h1/h2 必须独占一行")
    tag = match.group("tag")
    attrs = match.group("attrs")
    inner = match.group("inner")
    result = migrate_nested(
        tag, attrs, inner, match.group("indent"), match.group("trail")
    ) or migrate_direct(tag, attrs, inner, match.group("indent"), match.group("trail"))

    if BR_RE.search(result.line):
        raise MigrationError("迁移后的标题仍含 <br/>")
    try:
        ET.fromstring(result.line.strip())
    except ET.ParseError as exc:
        raise MigrationError(f"迁移后的标题不是有效 XML：{exc}") from exc
    return result


def read_xhtml_lines(path: Path) -> tuple[list[str], bool, bool, bool]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    return text.splitlines(), bom, "\r\n" in text, text.endswith(("\r", "\n"))


def encode_lines(
    lines: list[str], bom: bool, crlf: bool, terminal_newline: bool
) -> bytes:
    separator = "\r\n" if crlf else "\n"
    text = separator.join(lines) + (separator if terminal_newline else "")
    result = text.encode("utf-8")
    return b"\xef\xbb\xbf" + result if bom else result


def heading_break_count(source: str) -> int:
    return sum(bool(BR_RE.search(match.group(0))) for match in HEADING_RE.finditer(source))


def css_path_for(xhtml: Path, lines: list[str], book: Path) -> Path:
    candidates: list[Path] = []
    for line in lines:
        for match in LINK_CSS_RE.finditer(line):
            href = unquote(urlsplit(match.group("href")).path)
            candidate = (xhtml.parent / Path(href.replace("/", os.sep))).resolve()
            try:
                candidate.relative_to(book.resolve())
            except ValueError as exc:
                raise MigrationError(f"CSS 引用越出书籍目录：{href}") from exc
            if candidate.is_file():
                candidates.append(candidate)
    if not candidates:
        raise MigrationError("多层标题文件没有可用的 CSS 引用")
    preferred = [path for path in candidates if path.name.casefold() == "style.css"]
    return preferred[0] if preferred else candidates[0]


def append_heading_css(raw: bytes) -> bytes:
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    if re.search(r"\.heading-lines\b", text):
        return raw
    separator = "\r\n" if "\r\n" in text else "\n"
    normalized_rule = HEADING_CSS.replace("\n", separator)
    prefix = text
    if not prefix.endswith(separator):
        prefix += separator
    if not prefix.endswith(separator * 2):
        prefix += separator
    combined = f"{prefix}{normalized_rule}"
    encoded = combined.encode("utf-8")
    return b"\xef\xbb\xbf" + encoded if bom else encoded


def plan_book(book: Path) -> BookPlan | None:
    plan = BookPlan(book)
    for xhtml in sorted(book.rglob("*.xhtml")):
        lines, bom, crlf, terminal_newline = read_xhtml_lines(xhtml)
        source = "\n".join(lines)
        expected = heading_break_count(source)
        if not expected:
            continue

        transformed = list(lines)
        found = 0
        layered = False
        for index, line in enumerate(lines):
            if not re.search(r"<h[12]\b[^>]*>.*<br\s*/?>", line, re.I):
                continue
            try:
                result = migrate_heading_line(line)
            except MigrationError as exc:
                raise MigrationError(f"{xhtml.relative_to(book)}:{index + 1}: {exc}") from exc
            transformed[index] = result.line
            found += 1
            layered = layered or result.layered
            plan.kinds[result.kind] += 1

        if found != expected:
            raise MigrationError(
                f"{xhtml.relative_to(book)}: 发现 {expected} 个标题块，但只能安全迁移 {found} 个"
            )
        if heading_break_count("\n".join(transformed)):
            raise MigrationError(f"{xhtml.relative_to(book)}: 迁移后仍有标题内嵌 <br/>")

        original = xhtml.read_bytes()
        updated = encode_lines(transformed, bom, crlf, terminal_newline)
        if updated != original:
            plan.originals[xhtml] = original
            plan.changes[xhtml] = updated
            plan.xhtml_files.add(xhtml)
        if layered:
            css = css_path_for(xhtml, lines, book)
            if css not in plan.originals:
                raw_css = css.read_bytes()
                updated_css = append_heading_css(raw_css)
                if updated_css != raw_css:
                    plan.originals[css] = raw_css
                    plan.changes[css] = updated_css
                    plan.css_files.add(css)

    return plan if plan.heading_count else None


def atomic_write(path: Path, data: bytes) -> None:
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def apply_book(plan: BookPlan) -> None:
    written: list[Path] = []
    try:
        for path in sorted(plan.changes):
            atomic_write(path, plan.changes[path])
            written.append(path)
    except OSError:
        for path in reversed(written):
            atomic_write(path, plan.originals[path])
        raise


def selected_books(cache: Path, patterns: list[str]) -> list[Path]:
    books = sorted(path for path in cache.iterdir() if path.is_dir())
    if not patterns:
        return books
    folded = [pattern.casefold() for pattern in patterns]
    return [
        book
        for book in books
        if any(fnmatch.fnmatch(book.name.casefold(), pattern) for pattern in folded)
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将中文缓存中历史 h1/h2 内嵌 <br/> 迁移为语义标题层。"
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE,
        help="中文缓存根目录（默认 .cache/epub-work/chinese-text）",
    )
    parser.add_argument(
        "--book",
        action="append",
        default=[],
        metavar="GLOB",
        help="只处理书籍目录名匹配的 glob；可重复指定",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="写入缓存；不指定时只预览",
    )
    parser.add_argument("--verbose", action="store_true", help="列出每本书的统计")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cache = args.cache.resolve()
    if not cache.is_dir():
        print(f"缓存目录不存在：{cache}")
        return 2

    books = selected_books(cache, args.book)
    if args.book and not books:
        print("没有书籍匹配 --book")
        return 2

    plans: list[BookPlan] = []
    errors: list[str] = []
    for book in books:
        try:
            plan = plan_book(book)
        except (MigrationError, UnicodeError, OSError) as exc:
            errors.append(f"{book.name}: {exc}")
            continue
        if plan:
            plans.append(plan)

    if errors:
        print("迁移预检失败；没有写入任何书籍：")
        for error in errors:
            print(f"  - {error}")
        return 1

    if args.apply:
        for plan in plans:
            apply_book(plan)

    totals: Counter[str] = Counter()
    for plan in plans:
        totals.update(plan.kinds)
        if args.verbose:
            print(
                f"{plan.book.name}: 标题 {plan.heading_count}，"
                f"XHTML {len(plan.xhtml_files)}，CSS {len(plan.css_files)}"
            )
    mode = "已应用" if args.apply else "预览"
    print(
        f"{mode}：书籍 {len(plans)}，标题 {sum(totals.values())}，"
        f"XHTML {sum(len(plan.xhtml_files) for plan in plans)}，"
        f"CSS {sum(len(plan.css_files) for plan in plans)}"
    )
    if totals:
        print("类型：" + "，".join(f"{key}={value}" for key, value in sorted(totals.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
