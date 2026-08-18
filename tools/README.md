# EPUB 维护工具

## 正文行结构规范（统一固定行模板）

中日两侧带正文的 XHTML 使用统一固定行模板：

```
1  <?xml …?>
2  <!DOCTYPE html>
3  <html …><head>…</head><body…>   ← 可并入篇首图片（body 开头）
4  <h1>…</h1>                      ← 独占行；无 h1 则空行
5  <h2>…</h2>                      ← 独占行；无 h2 则空行
6  <p>正文首行</p>                 ← 永远在第 6 行
```

- h1、h2 必须独占一行；缺元素用空行占位（不得用 `<br/>` 占位）。
- 中文 Note 等列表型包装页：若没有 h2，`<ul>`/`<ol>` 可放在第 5 行占位，第一条列表项从第 6 行开始。
- 同一文件中日两侧的 h1/h2/空行位置一一对应；总行数一致。
- 纯图片页、无正文页、日文独有包装页（原样快照）不适用。

## 拉取与发布流程

三处中文文件副本各有固定角色，不得互相替代：

- `.cache/epub-work/`（解包工作区，不提交）：唯一编辑点。`pull.ps1` 从 OneDrive 解包生成，可随时删除重建。
- `EPUB/`（解包归档，提交到 git）：版本控制真源，diff 友好；仅由 `publish.py` 从缓存同步覆盖。
- OneDrive（打包 `.epub`，外部）：分发与阅读副本；既是 `pull.ps1` 的输入，也是 `publish.py` 的上传目标。

编辑边界：

- 只在 `.cache/epub-work/` 中编辑。直接修改 `EPUB/` 不会同步回 OneDrive，因为 `publish.py` 只读取缓存。
- 不得直接修改 OneDrive 中的 `.epub`。若已修改，切勿在发布前运行 `pull.ps1`，否则 OneDrive 的改动会被当作新基线拉入缓存，覆盖缓存中的编辑。
- 缓存中的改动必须经 `publish.py` 才会同步到 `EPUB/` 和 OneDrive。发布后中文缓存与 `EPUB/` 逐字节一致属预期行为。
- `.cache/` 可丢弃：删除后运行 `./tools/pull.ps1` 即可完整重建。

### 两种常用工作流（均增量处理，不做全量写入）

**流程 A：只改了 OneDrive 里的文件 → 拉回缓存并写进 `EPUB/`**

```powershell
./tools/pull.ps1 -SyncToEpub
```

只解压 OneDrive 中发生变化（修改时间/大小变化）的 `.epub`，与 `manifest.json` 对比后，仅把真正变化、新增或删除的文件写入 `EPUB/`，并更新这些书的清单基线。OneDrive 已是最终内容，本流程不会打包上传。可用 `-Side chinese` / `-Side japanese` / `-Pattern` 限定范围，`-WhatIf` 预览。

**流程 B：只改了缓存里的文件 → 打包上传 OneDrive 并写进 `EPUB/`**

```powershell
python tools/publish.py --dry-run   # 预览
python tools/publish.py             # 执行
```

对比 `manifest.json` 只处理发生变化的书：先打包，再只把变化文件写入 `EPUB/`（缓存中删除的文件也会从 `EPUB/` 删除），最后上传到 OneDrive（每本一个 `.epub`），上传后同步更新拉取状态避免下次重复解压。

### 1. 拉取（OneDrive -> 缓存）

```powershell
./tools/pull.ps1
```

将 OneDrive 中的中文和日文 EPUB 解压到审计缓存。脚本用 `.cache/epub-work/pull-state.tsv` 记录每个 EPUB 的修改时间与大小，只解压发生变化的书籍；首次运行会全部解压一次以建立状态，之后仅处理变化的书。解压后只为被解压的书籍增量更新 `manifest.json`，未变化的书籍保持原基线。

默认读取：

- `C:\Users\<用户名>\OneDrive\某系列\X系列\EPUB` -> `.cache/epub-work/chinese-text/`
- `C:\Users\<用户名>\OneDrive\某系列\日文原文` -> `.cache/epub-work/japanese-text/`

脚本会逐本先解压到缓存内临时目录（`.extract-` 前缀），校验 `mimetype` 和 `META-INF/container.xml` 后再替换对应书目录。启动时会自动清理上次中断遗留的 `.extract-*` 临时目录。

> 编码说明：`pull.ps1` 以 **UTF-8 with BOM** 保存，确保在 Windows PowerShell 5.1 与 PowerShell Core 下都能正确解析（无 BOM 时 5.1 会按 GBK 误读导致解析失败）。改动本文件时请保留 BOM。

