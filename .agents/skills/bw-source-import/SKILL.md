---
name: bw-source-import
description: index-X 日文 BW 源导入工作流（BookWalker 分页源 → 日文工作源 → 交给 volume-import）。用于「把某卷日文源做出来／日文原文入库／BW 提取预处理＋分页合并／S5 合订卷拆分」：先确认作品号与逐页内容序（含无标题尾声、附录与包装页边界），S5 合订卷先拆分，再按分页契约预处理、按换页衔接规则合并成章节文件，跑容器与 XML 门禁后进日文侧缓存并交接。触发词：日文源导入、BW 源、日文原文入库、bw_preprocess、分页合并、merge_bw_pages、S5 拆分、日文工作源。
---

# 日文 BW 源导入（index-X）

文档职责与入口见 [文档索引](../../../docs/README.md)。命令合同见 [工具说明](../../../tools/README.md) 的 C2（导入与交稿往返），
仓库级规约（作品号与表头、图片命名、固定行模板、写入边界）见 [AGENTS.md](../../../AGENTS.md)。

本 skill 管「把一份 BookWalker 分页源做成可配对、可对齐的日文工作源」。它**到日文侧进入
`.cache/epub-work/japanese-text/<作品号>书目录` 且能跑单侧对齐检查为止**；之后的「交稿 → 成品」
属于 `volume-import`（它的材料表把「日文原文：已同步进缓存的书目录」列为应当就绪的输入）。

## 一、先确认三件事（不确认不动手）

| 要确认的 | 为什么 | 找谁确认 |
| --- | --- | --- |
| 作品号与内容序 | `--book-id` 只用于**已确认**作品号和内容顺序的包；序号错会让中日配对整体错位 | 用户／既有档案；不确定就停下来问 |
| 逐页内容映射 | 无标题的新语义单元（尤其后记署名之后的「尾声」）、正文插图与作品级图片包装页**不能**沿用上一页表头 | 按内容人工确认后写进映射文件 |
| 源的类型 | 合订卷要拆、纯图册要跳过、普通分页源直接进预处理 | 看源结构与页型；纯图册整本无文本页 |

逐页映射落在 `bw_page_header_overrides.json`（或 `--header-map` 指定的显式文件）：正整数为内容序、`null` 为包装页；**缺页、额外页或非法序号都会阻断**，映射必须覆盖实际分页。

## 二、四步流程

| 步骤 | 入口 | 写什么 | 失败怎么办 |
| --- | --- | --- | --- |
| 1 拆分合订卷（仅 S5） | `split_s5_epubs.py` | 显式打包／解包暂存目录 | 页区间对不上 → 先核对 `SPLIT_SPECS`，不许放宽规格 |
| 2 分页预处理 | `bw_preprocess.py` | 显式产物／暂存目录 | `--check` 报契约问题 → 改规则表或映射，不改门禁 |
| 3 分页合并 | `merge_bw_pages.py` | 显式章节输出 | 表头／序号冲突或边界疑点 → 人工确认后再合并 |
| 4 入库与交接 | `pull.ps1` ＋ `check_alignment.py` | 日文侧缓存、单侧检查 | 缓存里没有该作品 → 先确认源已进 OneDrive 日文目录 |

### 1. 拆分合订卷（仅 S5）

```powershell
python tools/split_s5_epubs.py 显式源目录 --packed-out 显式打包暂存 --unpacked-out 显式解包暂存
python tools/split_s5_epubs.py 显式源目录 --packed-out 显式打包暂存 --unpacked-out 显式解包暂存 --apply
```

默认预览；两个输出路径必填且**视为显式暂存**，不能位于仓库缓存或 OneDrive。`SPLIT_SPECS` 是已确认源卷与页区间的唯一实现数据，新增卷先核对页区间再改规格。全部源、规格、页区间、资源与产物契约在输出前完成验证。

### 2. 分页预处理

