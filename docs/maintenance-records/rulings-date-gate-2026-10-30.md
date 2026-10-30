# 裁定表日期门禁（2026-10-30）

- 范围：`tools/check_project_docs.py` 的 `single_source_issues` 增加「裁定表不记日期」检查（第 ⑤ 项）；清理 `docs/translation-name-rulings.md` 备注列 19 个单元格里的落地日期；裁定表 §11.5 由「裁定被推翻时不新开一节」改写为「本表不记过往」；`tools/README.md` 的 C4 合同与 `tools/tests/test_check_project_docs.py` 同步。
- 背景：10-06 曾按「表不记过往」清理过一轮（`7d956111` 删 24 行的计数、日期、回滚史、维护者裁定、提交号与文件行号，`06cabb91` 改写 §11.5，`9e7b4c34` 去掉历史索引），但该原则只写在提交信息里，没有进规范正文，也没有机器检查。此后 42 次改裁定表的提交里有 17 次新增日期，最近一次为 `5c8ceca1`（2026-10-30）。读取裁定表的五处入口——`check_project_docs.py`、`check_translation_table.py --audit-rulings`、`check_term_anchors.py`、`proofread_review.py`／`audit_risk.py`、`publish_preflight.py`——都不检查日期，CI 因此长期全绿。

## 判定口径

- 只扫裁定表主表数据行（§五–§十，含 §6.1／§7.1／§8.1／§9.1）的「备注」「理由」「被否决或并存的候选」三列；锚点与裁定列不扫。
- 命中 `2026-10-30`、`2026/10/30`、`2026.10.30`、`2026年10月30日`，以及 `2026年10月` 这类年月表述；只认 `20xx`，不把 `GB/T 26992-2011`、`S6_24.06.07` 等标准号或作品号当日期。
- 单行可用 `<!-- rulings-date-ok -->` 显式放行；业务日期不得依赖该标记，应改写为不带日期的表述或移到留档。
- 报告文案指向留档与提交：落地时间、次数、提交号与回滚经过归 `docs/maintenance-records/` 与提交，不留在裁定表。

## 接入点

- `check_project_docs.py` 已由 `.github/workflows/check-epub-health.yml`（文档职责与链接检查）与 `.github/workflows/build-epub-release.yml`（Validate tools and publication source）执行，本次不改 workflow，命中即非零。
- 本地与 CI 同一入口；不新增工具、不新增 CI 步骤。

## 验证

- `python tools/check_project_docs.py`：**问题 0 条**（清理后）。
- `python -m unittest discover -s tools/tests -p "test_*.py"`：**1072 个测试通过，4 个跳过**（新增 5 个日期门禁用例）。
- 负向自检：临时裁定表写入「维护者裁定 2026-10-30」→ 报 `裁定表不记日期（「备注」列出现「2026-10-30」）`；同样内容加 `<!-- rulings-date-ok -->` → 不报。
- `python tools/check_translation_table.py --audit-rulings` 需 `--table`（译名表 xlsx），本机未配置该输入，未执行；本次未改动锚点列、裁定列与判定列，解析路径由全量测试中的 `test_check_translation_table.py` 覆盖。

## 限制与维护

- 只拦日期；「N 处／N 行」计数、7 位提交号与「回滚经过」叙述仍靠人工软门禁，后续需要时在同一检查里加规则并先清存量。
- 只覆盖 §五–§十 的裁定条目表；§一–§四、§十一的规则正文不在扫描范围。
- 回退：`git revert <commit>`；删除检查后裁定表可恢复带日期的写法，但不建议。
