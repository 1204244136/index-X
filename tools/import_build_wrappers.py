#!/usr/bin/env python3
"""正文 + 计划 + 素材 → 包装页与容器文件（nav/ncx/opf/mimetype/container/style.css）。

新书导入第 4 步，只写包装页（Cover／Illustrations／Information／Introduction）与
容器文件；正文与 Note 由 `import_build_text.py` 负责，图片由 `import_images.py`
负责，三者写作用域互不重叠。

前置（缺一即阻断，不写盘）：
* `<书目录>/OEBPS/Text/` 已有计划里的全部章节文件（`fname`）；
* 计划里登记了 `role=cover` 与 `role=illustration` 的图片，且对应文件已在
  `OEBPS/Images/`（先跑 `import_images.py`）；
* 模板书齐备（`OEBPS/Styles/style.css`、`OEBPS/content.opf`、`META-INF/container.xml`）。

`--info`／`--intro` 是页面 **L4 起**的内容行（第 1 行 h1、第 2 行空行占位），
由用户提供的素材决定，工具不内置汉化组署名或简介文本。

用法：
    python tools/import_build_wrappers.py plan.json --template "EPUB/[S4_03]…" \
        --info info.txt --intro intro.txt --out 暂存目录/书目录 --apply --staging
"""
from __future__ import annotations

import argparse
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from docx_source import esc
from edit_safety import EditSafetyError, add_edit_mode, require_edit_target
from file_transaction import atomic_write_bytes, rollback_paths
from import_plan import PlanError, load_plan

HEAD3 = ('<html xmlns="http://www.w3.org/1999/xhtml" '
         'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
         '<link href="../Styles/style.css" rel="stylesheet" type="text/css"/>'
         "<title></title></head><body>")
TEMPLATE_FILES = ("OEBPS/Styles/style.css", "OEBPS/content.opf", "META-INF/container.xml")


def page_document(body_lines: list[str]) -> str:
    return "\n".join(["<?xml version='1.0' encoding='utf-8'?>", "<!DOCTYPE html>", HEAD3,
                      *body_lines, "</body></html>"]) + "\n"


def render_cover(cover: str) -> str:
    return ("<?xml version='1.0' encoding='utf-8'?>\n<!DOCTYPE html>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops">\n<br/>\n<head>\n'
            '<link href="../Styles/style.css" rel="stylesheet" type="text/css"/>\n'
            "<title></title>\n</head>\n<body epub:type=\"cover\">\n"
            f'<div class="center"><img alt="图像" class="fit" src="../Images/{cover}"/></div>'
            "</body></html>\n")


def render_illustrations(names: list[str]) -> str:
    body = "\n".join(f'<p><img alt="图片" class="fit" src="../Images/{name}" /></p>'
                     for name in names)
    return "\n".join(["<?xml version='1.0' encoding='utf-8'?>", "<!DOCTYPE html>", HEAD3,
                      body, "</body></html>"]) + "\n"


def render_nav(entries: list[tuple[str, str, int]]) -> str:
    lines = ["<?xml version='1.0' encoding='utf-8'?>", "<!DOCTYPE html>",
             '<html xmlns="http://www.w3.org/1999/xhtml" '
             'xmlns:epub="http://www.idpf.org/2007/ops" lang="zh" xml:lang="zh">',
             "<br/>", "    <head>", "        <title>Navigation</title>", "    </head>",
             "    <body>", '    <nav epub:type="toc">', "  <ol>"]
    for name, title, sections in entries:
        href = f"OEBPS/Text/{name}"
        if sections:
            lines.append("    <li>")
            lines.append(f'      <a href="{href}">{title}</a>')
            lines.append("      <ol>")
            for number in range(1, sections + 1):
                lines.append(f'        <li><a href="{href}#toc_{number}">{number}</a></li>')
            lines.append("      </ol>")
            lines.append("    </li>")
        else:
            lines.append(f'    <li><a href="{href}">{title}</a></li>')
    lines += ["  </ol>", "</nav>", "</body></html>"]
    return "\n".join(lines) + "\n"


def render_ncx(entries: list[tuple[str, str, int]], title: str, uid: str) -> str:
    lines = ["<?xml version='1.0' encoding='utf-8'?>",
             '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="zh">',
             "  <head>", f'    <meta name="dtb:uid" content="{uid}"/>',
             '    <meta name="dtb:depth" content="3"/>',
             '    <meta name="dtb:generator" content="calibre (8.16.2)"/>',
             '    <meta name="dtb:totalPageCount" content="0"/>',
             '    <meta name="dtb:maxPageNumber" content="0"/>', "  </head>",
             "  <docTitle>", f"    <text>{esc(title)}</text>", "  </docTitle>", "  <navMap>"]
    order = 0
    for name, label, sections in entries:
        order += 1
        lines += [f'    <navPoint id="num_{order}" playOrder="{order}">',
                  "      <navLabel>", f"        <text>{esc(label)}</text>", "      </navLabel>",
                  f'      <content src="OEBPS/Text/{name}"/>']
        for number in range(1, sections + 1):
            order += 1
            lines += [f'      <navPoint id="num_{order}" playOrder="{order}">',
                      "        <navLabel>", f"          <text>{number}</text>",
                      "        </navLabel>",
                      f'        <content src="OEBPS/Text/{name}#toc_{number}"/>',
                      "      </navPoint>"]
        lines.append("    </navPoint>")
    lines += ["  </navMap>", "</ncx>"]
    return "\n".join(lines) + "\n"


