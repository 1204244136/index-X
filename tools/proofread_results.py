"""Assemble and mechanically validate frozen proofread-review reports.

Passing these checks establishes coverage and verifiable quotations. It does
not establish that a translation decision is correct; that remains Lead work.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from proofread_packets import (
    _physical_lines, load_packet, load_session, require_report_target, sha256_file, write_new_artifacts,
)
from japanese_lookup import strip_rt_and_tags, to_ruby_markup


DECISIONS = ("保留新译", "确认误改", "待人工", "未覆盖")
CATEGORIES = (
    "否定与逻辑方向", "数字与单位", "主体与动作时序", "关键漏译与专名", "其他重大语义问题",
)
TOP_FIELDS = {"run_id", "slice_id", "attempt", "items", "discoveries"}
ITEM_ORDER = ("item_id", "decision", "jp_location", "jp_quote", "reason", "proposed_cn", "original_fix")
ITEM_FIELDS = set(ITEM_ORDER)
FIX_FIELDS = {"category", "old_error", "new_fix", "impact"}
DISCOVERY_FIELDS = {"location", "issue", "needed_context"}
DRAFT_FIELDS = ITEM_FIELDS - {"jp_location", "jp_quote"}


def _read_json(path: Path | str):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"重复 JSON 字段：{key}")
            result[key] = value
        return result

    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                          object_pairs_hook=unique_object)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"无法读取 JSON {path}：{exc}") from exc


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(kind: str, message: str, item_id: str | None = None) -> dict:
    return {"kind": kind, "item_id": item_id, "message": message}


def _plain(value: str) -> str:
    """Use the repository's base-text ruby track, preserving internal spacing."""
    return _space(strip_rt_and_tags(value))


def _space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _context_rows(root: Path, session: dict, item: dict) -> list[dict]:
    """Read sealed supplements belonging to this item, without changing ownership."""
    folder = root / "slices" / "context" / session["active_slice"]
    rows = []
    for path in sorted(folder.glob(f"{item['item_id']}.c*.json")):
        require_report_target(path)
        if not re.fullmatch(re.escape(item["item_id"]) + r"\.c[1-9][0-9]*\.json", path.name):
            raise ValueError(f"上下文补包文件名无效：{path.name}")
        seal = path.with_suffix(".sha256")
        require_report_target(seal)
        if seal.read_text(encoding="ascii").strip() != sha256_file(path):
            raise ValueError(f"冻结上下文补包已变化：{path.name}")
        extra = _read_json(path)
        if (not isinstance(extra, dict) or extra.get("schema_version") != 1
                or extra.get("run_id") != session["run_id"]
                or extra.get("slice_id") != session["active_slice"]
                or extra.get("item_id") != item["item_id"]
                or type(extra.get("radius")) is not int or not 1 <= extra["radius"] <= 10):
            raise ValueError(f"冻结上下文补包标识或半径无效：{path.name}")
        expected_sources = {f"{side}:{item['seq']}" for side in ("jp", "cn")}
        sources = extra.get("source_files")
        if (not isinstance(sources, dict) or set(sources) != expected_sources
                or any(source != session["source_files"].get(key)
                       for key, source in sources.items())):
            raise ValueError(f"上下文补包来源不属于本条冻结源：{path.name}")
        evidence, neighbors = extra.get("evidence"), extra.get("context")
        if (not isinstance(evidence, list) or len(evidence) != 1
                or not isinstance(evidence[0], dict) or evidence[0].get("line") != item["line"]
                or not isinstance(neighbors, list)):
            raise ValueError(f"上下文补包行结构无效：{path.name}")
        for row in evidence + neighbors:
            if (not isinstance(row, dict) or type(row.get("line")) is not int
                    or abs(row["line"] - item["line"]) > extra["radius"]
                    or row.get("source_id") != f"jp:{item['seq']}"):
                raise ValueError(f"上下文补包位置越出本条边界：{path.name}")
        rows.extend(evidence + neighbors)
    return rows


