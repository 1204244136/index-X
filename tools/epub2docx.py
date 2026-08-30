#!/usr/bin/env python3
"""EPUB → DOCX 转换脚本（交稿格式）。

参考 calibre 仓库的 EPUB/DOCX 转换管线：转换交给本机安装的 calibre
（ebook-convert）。转换前先把 EPUB 成品中的注音

    <ruby>基文<rt>注音</rt></ruby>

反向还原为《翻译与修嵌规范》交稿层面的注音记号

    |基文[注音]

（EPUB 成品中已把 |基文[注音] 转为 <ruby>，本脚本做反向还原，
对应 tools/README.md「交稿层面机制」的说明。）

流程（每本）：
  1. 读入 .epub（若是解包书籍目录则先按 EPUB 规范打包）；
  2. 只改写含 <ruby> 的 XHTML 文件：<ruby>基文<rt>注音</rt></ruby> → |基文[注音]，
     其余字节原样保留（含 BOM、CRLF、条目顺序与压缩方式）；
  3. 重新打包为中间 .ruby.epub（--keep-src-epub 保留，否则临时文件自动清理）；
  4. 调用本机 calibre 的 ebook-convert 把中间 EPUB 转成 .docx；
  5. 输出 docx 中 ruby 变成字面文本 |基文[注音]，可直接作为交稿使用。

用法：
    python tools/epub2docx.py 某书.epub
    python tools/epub2docx.py 解包的书目录/                # 目录会先打包再转换
    python tools/epub2docx.py --out 输出目录/ 书1.epub 书2.epub
    python tools/epub2docx.py --pattern "*S1_01*" EPUB/    # 批量目录（按书名筛选）
    python tools/epub2docx.py --dry-run 某书.epub          # 只统计 ruby 改写，不转换
    python tools/epub2docx.py --keep-src-epub 某书.epub    # 保留中间 .ruby.epub
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

XHTML_SUFFIXES = (".xhtml", ".html", ".htm")
EPUB_MIMETYPE = b"application/epub+zip"

# 只命中 <ruby>…</ruby> 块（允许属性、大小写、嵌套）；块外内容逐字节保留
_RUBY_START = re.compile(r"<ruby\b[^>]*>", re.IGNORECASE)
_RUBY_END = re.compile(r"</ruby\s*>", re.IGNORECASE)
_RT = re.compile(r"<rt\b[^>]*>(.*?)</rt\s*>", re.DOTALL | re.IGNORECASE)
_RP = re.compile(r"<rp\b[^>]*>.*?</rp\s*>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
try:
    from package_cache_epubs import package_book  # type: ignore
except Exception:  # pragma: no cover - 兜底
    package_book = None


def clean_text(raw: str) -> str:
    """去掉全部标签并把空白折叠为单个空格，再去除首尾空白。

    文本取自源 XHTML 的文本节点，其中的实体（如 &amp;）原样保留，
    重新写回 XML 文本节点时仍是合法表示，不会二次转义。
    """
    return _WS.sub(" ", _TAG.sub("", raw)).strip()


def render_ruby(inner: str) -> str:
    """把 <ruby> 的 inner 渲染为 |基文[注音] 字面文本。

    - <rt> 内容（可多个）拼接为注音；<rp> 直接丢弃；
    - 无 <rt> 或注音为空 → 只输出基文（去掉 ruby 外壳）；
    - 基文为空 → 只输出注音。
    """
    annos = [clean_text(m.group(1)) for m in _RT.finditer(inner)]
    base_raw = _RP.sub("", inner)
    base_raw = _RT.sub("", base_raw)
    base = clean_text(base_raw)
    if not annos:
        return base
    anno = "".join(annos)
    if not base:
        return anno
    if not anno:
        return base
    return f"|{base}[{anno}]"


def rewrite_ruby(text: str) -> tuple[str, int]:
    """把文本中全部 <ruby>…</ruby> 改写为 |基文[注音]，支持嵌套（自外向内展开）。

    返回 (新文本, 改写处数)。只替换 ruby 块本身，块外内容逐字节保留。
    """
    out: list[str] = []
    count = 0
    pos = 0
    n = len(text)
    while True:
        start = _RUBY_START.search(text, pos)
        if start is None:
            out.append(text[pos:])
            break
        out.append(text[pos:start.start()])
        # 找配对的 </ruby>（记录嵌套深度以跳过内层）
        depth = 1
        i = start.end()
        close_start = close_end = None
        while depth > 0:
            nxt_start = _RUBY_START.search(text, i)
            nxt_end = _RUBY_END.search(text, i)
            if nxt_end is None:
                close_start = close_end = None
                break
            if nxt_start is not None and nxt_start.start() < nxt_end.start():
                depth += 1
                i = nxt_start.end()
            else:
                depth -= 1
                close_start, close_end = nxt_end.start(), nxt_end.end()
                i = close_end
        if close_end is None:
            # 未配对的 <ruby>，剩余文本原样保留（不破坏原文件）
            out.append(text[start.start():])
            break
        inner = text[start.end():close_start]
        out.append(render_ruby(inner))
        count += 1
        pos = close_end
    return "".join(out), count


def transform_bytes(data: bytes) -> tuple[bytes, int]:
    """解码（保留 BOM）→ ruby 改写 → 编码。返回 (新字节, 改写处数)。"""
    bom = data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    new_text, count = rewrite_ruby(text)
    if count == 0:
        return data, 0
    out = new_text.encode("utf-8")
    if bom:
        out = b"\xef\xbb\xbf" + out
    return out, count


def rewrite_epub_entries(epub: Path) -> tuple[dict[str, bytes], list, dict]:
    """读取并改写 EPUB 全部条目。返回 (条目名->数据, 原 ZipInfo 列表, 统计)。"""
    stats = {"files": 0, "rewritten": 0, "ruby": 0, "issues": []}
    with zipfile.ZipFile(epub) as zin:
        infos = zin.infolist()
        entries: dict[str, bytes] = {}
        for info in infos:
            data = zin.read(info.filename)
            if info.filename.lower().endswith(XHTML_SUFFIXES):
                stats["files"] += 1
                try:
                    new_data, count = transform_bytes(data)
                except UnicodeDecodeError as exc:
                    stats["issues"].append(f"{info.filename}: 非 UTF-8，跳过改写（{exc}）")
                    new_data, count = data, 0
                if count:
                    stats["rewritten"] += 1
                    stats["ruby"] += count
                    data = new_data
            entries[info.filename] = data
    return entries, infos, stats


def write_epub(entries: dict[str, bytes], infos: list, out_path: Path) -> None:
    """把（改写后的）条目按原 ZipInfo 顺序与压缩方式写回 EPUB。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w") as zout:
        for info in infos:
            new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new_info.compress_type = (
                zipfile.ZIP_STORED
                if info.compress_type == zipfile.ZIP_STORED
                else zipfile.ZIP_DEFLATED)
            new_info.external_attr = info.external_attr
            new_info.comment = info.comment
            new_info.extra = info.extra
            zout.writestr(new_info, entries[info.filename])


