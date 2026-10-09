#!/usr/bin/env python3
"""图片素材 → 归档命名与落位（建议映射 + 按计划复制校验）。

新书导入第 5 步，只写 `<书目录>/OEBPS/Images/`。

* `suggest`：素材文件名与归档命名无关（美工给什么名字都行），用 dHash 指纹把
  素材对到日文原图上，给出「素材 → 应落地的归档名」建议；只读，写显式 `--out`。
* `apply`：按计划里的 `images`（`src`／`dst`／`role`）复制并校验——`dst` 必须带
  作品号前缀、源文件存在且可解码、正文插图数量与计划一致；写入前后都报指纹。

用法：
    python tools/import_images.py suggest --src 素材目录 --jp-dir 缓存日文图目录 --work S4_04
    python tools/import_images.py apply plan.json --out EPUB/[S4_04]… --apply
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from edit_safety import EditSafetyError, add_edit_mode, require_edit_target
from file_transaction import atomic_write_bytes, rollback_paths
from image_signature import dimensions, dhash, hamming, image_files, pillow_available
from import_plan import PlanError, body_images, load_plan


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def suggest(args) -> int:
    if not args.src.is_dir():
        print(f"[阻断] 素材目录不存在：{args.src}")
        return 2
    if not args.jp_dir.is_dir():
        print(f"[阻断] 日文图片目录不存在：{args.jp_dir}")
        return 2
    sources = image_files(args.src)
    targets = image_files(args.jp_dir)
    if not sources or not targets:
        print("[阻断] 素材或日文图片目录为空")
        return 2
    lines = [f"素材 {len(sources)} 张 / 日文原图 {len(targets)} 张"
             + ("" if pillow_available() else "（未安装 Pillow，只能按尺寸与文件名给低置信建议）")]
    for path in sources:
        size = dimensions(path)
        source_hash = dhash(path)
        ranked = sorted(((hamming(source_hash, dhash(target)), target) for target in targets),
                        key=lambda item: (item[0] < 0, item[0]))
        best = ranked[0] if ranked else None
        if best is None:
            lines.append(f"{path.name}\t未知\t指纹不可用")
            continue
        distance, match = best
        confidence = "高" if 0 <= distance <= 6 else ("中" if distance <= 16 else "低")
        archive_name = f"{args.work}-{match.name}" if args.work and not match.name.startswith(f"{args.work}-") else match.name
        lines.append(f"{path.name}\t{size}\t->\t{archive_name}\t距离 {distance}（{confidence}）")
    text = "\n".join(lines) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"建议映射：{args.out}")
    print(text, end="")
    print("低置信项必须打开图看过再落位；同一张原图只允许对应一个归档名。")
    return 0


def apply(args) -> int:
    try:
        plan = load_plan(args.plan)
    except PlanError as exc:
        print(f"[阻断] {exc}")
        return 2
    work_id = plan["work_id"]
    source_root = Path(plan.get("images_source", ""))
    if not plan.get("images_source") or not source_root.is_dir():
        print(f"[阻断] 计划里的 images_source 不可用：{plan.get('images_source')!r}")
        return 2

    problems: list[str] = []
    payloads: dict[str, bytes] = {}
    for entry in plan["images"]:
        destination = entry["dst"]
        if not destination.startswith(f"{work_id}-"):
            problems.append(f"{destination} 缺少作品号前缀 {work_id}-")
        source = source_root / entry["src"]
        if not source.is_file():
            problems.append(f"素材不存在：{source}")
            continue
        data = source.read_bytes()
        if not data:
            problems.append(f"素材是空文件：{source}")
            continue
        if pillow_available() and dimensions(source) is None:
            problems.append(f"素材无法解码：{source}")
            continue
        if destination in payloads:
            problems.append(f"归档名重复：{destination}")
            continue
        payloads[destination] = data
    if not body_images(plan):
        problems.append("计划里没有 role=body 的正文插图")
    if problems:
        print("图片未落位：")
        for item in problems:
            print(f"  - {item}")
        return 1

    report = []
    for name, data in sorted(payloads.items()):
        entry = next(item for item in plan["images"] if item["dst"] == name)
        size = dimensions(source_root / entry["src"])
        shape = f"{size[0]}x{size[1]}" if size else "尺寸未知"
        report.append(f"{name}\t{shape}\tsha256 {sha256_bytes(data)[:16]}")
    print("\n".join(report))
    if not args.apply:
        print(f"[预览] 将写入 {len(payloads)} 张图片到 {args.out}/OEBPS/Images/；加 --apply 写盘")
        return 0
    try:
        target = require_edit_target(args.out, args.staging)
    except EditSafetyError as exc:
        print(f"[阻断] {exc}")
        return 2
    image_dir = target / "OEBPS" / "Images"
    image_dir.mkdir(parents=True, exist_ok=True)
    with rollback_paths([image_dir]):
        for name, data in sorted(payloads.items()):
            atomic_write_bytes(image_dir / name, data)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    print(f"已写入 {len(payloads)} 张图片：{image_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="图片素材 → 归档命名与落位")
    sub = parser.add_subparsers(dest="command", required=True)

    suggest_parser = sub.add_parser("suggest", help="用指纹把素材对到日文原图（只读）")
    suggest_parser.add_argument("--src", type=Path, required=True, help="素材目录")
    suggest_parser.add_argument("--jp-dir", type=Path, required=True, help="日文原图目录（缓存）")
    suggest_parser.add_argument("--work", default="", help="作品号，用于生成归档名建议")
    suggest_parser.add_argument("--out", type=Path, help="建议映射输出文件")

    apply_parser = sub.add_parser("apply", help="按计划复制图片并校验")
    apply_parser.add_argument("plan", type=Path, help="导入计划 plan.json")
    apply_parser.add_argument("--out", type=Path, required=True, help="书目录（写入其 OEBPS/Images/）")
    apply_parser.add_argument("--report", type=Path, help="指纹报告输出文件")
    add_edit_mode(apply_parser)

    args = parser.parse_args(argv)
    if args.command == "suggest":
        return suggest(args)
    return apply(args)


if __name__ == "__main__":
    raise SystemExit(main())
