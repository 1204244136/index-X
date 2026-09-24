#!/usr/bin/env python3
"""中日 XHTML 语义逐行对齐检验与漂移诊断工具。

本工具提供两级对齐诊断能力：
  1. Level 1（极速初筛，纯 CPU，零外部依赖）：
     基于结构锚点、字符集重合率与长度宽容度，数秒内扫描全库或指定卷，
     过滤掉完全对齐的绿区文件，输出候选问题清单。
  2. Level 2（矢量化精检，利用 BetweenLines 文本矢量化工具与 GPU 加速）：
     基于 sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)，
     计算中日文本行真实跨语言余弦相似度；利用局部位移滑动窗口算法，
     精准区分「意译/假名引起的假阳性」与「段落合并/拆分导致的真实结构性错位（Drift Window）」。

用法：
    # 1. 极速全库初筛（数秒完成）
    python tools/check_semantic_alignment.py --l1-only

    # 2. 单个表头矢量化深度诊断
    python tools/check_semantic_alignment.py S5_01_02-06 --vector

    # 3. 指定作品卷或系列进行深度诊断（合理切分流程，避免超长周期）
    python tools/check_semantic_alignment.py --work "S5_01_02" --vector
    python tools/check_semantic_alignment.py --work "S1_*" --top 10 --vector

    # 4. 自动全景排查：先跑 L1 找出可疑单元，再对前 N 个最严重单元跑 L2
    python tools/check_semantic_alignment.py --auto-audit --top 20
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

# 解决 Windows 控制台与管道 UTF-8 编码问题
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except OSError:
            pass

# 屏蔽 torchvision 冲突（若在 BetweenLines 环境中运行）
if "torchvision" not in sys.modules:
    try:
        import torchvision  # noqa: F401
    except Exception:
        sys.modules["torchvision"] = None

ROOT_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
CACHE_DEFAULT = ROOT_DIR / ".cache" / "epub-work"
BETWEENLINES_DIR = Path(r"C:\Users\12042\Documents\GitHub\BetweenLines")
BETWEENLINES_VENV_PYTHON = BETWEENLINES_DIR / ".venv" / "Scripts" / "python.exe"

try:
    from alignment_rules import (
        MANUAL_ALIGNMENT_HEADERS,
        NON_PAIR_WORK_IDS,
        PAIR_RULES,
        TEXTUAL_IMAGE_HEADERS,
        pairing_header_of,
    )
    from epub_ids import book_id, japanese_book_id
except ImportError:
    sys.path.insert(0, str(TOOLS_DIR))
    from alignment_rules import (
        MANUAL_ALIGNMENT_HEADERS,
        NON_PAIR_WORK_IDS,
        PAIR_RULES,
        TEXTUAL_IMAGE_HEADERS,
        pairing_header_of,
    )
    from epub_ids import book_id, japanese_book_id

TAG_RE = re.compile(r"<[^>]+>")
RT_RE = re.compile(r"<rt\b[^>]*>.*?</rt\s*>", re.S | re.I)
KANJI_CHAR_RE = re.compile(r"[\u4e00-\u9fff0-9A-Za-z]")

TEMPLATE_XML_RE = re.compile(r"^\s*<\?xml\b", re.I)
TEMPLATE_DOCTYPE_RE = re.compile(r"^\s*<!DOCTYPE\b", re.I)
TEMPLATE_HTML_RE = re.compile(r"<html\b", re.I)


@dataclass
class LineData:
    raw: str
    text: str
    char_set: set[str]
    length: int
    is_img: bool
    is_h1: bool
    is_h2: bool
    is_br: bool
    is_dialogue: bool
    is_template: bool


def parse_line(raw_line: str) -> LineData:
    stripped = raw_line.strip()
    lowered = stripped.lower()
    is_inline_glyph = "gaiji" in lowered or "height-2em" in lowered
    is_img = bool(re.search(r"<(?:img|svg)\b|data-image-continuation=", stripped, re.I)) and not is_inline_glyph
    is_h1 = bool(re.search(r"<h1\b", stripped, re.I))
    is_h2 = bool(re.search(r"<h2\b", stripped, re.I))
    is_br = bool(re.search(r"^\s*<br\s*/?>\s*$", stripped, re.I)) or stripped == ""
    is_template = bool(
        TEMPLATE_XML_RE.match(stripped)
        or TEMPLATE_DOCTYPE_RE.match(stripped)
        or TEMPLATE_HTML_RE.search(stripped)
    )
    visible_text = TAG_RE.sub("", RT_RE.sub("", stripped)).strip()
    kanji_and_digits = set(KANJI_CHAR_RE.findall(visible_text))
    is_dialogue = visible_text.startswith(("「", "“", '"', "『", "（", "("))

    return LineData(
        raw=stripped,
        text=visible_text,
        char_set=kanji_and_digits,
        length=len(visible_text),
        is_img=is_img,
        is_h1=is_h1,
        is_h2=is_h2,
        is_br=is_br,
        is_dialogue=is_dialogue,
        is_template=is_template,
    )


def compute_heuristic_sim(jp: LineData, cn: LineData) -> float:
    """Level 1 启发式相似度计算 [-1.0, 1.0]"""
    if jp.is_img and cn.is_img:
        return 1.0
    if jp.is_h1 and cn.is_h1:
        return 1.0
    if jp.is_h2 and cn.is_h2:
        return 1.0
    if jp.is_br and cn.is_br:
        return 1.0

    if any([
        jp.is_img != cn.is_img,
        jp.is_h1 != cn.is_h1,
        jp.is_h2 != cn.is_h2,
        jp.is_br != cn.is_br,
    ]):
        return -0.8

    if jp.is_template and cn.is_template:
        return 1.0
    if jp.length == 0 and cn.length == 0:
        return 1.0
    if jp.length == 0 or cn.length == 0:
        return -0.5
    if not jp.char_set and not cn.char_set:
        return 1.0

    dialogue_match = 0.2 if (jp.is_dialogue == cn.is_dialogue) else -0.15
    token_sim = 0.0
    if jp.char_set and cn.char_set:
        intersection = len(jp.char_set & cn.char_set)
        union = len(jp.char_set | cn.char_set)
        token_sim = intersection / union if union > 0 else 0.0

    diff = abs(cn.length - jp.length)
    len_penalty = 0.0 if diff <= max(8.0, 0.6 * jp.length) else -0.2
    ratio = cn.length / max(jp.length, 1)
    score = dialogue_match + (0.5 * token_sim) + (0.3 * (1.0 - min(abs(ratio - 0.8), 1.0))) + len_penalty
    return max(min(score, 1.0), -1.0)


@dataclass
class DriftWindow:
    start_line: int
    end_line: int
    offset: int  # +1 表示中文侧慢1行（日文第i行对应中文i+1），-1表示中文侧快1行
    avg_direct_sim: float
    avg_offset_sim: float
    description: str


@dataclass
class UnitSemanticResult:
    work_id: str
    header: str
    jp_path: Path
    cn_path: Path
    total_lines: int
    l1_drift_count: int
    l2_checked: bool = False
    semantic_match_count: int = 0
    real_drift_count: int = 0
    false_positives: int = 0
    drift_windows: list[DriftWindow] = field(default_factory=list)
    avg_similarity: float = 0.0
    health_score: float = 1.0
    execution_time_sec: float = 0.0


def index_by_header(paths: list[Path]) -> tuple[dict[str, Path], list[Path]]:
    by_header: dict[str, Path] = {}
    unmatched: list[Path] = []
    for p in paths:
        h = pairing_header_of(p.name)
        if h:
            by_header[h] = p
        else:
            unmatched.append(p)
    return by_header, unmatched


# ===========================================================================
# Level 2: SentenceTransformer 矢量化语义分析引擎
# ===========================================================================

_MODEL = None


def get_embedding_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    try:
        import torch
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None

    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        _MODEL = SentenceTransformer(
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            device=device,
            model_kwargs={"attn_implementation": "eager"},
        )
        return _MODEL
    except Exception as e:
        print(f"Warning: Failed to load SentenceTransformer: {e}", file=sys.stderr)
        return None


def run_vector_analysis(
    jp_lines: list[LineData],
    cn_lines: list[LineData],
    model,
    search_window: int = 5,
    min_match_sim: float = 0.50,
) -> tuple[float, int, int, int, list[DriftWindow], list[dict]]:
    """对单对文件进行正文段落序列级别的矢量化对齐分析。

    返回:
      (avg_similarity, match_count, real_drift_count, false_positive_count, drift_windows, line_details)
    """
    import numpy as np

    # 1. 提取有效正文段落序列（保留物理行号）
    jp_paras: list[tuple[int, LineData]] = []
    cn_paras: list[tuple[int, LineData]] = []

    for idx, line in enumerate(jp_lines):
        if not line.is_template and not line.is_img and not line.is_br and line.length > 0:
            jp_paras.append((idx, line))

    for idx, line in enumerate(cn_lines):
        if not line.is_template and not line.is_img and not line.is_br and line.length > 0:
            cn_paras.append((idx, line))

    total_lines = min(len(jp_lines), len(cn_lines))
    if not jp_paras or not cn_paras:
        return 1.0, total_lines, 0, 0, [], []

    # 2. 批量向量编码
    jp_texts = [p[1].text for p in jp_paras]
    cn_texts = [p[1].text for p in cn_paras]

    v_jp = model.encode(jp_texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    v_cn = model.encode(cn_texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)

    # 相似度矩阵 (len_jp, len_cn)
    sim_matrix = np.dot(v_jp, v_cn.T)

    # 建立物理行号 -> 段落索引的快速查找
    jp_line_to_para = {p[0]: i for i, p in enumerate(jp_paras)}
    cn_line_to_para = {p[0]: i for i, p in enumerate(cn_paras)}

    line_details = []
    direct_sims = []
    match_count = 0
    real_drift_count = 0
    false_positives = 0
    candidate_drifts = []

    for i in range(total_lines):
        jp = jp_lines[i]
        cn = cn_lines[i]

        # 结构锚点（模板、图片、纯空行）天然对齐
        if (jp.is_template and cn.is_template) or (jp.is_img and cn.is_img) or (jp.is_br and cn.is_br):
            sim = 1.0
            best_offset = 0
            best_sim = 1.0
            status = "ANCHOR_MATCH"
            match_count += 1
            direct_sims.append(sim)
            line_details.append({
                "line": i + 1, "direct_sim": 1.0, "best_offset": 0,
                "best_sim": 1.0, "status": status,
            })
            continue

        jp_p_idx = jp_line_to_para.get(i)
        cn_p_idx = cn_line_to_para.get(i)

        if jp_p_idx is None or cn_p_idx is None:
            # 单侧为空或非正文
            sim = 1.0 if jp.length == 0 and cn.length == 0 else 0.0
            best_offset = 0
            best_sim = sim
            status = "MATCH" if sim >= min_match_sim else "MISMATCH"
            if sim >= min_match_sim:
                match_count += 1
            else:
                real_drift_count += 1
            direct_sims.append(sim)
            line_details.append({
                "line": i + 1, "direct_sim": sim, "best_offset": 0,
                "best_sim": sim, "status": status,
            })
            continue

        # 两侧都是有效正文段落
        sim = float(sim_matrix[jp_p_idx, cn_p_idx])
        direct_sims.append(sim)

        # 在段落序列窗口 [jp_p_idx - search_window, jp_p_idx + search_window] 内搜索最优匹配
        best_p_offset = 0
        best_sim = sim
        for off in range(-search_window, search_window + 1):
            target_c_idx = jp_p_idx + off
            if 0 <= target_c_idx < len(cn_paras):
                val = float(sim_matrix[jp_p_idx, target_c_idx])
                if val > best_sim:
                    best_sim = val
                    best_p_offset = off

        if sim >= min_match_sim:
            status = "MATCH"
            match_count += 1
        else:
            # 物理行相同但相似度低于阈值
            if best_p_offset != 0 and best_sim >= 0.60 and best_sim >= (sim + 0.18):
                status = f"DRIFT_OFFSET_{best_p_offset:+d}"
                real_drift_count += 1
                # 记录段落错位对应的物理行号
                target_physical_line = cn_paras[jp_p_idx + best_p_offset][0] + 1
                candidate_drifts.append((i + 1, best_p_offset, sim, best_sim, target_physical_line))
            else:
                # 检查是否为正常意译/假名（消除假阳性）
                h_sim = compute_heuristic_sim(jp, cn)
                if sim >= 0.40 or h_sim >= 0.20:
                    status = "SEMANTIC_ACCEPT"
                    false_positives += 1
                    match_count += 1
                else:
                    status = "LOW_SIM"
                    real_drift_count += 1

        line_details.append({
            "line": i + 1,
            "direct_sim": round(sim, 4),
            "best_offset": best_p_offset,
            "best_sim": round(best_sim, 4),
            "status": status,
        })

    # 3. 聚合连续错位窗口 (Drift Windows)
    drift_windows = []
    if candidate_drifts:
        cur_start = candidate_drifts[0][0]
        cur_end = cur_start
        cur_off = candidate_drifts[0][1]
        cur_sims = [candidate_drifts[0][2]]
        cur_best_sims = [candidate_drifts[0][3]]

        for line_no, off, d_sim, b_sim, _ in candidate_drifts[1:]:
            if line_no <= cur_end + 3 and off == cur_off:
                cur_end = line_no
                cur_sims.append(d_sim)
                cur_best_sims.append(b_sim)
            else:
                if cur_end - cur_start + 1 >= 2:
                    drift_windows.append(DriftWindow(
                        start_line=cur_start,
                        end_line=cur_end,
                        offset=cur_off,
                        avg_direct_sim=round(float(np.mean(cur_sims)), 4),
                        avg_offset_sim=round(float(np.mean(cur_best_sims)), 4),
                        description=f"L{cur_start}~L{cur_end} ({cur_end - cur_start + 1}行): 中文正文{'落后' if cur_off > 0 else '超前'} {abs(cur_off)} 个段落",
                    ))
                cur_start = line_no
                cur_end = line_no
                cur_off = off
                cur_sims = [d_sim]
                cur_best_sims = [b_sim]

        if cur_end - cur_start + 1 >= 2:
            drift_windows.append(DriftWindow(
                start_line=cur_start,
                end_line=cur_end,
                offset=cur_off,
                avg_direct_sim=round(float(np.mean(cur_sims)), 4),
                avg_offset_sim=round(float(np.mean(cur_best_sims)), 4),
                description=f"L{cur_start}~L{cur_end} ({cur_end - cur_start + 1}行): 中文正文{'落后' if cur_off > 0 else '超前'} {abs(cur_off)} 个段落",
            ))

    avg_similarity = float(np.mean(direct_sims)) if direct_sims else 1.0
    return avg_similarity, match_count, real_drift_count, false_positives, drift_windows, line_details


# ===========================================================================
# 流程编排与批处理
# ===========================================================================

def collect_pairing_units(
    cache: Path, works: list[str] | None = None, include_exempt: bool = False
) -> list[tuple[str, str, Path, Path]]:
    cn_root = cache / "chinese-text"
    jp_root = cache / "japanese-text"
    if not cn_root.is_dir() or not jp_root.is_dir():
        raise FileNotFoundError(f"缓存目录不存在或未解包: {cache}")

    cn_books = {book_id(d.name): d for d in cn_root.iterdir() if d.is_dir()}
    jp_books = {book_id(d.name): d for d in jp_root.iterdir() if d.is_dir()}

    units = []
    for cn_id, cn_dir in sorted(cn_books.items()):
        if cn_id is None or cn_id in NON_PAIR_WORK_IDS:
            continue
        if works and not any(fnmatch.fnmatch(cn_id, pat) for pat in works):
            continue
        jp_dir = jp_books.get(japanese_book_id(cn_id))
        if jp_dir is None:
            continue
        cn_all = [p for p in cn_dir.rglob("*.xhtml") if p.name.lower() != "nav.xhtml"]
        jp_all = [p for p in jp_dir.rglob("*.xhtml") if p.name.lower() != "nav.xhtml"]
        cn_by, _ = index_by_header(cn_all)
        jp_by, _ = index_by_header(jp_all)
        for h in sorted(set(cn_by) & set(jp_by)):
            if h in MANUAL_ALIGNMENT_HEADERS:
                continue
            if not include_exempt and h in TEXTUAL_IMAGE_HEADERS:
                continue
            units.append((cn_id, h, jp_by[h], cn_by[h]))
    return units


def run_pipeline(
    cache: Path,
    works: list[str] | None = None,
    target_header: str | None = None,
    run_vector: bool = False,
    l1_only: bool = False,
    top_n: int | None = None,
    output_dir: Path | None = None,
    include_exempt: bool = False,
    strict: bool = False,
) -> int:
    start_time = time.time()
    if output_dir is None:
        output_dir = cache
    output_dir.mkdir(parents=True, exist_ok=True)

    units = collect_pairing_units(cache, works, include_exempt=include_exempt)
    if target_header:
        units = [u for u in units if u[1].upper() == target_header.upper()]

    if not units:
        print(f"未找到匹配的配对单元（works={works}, header={target_header}）")
        return 0

    print("=" * 95)
    print(f"中日语义逐行对齐检验引擎 | 配对单元: {len(units)} 个 | 模式: {'L1极速初筛' if l1_only else ('L2深度矢量化' if run_vector else 'L1+L2自适应')}")
    print("=" * 95)

    results: list[UnitSemanticResult] = []

    # 阶段 1: Level 1 启发式初筛
    print("\n>>> [阶段 1/2] 执行 Level 1 结构与启发式初筛...")
    for idx, (work_id, h, jp_p, cn_p) in enumerate(units, 1):
        jp_raw = jp_p.read_text(encoding="utf-8", errors="ignore").splitlines()
        cn_raw = cn_p.read_text(encoding="utf-8", errors="ignore").splitlines()
        jl = [parse_line(x) for x in jp_raw]
        cl = [parse_line(x) for x in cn_raw]

        tot = min(len(jl), len(cl))
        l1_drift = 0
        for i in range(tot):
            if compute_heuristic_sim(jl[i], cl[i]) < 0.15:
                l1_drift += 1

        res = UnitSemanticResult(
            work_id=work_id,
            header=h,
            jp_path=jp_p,
            cn_path=cn_p,
            total_lines=tot,
            l1_drift_count=l1_drift,
        )
        results.append(res)
        if idx % 100 == 0 or idx == len(units):
            print(f"  - 初筛进度: {idx}/{len(units)} ({idx/len(units)*100:.1f}%)")

    # 统计初筛结果
    drift_units = [r for r in results if r.l1_drift_count > 0]
    drift_units.sort(key=lambda x: x.l1_drift_count, reverse=True)

    print(f"\n初筛完成：共 {len(results)} 个单元，{len(results) - len(drift_units)} 个单元为 0 漂移绿区。")
    print(f"发现 {len(drift_units)} 个单元存在潜在漂移信号。")

    if l1_only or not (run_vector or top_n is not None):
        _write_summary_tsv(results, output_dir / "semantic-alignment-summary.tsv")
        print(f"\n报告已写入: {output_dir / 'semantic-alignment-summary.tsv'}")
        return

    # 阶段 2: Level 2 矢量化深度检验
    vector_targets = drift_units
    if top_n is not None:
        vector_targets = drift_units[:top_n]
    elif not run_vector:
        # 默认只对 L1 DRIFT >= 5 的疑似严重单元精检
        vector_targets = [r for r in drift_units if r.l1_drift_count >= 5]

    print(f"\n>>> [阶段 2/2] 载入 SentenceTransformer 对 {len(vector_targets)} 个高疑似单元执行语义矢量精检...")
    model = get_embedding_model()
    if model is None:
        print("错误: 无法载入 SentenceTransformer 矢量模型。请确认 PyTorch/SentenceTransformers 环境可用。")
        return

    all_windows: list[dict] = []

    for idx, r in enumerate(vector_targets, 1):
        t0 = time.time()
        jp_raw = r.jp_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        cn_raw = r.cn_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        jl = [parse_line(x) for x in jp_raw]
        cl = [parse_line(x) for x in cn_raw]

        avg_sim, matches, real_drifts, fps, windows, details = run_vector_analysis(jl, cl, model)
        r.l2_checked = True
        r.avg_similarity = avg_sim
        r.semantic_match_count = matches
        r.real_drift_count = real_drifts
        r.false_positives = fps
        r.drift_windows = windows
        r.health_score = matches / max(r.total_lines, 1)
        r.execution_time_sec = time.time() - t0

        print(f"  [{idx}/{len(vector_targets)}] {r.work_id} {r.header} | 行数: {r.total_lines} | L1漂移: {r.l1_drift_count} -> 真错位: {real_drifts} (假阳性消除: {fps}) | 语义均分: {avg_sim:.3f} | 错位窗口: {len(windows)} 个 ({r.execution_time_sec:.2f}s)")

        for w in windows:
            print(f"      * [错位区间] {w.description} (直连相似度: {w.avg_direct_sim:.2f} -> 偏移相似度: {w.avg_offset_sim:.2f})")
            all_windows.append({
                "work": r.work_id,
                "header": r.header,
                "start": w.start_line,
                "end": w.end_line,
                "offset": w.offset,
                "direct_sim": w.avg_direct_sim,
                "offset_sim": w.avg_offset_sim,
                "desc": w.description,
            })

    # 输出两份成果
    _write_summary_tsv(results, output_dir / "semantic-alignment-summary.tsv")
    _write_windows_tsv(all_windows, output_dir / "semantic-drift-windows.tsv")

    print("\n" + "=" * 95)
    print(f"检验完成！总耗时: {time.time() - start_time:.2f}s")
    print(f"全景健康度汇总: {output_dir / 'semantic-alignment-summary.tsv'}")
    print(f"真实结构错位窗口明细: {output_dir / 'semantic-drift-windows.tsv'}")
    print("=" * 95)

    if strict:
        if all_windows:
            print(f"\n[门禁阻断] 检测到 {len(all_windows)} 处真实结构错位窗口未消除，语义对齐门禁失败！", file=sys.stderr)
            return 1
        print("\n[门禁通过] 所有被测单元均为 0 错位窗口，语义逐行对齐检验通过！")
    return 0


def _write_summary_tsv(results: list[UnitSemanticResult], path: Path):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow([
            "书号", "表头", "总行数", "L1漂移数", "L2精检", "语义均分",
            "健康评分", "真实错位行数", "假阳性消除数", "错位窗口数", "耗时(秒)"
        ])
        for r in results:
            w.writerow([
                r.work_id,
                r.header,
                r.total_lines,
                r.l1_drift_count,
                "是" if r.l2_checked else "否",
                f"{r.avg_similarity:.4f}" if r.l2_checked else "",
                f"{r.health_score*100:.1f}%" if r.l2_checked else "",
                r.real_drift_count if r.l2_checked else "",
                r.false_positives if r.l2_checked else "",
                len(r.drift_windows) if r.l2_checked else "",
                f"{r.execution_time_sec:.2f}" if r.l2_checked else "",
            ])


def _write_windows_tsv(windows: list[dict], path: Path):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["书号", "表头", "起始行", "结束行", "偏移步长", "直连相似度", "偏移相似度", "问题描述"])
        for item in windows:
            w.writerow([
                item["work"], item["header"], item["start"], item["end"],
                item["offset"], item["direct_sim"], item["offset_sim"], item["desc"]
            ])


def ensure_vector_environment(args):
    """如果需要跑向量分析但当前环境无 torch/sentence_transformers，自动切换到 BetweenLines venv。"""
    needs_vector = (
        args.vector
        or args.auto_audit
        or args.strict
        or (not args.l1_only and args.top is not None)
    )
    if not needs_vector:
        return

    try:
        import torch  # noqa: F401
        import sentence_transformers  # noqa: F401
    except ImportError:
        if BETWEENLINES_VENV_PYTHON.is_file():
            print(f"[环境适配] 检测到当前 Python 缺少矢量化依赖，自动切换至 BetweenLines 矢量化环境:\n  {BETWEENLINES_VENV_PYTHON}")
            cmd = [str(BETWEENLINES_VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:]
            import subprocess
            res = subprocess.run(cmd)
            sys.exit(res.returncode)
        else:
            print("警告: 当前环境无 sentence_transformers 且未找到 BetweenLines 虚拟环境，回退为 L1 纯启发式模式。", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="中日 XHTML 语义逐行对齐检验与漂移诊断")
    parser.add_argument("target", nargs="?", help="指定单个表头（如 S5_01_02-06）")
    parser.add_argument("--work", action="append", help="作品筛选（如 S5_01_02、S1_*，可重复传入）")
    parser.add_argument("--l1-only", action="store_true", help="仅执行 L1 极速初筛")
    parser.add_argument("--vector", action="store_true", help="强制启用 L2 矢量化精检")
    parser.add_argument("--auto-audit", action="store_true", help="自动排查：初筛后自动精检 Top 疑点单元")
    parser.add_argument("--top", type=int, default=None, help="仅对前 N 个最严重疑点单元执行 L2 精检")
    parser.add_argument("--strict", action="store_true", help="门禁模式：若发现任何结构错位窗口则返回非零退出码阻断")
    parser.add_argument("--include-exempt", action="store_true", help="包含文本化图片等已确认豁免的页面（默认跳过）")
    parser.add_argument("--cache", type=Path, default=CACHE_DEFAULT, help="缓存目录")
    parser.add_argument("--out", type=Path, default=None, help="报告输出目录")
    args = parser.parse_args()

    if args.strict and not (args.vector or args.l1_only or args.auto_audit or args.top is not None or args.target or args.work):
        args.auto_audit = True

    ensure_vector_environment(args)

    code = run_pipeline(
        cache=args.cache,
        works=args.work,
        target_header=args.target,
        run_vector=args.vector,
        l1_only=args.l1_only,
        top_n=args.top or (20 if args.auto_audit else None),
        output_dir=args.out,
        include_exempt=args.include_exempt,
        strict=args.strict,
    )
    if args.strict and code != 0:
        sys.exit(code)


if __name__ == "__main__":
    main()
