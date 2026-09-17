#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`EPUB/` 单侧只读体检：把「不需要中日对照就能判定」的结构问题一次报全。

定位
----
这是一个**汇总入口**，不是新判定口径的来源。每个检查项的判定标准都取自本项目
既有规约（`AGENTS.md`）或既有工具，本文件只负责：
  1. 在 `EPUB/` 上（而不是 `.cache/`）跑一遍单侧可判的机械检查；
  2. 把结果聚合成一张可提交的体检报告；
  3. 用显式豁免名单压掉已确认的合法例外，让「有新问题」这件事本身成为信号。

**它只读**：不写 `EPUB/`、不写 `.cache/`，报告只输出到终端与 `--tsv/--json` 指定路径。

覆盖不了什么
------------
中日行错位、加粗范围是否对应日文傍点、注音义务——这些必须读日文侧，
`EPUB/` 里只有中文，CI 也看不到 `.cache/`，所以结构上做不到。
单侧检查的上限就是「不需要对照就能判定的问题」，中日对照只能本地定期核查。

检查项
------
  XML        每个 XHTML 能被 `xml.etree` 解析，且 `<img>` 都带 src
  template   固定行模板与正文行原子性（复用 `check_alignment.check_file`）
  bold-punct `<b>` 段内含标点（复用 `text_norm.split_bold_punct`，与每日 CI 同源）
  bold-empty 空 `<b>` 段
  bold-pair  `<b>` 开闭标签数量不一致
  ruby       `<ruby>` 缺 `<rt>` 注音 / ruby 开闭不配对
  seq-00     非法内容序 `-00`
  dup-header 同一本书内同侧重复表头
  seq-gap    同一作品内内容序缺号
  img-prefix 图片文件名缺完整作品号前缀
  dangling   XHTML/OPF/CSS 引用的资源或锚点不存在

刻意不纳入的检查项
------------------
  quotes      直角引号配对。全库有 21 处「开/闭不在同一段」的写法（引语跨段、
              强调性收尾、把原文截断以模拟通讯中断），逐条都需要人工判断该补还是
              该删，不满足「替换值唯一」，因此只报告不进门禁——本文件不实现它，
              需要时单独逐本人工核查。
  li-number   Note 列表项编号。它与正文条目号是两套编号，且条目号与普通正文行
              （如「4.5 个榻榻米」）形式上无法区分，任何判据都会误报。Note 编号
              一致性由 `check_note_order.py` 在缓存上按「定义顺序 vs 正文首次引用
              顺序」判定，口径更强。
  换行符      `AGENTS.md` 明确「换行符不作为修改对象」，CRLF 属仓库容忍的既有态，
             不是问题，因此不做检查也不报告。

豁免名单（`alignment_rules.TEMPLATE_EXEMPT_WORK_IDS`）
--------------------------------------------------
`S0_00`（读前必看，非正文）、`S6_10.06.26`、`S6_24.12.10`——后两本没有 BW 分页源，
已明确不处理。豁免粒度按「书 + 检查项」，这三本只豁免 template，其余照查
（如 `S0_00-00` 这类非法内容序仍会被 `check_alignment.py` 报出来）。名单本体放在
`alignment_rules.py`，`check_alignment.py` 与 `check_epub_health.py` 共用一份。

用法
----
    python tools/check_epub_health.py                       # 终端汇总
    python tools/check_epub_health.py --strict              # 有问题时非零退出（CI 门禁）
    python tools/check_epub_health.py --pattern "*S3_*"     # 按书目录名筛选
    python tools/check_epub_health.py --only bold-punct,ruby,dangling
    python tools/check_epub_health.py --tsv r.tsv --json r.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from alignment_rules import TEMPLATE_EXEMPT_WORK_IDS, template_exempt  # noqa: F401
from check_alignment import check_file as check_template
from epub_ids import book_id, content_sequence, header_of, is_packaging_header, work_id
from text_norm import split_bold_punct

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "EPUB"

