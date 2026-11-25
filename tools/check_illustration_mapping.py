#!/usr/bin/env python3
"""核对 docs/illustration-text-mapping.md 的中日双向插图映射、重嵌清单与改动影响。

功能：
1. 校验 `docs/illustration-text-mapping.md` 第四节（13 列中日映射表）与第五节（待重新嵌字清单）格式及一致性；
2. 逐行回查中文 `EPUB/`（默认必查）与日文 `.cache/epub-work/japanese-text/`（存在且未禁用时必查）的实体文件、物理行号与原文/译文句；
3. 检查映射表与重嵌清单中登记的中日图片文件在对应书目录内是否存在；
4. `--diff [REF]` 检测 `EPUB/` 相对指定 Git 基线（默认 `HEAD`）的改动是否命中已映射正文行、带目录彩图卷的章节标题（`<h1>`/`<h2>`）或插图页/图片资源，并输出显著的【插图文本联动提醒】。

退出码：0 通过；1 映射格式/行位/原句不一致或清单不自洽；2 前置条件失败（文档或显式指定的目录缺失、参数冲突、Git 执行失败）。
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

if __package__:
    from .cli_output import configure_output
    from .epub_ids import book_id
else:
    from cli_output import configure_output
    from epub_ids import book_id

REPO_ROOT = TOOLS_DIR.parent
DEFAULT_DOC = REPO_ROOT / "docs" / "illustration-text-mapping.md"
DEFAULT_JP_ROOT = REPO_ROOT / ".cache" / "epub-work" / "japanese-text"
DEFAULT_CN_ROOT = REPO_ROOT / "EPUB"

COLUMNS = (
    "卷号",
    "日文图片",
    "日文图片文字",
    "日文正文文件",
    "日文行号",
    "日文正文原句",
    "中文图片",
    "中文图片文字",
    "中文正文文件",
    "中文行号",
    "中文正文原句",
    "嵌字状态",
    "备注",
)
RETYPESET_COLUMNS = (
    "卷号",
    "中文图片",
    "优先级",
    "类别",
    "当前图上问题",
    "建议修改／参考文本",
    "映射表行位",
)
VALID_TYPESET_STATES = frozenset({
    "无需重嵌",
    "待重新嵌字",
    "同图它处待重嵌",
    "已无中文图",
    "无中文对照",
})
VALID_PRIORITIES = frozenset({"高", "中", "低"})

_DASHES = {"", "—", "-"}
_ESCAPED_PIPE_SENTINEL = "\x00PIPE\x00"
_SEP_RE = re.compile(r"^[\s|:\-]+$")
_RANGE_RE = re.compile(r"^(\d+)(?:[–-](\d+))?$")
_RT_RP_RE = re.compile(r"<(?:rt|rp)\b[^>]*>.*?</(?:rt|rp)\s*>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[\s\u3000]+")
_HEADING_RE = re.compile(r"<h[12]\b", re.I)
_DIFF_OLD_FILE_RE = re.compile(r"^--- a/(.+)$")
_DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")
_DIFF_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".svg"}


def norm(text: str) -> str:
    """移除注音以外的空白差异，便于与映射表原文逐字比对。"""
    return _WS_RE.sub("", html.unescape(text))


def _uncode(cell: str) -> str:
    cell = cell.strip()
    if len(cell) >= 2 and cell.startswith("`") and cell.endswith("`") and "`" not in cell[1:-1]:
        return cell[1:-1].strip()
    return cell


def _split_md_row(line: str) -> list[str]:
    safe = line.strip().replace("\\|", _ESCAPED_PIPE_SENTINEL)
    if safe.startswith("|"):
        safe = safe[1:]
    if safe.endswith("|"):
        safe = safe[:-1]
    return [_uncode(part.replace(_ESCAPED_PIPE_SENTINEL, "|")) for part in safe.split("|")]


def _line_plain(raw_line: str) -> str:
    without_ruby = _RT_RP_RE.sub("", raw_line)
    plain = _TAG_RE.sub("", without_ruby)
    return html.unescape(plain)


def parse_line_spec(spec: str) -> tuple[int, int] | None:
    """把行号或起止区间（如 `194–204`）解析为闭区间 `(start, end)`。"""
    m = _RANGE_RE.match(spec.strip())
    if not m:
        return None
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    if start < 1 or end < start:
        return None
    return start, end


def read_doc(doc: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    """解析映射文档，返回 `(映射表行列表, 重嵌清单行列表, 解析错误列表)`。"""
    if not doc.is_file():
        return [], [], [f"文档不存在：{doc}"]

    rows: list[dict[str, str]] = []
    retypeset_rows: list[dict[str, str]] = []
    errors: list[str] = []
    mode: str | None = None
    saw_map_header = False
    saw_retypeset_header = False

    for lineno, raw in enumerate(doc.read_text(encoding="utf-8-sig").splitlines(), 1):
        stripped = raw.strip()
        if not stripped.startswith("|"):
            mode = None
            continue
        cells = _split_md_row(stripped)
        if _SEP_RE.match(stripped):
            continue

        tup = tuple(cells)
        if mode is None:
            if tup == COLUMNS:
                mode = "map"
                saw_map_header = True
            elif tup == RETYPESET_COLUMNS:
                mode = "retypeset"
                saw_retypeset_header = True
            else:
                mode = "skip"
            continue

        if mode == "skip":
            continue

        if mode == "map":
            if len(cells) != len(COLUMNS):
                errors.append(f"L{lineno}: 映射表列数应为 {len(COLUMNS)}，实为 {len(cells)}：{stripped[:80]}")
                continue
            item = dict(zip(COLUMNS, cells))
            item["_doc_line"] = str(lineno)
            state = item["嵌字状态"]
            if state not in VALID_TYPESET_STATES:
                errors.append(f"L{lineno}: 非法嵌字状态 {state!r}（允许：{sorted(VALID_TYPESET_STATES)}）")
            for col in ("日文行号", "中文行号"):
                val = item[col]
                if val not in _DASHES and parse_line_spec(val) is None:
                    errors.append(f"L{lineno}: 非法{col} {val!r}")
            rows.append(item)
            continue

        if mode == "retypeset":
            if len(cells) != len(RETYPESET_COLUMNS):
                errors.append(f"L{lineno}: 重嵌清单列数应为 {len(RETYPESET_COLUMNS)}，实为 {len(cells)}：{stripped[:80]}")
                continue
            item = dict(zip(RETYPESET_COLUMNS, cells))
            item["_doc_line"] = str(lineno)
            if item["优先级"] not in VALID_PRIORITIES:
                errors.append(f"L{lineno}: 非法重嵌优先级 {item['优先级']!r}")
            if item["中文图片"] in _DASHES:
                errors.append(f"L{lineno}: 重嵌清单缺少中文图片名")
            retypeset_rows.append(item)

    if not saw_map_header:
        errors.append(f"未找到标准 13 列映射表表头：{' | '.join(COLUMNS)}")

    retypeset_imgs = {(r["卷号"], r["中文图片"]) for r in retypeset_rows}
    if saw_retypeset_header or any(r["嵌字状态"] in {"待重新嵌字", "同图它处待重嵌"} for r in rows):
        for r in rows:
            if r["嵌字状态"] in {"待重新嵌字", "同图它处待重嵌"}:
                key = (r["卷号"], r["中文图片"])
                if r["中文图片"] in _DASHES:
                    errors.append(f"L{r['_doc_line']}: 嵌字状态为 {r['嵌字状态']} 但未填写中文图片")
                elif not saw_retypeset_header:
                    errors.append(f"L{r['_doc_line']}: 存在待重嵌记录，但文档缺少五号重嵌清单表")
                elif key not in retypeset_imgs:
                    errors.append(f"L{r['_doc_line']}: {key[0]} {key[1]} 标记为 {r['嵌字状态']}，但未列入重嵌清单")

    return rows, retypeset_rows, errors


def read_rows(doc: Path) -> tuple[list[dict[str, str]], list[str]]:
    """兼容旧入口：返回 `(映射表行列表, 解析错误列表)`。"""
    rows, _retypeset_rows, errors = read_doc(doc)
    return rows, errors


def volume_dir(root: Path, vol: str) -> Path | None:
    """按全角作品号前缀 `【<vol>】*` 查找书目录。"""
    return next((p for p in sorted(root.glob(f"【{vol}】*")) if p.is_dir()), None)


def xhtml_dir(vol_dir: Path) -> Path | None:
    """定位卷内 XHTML 正文目录（兼容中文 OEBPS/Text 与日文 item/xhtml）。"""
    for cand in (
        vol_dir / "OEBPS" / "Text",
        vol_dir / "item" / "xhtml",
        vol_dir / "xhtml",
        vol_dir,
    ):
        if cand.is_dir() and any(cand.glob("*.xhtml")):
            return cand
    return None


def image_dir(vol_dir: Path) -> Path | None:
    """定位卷内图片目录（兼容中文 OEBPS/Images 与日文 item/image）。"""
    for cand in (
        vol_dir / "OEBPS" / "Images",
        vol_dir / "item" / "image",
        vol_dir / "Images",
        vol_dir / "image",
        vol_dir,
    ):
        if cand.is_dir() and any(cand.iterdir()):
            return cand
    return None


class _SideCache:
    """单次检查的卷目录、XHTML 纯文本与图片清单缓存。"""

    def __init__(self, root: Path):
        self.root = root
        self._vols: dict[str, Path | None] = {}
        self._xdirs: dict[str, Path | None] = {}
        self._idirs: dict[str, Path | None] = {}
        self._imgs: dict[str, set[str]] = {}
        self._lines: dict[Path, list[str]] = {}
        self._norms: dict[Path, list[str]] = {}
        self._vol_xhtmls: dict[str, list[Path]] = {}

    def vol(self, vol_id: str) -> Path | None:
        if vol_id not in self._vols:
            self._vols[vol_id] = volume_dir(self.root, vol_id)
        return self._vols[vol_id]

    def xdir(self, vol_id: str) -> Path | None:
        if vol_id not in self._xdirs:
            v = self.vol(vol_id)
            self._xdirs[vol_id] = xhtml_dir(v) if v is not None else None
        return self._xdirs[vol_id]

    def images(self, vol_id: str) -> set[str] | None:
        if vol_id not in self._idirs:
            v = self.vol(vol_id)
            idir = image_dir(v) if v is not None else None
            self._idirs[vol_id] = idir
            self._imgs[vol_id] = {p.name for p in idir.iterdir() if p.is_file()} if idir else set()
        return self._imgs[vol_id] if self._idirs[vol_id] is not None else None

    def file_norms(self, path: Path) -> list[str]:
        if path not in self._norms:
            raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
            self._lines[path] = raw_lines
            self._norms[path] = [norm(_line_plain(line)) for line in raw_lines]
        return self._norms[path]

    def file_plains(self, path: Path) -> list[str]:
        if path not in self._lines:
            self.file_norms(path)
        return [_line_plain(line).strip() for line in self._lines[path]]

    def vol_xhtmls(self, vol_id: str) -> list[Path]:
        if vol_id not in self._vol_xhtmls:
            xd = self.xdir(vol_id)
            if xd is None:
                self._vol_xhtmls[vol_id] = []
            else:
                hits = sorted(xd.glob(f"{vol_id}-*.xhtml"))
                self._vol_xhtmls[vol_id] = hits if hits else sorted(xd.glob("*.xhtml"))
        return self._vol_xhtmls[vol_id]

    def relocate(self, vol_id: str, expected_path: Path | None, target_norm: str, target_line: int) -> tuple[str | None, int | None]:
        """先在预期文件内按就近行号检索，未果再扫同卷全部章节文件。"""
        if not target_norm:
            return None, None
        candidates: list[Path] = []
        if expected_path is not None and expected_path.is_file():
            candidates.append(expected_path)
        for p in self.vol_xhtmls(vol_id):
            if p != expected_path:
                candidates.append(p)
        for p in candidates:
            norms = self.file_norms(p)
            matches = [i + 1 for i, val in enumerate(norms) if val == target_norm]
            if matches:
                best = min(matches, key=lambda ln: abs(ln - target_line))
                return p.name, best
        return None, None


def _matches_line_spec(norms: list[str], plains: list[str], span: tuple[int, int], expected_raw: str) -> tuple[bool, str]:
    start, end = span
    expected_norm = norm(expected_raw)
    if start == end:
        got_norm = norms[start - 1]
        return got_norm == expected_norm, plains[start - 1]
    joined_norm = "".join(norms[start - 1 : end])
    joined_plain = " ".join(p for p in plains[start - 1 : end] if p)
    if joined_norm == expected_norm:
        return True, joined_plain
    if norms[start - 1] == expected_norm and expected_norm in joined_norm:
        return True, plains[start - 1]
    return False, joined_plain


def _check_side_anchor(
    cache: _SideCache,
    side: str,
    row: dict[str, str],
    *,
    img_col: str,
    file_col: str,
    line_col: str,
    sent_col: str,
    require_vol_for_img: bool,
) -> tuple[bool, dict[str, object] | None]:
    vol = row["卷号"]
    img = row[img_col]
    fn = row[file_col]
    line_spec = row[line_col]
    expected_raw = row[sent_col]

    if img not in _DASHES and require_vol_for_img:
        vdir = cache.vol(vol)
        if vdir is None:
            return False, {
                "side": side,
                "kind": "missing_vol",
                "row": row,
                "message": f"{side.upper()} 缺少书目录：{vol}",
            }
        imgs = cache.images(vol)
        if imgs is None or img not in imgs:
            return False, {
                "side": side,
                "kind": "missing_image",
                "row": row,
                "message": f"{side.upper()} 图片不存在：{vol}/{img}",
            }

    if fn in _DASHES or line_spec in _DASHES:
        return False, None

    xdir = cache.xdir(vol)
    if xdir is None:
        kind = "missing_vol" if cache.vol(vol) is None else "missing_dir"
        return True, {
            "side": side,
            "kind": kind,
            "row": row,
            "message": f"{side.upper()} 正文目录缺失：{vol}",
        }

    xpath = xdir / fn
    if not xpath.is_file():
        suggest_file, suggest_line = cache.relocate(vol, None, norm(expected_raw), 1)
        return True, {
            "side": side,
            "kind": "missing_file",
            "row": row,
            "suggest_file": suggest_file,
            "suggest": suggest_line,
            "message": f"{side.upper()} 文件不存在：{vol}/{fn}",
        }

    span = parse_line_spec(line_spec)
    if span is None:
        return True, {
            "side": side,
            "kind": "bad_line_spec",
            "row": row,
            "message": f"{side.upper()} 行号格式非法：{vol}/{fn}:{line_spec}",
        }

    norms = cache.file_norms(xpath)
    plains = cache.file_plains(xpath)
    if span[1] > len(norms):
        suggest_file, suggest_line = cache.relocate(vol, xpath, norm(expected_raw), span[0])
        kind = "line_drift" if suggest_line is not None else "line_oob"
        return True, {
            "side": side,
            "kind": kind,
            "row": row,
            "expected": expected_raw,
            "actual": f"<EOF at {len(norms)}>",
            "suggest_file": suggest_file,
            "suggest": suggest_line,
            "message": f"{side.upper()} 行号越界：{vol}/{fn}:{line_spec}（共 {len(norms)} 行）",
        }

    ok, actual_plain = _matches_line_spec(norms, plains, span, expected_raw)
    if ok:
        return True, None

    suggest_file, suggest_line = cache.relocate(vol, xpath, norm(expected_raw), span[0])
    if suggest_line is not None:
        return True, {
            "side": side,
            "kind": "line_drift",
            "row": row,
            "expected": expected_raw,
            "actual": actual_plain,
            "suggest_file": suggest_file,
            "suggest": suggest_line,
            "message": f"{side.upper()} 行号漂移：{vol}/{fn}:{line_spec} -> {suggest_file}:{suggest_line}",
        }
    return True, {
        "side": side,
        "kind": "content_changed",
        "row": row,
        "expected": expected_raw,
        "actual": actual_plain,
        "suggest_file": None,
        "suggest": None,
        "message": f"{side.upper()} 正文原句已变更：{vol}/{fn}:{line_spec}",
    }


def check(
    doc: Path,
    jp_root: Path | None = DEFAULT_JP_ROOT,
    limit: int = 0,
    *,
    cn_root: Path | None = None,
    books: set[str] | None = None,
    check_jp: bool = True,
    check_cn: bool = False,
) -> tuple[int, list[dict[str, object]], list[str]]:
    """执行映射校验，返回 `(已校验锚点数, 问题列表, 文档解析错误列表)`。"""
    rows, retypeset_rows, errors = read_doc(doc)
    if errors:
        return 0, [], errors

    target_rows = [r for r in rows if books is None or r["卷号"] in books]
    target_retypeset = [r for r in retypeset_rows if books is None or r["卷号"] in books]

    jp_cache = _SideCache(jp_root) if (check_jp and jp_root is not None) else None
    cn_cache = _SideCache(cn_root) if (check_cn and cn_root is not None) else None

    checked = 0
    problems: list[dict[str, object]] = []
    seen_retypeset_imgs: set[tuple[str, str]] = set()

    def _record(prob: dict[str, object] | None) -> None:
        if prob is not None:
            problems.append(prob)

    for row in target_rows:
        if jp_cache is not None:
            had_anchor, prob = _check_side_anchor(
                jp_cache,
                "jp",
                row,
                img_col="日文图片",
                file_col="日文正文文件",
                line_col="日文行号",
                sent_col="日文正文原句",
                require_vol_for_img=True,
            )
            if had_anchor:
                checked += 1
            _record(prob)

        if cn_cache is not None:
            had_anchor, prob = _check_side_anchor(
                cn_cache,
                "cn",
                row,
                img_col="中文图片",
                file_col="中文正文文件",
                line_col="中文行号",
                sent_col="中文正文原句",
                require_vol_for_img=True,
            )
            if had_anchor:
                checked += 1
            _record(prob)

    if cn_cache is not None:
        for rrow in target_retypeset:
            key = (rrow["卷号"], rrow["中文图片"])
            if key in seen_retypeset_imgs:
                continue
            seen_retypeset_imgs.add(key)
            vol, img = key
            vdir = cn_cache.vol(vol)
            if vdir is None:
                problems.append({
                    "side": "cn",
                    "kind": "missing_vol",
                    "row": rrow,
                    "message": f"重嵌清单指向不存在的中文书目录：{vol}",
                })
            else:
                imgs = cn_cache.images(vol)
                if imgs is None or img not in imgs:
                    problems.append({
                        "side": "cn",
                        "kind": "missing_image",
                        "row": rrow,
                        "message": f"重嵌清单图片不存在：{vol}/{img}",
                    })

    return checked, problems, []


def load_cn_anchors(
    doc: Path = DEFAULT_DOC,
) -> tuple[dict[tuple[str, str, int], list[dict[str, str]]], dict[tuple[str, str], list[dict[str, str]]], list[str]]:
    """供校对复核、术语统一与差异告警共用的中文锚点加载器。

    返回 `(精确行号索引 (vol, file, line) -> rows, 跨行区间索引 (vol, file) -> rows, 解析错误)`。
    """
    rows, _retypeset, errors = read_doc(doc)
    exact: dict[tuple[str, str, int], list[dict[str, str]]] = {}
    ranges: dict[tuple[str, str], list[dict[str, str]]] = {}
    if errors:
        return exact, ranges, errors
    for row in rows:
        vol = row["卷号"]
        fn = row["中文正文文件"]
        lspec = row["中文行号"]
        if fn in _DASHES or lspec in _DASHES:
            continue
        span = parse_line_spec(lspec)
        if span is None:
            continue
        bname = Path(fn).name
        for ln in range(span[0], span[1] + 1):
            exact.setdefault((vol, bname, ln), []).append(row)
        if span[0] != span[1]:
            ranges.setdefault((vol, bname), []).append(row)
    return exact, ranges, []


def find_cn_hits(
    items: Iterable[tuple[str, str, int]],
    doc: Path = DEFAULT_DOC,
) -> list[dict[str, object]]:
    """查询一组 `(vol, file_or_path, line)` 是否命中插图中文映射行。"""
    exact, _ranges, errors = load_cn_anchors(doc)
    if errors:
        return []
    hits: list[dict[str, object]] = []
    seen: set[tuple[str, str, int]] = set()
    for vol, fn, ln in items:
        key = (vol, Path(fn).name, int(ln))
        if key in seen:
            continue
        seen.add(key)
        matched = exact.get(key)
        if matched:
            hits.append({
                "vol": vol,
                "file": key[1],
                "line": key[2],
                "rows": matched,
            })
    return hits


def _parse_book_filter(raw_books: list[str] | None) -> set[str] | None:
    if not raw_books:
        return None
    out: set[str] = set()
    for item in raw_books:
        for part in item.split(","):
            token = part.strip()
            if token:
                out.add(token)
    return out or None


def _vol_has_contents_img(cn_root: Path, vol: str) -> str | None:
    vdir = volume_dir(cn_root, vol)
    if vdir is None:
        return None
    idir = image_dir(vdir)
    if idir is None:
        return None
    for p in sorted(idir.iterdir()):
        if p.is_file() and p.name.startswith(f"{vol}-Contents") and p.suffix.lower() in _IMG_EXTS:
            return p.name
    return None


def _vol_toc_images(
    cn_root: Path,
    vol: str,
    retypeset_rows: list[dict[str, str]] | None = None,
) -> str | None:
    """返回指定卷带目录文字的彩图文件名（优先 `*-Contents*`，其次第五节目录类插图）。"""
    vdir = volume_dir(cn_root, vol)
    contents_imgs: list[str] = []
    if vdir is not None:
        idir = image_dir(vdir)
        if idir is not None:
            contents_imgs = [
                p.name
                for p in sorted(idir.iterdir())
                if p.is_file() and p.name.startswith(f"{vol}-Contents") and p.suffix.lower() in _IMG_EXTS
            ]
    if contents_imgs:
        return ", ".join(contents_imgs)
    if not retypeset_rows:
        return None
    toc_imgs: list[str] = []
    seen: set[str] = set()
    for row in retypeset_rows:
        if row.get("卷号") == vol and "目录" in row.get("类别", ""):
            img = row.get("中文图片", "").strip()
            if img and img not in _DASHES and img not in seen:
                seen.add(img)
                toc_imgs.append(img)
    return ", ".join(toc_imgs) or None


def _parse_git_diff_changes(
    diff_text: str,
    cn_rel_prefix: str,
) -> tuple[dict[tuple[str, str], set[int]], list[tuple[str, str, int, str]], list[str]]:
    """解析 unified diff，返回 `(文件->受影响行号集, 标题变动列表, 插图页/图片文件变动)`。"""
    touched_lines: dict[tuple[str, str], set[int]] = {}
    heading_hits: list[tuple[str, str, int, str]] = []
    asset_hits: list[str] = []
    seen_assets: set[str] = set()

    cur_vol: str | None = None
    cur_name: str | None = None
    cur_is_xhtml = False
    pending_old_path: str | None = None
    old_ln = 0
    new_ln = 0

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            cur_vol = None
            cur_name = None
            cur_is_xhtml = False
            pending_old_path = None
            continue

        if line.startswith("--- "):
            m_old = _DIFF_OLD_FILE_RE.match(line)
            pending_old_path = m_old.group(1) if m_old else None
            continue

        m_file = _DIFF_FILE_RE.match(line)
        if m_file or line == "+++ /dev/null":
            rel_path = m_file.group(1) if m_file else (pending_old_path or "")
            pending_old_path = None
            cur_vol = None
            cur_name = None
            cur_is_xhtml = False
            sub = (
                rel_path[len(cn_rel_prefix) + 1 :]
                if cn_rel_prefix and rel_path.startswith(cn_rel_prefix + "/")
                else (rel_path if not cn_rel_prefix else "")
            )
            sub_parts = [p for p in sub.split("/") if p]
            if len(sub_parts) >= 2:
                book_part = sub_parts[0]
                vol = book_id(book_part) or book_part
                fname = sub_parts[-1]
                cur_vol = vol
                cur_name = fname
                if fname.endswith("-Illustrations.xhtml") or Path(fname).suffix.lower() in _IMG_EXTS:
                    if rel_path not in seen_assets:
                        seen_assets.add(rel_path)
                        asset_hits.append(rel_path)
                cur_is_xhtml = fname.endswith(".xhtml") and not fname.endswith("-Illustrations.xhtml")
            continue

        m_hunk = _DIFF_HUNK_RE.match(line)
        if m_hunk and cur_vol and cur_name and cur_is_xhtml:
            old_ln = int(m_hunk.group(1))
            new_ln = int(m_hunk.group(3))
            continue

        if not (cur_vol and cur_name and cur_is_xhtml):
            continue

        if line.startswith("-") and not line.startswith("---"):
            touched_lines.setdefault((cur_vol, cur_name), set()).add(old_ln)
            if _HEADING_RE.search(line[1:]):
                heading_hits.append((cur_vol, cur_name, old_ln, _line_plain(line[1:]).strip()))
            old_ln += 1
        elif line.startswith("+") and not line.startswith("+++"):
            touched_lines.setdefault((cur_vol, cur_name), set()).add(new_ln)
            if _HEADING_RE.search(line[1:]):
                heading_hits.append((cur_vol, cur_name, new_ln, _line_plain(line[1:]).strip()))
            new_ln += 1

    return touched_lines, heading_hits, asset_hits


def scan_git_diff(
    ref: str = "HEAD",
    *,
    repo_root: Path = REPO_ROOT,
    doc: Path = DEFAULT_DOC,
    cn_root: Path = DEFAULT_CN_ROOT,
) -> dict[str, object]:
    """检测相对 Git 基线 `ref` 的 `EPUB/` 改动是否涉及插图文字或目录彩图标题。"""
    exact, _ranges, errors = load_cn_anchors(doc)
    if errors:
        return {"error": "; ".join(errors), "line_hits": [], "heading_hits": [], "asset_hits": []}

    try:
        cn_rel = cn_root.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        cn_rel = "EPUB"

    proc = subprocess.run(
        ["git", "-C", str(repo_root), "-c", "core.quotePath=false", "diff", "-U0", "--no-color", ref, "--", cn_rel],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return {
            "error": f"git diff 失败（exit={proc.returncode}）：{proc.stderr.strip()}",
            "line_hits": [],
            "heading_hits": [],
            "asset_hits": [],
        }

    # 同时检查二进制图片文件变更（git diff --name-only）
    proc_names = subprocess.run(
        ["git", "-C", str(repo_root), "-c", "core.quotePath=false", "diff", "--name-only", ref, "--", cn_rel],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    extra_assets = []
    if proc_names.returncode == 0:
        for rel in proc_names.stdout.splitlines():
            rel = rel.strip()
            if rel and (rel.endswith("-Illustrations.xhtml") or Path(rel).suffix.lower() in _IMG_EXTS):
                extra_assets.append(rel)

    touched_lines, raw_heading_hits, asset_hits = _parse_git_diff_changes(proc.stdout, cn_rel)
    for rel in extra_assets:
        if rel not in asset_hits:
            asset_hits.append(rel)

    line_hits: list[dict[str, object]] = []
    for (vol, fname), line_set in sorted(touched_lines.items()):
        for ln in sorted(line_set):
            matched = exact.get((vol, fname, ln))
            if matched:
                line_hits.append({
                    "vol": vol,
                    "file": fname,
                    "line": ln,
                    "rows": matched,
                })

    toc_cache: dict[str, str | None] = {}
    retypeset_rows: list[dict[str, str]] | None = None
    if raw_heading_hits:
        _, retypeset_rows, _ = read_doc(doc)
    grouped_headings: dict[tuple[str, str, int, str], list[str]] = {}
    for vol, fname, ln, txt in raw_heading_hits:
        if vol not in toc_cache:
            toc_cache[vol] = _vol_toc_images(cn_root, vol, retypeset_rows)
        contents_img = toc_cache[vol]
        if contents_img:
            vals = grouped_headings.setdefault((vol, fname, ln, contents_img), [])
            if txt not in vals:
                vals.append(txt)
    heading_hits: list[dict[str, object]] = [
        {
            "vol": vol,
            "file": fname,
            "line": ln,
            "contents_img": contents_img,
            "heading": " -> ".join(vals),
        }
        for (vol, fname, ln, contents_img), vals in sorted(grouped_headings.items())
    ]

    return {
        "error": None,
        "ref": ref,
        "line_hits": line_hits,
        "heading_hits": heading_hits,
        "asset_hits": asset_hits,
    }


def print_illustration_reminder(affected_cn_imgs: list[tuple[str, str, str]]) -> None:
    """在标准输出打印醒目的插图文本联动与最终答复提醒要求。"""
    print("\n【插图文本联动提醒】本次改动或校验涉及彩色插图对应内容：")
    seen: set[tuple[str, str, str]] = set()
    for vol, img, detail in affected_cn_imgs:
        key = (vol, img, detail)
        if key in seen:
            continue
        seen.add(key)
        prefix = f"  - {vol} / {img}" if img and img not in _DASHES else f"  - {vol}（无中文对应彩图）"
        print(f"{prefix}：{detail}")
    print("  [联动提醒] 1) 请同步更新 docs/illustration-text-mapping.md 对应正文行号／正文原句；")
    print("  [联动提醒] 2) 请在最终回复末尾显著提醒受影响的中文插图（未命中清单时保持静默）。")


def _non_negative_int(raw: str) -> int:
    try:
        val = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"必须是非负整数：{raw!r}") from exc
    if val < 0:
        raise argparse.ArgumentTypeError(f"--limit 不能为负数：{val}")
    return val


def main(argv: list[str] | None = None) -> int:
    configure_output()
    ap = argparse.ArgumentParser(description="核对插图文字映射表（中文/日文双向）与改动影响")
    ap.add_argument("--doc", type=Path, default=DEFAULT_DOC, help="映射文档路径")
    ap.add_argument("--cn-root", type=Path, default=None, help="中文 EPUB 根目录（默认 EPUB/）")
    ap.add_argument("--jp-root", type=Path, default=None, help="日文 EPUB 缓存目录（默认 .cache/epub-work/japanese-text）")
    ap.add_argument("--cn-only", action="store_true", help="仅核对中文侧（跳过日文缓存）")
    ap.add_argument("--jp-only", action="store_true", help="仅核对日文侧")
    ap.add_argument("--require-jp", action="store_true", help="日文缓存缺失时按前置条件失败退出")
    ap.add_argument("--book", action="append", default=None, help="仅检查指定作品号，可多次传入或逗号分隔（如 S1_01）")
    ap.add_argument("--diff", nargs="?", const="HEAD", default=None, help="检查相对 Git 基线（默认 HEAD）的改动是否命中插图对应行或目录彩图标题")
    ap.add_argument("--fail-on-diff", action="store_true", help="与 --diff 联用：检测到命中时返回非零退出码")
    ap.add_argument("--limit", type=_non_negative_int, default=0, help="终端最多显示的问题条数（0 表示不限）")
    ap.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    args = ap.parse_args(argv)

    if args.cn_only and args.jp_only:
        print("错误：--cn-only 与 --jp-only 不能同时使用", file=sys.stderr)
        return 2
    if not args.doc.is_file():
        print(f"错误：映射文档不存在：{args.doc}", file=sys.stderr)
        return 2

    cn_root = args.cn_root if args.cn_root is not None else DEFAULT_CN_ROOT
    jp_root = args.jp_root if args.jp_root is not None else DEFAULT_JP_ROOT

    if args.diff is not None:
        result = scan_git_diff(args.diff, doc=args.doc, cn_root=cn_root)
        if result["error"]:
            print(f"错误：{result['error']}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            line_hits = result["line_hits"]
            heading_hits = result["heading_hits"]
            asset_hits = result["asset_hits"]
            total_hits = len(line_hits) + len(heading_hits) + len(asset_hits)
            print(f"插图改动影响扫描（基线 {args.diff}）：正文锚点命中 {len(line_hits)} 条／目录标题联动 {len(heading_hits)} 处／插图资源变动 {len(asset_hits)} 项")
            if total_hits:
                reminders: list[tuple[str, str, str]] = []
                for h in line_hits:
                    for row in h["rows"]:
                        reminders.append((
                            h["vol"],
                            row["中文图片"],
                            f"{h['file']}:{h['line']}｜当前状态={row['嵌字状态']}｜图上「{row['中文图片文字']}」",
                        ))
                for h in heading_hits:
                    reminders.append((
                        h["vol"],
                        h["contents_img"],
                        f"{h['file']}:{h['line']} 修改了标题「{h['heading']}」（涉及目录彩图对照文本）",
                    ))
                for rel in asset_hits:
                    book_seg = next((p for p in Path(rel).parts if p.startswith("【") and "】" in p), "")
                    vol = book_id(book_seg) if book_seg else Path(rel).stem
                    reminders.append((vol or rel, Path(rel).name, f"直接变动：{rel}"))
                print_illustration_reminder(reminders)
        if args.fail_on_diff and (result["line_hits"] or result["heading_hits"] or result["asset_hits"]):
            return 1
        return 0

    if args.cn_only:
        check_cn, check_jp = True, False
    elif args.jp_only:
        check_cn, check_jp = False, True
    elif args.cn_root is not None or args.jp_root is not None:
        check_cn = args.cn_root is not None
        check_jp = args.jp_root is not None or args.require_jp
    else:
        check_cn, check_jp = True, True

    if check_cn and not cn_root.is_dir():
        print(f"错误：中文根目录不存在：{cn_root}", file=sys.stderr)
        return 2

    notes: list[str] = []
    if check_jp and not jp_root.is_dir():
        if args.jp_only or args.jp_root is not None or args.require_jp:
            print(f"错误：日文缓存目录不存在：{jp_root}", file=sys.stderr)
            return 2
        check_jp = False
        notes.append(f"日文参考缓存缺失，已跳过日文侧核对（仅核对中文侧 {cn_root.name}/）")

    books = _parse_book_filter(args.book)
    checked, problems, errors = check(
        args.doc,
        jp_root if check_jp else None,
        limit=args.limit,
        cn_root=cn_root if check_cn else None,
        books=books,
        check_jp=check_jp,
        check_cn=check_cn,
    )

    if args.json:
        print(json.dumps({
            "checked": checked,
            "problems": problems,
            "errors": errors,
            "notes": notes,
        }, ensure_ascii=False, indent=2))
        return 1 if (errors or problems) else 0

    for note in notes:
        print(f"[提示] {note}")
    if errors:
        for err in errors:
            print(f"格式错误：{err}", file=sys.stderr)
        return 1

    sides = []
    if check_cn:
        sides.append("中文")
    if check_jp:
        sides.append("日文")
    print(f"插图映射核对（{'+'.join(sides)}）：已核锚点 {checked} 个／问题 {len(problems)} 条")

    shown = problems[: args.limit] if args.limit else problems
    cn_reminders: list[tuple[str, str, str]] = []
    for p in shown:
        row = p["row"]
        vol = row.get("卷号", "")
        if p.get("side") == "cn":
            img = row.get("中文图片", "")
            img_txt = row.get("中文图片文字", "")
            fn = row.get("中文正文文件", "")
            ln = row.get("中文行号", "")
            msg = f"  [中文 {p['kind']}] {p['message']}"
            if p.get("suggest_file") and p.get("suggest"):
                msg += f"（疑似移至 {p['suggest_file']}:{p['suggest']}）"
            print(msg)
            if p.get("expected") is not None and p.get("actual") is not None:
                print(f"    预期：{p['expected']}\n    实际：{p['actual']}")
            if img and img not in _DASHES:
                cn_reminders.append((vol, img, f"{p['kind']}（{fn}:{ln}｜图上「{img_txt}」）"))
        else:
            msg = f"  [日文 {p['kind']}] {p['message']}"
            if p.get("suggest_file") and p.get("suggest"):
                msg += f"（疑似移至 {p['suggest_file']}:{p['suggest']}）"
            print(msg)
    if args.limit and len(problems) > args.limit:
        print(f"  …… 其余 {len(problems) - args.limit} 条已省略（共 {len(problems)} 条）")

    if cn_reminders:
        print_illustration_reminder(cn_reminders)

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
