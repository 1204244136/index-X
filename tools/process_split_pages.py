#!/usr/bin/env python3
"""
旧版分页 EPUB 生成器：保持分页结构，每个页面独立文件。

此入口仅用于复现旧产物；新维护流程使用 bw_preprocess.py +
merge_bw_pages.py，避免与固定行模板、跨页衔接规则形成两套实现。

用法：
    python process_split_pages.py <preprocessed_dir> --book S4_05 --out <output_dir>

流程：
    1. 读取所有预处理后的分页 XHTML
    2. 规范化每个分页（独立处理）
    3. 将标题 <p class="font-1em30"> 转换为 <h1>
    4. 重命名为标准格式：S4_05-01_p-001.xhtml
    5. 生成完整 EPUB 结构（content.opf, toc.ncx, nav.xhtml）
    6. 打包成 EPUB
"""

import argparse
import re
import shutil
import zipfile
from pathlib import Path
from datetime import datetime


def normalize_page(xhtml_path: Path) -> tuple[str, str]:
    """规范化单个分页，返回 (标题, 规范化内容)"""
    content = xhtml_path.read_text(encoding='utf-8')

    # 转换标题：<p class="font-1em30"> -> <h1>
    # AGENTS.md 规定 font-1em10/30 的 p 型标题都重建为 h1。
    content = re.sub(
        r'<p\s+class="font-1em30"([^>]*)>(.*?)</p>',
        r'<h1\1>\2</h1>',
        content,
        flags=re.DOTALL
    )
    content = re.sub(
        r'<p\s+class="font-1em10"([^>]*)>(.*?)</p>',
        r'<h1\1>\2</h1>',
        content,
        flags=re.DOTALL
    )

    # 转换 <p class="start-3em"> -> <h1>
    content = re.sub(
        r'<p\s+class="start-3em"([^>]*)>(.*?)</p>',
        r'<h1\1>\2</h1>',
        content,
        flags=re.DOTALL
    )

    # 提取标题
    title_match = re.search(r'<h1[^>]*>(.*?)</h1>', content, re.DOTALL)
    title = ""
    if title_match:
        # 清理 HTML 标签（保留 ruby 内容）
        title_html = title_match.group(1)
        # 移除 ruby 的 rt 标签
        title_clean = re.sub(r'<rt>.*?</rt>', '', title_html)
        # 移除所有其他标签
        title_clean = re.sub(r'<[^>]+>', '', title_clean)
        title = title_clean.strip()

    # 规范化路径：../style/ -> ../Styles/, ../image/ -> ../Images/
    content = content.replace('href="../style/', 'href="../Styles/')
    content = content.replace('src="../image/', 'src="../Images/')
    content = content.replace('xlink:href="../image/', 'xlink:href="../Images/')

    # 压缩 HTML 头部为紧凑格式（正文从第 6 行开始）
    # 解析 XML 声明和 DOCTYPE
    xml_decl_match = re.search(r'<\?xml[^>]+\?>', content)
    doctype_match = re.search(r'<!DOCTYPE[^>]+>', content)

    # 提取 html 标签属性
    html_match = re.search(r'<html([^>]*)>', content, re.DOTALL)
    html_attrs = html_match.group(1).strip() if html_match else ''

    # 提取 head 内容
    head_match = re.search(r'<head>(.*?)</head>', content, re.DOTALL)
    head_content = head_match.group(1).strip() if head_match else ''

    # 提取 body 内容
    body_match = re.search(r'<body[^>]*>(.*)</body>', content, re.DOTALL)
    body_content = body_match.group(0) if body_match else '<body></body>'

    # 重新组装为紧凑格式
    xml_decl = xml_decl_match.group(0) if xml_decl_match else '<?xml version=\'1.0\' encoding=\'utf-8\'?>'
    doctype = doctype_match.group(0) if doctype_match else '<!DOCTYPE html>'

    # 压缩 head 内的多个标签为一行
    head_lines = []
    for line in head_content.split('\n'):
        line = line.strip()
        if line:
            head_lines.append(line)
    head_compact = ''.join(head_lines)

    # 构建紧凑的 HTML（前 5 行 + 正文从第 6 行开始）
    compact_html = f"""{xml_decl}
{doctype}
<html {html_attrs}><head>{head_compact}</head>{body_content}</html>"""

    return title, compact_html


