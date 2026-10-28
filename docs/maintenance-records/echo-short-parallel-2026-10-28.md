# 呼应检查新增「短平行句」候选类（2026-10-28）

- 范围：`tools/check_echo.py`、`tools/tests/test_check_echo.py`、`tools/README.md`、`.agents/skills/proofread-review/SKILL.md`
- 触发：S2_04 校对复核发现 `S2_04-01` L6/L7 的 `たった三人の『木原』`／`たった三人の『グレムリン』` 只改 L6 为「三名」、L7 留「三人的」，形成量词呼应断裂；旧版类 1（要求日文片段相同）与类 2（只收 ≥20 字）都覆盖不到 9／11 字的短平行句。
- 实现：新增类 4「短平行句」。条件为同文件、行距 ≤1（`--short-window`）、日文 6–24 字（`--short-min`／`--short-max`）、最长公共前后缀 ≥4（`--short-affix`）、序列相似度 ≥0.5（`--short-ratio`）、中文不同；按「量词 > 功能词 > 实词」排序，量词型（两句共享日文数词、中文量词不一致）置顶。
- 验收：
  - `python -m pytest tools/tests -q`：1058 passed、4 skipped、494 subtests；
  - `python tools/check_project_docs.py`：问题 0；
  - S2_04 回放：3753 行报 13 对（L6/L7 为 4.11）；S1_01 回放：3110 行报 7 对；
  - 全库只读估算：204 对／58 本（用于校准候选量，未逐条判定）。
- 边界：只报候选、不判定、不写盘；刻意平行（不同说话人、语体、对照句）须人工排除；不改变类 1／类 2 的既有阈值。
