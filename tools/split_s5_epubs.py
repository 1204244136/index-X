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

用法：
    python tools/split_s5_epubs.py "<BW 提取源目录>" --packed-out 打包输出目录 --unpacked-out 解包输出目录
    python tools/split_s5_epubs.py "<BW 提取源目录>" --packed-out 打包输出目录 --unpacked-out 解包输出目录 --apply

源目录必须显式传入（存放「とある魔術の禁書目録 外典書庫（N）.epub」的 BW 提取目录）。
输出必须显式指定暂存目录；默认只预览，--apply 才写入。整批作品先准备与
校验，任一源文件、页区间或契约不满足即停止，保留已有产物。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import bw_preprocess  # noqa: E402
from edit_safety import require_edit_target  # noqa: E402
from epub_structure import (  # noqa: E402
    CSS_URL_RE, artifact_contract_issues, container_contract_issues,
    epub_zip_issues, resolve_reference,
)
from path_safety import (  # noqa: E402
    archive_member_destination,
    validate_archive_member_name,
)

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


@dataclass
class SplitPlan:
    book_id: str
    title: str
    entries: dict[str, bytes]

    @property
    def basename(self) -> str:
        return f"[{self.book_id}]{self.title}"


def _zip_infos(entries: dict[str, bytes]) -> list[zipfile.ZipInfo]:
    infos = []
    for name in ["mimetype", *(n for n in sorted(entries) if n != "mimetype")]:
        info = zipfile.ZipInfo(name)
        info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
        infos.append(info)
    return infos


def _read_source(path: Path) -> tuple[dict[str, bytes], str]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        for info in infos:
            validate_archive_member_name(info.filename)
        entries = {info.filename: archive.read(info.filename) for info in infos}
    issues = epub_zip_issues(infos, entries) + container_contract_issues(entries)
    if issues:
        raise ValueError(f"源 EPUB 容器不合法 {path.name}: {issues}")
    opfs = [name for name in entries if name.lower().endswith(".opf")]
    if len(opfs) != 1:
        raise ValueError(f"源 EPUB 必须有唯一 OPF {path.name}: {opfs}")
    return entries, opfs[0]