参数：

- `-Force`：忽略状态记录，全部重新解压
- `-SyncToEpub`：解压后调用 `publish.py --sync-only`，把变化文件增量同步到 `EPUB/`（流程 A）
- `-WhatIf`：只预览将解压/跳过的书，不写入
- `-Side chinese` / `-Side japanese`：只处理一侧
- `-Pattern '*S2_14*'`：按书名筛选
- `-ChineseSourceDirectory` / `-JapaneseSourceDirectory` / `-CacheDirectory` / `-EpubDirectory`：覆盖路径

### 2. 修改缓存（Agent 或手动）

使用 agent 或手动修改 `.cache/epub-work/` 中的文件。可先运行 `python tools/normalize_epub_cache.py` 按统一固定行模板规范化缓存，再用 `python tools/check_alignment.py` 检查模板与中日对齐。

### 3. 发布（缓存 -> 打包 + OneDrive + EPUB/）

```powershell
python tools/publish.py --dry-run    # 预览变更
python tools/publish.py              # 执行发布
```

对比 `manifest.json` 检测自上次拉取以来哪些文件被修改、新增或删除，只处理受影响的书籍：

1. **重新打包**受影响的书籍为 `.epub`（输出到 `.cache/epub-work/packed-epubs/`）；打包失败不会改动 `EPUB/`
2. **中文变更**只把发生变化的文件写入 `EPUB/`（包含缓存中已删除文件的删除；`--force` 时才整本全量重建）
3. **上传**到 OneDrive 对应目录（中文 -> `某系列\X系列\EPUB`，日文 -> `某系列\日文原文`），并同步更新 `pull-state.tsv`
4. **更新清单**，记录已成功发布的书籍状态

可用参数：

- `--side chinese` / `--side japanese`：只处理一侧
- `--pattern "*S1_01*"`：按书名筛选
- `--sync-only`：只同步 `EPUB/` 并更新清单，不打包不上传（流程 A 内部使用）
- `--only-books "chinese-text/[S1_01]...,japanese-text/..."`：只处理列出的书（逗号分隔）
- `--force`：忽略清单，处理所有文件（首次发布或全量重建）
- `--no-upload`：跳过 OneDrive 上传，仅同步 EPUB/ 并打包
- `--dry-run`：仅预览，不执行任何操作

发布失败的书籍不会更新清单，下次运行时会自动重试。

若需要让全部中文缓存与项目 `EPUB/`、以及两侧 OneDrive 打包文件重新建立一致，使用 `python tools/publish.py --force`；该命令会重建并覆盖全部书籍的 EPUB，执行前应先确认缓存就是预期发布源。

### 哈希清单工具

```powershell
python tools/manifest.py                             # 重新生成清单（全量）
python tools/manifest.py --update-books chinese-text/[S1_01]...   # 只刷新指定书籍
python tools/manifest.py --cache path                # 指定缓存目录
```

`manifest.py` 扫描 `chinese-text/` 和 `japanese-text/` 下所有文件，计算 SHA-256 哈希并写入 `manifest.json`。`pull.ps1` 在解压后只对解压的书籍增量刷新清单；`--update-books` 保留其余书籍的基线不变，避免吞掉缓存中尚未发布的修改。

### 初始设置或全量重建 EPUB/

```powershell
./tools/pull.ps1
python tools/publish.py --force --no-upload
```

`pull.ps1` 把 OneDrive 的 EPUB 解包到缓存并建立清单；`publish.py --force --no-upload` 忽略清单把全部中文书籍从缓存全量重建到 `EPUB/` 并打包，跳过 OneDrive 上传。不要直接解包 OneDrive 的 `.epub` 到 `EPUB/`，那会绕过清单与规范化流程。

### 打包工具（CI 和手动使用）

```powershell
python tools/package_cache_epubs.py
```

`publish.py` 内部调用此模块的打包函数。`package_cache_epubs.py` 也可独立运行，默认读取 `.cache/epub-work/japanese-text/` 和 `chinese-text/`，输出到 `.cache/epub-work/packed-epubs/` 下对应的语言目录。生成的 EPUB 会将根目录 `mimetype` 作为第一个未压缩条目，并压缩其余内容。可使用 `--side japanese` 或 `--side chinese` 只打包一侧，使用 `--pattern "*S3_11*"` 筛选书名，使用 `--dry-run` 仅预览输出。

GitHub Release 从版本化的 `EPUB/` 目录直接打包时，使用显式源目录和输出目录：

