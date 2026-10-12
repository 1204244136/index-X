# 6 本 `unique-identifier` 去重 ＋ 该检查升级为阻断（2026-10-12）

- **触发**：成品构成门禁的 `identifier-unique`（报告级）存量：6 本共用同一个 `id="BookId"`。
- **范围**：**6 本**内容改动（`[S3_11]`、`[S4_02]`、`[S4_03]`、`[S6_24.01.10]`、`[S6_24.06.07]`、`[S6_24.12.10]`）＋ **门禁级别升级与接线**。
- **性质**：明显错误订正（模板串值残留）与规范执行，不构成裁定。

## 一、诊断

- 6 本共用 `uuid:1ffc6038-be43-40bc-a2ce-6de06e702c7b` 作为包文档的 `unique-identifier`——那是模板串值；`toc.ncx` 的 `dtb:uid` 也是它。
- **每本在同一文件的另一行已经有一条自己的 uuid**（calibre 写入的那条），所以修复**不需要新造任何标识值**：把 `id="BookId"` 的值改回本册自有 uuid、并让 `dtb:uid` 同值即可。
- 目标形态取**当前导入管线的产物形态**（`import_build_wrappers.py`：`uuid:X` ＋ 同值 `id="BookId"`，`dtb:uid` = X），先例 `[S5_04_02]`（该管线 2026-10-10 产出）与 `[S4_04]`。

## 二、改动

| 项 | 内容 |
| --- | --- |
| 文件 | 6 本 × 2 个文件（`OEBPS/content.opf` 的 `BookId` 行、`toc.ncx` 的 `dtb:uid`） |
| 规模 | **12 行替换**（+12/−12），无增删行 |
| 标识值 | 全部沿用各册**既有** uuid；calibre 库身份不变 |

一次性修订用临时脚本（默认预览、`--apply` 才写、逐册预检 BookId／自有 uuid／`dtb:uid` 各恰好一处且为模板串值），按 AGENTS「工具与记录的边界」**改完即删**。

## 三、门禁升级与接线

`identifier-unique` 由 **warning 升级为 error**。它此前只在 `check_epub_health` 的 `main()` 层计算，**发布预检取不到**；本次在 `publish_preflight.validate_publication()` 增加库级复核（复用同一实现 `find_identifier_duplicates` ＋ 同一豁免注册表），使升级真正生效。测试补两处：严重级断言、以及「两本共用同一 uuid → `validate_publication` 返回 False」的反例。`docs/epub-artifact-spec.md` 第五节的级别口径与 `tools/README.md` 的检查项说明同步——**六项全部为阻断项**。

## 四、验证

| 门禁 | 结果 |
| --- | --- |
| `check_epub_health.py --only identifier-unique` | 0 命中 |
| `check_epub_health.py --root EPUB --strict` | 退出 0，**问题 0 条（error 0 / warning 0）**——19 项检查全库归零 |
| `python -m unittest discover -s tools/tests -p "test_*.py"` | 全部通过（含新增的预检反例） |
| `check_project_docs.py` | 0 问题 |

## 五、发布

`publish_auto.py` 走**流程 C**，6 本「全部方向执行成功」；复验 dry-run 无待发布。

## 六、本次新暴露、未处理的第三类标识缺陷（登记待办）

统计发现 **61 本**的 `toc.ncx` `dtb:uid` 与包文档的两条 identifier 都不相同；其中 **56 本共用一个模板串值** `uuid:afa76961-fe51-4f63-a4c8-42cdfdd47768`，另有 `[S6_22.06.10]` 的 `dtb:uid` 缺 `uuid:` 前缀、`[S0_00]` 与 `[S4_01]` 共用 `uuid:f0fea63f-…`、`[S3_08]` 与 `[S3_09]` 共用 `uuid:895a6230-…`。

**本次不动**：① 规范尚未立这条（`dtb:uid` 必须等于 `unique-identifier`）；② 61 本重发与样式表统一同量级，应合并评估。建议下一批：立条文 ＋ 新增报告级检查 `ncx-uid`，随后清理并升级为阻断（与 `docTitle`／`toc-entry` 同一路径）。

## 七、回退

`git revert` 本次提交恢复 12 行；门禁级别回退需另改 `SEVERITY` 与预检接线（有测试兜底）。