def generate_opf(book_id: str, book_title: str, page_info: list, output_dir: Path):
    """生成 content.opf"""

    manifest_items = []
    spine_items = []

    # 添加导航和样式
    manifest_items.append('    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
    manifest_items.append('    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')

    # 添加样式文件
    styles_dir = output_dir / "OEBPS" / "Styles"
    for css in sorted(styles_dir.glob("*.css")):
        css_id = css.stem.replace('-', '_')
        manifest_items.append(f'    <item id="style_{css_id}" href="Styles/{css.name}" media-type="text/css"/>')

    # 添加分页
    for info in page_info:
        manifest_items.append(f'    <item id="{info["id"]}" href="{info["href"]}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'    <itemref idref="{info["id"]}"/>')

    # 添加图片
    images_dir = output_dir / "OEBPS" / "Images"
    if images_dir.exists():
        for idx, img in enumerate(sorted(images_dir.glob("*")), 1):
            if img.is_file():
                media_type = "image/jpeg" if img.suffix.lower() in ['.jpg', '.jpeg'] else "image/png"
                manifest_items.append(f'    <item id="img_{idx:03d}" href="Images/{img.name}" media-type="{media_type}"/>')

    opf_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookID" xml:lang="ja">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookID">urn:uuid:{book_id.lower()}</dc:identifier>
    <dc:title>{book_title}</dc:title>
    <dc:creator>鎌池和馬</dc:creator>
    <dc:language>ja</dc:language>
    <meta property="dcterms:modified">{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}</meta>
  </metadata>
  <manifest>
{chr(10).join(manifest_items)}
  </manifest>
  <spine toc="ncx">
{chr(10).join(spine_items)}
  </spine>
</package>
'''

    opf_file = output_dir / "OEBPS" / "content.opf"
    opf_file.write_text(opf_content, encoding='utf-8')
    print("  生成 content.opf")


def generate_nav(book_title: str, page_info: list, output_dir: Path):
    """生成 nav.xhtml"""

    nav_items = []
    for info in page_info:
        if info['title']:
            nav_items.append(f'      <li><a href="{info["href"]}">{info["title"]}</a></li>')

    nav_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="ja">
<head>
  <meta charset="UTF-8"/>
  <title>目次</title>
</head>
<body>
  <nav epub:type="toc">
    <h1>目次</h1>
    <ol>
{chr(10).join(nav_items)}
    </ol>
  </nav>
</body>
</html>
'''

    nav_file = output_dir / "OEBPS" / "nav.xhtml"
    nav_file.write_text(nav_content, encoding='utf-8')
    print("  生成 nav.xhtml")


def generate_ncx(book_id: str, book_title: str, page_info: list, output_dir: Path):
    """生成 toc.ncx"""

    navpoints = []
    play_order = 1
    for info in page_info:
        if info['title']:
            navpoints.append(f'''    <navPoint id="{info['id']}" playOrder="{play_order}">
      <navLabel>
        <text>{info['title']}</text>
      </navLabel>
      <content src="{info['href']}"/>
    </navPoint>''')
            play_order += 1

    ncx_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="urn:uuid:{book_id.lower()}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle>
    <text>{book_title}</text>
  </docTitle>
  <navMap>
{chr(10).join(navpoints)}
  </navMap>
</ncx>
'''

    ncx_file = output_dir / "OEBPS" / "toc.ncx"
    ncx_file.write_text(ncx_content, encoding='utf-8')
    print("  生成 toc.ncx")


def generate_container(output_dir: Path):
    """生成 META-INF/container.xml"""

    container_content = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
'''

    meta_dir = output_dir / "META-INF"
    meta_dir.mkdir(exist_ok=True)

    container_file = meta_dir / "container.xml"
    container_file.write_text(container_content, encoding='utf-8')
    print("  生成 META-INF/container.xml")


def generate_mimetype(output_dir: Path):
    """生成 mimetype"""
    mimetype_file = output_dir / "mimetype"
    mimetype_file.write_text("application/epub+zip", encoding='utf-8')
    print("  生成 mimetype")


def pack_epub(source_dir: Path, output_file: Path):
    """打包 EPUB"""

    with zipfile.ZipFile(output_file, 'w') as epub:
        # mimetype 必须未压缩且在第一位
        epub.write(source_dir / 'mimetype', 'mimetype', compress_type=zipfile.ZIP_STORED)

        # 其他文件
        for path in source_dir.rglob('*'):
            if path.is_file() and path.name != 'mimetype':
                arcname = path.relative_to(source_dir)
                epub.write(path, arcname, compress_type=zipfile.ZIP_DEFLATED)

    size_mb = output_file.stat().st_size / 1024 / 1024
    print(f"\n  打包完成：{output_file.name}")
    print(f"  文件大小：{size_mb:.2f} MB")


def process_split_pages(input_dir: Path, book_id: str, book_title: str, output_dir: Path, pack: bool = True):
    """处理分页 EPUB，保持分页结构"""

    xhtml_dir = input_dir / "xhtml"
    if not xhtml_dir.exists():
        raise ValueError(f"XHTML 目录不存在：{xhtml_dir}")

    # 创建输出目录结构
    output_xhtml = output_dir / "OEBPS" / "Text"
    output_styles = output_dir / "OEBPS" / "Styles"
    output_images = output_dir / "OEBPS" / "Images"

    output_xhtml.mkdir(parents=True, exist_ok=True)
    output_styles.mkdir(parents=True, exist_ok=True)
    output_images.mkdir(parents=True, exist_ok=True)

    # 获取所有 XHTML 文件（包括正文和元数据页）
    all_xhtml = list(xhtml_dir.glob("*.xhtml"))

    # 按照正确的顺序排序（参考 S4_01 标准）
    def sort_key(path):
        name = path.stem
        # 定义元数据页面的顺序
        metadata_order = {
            'p-cover': 1,
            'p-fmatter-001': 2,
            'p-fmatter-002': 3,
            'p-fmatter-003': 4,
            'p-fmatter-004': 5,
            'p-titlepage': 6,
            'p-caution': 7,
            'p-toc-001': 8,
            # 正文分页：9-1000（按数字排序）
            'p-bmatter-001': 10001,
            'p-allcover-001': 10002,
            'p-colophon': 10003,
            'p-colophon2': 10004,
            'p-bookwalker': 10005,
        }

        if name in metadata_order:
            return metadata_order[name]
        elif name.startswith('p-') and name.split('-')[1].isdigit():
            # 正文分页：p-001, p-002, ... -> 9+数字
            return 9 + int(name.split('-')[1])
        else:
            # 其他未知页面放在最后
            return 20000

    all_pages = sorted(all_xhtml, key=sort_key)

    # 预处理：合并需要合并的页面（如 p-007 + p-008 + p-009）
    merged_pages = []
    skip_next = set()

    for i, page_path in enumerate(all_pages):
        if page_path in skip_next:
            continue

        # 检查是否需要合并后续页面（只对正文分页执行）
        if page_path.stem.startswith('p-') and len(page_path.stem.split('-')) == 2 and page_path.stem.split('-')[1].isdigit():
            # 收集需要合并的后续页面
            pages_to_merge = [page_path]
            j = i + 1

            while j < len(all_pages):
                next_page = all_pages[j]
                next_stem = next_page.stem

                # 只考虑紧邻的正文分页
                if not (next_stem.startswith('p-') and len(next_stem.split('-')) == 2 and next_stem.split('-')[1].isdigit()):
                    break

                # 检查页码是否连续
                current_num = int(page_path.stem.split('-')[1])
                next_num = int(next_stem.split('-')[1])
                if next_num != current_num + len(pages_to_merge):
                    break

                next_content = next_page.read_text(encoding='utf-8')

                # 判断是否为小段落页面或插图页面（需要合并）
                # 不能包含新的章节标题（font-1em30, start-3em）
                if 'font-1em30' in next_content or 'class="start-3em"' in next_content:
                    break

                main_match = re.search(r'<div class="main">(.*?)</div>', next_content, re.DOTALL)
                if main_match:
                    main_content = main_match.group(1).strip()
                    # 如果主体内容很短（< 200 字符），或者是纯插图页，则合并
                    if len(main_content) < 200 or 'class="p-image"' in next_content or ('<img' in main_content and len(main_content) < 300):
                        pages_to_merge.append(next_page)
                        skip_next.add(next_page)
                        j += 1
                    else:
                        break
                else:
                    break

            # 如果有需要合并的页面，进行合并
            if len(pages_to_merge) > 1:
                merged_pages.append(('merged', pages_to_merge))
            else:
                merged_pages.append(('single', page_path))
        else:
            merged_pages.append(('single', page_path))

    print(f"\n找到 {len(all_pages)} 个 XHTML 文件")
    print(f"合并后：{len(merged_pages)} 个文件")
    print("正在处理...")

    # 处理每个文件（包括合并的）
    page_info = []
    text_page_idx = 1
    for page_type, page_data in merged_pages:
        if page_type == 'single':
            page_path = page_data
            # 读取并规范化
            title, content = normalize_page(page_path)
        else:  # merged
            # 合并多个页面
            pages_to_merge = page_data
            page_path = pages_to_merge[0]

            # 读取主页面
            title, base_content = normalize_page(page_path)

            # 提取主页面的 body 内容
            body_match = re.search(r'(<body[^>]*>)(.*)(</body>)', base_content, re.DOTALL)
            if body_match:
                body_start = body_match.group(1)
                body_content = body_match.group(2)
                body_end = body_match.group(3)

                # 合并后续页面的内容
                for merge_page in pages_to_merge[1:]:
                    _, merge_content = normalize_page(merge_page)
                    merge_body_match = re.search(r'<body[^>]*>(.*)</body>', merge_content, re.DOTALL)
                    if merge_body_match:
                        merge_body = merge_body_match.group(1)
                        # 提取 main div 的内容
                        merge_main_match = re.search(r'<div class="main">(.*?)</div>', merge_body, re.DOTALL)
                        if merge_main_match:
                            merge_main_content = merge_main_match.group(1).strip()
                            # 将合并内容追加到主体末尾（在 </div></body> 之前）
                            body_content = body_content.rstrip()
                            if not body_content.endswith('</div>'):
                                body_content += '\n'
                            # 插入到 main div 结束前
                            body_content = re.sub(
                                r'(</div>\s*)$',
                                f'\n{merge_main_content}\n\\1',
                                body_content
                            )

                # 重组内容
                content = base_content.replace(body_start + body_match.group(2) + body_end, body_start + body_content + body_end)

        # 生成新文件名
        if page_path.stem.startswith('p-'):
            # 检查是否为纯数字正文分页（p-001, p-002）
            parts = page_path.stem.split('-')
            if len(parts) == 2 and parts[1].isdigit():
                # 判断是否为宣传插图页（固定布局 + SVG 图片）
                if 'fixed-layout-jp.css' in content and '<svg' in content:
                    # 宣传插图页：S4_05-p-014.xhtml（不带序号）
                    new_name = f"{book_id}-{page_path.name}"
                else:
                    # 正文分页：p-001 -> S4_05-01_p-001.xhtml（带序号）
                    new_name = f"{book_id}-{text_page_idx:02d}_{page_path.name}"
                    text_page_idx += 1
            else:
                # 元数据页：p-cover, p-fmatter-001, p-toc-001 等 -> S4_05-p-cover.xhtml（不带序号）
                new_name = f"{book_id}-{page_path.name}"
        else:
            # 其他文件直接使用原名
            new_name = f"{book_id}-{page_path.name}"

        # 写入输出
        output_file = output_xhtml / new_name
        output_file.write_text(content, encoding='utf-8')

        page_info.append({
            'id': f"page-{page_path.stem}",
            'href': f"Text/{new_name}",
            'title': title or page_path.stem
        })

        title_display = f" - {title[:30]}" if title else ""
        print(f"  [{len(page_info):02d}/{len(all_pages)}] {page_path.name} -> {new_name}{title_display}")

    # 复制样式
    print("\n复制资源文件...")
    style_src = input_dir / "style"
    if style_src.exists():
        for css in style_src.glob("*.css"):
            # 复制所有 CSS 文件（保持原样，不清理）
            shutil.copy2(css, output_styles / css.name)
            print(f"  复制样式：{css.name}")

    # 复制图片
    image_src = input_dir / "image"
    if image_src.exists():
        img_count = 0
        for img in image_src.glob("*"):
            if img.is_file():
                shutil.copy2(img, output_images / img.name)
                img_count += 1
        print(f"  复制图片：{img_count} 个")

    # 生成 EPUB 元数据
    print("\n生成 EPUB 元数据...")
    generate_opf(book_id, book_title, page_info, output_dir)
    generate_nav(book_title, page_info, output_dir)
    generate_ncx(book_id, book_title, page_info, output_dir)
    generate_container(output_dir)
    generate_mimetype(output_dir)

    # 打包 EPUB
    if pack:
        print("\n打包 EPUB...")
        epub_file = output_dir.parent / f"[{book_id}]{book_title}.epub"
        pack_epub(output_dir, epub_file)

    print(f"\n处理完成：{len(page_info)} 个分页")
    print(f"输出目录：{output_dir}")

    return page_info


def main():
    parser = argparse.ArgumentParser(description="旧版分页 EPUB 生成器（仅用于复现旧产物）")
    parser.add_argument("input_dir", type=Path, help="预处理后的目录（包含 xhtml/ 子目录）")
    parser.add_argument("--book", required=True, help="书籍编号（如 S4_05）")
    parser.add_argument("--title", default="", help="书籍标题（如 とある暗部の少女共棲（５））")
    parser.add_argument("--out", type=Path, required=True, help="输出目录")
    parser.add_argument("--no-pack", action="store_true", help="不打包 EPUB，仅生成文件")

    args = parser.parse_args()

    print(
        "警告: process_split_pages.py 是旧版兼容入口；新流程请使用 "
        "bw_preprocess.py + merge_bw_pages.py。"
    )

    if not args.title:
        # 从书籍编号推断标题
        if args.book.startswith("S4_"):
            vol = args.book.split('_')[1]
            args.title = f"とある暗部の少女共棲（{vol}）"
        else:
            args.title = "未命名"

    process_split_pages(args.input_dir, args.book, args.title, args.out, pack=not args.no_pack)


if __name__ == "__main__":
    main()