def _prepare_split(
    entries: dict[str, bytes], opf_name: str, book_id: str, title: str,
    start_page: int, end_page: int, rules: list[dict],
) -> SplitPlan:
    target_pages = {f"p-{number:03d}.xhtml" for number in range(start_page, end_page + 1)}
    by_basename: dict[str, list[str]] = {}
    for name in entries:
        by_basename.setdefault(name.rsplit("/", 1)[-1], []).append(name)
    missing = sorted(target_pages - set(by_basename))
    duplicate = sorted(page for page in target_pages if len(by_basename.get(page, [])) > 1)
    if missing or duplicate:
        raise ValueError(f"{book_id} 页区间不完整；缺页={missing}，重复页={duplicate}")
    selected = {by_basename[page][0] for page in target_pages}
    split_entries = {
        name: data for name, data in entries.items()
        if name == "mimetype" or name.startswith("META-INF/") or name.lower().endswith(".css")
        or name in selected
    }

    # Keep resources referenced by selected pages/CSS/SVG, including nested images/fonts.
    pending = list(split_entries)
    checked: set[str] = set()
    while pending:
        source = pending.pop()
        if source in checked or not source.lower().endswith((".xhtml", ".html", ".htm", ".svg", ".css")):
            continue
        checked.add(source)
        text = split_entries[source].decode("utf-8-sig", errors="strict")
        if source.lower().endswith(".css"):
            css = re.sub(rb"/\*.*?\*/", b"", split_entries[source], flags=re.S)
            references = [match.group(2).decode("utf-8") for match in CSS_URL_RE.finditer(css)]
            references.extend(re.findall(r"@import\s+['\"]([^'\"]+)['\"]", text, re.I))
        else:
            document = ET.fromstring(text)
            references = [value for element in document.iter() for attr, value in element.attrib.items()
                          if attr.rsplit("}", 1)[-1].casefold() in {"src", "href", "poster"}]
        for reference in references:
            resolved = resolve_reference(source, reference)
            if resolved is None or resolved == source:
                continue
            # Other XHTML pages belong to another split; the artifact gate reports
            # such cross-work links instead of importing another work's text.
            if resolved in entries and not resolved.lower().endswith(bw_preprocess.XHTML_SUFFIXES):
                if resolved not in split_entries:
                    split_entries[resolved] = entries[resolved]
                    pending.append(resolved)

    opf = ET.fromstring(entries[opf_name])
    namespace = opf.tag.partition("}")[0].lstrip("{") if "}" in opf.tag else ""
    if namespace:
        ET.register_namespace("", namespace)
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    def local(element: ET.Element) -> str:
        return element.tag.rsplit("}", 1)[-1]
    manifest = next((element for element in opf if local(element) == "manifest"), None)
    spine = next((element for element in opf if local(element) == "spine"), None)
    if manifest is None or spine is None:
        raise ValueError(f"{book_id} OPF 缺 manifest/spine")
    kept_ids: set[str] = set()
    for item in list(manifest):
        resolved = resolve_reference(opf_name, item.get("href", ""))
        if resolved in split_entries:
            kept_ids.add(item.get("id", ""))
        else:
            manifest.remove(item)
    for item in list(spine):
        if item.get("idref") not in kept_ids:
            spine.remove(item)
    if spine.get("toc") not in kept_ids:
        spine.attrib.pop("toc", None)
    for element in opf.iter():
        if local(element) == "title":
            element.text = title
            break
    for element in list(opf):
        if local(element) == "guide":
            for reference in list(element):
                if resolve_reference(opf_name, reference.get("href", "")) not in split_entries:
                    element.remove(reference)
    ET.indent(opf, space="  ")
    split_entries[opf_name] = ET.tostring(opf, encoding="utf-8", xml_declaration=True)

    for name in list(split_entries):
        if name.lower().endswith(bw_preprocess.XHTML_SUFFIXES):
            transformed, _ = bw_preprocess.transform_bytes(split_entries[name], rules)
            problems = bw_preprocess.verify_text(transformed.decode("utf-8-sig"))
            if problems:
                raise ValueError(f"{book_id} 预处理模板不满足契约 {name}: {problems}")
            split_entries[name] = transformed
    renames = bw_preprocess.pairing_header_renames(split_entries, book_id, None)
    if renames:
        split_entries = bw_preprocess.apply_entry_renames(split_entries, renames)
    split_entries, infos, _notes = bw_preprocess.merge_epub_pages(
        split_entries, book_id, _zip_infos(split_entries),
    )
    bw_preprocess.inject_pb_css(split_entries)
    issues = container_contract_issues(split_entries) + artifact_contract_issues(split_entries, book_id)
    issues.extend(epub_zip_issues(infos, split_entries))
    for name, data in split_entries.items():
        if name.lower().endswith(bw_preprocess.XHTML_SUFFIXES):
            issues.extend((name, problem) for problem in bw_preprocess.verify_text(
                data.decode("utf-8-sig"), merged=True,
            ))
    if issues:
        raise ValueError(f"{book_id} 产物契约校验失败: {issues}")
    return SplitPlan(book_id, title, split_entries)


def prepare_split_plans(src_dir: Path, specs: list[dict] | None = None) -> list[SplitPlan]:
    if not src_dir.is_dir():
        raise ValueError(f"BW 提取源目录不存在：{src_dir}")
    specs = SPLIT_SPECS if specs is None else specs
    rules = bw_preprocess.load_rules(None)
    plans: list[SplitPlan] = []
    for spec in specs:
        vol = spec["vol"]
        name = f"とある魔術の禁書目録 外典書庫（{chr(0xFF10 + vol)}）.epub"
        path = src_dir / name
        if not path.is_file():
            raise ValueError(f"缺少拆分源：{path}")
        entries, opf_name = _read_source(path)
        for book_id, title, start, end in spec["splits"]:
            plans.append(_prepare_split(entries, opf_name, book_id, title, start, end, rules))
    if not plans:
        raise ValueError("没有找到可拆分的作品")
    names = [plan.basename for plan in plans]
    if len(names) != len(set(names)):
        raise ValueError("拆分计划包含重复输出作品")
    return plans


