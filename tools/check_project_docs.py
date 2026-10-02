"""Check local documentation links and maintenance-tool discoverability."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]\n]+\]\((<[^>]+>|[^)\n]+)\)")


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
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读检查文档链接与工具职责覆盖")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    issues = audit(args.root)
    print(f"项目文档检查：问题 {len(issues)} 条")
    for issue in issues:
        print(f"  {issue}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