def _source_rows(root: Path, session: dict, item: dict, cache: dict) -> list[dict]:
    rows = []
    supplied = item.get("evidence", []) + item.get("context", []) + _context_rows(root, session, item)
    for row in supplied:
        source_id = row["source_id"]
        source = session["source_files"][source_id]
        if (source_id != f"jp:{item['seq']}" or row.get("seq") != item["seq"]
                or row.get("file") != Path(source["path"]).name):
            raise ValueError("冻结证据文件、内容序或来源标识不匹配")
        if source_id not in cache:
            cache[source_id] = _physical_lines(Path(source["path"]).read_bytes())
        lines = cache[source_id]
        number = row["line"]
        if type(number) is not int or not 1 <= number <= len(lines):
            raise ValueError(f"冻结证据行号不在源文件范围内：{row.get('file')}:{number}")
        actual = lines[number - 1]
        if (row.get("raw") != actual or row.get("plain") != strip_rt_and_tags(actual)
                or row.get("markup") != to_ruby_markup(actual)):
            raise ValueError(f"冻结证据文本与实际源不符：{row['file']}:{number}")
        if "cn" in row:
            cn_source = f"cn:{item['seq']}"
            if cn_source not in cache:
                cache[cn_source] = _physical_lines(
                    Path(session["source_files"][cn_source]["path"]).read_bytes())
            if (number > len(cache[cn_source])
                    or row["cn"] != strip_rt_and_tags(cache[cn_source][number - 1])):
                raise ValueError(f"冻结中文上下文与实际源不符：{item['file']}:{number}")
        rows.append(row)
    return rows


def _location_matches(reference: str, row: dict) -> bool:
    match = re.fullmatch(r"(.+):L?([1-9][0-9]*)", reference.strip())
    if not match or int(match.group(2)) != row["line"]:
        return False
    name = match.group(1).replace("\\", "/")
    filename = row["file"]
    seq = row.get("seq", "")
    aliases = {filename, Path(filename).stem}
    if seq:
        aliases.update({seq, f"{filename}/{seq}", f"{Path(filename).stem}/{seq}"})
    return name in aliases


def _quote_matches(quote: str, raw: str) -> bool:
    # A quotation containing readings must verify those readings as well. Never
    # strip a forged <rt> or |base[reading] and accept only the remaining base.
    ruby_track = bool(re.search(r"</?(?:ruby|rt|rp)\b|\|[^\n]*\[", quote, re.I))
    if ruby_track:
        normalized, actual = _space(to_ruby_markup(quote)), _space(to_ruby_markup(raw))
    else:
        normalized, actual = _plain(quote), _plain(raw)
    if normalized:
        return normalized in actual
    # An actual empty/structural line may be cited literally, never invented.
    return bool(quote.strip()) and _space(quote) == _space(raw)


def _check_evidence(root: Path, session: dict, item: dict, report: dict, cache: dict) -> list[dict]:
    item_id = item["item_id"]
    location, quote = report.get("jp_location"), report.get("jp_quote")
    if not _nonempty(location) or not _nonempty(quote):
        return [_issue("evidence", "须提供实际日文位置及原句；未覆盖可同时为 null", item_id)]
    locations = [part.strip() for part in re.split(r"[;；]", location) if part.strip()]
    try:
        quotations = [part.strip() for part in _physical_lines(quote.encode("utf-8")) if part.strip()]
    except UnicodeError:
        return [_issue("evidence", "原句含无法编码为 UTF-8 的字符", item_id)]
    if len(locations) != len(quotations) or not locations:
        return [_issue("evidence", "日文位置与引句须逐行一一对应，位置用分号、原句用换行分隔", item_id)]
    try:
        rows = _source_rows(root, session, item, cache)
    except (KeyError, OSError, UnicodeError, ValueError) as exc:
        return [_issue("input", f"冻结证据无法读取：{exc}", item_id)]
    matches = [[row for row in rows if _location_matches(loc, row)] for loc in locations]
    issues = []
    for loc, quotation, matched in zip(locations, quotations, matches):
        if not matched:
            issues.append(_issue("evidence", f"引用不属于本条冻结窗口，或位置格式无效：{loc}", item_id))
        elif not any(_quote_matches(quotation, row["raw"]) for row in matched):
            issues.append(_issue("evidence", f"原句与指定日文实际内容不符：{loc}", item_id))
    return issues


