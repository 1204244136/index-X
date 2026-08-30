#!/usr/bin/env python3
"""BookWalker（bw）提取预处理：按规则集改写原始 bw EPUB / 解包目录中的 XHTML。

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
    python tools/bw_preprocess.py --check 某本bw提取.epub   # 校验模式，不写盘
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

XHTML_SUFFIXES = (".xhtml", ".html", ".htm")
DEFAULT_RULES_JSON = "bw_extract_preprocess.json"


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


def is_content(text: str) -> bool:
    """是否为正文内容文件（body 使用 p-text 类，套用固定行模板）。"""
    return '<body class="p-text">' in text


def template_issues(lines: list[str]) -> list[str]:
    """固定行模板 L1-L6 校验。返回问题列表；空列表 = 符合。

    L1 <?xml …?>  L2 <!DOCTYPE html>  L3 <html …><div class="main">
    L4 <h1>…</h1> 或空行  L5 <h2>…</h2> 或空行（中文包装页可为 <ul>/<ol>）
    L6 <p>正文首行</p>
    """
    issues: list[str] = []
    if len(lines) < 6:
        return [f"行数 {len(lines)} < 6，无法满足 L1-L6 模板"]
    if not lines[0].startswith("<?xml"):
        issues.append(f"L1 非 XML 声明：{lines[0][:40]}")
    if not lines[1].startswith("<!DOCTYPE"):
        issues.append(f"L2 非 DOCTYPE：{lines[1][:40]}")
    if not (lines[2].startswith("<html") and '<div class="main">' in lines[2]):
        issues.append("L3 未折叠为单行头部（需含 <div class=\"main\">）")
    l4, l5, l6 = lines[3], lines[4], lines[5]
    if l4 and not l4.startswith("<h1"):
        issues.append(f"L4 应为 <h1> 或空行：{l4[:40]}")
    if l5 and not (l5.startswith("<h2") or l5.startswith("<ul") or l5.startswith("<ol")):
        issues.append(f"L5 应为 <h2> 或空行：{l5[:40]}")
    if not re.match(r"^\s*<p\b", l6):
        issues.append(f"L6 应为正文 <p>：{l6[:40]}")
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


def process_epub(epub_path: Path, rules: list[dict], out_path: Path,
                 dry_run: bool) -> dict:
    """处理 .epub：解包改写后重新打包。返回统计 dict。"""
    with zipfile.ZipFile(epub_path) as zin:
        infos = zin.infolist()
        entries = {i.filename: zin.read(i.filename) for i in infos}
    stats = {"total": 0, "changed": 0, "content": 0, "issues": []}
    for name in entries:
        if name.lower().endswith(XHTML_SUFFIXES):
            stats["total"] += 1
            new_data, ch = transform_bytes(entries[name], rules)
            if ch:
                stats["changed"] += 1
                if not dry_run:
                    entries[name] = new_data
            if is_content(new_data.decode("utf-8-sig", errors="replace")):
                stats["content"] += 1
            if not dry_run:
                issues = verify_text(new_data.decode("utf-8-sig", errors="replace"))
                for it in issues:
                    stats["issues"].append((name, it))
    if dry_run:
        return stats
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w") as zout:
        for info in infos:
            data = entries[info.filename]
            new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new_info.compress_type = (
                zipfile.ZIP_STORED
                if info.compress_type == zipfile.ZIP_STORED
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
    stats = {"total": 0, "changed": 0, "content": 0, "issues": []}
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
    """--check：内存中应用规则并校验模板，不写盘。"""
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


def check_epub(epub_path: Path, rules: list[dict]) -> dict:
    """--check：epub 模式内存校验。"""
    with zipfile.ZipFile(epub_path) as zin:
        stats = {"total": 0, "content": 0, "issues": []}
        for info in zin.infolist():
            if not info.filename.lower().endswith(XHTML_SUFFIXES):
                continue
            stats["total"] += 1
            text = apply_rules(
                zin.read(info.filename).decode("utf-8-sig", errors="replace"),
                rules)
            if is_content(text):
                stats["content"] += 1
                for it in template_issues(text.splitlines()):
                    stats["issues"].append((info.filename, it))
        return stats


def report_stats(label: str, stats: dict, dry_run: bool, check: bool,
                 out=None) -> None:
    non_content = stats["total"] - stats["content"]
    base = (f"XHTML {stats['total']} 个：内容 {stats['content']}，"
            f"非内容 {non_content}")
    if not check:
        base += f"；改写 {stats['changed']}"
    if check:
        base += "（校验，未写盘）"
    elif dry_run:
        base += "（预览，未写盘）"
    elif out:
        base += f"（输出：{out}）"
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
    ap.add_argument("--out", type=Path, default=None,
                    help="epub 模式输出目录（默认写在源文件同目录）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写文件")
    ap.add_argument("--check", action="store_true",
                    help="校验模式：内存中应用规则并检查内容文件 L1-L6 模板符合度，不写盘")
    args = ap.parse_args()

    rules = load_rules(args.rules)
    print(f"加载规则：{len(rules)} 条（{args.rules or DEFAULT_RULES_JSON}）")
    for r in rules:
        print(f"  - {r['name']}")

    for raw in args.paths:
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
                stats = check_epub(p, rules)
                report_stats(f"epub {p}", stats, False, True)
            else:
                out_dir = args.out if args.out else p.parent
                out = out_dir / p.name
                if args.out is None:
                    out = p.with_name(p.stem + ".preprocessed" + p.suffix)
                stats = process_epub(p, rules, out, args.dry_run)
                report_stats(f"epub {p}", stats, args.dry_run, False,
                             None if args.dry_run else out)
        else:
            print(f"[跳过] 不是 .epub 或目录：{p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