# 豁免名单本体在 `alignment_rules.TEMPLATE_EXEMPT_WORK_IDS`——`check_alignment.py`
# 和本工具都从那里取。两处各放一份必然漂移：一边放宽了、另一边还在报。
# 粒度是「作品 + 检查项」：`S0_00` 这类只豁免 template，其余检查照跑。

IMG_REF_RE = re.compile(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', re.I)
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|gif|svg|webp)$", re.I)
RUBY_BLOCK_RE = re.compile(r"<ruby\b[^>]*>(.*?)</ruby\s*>", re.S | re.I)

CHECK_ORDER = (
    "XML", "template", "bold-punct", "bold-empty", "bold-pair",
    "ruby", "seq-00", "dup-header", "seq-gap", "img-prefix", "dangling",
)
CHECK_DESC = {
    "XML": "XHTML 不是合法 XML 或 `<img>` 缺 src",
    "template": "固定行模板/正文行原子性",
    "bold-punct": "`<b>` 段内含标点",
    "bold-empty": "空 `<b>` 段",
    "bold-pair": "`<b>` 开闭标签数量不一致",
    "ruby": "`<ruby>` 缺 `<rt>` 注音或开闭不配对",
    "seq-00": "非法内容序 -00",
    "dup-header": "同书内重复表头",
    "seq-gap": "同作品内容序缺号",
    "img-prefix": "图片文件名缺作品号前缀",
    "dangling": "悬空资源/锚点引用",
}
SEVERITY = {
    "XML": "error", "template": "error", "bold-punct": "error",
    "bold-empty": "warning", "bold-pair": "error", "ruby": "error", "seq-00": "error",
    "dup-header": "error", "seq-gap": "warning", "img-prefix": "error",
    "dangling": "error",
}


# ---------------------------------------------------------------------------
# 单文件检查
# ---------------------------------------------------------------------------

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def read_lines(path: Path) -> list[str]:
    return read_text(path).splitlines()


def check_xml_refs(path: Path, lines: list[str]) -> str | None:
    """`<img>` 必须带 src 属性；缺 src 的图片标签在阅读器里是空洞。"""
    for line in lines:
        if "<img" not in line.lower():
            continue
        for tag in IMG_TAG_RE.findall(line):
            if not re.search(r"\bsrc\s*=", tag, re.I):
                return "`<img>` 缺 src 属性：%s" % tag[:80]
    return None


def find_ruby_problems(lines: list[str]) -> list[tuple[int, str]]:
    """`<ruby>` 必须有 `<rt>` 注音，且同文件内开闭标签数量一致。

    只查结构，不判注音内容对不对——「日文注音是否该译成汉语」属内容层，
    由 `check_translation_spec.py` 的 P10 报告，不在这里重复判定。
    """
    out: list[tuple[int, str]] = []
    opens = closes = 0
    for lineno, line in enumerate(lines, 1):
        opens += len(re.findall(r"<ruby\b", line, re.I))
        closes += len(re.findall(r"</ruby\s*>", line, re.I))
        for m in RUBY_BLOCK_RE.finditer(line):
            if not re.search(r"<rt\b", m.group(1), re.I):
                out.append((lineno, "`<ruby>` 缺 `<rt>` 注音：%s"
                            % re.sub(r"\s+", " ", m.group(0))[:80]))
    if opens != closes:
        out.append((0, "`<ruby>` %d 个 / `</ruby>` %d 个" % (opens, closes)))
    return out


def find_bold_punct(lines: list[str]) -> list[tuple[int, str]]:
    """`<b>` 段内标点：与每日 CI（`text_norm.py`）同判定，命中即为 CI 会改的内容。"""
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(lines, 1):
        if "<b" not in line.lower():
            continue
        _new, block_hits = split_bold_punct(line)
        for _rid, matched, _ctx in block_hits:
            hits.append((lineno, matched))
    return hits