def validate_outputs(src_dir: Path, packed: Path, unpacked: Path) -> None:
    for path in (packed, unpacked):
        require_edit_target(path, staging=True)
        if path == src_dir or path.is_relative_to(src_dir) or src_dir.is_relative_to(path):
            raise ValueError(f"输出目录不得与源目录重叠：{path}")
    if packed == unpacked or packed.is_relative_to(unpacked) or unpacked.is_relative_to(packed):
        raise ValueError("打包与解包输出目录不得重叠")


def apply_split_plans(plans: list[SplitPlan], packed: Path, unpacked: Path) -> None:
    '''Stage the whole batch, then replace destinations with rollback on failure.'''
    for root in (packed, unpacked):
        require_edit_target(root, staging=True)
        root.mkdir(parents=True, exist_ok=True)
    stage_roots = [Path(tempfile.mkdtemp(prefix=".split-s5-", dir=root)) for root in (packed, unpacked)]
    replacements: list[dict] = []
    preserve_stages = False
    try:
        for index, plan in enumerate(plans):
            epub = stage_roots[0] / f"{index}.epub"
            with zipfile.ZipFile(epub, "w") as archive:
                for info in _zip_infos(plan.entries):
                    archive.writestr(info, plan.entries[info.filename])
            directory = stage_roots[1] / str(index)
            directory.mkdir()
            for name, data in plan.entries.items():
                destination = archive_member_destination(directory, name)
                if name.endswith("/"):
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
            for staged, target, backup in (
                (epub, packed / f"{plan.basename}.epub", stage_roots[0] / f"{index}.old"),
                (directory, unpacked / plan.basename, stage_roots[1] / f"{index}.old"),
            ):
                replacements.append({"staged": staged, "target": target, "backup": backup,
                                     "installed": False, "backed_up": False})
        for item in replacements:
            if item["target"].exists():
                os.replace(item["target"], item["backup"])
                item["backed_up"] = True
            os.replace(item["staged"], item["target"])
            item["installed"] = True
    except Exception:
        rollback_errors = []
        for item in reversed(replacements):
            try:
                if item["installed"]:
                    if item["target"].is_dir():
                        shutil.rmtree(item["target"])
                    else:
                        item["target"].unlink()
                if item["backed_up"]:
                    os.replace(item["backup"], item["target"])
            except OSError as exc:
                rollback_errors.append(str(exc))
        if rollback_errors:
            preserve_stages = True
            raise RuntimeError(f"输出替换与回滚失败；旧产物保留于 {stage_roots}: {rollback_errors}")
        raise
    finally:
        if not preserve_stages:
            for root in stage_roots:
                shutil.rmtree(root)


def split_and_process_s5(
    src_dir: Path, packed_out_dir: Path, unpacked_out_dir: Path, *, apply: bool = False,
) -> int:
    src_dir, packed_out_dir, unpacked_out_dir = (
        path.resolve() for path in (src_dir, packed_out_dir, unpacked_out_dir)
    )
    try:
        validate_outputs(src_dir, packed_out_dir, unpacked_out_dir)
        plans = prepare_split_plans(src_dir)
        for plan in plans:
            print(f"[校验通过] {plan.book_id}: {len(plan.entries)} 个条目 -> {plan.basename}")
        if apply:
            apply_split_plans(plans, packed_out_dir, unpacked_out_dir)
        print(f"{'已写入' if apply else '预览'}：{len(plans)} 部作品" + ("" if apply else "（加 --apply 写入）"))
        return 0
    except Exception as exc:
        print(f"[阻断] S5 拆分未完成：{exc}", file=sys.stderr)
        return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="外典书库拆分：整批预检后输出独立作品到显式暂存目录")
    parser.add_argument("src", type=Path, help="BW 提取源目录")
    parser.add_argument("--packed-out", required=True, type=Path, help="打包产物暂存目录（不得在项目缓存/OneDrive 中）")
    parser.add_argument("--unpacked-out", required=True, type=Path, help="解包产物暂存目录（不得在项目缓存/OneDrive 中）")
    parser.add_argument("--apply", action="store_true", help="写入；默认只预检与预览")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return split_and_process_s5(args.src, args.packed_out, args.unpacked_out, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
