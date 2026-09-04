#!/usr/bin/env python3
"""Reviewed project-level exceptions shared by alignment-related tools."""
from __future__ import annotations

import re

from epub_ids import NUMBERED_BOOK, S6_DATE, header_of


NON_PAIR_WORK_IDS = frozenset({"S6_24.12.10"})
MANUAL_ALIGNMENT_HEADERS = frozenset({"S1_25-STIYL_MAGNUS"})
JP_WRAPPER_RE = re.compile(
    rf"^(p-|navigation-documents|Anotherworld|(?:{S6_DATE}|{NUMBERED_BOOK})-(?:p-|navigation))",
    re.I,
)
# 已确认的文本化图片例外（AGENTS.md「图片行」条目）：中文侧把 BW 整页图片
# （新约 14 卷 Ingredients 1-5「材料」页）重排为样式文本行，行数/h2/图片行/<br/>
# 本就允许与日文侧不同，配对检查整体豁免（check_alignment.pair_problems）。
TEXTUAL_IMAGE_HEADERS = frozenset({
    "S2_14-02", "S2_14-04", "S2_14-07", "S2_14-10", "S2_14-13",
})
JP_H1_BY_HEADER = {
    "S1_25-UIHARU_KAZARI": "初春飾利",
    "S1_25-KAMIJOU_TOUMA": "上条当麻",
    "S1_25-MARK_SPACE": "マーク＝スペース",
}

def pairing_header_of(name: str) -> str | None:
    """Return a content header while excluding Japanese wrapper pages."""
    if JP_WRAPPER_RE.match(name):
        return None
    return header_of(name)
