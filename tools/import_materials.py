#!/usr/bin/env python3
"""新书导入的材料核对门禁（只读）：材料不齐就不开工。

成品生成需要五类材料，缺任何一类都不许动手——不猜封面、不补简介、不替用户
写制作信息。本工具逐项核对并输出「齐／缺」清单，缺项时非零退出，并把要用户
补的东西写成一句可以直接发给用户的话。

必需材料（`--docx`／`--images`／`--info`／`--intro` 与作品号、日文工作源、模板书）：

| 材料 | 选项 | 合格判据 |
| --- | --- | --- |
| 交稿正文 | `--docx` | 可解析的 .docx，含 Heading 1 章标题 |
| 图片素材 | `--images` | 目录存在且非空，图片可解码（无 Pillow 时只查存在与后缀） |
| 制作信息 | `--info` | 含 `<h1` 的 Information 正文块，且带「翻译：／校对：／美工：」署名 |
| 简介 | `--intro` | ≥2 行（首行导语＋正文段） |
| 作品号 | `--work` | 形如 `S4_04`，且 `--book-dir` 以 `[作品号]` 开头 |
| 日文工作源 | `--jp-root`（＋`--work`） | 根目录下存在该作品号的日文书目录，且含内容 XHTML |
| 模板书 | `--template` | 同系列已入库书目录：`OEBPS/Styles/style.css`、`OEBPS/content.opf`、`META-INF/container.xml` 齐备 |

另需人工确认（工具不代查）：`publish_auto.py --dry-run` 三副本无待发布改动。

用法：
    python tools/import_materials.py --docx 交稿.docx --images 图片目录 --info info.txt \
        --intro intro.txt --work S4_04 --book-dir "[S4_04]某暗部的少女共栖 4X" \
        --jp-root .cache/epub-work/japanese-text --template "EPUB/[S4_03]某暗部的少女共栖 3X"
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from docx_source import read_docx, split_chapters
from epub_ids import book_id
from image_signature import IMAGE_SUFFIXES, dimensions, pillow_available

OK = "齐"
MISSING = "缺"


def check_docx(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"交稿不存在：{path}"
    try:
        paragraphs, _, _, _ = read_docx(path, collapse_whitespace=False)
    except (OSError, ValueError, KeyError) as exc:
        return False, f"交稿无法解析：{exc}"
    chapters = [c for c in split_chapters(paragraphs) if c["title"]]
    if not chapters:
        return False, "交稿没有 Heading 1 章标题"
    return True, f"{len(paragraphs)} 段、{len(chapters)} 章（{'／'.join(c['title'][:12] for c in chapters[:4])}…）"


def check_images(directory: Path) -> tuple[bool, str]:
    if not directory.is_dir():
        return False, f"图片素材目录不存在：{directory}"
    files = [p for p in sorted(directory.iterdir())
             if p.is_file() and p.suffix.casefold() in IMAGE_SUFFIXES]
    if not files:
        return False, f"图片素材目录里没有图片：{directory}"
    if not pillow_available():
        return True, f"{len(files)} 张（未安装 Pillow，只核对了存在与后缀）"
    broken = [p.name for p in files if dimensions(p) is None]
    if broken:
        return False, f"{len(files)} 张，其中无法解码：{broken[:5]}"
    prefixed = sum(1 for p in files if re.match(r"^\[?S\d+_\d+", p.name))
    return True, f"{len(files)} 张（{prefixed} 张已带作品号前缀，其余须在计划里映射）"


def check_page_block(path: Path, label: str, require_roles: bool = False) -> tuple[bool, str]:
    """包装页正文块：页面 L4 起的内容行，第 1 行是 h1、第 2 行是空行占位。"""
    if not path.is_file():
        return False, f"{label}不存在：{path}"
    raw = path.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()
    if len(lines) < 2:
        return False, f"{label}至少要有 h1 与空行占位两行"
    if "<h1" not in lines[0]:
        return False, f"{label}第 1 行必须是 `<h1>` 标题行：{lines[0][:40]!r}"
    if lines[1].strip():
        return False, f"{label}第 2 行必须留空（固定行模板的 L5 空行占位）：{lines[1][:40]!r}"
    if require_roles:
        roles = [name for name in ("翻译：", "校对：", "美工：") if name in raw]
        if len(roles) < 3:
            return False, f"{label}署名不全，只看到：{roles}"
        return True, f"{len(lines)} 行，署名 {len(roles)} 项"
    return True, f"{len(lines)} 行"


def check_intro(path: Path) -> tuple[bool, str]:
    return check_page_block(path, "简介")


def check_info(path: Path) -> tuple[bool, str]:
    return check_page_block(path, "制作信息", require_roles=True)


def check_work(work: str, book_dir: str) -> tuple[bool, str]:
    if not re.fullmatch(r"S\d+_\d+(?:_\d+)?", work):
        return False, f"作品号形状异常：{work}"
    if not book_dir:
        return False, "缺少 --book-dir（中文书目录名）"
    if book_id(book_dir) != work.upper():
        return False, f"书目录名 {book_dir!r} 与作品号 {work} 不一致（应以 [{work}] 开头）"
    return True, f"{work} → {book_dir}"


def check_jp(jp_root: Path, work: str) -> tuple[bool, str]:
    if not jp_root.is_dir():
        return False, f"日文参考根目录不存在：{jp_root}"
    for child in sorted(jp_root.iterdir()):
        if child.is_dir() and (book_id(child.name) or "").upper() == work.upper():
            pages = list(child.rglob("*.xhtml"))
            if not pages:
                return False, f"日文书目录里没有 XHTML：{child}"
            return True, f"{child.name}（{len(pages)} 个 XHTML）"
    return False, f"{jp_root} 下找不到 {work} 的日文书目录；先把日文原文同步进缓存"


def check_template(path: Path) -> tuple[bool, str]:
    if not path.is_dir():
        return False, f"模板书目录不存在：{path}"
    needed = ("OEBPS/Styles/style.css", "OEBPS/content.opf", "META-INF/container.xml")
    missing = [name for name in needed if not (path / name).is_file()]
    if missing:
        return False, f"模板书缺少：{missing}"
    return True, str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="新书导入的材料核对门禁（只读）：材料不齐就不开工")
    parser.add_argument("--docx", type=Path, default=None, help="交稿 .docx")
    parser.add_argument("--images", type=Path, default=None, help="图片素材目录")
    parser.add_argument("--info", type=Path, default=None, help="制作信息正文块文件")
    parser.add_argument("--intro", type=Path, default=None, help="简介正文块文件")
    parser.add_argument("--work", default=None, help="作品号，如 S4_04")
    parser.add_argument("--book-dir", default="", help="中文书目录名")
    parser.add_argument("--jp-root", type=Path, default=Path(".cache/epub-work/japanese-text"),
                        help="日文只读参考根目录")
    parser.add_argument("--template", type=Path, default=None, help="模板书目录（同系列已入库的一卷）")
    args = parser.parse_args(argv)

    missing_options = [name for name, value in (
        ("--docx", args.docx), ("--images", args.images), ("--info", args.info),
        ("--intro", args.intro), ("--work", args.work), ("--template", args.template),
    ) if not value]
    rows: list[tuple[str, str, str]] = []
    if args.docx:
        rows.append(("交稿正文", *check_docx(args.docx)))
    if args.images:
        rows.append(("图片素材", *check_images(args.images)))
    if args.info:
        rows.append(("制作信息", *check_info(args.info)))
    if args.intro:
        rows.append(("简介", *check_intro(args.intro)))
    if args.work:
        rows.append(("作品号", *check_work(args.work, args.book_dir)))
        rows.append(("日文工作源", *check_jp(args.jp_root, args.work)))
    if args.template:
        rows.append(("模板书", *check_template(args.template)))

    print("材料核对：")
    for name, ok, detail in rows:
        print(f"  [{OK if ok else MISSING}] {name}：{detail}")

    problems: list[str] = []
    if missing_options:
        problems.append("未提供：" + "、".join(missing_options))
    problems += [f"{name}（{detail}）" for name, ok, detail in rows if not ok]
    if problems:
        print("\n材料不齐，不进入生成流程。请补齐以下材料后重跑本命令：")
        for item in problems:
            print(f"  - {item}")
        print("\n提示：成品生成需要「交稿正文、图片素材（封面/彩页/正文插图）、制作信息、"
              "简介、作品号与书目录名、日文原文、模板书」七项；缺项请向用户索取，"
              "不要自行编造封面、简介或制作信息。")
        return 1
    print("\n材料齐备，可以进入 import_docx_outline.py → import_align_plan.py 流程。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
