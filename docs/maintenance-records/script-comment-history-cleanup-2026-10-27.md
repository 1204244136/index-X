# 工具脚本历史说明归位（2026-10-27）

文档职责与入口见 [文档索引](../README.md)。

## 范围与处理

检查 `tools/`（含测试）与 `.github/` 脚本中的日期、修订叙述及相邻说明，整理 11 个 Python 文件与 1 个发布 workflow 的注释；另更新 `AGENTS.md` 与 `tools/README.md`，并新增本记录，共 15 个文件。未改运行逻辑、规则常量、测试断言或 EPUB 内容；模板豁免测试名称改为不依赖数量的名称。

代码保留当前行为、实现约束与必要的设计原因；移出带日期的变更经过和当次验收统计。同步修正体检代码及测试中仍称“报告级／存量未清零”的过期说明，级别说明指向实际的 `SEVERITY` 定义。工具合同中术语锚点一节的历史实测数字也移出，保留判定原因与历史记录指针。

软门禁正文见 [AGENTS.md](../../AGENTS.md#脚本说明软门禁)，工具合同只留入口；采用本次 diff 人工复核，不增加日期扫描器或 CI 阻断。协议版本与命名空间、业务日期、S6 标识、Unicode 码位、生卒年示例及历史文档路径按实际用途保留。

## 历史说明的去向

下表承接改动前脚本注释、docstring 与合同中的历史说明；日期与数字反映原说明的当时口径，**不是本轮重新实测的结果**。已有记录直接引用，不改写其历史结论。

| 原位置 | 迁出内容与已有记录 |
| --- | --- |
| `alignment_rules.py`、`tests/test_check_epub_health.py` | 原注释记载 `S6_24.12.10` 于 2026-09-18 补齐日文侧：画集中以图片收录的 SS 经图像转录还原为单文件 EPUB，经 `pull.ps1` 入库，移除例外并恢复常规配对与模板检查；旧测试说明指向提交 `cd2b7012`。此处承接该历史说明；活动例外表只说明仍有效的例外。 |
| `audit_risk.py`、`tests/test_proofread_review.py` | 2026-10-05 按维护者决定移除无裁定表落点、依据仅存历史提交的纠错规则（Saintium、站所、瓢虫铁处女机制、灵异照片机制、方向反转、12 人 VIP）；测试改用裁定表有落点的条目。相关文档职责订正见 [裁定表角色与归属订正](ruling-table-role-attribution-correction-2026-10-05.md)。 |
| `epub_ids.py`、`text_norm.py`、`build-epub-release.yml` | 2026-10-12 作品号定界符由半角迁为全角，历史迁移见 [定界符改形记录](bracket-form-change-2026-10-12.md)；代码只保留成品侧与外部输入侧的识别边界，以及全角定界符在 glob 中的字面含义。 |
| `check_epub_health.py`、`alignment_rules.py`、`tests/test_check_epub_health.py` | 原说明的目录名／标题／必备部件基线为 81/81；`docTitle` 同日清理 68 本（含 `S0_00`），目录条目补齐 `S6_24.01.10`，跨书标识符修复 6 本，`dtb:uid` 对齐 61 本后升级阻断。分别见 [上线基线](artifact-gates-baseline-2026-10-12.md)、[docTitle 对齐](doctitle-alignment-2026-10-12.md)、[目录条目订正](s6-24-01-10-toc-entry-fix-2026-10-12.md)、[标识符去重](unique-identifier-repair-2026-10-12.md)、[NCX UID 对齐](ncx-uid-alignment-2026-10-12.md)。相邻说明中的 Note 结构一次性修正见 [译注规范落盘](note-spec-landing-2026-10-09.md)，79 本 nav 裸 `br` 清理见 [导航结构清理](nav-structure-br-cleanup-2026-10-12.md)。直角引号曾有 21 处跨段等写法，原说明以此解释需人工判断，代码改为只保留判断原因。 |
| `check_translation_spec.py` | 原注释的 2026-10 回测：856 条译注中可选逗号缺失造成 38 条误判（346 → 308）；放宽甲类后需元话语和连词黑名单配合。样例与修正经过已在 [译注起句收敛记录](note-lead-convergence-2026-10-09.md) 保存。代码保留可选逗号与黑名单互补的原因及必要样例。 |
| `check_term_anchors.py`、`publish_preflight.py`、`tools/README.md` | 2026-09-17 统一后，2026-10-05 整卷重写使 98 处回落，10-19 仅补 `魔術師`，10-27 反馈后建立锚点门禁；背景与回测见 [术语锚点门禁记录](term-anchor-gate-2026-10-27.md)。原说明另记 `S5_01_02` 有 441 处 `魔術`、仅书名一处带括号，以及全库“日文含锚点而中文缺裁定写法”728 行，多为书名、省略或改写；此处承接数字，合同与代码只保留误形判定原因。 |
| `tests/test_compare_epub_images.py` | 原注释记载 2026-10-09 Build EPUB Release 因硬导入可选 Pillow 导致测试采集失败；经过与验证见 [图片对照测试记录](compare-epub-images-tests-2026-10-09.md)。测试保留缺依赖时跳过及捕获 `SystemExit` 的原因。 |

## 本轮验证

| 检查 | 结果 |
| --- | --- |
| `python tools/check_project_docs.py` | 0 问题。 |
| `python -m unittest discover -s tools/tests -p "test_*.py" -q` | 922 项测试，`OK (skipped=3)`，无失败；跳过项未计作执行通过。 |
| Python AST 与改动前 HEAD 比对 | 11 个文件剔除 docstring、归一化已审阅的测试改名后完全一致；运行逻辑、规则常量及断言未变。 |
| 发布 workflow 比对 | 剔除整行注释后与改动前一致。 |
| `python tools/publish_preflight.py --help` | 退出 0，帮助入口正常；本轮未运行内容发布或同步。 |
| `git diff --check` 与人工复核 | 无补丁空白错误；脚本说明、软门禁及记录链接经独立复核。剩余日期命中为文档引用、协议版本或业务数据。 |