```powershell
python tools/package_cache_epubs.py --source EPUB --output output/epubs
```

直接源目录模式会把每个书籍目录打包到同一个输出目录，并沿用相同的 EPUB 结构校验与 `mimetype` 首项规则。`--source` 必须与 `--output` 一起使用，且不能与 `--side` 组合。

### 缓存规范化（统一固定行模板）

```powershell
python tools/normalize_epub_cache.py            # 应用规范化
python tools/normalize_epub_cache.py --dry-run  # 只预览，不写文件
```

只处理 `.cache/epub-work/`，不修改 `EPUB/` 源文件。按统一固定行模板（见文首）重建文件头部：

- 头部标签跨行折叠为一行；填充 `<br/>` 删除；跨行 h1/h2 折叠为单行；
- 日文 p 型标题（`font-1em10/30`、裸 `<p>あとがき/译注` 等）转为 `<h1>`；
- 数字小节 `<p>N</p>` 转为 `<h2>`；`start-3em/start-5em` 容器内嵌标题按语义重建为独立 `<h1>`；
- 中文包装页（Information/Note/Introduction 等）头部行内的 h1 提取到第 4 行；
- 中文 Note 等列表型包装页的 `<ul>`/`<ol>` 包装行不视为正文，放入第 5 行（h2 空位），使第一条注释从第 6 行开始；
- 中文 Note 等列表型包装页中 `<p>` 包裹 `<li>` 的写法会剥离 `<p>`，让 `<li>` 直接作为列表项；
- 篇首图片并入第 3 行头部行；SP 篇目日文侧补 `<h1>`（标题取自日文原版目录）；
- 中日配对文件两侧行数必须一致：任一侧无法套用模板或会造成行数不对称时，该对跳过并报告。

已知跳过项（内容级特例，需人工处理）：`S1_25-Stiyl_Magnus`（已手工完成模板对齐并修复原文件缺 `<body>` 的 XML 缺陷，跳过以免重建破坏手工对齐）。

### 对齐检查（只读）

```powershell
python tools/check_alignment.py
```

逐文件检查模板符合性（L1-L3 头部结构、L4=h1 独占或空、L5=h2 独占或空（中文 Note 等包装页可为 `<ul>`/`<ol>` 列表包装占位）、L6=正文），并对中日配对文件检查总行数一致、h2 位置一致、图片行一致（`gaiji`/`height-2em` 内嵌字形不计；`S2_14-04/07/10/13` 为已确认的文本化图片例外）。报告写入 `.cache/epub-work/alignment-check.tsv`。纯图片页/无正文页不适用；仅单侧存在的 EPUB、日文独有包装页不参与。

### 中日图片内容对应检查（只读）

```powershell
python tools/compare_epub_images.py
python tools/compare_epub_images.py --pattern "*S1_01*"
```

扫描 `.cache/epub-work/chinese-text/` 和 `japanese-text/` 中按作品号配对的 EPUB，读取 XHTML 图片引用并检查全部图片资源。报告写入 `.cache/epub-work/image-comparison/report.json` 和 `report.md`；`--output` 可指定其他目录。

判定分层如下：

- `name_rule_same_content`：文件名族和稳定位置规则同时成立，例如 `Cover ↔ cover`、`Back_cover ↔ hyou4`、`Contents ↔ toc-*`、`Deputy_cover ↔ kuchie-001`、`IllustrationsN ↔ kuchie-(N+1)`。正文图片还会识别 `i-NNN`、`i-NNN-NNN`、`pNNN-pNNN` 及旧日文 `p000-00-XX-1` 格式；两侧正文编号相同且图片宽高比类别相同（单页/双页）时，直接按编号视为对应，不要求 XHTML 图片槽位相同。中文双页范围（如 `i-232-233`）也会和日文两张连续单页（`i-232` + `i-233`）合并记录。其余旧 `pN` 与 `p000-00-XX-1` 仍使用共同表头/槽位规则，避免把源页码误当成中文序号；
- `exact_bytes_*`：SHA-256 完全相同，可能只是文件名不同；
- `decoded_pixels_*`：缩放后像素和感知哈希高度一致，通常是重新编码/缩放后的同图；
- `possible_same_content`：结构相似但颜色/灰度渲染差异较大，需人工确认；
- `possible_same_content_text_or_font_changed`：整体结构和颜色相似，可能只替换了文字或字体，必须人工查看原图；
- `layout_mismatches`：两侧正文文件名编号相同，但宽高比分别判为单页和双页。此类图片不会自动计入匹配，优先人工检查是否发生插图换序；报告同时输出像素尺寸和文件路径。
- 未匹配清单：一侧存在而另一侧没有算法对应项的图片，包含未被 XHTML 引用的资源。

