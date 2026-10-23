"""核对 docs/illustration-text-mapping.md 的每一行锚点：行号是否还指着那句正文。

表里的「行号」是日文缓存的**物理行号**，而 `.cache/epub-work/japanese-text/` 由
`tools/pull.ps1` 重建——日文源一重导、一规范化，行号就可能整体位移。本工具逐行回查：

- 行号仍命中且 `正文原句` 对得上 → 通过；
- 行号不符 → 在该卷正文里按 `正文原句` 重新定位，给出建议行号；
- 重新定位也找不到 → 记为未解析，非零退出。

只读：不写任何文件（`--json` 除外，写显式报告路径）。
"""
from __future__ import annotations

import argparse
import difflib
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOC = REPO_ROOT / "docs" / "illustration-text-mapping.md"
DEFAULT_JP_ROOT = REPO_ROOT / ".cache" / "epub-work" / "japanese-text"

COLUMNS = ("卷号", "图片", "图片文字", "正文文件", "行号", "正文原句", "备注")
DROP_CATS = {"P", "Z", "C", "S"}
TABLE_ROW = re.compile(r"^\s*\|")
RT_RE = re.compile(r"<rt\b[^>]*>.*?</rt>", re.S)
RP_RE = re.compile(r"<rp\b[^>]*>.*?</rp>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
GAIJI_RE = re.compile(r'<img\b[^>]*class="gaiji"[^>]*>', re.I)
ALT_RE = re.compile(r'alt="([^"]*)"')
BR_RE = re.compile(r"<br\s*/?>", re.I)
P_SPLIT_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S)
FUZZY_MIN = 0.9


def norm(text: str) -> str:
    """与建表时同一套规范化：NFKC 后丢掉标点／空白／控制／符号。"""
    value = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in value if unicodedata.category(ch)[0] not in DROP_CATS)


def para_text(fragment: str) -> str:
    text = GAIJI_RE.sub(lambda m: (ALT_RE.search(m.group(0)) or [None, ""])[1], fragment)
    text = RT_RE.sub("", text)
    text = RP_RE.sub("", text)
    text = BR_RE.sub("\n", text)
    text = TAG_RE.sub("", text)
    return html.unescape(text).strip()


