#!/usr/bin/env python3
"""外典書庫拆分工具：参考中文目录规范，将日文外典书库合订卷拆分为独立作品 EPUB 与解包目录。

对应关系与拆分范围：
- 外典書庫（１）：
    S5_01_01: 神裂火織編 (p-001 ~ p-009)
    S5_01_02: 『必要悪の教会』特別編入試験編 (p-010 ~ p-018)
    S5_01_03: ロード・トゥ・エンデュミオン (p-019 ~ p-027)
- 外典書庫（２）：
    S5_02_01: 学芸都市編 (p-001 ~ p-009)
    S5_02_02: 能力実演旅行編 (p-010 ~ p-018)
    S5_02_03: コールドゲーム (p-019 ~ p-021)
- 外典書庫（３）：
    S5_03_01: アニェーゼの魔術サイドお仕事体験編 (p-001 ~ p-009)
    S5_03_02: バイオハッカー編 (p-010 ~ p-019)
- 外典書庫（４）：
    S5_04_01: ステートバリウス編 (p-001 ~ p-009)
    S5_04_02: 御坂美琴と食蜂操祈をイチャイチャさせる完全にキレたやり方 (p-010 ~ p-024)
"""
from __future__ import annotations

import posixpath
import re
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import bw_preprocess
import merge_bw_pages

SPLIT_SPECS = [
    # Volume 1
    {
        "vol": 1,
        "splits": [
            ("S5_01_01", "とある魔術の禁書目録SS 神裂火織編", 1, 9),
            ("S5_01_02", "とある魔術の禁書目録SS 『必要悪の教会』特別編入試験編", 10, 18),
            ("S5_01_03", "とある魔術の禁書目録 ロード・トゥ・エンデュミオン", 19, 27),
        ]
    },
    # Volume 2
    {
        "vol": 2,
        "splits": [
            ("S5_02_01", "とある科学の超電磁砲SS 学芸都市編", 1, 9),
            ("S5_02_02", "とある科学の超電磁砲SS2 能力実演旅行編", 10, 18),
            ("S5_02_03", "とある科学の超電磁砲 コールドゲーム", 19, 21),
        ]
    },
    # Volume 3
    {
        "vol": 3,
        "splits": [
            ("S5_03_01", "とある魔術の禁書目録SS アニェーゼの魔術サイドお仕事体験編", 1, 9),
            ("S5_03_02", "とある魔術の禁書目録SS バイオハッカー編", 10, 19),
        ]
    },
    # Volume 4
    {
        "vol": 4,
        "splits": [
            ("S5_04_01", "とある科学の超電磁砲SS3 ステートバリウス編", 1, 9),
            ("S5_04_02", "とある魔術の禁書目録外伝 御坂美琴と食蜂操祈をイチャイチャさせる完全にキレたやり方", 10, 24),
        ]
    },
]


