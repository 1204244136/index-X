#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 calibre 的 Check Book 接口对 EPUB 做只读合法性校验。

定位
----
calibre 编辑器里的「Check book」是一套完整的 EPUB 结构检查器：容器/OPF 解析、
XML 良构性、清单与 spine 一致性、内部链接与锚点、字体与图片、文件名、ID 唯一性、
编码声明、CSS 语法。本工具把这些检查**批量**跑在整库上，并把结果聚合成一眼能
扫完的报告，作为 `check_epub_health.py`（本项目自有判定）之外的第三方口径闸门。

判定口径全部来自 calibre，本文件**不自己实现另一套 EPUB 规范检查器**：这里只负责
收集目标、控制并行、把 calibre 的原始错误分级归类、输出与退出码。

校验对象
--------
两种输入都支持，且都是只读：

  * **`.epub` 成品**（如 `.cache/epub-work/packed-epubs/` 下的分发副本）；
  * **解包书籍目录**（如 `EPUB/` 下每本书，含 `mimetype` 与
    `META-INF/container.xml`）——calibre 能直接把这种目录当容器打开，
    因此不必先打包就能验证归档源。

不传路径时默认校验 `EPUB/`。传普通目录时按一层扫描其中的 `.epub` 与书籍目录，
`--recursive` 递归更深层级。

类别（category）
----------------
calibre 的原始类型名（`CSSError`、`DanglingLink`……）不足以判断轻重，本工具据此
再归一层类别。`--list-categories` 可打印这张表：

    结构性（默认门禁范围）
      container   无法打开/解析容器（打包损坏、OPF 缺失等硬失败）
      xml         XHTML/XML 不是良构文档
      opf         OPF 清单、spine、metadata 或 idref 不一致
      nav         导航文档缺失或无效
      link        DanglingLink / BadDestinationFragment：链接指向不存在的文件或锚点
      resource    UnreferencedResource：文件没有被清单或正文引用
      font        字体缺失或声明错误
      image       图片损坏或声明错误
      encoding    编码声明与实际内容不符
      filename    文件名含非法字符或与清单不一致
      ids         元素 ID 重复/非法
      markup      HTML 标记结构问题
      mimetype    mimetype 声明问题
      empty-file  应含内容却是空文件
      css-syntax  CSS 真语法错误（无效声明、括号不配对等）
      other       未归类（出现即说明需要补映射，见下）

    样式风格（只影响 EPUB 内部观感，不构成合法性缺陷）
      css-order        选择器书写顺序建议（"Expected selector … to come before …"）
      css-duplicate    重复选择器（"Unexpected duplicate selector …"）
      css-empty-block  空规则块（"Unexpected empty block"）
      html-size        单个 XHTML 体积过大

`--structural` 会排除上表「样式风格」四项——这是本项目实际关心的口径：整库样式表由
本仓库自建，空块、重复与选择器顺序都不影响阅读器行为，而它们在本库能占命中总数的
九成九以上，混在一起会把真信号淹没。

类别映射以 calibre 的**类名**为准（`DanglingLink`、`BadDestinationFragment`……），
不匹配本地化后的消息文本，因此换 calibre 语言或版本不会改变归类结果；`other` 是
兜底而不是静默丢弃，命中它会照常出现在报告与门禁里。

用法
----
    python tools/check_epub_validity.py                      # 默认校验 EPUB/
    python tools/check_epub_validity.py EPUB --structural     # 只看结构性
    python tools/check_epub_validity.py .cache/epub-work/packed-epubs --recursive
    python tools/check_epub_validity.py --pattern "*S3_*" --jobs 1
    python tools/check_epub_validity.py --report r.txt --json r.json --tsv r.tsv
    python tools/check_epub_validity.py --list-categories

退出码
------
    0   没有命中（或未开 --strict 时的正常结束）
    1   --strict 且过滤后仍有问题（含单本检查失败）
    2   输入路径、calibre 环境等运行前提有误

**它只读**：不修改、不修复、不重新打包任何输入；不写 `EPUB/`、不写 `.cache/`。
报告只在显式给出 `--report/--json/--tsv` 时写盘，临时文件落在系统临时目录。

