#!/usr/bin/env python3
"""校对复核的输入包、分页阅读、报告装配与独立校验入口。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from cli_output import configure_output
from proofread_packets import (
    initialize_manifest,
    prepare_session,
    read_packet,
    render_packet,
    require_report_target,
    source_context,
    write_new_artifacts,
)
from proofread_results import assemble_result, coverage_summary, validate_result


REPO = Path(__file__).resolve().parents[1]


def write_artifact(path: Path, data: dict, *, seal: bool = False) -> None:
    """预先序列化，原子创建报告；已有产物始终保留。"""
    require_report_target(path)
    content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    outputs = {path: content}
    if seal:
        outputs[path.with_suffix(".sha256")] = (
            hashlib.sha256(content).hexdigest() + "\n").encode("ascii")
    write_new_artifacts(outputs, apply=True)


def _write_mode(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="明确写入新报告产物")
    mode.add_argument("--dry-run", action="store_true", help="只预览（默认）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init", help="从 changes.tsv 建立稳定 ID 清单")
    initialize.add_argument("--report-root", type=Path, required=True)
    _write_mode(initialize)

    prepare = commands.add_parser("prepare", help="验证人工切片，冻结来源与最小上下文包")
    prepare.add_argument("--report-root", type=Path, required=True)
    prepare.add_argument("--jp-base", type=Path,
                         default=REPO / ".cache/epub-work/japanese-text")
    prepare.add_argument("--cn-base", type=Path, default=REPO / "EPUB")
    prepare.add_argument("--plan", type=Path, help="显式 JSON 归属；省略则读 slices/ids/*.txt")
    prepare.add_argument("--max-input-chars", type=int, default=60000,
                         help="每片输入字符预算，超出提示调整，保留语义单元")
    _write_mode(prepare)

    read = commands.add_parser("read", help="按 ID、风险标签分页阅读冻结输入")
    read.add_argument("--report-root", type=Path, required=True)
    read.add_argument("--slice", required=True)
    read.add_argument("--ids", nargs="+")
    read.add_argument("--flag")
    read.add_argument("--page", type=int, default=1)
    read.add_argument("--page-size", type=int, default=10)
    read.add_argument("--context", type=int, choices=(0, 1), default=1)
    read.add_argument("--json", action="store_true")

    context = commands.add_parser("context", help="Lead 按具体依赖生成只读上下文补包")
    context.add_argument("--report-root", type=Path, required=True)
    context.add_argument("--slice", required=True)
    context.add_argument("--item-id", required=True)
    context.add_argument("--radius", type=int, default=2, choices=range(1, 11))
    context.add_argument("--revision", type=int, default=1)
    _write_mode(context)

    assemble = commands.add_parser("assemble", help="装配逐条决策，缺项失败，不预设判定")
    assemble.add_argument("--report-root", type=Path, required=True)
    assemble.add_argument("--slice", required=True)
    assemble.add_argument("--decisions", type=Path, required=True)
    assemble.add_argument("--attempt", type=int, choices=(1, 2), default=1)
    assemble.add_argument("--revision", type=int, default=0,
                          help="纯格式修订编号；保留同 attempt 的旧产物")
    _write_mode(assemble)

    validate = commands.add_parser("validate", help="独立核对结构、ID 与实际日文引用")
    validate.add_argument("--report-root", type=Path, required=True)
    validate.add_argument("--result", type=Path, required=True)
    validate.add_argument("--json", action="store_true")

    coverage = commands.add_parser("coverage", help="按显式有效报告选择派生覆盖与阻断项")
    coverage.add_argument("--report-root", type=Path, required=True)
    coverage.add_argument("--selection", type=Path, required=True)
    coverage.add_argument("--output", type=Path, help="显式输出路径，限本轮报告目录")
    _write_mode(coverage)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.report_root.resolve()
    try:
        if args.command == "init":
            result = initialize_manifest(root, apply=args.apply)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "prepare":
            result = prepare_session(
                root, jp_base=args.jp_base, cn_base=args.cn_base,
                plan_path=args.plan, max_input_chars=args.max_input_chars,
                apply=args.apply,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "read":
            data = read_packet(
                root, args.slice, item_ids=args.ids, flag=args.flag,
                page=args.page, page_size=args.page_size, context=args.context,
            )
            print(json.dumps(data, ensure_ascii=False, indent=2)
                  if args.json else render_packet(data))
        elif args.command == "context":
            if args.revision < 1:
                raise ValueError("revision 必须是正整数")
            data = source_context(root, args.slice, args.item_id, radius=args.radius)
            output = root / "slices/context" / args.slice / (
                f"{args.item_id}.c{args.revision}.json")
            require_report_target(output)
            if args.apply:
                write_artifact(output, data, seal=True)
            print(json.dumps({"output": str(output), "applied": args.apply,
                              "context": data}, ensure_ascii=False, indent=2))
        elif args.command == "assemble":
            if args.revision < 0:
                raise ValueError("revision 不能为负数")
            result = assemble_result(
                root, args.slice, args.decisions, attempt=args.attempt,
                revision=args.revision, apply=args.apply,
            )
            suffix = f".r{args.revision}" if args.revision else ""
            output = root / "slices" / f"{args.slice}.a{args.attempt}{suffix}.json"
            print(json.dumps({"output": str(output), "applied": args.apply,
                              "items": len(result["items"])}, ensure_ascii=False))
        elif args.command == "validate":
            issues = validate_result(root, args.result)
            if args.json:
                print(json.dumps({"valid": not issues, "issues": issues},
                                 ensure_ascii=False, indent=2))
            elif issues:
                for issue in issues:
                    print(f"[{issue['kind']}] {issue.get('item_id') or '-'}: "
                          f"{issue['message']}")
            else:
                print("结构、ID 与原文引用核验通过；语义判定仍须 Lead 验收。")
            return 1 if issues else 0
        elif args.command == "coverage":
            if args.apply and args.output is None:
                raise ValueError("写入 coverage 必须显式指定 --output")
            data = coverage_summary(root, args.selection)
            if args.output is not None:
                output = args.output.resolve()
                if not output.is_relative_to(root):
                    raise ValueError("coverage 输出必须位于本轮报告目录")
                require_report_target(output)
                if args.apply:
                    write_artifact(output, data)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0 if data["ready_for_lead_acceptance"] else 1
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"[阻断] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
