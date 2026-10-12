# 61 本 `toc.ncx` 的 `dtb:uid` 对齐 ＋ `ncx-uid` 升级为阻断（2026-10-12）

- **触发**：同日新立的 `ncx-uid` 检查（提交 `dfb30776`：先落地条文＋报告级门禁）存量 61 本。
- **范围**：**61 本**内容改动（`toc.ncx` 的 `dtb:uid` 对齐为包文档 `unique-identifier`）＋ **门禁级别升级**。
- **性质**：规范执行与模板串值清理，不构成裁定。

## 一、改动

| 项 | 内容 |
| --- | --- |
| 文件 | 61 个 `toc.ncx`，各**恰好替换 1 行**（`dtb:uid` 的 content），合计 **+61/−61** |
| 目标值 | 各册包文档 `id="BookId"` 的既有值（**不新造标识值**） |
| 另 20 本 | 原本已一致，未动 |

原值分布：**56 本共用模板串值** `uuid:afa76961-fe51-4f63-a4c8-42cdfdd47768`；其余为零散旧值——`[S0_00]` 与 `[S4_01]` 共用 `uuid:f0fea63f-…`、`[S3_08]` 与 `[S3_09]` 共用 `uuid:895a6230-…`、`[S3_06]`／`[S3_07]` 各有各的旧值、**`[S6_22.06.10]` 的 `dtb:uid` 还缺 `uuid:` 前缀**（本次一并补上）。

一次性修订用临时脚本（默认预览、`--apply` 才写、逐本预检「BookId 恰好 1 条、`dtb:uid` 恰好 1 处、只改 1 行」，任一不符整批拒写），按 AGENTS「工具与记录的边界」**改完即删**。

## 二、门禁升级

`ncx-uid` 由 **warning 升级为 error**：存量清零后与其余六项同级。它是**逐本项**（由 `audit_book` 判定），因此自动经 `publish_preflight` 进入发布阻断，无需像 `identifier-unique` 那样额外接线。测试断言同步改为 `error`；`docs/epub-artifact-spec.md` 第五节的级别口径与 `tools/README.md` 同步——**七项全部为阻断项**。

## 三、验证

| 门禁 | 结果 |
| --- | --- |
| `check_epub_health.py --only ncx-uid` | 0 命中 |
| `check_epub_health.py --root EPUB --strict` | 退出 0，**问题 0 条（error 0 / warning 0）**——20 项检查全库归零 |
| `check_epub_validity.py EPUB --structural --strict`（calibre 9.14） | 81 本、0 问题 |
| `python -m unittest discover -s tools/tests -p "test_*.py"` | 651 tests OK（2 skipped） |
| `check_project_docs.py` | 0 问题 |

## 四、发布

`publish_auto.py` 走**流程 C**，61 本「全部方向执行成功」；复验 dry-run 无待发布。

## 五、回退

`git revert` 本次提交恢复 61 行；门禁级别回退需另改 `SEVERITY`（有测试兜底）。