def description_of(intro_lines: list[str]) -> str:
    """把简介正文块转成 OPF 的 dc:description（首行加粗，丢弃空行与 `<br/>`）。"""
    paragraphs = []
    for line in intro_lines:
        if line.strip() in ("", "<br/>") or "<h1" in line:
            continue
        text = re.sub(r"</?b>", "", line)
        text = re.sub(r"^<p\b[^>]*>|</p>$", "", text.strip())
        paragraphs.append(text)
    if not paragraphs:
        raise PlanError("简介里没有可用的正文段")
    parts = [f'<p style="font-weight: bold">{paragraphs[0]}</p>']
    parts += [f"<p>{text}</p>" for text in paragraphs[1:]]
    return "<div>\n" + "\n".join(parts) + "</div>"


def render_opf(plan: dict, text_order: list[str], uid: str, author: str, description: str,
               template_opf: str, cover: str, images: list[str],
               calibre_id: str = "") -> str:
    image_names = [cover] + [name for name in images if name != cover]
    items = []
    for number, name in enumerate(text_order, 1):
        items.append(f'    <item id="id-t{number}" href="Text/{name}" '
                     'media-type="application/xhtml+xml"/>')
    items.append('    <item id="nav" href="../nav.xhtml" media-type="application/xhtml+xml" '
                 'properties="nav"/>')
    items.append('    <item href="../toc.ncx" id="ncx" media-type="application/x-dtbncx+xml"/>')
    items.append('    <item id="id-css" href="Styles/style.css" media-type="text/css"/>')
    for number, name in enumerate(image_names, 1):
        if name == cover:
            items.append(f'    <item id="cover" href="Images/{name}" media-type="image/jpeg" '
                         'properties="cover-image"/>')
        else:
            items.append(f'    <item id="id-img-{number}" href="Images/{name}" '
                         'media-type="image/jpeg"/>')
    spine = "\n".join(f'    <itemref idref="id-t{number}"/>'
                      for number in range(1, len(text_order) + 1))
    user_metadata = re.search(r'<meta property="calibre:user_metadata">.*?</meta>',
                              template_opf, re.DOTALL)
    metadata_block = ""
    if user_metadata:
        # 只给块首行补缩进：块内是 calibre 写出的 JSON，改缩进会破坏字节一致性
        block = user_metadata.group(0).splitlines()
        metadata_block = "\n".join(["    " + block[0], *block[1:]])
    calibre_identifier = (f"    <dc:identifier>calibre:{calibre_id}</dc:identifier>\n"
                          if calibre_id else "")
    book_dir = plan["book_dir"]
    return f'''<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="3.0" prefix="calibre: https://calibre-ebook.com">
  <metadata xmlns:opf="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title id="id-1">{esc(book_dir)}</dc:title>
    <dc:creator id="id-2">{esc(author)}</dc:creator>
{calibre_identifier}    <dc:identifier>{uid}</dc:identifier>
    <dc:identifier id="BookId">{uid}</dc:identifier>
    <dc:language>zh-CN</dc:language>
    <dc:contributor id="id-28">calibre (8.16.2) [https://calibre-ebook.com]</dc:contributor>
    <dc:description>{esc(description)}</dc:description>
    <dc:subject>重小说</dc:subject>
    <meta refines="#id-1" property="title-type">main</meta>
    <meta refines="#id-1" property="file-as">{esc(book_dir)}</meta>
    <meta property="dcterms:modified" scheme="dcterms:W3CDTF">{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}</meta>
{metadata_block}
    <meta refines="#id-28" property="role" scheme="marc:relators">bkp</meta>
    <meta refines="#id-2" property="role" scheme="marc:relators">aut</meta>
    <meta refines="#id-2" property="file-as">{esc(author)}</meta>
    <meta property="calibre:rating">10</meta>
  </metadata>
  <manifest>
{chr(10).join(items)}
  </manifest>
  <spine toc="ncx">
{spine}
  </spine>
</package>
'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="正文 + 计划 + 素材 → 包装页与容器文件")
    parser.add_argument("plan", type=Path, help="导入计划 plan.json")
    parser.add_argument("--template", type=Path, required=True, help="模板书目录（同系列已入库的一卷）")
    parser.add_argument("--info", type=Path, required=True, help="制作信息页正文块（L4 起）")
    parser.add_argument("--intro", type=Path, required=True, help="简介页正文块（L4 起）")
    parser.add_argument("--out", type=Path, required=True, help="书目录（读 OEBPS/Text，写包装页与容器文件）")
    parser.add_argument("--author", default="镰池和马", help="作者署名")
    parser.add_argument("--calibre-id", default="", help="可选的 calibre 库号（写入 dc:identifier）")
    parser.add_argument("--report", type=Path, help="报告输出文件")
    add_edit_mode(parser)
    args = parser.parse_args(argv)

    try:
        plan = load_plan(args.plan)
    except PlanError as exc:
        print(f"[阻断] {exc}")
        return 2
    missing_template = [name for name in TEMPLATE_FILES if not (args.template / name).is_file()]
    if missing_template:
        print(f"[阻断] 模板书缺少：{missing_template}")
        return 2
    for page, path in (("制作信息", args.info), ("简介", args.intro)):
        if not path.is_file():
            print(f"[阻断] {page}正文块不存在：{path}")
            return 2

    text_dir = args.out / "OEBPS" / "Text"
    image_dir = args.out / "OEBPS" / "Images"
    work_id = plan["work_id"]
    report: list[str] = []
    text_order: list[str] = []
    entries: list[tuple[str, str, int]] = []
    problems: list[str] = []

    cover = next((entry["dst"] for entry in plan["images"] if entry["role"] == "cover"), None)
    illustrations = [entry["dst"] for entry in plan["images"] if entry["role"] == "illustration"]
    if not cover:
        problems.append("计划里没有 role=cover 的图片（封面是必需材料）")
    if not illustrations:
        problems.append("计划里没有 role=illustration 的彩页图片")
    for name in ([cover] if cover else []) + illustrations:
        if not (image_dir / name).is_file():
            problems.append(f"图片尚未就位：{name}；先跑 import_images.py")

    for name in [f"{work_id}-Cover.xhtml", f"{work_id}-Information.xhtml",
                 f"{work_id}-Introduction.xhtml", f"{work_id}-Illustrations.xhtml"]:
        text_order.append(name)
    for chapter in plan["chapters"]:
        path = text_dir / chapter["fname"]
        if not path.is_file():
            problems.append(f"正文文件不存在：{chapter['fname']}；先跑 import_build_text.py")
            continue
        text_order.append(chapter["fname"])
        if chapter.get("nav"):
            sections = len(re.findall(r"^<h2\b", path.read_text(encoding="utf-8"), re.M))
            entries.append((chapter["fname"], chapter["nav"], sections))
            report.append(f"{chapter['fname']}：目录条目《{chapter['nav']}》+ {sections} 个小节")
    note_file = f"{work_id}-Note.xhtml"
    if (text_dir / note_file).is_file():
        text_order.append(note_file)
        report.append(f"{note_file}：译注页（不进目录，排在 spine 末尾）")

    if problems:
        print("包装页与容器文件未生成：")
        for item in problems:
            print(f"  - {item}")
        return 1

    pages = {
        text_order[0]: render_cover(cover),
        text_order[1]: page_document(args.info.read_text(encoding="utf-8-sig").splitlines()),
        text_order[2]: page_document(args.intro.read_text(encoding="utf-8-sig").splitlines()),
        text_order[3]: render_illustrations(illustrations),
    }
    nav_entries = [(f"{work_id}-Information.xhtml", "制作信息", 0),
                   (f"{work_id}-Introduction.xhtml", "简介", 0)] + entries
    uid = f"uuid:{uuid.uuid4()}"
    description = description_of(args.intro.read_text(encoding="utf-8-sig").splitlines())
    template_opf = (args.template / "OEBPS" / "content.opf").read_text(encoding="utf-8")
    all_images = [entry["dst"] for entry in plan["images"]]
    documents = {
        "nav.xhtml": render_nav(nav_entries),
        "toc.ncx": render_ncx(nav_entries, plan["book_dir"], uid),
        "OEBPS/content.opf": render_opf(plan, text_order, uid, args.author, description,
                                        template_opf, cover, all_images, args.calibre_id),
    }
    print("\n".join(report))
    print(f"将写入包装页 {len(pages)} 个、容器文件 {len(documents)} 个、样式表与 container.xml 各 1 个")

    if not args.apply:
        print("[预览] 加 --apply 写盘")
        return 0
    try:
        target = require_edit_target(args.out, args.staging)
    except EditSafetyError as exc:
        print(f"[阻断] {exc}")
        return 2
    with rollback_paths([target]):
        for name, content in pages.items():
            atomic_write_bytes(target / "OEBPS" / "Text" / name, content.encode("utf-8"))
        for name, content in documents.items():
            atomic_write_bytes(target / name, content.encode("utf-8"))
        atomic_write_bytes(target / "mimetype", b"application/epub+zip")
        for name in ("OEBPS/Styles/style.css", "META-INF/container.xml"):
            atomic_write_bytes(target / name, (args.template / name).read_bytes())
    print(f"已写入：{target}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