def cells_of(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


def unescape_cell(value: str) -> str:
    return value.replace("\\|", "|").strip()


def read_rows(doc: Path) -> tuple[list[dict[str, str]], list[str]]:
    """取出主映射表的数据行；同时返回解析层面的问题。

    文档里有三张表（列说明、映射表、覆盖统计），只有表头恰好是 `COLUMNS` 的那张才算映射表，
    其余整张跳过——不因为「不是映射表」而报错。
    """
    problems: list[str] = []
    rows: list[dict[str, str]] = []
    mode: str | None = None
    for number, line in enumerate(doc.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not TABLE_ROW.match(line):
            mode = None
            continue
        cells = [unescape_cell(cell) for cell in cells_of(line)]
        if set("".join(cells)) <= set("-: "):
            continue
        if mode is None:
            mode = "map" if tuple(cells) == COLUMNS else "skip"
            continue
        if mode != "map":
            continue
        if len(cells) != len(COLUMNS):
            problems.append(f"{doc.name}:{number}: 映射表该行不是 {len(COLUMNS)} 列：{'｜'.join(cells)}")
            continue
        rows.append(dict(zip(COLUMNS, cells)))
    if not rows:
        problems.append(f"{doc.name}: 没找到表头为 {'｜'.join(COLUMNS)} 的映射表")
    return rows, problems


def line_paragraphs(path: Path) -> dict[int, list[str]]:
    """物理行号 → 该行所有 `<p>` 的正文（与建表口径一致）。"""
    result: dict[int, list[str]] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "<p" not in line:
            continue
        texts = [para_text(frag) for frag in P_SPLIT_RE.findall(line)]
        texts = [text for text in texts if text]
        if texts:
            result[number] = texts
    return result


def volume_dir(jp_root: Path, vol: str) -> Path | None:
    return next((p for p in jp_root.glob(f"【{vol}】*") if p.is_dir()), None)


def xhtml_dir(vol_dir: Path) -> Path | None:
    for cand in (vol_dir / "item" / "xhtml", vol_dir / "xhtml", vol_dir):
        if cand.is_dir():
            return cand
    return None


def relocate(jp_root: Path, vol: str, expected: str) -> int | None:
    """按 `正文原句` 在整卷里重新定位，返回最佳行号。"""
    directory = volume_dir(jp_root, vol)
    if directory is None:
        return None
    source = xhtml_dir(directory)
    if source is None:
        return None
    query = norm(expected)
    if not query:
        return None
    best: tuple[float, int] | None = None
    for path in sorted(source.glob(f"{vol}-*.xhtml")):
        for number, texts in line_paragraphs(path).items():
            for text in texts:
                candidate = norm(text)
                if candidate == query:
                    return number
                ratio = difflib.SequenceMatcher(None, query, candidate).ratio()
                if ratio >= FUZZY_MIN and (best is None or ratio > best[0]):
                    best = (ratio, number)
    return best[1] if best else None


def check(doc: Path, jp_root: Path, limit: int = 0) -> tuple[int, list[dict[str, object]], list[str]]:
    """返回完整核对结果；兼容旧调用的 limit，样例限制仅在终端应用。"""
    rows, problems = read_rows(doc)
    cache: dict[tuple[str, str], dict[int, list[str]]] = {}
    unresolved: list[dict[str, object]] = []
    checked = skipped = 0

    for row in rows:
        if not row["正文文件"] or row["正文文件"] == "—":
            skipped += 1
            continue
        checked += 1
        vol, name, filename = row["卷号"], row["图片"], row["正文文件"]
        span = row["行号"]
        start = int(span.split("–")[0]) if span and span[0].isdigit() else 0
        directory = volume_dir(jp_root, vol)
        if directory is None:
            unresolved.append({"vol": vol, "image": name, "kind": "missing_volume",
                               "detail": f"找不到卷目录：【{vol}】*"})
            continue
        source = xhtml_dir(directory)
        path = (source / filename) if source else None
        if path is None or not path.is_file():
            unresolved.append({"vol": vol, "image": name, "kind": "missing_file",
                               "detail": f"找不到正文文件：{filename}"})
            continue
        key = (vol, filename)
        if key not in cache:
            cache[key] = line_paragraphs(path)
        texts = cache[key].get(start)
        expected = row["正文原句"] if row["正文原句"] != "—" else ""
        if texts:
            wanted = norm(expected)
            if not wanted or any(norm(text) == wanted for text in texts):
                continue
        suggestion = relocate(jp_root, vol, expected) if expected else None
        unresolved.append({
            "vol": vol, "image": name, "kind": "line_drift",
            "file": filename, "line": start, "suggest": suggestion,
            "detail": f"第 {start} 行已不是这句" + (f"，建议 {suggestion}" if suggestion else "，整卷未找到"),
        })

    if problems:
        unresolved.extend({"vol": "-", "image": "-", "kind": "format", "detail": text}
                          for text in problems)
    return checked, unresolved, [f"跳过 {skipped}"]


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="核对插图映射表的正文行号锚点（只读）")
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC, help="映射表 Markdown 路径")
    parser.add_argument("--jp-root", type=Path, default=DEFAULT_JP_ROOT, help="日文缓存根目录")
    parser.add_argument("--limit", type=int, default=0, help="只显示前 N 条问题（0 = 全部）")
    parser.add_argument("--json", type=Path, default=None, help="把结果写成 JSON 报告")
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit 必须是非负整数")

    if not args.doc.is_file():
        print(f"缺少映射表：{args.doc}", file=sys.stderr)
        return 2
    if not args.jp_root.is_dir():
        print(f"缺少日文缓存：{args.jp_root}（先运行 ./tools/pull.ps1 建立缓存）", file=sys.stderr)
        return 2

    checked, unresolved, notes = check(args.doc, args.jp_root)
    print(f"插图映射核对：有锚点 {checked} 行／问题 {len(unresolved)} 条（{'；'.join(notes)}）")
    for item in unresolved[:args.limit] if args.limit else unresolved:
        print(f"  {item['vol']} {item['image']}: {item['detail']}")
    if args.limit and len(unresolved) > args.limit:
        print(f"  …另有 {len(unresolved) - args.limit} 条；用 --limit 0 显示全部，或用 --json 路径导出完整报告")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"checked": checked, "problems": unresolved}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f"报告：{args.json}")
    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