def _quotes_frozen_fragment(description: str, frozen: str) -> bool:
    frozen = _plain(frozen)
    if not frozen:
        return any(token in description for token in ("空", "缺", "漏", "无", "删除", "新增"))
    description_plain = _plain(description)
    if frozen in description_plain:
        return True
    # Accept a necessary short fragment, not a requirement to repeat a long line.
    fragments = re.findall(r"[「『“\"`‘]([^」』”\"`’]+)[」』”\"`’]", description)
    return any(len(_plain(fragment)) >= min(2, len(frozen)) and _plain(fragment) in frozen
               for fragment in fragments)


def _check_original_fix(item: dict, report: dict, manifest: dict) -> list[dict]:
    fix = report.get("original_fix")
    if fix is None:
        return []
    item_id = item["item_id"]
    issues = []
    initial = manifest.get(item_id, {})
    if (not re.fullmatch(r"C[0-9]{6}", item_id) or item_id not in manifest
            or report.get("decision") != DECISIONS[0]
            or initial.get("parent_id", "").strip()):
        issues.append(_issue("input", "original_fix 仅属于无 parent_id 的初始 C 保留项", item_id))
    if not isinstance(fix, dict) or set(fix) != FIX_FIELDS:
        return issues + [_issue("structure", "original_fix 必须固定为 category/old_error/new_fix/impact", item_id)]
    if not all(_nonempty(value) for value in fix.values()) or fix["category"] not in CATEGORIES:
        issues.append(_issue("structure", "original_fix 四字段须非空，category 须为规定类型", item_id))
    for key, frozen_key in (("old_error", "old"), ("new_fix", "new")):
        if _nonempty(fix[key]) and not _quotes_frozen_fragment(fix[key], item[frozen_key]):
            issues.append(_issue("evidence", f"{key} 须引用冻结 {frozen_key} 的必要片段", item_id))
    return issues


def _manifest_rows(root: Path) -> dict:
    with (root / "manifest.tsv").open(encoding="utf-8-sig", newline="") as stream:
        return {row["item_id"]: row for row in csv.DictReader(stream, delimiter="\t")}