def find_bold_pairing(lines: list[str]) -> str | None:
    text = "\n".join(lines)
    opens = len(re.findall(r"<b\b", text, re.I))
    closes = len(re.findall(r"</b\s*>", text, re.I))
    if opens != closes:
        return "`<b>` %d 个 / `</b>` %d 个" % (opens, closes)
    return None


def find_bold_empty(lines: list[str]) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(lines, 1):
        for m in re.finditer(r"<b\b[^>]*>(.*?)</b\s*>", line, re.S | re.I):
            if not re.sub(r"<[^>]*>", "", m.group(1)).strip():
                hits.append((lineno, m.group(0)))
    return hits


# ---------------------------------------------------------------------------
# 单本检查
# ---------------------------------------------------------------------------

def collect_xhtml(book_dir: Path) -> list[Path]:
    return sorted(p for p in book_dir.rglob("*.xhtml") if p.name.lower() != "nav.xhtml")


def find_sequence_problems(xhtmls: list[Path]) -> list[tuple[str, str]]:
    """`-00` / 重复表头 / 内容序缺号。返回 (检查项, 说明) 列表。"""
    out: list[tuple[str, str]] = []
    by_header: dict[str, list[Path]] = defaultdict(list)
    by_work: dict[str, set[int]] = defaultdict(set)
    for path in xhtmls:
        seq = content_sequence(path.name)
        if seq == 0:
            out.append(("seq-00", "`%s` 使用非法内容序 -00" % path.name))
        header = header_of(path.name)
        if header:
            by_header[header].append(path)
    for header, paths in sorted(by_header.items()):
        if len(paths) > 1:
            out.append(("dup-header", "表头 `%s` 出现 %d 次：%s"
                        % (header, len(paths), "、".join(p.name for p in paths))))
        seq = content_sequence(paths[0].name)
        wid = work_id(paths[0].name)
        if seq and wid:
            by_work[wid].add(seq)
    for wid, seqs in sorted(by_work.items()):
        # 内容序从 -01 开始连续；补号只对「有多个内容序」的作品判定，
        # 单文件作品（如 S6 短篇）本来就只有 -01。
        if len(seqs) < 2:
            continue
        missing = [n for n in range(1, max(seqs) + 1) if n not in seqs]
        if missing:
            out.append(("seq-gap", "作品 `%s` 内容序缺号：%s（现有 %s）"
                        % (wid, ",".join("%02d" % n for n in missing),
                           ",".join("%02d" % n for n in sorted(seqs)))))
    return out


def find_image_prefix_problems(book_dir: Path, wid: str | None) -> list[tuple[str, str]]:
    if not wid:
        return []
    out: list[tuple[str, str]] = []
    for path in sorted(book_dir.rglob("*")):
        if not path.is_file() or not IMAGE_EXT_RE.search(path.name):
            continue
        if not path.name.upper().startswith(wid.upper() + "-"):
            out.append(("img-prefix", "`%s` 缺作品号前缀 `%s-`"
                        % (path.relative_to(book_dir).as_posix(), wid)))
    return out


def find_dangling(book_dir: Path, xhtmls: list[Path]) -> list[tuple[str, str]]:
    """XHTML/OPF/CSS 里的相对引用（含 `#frag`）必须真实存在。"""
    out: list[tuple[str, str]] = []
    anchors: dict[Path, set[str]] = {}
    for path in xhtmls:
        anchors[path] = set(re.findall(r'\bid\s*=\s*["\']([^"\']+)["\']', read_text(path)))
    sources = list(xhtmls)
    for pat in ("*.opf", "*.ncx", "*.css"):
        sources.extend(sorted(book_dir.rglob(pat)))
    for path in sources:
        for ref in IMG_REF_RE.findall(read_text(path)):
            if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|data:)", ref, re.I):
                continue
            target, _, frag = ref.partition("#")
            if not target:
                # 纯锚点：只在同文件内找
                if frag and frag not in anchors.get(path, ()):
                    out.append(("dangling", "`%s` 锚点 `#%s` 不存在" % (path.name, frag)))
                continue
            # EPUB 内部引用一律以 `/` 分隔且相对当前文件；用 `/` 解析
            # 以免在 Windows 上把 `a/b.png` 当成字面文件名。
            resolved = path.parent.joinpath(*target.split("/"))
            if not resolved.exists():
                out.append(("dangling", "`%s` 引用不存在的 `%s`" % (path.name, ref)))
            elif frag and resolved.suffix.lower() in (".xhtml", ".html"):
                if frag not in anchors.get(resolved, set()):
                    out.append(("dangling", "`%s` 引用 `%s`，但锚点 `#%s` 不存在"
                                % (path.name, target, frag)))
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def iter_books(root: Path, pattern: str | None):
    if not root.is_dir():
        raise SystemExit("根目录不存在：%s" % root)
    rx = re.compile(pattern.replace("*", ".*")) if pattern else None
    for book in sorted(p for p in root.iterdir() if p.is_dir()):
        if rx and not rx.search(book.name):
            continue
        yield book


