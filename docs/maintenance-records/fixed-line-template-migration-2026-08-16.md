# 中日缓存统一固定行模板迁移（2026-08-16）

## 结论

将 `.cache/epub-work/` 中日两侧正文 XHTML 全量迁移到「统一固定行模板」：L1 XML 声明、L2 DOCTYPE、L3 html/head/body 合并行（可含篇首图片）、L4 `<h1>` 独占行或空行、L5 `<h2>` 独占行或空行、L6 正文首行（绝对行号，缺元素以空行占位，空行不得用 `<br/>` 占位）。共迁移 1160 个缓存文件（含备份），`tools/check_alignment.py` 对 1001 个带正文文件校验结果：**0 问题**（模板符合、中日总行数一致、h2 位置一致、图片行一致）。

旧规范（正文第 5 行、标题行可并入 HTML 行、日文独有标题行合并删除）已废除。

## 范围与统计

- 迁移备份：`.cache/migrate-backup-20260816-171853/`、`-172104/`（一次性备份，确认后删除，不提交）。
- `tools/normalize_epub_cache.py` 按新模板重写（1729 个候选文件，2 个人工判定跳过，9 个最终改写，含二次运行修正历史双空格 `<h1 ` 标签）；`--dry-run` 预览、幂等。
- `tools/check_alignment.py` 新增（只读）：逐文件模板校验 + 中日配对行数/h2/图片对齐，报告 `.cache/epub-work/alignment-check.tsv`。
- 删除 6 个被取代的一次性分析工具（compare_cache_lines、analyze_image_alignment、analyze_unified_alignment、analyze_cache_diffs、analyze_afterword_breaks、analyze_orphan_image_pages）。

## S6 单文件作品处理（日文 start.xhtml 重命名 + 对齐）

| 作品 | 处理 |
|---|---|
| S6_14.09.10 | JP `start.xhtml` → `S6_14.09.10-Main.xhtml`；中文独有插图补入日文（占位行替换为图片行、复制图片、OPF 声明）；中日 357 行一致 |
| S6_18.04.10 | JP `start.xhtml` → `S6_18.04.10-Chapter.xhtml`；CN 删「正文」h1；正文固定第 6 行；OPF/NCX/nav 同步 |
| S6_20.05.09 | JP `start.xhtml` → `S6_20.05.09-Main.xhtml`；尾部附赠文本「本书由灰村清孝画集3附赠」移入 `S6_20.05.09-Information.xhtml`；CN 删 h1 |
| S6_24.01.10 | JP 13 个 h1 → h2（含头部内嵌 `<h1>1</h1>`）；CN 合并 2 行、拆分 1 行、4 处裸文本补 `<p>`；中日各 1027 行，h2 各 14 个位置一一对应 |
| S6_24.12.10 | 仅命名修正：CN `S6_24.12.10-Introduction.xhtml` → `S6_24.12.10-Main.xhtml`（nav/toc/opf 同步）；该作品两侧非同一作品（画集 vs SS），不参与配对 |

## S1_25 SP 篇（日文侧补 h1）

- Uiharu / Kamijou / Mark_Space / Afterwords：日文侧补 `<h1>`（标题取自日文原版目录：初春飾利、上条当麻、マーク＝スペース），中日对齐。
- Stiyl_Magnus：日文原文件缺 `<body>` 开标签（XML 非法），补 `<body class="p-text"><div class="main">`；日文补 `<h1>` + `<h2>` 1..6（L5/118/408/798/1326/1815）；中文 h1 → L4、h2 → L5；中日各 2019 行，6 组插图行（[3,115-117,405-407,795-797,1322-1325,1812-1814]）位置一致；lxml 校验通过。

## 遗留项

- `S2_19-13`：原记录为日文 37 行 vs 中文 35 行的跨页后记尾布局特例；复查确认两侧现均为 **37 行且逐行对齐**（L4/L5 空行、L6 正文、L18/20-22/29-34 `<br/>` 序列一致、L28 图片行一致），已从 `JUDGE_PAIRS` 移除并纳入 `check_alignment.py` 检查（1002 个文件 0 问题）。
- `S1_25-STIYL_MAGNUS` 保留在 `JUDGE_PAIRS`：已手工完成模板对齐，跳过以免规范化重建破坏手工结果。

## 备注

- 新模板规则已写入 `AGENTS.md`（Agent 操作边界-正文行结构）与 `tools/README.md`。
- 一次性扫描/迁移脚本位于 `.cache/`，未提交；可复用逻辑已并入 `tools/normalize_epub_cache.py` 与 `tools/check_alignment.py`。
- 迁移只影响缓存，未发布；发布前建议先运行 `python tools/check_alignment.py` 确认 0 问题。