```powershell
python tools/bw_preprocess.py 原始.epub --book-id S4_05 --check
python tools/bw_preprocess.py 原始.epub --book-id S4_05 --header-map 映射.json --out 暂存输出 --apply --staging
python tools/bw_preprocess.py 显式分页目录 --dry-run
```

默认预览，`--apply` 才写入；`.epub` 写入必须显式 `--out --staging`。默认是**分页契约**：L3 必须含 `<div class="main">`（合并器靠它定位正文）。`--check` 在内存模拟转换、重命名与资源更新，正常产出走同一门禁。图片前缀与全部引用同步更新。

### 3. 分页合并

```powershell
python tools/merge_bw_pages.py 分页目录 --book S4_05 --dry-run
python tools/merge_bw_pages.py 分页目录 --book S4_05 --out 显式章节输出 --apply --staging
```

默认预览，`--apply` 必须显式 `--out`。输入须经过预处理；输出章节已套固定行模板。按 AGENTS 的换页衔接规则处理 `pb`、篇首图片与标题。文本跨页是否同一段断续、图片归属、标题边界与残留噪声会输出**待确认项**，不自动改译文。

合并后的目录若还要再校验，必须换契约：`python tools/bw_preprocess.py 显式章节目录 --merged --check`——**不能用分页契约检查已合并章节**。

### 4. 入库与交接

产物先留在显式暂存目录，验证通过后进 OneDrive 日文源，再由拉取同步器进缓存：

```powershell
./tools/pull.ps1 -WhatIf -Side japanese
./tools/pull.ps1 -Side japanese
```

缓存是同步器的作用域，本流程**不直接写** `.cache/`。

## 三、交接检查（交给 volume-import 之前逐条确认）

- [ ] `.cache/epub-work/japanese-text/` 下存在该作品号的日文书目录，且里面有分页合并后的 XHTML。
- [ ] 逐页映射已落盘（`bw_page_header_overrides.json` 或显式 `--header-map`），并与实际分页逐页一致。
- [ ] 单侧对齐检查能跑：`python tools/check_alignment.py --root EPUB --jp-root .cache/epub-work/japanese-text`。中文侧尚未就绪时应如实报「未配对」，**不得据此宣布中日配对已通过**。
- [ ] 作品号、图片前缀与容器引用一致（图片名带完整作品号前缀，XHTML/OPF/NCX/nav/CSS/SVG 引用同步更新）。
- [ ] 没有把纯图册源当文本源处理；`S6_24.12.10` 画集本身不归档，其中 SS 的独立转录 EPUB 按常规配对，不套画集例外。

## 四、不许做的事

- **不写 `.cache/`**：日文侧缓存只由 `pull.ps1`／发布同步器更新。暂存目录必须在归档、仓库缓存与 OneDrive 之外。
- **不猜表头与内容序**：不得只按 `h1`、页码或文件名模式推导；无标题尾声／附录边界必须人工确认后写进映射。
- **不猜中日配对**：源缺失就报缺失，不用相同日期或相似文件名凑对。
- **不放宽门禁**：预处理与合并的契约检查失败时改输入或映射，不改判定条件。

## 五、坑清单（都踩过）

| 坑 | 表现 | 处置 |
| --- | --- | --- |
| 用分页契约校验合并结果 | 报「L3 未折叠为单行头部（需含 `<div class="main">`）」 | 加 `--merged`；两者契约不同 |
| 映射未覆盖实际分页 | 预处理阻断或插图沿用上一单元表头 | 补齐逐页映射，不留「默认继承」 |
| 纯图册源 | 整本无文本页，产出空章节 | 整本跳过（`--force-image-only` 只是显式强制开关，不是常规路径） |
| 把后记之后的附录并进「尾声」 | 附录页被当成故事性尾声 | 后记之后一遇非正文页即进书末附录，保留原名、不开尾声 |
| 在暂存目录就地 `--apply` | 被路径保护拒绝 | 临时目录就地处理要 `--apply --staging`；`EPUB/` 内的目录目标可直接 `--apply` |