def split_and_process_s5(
    src_dir: Path,
    packed_out_dir: Path,
    unpacked_out_dir: Path,
) -> None:
    rules = bw_preprocess.load_rules(None)
    packed_out_dir.mkdir(parents=True, exist_ok=True)
    unpacked_out_dir.mkdir(parents=True, exist_ok=True)

    for spec in SPLIT_SPECS:
        vol = spec["vol"]
        epub_name = f"とある魔術の禁書目録 外典書庫（{chr(0xFF10 + vol)}）.epub"
        epub_path = src_dir / epub_name
        if not epub_path.exists():
            print(f"[跳过] 不存在：{epub_path}")
            continue

        with zipfile.ZipFile(epub_path) as zin:
            raw_entries = {info.filename: zin.read(info.filename) for info in zin.infolist()}
            raw_infos = {info.filename: info for info in zin.infolist()}

        # 查找 OPF
        opf_name = next(n for n in raw_entries if n.lower().endswith(".opf"))
        opf_data = raw_entries[opf_name].decode("utf-8-sig", errors="replace")

        for book_id, clean_title, start_page, end_page in spec["splits"]:
            print(f"\n--- 正在拆分并处理: [{book_id}]{clean_title} (p-{start_page:03d} ~ p-{end_page:03d}) ---")
            split_entries: dict[str, bytes] = {}
            target_page_names = {f"p-{p:03d}.xhtml" for p in range(start_page, end_page + 1)}

            # 1. 拷贝固定基础设施文件
            for name, data in raw_entries.items():
                if name == "mimetype":
                    split_entries[name] = data
                elif name.startswith("META-INF/"):
                    split_entries[name] = data
                elif name.lower().endswith(".css"):
                    split_entries[name] = data

            # 2. 提取该篇目范围的 XHTML
            selected_xhtml_paths = []
            for name, data in raw_entries.items():
                if not name.lower().endswith(bw_preprocess.XHTML_SUFFIXES):
                    continue
                basename = name.rsplit("/", 1)[-1]
                if basename in target_page_names:
                    selected_xhtml_paths.append(name)
                    split_entries[name] = data

            # 3. 收集该篇目 XHTML 所引用的图片资源 (含 img src, svg image xlink:href/href)
            referenced_images: set[str] = set()
            for x_name in selected_xhtml_paths:
                text = split_entries[x_name].decode("utf-8-sig", errors="replace")
                for img_src in re.findall(r'(?:src|href|xlink:href)=[\'"]([^\'"]+\.(?:jpg|jpeg|png|gif|webp|svg))[\'"]', text, re.I):
                    resolved = bw_preprocess._resolved_reference(x_name, img_src)
                    if resolved and resolved in raw_entries:
                        referenced_images.add(resolved)

            for img_path in referenced_images:
                split_entries[img_path] = raw_entries[img_path]

            # 4. 构建拆分后的独立 OPF
            # 过滤 manifest
            manifest_match = re.search(r"<manifest\b[^>]*>(.*?)</manifest>", opf_data, re.S)
            spine_match = re.search(r"<spine\b[^>]*>(.*?)</spine>", opf_data, re.S)
            assert manifest_match and spine_match

            # 匹配当前作品需要的 item
            new_manifest_items = []
            kept_item_ids: set[str] = set()
            for line in manifest_match.group(1).splitlines(keepends=True):
                m_href = re.search(r'\bhref="([^"]+)"', line, re.I)
                m_id = re.search(r'\bid="([^"]+)"', line, re.I)
                if m_href and m_id:
                    href = m_href.group(1)
                    item_id = m_id.group(1)
                    resolved = bw_preprocess._resolved_reference(opf_name, href)
                    if resolved in split_entries:
                        new_manifest_items.append(line)
                        kept_item_ids.add(item_id)
                elif re.search(r'<item\b', line, re.I):
                    pass
                else:
                    new_manifest_items.append(line)

            # 过滤 spine
            new_spine_items = []
            for line in spine_match.group(1).splitlines(keepends=True):
                m_idref = re.search(r'\bidref="([^"]+)"', line, re.I)
                if m_idref:
                    if m_idref.group(1) in kept_item_ids:
                        new_spine_items.append(line)
                else:
                    new_spine_items.append(line)

            split_opf = (
                opf_data[:manifest_match.start(1)]
                + "".join(new_manifest_items)
                + opf_data[manifest_match.end(1):spine_match.start(1)]
                + "".join(new_spine_items)
                + opf_data[spine_match.end(1):]
            )
            # 更新 metadata 标题
            split_opf = re.sub(
                r"<dc:title\b[^>]*>(.*?)</dc:title>",
                f"<dc:title>{clean_title}</dc:title>",
                split_opf,
                flags=re.S
            )
            split_entries[opf_name] = split_opf.encode("utf-8")

            # 5. 生成对应的 ZipInfo 列表
            infos: list[zipfile.ZipInfo] = []
            mimetype_info = zipfile.ZipInfo("mimetype")
            mimetype_info.compress_type = zipfile.ZIP_STORED
            infos.append(mimetype_info)
            for name in split_entries:
                if name == "mimetype":
                    continue
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                infos.append(info)

            # 6. 执行与主工作流一致的规则预处理、表头分配、章节合并、换页样式注入
            # a. 预处理 rules
            for name in list(split_entries):
                if name.lower().endswith(bw_preprocess.XHTML_SUFFIXES):
                    new_data, _ = bw_preprocess.transform_bytes(split_entries[name], rules)
                    split_entries[name] = new_data

            # b. 表头与资源重命名 (分配 S5_AA_BB 前缀)
            renames = bw_preprocess.pairing_header_renames(split_entries, book_id, None)
            if renames:
                split_entries = bw_preprocess.apply_entry_renames(split_entries, renames)
                new_infos = []
                for info in infos:
                    new_name = renames.get(info.filename, info.filename)
                    new_info = zipfile.ZipInfo(new_name)
                    new_info.compress_type = (
                        zipfile.ZIP_STORED if new_name == "mimetype" else zipfile.ZIP_DEFLATED
                    )
                    new_infos.append(new_info)
                infos = new_infos

            # c. 分页合并为章节单元
            split_entries, infos, merge_notes = bw_preprocess.merge_epub_pages(split_entries, book_id, infos)
            bw_preprocess.inject_pb_css(split_entries)

            # d. 产物校验
            issues = bw_preprocess.artifact_contract_issues(split_entries, book_id)
            if issues:
                print(f"  [警告] 校验问题 ({len(issues)}): {issues[:5]}")
            else:
                print(f"  [校验通过] 契约校验 0 问题")

            # 7. 写盘
            out_epub_path = packed_out_dir / f"[{book_id}]{clean_title}.epub"
            unpacked_dir = unpacked_out_dir / f"[{book_id}]{clean_title}"

            out_epub_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(out_epub_path, "w") as zout:
                for info in infos:
                    data = split_entries[info.filename]
                    new_info = zipfile.ZipInfo(info.filename)
                    new_info.compress_type = (
                        zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
                    )
                    zout.writestr(new_info, data)

            unpacked_dir.mkdir(parents=True, exist_ok=True)
            for name, data in split_entries.items():
                dest = unpacked_dir / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)

            # 统计生成章节数
            ch_count = sum(1 for n in split_entries if re.search(rf"{book_id}-\d+\.xhtml", n))
            print(f"  -> 已成功输出: EPUB={out_epub_path.name}, 章节数={ch_count}, 解包={unpacked_dir.name}")


if __name__ == "__main__":
    src = Path(r"C:\Users\12042\OneDrive\某系列\BW提取")
    packed = Path(".cache/epub-work/packed-epubs/japanese-text")
    unpacked = Path(".cache/epub-work/japanese-text")
    split_and_process_s5(src, packed, unpacked)
