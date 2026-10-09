"""Check local documentation links, tool cluster contracts and single-source rules."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]\n]+\]\((<[^>]+>|[^)\n]+)\)")
TOOL_FILE = re.compile(r"`([A-Za-z0-9_.-]+\.(?:py|ps1|json))`")
TOOL_NAME = re.compile(r"([A-Za-z0-9_.-]+\.(?:py|ps1|json))")
BACKTICK_SPAN = re.compile(r"`([^`]+)`")
# 活跃文档开头允许回指文档索引的最大行范围（现有文档均在 10 行以内）
BACK_POINTER_HEAD_LINES = 20

# ── 工具簇合同：tools/README.md 的结构必须自洽，缺结构即报错而不是静默跳过 ──
CLUSTER_SECTION = re.compile(r"^(C\d+)\s+(\S.*)$")
MEMBER_COLUMNS = ("工具", "入口命令", "读写范围", "门禁与失败边界", "测试")
PLAN_MARK = re.compile(r"【(P\d+|无)】")
PLAN_ROW = re.compile(r"^P\d+$")
INDEX_COUNT = re.compile(r"^\d+$")
CLI_COMMAND = re.compile(r"`(?:python |\./tools/)")
INDEX_SECTION = "簇索引"
ROUTER_SECTION = "路由"
PLAN_SECTION = "阻塞与恢复"


def prose(text: str) -> str:
    # Preserve line numbers while excluding examples inside fenced code blocks.
    fenced = False
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*(`{3,}|~{3,})", line):
            fenced = not fenced
            lines.append("")
        else:
            lines.append("" if fenced else line)
    return "\n".join(lines)


def anchors(text: str) -> set[str]:
    result: set[str] = set()
    counts: dict[str, int] = {}
    for line in prose(text).splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        heading = re.sub(r"<[^>]+>", "", match.group(1)).lower()
        slug = re.sub(r"[^\w\s-]", "", heading).replace(" ", "-")
        number = counts.get(slug, 0)
        counts[slug] = number + 1
        result.add(f"{slug}-{number}" if number else slug)
    result.update(re.findall(r'\bid\s*=\s*[\'"]([^\'"]+)[\'"]', text))
    return result


def audit(root: Path) -> list[str]:
    issues = []
    files = [root / "README.md", root / "AGENTS.md", root / "tools/README.md"]
    files += [p for p in (root / "docs").rglob("*.md") if "archive" not in p.relative_to(root / "docs").parts]
    files += list((root / ".agents").rglob("*.md"))
    for path in files:
        if not path.is_file():
            issues.append(f"缺少文档：{path.relative_to(root)}")
            continue
        text = prose(path.read_text(encoding="utf-8-sig"))
        for match in LINK.finditer(text):
            value = match.group(1).strip().strip("<>")
            parsed = urlsplit(value)
            if parsed.scheme or value.startswith("//"):
                continue
            target = path.parent / unquote(parsed.path) if parsed.path else path
            line = text[:match.start()].count("\n") + 1
            location = f"{path.relative_to(root).as_posix()}:{line}"
            if not target.exists():
                issues.append(f"{location}: 本地链接不存在：{value}")
            elif parsed.fragment and target.suffix.lower() == ".md":
                if unquote(parsed.fragment) not in anchors(target.read_text(encoding="utf-8-sig")):
                    issues.append(f"{location}: 标题锚点不存在：{value}")
    index = root / "tools/README.md"
    if index.is_file():
        text = index.read_text(encoding="utf-8-sig")
        tool_files = [
            path for path in sorted((root / "tools").iterdir())
            if path.is_file() and path.suffix in {".py", ".ps1", ".json"}
        ]
        for path in tool_files:
            if f"`{path.name}`" not in text:
                issues.append(f"tools/README.md: 缺少工具/配置职责：{path.name}")
        if tool_files:
            issues.extend(tool_cluster_issues(root, prose(text)))
    doc_index = root / "docs" / "README.md"
    if doc_index.is_file():
        index_resolved = doc_index.resolve()
        index_text = doc_index.read_text(encoding="utf-8-sig")
        # 顶层 docs/*.md 必须登记进文档索引；maintenance-records/ 与 archive/ 按目录登记，不逐项要求
        for path in sorted((root / "docs").glob("*.md")):
            if path.name != "README.md" and path.name not in index_text:
                issues.append(f"docs/README.md: 缺少文档登记：{path.name}")
        # 活跃文档开头必须保留回指索引的入口；维护记录与冻结归档不在此列
        active = [root / "README.md", root / "AGENTS.md", root / "tools/README.md"]
        active += [p for p in sorted((root / "docs").glob("*.md")) if p.name != "README.md"]
        active += list((root / ".agents").rglob("*.md"))
        for path in active:
            if not path.is_file():
                continue
            head = "\n".join(prose(path.read_text(encoding="utf-8-sig")).splitlines()[:BACK_POINTER_HEAD_LINES])
            linked = False
            for match in LINK.finditer(head):
                value = match.group(1).strip().strip("<>")
                parsed = urlsplit(value)
                if parsed.scheme or value.startswith("//") or not parsed.path:
                    continue
                if (path.parent / unquote(parsed.path)).resolve() == index_resolved:
                    linked = True
                    break
            if not linked:
                issues.append(f"{path.relative_to(root).as_posix()}: 开头缺少回指文档索引的入口")
    issues += single_source_issues(root)
    return issues


def markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown_tables(lines: list[str]) -> list[tuple[int, list[str], list[list[str]]]]:
    """Return (start index, headers, data rows) for every top-level Markdown table."""
    tables: list[tuple[int, list[str], list[list[str]]]] = []
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        start = index
        block: list[str] = []
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            block.append(lines[index])
            index += 1
        if len(block) >= 2:
            tables.append((start, markdown_cells(block[0]), [markdown_cells(row) for row in block[2:]]))
    return tables


def level2_sections(text: str) -> list[tuple[str, int, int]]:
    """(heading, start, end) for `## ` sections; end is exclusive and line-indexed."""
    lines = text.splitlines()
    heads = [index for index, line in enumerate(lines) if line.startswith("## ")]
    sections: list[tuple[str, int, int]] = []
    for position, start in enumerate(heads):
        end = heads[position + 1] if position + 1 < len(heads) else len(lines)
        sections.append((lines[start][3:].strip(), start, end))
    return sections


def tool_cluster_issues(root: Path, text: str) -> list[str]:
    """Enforce the cluster contract: one cluster per tool, indexed and self-consistent."""
    issues: list[str] = []
    lines = text.splitlines()
    members_by_cluster: dict[str, list[str]] = {}
    referenced_plans: set[str] = set()

    for heading, start, end in level2_sections(text):
        match = CLUSTER_SECTION.match(heading)
        if not match:
            continue
        cluster = match.group(1)
        members: list[str] | None = None
        for table_start, headers, rows in markdown_tables(lines[start:end]):
            if tuple(headers[: len(MEMBER_COLUMNS)]) != MEMBER_COLUMNS:
                continue
            members = []
            for offset, row in enumerate(rows):
                line_no = start + table_start + 3 + offset
                if len(row) < len(MEMBER_COLUMNS):
                    issues.append(f"tools/README.md:{line_no}: 成员表列数不足（{cluster} 要求 {'｜'.join(MEMBER_COLUMNS)}）")
                    continue
                found = TOOL_FILE.findall(row[0])
                if len(found) != 1:
                    issues.append(f"tools/README.md:{line_no}: 成员表每行必须恰好登记一个工具（{cluster}）：{row[0] or '（空）'}")
                    continue
                members.append(found[0])
                if cluster == "C0":
                    if "无 CLI" not in row[1]:
                        issues.append(f"tools/README.md:{line_no}: C0 的入口命令列必须写「无 CLI」（{found[0]}）")
                elif "无 CLI" not in row[1] and not CLI_COMMAND.search(row[1]):
                    issues.append(f"tools/README.md:{line_no}: 入口命令必须是反引号命令，或显式写「无 CLI」（{found[0]}）")
                marks = PLAN_MARK.findall(row[3])
                if not marks:
                    issues.append(f"tools/README.md:{line_no}: 门禁与失败边界必须写【P<n>】或【无】（{found[0]}）")
                referenced_plans.update(mark for mark in marks if mark != "无")
            break
        if members is None:
            issues.append(f"tools/README.md: {cluster} 节缺少成员表（列：{'｜'.join(MEMBER_COLUMNS)}）")
            continue
        members_by_cluster[cluster] = members

    if not members_by_cluster:
        issues.append("tools/README.md: 缺少簇节与成员表（形如 `## C1 同步与发布`）")
        return issues

    counts: dict[str, int] = {}
    for members in members_by_cluster.values():
        for tool in members:
            counts[tool] = counts.get(tool, 0) + 1
    for path in sorted((root / "tools").iterdir()):
        if not path.is_file() or path.suffix not in {".py", ".ps1", ".json"}:
            continue
        count = counts.get(path.name, 0)
        if count == 0:
            issues.append(f"tools/README.md: 工具未被任何簇成员表登记：{path.name}")
        elif count > 1:
            issues.append(f"tools/README.md: 工具在多个簇成员表重复登记：{path.name}（{count} 处）")

    for cluster, members in members_by_cluster.items():
        for tool in members:
            if not tool.endswith(".py"):
                continue
            source = root / "tools" / tool
            has_main = source.is_file() and "__main__" in source.read_text(encoding="utf-8-sig", errors="replace")
            if cluster == "C0" and has_main:
                issues.append(f"tools/README.md: 有 __main__ 的工具不得登记在 C0：{tool}")
            elif cluster != "C0" and not has_main:
                issues.append(f"tools/README.md: 无 __main__ 的模块必须登记在 C0：{tool}")

    issues.extend(cluster_index_issues(lines, text, members_by_cluster))
    issues.extend(router_issues(lines, text, members_by_cluster))
    issues.extend(plan_issues(lines, text, referenced_plans))
    return issues


def cluster_index_issues(
    lines: list[str], text: str, members_by_cluster: dict[str, list[str]]
) -> list[str]:
    issues: list[str] = []
    rows_found = None
    for heading, start, end in level2_sections(text):
        if heading != INDEX_SECTION:
            continue
        for table_start, headers, rows in markdown_tables(lines[start:end]):
            if headers and headers[0] == "簇":
                rows_found = (start + table_start, rows)
                break
    if rows_found is None:
        return [f"tools/README.md: 缺少「## {INDEX_SECTION}」表（首列必须是 `C1 同步与发布` 形式的簇号）"]
    base, rows = rows_found
    declared: dict[str, int] = {}
    for offset, row in enumerate(rows):
        line_no = base + 3 + offset
        match = CLUSTER_SECTION.match(row[0]) if row else None
        if not match:
            issues.append(f"tools/README.md:{line_no}: 簇索引首列必须形如 `C1 同步与发布`")
            continue
        cluster = match.group(1)
        numbers = [cell for cell in row[1:] if INDEX_COUNT.match(cell)]
        if len(numbers) != 1:
            issues.append(f"tools/README.md:{line_no}: 簇索引必须恰好给出一列入（{cluster} 入口数）")
            continue
        declared[cluster] = int(numbers[0])
    for cluster, members in members_by_cluster.items():
        if cluster not in declared:
            issues.append(f"tools/README.md: 簇索引缺少 {cluster}")
        elif declared[cluster] != len(members):
            issues.append(
                f"tools/README.md: {cluster} 入口数与成员表不一致（索引 {declared[cluster]}／成员表 {len(members)}）")
    for cluster in declared:
        if cluster not in members_by_cluster:
            issues.append(f"tools/README.md: 簇索引登记了没有成员表的 {cluster}")
    return issues


def router_issues(lines: list[str], text: str, members_by_cluster: dict[str, list[str]]) -> list[str]:
    issues: list[str] = []
    referenced: set[str] = set()
    found = False
    for heading, start, end in level2_sections(text):
        if heading != ROUTER_SECTION:
            continue
        found = True
        for _, _, rows in markdown_tables(lines[start:end]):
            for row in rows:
                for cell in row:
                    for span in BACKTICK_SPAN.findall(cell):
                        referenced.update(TOOL_NAME.findall(span))
    if not found:
        return [f"tools/README.md: 缺少「## {ROUTER_SECTION}」表"]
    known = {tool for members in members_by_cluster.values() for tool in members}
    for tool in sorted(referenced - known):
        issues.append(f"tools/README.md: 路由表引用的工具不在任何簇成员表：{tool}")
    return issues


def plan_issues(lines: list[str], text: str, referenced: set[str]) -> list[str]:
    issues: list[str] = []
    defined: set[str] = set()
    found = False
    for heading, start, end in level2_sections(text):
        if heading != PLAN_SECTION:
            continue
        found = True
        for _, _, rows in markdown_tables(lines[start:end]):
            for row in rows:
                if row and PLAN_ROW.match(row[0]):
                    defined.add(row[0])
    if not found:
        return [f"tools/README.md: 缺少「## {PLAN_SECTION}」预案表"]
    if not defined:
        issues.append(f"tools/README.md: 「## {PLAN_SECTION}」表首列必须写 P1、P2… 形式的预案号")
    for plan in sorted(referenced - defined):
        issues.append(f"tools/README.md: 成员表引用的 {plan} 未在「{PLAN_SECTION}」定义")
    return issues


# ── 单一来源检查：裁定表锚点唯一、规范不嵌取值、规范不复制词表、§ 引用可解析 ──
RULINGS_DOC = "docs/translation-name-rulings.md"
SPEC_DOCS = ("docs/translation-spec.md", "docs/translation-name-selection-spec.md")
RULING_SECTIONS = ("五、", "六、", "七、", "八、", "九、", "9.1", "十、")
BACKTICK_RE = re.compile(r"`([^`]+)`")
RUBY_ANCHOR_RE = re.compile(r"<ruby\b[^>]*>.*?</ruby\s*>", re.S | re.I)
MAPPING_MARK_RE = re.compile(r"→|＝|译作|译为")
WHITELIST_MARK = "single-source-ok"
TABLE_ROW_RE = re.compile(r"^\s*\|")
SECTION_HEAD_RE = re.compile(r"^#{2,3}\s+([0-9]+(?:\.[0-9]+)?|[一二三四五六七八九十]+)[、\s]")
SECTION_REF_RE = re.compile(r"§\s*([0-9]+(?:\.[0-9]+)?|[一二三四五六七八九十]+)")
REF_SCAN_DOCS = SPEC_DOCS + (RULINGS_DOC,)


def norm_anchor(value: str) -> str:
    """锚点归一化：剥 `<ruby>` 取基文、剥标签与装饰符、去空白。"""
    text = re.sub(r"<ruby\b[^>]*>(.*?)<rt\b[^>]*>.*?</rt>\s*</ruby>", r"\1", value or "", flags=re.S)
    text = re.sub(r"<[^>]+>", "", text).replace("`", "").replace("**", "")
    return re.sub(r"[【】「」『』\s]", "", text)


def ruling_rows(root: Path) -> list[tuple[str, str, int]]:
    """裁定表主表条目：(锚点, 义项标识, 行号)。义项标识 = 锚点列中反引号与 `<ruby>` 之外的部分。

    锚点列按「列内只写锚点」整理后，该列不再残留义项文字；此时义项标识取**「备注」列**
    （原「理由」列），同一锚点的多行（如 `スフィア` 的装备／组织两个义项）靠它区分。
    """
    path = root / RULINGS_DOC
    if not path.is_file():
        return []
    rows: list[tuple[str, str, int]] = []
    in_main = False
    header: list[str] | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        head = re.match(r"^#{2,3}\s", line)
        if head:
            in_main = any(key in line for key in RULING_SECTIONS)
            header = None
            continue
        if not TABLE_ROW_RE.match(line):
            header = None
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if not in_main or set("".join(cells)) <= set("-: ") or len(cells) != len(header):
            continue
        index = 1 if "角色" in header[0] else 0
        if index >= len(cells):
            continue
        raw = cells[index]
        found = BACKTICK_RE.findall(raw)
        # 含注音的锚点写成裸 <ruby>…</ruby>（不加反引号，见裁定表 §12 格式约定），同样计入锚点
        found += [match.group(0) for match in RUBY_ANCHOR_RE.finditer(raw)]
        found = list(dict.fromkeys(found))
        if not found:
            continue
        label = RUBY_ANCHOR_RE.sub("", BACKTICK_RE.sub("", raw)).strip("（）() ").strip()
        if not label:
            note_index = next((n for n, name in enumerate(header) if name in ("备注", "理由")), None)
            if note_index is not None and note_index < len(cells):
                label = cells[note_index]
        rows.append((found[0], label, number))
    return rows


def single_source_issues(root: Path) -> list[str]:
    """单一来源检查：同一规则只在一处写正文，其余处只留指针。"""
    issues: list[str] = []
    rows = ruling_rows(root)
    if not rows:
        return issues

    # ① 裁定表锚点唯一：同一锚点 + 相同义项标识不得重复登记
    seen: dict[tuple[str, str], int] = {}
    for anchor, label, number in rows:
        key = (norm_anchor(anchor), label)
        if key in seen:
            show = label if len(label) <= 30 else label[:30] + "…"
            issues.append(
                f"{RULINGS_DOC}:{number}: 裁定条目重复（锚点 `{anchor}` 义项「{show}」已见第 {seen[key]} 行）")
        else:
            seen[key] = number

    # ② 规范正文不得嵌入裁定取值：出现裁定表锚点且同行带映射标记即视为复述
    anchors = sorted({a for a, _, _ in rows if len(a) >= 2}, key=len, reverse=True)
    for rel in SPEC_DOCS:
        path = root / rel
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if WHITELIST_MARK in line or "translation-name-rulings" in line:
                continue
            hit = [a for a in anchors if a in line]
            if hit and MAPPING_MARK_RE.search(line):
                issues.append(
                    f"{rel}:{number}: 规范正文出现裁定取值（{'、'.join(hit[:3])}），应改为指向裁定表的指针")

    # ③ 规范不得复制检查工具的词表（命中过半数即视为复制）
    suffixes: tuple[str, ...] = ()
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("_cts", root / "tools/check_translation_spec.py")
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            suffixes = tuple(getattr(module, "P9_EVENT_SUFFIXES", ()))
    except Exception:
        suffixes = ()
    if suffixes:
        for rel in SPEC_DOCS:
            path = root / rel
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8-sig")
            hits = [item for item in suffixes if item in text]
            if len(hits) * 2 >= len(suffixes):
                issues.append(
                    f"{rel}: 疑似复制检查词表（命中 {len(hits)}/{len(suffixes)} 个 P9_EVENT_SUFFIXES 元素）")

    # ④ § 引用可解析：引用的裁定表小节必须真实存在
    sections = {
        match.group(1)
        for line in (root / RULINGS_DOC).read_text(encoding="utf-8-sig").splitlines()
        for match in [SECTION_HEAD_RE.match(line)]
        if match
    }
    for rel in REF_SCAN_DOCS:
        path = root / rel
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            for ref in SECTION_REF_RE.findall(line):
                if ref not in sections:
                    issues.append(f"{rel}:{number}: 引用的裁定表小节 §{ref} 不存在")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读检查文档链接、索引登记、回指、工具簇归属与单一来源")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    issues = audit(args.root)
    print(f"项目文档检查：问题 {len(issues)} 条")
    for issue in issues:
        print(f"  {issue}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
