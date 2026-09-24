#!/usr/bin/env python3
"""深入查看具体文件在指定行号区间的原始中日对照与相似度。"""
import sys
from pathlib import Path
import re

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except OSError:
            pass

from check_semantic_alignment import parse_line, get_embedding_model
import numpy as np

def inspect(header: str, start_l: int, end_l: int):
    cache = Path(r".cache\epub-work")
    jp_files = list(cache.glob(f"japanese-text/*/*/*/{header}*.xhtml"))
    cn_files = list(cache.glob(f"chinese-text/*/*/*/{header}*.xhtml"))
    if not jp_files or not cn_files:
        print(f"未找到文件: {header}")
        return

    jp_p = jp_files[0]
    cn_p = cn_files[0]
    print(f"JP: {jp_p}")
    print(f"CN: {cn_p}")

    jp_lines = [parse_line(x) for x in jp_p.read_text(encoding="utf-8").splitlines()]
    cn_lines = [parse_line(x) for x in cn_p.read_text(encoding="utf-8").splitlines()]

    model = get_embedding_model()

    print(f"\n{'行号':<5} | {'直接Sim':<8} | {'JP原文':<35} | {'CN译文':<35}")
    print("-" * 95)
    for i in range(start_l - 1, min(end_l, len(jp_lines), len(cn_lines))):
        jl = jp_lines[i]
        cl = cn_lines[i]
        if jl.length == 0 and cl.length == 0:
            sim = 1.0
        elif jl.is_template or jl.is_img or jl.is_br:
            sim = 1.0
        else:
            v_j = model.encode([jl.text], normalize_embeddings=True, show_progress_bar=False)[0]
            v_c = model.encode([cl.text], normalize_embeddings=True, show_progress_bar=False)[0]
            sim = float(np.dot(v_j, v_c))

        flag = "  " if sim >= 0.50 else "!!"
        print(f"L{i+1:04d} {flag} | {sim:8.4f} | {jl.text[:35]:<35} | {cl.text[:35]:<35}")

if __name__ == "__main__":
    header = sys.argv[1] if len(sys.argv) > 1 else "S5_01_02-07"
    start_l = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    end_l = int(sys.argv[3]) if len(sys.argv) > 3 else 25
    inspect(header, start_l, end_l)