def _validate_loaded(root: Path, data, session: dict, packet: dict) -> list[dict]:
    issues = []
    if not isinstance(data, dict):
        return [_issue("structure", "报告顶层必须为 JSON 对象")]
    if set(data) != TOP_FIELDS:
        issues.append(_issue("structure", "报告顶层字段须恰为 run_id/slice_id/attempt/items/discoveries"))
    for key, expected in (("run_id", session["run_id"]), ("slice_id", packet["slice_id"])):
        if type(data.get(key)) is not str or data[key] != expected:
            issues.append(_issue("input", f"{key} 与冻结输入不一致"))
    if type(data.get("attempt")) is not int or data["attempt"] not in (1, 2):
        issues.append(_issue("structure", "attempt 必须为整数 1 或 2"))
    assigned = packet["items"]
    items = data.get("items")
    if not isinstance(items, list):
        issues.append(_issue("structure", "items 必须为列表"))
        items = []
    ids = [item.get("item_id") if isinstance(item, dict) else None for item in items]
    if ids != [item["item_id"] for item in assigned]:
        issues.append(_issue("structure", "items 须按分配 ID 顺序返回且无遗漏、重复、越界"))
    by_id = {item["item_id"]: item for item in assigned}
    source_cache = {}
    session = dict(session, active_slice=packet["slice_id"])
    try:
        manifest = _manifest_rows(root)
    except (OSError, UnicodeError, KeyError, csv.Error) as exc:
        return issues + [_issue("input", f"冻结清单无法读取：{exc}")]
    for report in items:
        if not isinstance(report, dict):
            issues.append(_issue("structure", "每个条目必须为对象"))
            continue
        item_id = report.get("item_id")
        label = item_id if isinstance(item_id, str) else None
        if set(report) != ITEM_FIELDS:
            issues.append(_issue("structure", "条目须恰有契约七字段", label))
        if not isinstance(item_id, str) or item_id not in by_id:
            continue
        decision = report.get("decision")
        if not isinstance(decision, str) or decision not in DECISIONS:
            issues.append(_issue("structure", "decision 须为规定四种判定", item_id))
        if not _nonempty(report.get("reason")):
            issues.append(_issue("evidence", "须填写逐条判定理由，不自动补判定或通用理由", item_id))
        if decision == DECISIONS[1]:
            if not _nonempty(report.get("proposed_cn")):
                issues.append(_issue("structure", "确认误改须有非空最小中文修正", item_id))
        elif report.get("proposed_cn") is not None:
            issues.append(_issue("structure", "非确认误改的 proposed_cn 必须为 null", item_id))
        if decision == DECISIONS[3] and report.get("jp_location") is None and report.get("jp_quote") is None:
            pass
        else:
            issues.extend(_check_evidence(root, session, by_id[item_id], report, source_cache))
        if (decision == DECISIONS[2] and _nonempty(report.get("reason"))
                and not re.search(r"缺|不足|无法|未|待|需|不明|不清|不确定", report["reason"])):
            issues.append(_issue("evidence", "待人工的理由须说明仍缺的事实或依赖", item_id))
        issues.extend(_check_original_fix(by_id[item_id], report, manifest))
    discoveries = data.get("discoveries")
    if not isinstance(discoveries, list):
        issues.append(_issue("structure", "discoveries 必须为列表"))
    else:
        for discovery in discoveries:
            if (not isinstance(discovery, dict) or set(discovery) != DISCOVERY_FIELDS
                    or not all(_nonempty(value) for value in discovery.values())):
                issues.append(_issue("structure", "discovery 须为 location/issue/needed_context 三个非空字符串"))
    return issues


def validate_data(report_root: Path | str, data) -> list[dict]:
    """Validate an in-memory report without creating any report file."""
    root = Path(report_root)
    try:
        session = load_session(root)
        if not isinstance(data, dict) or not isinstance(data.get("slice_id"), str):
            return [_issue("structure", "报告须包含字符串 slice_id")]
        packet = load_packet(root, data["slice_id"])
        return _validate_loaded(root, data, session, packet)
    except (OSError, UnicodeError, ValueError, KeyError) as exc:
        return [_issue("input", str(exc))]


def validate_result(report_root: Path | str, result_path: Path | str) -> list[dict]:
    """Return structured issues; an empty list is only mechanical acceptance."""
    try:
        data = _read_json(result_path)
    except ValueError as exc:
        return [_issue("input" if isinstance(exc.__cause__, OSError) else "structure", str(exc))]
    issues = validate_data(report_root, data)
    if issues or not isinstance(data, dict):
        return issues
    try:
        root = require_report_target(report_root)
        path = require_report_target(result_path)
        match = re.fullmatch(re.escape(data["slice_id"]) + r"\.a([12])(?:\.r([1-9][0-9]*))?\.json",
                             path.name)
        if path.parent != root / "slices" or not match:
            return [_issue("input", "正式结果路径须为本轮 slices/<slice>.a<attempt>[.rN].json")]
        if int(match.group(1)) != data["attempt"]:
            return [_issue("input", "结果 attempt 与所选文件名不一致")]
        _check_revision(root, data, int(match.group(2) or 0))
    except (OSError, UnicodeError, ValueError, KeyError) as exc:
        issues.append(_issue("evidence", str(exc)))
    return issues


def _raise_issues(issues: list[dict]) -> None:
    if issues:
        raise ValueError("；".join(f"{issue['item_id'] or 'report'} [{issue['kind']}] {issue['message']}"
                                  for issue in issues))