def pack_book_dir(book: Path, destination: Path) -> None:
    """把解包书籍目录打包为 EPUB（复用 package_cache_epubs.package_book）。"""
    if package_book is not None:
        package_book(book, destination)
        return
    # 兜底：与 package_cache_epubs.package_book 相同的打包逻辑
    mimetype = book / "mimetype"
    container = book / "META-INF" / "container.xml"
    if not mimetype.is_file() or mimetype.read_bytes() != EPUB_MIMETYPE:
        raise ValueError(f"缺少合法 mimetype：{book}")
    if not container.is_file():
        raise ValueError(f"缺少 META-INF/container.xml：{book}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w") as zout:
        zout.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)
        for path in sorted(
            (p for p in book.rglob("*") if p.is_file() and p.name != "mimetype"),
            key=lambda p: p.relative_to(book).as_posix().casefold(),
        ):
            zout.write(path, path.relative_to(book).as_posix(),
                       compress_type=zipfile.ZIP_DEFLATED)


def find_ebook_convert(explicit: Path | None) -> str | None:
    """定位本机 calibre 的 ebook-convert 可执行文件。"""
    if explicit is not None:
        return str(explicit) if explicit.is_file() else None
    found = shutil.which("ebook-convert")
    if found:
        return found
    candidates = [
        r"C:\Program Files\Calibre2\ebook-convert.exe",
        r"C:\Program Files (x86)\Calibre2\ebook-convert.exe",
        "/Applications/calibre.app/Contents/MacOS/ebook-convert",
        "/opt/calibre/ebook-convert",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def expand_inputs(paths: list[str], pattern: str) -> list[Path]:
    """展开输入：.epub 文件直接收下；书籍目录收下；根目录按 pattern 收集子目录。"""
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            print(f"[跳过] 不存在：{p}")
            continue
        if p.is_file():
            if p.suffix.lower() == ".epub":
                out.append(p)
            else:
                print(f"[跳过] 不是 .epub：{p}")
            continue
        if (p / "mimetype").is_file() and (p / "META-INF" / "container.xml").is_file():
            out.append(p)  # 单个解包书目录
            continue
        pat = pattern.casefold()
        books = sorted(
            (c for c in p.iterdir()
             if c.is_dir() and not c.name.startswith(".")
             and fnmatch.fnmatch(c.name.casefold(), pat)),
            key=lambda c: c.name.casefold(),
        )
        out.extend(books)
    return out


def report(label: str, stats: dict, out_docx: Path | None, dry_run: bool) -> None:
    changed = (f"，ruby 改写 {stats['rewritten']} 个文件 / {stats['ruby']} 处")
    if dry_run:
        print(f"[{label}] XHTML {stats['files']} 个{changed}（预览，未生成 docx）")
    else:
        print(f"[{label}] XHTML {stats['files']} 个{changed} -> {out_docx}")
    for it in stats["issues"][:20]:
        print(f"  ! {it}")
    if len(stats["issues"]) > 20:
        print(f"  …另有 {len(stats['issues']) - 20} 条问题未列出")


def process_one(book: Path, args: argparse.Namespace, exe: str | None) -> int:
    """处理一本书（.epub 或解包目录）。返回 0 成功 / 1 失败。"""
    label = str(book)
    is_dir = book.is_dir()
    stem = book.name if is_dir else book.stem
    out_dir = (args.out if args.out else book.parent).resolve()
    out_docx = out_dir / f"{stem}.docx"

    with tempfile.TemporaryDirectory(prefix="epub2docx-") as tmp:
        try:
            if is_dir:
                src = Path(tmp) / f"{stem}.epub"
                pack_book_dir(book, src)
            else:
                src = book

            entries, infos, stats = rewrite_epub_entries(src)

            if args.dry_run:
                report(label, stats, out_docx, dry_run=True)
                return 0

            # 写中间 epub（--keep-src-epub 时留在源目录，否则进临时目录）
            if args.keep_src_epub:
                mid = book.parent / f"{stem}.ruby.epub"
            else:
                mid = Path(tmp) / f"{stem}.ruby.epub"
            write_epub(entries, infos, mid)

            # 调用 calibre 转换
            out_docx.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                [exe, str(mid), str(out_docx), *args.extra],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            if result.returncode != 0:
                print(f"[失败] 转换出错：{book}", file=sys.stderr)
                for line in result.stderr.strip().splitlines()[-8:]:
                    print(f"    {line}", file=sys.stderr)
                return 1

            report(label, stats, out_docx, dry_run=False)
            return 0
        except (OSError, zipfile.BadZipFile, ValueError) as exc:
            print(f"[失败] {label}：{exc}", file=sys.stderr)
            return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="把 EPUB 转成 DOCX（交稿格式），<ruby>基文<rt>注音</rt></ruby> 还原为 |基文[注音]")
    ap.add_argument("paths", nargs="+", help="一个或多个 .epub 文件或解包书籍目录")
    ap.add_argument("--out", type=Path, default=None,
                    help="docx 输出目录（默认与输入同目录）")
    ap.add_argument("--pattern", default="*",
                    help="目录输入时按书名 glob 筛选（大小写不敏感）")
    ap.add_argument("--ebook-convert", type=Path, default=None,
                    help="ebook-convert 可执行文件路径（默认自动探测）")
    ap.add_argument("--extra", action="append", default=[],
                    help="透传给 ebook-convert 的额外参数（可多次，如 --extra --docx-page-size=A4）")
    ap.add_argument("--keep-src-epub", action="store_true",
                    help="保留中间 .ruby.epub（默认用后即删）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只统计 ruby 改写，不生成 docx")
    ap.add_argument("--quiet", action="store_true", help="只打印错误与汇总")
    args = ap.parse_args()

    exe = None
    if not args.dry_run:
        exe = find_ebook_convert(args.ebook_convert)
        if exe is None:
            print("找不到 ebook-convert：请安装 calibre 或用 --ebook-convert 指定路径",
                  file=sys.stderr)
            return 2
        if not args.quiet:
            print(f"使用 calibre：{exe}")

    inputs = expand_inputs(args.paths, args.pattern)
    if not inputs:
        print("没有匹配到任何输入", file=sys.stderr)
        return 1

    ok = failed = 0
    for book in inputs:
        if process_one(book, args, exe) == 0:
            ok += 1
        else:
            failed += 1
    print(f"完成：{ok} 本成功，{failed} 本失败")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
