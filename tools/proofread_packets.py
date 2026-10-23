"""Frozen proofread inputs and bounded evidence packets (no semantic decisions)."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path

from epub_ids import book_id, header_of, work_id
from japanese_lookup import strip_rt_and_tags, to_ruby_markup
from proofread_review import to_text

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_BASE = REPO_ROOT / ".cache" / "epub-work" / "proofread-review"
MANIFEST_COLUMNS = ("item_id", "commit", "work", "file", "line", "old", "new",
                    "source_grade", "effective_grade", "parent_id")
GRADES = frozenset({"spec", "tiny", "local", "rewrite"})
SLICE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}\Z")


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _one_drive(path: Path) -> bool:
    if any(p.casefold() == "onedrive" or p.casefold().startswith("onedrive - ")
           for p in path.parts):
        return True
    return any(value and _inside(path, Path(value).resolve()) for value in
               (os.environ.get(name) for name in
                ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")))


def require_report_target(path: Path | str) -> Path:
    """Resolve an explicit report path; never permit book or distribution writes.

    The only repository-cache exception is a named proofread-review run. Report
    symlinks/junctions are rejected, including aliases to an otherwise safe path.
    Source/output overlap is additionally checked against explicit bases by prepare.
    """
    supplied = Path(path).absolute()
    resolved = supplied.resolve()
    for candidate in (supplied, resolved):
        cache = REPO_ROOT / ".cache"
        if _inside(candidate, cache) and not (
                _inside(candidate, REPORT_BASE) and candidate != REPORT_BASE):
            raise ValueError(f"报告禁止写入缓存书籍或缓存根目录：{path}")
        if _inside(candidate, REPO_ROOT / "EPUB") or _one_drive(candidate):
            raise ValueError(f"报告禁止写入 EPUB 或 OneDrive：{path}")
        if any(p.casefold() in {"epub", "japanese-text", "chinese-text"}
               for p in candidate.parts):
            raise ValueError(f"报告禁止写入书籍目录：{path}")
    for ancestor in (supplied, *supplied.parents):
        is_junction = getattr(ancestor, "is_junction", lambda: False)
        if ancestor.is_symlink() or is_junction():
            raise ValueError(f"报告路径不能经过符号链接或 junction：{ancestor}")
    if resolved in {REPO_ROOT, REPO_ROOT.parent, Path(resolved.anchor)}:
        raise ValueError(f"必须指定独立报告目录：{path}")
    for ancestor in (resolved, *resolved.parents):
        if (book_id(ancestor.name) or (ancestor / "META-INF" / "container.xml").is_file()
                or (ancestor / "item" / "xhtml").is_dir()):
            raise ValueError(f"报告目标位于书籍源目录：{path}")
    if ((resolved.is_dir() and any(resolved.glob("*.xhtml")))
            or (not resolved.is_dir() and any(resolved.parent.glob("*.xhtml")))):
        raise ValueError(f"报告目标是书籍源目录：{path}")
    if resolved.is_dir() and any(p.is_dir() and book_id(p.name) for p in resolved.iterdir()):
        raise ValueError(f"报告目标是书籍源目录：{path}")
    return resolved


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_tsv(path: Path, required: tuple[str, ...]) -> list[dict]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            fields = reader.fieldnames or []
            if len(fields) != len(set(fields)) or not set(required) <= set(fields):
                raise ValueError(f"TSV 列名缺失或重复：{path}")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"无法读取 TSV {path}：{exc}") from exc
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"TSV 数据列数不符：{path}")
    return rows


def _changes(root: Path) -> list[dict]:
    rows = _read_tsv(root / "changes.tsv",
                     ("commit", "work", "file", "line", "old", "new", "grade"))
    for index, row in enumerate(rows, 1):
        if row["grade"] not in GRADES:
            raise ValueError(f"changes.tsv 第 {index} 条 grade 无效：{row['grade']}")
    return rows


def load_manifest(report_root: Path | str) -> list[dict]:
    """Read the complete manifest and reconcile immutable fields with changes.tsv."""
    root = require_report_target(report_root)
    changes = _changes(root)
    manifest = _read_tsv(root / "manifest.tsv", MANIFEST_COLUMNS)
    if len(manifest) != len(changes):
        raise ValueError("manifest.tsv 与 changes.tsv 条目数不符；请建立新轮")
    for index, (item, change) in enumerate(zip(manifest, changes), 1):
        expected = {key: change[key] for key in MANIFEST_COLUMNS[1:7]}
        expected.update(item_id=f"C{index:06d}", source_grade=change["grade"])
        if any(item[key] != value for key, value in expected.items()):
            raise ValueError(f"manifest.tsv 与 changes.tsv 输入不符：C{index:06d}；请建立新轮")
        if item["effective_grade"] not in GRADES:
            raise ValueError(f"{item['item_id']} effective_grade 无效")
    return manifest


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_new_artifacts(outputs: dict[Path, bytes], apply: bool = False) -> None:
    """Create a set of report artifacts exclusively, rolling back our own files.

    Preflight is identical during preview. A same-directory hard link publishes
    each fully written temporary file without replacing a concurrent writer.
    """
    for path in outputs:
        require_report_target(path)
        if path.exists():
            raise ValueError(f"产物已存在，禁止覆盖：{path}")
        if not isinstance(outputs[path], bytes):
            raise ValueError(f"产物必须预先序列化为 bytes：{path}")
    if not apply:
        return
    created: list[tuple[Path, os.stat_result]] = []
    temporary: Path | None = None
    try:
        for path, data in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent,
                    prefix=".proofread-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
            os.link(temporary, path)
            created.append((path, path.stat()))
            temporary.unlink()
            temporary = None
    except BaseException:
        for path, original in reversed(created):
            if path.exists() and path.stat().st_ino == original.st_ino:
                path.unlink()
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def initialize_manifest(report_root: Path | str, *, apply: bool = False) -> dict:
    root = require_report_target(report_root)
    path = root / "manifest.tsv"
    changes = _changes(root)
    if path.exists():
        manifest = load_manifest(root)
        reused = True
    else:
        manifest = []
        for index, row in enumerate(changes, 1):
            item = {key: row[key] for key in MANIFEST_COLUMNS[1:7]}
            item.update(item_id=f"C{index:06d}", source_grade=row["grade"],
                        effective_grade=row["grade"], parent_id="")
            manifest.append(item)
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, MANIFEST_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(manifest)
        write_new_artifacts({path: stream.getvalue().encode("utf-8")}, apply)
        reused = False
    return {"run_id": root.name, "manifest": str(path), "applied": bool(apply and not reused),
            "reused": reused, "stats": {"total": len(manifest),
            "grades": dict(Counter(item["effective_grade"] for item in manifest))}}


def _read_json(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON {path}：{exc}") from exc
    if not isinstance(result, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return result


def _plan(root: Path, plan_path: Path | str | None, semantic_ids: list[str]) -> list[dict]:
    if plan_path is None:
        slices = [{"slice_id": path.stem, "item_ids": [line.strip() for line in
                   path.read_text(encoding="utf-8-sig").splitlines()
                   if line.strip() and not line.lstrip().startswith("#")]}
                  for path in sorted((root / "slices" / "ids").glob("*.txt"))]
    else:
        slices = _read_json(Path(plan_path)).get("slices")
    if not isinstance(slices, list):
        raise ValueError("计划须包含 slices 列表")
    seen_slices: set[str] = set()
    seen_ids: set[str] = set()
    for part in slices:
        if not isinstance(part, dict) or not isinstance(part.get("slice_id"), str):
            raise ValueError("切片缺少 slice_id")
        sid, ids = part["slice_id"], part.get("item_ids")
        if not SLICE_ID.fullmatch(sid) or sid.casefold() in seen_slices:
            raise ValueError(f"slice_id 无效或重复：{sid}")
        if not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids):
            raise ValueError(f"{sid} item_ids 必须是非空字符串列表")
        diff_lines = part.get("diff_lines")
        if diff_lines is not None and (
                not isinstance(diff_lines, int) or isinstance(diff_lines, bool) or diff_lines < 1):
            raise ValueError(f"{sid} diff_lines 必须是正整数实测值")
        duplicates = [item for item in ids if item in seen_ids]
        if len(ids) != len(set(ids)) or duplicates:
            raise ValueError(f"计划 ID 重复：{sid} {duplicates or ids}")
        seen_ids.update(ids)
        seen_slices.add(sid.casefold())
    expected = set(semantic_ids)
    if seen_ids != expected:
        raise ValueError(f"计划 ID 集合不符；漏项={sorted(expected - seen_ids)}；"
                         f"越界={sorted(seen_ids - expected)}")
    return slices


def _source_index(base: Path, headers: set[str]) -> dict[str, Path]:
    if not base.is_dir():
        raise ValueError(f"源目录不存在：{base}")
    result: dict[str, Path] = {}
    for path in sorted(base.rglob("*.xhtml")):
        header = header_of(path.name)
        if header not in headers:
            continue
        resolved = path.resolve()
        if not _inside(resolved, base):
            raise ValueError(f"源文件经过链接逃逸源目录：{path}")
        if header in result:
            raise ValueError(f"同侧重复表头 {header}：{result[header]} / {path}")
        result[header] = resolved
    return result


def _physical_lines(data: bytes) -> list[str]:
    text = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if not text:
        return []
    lines = text.split("\n")
    return lines[:-1] if lines[-1] == "" else lines


def _check_line_ruby(lines: list[str], path: Path) -> None:
    """Do not flatten multiline ruby and silently change the physical line basis."""
    for number, line in enumerate(lines, 1):
        for tag in ("ruby", "rt", "rp"):
            opens = len(re.findall(rf"<{tag}\b[^>]*>", line, re.I))
            closes = len(re.findall(rf"</{tag}\s*>", line, re.I))
            if opens != closes:
                raise ValueError(f"暂不支持跨物理行 {tag}：{path}:{number}；请提供保持行号的工作源")


def _evidence(source: dict, header: str, lines: list[str], number: int) -> dict:
    raw = lines[number - 1]
    return {"source_id": f"jp:{header}", "file": Path(source["path"]).name,
            "seq": header, "line": number, "raw": raw,
            "plain": strip_rt_and_tags(raw), "markup": to_ruby_markup(raw)}


def prepare_session(report_root: Path | str, *, jp_base: Path | str, cn_base: Path | str,
                    plan_path: Path | str | None = None, max_input_chars: int = 60000,
                    context: int = 1, apply: bool = False) -> dict:
    """Preflight every slice and freeze actual source hashes and minimal packets.

    Slice ownership is supplied by the Lead. Budgets never split semantic units.
    Optional per-slice diff_lines is the Lead's actual diff measurement; omitted
    values are explicitly estimates and remain a manual gate.
    """
    root = require_report_target(report_root)
    if context not in (0, 1) or isinstance(context, bool):
        raise ValueError("context 只支持 0 或 1")
    if not isinstance(max_input_chars, int) or isinstance(max_input_chars, bool) or max_input_chars < 1:
        raise ValueError("max_input_chars 必须是正整数")
    if (root / "session.json").exists():
        raise ValueError("session.json 已存在，禁止覆盖；输入变化请建立新轮")
    jp_root, cn_root = Path(jp_base).resolve(), Path(cn_base).resolve()
    for base in (jp_root, cn_root):
        if _inside(root, base) or _inside(base, root):
            raise ValueError(f"报告与只读源目录重叠：{root} / {base}")
    manifest = load_manifest(root)
    by_id = {item["item_id"]: item for item in manifest}
    semantic_ids = [item["item_id"] for item in manifest if item["effective_grade"] != "spec"]
    slices = _plan(root, plan_path, semantic_ids)
    changes = {f"C{i:06d}": item for i, item in enumerate(_changes(root), 1)}
    headers: set[str] = set()
    for item_id in semantic_ids:
        row = by_id[item_id]
        header = header_of(row["file"])
        if not header or work_id(row["file"]) != row["work"].upper():
            raise ValueError(f"{item_id} 文件表头与作品号不符：{row['file']} / {row['work']}")
        headers.add(header)
    indexes = {"jp": _source_index(jp_root, headers), "cn": _source_index(cn_root, headers)}
    sources: dict[str, dict] = {}
    source_lines: dict[str, list[str]] = {}
    packets: dict[Path, bytes] = {}
    frozen_slices = []
    warnings = []

    def lines_for(side: str, header: str) -> list[str]:
        source_id = f"{side}:{header}"
        if source_id not in source_lines:
            path = indexes[side].get(header)
            if path is None:
                raise ValueError(f"缺少 {side.upper()} 配对文件：{header}")
            try:
                data = path.read_bytes()
                lines = _physical_lines(data)
                _check_line_ruby(lines, path)
            except (OSError, UnicodeError) as exc:
                raise ValueError(f"无法读取源文件 {path}：{exc}") from exc
            sources[source_id] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
                                  "line_count": len(lines)}
            source_lines[source_id] = lines
        return source_lines[source_id]

    for part in slices:
        sid, ids = part["slice_id"], part["item_ids"]
        files = {by_id[item]["file"] for item in ids}
        diff_lines = part.get("diff_lines")
        if len(ids) > 150 or len(files) > 3 or (diff_lines is not None and diff_lines > 400):
            raise ValueError(f"{sid} 超出切片硬边界：{len(ids)} 条/{len(files)} 文件/"
                             f"{diff_lines if diff_lines is not None else '未实测'} diff 行")
        if diff_lines is None:
            warnings.append(f"{sid} 未提供 diff_lines 实测值，约 {len(ids) * 2} 行仅为估计；"
                            "Lead 仍须核对原始 diff 不超过 400 行")
        items = []
        for item_id in ids:
            row = by_id[item_id]
            header = header_of(row["file"])
            jp, cn = lines_for("jp", header), lines_for("cn", header)
            if len(jp) != len(cn):
                raise ValueError(f"配对行数不齐 {row['file']} / {Path(sources['jp:' + header]['path']).name}："
                                 f"CN={len(cn)} JP={len(jp)} 差值(CN-JP)={len(cn) - len(jp):+d}")
            try:
                line = int(row["line"])
            except ValueError as exc:
                raise ValueError(f"{item_id} 行号无效：{row['line']}") from exc
            if line < 1 or line > len(jp):
                raise ValueError(f"{item_id} 行号越界：{line} / {len(jp)}")
            if to_text(cn[line - 1]) != row["new"]:
                raise ValueError(f"{item_id} 新译与中文源实际行不符：{row['file']}:{line}；"
                                 "请提供匹配输入版本的 --cn-base；跨行增删须另行对齐")

            neighbors = []
            for number in range(max(1, line - context), min(len(jp), line + context) + 1):
                if number != line:
                    neighbors.append(dict(_evidence(sources[f"jp:{header}"], header, jp, number),
                                          cn=strip_rt_and_tags(cn[number - 1])))
            items.append({"item_id": item_id, "file": row["file"], "work": row["work"],
                          "seq": header, "line": line, "grade": row["effective_grade"],
                          "flags": [x for x in changes[item_id].get("flags", "").split(",") if x],
                          "old": row["old"], "new": row["new"],
                          "evidence": [_evidence(sources[f"jp:{header}"], header, jp, line)],
                          "context": neighbors})
        packet = {"schema_version": 1, "run_id": root.name, "slice_id": sid, "items": items}
        data = _json_bytes(packet)
        input_chars = len(data.decode("utf-8"))
        relative = f"slices/packets/{sid}.json"
        packets[root / relative] = data
        frozen_slices.append({"slice_id": sid, "item_ids": ids, "packet": relative,
                              "sha256": hashlib.sha256(data).hexdigest(), "input_chars": input_chars,
                              "file_count": len(files), "diff_lines": diff_lines,
                              "diff_lines_estimate": len(ids) * 2})
        if input_chars > max_input_chars:
            raise ValueError(f"{sid} 输入 {input_chars} 字符超过预算 {max_input_chars}；"
                             "请由 Lead 调整语义边界或说明依据后显式调整预算，不自动拆片")
    session = {"schema_version": 1, "run_id": root.name,
               "manifest_sha256": sha256_file(root / "manifest.tsv"),
               "changes_sha256": sha256_file(root / "changes.tsv"), "source_files": sources,
               "slices": frozen_slices,
               "spec_ids": [item["item_id"] for item in manifest if item["effective_grade"] == "spec"],
               "context": context, "max_input_chars": max_input_chars, "warnings": warnings,
               "diff_budget_verified": all(part.get("diff_lines") is not None for part in slices),
               "diff_lines_estimate": "每条按 2 行估计；不代替原始 diff 行数核查"}
    packets[root / "session.json"] = _json_bytes(session)
    packets[root / "session.sha256"] = (
        hashlib.sha256(packets[root / "session.json"]).hexdigest() + "\n").encode("ascii")
    write_new_artifacts(packets, apply)
    return dict(session, applied=apply, session_path=str(root / "session.json"))


def _packet_path(root: Path, part: dict) -> Path:
    sid = part.get("slice_id", "")
    if not isinstance(sid, str) or not SLICE_ID.fullmatch(sid):
        raise ValueError("冻结 session 的 slice_id 无效")
    if part.get("packet") != f"slices/packets/{sid}.json":
        raise ValueError(f"冻结 packet 路径无效：{sid}")
    path = require_report_target(root / part["packet"])
    if not _inside(path, root):
        raise ValueError("packet 路径逃逸报告目录")
    return path


def load_session(report_root: Path | str, *, verify_sources: bool = True) -> dict:
    root = require_report_target(report_root)
    try:
        digest = (root / "session.sha256").read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError("缺少有效 session.sha256 封存摘要；请建立新轮") from exc
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or sha256_file(root / "session.json") != digest:
        raise ValueError("冻结 session.json 已变化；请建立新轮")
    session = _read_json(root / "session.json")
    if session.get("schema_version") != 1 or session.get("run_id") != root.name:
        raise ValueError("session 版本或 run_id 无效")
    for filename, key in (("manifest.tsv", "manifest_sha256"), ("changes.tsv", "changes_sha256")):
        if sha256_file(root / filename) != session.get(key):
            raise ValueError(f"冻结 {filename} 已变化；请建立新轮")
    manifest = load_manifest(root)
    slices = session.get("slices")
    sources = session.get("source_files")
    if not isinstance(slices, list) or not isinstance(sources, dict):
        raise ValueError("session 的 slices/source_files 格式无效")
    seen = set()
    seen_ids: list[str] = []
    for part in slices:
        if not isinstance(part, dict):
            raise ValueError("冻结切片格式无效")
        path = _packet_path(root, part)
        if part["slice_id"].casefold() in seen:
            raise ValueError("冻结 slice_id 重复")
        seen.add(part["slice_id"].casefold())
        ids = part.get("item_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
            raise ValueError(f"冻结切片 item_ids 无效：{part['slice_id']}")
        seen_ids.extend(ids)
        if sha256_file(path) != part.get("sha256"):
            raise ValueError(f"冻结 packet 已变化：{path}；请建立新轮")
        packet = _read_json(path)
        if (packet.get("schema_version") != 1 or packet.get("run_id") != session["run_id"]
                or packet.get("slice_id") != part["slice_id"]
                or not isinstance(packet.get("items"), list)
                or not all(isinstance(item, dict) for item in packet["items"])
                or [item.get("item_id") for item in packet["items"]] != ids):
            raise ValueError(f"packet 标识或 ID 与冻结计划不符：{part['slice_id']}")
    expected = {item["item_id"] for item in manifest if item["effective_grade"] != "spec"}
    spec = [item["item_id"] for item in manifest if item["effective_grade"] == "spec"]
    if len(seen_ids) != len(set(seen_ids)) or set(seen_ids) != expected or session.get("spec_ids") != spec:
        raise ValueError("冻结计划的语义/规范 ID 归属漏项、重复或越界")
    if verify_sources:
        for source_id, source in sources.items():
            if (not isinstance(source_id, str) or not source_id.startswith(("jp:", "cn:"))
                    or not isinstance(source, dict) or not isinstance(source.get("path"), str)
                    or not isinstance(source.get("line_count"), int)):
                raise ValueError(f"冻结 source 格式无效：{source_id}")
            path = Path(source["path"])
            if not path.is_file() or sha256_file(path) != source.get("sha256"):
                raise ValueError(f"冻结源文件已变化或缺失：{source_id} {path}；请建立新轮")
    return session


def load_packet(report_root: Path | str, slice_id: str, *, verify_sources: bool = True) -> dict:
    root = require_report_target(report_root)
    session = load_session(root, verify_sources=verify_sources)
    part = next((part for part in session["slices"] if part["slice_id"] == slice_id), None)
    if part is None:
        raise ValueError(f"未知 slice_id：{slice_id}")
    packet = _read_json(_packet_path(root, part))
    if (packet.get("schema_version") != 1 or packet.get("run_id") != session["run_id"]
            or packet.get("slice_id") != slice_id or not isinstance(packet.get("items"), list)
            or not all(isinstance(item, dict) for item in packet["items"])
            or [item.get("item_id") for item in packet["items"]] != part.get("item_ids")):
        raise ValueError(f"packet 标识或 ID 与冻结计划不符：{slice_id}")
    return packet


def source_context(report_root: Path | str, slice_id: str, item_id: str, *, radius: int = 2) -> dict:
    """Read an item-specific larger window from the unchanged frozen source pair.

    The caller may save this as a new immutable supplement. It does not mutate
    the original packet or grant access to other items or arbitrary source lines.
    """
    if not isinstance(radius, int) or isinstance(radius, bool) or not 1 <= radius <= 10:
        raise ValueError("radius 必须是 1..10 的整数")
    packet = load_packet(report_root, slice_id)
    item = next((item for item in packet["items"] if item["item_id"] == item_id), None)
    if item is None:
        raise ValueError(f"请求 ID 不属于本片：{item_id}")
    session = load_session(report_root)
    header, line = item["seq"], item["line"]
    pair = {key: session["source_files"][key] for key in (f"jp:{header}", f"cn:{header}")}
    lines = {}
    for key, source in pair.items():
        data = Path(source["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError(f"冻结源文件读取时变化：{key}；请建立新轮")
        lines[key] = _physical_lines(data)
        if len(lines[key]) != source["line_count"]:
            raise ValueError(f"冻结源行数不符：{key}")
    jp, cn = lines[f"jp:{header}"], lines[f"cn:{header}"]
    neighbors = [dict(_evidence(pair[f"jp:{header}"], header, jp, number),
                      cn=strip_rt_and_tags(cn[number - 1]))
                 for number in range(max(1, line - radius), min(len(jp), line + radius) + 1)
                 if number != line]
    return {"schema_version": 1, "run_id": packet["run_id"], "slice_id": slice_id,
            "item_id": item_id, "radius": radius, "source_files": copy.deepcopy(pair),
            "evidence": [_evidence(pair[f"jp:{header}"], header, jp, line)],
            "context": neighbors}


def read_packet(report_root: Path | str, slice_id: str, *, item_ids: list[str] | None = None,
                flag: str | None = None, page: int = 1, page_size: int = 10,
                context: int = 1) -> dict:
    if context not in (0, 1) or isinstance(context, bool):
        raise ValueError("context 只支持 0 或 1")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 1
           for value in (page, page_size)):
        raise ValueError("page/page_size 必须是正整数")
    packet = load_packet(report_root, slice_id)
    items = packet["items"]
    if item_ids is not None:
        if not isinstance(item_ids, list) or not all(isinstance(x, str) for x in item_ids):
            raise ValueError("item_ids 必须是字符串列表")
        outside = set(item_ids) - {item["item_id"] for item in items}
        if outside:
            raise ValueError(f"请求 ID 不属于本片：{sorted(outside)}")
        selected = set(item_ids)
        items = [item for item in items if item["item_id"] in selected]
    if flag is not None:
        items = [item for item in items if flag in item["flags"]]
    total = len(items)
    items = copy.deepcopy(items[(page - 1) * page_size:page * page_size])
    if context == 0:
        for item in items:
            item["context"] = []
    return {"run_id": packet["run_id"], "slice_id": slice_id, "items": items,
            "total": total, "page": page, "page_size": page_size,
            "pages": (total + page_size - 1) // page_size}


def render_packet(data: dict) -> str:
    """Render a read_packet result without inferring or filling any decisions."""
    lines = [f"run_id={data['run_id']} slice_id={data['slice_id']} "
             f"page={data.get('page', 1)} total={data.get('total', len(data['items']))}"]
    for item in data["items"]:
        lines.extend(["", f"[{item['item_id']}] {item['file']}:{item['line']} "
                      f"grade={item['grade']} flags={','.join(item['flags'])}",
                      f"旧译: {item['old']}", f"新译: {item['new']}"])
        for evidence in item["evidence"]:
            lines.extend([f"日文 {evidence['file']}:{evidence['line']}",
                          f"底字: {evidence['plain']}", f"注音: {evidence['markup']}"])
        for neighbor in item["context"]:
            lines.extend([f"邻接 {neighbor['file']}:{neighbor['line']}",
                          f"JP: {neighbor['plain']}", f"ruby: {neighbor['markup']}",
                          f"CN: {neighbor['cn']}"])
    return "\n".join(lines) + "\n"