def _semantic_record(data: dict) -> dict:
    """Conservatively compare recorded facts when repairing only JSON structure."""
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("无法证明旧报告的语义记录，不能作为格式修订基准")
    records = {}
    required = ITEM_FIELDS - {"proposed_cn", "original_fix"}
    for item in data["items"]:
        if (not isinstance(item, dict) or not required <= set(item)
                or not isinstance(item["item_id"], str) or item["item_id"] in records):
            raise ValueError("旧报告缺少明确语义字段或 ID 重复，不能自动视为格式修订")
        records[item["item_id"]] = {key: item.get(key) for key in ITEM_FIELDS}
    if not isinstance(data.get("discoveries"), list):
        raise ValueError("旧报告缺少 discoveries 记录，不能自动视为格式修订")
    return {"items": records, "discoveries": data["discoveries"]}


def _check_revision(root: Path, result: dict, revision: int) -> None:
    if not revision:
        return
    semantic = _semantic_record(result)
    for number in range(revision - 1, -1, -1):
        suffix = f".r{number}" if number else ""
        previous = require_report_target(root / "slices" / (
            f"{result['slice_id']}.a{result['attempt']}{suffix}.json"))
        if not previous.is_file():
            raise ValueError(f"格式修订须保留确定的前一产物：{previous}")
        old = _read_json(previous)
        for key in ("run_id", "slice_id", "attempt"):
            if isinstance(old, dict) and key in old and old[key] != result[key]:
                raise ValueError(f"格式修订不能改变 {key}，输入变化须建立新轮")
        if _semantic_record(old) != semantic:
            raise ValueError("格式修订不能改变判定、理由、引用、修正或发现；取证/判定问题须重发切片")


