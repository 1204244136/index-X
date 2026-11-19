#!/usr/bin/env python3
"""按模块并发运行 tools/tests/ 下的 unittest 测试套件。"""
from __future__ import annotations

import argparse
import contextlib
import fnmatch
import io
import os
import sys
import time
import traceback
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = TESTS_DIR.parent
REPO_ROOT = TOOLS_DIR.parent

for _path in (str(TESTS_DIR), str(TOOLS_DIR), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from cli_output import configure_output  # noqa: E402

# 高耗时测试模块优先调度，压低并发尾延迟。
HEAVY_MODULES = (
    "test_pull",
    "test_publish_auto",
    "test_sync_lock",
    "test_proofread_session",
    "test_proofread_results",
    "test_cli_output",
)


def _discover_modules(pattern: str) -> list[str]:
    names = [
        path.stem
        for path in sorted(TESTS_DIR.iterdir())
        if path.is_file()
        and path.suffix == ".py"
        and path.name != "__init__.py"
        and fnmatch.fnmatch(path.name, pattern)
    ]
    heavy_rank = {name: idx for idx, name in enumerate(HEAVY_MODULES)}
    return sorted(names, key=lambda name: (0 if name in heavy_rank else 1, heavy_rank.get(name, 0), name))


def _run_module(task: tuple[str, bool]) -> dict[str, object]:
    module_name, verbose = task
    for _path in (str(TESTS_DIR), str(TOOLS_DIR), str(REPO_ROOT)):
        if _path not in sys.path:
            sys.path.insert(0, _path)

    started = time.perf_counter()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            suite = unittest.defaultTestLoader.loadTestsFromName(module_name)
            runner = unittest.TextTestRunner(
                stream=buf,
                verbosity=2 if verbose else 1,
            )
            result = runner.run(suite)
        elapsed = time.perf_counter() - started
        return {
            "module": module_name,
            "elapsed": elapsed,
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "expected_failures": len(result.expectedFailures),
            "unexpected_successes": len(result.unexpectedSuccesses),
            "ok": result.wasSuccessful(),
            "output": buf.getvalue(),
        }
    except Exception:
        elapsed = time.perf_counter() - started
        buf.write(traceback.format_exc())
        return {
            "module": module_name,
            "elapsed": elapsed,
            "tests_run": 0,
            "failures": 0,
            "errors": 1,
            "skipped": 0,
            "expected_failures": 0,
            "unexpected_successes": 0,
            "ok": False,
            "output": buf.getvalue(),
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按模块并发运行 tools/tests 单元测试。")
    parser.add_argument("--jobs", type=int, default=0, help="并发进程数（0 表示自动，1 表示单进程）")
    parser.add_argument("--pattern", default="test_*.py", help="匹配测试文件名模式（默认 test_*.py）")
    parser.add_argument("--slowest", type=int, default=0, help="结束时展示耗时最长的 N 个测试模块")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出每个模块的完整 unittest 日志")
    args = parser.parse_args(argv)
    if args.jobs < 0:
        parser.error("--jobs 不能为负数")
    if args.slowest < 0:
        parser.error("--slowest 不能为负数")
    return args


def main(argv: list[str] | None = None) -> int:
    configure_output()
    args = parse_args(argv)
    modules = _discover_modules(args.pattern)
    if not modules:
        print(f"[错误] 未在 {TESTS_DIR} 找到匹配 {args.pattern!r} 的测试模块。", file=sys.stderr)
        return 1

    jobs = args.jobs if args.jobs > 0 else min(os.cpu_count() or 1, 8)
    jobs = min(jobs, len(modules))
    tasks = [(name, args.verbose) for name in modules]
    wall_start = time.perf_counter()

    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as executor:
            results = list(executor.map(_run_module, tasks))
    else:
        results = [_run_module(task) for task in tasks]

    wall_elapsed = time.perf_counter() - wall_start
    results_by_name = sorted(results, key=lambda item: str(item["module"]))

    total_tests = 0
    total_failures = 0
    total_errors = 0
    total_skipped = 0
    total_expected_failures = 0
    total_unexpected_successes = 0
    failed_modules: list[str] = []

    for item in results_by_name:
        mod = str(item["module"])
        total_tests += int(item["tests_run"])
        total_failures += int(item["failures"])
        total_errors += int(item["errors"])
        total_skipped += int(item["skipped"])
        total_expected_failures += int(item["expected_failures"])
        total_unexpected_successes += int(item["unexpected_successes"])
        ok = bool(item["ok"])
        if not ok:
            failed_modules.append(mod)
        if args.verbose or not ok:
            status = "PASS" if ok else "FAIL"
            print(f"=== [{status}] {mod} ({int(item['tests_run'])} tests, {float(item['elapsed']):.2f}s) ===")
            output = str(item["output"]).rstrip()
            if output:
                print(output)

    if args.slowest > 0:
        print(f"\n== 最慢 {min(args.slowest, len(results))} 个测试模块 ==")
        for item in sorted(results, key=lambda r: float(r["elapsed"]), reverse=True)[:args.slowest]:
            print(f"  {float(item['elapsed']):6.2f}s  {item['module']} ({item['tests_run']} tests)")

    print(
        f"\nRan {total_tests} tests across {len(modules)} modules in {wall_elapsed:.2f}s "
        f"(jobs={jobs}, failures={total_failures}, errors={total_errors}, "
        f"skipped={total_skipped}, expectedFailures={total_expected_failures}, "
        f"unexpectedSuccesses={total_unexpected_successes})"
    )
    if failed_modules:
        print(f"FAILED modules: {', '.join(failed_modules)}", file=sys.stderr)
        return 1
    if total_tests == 0:
        print("[错误] 执行了 0 个测试用例。", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
