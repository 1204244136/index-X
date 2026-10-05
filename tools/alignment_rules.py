#!/usr/bin/env python3
"""Reviewed project-level exceptions shared by alignment-related tools."""
from __future__ import annotations

import re

from epub_ids import NUMBERED_BOOK, S6_DATE, header_of


# S6_24.12.10：已于 2026-09-18 补齐日文侧（画集内以图片收录的 SS 短篇已用
# 图像转录还原为单文件 EPUB，交付后经 pull.ps1 入库），两侧恢复常规配对与
# 模板检查，登记已移除。
# S5_02_03：日文源不是分页文本，而是一页式固定版式 EPUB——整个作品只有一个
# `item/xhtml/S5_02_03-01.xhtml`（自成一页，配 `fixed-layout-jp.css`），
# 中文侧则是拆成 5 章的文本化重排。两者无法按行/表头对应，逐条比对只会
# 产出「h2 位置 JP[…22 个…] vs CN[]」这类恒定噪声（日文那 22 个 h2 是
# 一页式文件里的版式锚点，不是章节标题）。因此按「非同一形态」跳过配对，
# 中文侧仍照常做单侧模板检查。
NON_PAIR_WORK_IDS = frozenset({"S5_02_03"})
MANUAL_ALIGNMENT_HEADERS = frozenset({"S1_25-STIYL_MAGNUS"})

# 译文归属：该作品的**部分中文译文**落在另一本书里，术语落地核对
# （`check_translation_table.py`）必须在归属书里一并检索，否则日文锚点在这本、
# 中文译文在那本的条目会一律误报「未落地」。
#
# 登记项（键＝日文锚点所在书，值＝中文译文所在书）：
#   S5_02_03（Cold Game）→ S5_02_01（学艺都市篇）：本卷的**后记**在中文侧被归入
#   合订卷首篇。中文 `S5_02_03-01_Main.xhtml` 末行自述「（后记在[S5_02_01]某科学的
#   超电磁炮SS 学艺都市篇X中）」，日文后记里的角色名（`トチトリ`、`ショチトル`）
#   因此只在 S5_02_01 的中文正文里能命中。
# 只登记**有明确书内自述或结构性依据**的归属，不凭检索猜测。
TRANSLATION_HOST = {
    "S5_02_03": "S5_02_01",
}

# 已判定、**不再计入待判**的锚点（键＝归一化后的日文写法，值＝判定说明）。
#
# `check_translation_table.py` 只做字符串命中，无法区分「专名」与「普通词」：表内是某个
# 专名，正文里出现的是同形的普通词时，必然误报「术语未落地」。这类命中已逐条回日文原文
# 判定过，按 `translation-spec.md` 的术语分层口径属**工具误报**，不构成缺陷——登记于此，
# 工具命中时记为 `settled`，不再出现在待判清单里，避免每天重复翻出。
#
# 只登记**已逐条回原文判定过**的锚点；新出现的同类命中仍先按待判处理，判定后再登记。
# 每条三个字段：
#   note   —— 为什么是同形不同义（写清「表内义项」与「正文义项」）
#   scope  —— 该判定适用的作品号；空串表示不限。**抑制只在该作品内生效**，避免一个锚点
#             在一本书里被判定后，在别的书里连真专名也一起被跳过。
#   status —— `settled`（已判定为同形不同义）或 `待裁定`（两个译法都成立、尚未定，暂缓）。
#             两种都不计待判；但只要该锚点进了《译名裁定总表》，抑制即失效、改按裁定判定。
SETTLED_ANCHORS = {
    "昼間": {"note": "表内是术语「【白昼】」，正文是普通词「白天」", "scope": "S2_19", "status": "settled"},
    "ラベンダー": {"note": "表内是人名「拉贝达」，正文是香草「薰衣草」", "scope": "S3_06", "status": "settled"},
    "ペルセフォネ": {"note": "表内是组织名，正文是神话女神名", "scope": "S2_15", "status": "settled"},
    "ヘイヘイ": {"note": "表内是企业名「HeyHey」，正文是语气词", "scope": "S2_01", "status": "settled"},
    "ロッド": {"note": "表内是人名别名「洛特」，正文是普通词「插销」", "scope": "S2_15", "status": "settled"},
    "ドラゴン": {"note": "表内是术语「DRAGON」，正文是普通词「龙」", "scope": "S3_09", "status": "settled"},
    "階層": {"note": "表内是术语「楼层」，正文是概念「阶层」", "scope": "S3_11", "status": "settled"},
    "ヒュドラ": {"note": "音译「海德拉」vs 意译「九头蛇」两案都成立", "scope": "S5_03_02", "status": "待裁定"},
}