def exempt(bid: str | None, check: str) -> bool:
    """只有 template 项有豁免名单，其余检查项对所有作品一律生效。"""
    return check == "template" and template_exempt(bid)


def audit_book(book_dir: Path, only: set[str] | None) -> tuple[list[tuple], Counter, Counter, Counter]:
    """返回 (findings, 命中计数, 豁免计数, 覆盖文件计数)。

    findings 每项：``(check, book_id, rel_path, line, severity, message)``；
    line 为 0 表示整文件/整书级。
    """
    bid = book_id(book_dir.name)
    findings: list[tuple] = []
    counts: Counter = Counter()
    exempted: Counter = Counter()
    covered: Counter = Counter()
    want = lambda c: only is None or c in only  # noqa: E731
    # 图片前缀用目录上的作品号；目录名无作品号（异常情况）时退回文件名解析
    wid = bid or work_id(book_dir.name)

    def add(check: str, rel: str, line: int, msg: str) -> None:
        if exempt(bid, check):
            exempted[check] += 1
            return
        counts[check] += 1
        findings.append((check, bid or book_dir.name, rel, line, SEVERITY[check], msg))

    xhtmls = collect_xhtml(book_dir)

    if want("seq-00") or want("dup-header") or want("seq-gap"):
        for check, msg in find_sequence_problems(xhtmls):
            if want(check):
                add(check, "-", 0, msg)
    if want("img-prefix"):
        for check, msg in find_image_prefix_problems(book_dir, wid):
            add(check, "-", 0, msg)
    if want("dangling"):
        for check, msg in find_dangling(book_dir, xhtmls):
            add(check, "-", 0, msg)

    for path in xhtmls:
        covered["files"] += 1
        rel = path.relative_to(book_dir).as_posix()
        # 先解析一次：解析结果同时用于 XML 检查和行级检查的输入。
        # 解析失败时行级检查没有可信输入，只报 XML 并跳过该文件。
        try:
            ET.parse(str(path))
            parse_error = None
        except ET.ParseError as exc:
            parse_error = "XML 解析失败：%s" % exc
        lines = read_lines(path)
        if parse_error:
            if want("XML"):
                add("XML", rel, 0, parse_error)
            continue
        if want("XML"):
            err = check_xml_refs(path, lines)
            if err:
                add("XML", rel, 0, err)

        allow_list = is_packaging_header(header_of(path.name))
        if want("template"):
            for err in check_template(lines, allow_list):
                add("template", rel, 0, err)
        if want("bold-punct"):
            for lineno, matched in find_bold_punct(lines):
                add("bold-punct", rel, lineno, "`<b>` 段内含标点：%s" % matched[:80])
        if want("bold-pair"):
            msg = find_bold_pairing(lines)
            if msg:
                add("bold-pair", rel, 0, msg)
        if want("bold-empty"):
            for lineno, matched in find_bold_empty(lines):
                add("bold-empty", rel, lineno, "空 `<b>` 段：%s" % matched[:80])
        if want("ruby"):
            for lineno, msg in find_ruby_problems(lines):
                add("ruby", rel, lineno, msg)
    return findings, counts, exempted, covered


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="EPUB/ 单侧只读体检（固定行模板、加粗标点、结构引用完整性等）")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="EPUB 根目录")
    ap.add_argument("--pattern", default=None, help="按书目录名筛选，如 '*S3_*'")
    ap.add_argument("--only", default=None, help="只跑指定检查项（逗号分隔）")
    ap.add_argument("--strict", action="store_true", help="有 error 级问题时返回非零（CI 门禁）")
    ap.add_argument("--top", type=int, default=5, help="每类最多列出的样例数")
    ap.add_argument("--tsv", type=Path, default=None, help="TSV 报告输出路径")
    ap.add_argument("--json", type=Path, default=None, help="JSON 报告输出路径")
    args = ap.parse_args()

    only = set(s.strip() for s in args.only.split(",")) if args.only else None
    unknown = (only or set()) - set(CHECK_ORDER)
    if unknown:
        raise SystemExit("未知检查项：%s（可选：%s）" % (", ".join(sorted(unknown)), ", ".join(CHECK_ORDER)))

    root = args.root.resolve()
    findings: list[tuple] = []
    counts: Counter = Counter()
    exempted: Counter = Counter()
    books = 0
    files = 0
    for book_dir in iter_books(root, args.pattern):
        books += 1
        book_findings, book_counts, book_exempted, covered = audit_book(book_dir, only)
        findings.extend(book_findings)
        counts.update(book_counts)
        exempted.update(book_exempted)
        files += covered["files"]

    errors = sum(1 for f in findings if f[4] == "error")
    warnings = len(findings) - errors

    print("EPUB 单侧体检：%d 本书、%d 个 XHTML；问题 %d 条（error %d / warning %d）"
          % (books, files, len(findings), errors, warnings))
    for check in CHECK_ORDER:
        n = counts.get(check, 0)
        if only is not None and check not in only:
            continue
        ex = exempted.get(check, 0)
        suffix = "（另有 %d 处命中已豁免）" % ex if ex else ""
        print("  %-11s %4d  %s%s" % (check, n, CHECK_DESC[check], suffix))
    if findings:
        print()
        by_check: dict[str, list[tuple]] = defaultdict(list)
        for f in findings:
            by_check[f[0]].append(f)
        for check in CHECK_ORDER:
            items = by_check.get(check)
            if not items:
                continue
            print("[%s] %s（%d 条）" % (check, CHECK_DESC[check], len(items)))
            for _c, bid, rel, lineno, _sev, msg in items[:args.top]:
                loc = "%s %s%s" % (bid, rel, ":%d" % lineno if lineno else "")
                print("    %s — %s" % (loc, msg))
            if len(items) > args.top:
                print("    …另有 %d 条，见报告文件" % (len(items) - args.top))
            print()

    if args.tsv:
        args.tsv.parent.mkdir(parents=True, exist_ok=True)
        with args.tsv.open("w", encoding="utf-8", newline="") as f:
            f.write("check\tbook\tfile\tline\tseverity\tmessage\n")
            for check, bid, rel, lineno, sev, msg in sorted(findings):
                clean = msg.replace("\t", " ").replace("\n", " ")
                f.write("\t".join([check, bid or "", rel, str(lineno), sev, clean]) + "\n")
        print("TSV：%s" % args.tsv)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "scope": "EPUB/**/*.xhtml（单侧只读体检）",
            "books": books,
            "files": files,
            "total": len(findings),
            "severity": {"error": errors, "warning": warnings},
            "by_check": {c: counts.get(c, 0) for c in CHECK_ORDER},
            "exempted": dict(exempted),
            "template_exempt_works": sorted(TEMPLATE_EXEMPT_WORK_IDS),
            "findings": [
                {"check": c, "book": b, "file": r, "line": l, "severity": s, "message": m}
                for c, b, r, l, s, m in findings
            ],
        }
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        print("JSON：%s" % args.json)

    return 1 if (args.strict and errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