def assemble_result(report_root: Path | str, slice_id: str, decisions_path: Path | str, *,
                    attempt: int = 1, revision: int = 0, apply: bool = False) -> dict:
    """Package explicit model decisions, optionally attaching frozen quotations.

    Adding a real quotation is serialization assistance, never a claim that the
    model read it. Supplied evidence is preserved and checked rather than fixed.
    """
    root = require_report_target(report_root)
    session = load_session(root)
    packet = load_packet(root, slice_id)
    if type(attempt) is not int or attempt not in (1, 2):
        raise ValueError("attempt 必须为整数 1 或 2")
    if type(revision) is not int or revision < 0:
        raise ValueError("revision 必须为非负整数")
    decisions = _read_json(decisions_path)
    if not isinstance(decisions, dict) or set(decisions) != {"items", "discoveries"}:
        raise ValueError("判定输入须固定为 items/discoveries")
    if not isinstance(decisions["items"], list):
        raise ValueError("items 必须为列表")
    supplied = decisions["items"]
    if [item.get("item_id") if isinstance(item, dict) else None for item in supplied] != [
            item["item_id"] for item in packet["items"]]:
        raise ValueError("判定输入须按分配 ID 顺序完整填写，无重复或越界")
    items = []
    for choice, item in zip(supplied, packet["items"]):
        if set(choice) - ITEM_FIELDS or not DRAFT_FIELDS <= set(choice):
            raise ValueError(f"{item['item_id']} 须显式填写 item_id/decision/reason/proposed_cn/original_fix，且不含未定义字段")
        if ("jp_location" in choice) != ("jp_quote" in choice):
            raise ValueError(f"{item['item_id']} jp_location/jp_quote 须成对提供或同时省略")
        report = {key: choice.get(key) for key in ITEM_ORDER}
        if "jp_location" not in choice and "jp_quote" not in choice and choice["decision"] != DECISIONS[3]:
            evidence = item.get("evidence", [])
            if evidence:
                report["jp_location"] = ";".join(f"{row['file']}:{row['line']}" for row in evidence)
                report["jp_quote"] = "\n".join(row["raw"] for row in evidence)
        items.append(report)
    result = {"run_id": session["run_id"], "slice_id": slice_id, "attempt": attempt,
              "items": items, "discoveries": decisions["discoveries"]}
    _raise_issues(_validate_loaded(root, result, session, packet))
    _check_revision(root, result, revision)
    suffix = f".r{revision}" if revision else ""
    target = require_report_target(root / "slices" / f"{slice_id}.a{attempt}{suffix}.json")
    if target.exists():
        raise ValueError(f"拒绝覆盖已有结果：{target}")
    write_new_artifacts({target: (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")},
                        apply=apply)
    return result


def coverage_summary(report_root: Path | str, selection_path: Path | str) -> dict:
    """Count only explicitly selected mechanically valid results in plan order."""
    root = require_report_target(report_root)
    session = load_session(root)
    selection = _read_json(selection_path)
    if not isinstance(selection, dict):
        raise ValueError("有效结果选择须为 slice_id 到结果相对路径的对象")
    planned = session["slices"]
    planned_ids = {entry["slice_id"] for entry in planned}
    if set(selection) - planned_ids:
        raise ValueError("有效结果选择包含计划外 slice_id")
    counts = dict.fromkeys(("T", "S", "M", "K", "R", "H", "U"), 0)
    counts["S"] = len(session["spec_ids"])
    slices, unresolved, original_fixes = [], [], []
    for entry in planned:
        sid = entry["slice_id"]
        issues, data = [], None
        selected = selection.get(sid)
        if not _nonempty(selected):
            issues = [_issue("input", "未显式选择本片有效结果")]
        else:
            relative = Path(selected)
            candidate = (root / relative).resolve()
            if relative.is_absolute() or not candidate.is_relative_to(root):
                raise ValueError(f"选择的结果路径越出 report-root：{selected}")
            require_report_target(root / relative)
            if (relative.parent.as_posix() != "slices" or not re.fullmatch(
                    re.escape(sid) + r"\.a[12](?:\.r[1-9][0-9]*)?\.json", relative.name)):
                raise ValueError(f"所选路径须为本片正式结果或格式修订：{selected}")
            try:
                data = _read_json(candidate)
                if not isinstance(data, dict) or data.get("slice_id") != sid:
                    issues = [_issue("input", "所选结果不属于该切片")]
                else:
                    issues = validate_result(root, candidate)
            except (OSError, UnicodeError, ValueError, KeyError) as exc:
                issues = [_issue("input", str(exc))]
        per_slice = dict.fromkeys(("K", "R", "H", "U"), 0)
        if issues:
            per_slice["U"] = len(entry["item_ids"])
            unresolved.extend({"item_id": item_id, "slice_id": sid, "decision": DECISIONS[3],
                               "reason": "切片无有效结果", "issues": issues}
                              for item_id in entry["item_ids"])
        else:
            for item in data["items"]:
                key = ("K", "R", "H", "U")[DECISIONS.index(item["decision"])]
                per_slice[key] += 1
                if key in ("H", "U"):
                    unresolved.append({"item_id": item["item_id"], "slice_id": sid,
                                       "decision": item["decision"], "reason": item["reason"]})
                if item["original_fix"] is not None:
                    original_fixes.append({"item_id": item["item_id"], "slice_id": sid,
                                           **item["original_fix"]})
        for key, value in per_slice.items():
            counts[key] += value
        counts["M"] += len(entry["item_ids"])
        slices.append({"slice_id": sid, "assigned": len(entry["item_ids"]), "counts": per_slice,
                       "result": selected, "valid": not issues, "issues": issues})
    counts["T"] = counts["S"] + counts["M"]
    complete = not unresolved and all(part["valid"] for part in slices)
    return {"run_id": session["run_id"], "counts": counts, "slices": slices,
            "unresolved": unresolved, "original_fixes": original_fixes,
            "original_fix_count": len(original_fixes), "coverage_complete": complete,
            "ready_for_lead_acceptance": complete, "semantic_acceptance": "requires_lead_review"}