# 已裁定不纳入**正文固定行模板**检查的作品。这些书不是「待修的问题书」，而是明确
# 保持原始快照/非正文结构，改动它们不在当前任务范围内；它们的模板差异是既有事实，
# 每天重复报出来只会淹没真信号。豁免粒度是「作品 + 检查项」：这里的书仍然参与
# 内容序、配对、悬空引用等其它检查。
#
# 这份名单是**唯一事实来源**，`check_alignment.py` 与 `check_epub_health.py` 都从这里
# 取；两处各写一份必然漂移。加条目等于放宽检查口径，必须同时写明依据。
TEMPLATE_EXEMPT_WORK_IDS = frozenset({
    # 读前必看，非正文作品，结构本身与正文模板无关
    "S0_00",
    # 无 BW 分页源，明确不处理（保持原始快照结构）
    "S6_10.06.26",
})


def template_exempt(work_id_value: str | None) -> bool:
    """This work is out of scope for the fixed-line-template check."""
    return bool(work_id_value) and work_id_value.upper() in TEMPLATE_EXEMPT_WORK_IDS

JP_WRAPPER_RE = re.compile(
    rf"^(p-|navigation-documents|Anotherworld|(?:{S6_DATE}|{NUMBERED_BOOK})-(?:p-|navigation))",
    re.I,
)
# 已确认的文本化图片例外（AGENTS.md「图片行」条目）：中文侧把分页源的整页图片
# 重排为样式文本行，行数/h2/图片行/<br/> 本就允许与日文侧不同，配对检查整体豁免
# （check_alignment.pair_problems）。
#
# 「外典书库」（S5）系列每部作品的首个内容单元是**作品扉页**：日文侧是一张
# 整页图片（`<p id="toc-00N"><img class="fit" src="../image/S5_…-m-00N.jpg"
# alt="作品名"/></p>`），中文侧没有这个图片页，改为一张文本化的「简介」页
# （`-01_Introduction.xhtml`，把该作品的宣传语/梗概排成正文）。因此这一对
# 天然是「一侧纯图片页 vs 一侧正文页」——按行比对只会产出恒定差异，
# 属同一族已确认例外（S2_14 那 5 个是「中文把整页材料图排成文本行」，
# 这里是「中文把整页扉页图换成简介页」，判定口径一致）。
TEXTUAL_IMAGE_HEADERS = frozenset({
    "S2_14-02", "S2_14-04", "S2_14-07", "S2_14-10", "S2_14-13",
    # S5 各作品扉页：日文整页图片 ↔ 中文「简介」文本页
    "S5_01_01-01", "S5_01_02-01", "S5_01_03-01",
    "S5_02_01-01", "S5_02_02-01",
    "S5_03_02-01", "S5_04_01-01",
})
# 已逐条确认的**配对差异例外**：中日两侧在这些表头上确实不同，但差异是已知且
# 有依据的，不是待修的对齐问题。判定函数在 `check_alignment.py`；命中后只抵消
# 该规则解释得了的问题项，其余差异照报（不是整表头豁免）。
#
#   afterword-moved  中文侧后记被有意合并到同一合订卷的另一部作品里
#                    （S5_01_03-Information.xhtml 明写「（后记在 [S5_01_01]…
#                    神裂火织篇X 中）」）。日文末尾的「あとがき」整段在中文
#                    这一侧本就不该有，因此行数与 <br/> 位置差异合法。
#                    已验证：日文截到「あとがき」独占行之前后，行数、h2 位置、
#                    图片行、<br/> 位置与中文侧完全一致。
#   section-order    中文侧把小节标题放在分页边界之前、日文快照放在之后
#                    （`<p class="pb">` 收束分页 → 中文 `<h2>` → 图片行；
#                    日文 图片行 → `<h2>`）。中文顺序让 h2 开启新页，是合并
#                    分页源时应有的形状；改日文侧等于改原样快照。
PAIR_RULES: dict[str, str] = {
    "S5_01_03-06": "afterword-moved",
    "S5_01_02-09": "section-order",
}


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