脚本需要 Pillow 的缩略图指标；在同时安装 [`ImageHash`](https://github.com/JohannesBuchner/imagehash) 时还会启用 pHash、dHash、wHash 和 colorhash，未安装 ImageHash 时自动使用 Pillow 回退：

```powershell
python -m pip install Pillow ImageHash
```

感知匹配只输出候选，不替代视觉确认；报告同时保留图片尺寸、SHA-256、引用 XHTML、表头和规则位置键。文件名规则只在同一作品内生效，不会跨书猜测。

### 空占位页清理

```powershell
python tools/fix_empty_placeholders.py
python tools/fix_empty_placeholders.py --apply
```

仅把“位于两个编号文件之间、正文无文本且无图片/SVG”的 XHTML 视为空占位页；应用后会删除该页，并将同目录后续文件的表头序号及数字页码后缀依次前移。默认只扫描，不修改缓存。注意与模板中的“空行占位”区分：本工具处理的是空占位**页**（整个文件无内容），模板空行是正文文件内部的第 4/5 行占位。

### Note 注释顺序检查（只读）

```powershell
python tools/check_note_order.py
python tools/check_note_order.py --pattern "*S1_01*"   # 按书名筛选
```

检查中文缓存 `*.Note.xhtml`（译注页）中的 `<li id="noteN">` 条目顺序与编号是否和正文 `epub:type="noteref"` 首次引用顺序一致。正文文件按表头内容序排序后逐行扫描，取每个注释 id 的首次引用位置作为“书中出现顺序”；包装页（Cover/Information 等）不参与。

报告以下问题：Note 列表顺序 != 正文首次出现顺序、正文引用但 Note 未定义、Note 已定义但正文未引用（孤儿注释）、id 数值顺序乱序（含 `note2.1` 这类补充编号）。报告写入 `.cache/epub-work/note-order-check.md` 与 `note-order-check.json`。只读，不修改缓存。

可用参数：`--cache` 指定中文缓存根目录（默认 `.cache/epub-work/chinese-text`）、`--output` 指定报告输出目录、`--pattern` 按书名子串筛选（支持 `*` 通配）。

### Note 注释顺序重排（写缓存，自动备份）

```powershell
python tools/reorder_notes.py --dry-run          # 预览
python tools/reorder_notes.py                    # 执行
python tools/reorder_notes.py --pattern "*S2_07*" # 按书名筛选
```

按正文 `epub:type="noteref"` 首次出现顺序重排 `*.Note.xhtml` 的 `<li>` 条目并重编号为 `note1..noteN`，同时单遍映射更新正文所有引用。写盘前会把涉及文件备份到 `.cache/reorder-backup/`；`--dry-run` 只打印旧顺序/新顺序/映射，不写盘。

自动跳过两类情况（需人工处理）：Note 文件含非注释 `<li>`（如 S0_00 的说明条目）、定义集合与引用集合不一致（孤儿/悬空引用）。可与 `tools/check_note_order.py` 配合：先用检查工具确认问题，再用本工具重排。

可用参数：`--cache` 指定中文缓存根目录、`--backup` 指定备份目录、`--pattern` 按书名子串筛选（支持 `*` 通配）。

### 术语审计

```powershell
python tools/epub_audit.py
```

读取日文缓存与项目内中文 EPUB，对比中日译法差异，报告写入 `.cache/epub-work/report.json` 与 `report.md`。只读，不提供重建或覆盖缓存的功能。

默认读取 `.cache/epub-work/japanese-text/` 和项目内 `EPUB/`；其中日文缓存只有在刚运行 `pull.ps1` 后才是原样解压快照，规范化或校对后以工作源状态为准。如需保留原样快照，请先拉取到临时缓存；如需读取其他中文目录，使用 `--cn`。

生成内容位于 `.cache/epub-work/`：

- `japanese-text/`：日文 EPUB 工作缓存；刚由 `pull.ps1` 生成时保留 EPUB 原样目录、文件名、标签和换行，规范化后允许按规约折叠排版包装
- `report.json`：机器可读的逐条命中记录
- `report.md`：按卷汇总的中文译法差异及上下文

`.cache/epub-work/` 已加入 `.gitignore`，不会提交到 GitHub。

定位命中内容时，直接打开 `japanese-text/<卷>/` 下对应的原始 XHTML 文件。报告中的上下文仅用于快速检索，不替代原始文件行号。
