# 成品构成门禁上线与存量基线（2026-10-12）

- **背景**：《EPUB 成品构成规范》（[epub-artifact-spec.md](../epub-artifact-spec.md)）同日新增（提交 `b68315d1`），本批把其中可机械判定的部分接进门禁。
- **范围**：`tools/check_epub_health.py`（新增 6 项）、`tools/alignment_rules.py`（豁免注册表 `HEALTH_EXEMPT_WORK_IDS`）、`tools/README.md`（体检节与 C4 说明）、四套测试夹具与新增负例。**未改动任何 EPUB 内容**，不涉及发布。

## 一、新增检查项与级别

| 检查项 | 级别 | 判什么 | 全库存量（81 本） |
| --- | --- | --- | --- |
| `dir-name` | error | 书目录名带 `[作品号]` 前缀与结尾 `X` | 0（`S0_00` 豁免 1 处） |
| `metadata-title` | error | `dc:title` 逐字节等于书目录名 | 0 |
| `packaging-required` | error | `content.opf`／`nav.xhtml`／`toc.ncx` 与封面、制作信息页齐备，且两张包装页已被 manifest 声明、已进 spine | 0 |
| `toc-entry` | warning | 目录首条目为「制作信息」、封面不入目录（nav 与 ncx 一致） | 2（均属 `[S6_24.01.10]`） |
| `ncx-doctitle` | warning | `docTitle` 等于 `dc:title` | 67（另 `S0_00` 豁免 1 处） |
| `identifier-unique` | warning | 跨书 `unique-identifier` 唯一 | 6 |

error 级经 `publish_preflight.py` **接入发布阻断**（预检取 `check_epub_health` 的全部 error 级）；warning 级只报告，不阻断。豁免粒度「作品 + 检查项」，名单唯一来源在 `tools/alignment_rules.py`。

## 二、存量基线与排队（关键：为什么后三项只是报告级）

- **`ncx-doctitle` 67 本**：59 本仅缺 `[作品号]` 前缀；9 本为其它差异，其中含真错——`[S5_04_01]` 的 `docTitle` 写「史迪特拉第瓦里篇」而书名是「斯塔蒂瓦里篇」（译名不一致）、`[S6_20.05.09]` 丢了「黑夜海鸟篇」、`[S6_24.01.10]` 写「女王的**演戏**」（错字）、`[S2_23]` 把 `22REVERSE` 缩成 `22R`、`[S4_01]` 完全没有卷号。**用户裁定：立规范、门禁只报告；68 处存量清理排队，与样式表统一同批评估。**
- **`identifier-unique` 6 本**（`[S3_11]`、`[S4_02]`、`[S4_03]`、`[S6_24.01.10]`、`[S6_24.06.07]`、`[S6_24.12.10]`）共用 `uuid:1ffc6038-be43-40bc-a2ce-6de06e702c7b`：**已裁定另立项**，修完再升级为阻断。
- **`toc-entry` `[S6_24.01.10]`**：目录首条目为「1」（nav 与 ncx 一致），属单本内容改动，登记待办。
- 样式表统一（81 本逐字节一致的路线选择）见 [移除翻译质量提醒记录](s5-translation-quality-notice-removal-2026-10-12.md) §五。

## 三、验证

| 门禁 | 结果 |
| --- | --- |
| `python -m unittest discover -s tools/tests -p "test_*.py"` | **649 tests OK**（2 skipped：Pillow／openpyxl 可选依赖） |
| `check_epub_health.py --root EPUB --strict` | 退出 0（error 0；warning 75 = 上述报告级项） |
| `check_project_docs.py` | 0 问题 |

新增检查项均带最小反例（`test_check_epub_health.py`）：目录名缺 X／缺作品号前缀、`dc:title` 与目录名不一致、缺制作信息页、包装页未入 manifest 与 spine、目录首条目错、`docTitle` 不一致、跨书 uuid 重复的助手函数。

## 四、夹具升级（测试侧，踩坑记录）

error 级接入发布预检后，"看起来正常"的合成书必须满足成品构成，四套夹具（`test_check_epub_health.py`、`test_package_cache_epubs.py`、`test_publish_auto.py`、`test_publish_preflight.py`）因此升级为：目录名带 `X`、`dc:title` 等于目录名、`nav.xhtml`／`toc.ncx` 齐备、封面与制作信息页齐备并已入 manifest/spine。

**踩坑**：夹具的 `nav.xhtml` 若使用 `epub:type` 而不声明 `xmlns:epub`，XML 解析会以 `unbound prefix` 失败——这一条由 `package_cache_epubs.validate_book` 拦下，表现为 5 个集成测试连带失败。夹具写 XHTML 时命名空间必须完整。
