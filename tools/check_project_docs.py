"""Check local documentation links and maintenance-tool discoverability."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]\n]+\]\((<[^>]+>|[^)\n]+)\)")
# 活跃文档开头允许回指文档索引的最大行范围（现有文档均在 10 行以内）
BACK_POINTER_HEAD_LINES = 20


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
        for path in sorted((root / "tools").iterdir()):
            if path.is_file() and path.suffix in {".py", ".ps1", ".json"} and f"`{path.name}`" not in text:
                issues.append(f"tools/README.md: 缺少工具/配置职责：{path.name}")
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
    parser = argparse.ArgumentParser(description="只读检查文档链接、索引登记、回指与工具职责覆盖")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    issues = audit(args.root)
    print(f"项目文档检查：问题 {len(issues)} 条")
    for issue in issues:
        print(f"  {issue}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