依赖与兼容性
------------
必须装有 calibre（`calibre-debug`）。本工具用的是 calibre 的**内部** API
（`calibre.ebooks.oeb.polish.{container,check.main}`），不属于其公开命令行接口，
calibre 升级后模块位置或函数签名可能变化：`load_calibre_api()` 是唯一的兼容层，
导入失败时给出明确提示而不是抛栈。入口解释器不需要是 calibre 自带的 Python——
校验统一在子进程里做，该子进程由本工具按需用 `calibre-debug` 拉起。
"""
from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_ROOT = REPO_ROOT / "EPUB"

EXIT_OK = 0
EXIT_ISSUES = 1
EXIT_SETUP_ERROR = 2

EPUB_SUFFIX = ".epub"
BOOK_MARKERS = ("mimetype", "META-INF/container.xml")

LEVEL_TO_SEVERITY = {1: "INFO", 2: "WARN", 3: "ERROR"}
SEVERITY_ORDER = {"INFO": 1, "WARN": 2, "ERROR": 3}
MIN_SEVERITY_CHOICES = ("info", "warn", "error")

WORKER_TEMP_PREFIX = "epub-validity-"

# 类别 -> 说明。用于 `--list-categories` 与终端汇总，避免口径只存在于代码里。
CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "container": "无法打开/解析 EPUB 容器",
    "xml": "XHTML/XML 不是良构文档",
    "opf": "OPF 清单、spine 或 metadata 不一致",
    "nav": "导航文档缺失或无效",
    "link": "链接指向不存在的文件或锚点",
    "resource": "引用的资源缺失或未被引用",
    "font": "字体缺失或声明错误",
    "image": "图片损坏或声明错误",
    "encoding": "编码声明与实际内容不符",
    "filename": "文件名非法或与清单不一致",
    "ids": "元素 ID 重复或非法",
    "markup": "HTML 标记结构问题",
    "mimetype": "mimetype 声明问题",
    "empty-file": "应含内容的空文件",
    "css-syntax": "CSS 语法错误",
    "other": "未归类（需要补类别映射）",
    "css-order": "选择器书写顺序建议（样式风格）",
    "css-duplicate": "重复选择器（样式风格）",
    "css-empty-block": "空规则块（样式风格）",
    "html-size": "单个 XHTML 体积过大（样式风格）",
}
STRUCTURAL_EXCLUDES = ("css-order", "css-duplicate", "css-empty-block", "html-size")


@dataclass(frozen=True)
class Target:
    """一个待校验对象：`.epub` 成品或解包书籍目录。"""

    path: Path
    kind: str  # "epub" | "dir"

    @property
    def display(self) -> str:
        """报告里用的路径：仓库内用相对路径，仓库外用绝对路径。"""
        try:
            return self.path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return self.path.as_posix()


# ---------------------------------------------------------------------------
# 目标收集
# ---------------------------------------------------------------------------

def is_book_dir(path: Path) -> bool:
    """判断目录是否是一本书的解包源（有 mimetype 与 container.xml）。"""
    if not path.is_dir():
        return False
    return all((path / marker).is_file() for marker in BOOK_MARKERS)


def looks_like_book_dir(path: Path) -> bool:
    """只差标记文件的书籍目录：仅用于提示，不纳入校验。"""
    if not path.is_dir() or is_book_dir(path):
        return False
    return (path / "META-INF" / "container.xml").is_file() or (path / "OEBPS").is_dir()


def collect_targets(
    raw_paths: Sequence[Path],
    recursive: bool = False,
    pattern: str = "*",
) -> tuple[list[Target], list[str]]:
    """把输入路径展开成去重、按路径排序的校验目标。返回 (目标, 警告)。"""
    found: dict[Path, Target] = {}
    warnings: list[str] = []
    glob = pattern.casefold()

    def matches(path: Path) -> bool:
        return fnmatch.fnmatch(path.name.casefold(), glob)

    def add_file(path: Path) -> None:
        if path.suffix.lower() == EPUB_SUFFIX and matches(path):
            found[path.resolve()] = Target(path.resolve(), "epub")

    def add_dir(path: Path) -> None:
        if matches(path):
            found[path.resolve()] = Target(path.resolve(), "dir")

    for raw_path in raw_paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            warnings.append(f"路径不存在，已跳过: {raw_path}")
            continue
        if path.is_file():
            if path.suffix.lower() != EPUB_SUFFIX:
                warnings.append(f"不是 .epub 文件，已跳过: {raw_path}")
            else:
                add_file(path)
            continue
        if is_book_dir(path):
            add_dir(path)
            continue
        if looks_like_book_dir(path):
            warnings.append(
                "目录像是书籍解包源但缺 " + " 或 ".join(BOOK_MARKERS) + f"，已跳过: {raw_path}"
            )
            continue

        # 普通目录：扫它下面（一层或递归）的 .epub 与书籍目录。
        before = len(found)
        iterator = path.rglob("*") if recursive else path.iterdir()
        for child in iterator:
            if child.is_file():
                add_file(child)
            elif child.is_dir() and is_book_dir(child):
                add_dir(child)
        if len(found) == before:
            hint = "" if recursive else "（子目录里的书籍需要 --recursive）"
            warnings.append(f"目录里没有找到 .epub 或书籍目录{hint}: {raw_path}")

    targets = sorted(found.values(), key=lambda item: (item.kind, item.display.casefold()))
    return targets, warnings


# ---------------------------------------------------------------------------
# calibre 接口兼容层
# ---------------------------------------------------------------------------

def load_calibre_api(
    calibre_threads: int | None = None,
) -> tuple[Callable[..., Any], Callable[[Any], list[Any]], list[str]]:
    """导入 calibre 内部校验接口。返回 (get_container, run_checks, 警告)。"""
    warnings: list[str] = []
    try:
        from calibre.ebooks.oeb.polish.check.main import run_checkers, run_checks
        from calibre.ebooks.oeb.polish.container import get_container
    except ImportError as exc:  # pragma: no cover - 取决于本机环境
        raise RuntimeError(
            "无法导入 calibre 的校验模块（calibre.ebooks.oeb.polish.*）。"
            "请确认已安装 calibre，且校验子进程由 calibre 自带的 Python 启动；"
            f"原始错误: {exc}"
        ) from exc

    if calibre_threads is not None:
        # calibre 的 run_checkers 用模块级 cpu_count() 决定线程池大小；多分片并行时
        # 让每个分片内部串行，避免「进程数 × 线程数」把 CPU 打满。这依赖 calibre
        # 内部实现，拿不到就降级为警告，不阻断校验。
        namespace = getattr(run_checkers, "__globals__", None)
        if isinstance(namespace, dict) and "cpu_count" in namespace:
            namespace["cpu_count"] = lambda: calibre_threads
        else:
            warnings.append(
                "当前 calibre 版本未暴露 run_checkers.cpu_count，"
                f"已按 calibre 默认线程数运行（--calibre-threads {calibre_threads} 未生效）"
            )
    return get_container, run_checks, warnings


def find_calibre_debug(explicit: Path | None = None) -> str | None:
    """定位本机 calibre 的 calibre-debug 可执行文件。"""
    if explicit is not None:
        return str(explicit)
    found = shutil.which("calibre-debug")
    if found:
        return found
    candidates = (
        r"C:\Program Files\Calibre2\calibre-debug.exe",
        r"C:\Program Files (x86)\Calibre2\calibre-debug.exe",
        "/Applications/calibre.app/Contents/MacOS/calibre-debug",
        "/opt/calibre/calibre-debug",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


def calibre_available_here() -> bool:
    """当前解释器是否自带 calibre 模块（即由 calibre-debug 启动）。"""
    try:
        return importlib.util.find_spec("calibre") is not None
    except (ImportError, ValueError):  # pragma: no cover - 环境相关
        return False


def is_calibre_launcher(executable: str) -> bool:
    """`sys.executable` 是否其实是 calibre 的启动器（而非普通 Python）。"""
    return Path(executable).stem.casefold().startswith("calibre")


_CALIBRE_VERSION: str | None = None


def calibre_version(calibre_debug: str | None = None) -> str | None:
    """取 calibre 版本，仅用于报告头；拿不到就返回 None。"""
    global _CALIBRE_VERSION
    if _CALIBRE_VERSION is not None:
        return _CALIBRE_VERSION
    version: str | None = None
    try:
        from calibre import __version__ as imported_version  # type: ignore[import-not-found]
        version = imported_version
    except Exception:  # noqa: BLE001 - 版本只影响报告头
        version = None
    if version is None:
        executable = calibre_debug
        if executable and not is_calibre_launcher(executable) and Path(executable).name.startswith("python"):
            executable = None
        executable = executable or find_calibre_debug(None)
        if executable:
            try:
                completed = subprocess.run(
                    [executable, "--version"], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=60,
                )
                for token in (completed.stdout or "").split():
                    cleaned = token.strip("()[],;")
                    if cleaned[:1].isdigit() and "." in cleaned:
                        version = cleaned
                        break
            except Exception:  # noqa: BLE001 - 版本只影响报告头
                version = None
    _CALIBRE_VERSION = version
    return version


# ---------------------------------------------------------------------------
# 单本校验
# ---------------------------------------------------------------------------

def severity_of(error: object) -> str:
    level = getattr(error, "level", None)
    if level in LEVEL_TO_SEVERITY:
        return LEVEL_TO_SEVERITY[level]
    name = type(error).__name__.casefold()
    if "warn" in name:
        return "WARN"
    if "info" in name:
        return "INFO"
    return "ERROR"


def position_of(error: object) -> tuple[int | None, int | None]:
    line = getattr(error, "line", None)
    col = getattr(error, "col", None)
    if line is None:
        # 少数错误（如 CSSError）只在消息里带 "(行, 列)"，属性上拿不到。
        match = re.search(r"\((\d+),\s*(\d+)\)", str(error))
        if match:
            line, col = int(match.group(1)), int(match.group(2))
    return (line if isinstance(line, int) else None,
            col if isinstance(col, int) else None)


def classify(type_name: str, message: str) -> str:
    """把 calibre 的错误类型 + 消息归入本工具的类别。"""
    name = (type_name or "").casefold()
    text = (message or "").casefold()

    if "css" in name:
        if "unexpected empty block" in text:
            return "css-empty-block"
        if "to come before" in text or "expected selector" in text:
            return "css-order"
        if "duplicate selector" in text:
            return "css-duplicate"
        return "css-syntax"
    if "dangling" in name or "dangling" in text:
        return "link"
    if "baddestination" in name or "destination fragment" in text:
        # 链接目标文件在，但锚点（#fragment）不存在。
        return "link"
    if "missingnav" in name:
        return "nav"
    if "idref" in name:
        return "opf"
    if "unreferenced" in name or "unreferenced" in text:
        return "resource"
    if "xml" in name or "not well-formed" in text or "syntax error" in text:
        return "xml"
    if "opf" in name:
        return "opf"
    if "font" in name:
        return "font"
    if "raster" in name or "image" in name:
        return "image"
    if "encoding" in name:
        return "encoding"
    if "filename" in name or "file name" in name:
        return "filename"
    if "emptyfile" in name or "empty file" in text:
        return "empty-file"
    if "mimetype" in name:
        return "mimetype"
    if name.startswith("id") or name.endswith("ids") or "checkid" in name:
        return "ids"
    # 体积类要在标记类之前判定：LargeHTMLFile 同时含 "html"。
    if "size" in name or "large" in name or "too big" in text:
        return "html-size"
    if "markup" in name or "html" in name:
        return "markup"
    if "missing" in text and "file" in text:
        return "resource"
    return "other"


def issue_to_dict(error: object) -> dict[str, object]:
    type_name = type(error).__name__
    message = str(error)
    line, col = position_of(error)
    return {
        "severity": severity_of(error),
        "category": classify(type_name, message),
        "type": type_name,
        "file": getattr(error, "name", None),
        "line": line,
        "column": col,
        "message": message,
    }


def failure_issue(message: str) -> dict[str, object]:
    """单本检查整体失败（容器打不开、子进程中断等）时合成的一条问题。"""
    return {
        "severity": "ERROR",
        "category": "container",
        "type": "CheckFailure",
        "file": None,
        "line": None,
        "column": None,
        "message": message,
    }


def check_target(
    target: Target,
    get_container: Callable[..., Any],
    run_checks: Callable[[Any], list[Any]],
) -> dict[str, object]:
    """校验单个目标。任何异常都收敛成一条 container 问题，不中断整批。"""
    started = time.time()
    result: dict[str, object] = {
        "path": target.display,
        "kind": target.kind,
        "issue_count": 0,
        "issues": [],
        "failed": False,
        "seconds": 0.0,
    }
    try:
        with tempfile.TemporaryDirectory(prefix=WORKER_TEMP_PREFIX) as temp_dir:
            path_text = str(target.path)
            # .epub 会被解包到临时目录；解包目录本身就是容器，不需要 tdir。
            container = (
                get_container(path_text, tdir=temp_dir)
                if target.kind == "epub"
                else get_container(path_text)
            )
            try:
                errors = list(run_checks(container))
            finally:
                del container
    except Exception as exc:  # noqa: BLE001 - 单本失败不应中断整批
        result["issues"] = [failure_issue(f"{type(exc).__name__}: {exc}")]
        result["issue_count"] = 1
        result["failed"] = True
        result["seconds"] = round(time.time() - started, 3)
        return result

    issues = [issue_to_dict(error) for error in errors]
    result["issues"] = issues
    result["issue_count"] = len(issues)
    result["seconds"] = round(time.time() - started, 3)
    return result


# ---------------------------------------------------------------------------
# 过滤与汇总
# ---------------------------------------------------------------------------

def split_categories(values: Iterable[str]) -> list[str]:
    """支持用逗号一次给多个类别。"""
    result: list[str] = []
    for value in values:
        for piece in str(value).split(","):
            piece = piece.strip()
            if piece:
                result.append(piece)
    return result


def keep_issue(issue: dict[str, object], min_severity: str, excluded: set[str]) -> bool:
    # 级别无法识别时按 ERROR 处理：宁可多报，也不静默丢掉没见过的级别。
    threshold = SEVERITY_ORDER[min_severity.upper()]
    severity = str(issue.get("severity", "ERROR")).upper()
    if SEVERITY_ORDER.get(severity, 3) < threshold:
        return False
    return str(issue.get("category", "other")) not in excluded


def filter_results(
    results: Sequence[dict[str, object]],
    min_severity: str,
    excluded: set[str],
) -> list[dict[str, object]]:
    """按严重级别与类别过滤，返回新结果（不改原对象）。"""
    filtered: list[dict[str, object]] = []
    for result in results:
        issues = [
            issue
            for issue in result["issues"]  # type: ignore[union-attr]
            if keep_issue(issue, min_severity, excluded)
        ]
        kept = dict(result)
        kept["total_issue_count"] = result["issue_count"]
        kept["issue_count"] = len(issues)
        kept["issues"] = issues
        filtered.append(kept)
    return filtered


def message_signature(issue: dict[str, object]) -> str:
    """把同类消息归并成一个签名，便于看「哪一类问题最多」。"""
    text = str(issue.get("message", ""))
    # calibre 的消息形如 "CSSError:<路径> (12, 3):<正文>"，只保留正文部分，
    # 否则每本书的路径都会把同一类问题拆成不同签名。
    body = text.rsplit(":", 1)[-1] if ":" in text else text
    collapsed: list[str] = []
    for char in body:
        if char.isdigit():
            if collapsed and collapsed[-1] != "#":
                collapsed.append("#")
            continue
        collapsed.append(char)
    signature = "".join(collapsed).strip()
    return (signature or body.strip() or text)[:160]


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def format_issue_line(issue: dict[str, object]) -> str:
    location = str(issue.get("file") or "")
    line = issue.get("line")
    column = issue.get("column")
    if line:
        location += f":{line}"
        if column:
            location += f":{column}"
    head = f"{issue.get('severity')} [{issue.get('category')}] {issue.get('type')}"
    tail = " ".join(part for part in (location, str(issue.get("message", ""))) if part)
    return f"  - {head} {tail}".rstrip()


def write_text_report(results: Sequence[dict[str, object]], path: Path, header: str) -> None:
    total = sum(int(result["issue_count"]) for result in results)
    lines = [
        "Calibre EPUB validity report",
        header,
        f"Targets checked: {len(results)}",
        f"Total issues: {total}",
        "",
    ]
    for result in results:
        lines.append(f"[{result['issue_count']} issues] {result['path']}")
        for issue in result["issues"]:  # type: ignore[union-attr]
            lines.append(format_issue_line(issue))
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_json_report(results: Sequence[dict[str, object]], path: Path, header: str) -> None:
    payload = {
        "header": header,
        "targets": len(results),
        "total_issues": sum(int(result["issue_count"]) for result in results),
        "results": list(results),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_tsv_report(results: Sequence[dict[str, object]], path: Path) -> None:
    columns = ("book", "severity", "category", "type", "file", "line", "column", "message")
    lines = ["\t".join(columns)]
    for result in results:
        for issue in result["issues"]:  # type: ignore[union-attr]
            row = (
                str(result["path"]),
                str(issue.get("severity", "")),
                str(issue.get("category", "")),
                str(issue.get("type", "")),
                str(issue.get("file") or ""),
                "" if issue.get("line") is None else str(issue.get("line")),
                "" if issue.get("column") is None else str(issue.get("column")),
                str(issue.get("message", "")).replace("\t", " ").replace("\n", " "),
            )
            lines.append("\t".join(row))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def count_by(results: Sequence[dict[str, object]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        for issue in result["issues"]:  # type: ignore[union-attr]
            value = str(issue.get(key) or "?")
            counts[value] = counts.get(value, 0) + 1
    return counts


def print_summary(
    results: Sequence[dict[str, object]],
    targets: Sequence[Target],
    header: str,
    filters_note: str,
) -> None:
    failed = [result for result in results if result.get("failed")]
    by_severity = count_by(results, "severity")
    by_category = count_by(results, "category")
    total = sum(int(result["issue_count"]) for result in results)

    print("", flush=True)
    print("=" * 72)
    print(f"EPUB 合法性校验（{header}）")
    print(f"目标 {len(targets)} 个（解包目录 {sum(1 for t in targets if t.kind == 'dir')}，"
          f".epub {sum(1 for t in targets if t.kind == 'epub')}）；"
          f"完成 {len(results)} 个，失败 {len(failed)} 个")
    print(f"过滤口径：{filters_note}")
    severity_text = "，".join(
        f"{name} {by_severity[name]}" for name in ("ERROR", "WARN", "INFO") if name in by_severity
    )
    print(f"问题合计：{total}" + (f"（{severity_text}）" if severity_text else ""))

    if by_category:
        print("-" * 72)
        print("按类别：")
        for category, count in sorted(by_category.items(), key=lambda item: (-item[1], item[0])):
            scope = "样式风格" if category in STRUCTURAL_EXCLUDES else "结构性"
            print(f"  {count:6d}  {category:<16}{scope}  {CATEGORY_DESCRIPTIONS.get(category, '')}")

    signatures: dict[str, int] = {}
    for result in results:
        for issue in result["issues"]:  # type: ignore[union-attr]
            signature = message_signature(issue)
            signatures[signature] = signatures.get(signature, 0) + 1
    if signatures:
        print("-" * 72)
        print("按消息模式（Top 10）：")
        for signature, count in sorted(signatures.items(), key=lambda item: (-item[1], item[0]))[:10]:
            print(f"  {count:6d}  {signature}")

    problem_books = [result for result in results if int(result["issue_count"])]
    if problem_books:
        print("-" * 72)
        print(f"有问题的书（{len(problem_books)} 本）：")
        for result in sorted(problem_books, key=lambda item: -int(item["issue_count"]))[:20]:
            print(f"  {result['issue_count']:6}  {result['path']}")
        if len(problem_books) > 20:
            print(f"  ... 另有 {len(problem_books) - 20} 本，见 --report/--tsv")
    if failed:
        print("-" * 72)
        print("检查失败（无法打开或子进程中断）：")
        for result in failed:
            first = result["issues"][0]  # type: ignore[index]
            print(f"  {result['path']}: {first['message']}")
    if total == 0 and not failed:
        print("未发现问题。")
    print("=" * 72, flush=True)


# ---------------------------------------------------------------------------
# 并行调度
# ---------------------------------------------------------------------------

def worker_configuration(file_count: int, requested_jobs: int | None,
                         available_cpus: int | None = None) -> int:
    """决定并行分片数：不超过目标数、CPU 数与 4。"""
    cpus = max(1, available_cpus or os.cpu_count() or 1)
    if requested_jobs is None:
        return max(1, min(file_count, min(4, cpus // 2)))
    return max(1, min(file_count, requested_jobs, cpus))


def worker_command(calibre_debug: str | None) -> list[str]:
    """构造校验子进程的命令行。

    当前解释器自带 calibre 时直接用它；否则用 calibre-debug 执行本脚本，后者
    需要用 `--` 把本脚本的参数与 calibre-debug 自己的参数分开。
    """
    if calibre_available_here():
        executable = sys.executable
        if is_calibre_launcher(executable):
            return [executable, str(SCRIPT_PATH), "--"]
        return [executable, str(SCRIPT_PATH)]
    if calibre_debug is None:
        raise RuntimeError(
            "找不到 calibre-debug，且当前解释器没有 calibre 模块。"
            "请安装 calibre，或用 --calibre-debug 指定可执行文件路径。"
        )
    return [calibre_debug, str(SCRIPT_PATH), "--"]


def run_worker_batch(
    batch_path: Path,
    out_path: Path,
    calibre_threads: int | None,
    label: str,
    quiet: bool = False,
) -> int:
    """子进程入口：逐本校验并**增量**写 JSONL，父进程超时也能保住已完成的结果。"""
    try:
        get_container, run_checks, warnings = load_calibre_api(calibre_threads)
    except RuntimeError as exc:
        print(f"[{label}] {exc}", file=sys.stderr, flush=True)
        return EXIT_SETUP_ERROR
    for warning in warnings:
        print(f"[{label}] 警告: {warning}", file=sys.stderr, flush=True)

    paths = json.loads(batch_path.read_text(encoding="utf-8"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for index, path_text in enumerate(paths, start=1):
            raw = Path(path_text)
            target = Target(raw, "dir" if raw.is_dir() else "epub")
            result = check_target(target, get_container, run_checks)
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            handle.flush()
            if not quiet:
                flag = "失败" if result["failed"] else f"{result['issue_count']} 问题"
                print(f"[{label}] {index}/{len(paths)} {target.display} — {flag}", flush=True)
    return EXIT_OK


def run_checks_parallel(
    targets: Sequence[Target],
    jobs: int,
    calibre_threads: int | None,
    calibre_debug: str | None,
    timeout: float,
    progress: bool,
) -> tuple[list[dict[str, object]], list[str]]:
    """把目标交错分片交给多个子进程，各片结束后按原顺序汇总。"""
    warnings: list[str] = []
    results: dict[str, dict[str, object]] = {}
    base = worker_command(calibre_debug)
    chunks = [list(targets[index::jobs]) for index in range(jobs)]

    with tempfile.TemporaryDirectory(prefix=WORKER_TEMP_PREFIX) as work_dir:
        work = Path(work_dir)
        running: list[tuple[subprocess.Popen, list[Target], Path, int]] = []
        for index, chunk in enumerate(chunks, start=1):
            if not chunk:
                continue
            batch_path = work / f"batch-{index}.json"
            out_path = work / f"out-{index}.jsonl"
            batch_path.write_text(
                json.dumps([str(target.path) for target in chunk]), encoding="utf-8"
            )
            command = base + [
                "--worker-batch", str(batch_path),
                "--worker-out", str(out_path),
                "--worker-label", f"w{index}",
            ]
            if calibre_threads is not None:
                command += ["--calibre-threads", str(calibre_threads)]
            if not progress:
                command.append("--quiet-worker")
            # calibre initializes GUI preferences even for Check Book. Keep that
            # state in this worker's temporary directory and do not load the
            # user's plugins or write to their personal configuration.
            config = work / f"calibre-config-{index}"
            config.mkdir()
            environment = os.environ.copy()
            environment["CALIBRE_CONFIG_DIRECTORY"] = str(config)
            running.append((subprocess.Popen(command, env=environment), chunk, out_path, index))

        for process, chunk, out_path, index in running:
            label = f"w{index}"
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                warnings.append(f"[{label}] 超过 {timeout:.0f} 秒未完成，已终止该分片")

            done: dict[str, dict[str, object]] = {}
            if out_path.is_file():
                for line in out_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    done[str(item.get("path"))] = item

            for target in chunk:
                if target.display in done:
                    results[target.display] = done[target.display]
                else:
                    results[target.display] = {
                        "path": target.display,
                        "kind": target.kind,
                        "issue_count": 1,
                        "issues": [failure_issue(
                            f"校验未完成（子进程退出码 {process.returncode}）"
                        )],
                        "failed": True,
                        "seconds": 0.0,
                    }

    ordered = [results[target.display] for target in targets if target.display in results]
    return ordered, warnings


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须是 ≥1 的整数")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("必须是 ≥0 的整数")
    return parsed


def print_categories() -> None:
    print(f"{'类别':<18}{'适用范围':<12}说明")
    for category, description in CATEGORY_DESCRIPTIONS.items():
        scope = "样式风格" if category in STRUCTURAL_EXCLUDES else "结构性"
        print(f"{category:<18}{scope:<12}{description}")
    print("\n--structural 会排除：" + "、".join(STRUCTURAL_EXCLUDES))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="用 calibre 的 Check Book 接口对 EPUB 做只读合法性校验。",
        epilog="不传路径时默认校验 EPUB/；详见本文件头部说明。",
    )
    parser.add_argument("paths", nargs="*", type=Path,
                        help="EPUB 文件、书籍解包目录或它们的上级目录（默认 EPUB/）")
    parser.add_argument("--recursive", action="store_true",
                        help="目录输入时递归扫描子目录")
    parser.add_argument("--pattern", default="*",
                        help="只处理名称匹配该 glob 的目标（大小写不敏感）")
    parser.add_argument("--jobs", type=positive_int, default=None,
                        help="并行分片数（默认自动，最多 4；1 表示单分片）")
    parser.add_argument("--calibre-threads", type=non_negative_int, default=1,
                        help="每个分片内 calibre 的检查线程数（默认 1；0 表示用 calibre 默认）")
    parser.add_argument("--timeout", type=float, default=900.0,
                        help="单个分片的超时秒数（默认 900）")
    parser.add_argument("--min-severity", choices=MIN_SEVERITY_CHOICES, default="info",
                        help="只报告不低于该级别的问题（默认 info，即全部）")
    parser.add_argument("--exclude-category", action="append", default=[],
                        help="排除某类别，可重复或用逗号分隔")
    parser.add_argument("--structural", action="store_true",
                        help="等价于排除 " + ",".join(STRUCTURAL_EXCLUDES) + "，只看结构性合法性问题")
    parser.add_argument("--strict", action="store_true",
                        help="过滤后仍有问题（含单本检查失败）时以退出码 1 结束")
    parser.add_argument("--report", type=Path, default=None, help="写出文本明细报告")
    parser.add_argument("--json", dest="json_report", type=Path, default=None,
                        help="写出 JSON 报告")
    parser.add_argument("--tsv", dest="tsv_report", type=Path, default=None,
                        help="写出 TSV 明细")
    parser.add_argument("--quiet", action="store_true", help="不打印逐本进度")
    parser.add_argument("--list-categories", action="store_true", help="打印类别表后退出")
    parser.add_argument("--calibre-debug", type=Path, default=None,
                        help="calibre-debug 可执行文件路径（默认自动探测）")
    # 子进程入口（内部使用）
    parser.add_argument("--worker-batch", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--worker-out", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--worker-label", default="worker", help=argparse.SUPPRESS)
    parser.add_argument("--quiet-worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_categories:
        print_categories()
        return EXIT_OK

    if args.worker_batch is not None:
        if args.worker_out is None:
            print("--worker-batch 需要同时给出 --worker-out", file=sys.stderr)
            return EXIT_SETUP_ERROR
        return run_worker_batch(
            args.worker_batch, args.worker_out, args.calibre_threads or None,
            args.worker_label, args.quiet_worker,
        )

    paths = args.paths or [DEFAULT_ROOT]
    targets, collect_warnings = collect_targets(paths, args.recursive, args.pattern)
    for warning in collect_warnings:
        print(f"警告: {warning}", file=sys.stderr, flush=True)
    if not targets:
        print("没有找到可校验的 EPUB 或书籍目录。", file=sys.stderr)
        return EXIT_SETUP_ERROR

    excluded = set(split_categories(args.exclude_category))
    if args.structural:
        excluded.update(STRUCTURAL_EXCLUDES)
    unknown = sorted(name for name in excluded if name not in CATEGORY_DESCRIPTIONS)
    if unknown:
        print("警告: 未知类别（拼写错误？）: " + "、".join(unknown), file=sys.stderr, flush=True)

    calibre_debug = find_calibre_debug(args.calibre_debug)
    jobs = worker_configuration(len(targets), args.jobs)
    header = (
        f"calibre {calibre_version(calibre_debug) or '?'}；分片 {jobs}；"
        f"min-severity {args.min_severity}"
    )
    if not args.quiet:
        print(f"待校验 {len(targets)} 个目标；并行分片 {jobs}；"
              f"calibre 线程/分片 {args.calibre_threads}", flush=True)

    try:
        results, run_warnings = run_checks_parallel(
            targets, jobs, args.calibre_threads or None, calibre_debug,
            args.timeout, not args.quiet,
        )
    except RuntimeError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return EXIT_SETUP_ERROR
    except KeyboardInterrupt:
        print("\n[中断] 已取消", file=sys.stderr)
        return EXIT_SETUP_ERROR

    for warning in run_warnings:
        print(f"警告: {warning}", file=sys.stderr, flush=True)

    filtered = filter_results(results, args.min_severity, excluded)
    filters_note = f"min-severity={args.min_severity}"
    if excluded:
        filters_note += "；排除类别 " + "、".join(sorted(excluded))
    print_summary(filtered, targets, header, filters_note)

    if args.report:
        write_text_report(filtered, args.report, header)
        print(f"文本报告: {args.report}", flush=True)
    if args.json_report:
        write_json_report(filtered, args.json_report, header)
        print(f"JSON 报告: {args.json_report}", flush=True)
    if args.tsv_report:
        write_tsv_report(filtered, args.tsv_report)
        print(f"TSV 报告: {args.tsv_report}", flush=True)

    remaining = sum(int(result["issue_count"]) for result in filtered)
    failures = sum(1 for result in filtered if result.get("failed"))
    if args.strict and (remaining or failures):
        return EXIT_ISSUES
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
