# EPUB 维护工具

本文只说明工具入口、参数、数据流和可验证行为。作品编号、文件命名、固定行模板及 Agent 操作边界以仓库根目录 `AGENTS.md` 为唯一规范来源；下文出现的规则摘要用于解释命令效果，不另立一套规则。

## 工作流程图（按处理阶段）

本工具集按照明确的职责分工处理 EPUB 文件，每个工具负责一个独立的处理阶段：

### 阶段 0：拉取与编辑准备
```
OneDrive EPUB → pull.ps1（增量解压）→ .cache/epub-work/（工作缓存）
```
- **工具**：`pull.ps1`
- **职责**：从 OneDrive 增量拉取变化的 EPUB 到本地缓存
- **输出**：`.cache/epub-work/chinese-text/` 和 `japanese-text/` 解包目录

### 阶段 1：BookWalker 源文件预处理（仅限新书导入）
```
bw 原始 EPUB → bw_preprocess.py（清理噪声 + 建立 L1-L5 分页模板）→ 预处理后分页目录
```
- **工具**：`bw_preprocess.py`
- **职责**：清理 BookWalker 特有排版噪声，并把正文页头部折叠到 L3、章节/小节重建为 L4/L5 的 `h1/h2`
- **输入**：BookWalker 解包的原始分页 EPUB
- **输出**：`<原名>.preprocessed.epub` 或就地改写的目录
- **边界**：只建立分页合并器所需的固定槽位；最终文件命名、中日配对和完整规范化仍在后续阶段完成

### 阶段 2：分页合并为章节文件（仅限新书导入）
```
预处理后分页 → merge_bw_pages.py（按 h1 合并 + 跨页衔接）→ 规范化章节文件 ✅
```
- **工具**：`merge_bw_pages.py`
- **职责**：按章节标题合并分页，处理跨页间隔（文本+文本插入 1 行换页标记 `<div style="break-after: page;"></div>`、跨图无缝）
- **输入**：`bw_preprocess` 处理后的分页目录
- **输出**：`<book>-NN.xhtml` 规范化章节文件（已套用 L1-L6 模板）✨
- **检测**：页首/页尾残留 `<br/>`（若有则报告警告）
- **说明**：v2 版本已增强，直接输出符合固定行模板的文件，可选使用 `normalize_single.py` 进行精细化处理

### 阶段 3：模板规范化

```
临时文件/缓存文件 → normalize_single.py（单文件规范化）→ 规范化缓存
                   → normalize_paired.py（配对批量处理）→ 规范化缓存
```

#### normalize_single.py - 定向单文件/目录规范化

**用途**：独立规范化单个或批量文件，**不依赖中日配对**

```powershell
# 单文件处理
python tools/normalize_single.py 文件.xhtml

# 批量处理目录
python tools/normalize_single.py --dir .cache/epub-work/japanese-text/某书/OEBPS/Text/
python tools/normalize_single.py --dir 目录/ --pattern "*.xhtml" --dry-run

```

- **职责**：统一套用固定行模板（头部折叠、标题提取、h1/h2 重建）
- **输入**：任何 XHTML 文件（日文或中文，单独或批量）
- **输出**：符合 L1-L6 模板的规范化文件（就地改写）
- **优点**：
  - ✅ 不需要中日配对即可处理
  - ✅ 适用于新导入日文书、修复手动编辑、历史文件处理
  - ✅ 可用于 `merge_bw_pages` 输出的兜底规范化

#### normalize_paired.py - 中日配对批量规范化（缓存主入口）

**用途**：中日配对批量规范化，依赖配对关系

```powershell
python tools/normalize_paired.py --dry-run
python tools/normalize_paired.py
```

- **职责**：遍历 `.cache/epub-work/` 下的中日配对书籍，批量规范化
- **约束**：
  - ⚠️ 只处理有中日配对的文件
  - ⚠️ 单独导入的日文书会被跳过
- **说明**：配对文件只有在两侧均可重建且重建后行数相同时才写入；`normalize_epub_cache.py` 是本入口的兼容别名。

---

**工作流位置（新架构）**：
```
阶段 1：bw EPUB → bw_preprocess（清理噪声 + L1-L5 分页模板）→ 预处理分页
阶段 2：预处理分页 → merge_bw_pages（合并章节）→ 接近规范的文件
阶段 3a：已配对缓存 → normalize_paired.py → 成对规范化并保持行数约束
阶段 3b：明确指定的单文件/目录 → normalize_single.py → 独立规范化
阶段 4：规范化文件 → check_alignment.py（质检）
```

两个入口共享 `xhtml_template.py` 的同一套模板重建规则；差别只在编排策略，避免规则漂移。

### 阶段 4：中日对齐与重命名（人工）
```
规范化缓存 → 人工对齐 + 重命名（临时序号 → 最终表头）→ 对齐后缓存
```
- **操作**：人工核对中日文件对应关系
- **任务**：
  1. 将临时序号文件 `<book>-NN.xhtml` 重命名为 `<表头>-<内容序>_<语义后缀>.xhtml`
  2. 确保中日两侧同位置文件的视觉间隔数量一致
  3. 更新 OPF/NCX/nav 元数据中的文件引用

### 阶段 5：质量检查
```
对齐后缓存 → check_alignment.py（模板与对齐检查）→ 报告
            → check_translation_spec.py（翻译规范检查）→ 报告
            → check_note_order.py（注释顺序检查）→ 报告
```
- **工具**：`check_alignment.py`、`check_translation_spec.py`、`check_note_order.py` 等
- **职责**：只读检查，不修改文件
- **输出**：`.cache/epub-work/` 下的检查报告（TSV/JSON/Markdown）

### 阶段 6：发布
```
缓存改动 → publish.py（增量同步 + 打包 + 上传）→ EPUB/ + OneDrive
```
- **工具**：`publish.py`
- **职责**：检测缓存变更，只处理变化的书籍和文件
- **流程**：
  1. 对比 `manifest.json` 检测变更
  2. 中文变更增量写入 `EPUB/`（含删除传播）
  3. 打包为 `.epub`（输出到 `.cache/epub-work/packed-epubs/`）
  4. 上传到 OneDrive 并更新 `pull-state.tsv`
- **反向流程**：若直接修改了 `EPUB/`，用 `publish_epub.py` 回流到 OneDrive 和缓存

### 特殊流程：交稿文件处理
```
docx 交稿 → docx2epub.py（|基文[注音] → <ruby>）→ X版 EPUB
X版 EPUB → epub2docx.py（<ruby> → |基文[注音]）→ 交稿 docx
```
- **工具**：`docx2epub.py`（正向）、`epub2docx.py`（反向）
- **职责**：交稿格式与成品格式互转
- **注意**：这两个工具独立于主工作流，用于交稿管理

---

## 共享规则模块与测试

以下文件是供命令行工具复用的内部模块，不是独立工作流入口：

- `epub_ids.py`：作品号、表头、内容序和包装页角色解析；历史异常只接受明确别名，不做模糊配对。
- `alignment_rules.py`：人工确认的非配对作品、手工对齐表头、文本化图片和 SP 标题例外。
- `xhtml_template.py`：固定行模板的纯重建规则；由两个 normalize 入口共同调用。
- `notes_core.py`：Note 条目解析、正文引用收集和阅读顺序。
- `sync_core.py`：清单差异、文件增量镜像和 `pull-state.tsv` 更新。

修改上述共享规则或其调用方后运行：

```powershell
python -m unittest discover -s tools/tests -p "test_*.py" -v
```

---

## 正文行结构规范（统一固定行模板）

中日两侧带正文的 XHTML 使用统一固定行模板：

```
1  <?xml …?>
2  <!DOCTYPE html>
3  <html …><head>…</head><body…>   ← 可并入篇首图片（body 开头）
4  <h1>…</h1>                      ← 独占行；无 h1 则空行
5  <h2>…</h2>                      ← 独占行；无 h2 则空行（中文列表型包装页可为 <ul>/<ol>）
6  <p>正文首行</p>                 ← 永远在第 6 行
```

- **L4（h1 槽位）**：`<h1>` 外层标题块独占行（开标签+内容+闭标签同行），或空行占位（不得用 `<br/>` 占位）。标题内部可以保留 `ruby`、`span`、`sup` 等行内语义标签，但不得使用 `<br/>` 或 `div`/`p` 块级包装。
- **L5（h2 槽位）**：`<h2>` 外层标题块独占行（开标签+内容+闭标签同行），或空行占位；标题内部约束与 h1 相同。
  - **列表型包装页例外**（中文 Note、Introduction 等）：若该文件没有 h2，允许 `<ul>`/`<ol>` 列表包装开标签独占 L5，语义上等价于"结构占位"（不是标题行），第一条列表项 `<li>` 从第 6 行开始。
  - 日文包装页不适用列表占位规则（保持原样快照）。
- 同一文件中日两侧的 h1/h2/独立 `<br/>` 行位置一一对应；总行数一致。`S2_14-04/07/10/13` 的图片文本化页面是已确认例外。
- 正文区每条物理行只能有一个同级顶层块。`<p>…</p><p>…</p>`、正文后直接拼 `<hr/>`、`</body>` 或 `</html>` 都会被视为原子性错误；一对多段落只能在语义确认后真正合并为一个 `<p>`，不能靠删除换行凑总行数。
- `python tools/check_alignment.py --strict` 在发现模板、原子性或配对问题时返回非零状态；普通模式仍生成完整报告并返回成功，便于人工审计。
- 纯图片页、无正文页、日文独有包装页（原样快照）不适用。

### 历史多层标题迁移

- 标题末尾没有后续内容的 `<br/>` 是排版噪声，可以直接删除。
- 分隔主标题、副标题、英文题名或特殊编码的 `<br/>` 是视觉结构，不能简单删除。规范形式是在同一物理行内使用 `heading-main`、`heading-subtitle`、`heading-code` span 表达各层，并由 `.heading-lines > … { display: block; }` 在该书 CSS 中恢复视觉分行。
- 迁移以整本书为原子：同步处理该书全部同类标题和 CSS，按层验证可见文本、顺序与字号语义，再检查阅读器显示。NCX/nav 现有标签不随 XHTML 格式化而改写。

先预览，再显式写入中文缓存：

```powershell
python tools/migrate_heading_breaks.py
python tools/migrate_heading_breaks.py --apply
```

- 可用重复的 `--book GLOB` 限定书籍，`--verbose` 展示逐书统计。默认缓存是 `.cache/epub-work/chinese-text`，也可用 `--cache` 显式指定。
- 工具只迁移审计确认的结构；任一书出现未知标题结构、越界 CSS 引用或缺失样式表时，整次预检不写入。写入前会同时生成该书的 XHTML/CSS 变更计划，单书写入失败时回滚已写文件。
- `normalize_paired.py` 和 `normalize_single.py` 不承担历史语义分层；迁移完成后，`check_alignment.py --strict` 会阻断 h1/h2 内嵌 `<br/>`、`div`/`p` 块级包装和跨行标题，防止旧结构回流。
- 2026-09-01 的数量、分类和迁移验收步骤见 `docs/maintenance-records/h1-inline-br-audit-2026-09-01.md`。

### 正文文件结构（引子与尾声）

- 序章（`Prologue`）之前的内容，无论页数多少，只写为一个文件「引子」，语义后缀用 `Before_the_Prologue`；不得按量拆分或并入 `Prologue` 文件。
- 后记（`Afterwords`）之后的内容，无论页数多少，只写为一个文件「尾声」，语义后缀用 `After_the_Epilogue`。
- 判定以表头内容序为准：引子位于第一个 `Prologue` 之前，尾声位于第一个 `Afterwords` 之后。该位置规则与 `epub_char_count` 的成分名规范化（第一个「序章」前的成分 → 引子、第一个「后记」后的成分 → 尾声）一致。
- 数字内容序统一从 `-01` 开始，`-00` 为验证错误。`docx2epub` 在首章为 `Prologue` 时会把此前无标题正文自动生成为 `-01_Before_the_Prologue.xhtml`，后续章节依次顺移；其他首章前文本仍并入首章。

### 换页衔接处理（跨页文件合并）

分页源（BookWalker 等）合并为章节文件时，按衔接处两侧的页型决定间距：

- **文本 + 图片 + 文本**（3 页，跨整页插图）：无缝衔接，图片行直接夹在两段文本之间，前后不插入 `<br/>`：

  ```html
  <p>…文本…</p>
  <p><img …/></p>
  <p>…文本…</p>
  ```

- **文本 + 文本**（连续两页正文）：在前一页末尾段落追加 `class="pb"`，不插入额外空白行：

  ```html
  <p class="pb">…前一页末段…</p>
  <p>…下一页首段…</p>
  ```

- 若前一页末段与后一页首段是同一段落的断续，先按原文语义拼回完整段落，不再套用换页标记；页首/页尾的填充 `<br/>` 属排版噪声，合并时删除，不得残留残缺行。
- 整页无文本且无图/SVG 的空占位页删除并前移后续文件序号（见「空占位页清理」）。
- 全页插图页（SVG 或 `body.p-image`）保留为图片行，随归属章节合并；中日两侧同一位置的换页标记数量一致（见「对齐检查」）。

## 拉取与发布流程

三处中文文件副本各有固定角色，不得互相替代：

- `.cache/epub-work/`（解包工作区，不提交）：唯一编辑点。`pull.ps1` 从 OneDrive 解包生成，可随时删除重建。
- `EPUB/`（解包归档，提交到 git）：版本化归档基线，diff 友好；通常由 `publish.py` 从缓存同步，也可通过 `publish_epub.py` 反向回流。它不是日常编辑点。
- OneDrive（打包 `.epub`，外部）：分发与阅读副本；是 `pull.ps1` 的输入，也是 `publish.py` / `publish_epub.py` 的上传目标。

编辑边界：

- 只在 `.cache/epub-work/` 中编辑。直接修改 `EPUB/` 不会同步回 OneDrive，因为 `publish.py` 只读取缓存。
- 若确实直接改了 `EPUB/`，可用 `publish_epub.py`（流程 C）把改动打包上传 OneDrive 并增量覆盖回缓存；这是唯一把 `EPUB/` 改动回流到 OneDrive 与缓存的正规路径。运行前务必 `--dry-run` 预览。
- 不得直接修改 OneDrive 中的 `.epub`。若已修改，切勿在发布前运行 `pull.ps1`，否则 OneDrive 的改动会被当作新基线拉入缓存，覆盖缓存中的编辑。
- 缓存中的改动必须经 `publish.py` 才会同步到 `EPUB/` 和 OneDrive。发布后中文缓存与 `EPUB/` 逐字节一致属预期行为。
- `.cache/` 可丢弃：删除后运行 `./tools/pull.ps1` 即可完整重建。

### 三种常用工作流（均增量处理，不做全量写入）

**流程 A：OneDrive 已有外部变更 → 拉回缓存并写进 `EPUB/`**

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

实际发布会先自动运行严格对齐检查；只要 `alignment-check.tsv` 仍有问题，就会在打包、同步或上传前停止。`--dry-run` 只预览变更，不触发该门禁，因此确认发布前仍应单独运行 `python tools/check_alignment.py --strict`。

**流程 C：只改了 `EPUB/` 里的文件 → 打包上传 OneDrive → 增量覆盖回缓存**

```powershell
python tools/publish_epub.py --dry-run   # 预览
python tools/publish_epub.py             # 执行
```

对比 `manifest.json` 只处理发生变化的书：对每本受影响的（中文）书，先从 `EPUB/` 书籍目录打包 `.epub`，上传到 OneDrive 并同步更新拉取状态，再把变化文件增量覆盖进缓存（缓存中删除的文件也会从缓存删除）。未变化的书和文件完全不碰。`EPUB/` 只镜像中文书，因此本流程只处理中文侧。

### 1. 拉取（OneDrive -> 缓存）

```powershell
./tools/pull.ps1
```

将 OneDrive 中的中文和日文 EPUB 解压到审计缓存。脚本用 `.cache/epub-work/pull-state.tsv` 记录每个 EPUB 的修改时间与大小，只解压发生变化的书籍；首次运行会全部解压一次以建立状态，之后仅处理变化的书。解压后只为被解压的书籍增量更新 `manifest.json`，未变化的书籍保持原基线。只有清单更新或 `-SyncToEpub` 同步成功后才推进 `pull-state.tsv`；下游失败会返回非零并保留重试条件。

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

使用 agent 或手动修改 `.cache/epub-work/` 中的文件。中日配对缓存使用 `python tools/normalize_paired.py`；只处理明确指定文件时使用 `python tools/normalize_single.py`。随后用 `python tools/check_alignment.py` 检查模板与中日对齐。

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

默认发布要求对应 OneDrive 目录已经存在；目录缺失会在打包、镜像前失败，不会再被当成“跳过上传但发布成功”。只需本地操作时必须显式使用 `--no-upload` 或 `--sync-only`。

若需要让全部中文缓存与项目 `EPUB/`、以及两侧 OneDrive 打包文件重新建立一致，使用 `python tools/publish.py --force`；该命令会重建并覆盖全部书籍的 EPUB，执行前应先确认缓存就是预期发布源。

### 4. 反向发布（`EPUB/` -> OneDrive + 缓存，流程 C）

```powershell
python tools/publish_epub.py --dry-run    # 预览变更
python tools/publish_epub.py              # 执行反向发布
```

与 `publish.py` 方向相反：检测 `EPUB/` 相对 `manifest.json` 的变化（新增/修改/删除），只处理受影响的中文书，逐本：

1. **打包** `EPUB/` 书籍目录为 `.epub`（输出到 `.cache/epub-work/packed-epubs/`）；打包失败不会改动缓存与 OneDrive
2. **上传**到 OneDrive（`某系列\X系列\EPUB`），并同步更新 `pull-state.tsv`，避免下次 `pull.ps1` 把旧的 OneDrive 文件拉回覆盖缓存
3. **增量覆盖**变化文件进缓存 `.cache/epub-work/chinese-text/`（缓存中已删除的文件也会删除），未变化的文件不碰
4. **更新清单**，记录已成功反向发布的书籍状态

可用参数：

- `--pattern "*S1_01*"`：按书名筛选
- `--only-books "chinese-text/[S1_01]..."`：只处理列出的书（逗号分隔）
- `--force`：忽略清单，把 `EPUB/` 全部视为变更，按整本全量重建缓存
- `--no-upload`：跳过 OneDrive 上传，仅增量覆盖缓存并更新清单（OneDrive 未变，下次拉取可能回拉旧内容）
- `--overwrite-cache`：允许覆盖缓存中「尚未发布」的修改（默认会跳过并报告冲突）
- `--dry-run`：仅预览，不执行任何操作

**冲突保护**：默认情况下，若某个文件在缓存中的副本与清单基线不一致（即缓存里还有未发布的修改），反向覆盖会丢失这些修改，本工具会列出冲突并跳过该书，不打包、不上传、不更新清单；确认要覆盖时用 `--overwrite-cache`，或先用 `publish.py` 把缓存修改发布掉。

> 注意：`manifest.json` 以缓存为基线且按字节哈希比较，`EPUB/` 与缓存/基线的换行符差异（如 LF vs CRLF）也会被当作变更。反向发布前请先 `--dry-run` 确认变更范围符合预期。

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
python tools/normalize_paired.py --dry-run       # 中日成对预览（缓存主入口）
python tools/normalize_paired.py                 # 中日成对应用
python tools/normalize_single.py 文件.xhtml      # 定向处理单文件
```

两个入口共享 `xhtml_template.py` 的重建实现。`normalize_paired.py` 只处理 `.cache/epub-work/` 中可确认的配对/单侧中文正文，并在成对写入前验证行数相等；`normalize_single.py` 只处理命令行明确指定的文件或目录，不保证中日对齐。两者都不修改 `EPUB/`。旧命令 `normalize_epub_cache.py` 保留为 `normalize_paired.py` 的兼容入口。

统一规则如下：

- 头部标签跨行折叠为一行；填充 `<br/>` 删除；跨行 h1/h2 折叠为单行。历史多层标题中的内嵌 `<br/>` 不得在缺少分层识别和 CSS 迁移时直接删除；
- 日文 p 型标题（`font-1em10/30`、裸 `<p>あとがき/译注` 等）转为 `<h1>`；
- 数字小节 `<p>N</p>` 转为 `<h2>`；`start-3em/start-5em` 容器内嵌标题按语义重建为独立 `<h1>`；
- 中文包装页（Information/Note/Introduction 等）头部行内的 h1 提取到第 4 行；
- 中文 Note 等列表型包装页的 `<ul>`/`<ol>` 包装行不视为正文，放入第 5 行（h2 空位），使第一条注释从第 6 行开始；
- 中文 Note 等列表型包装页中 `<p>` 包裹 `<li>` 的写法会剥离 `<p>`，让 `<li>` 直接作为列表项；
- 带 class 的 body 语义包装会保留；若其 `</div>` 原本独占尾行，则折叠到 `</body>` 行以保持模板行数。只有中文侧成对出现的裸 `<div>` / `</div>` 排版包装才会一起移除，不会单独删除可能属于 class 容器的闭标签；
- 篇首图片并入第 3 行头部行；SP 篇目日文侧补 `<h1>`（标题取自日文原版目录）；
- 中日配对文件两侧行数必须一致：任一侧无法套用模板或会造成行数不对称时，该对跳过并报告。

已知跳过项（内容级特例，需人工处理）：`S1_25-Stiyl_Magnus`（已手工完成模板对齐并修复原文件缺 `<body>` 的 XML 缺陷，跳过以免重建破坏手工对齐）。

### bw 提取预处理（BookWalker 原始 EPUB -> 清理噪声并建立分页模板）

```powershell
python tools/bw_preprocess.py 某本bw提取.epub            # 输出 某本bw提取.preprocessed.epub
python tools/bw_preprocess.py --dry-run 某本bw提取.epub   # 只预览
python tools/bw_preprocess.py --out 输出目录/ 某本bw提取.epub
python tools/bw_preprocess.py 已解包的目录/               # 就地改写目录下全部 .xhtml/.html/.htm
python tools/bw_preprocess.py --rules 自定义.rules.json 某本bw提取.epub
python tools/bw_preprocess.py --book-id S4_05 某本bw提取.epub # 为 XHTML/图片分配表头并更新引用
python tools/bw_preprocess.py --book-id S4_05 --header-map 自定义映射.json 某本bw提取.epub
python tools/bw_preprocess.py --book-id S4_05 --check 某本bw提取.epub # 完整产物校验，不写盘
```

对 BookWalker 解包后的原始 XHTML 应用查找/替换规则集，清理排版噪声，并建立 `merge_bw_pages.py` 所依赖的 L1-L5 固定槽位。

**本工具职责**（v3）：
- ✅ 正文页头部折叠为 L1-L3；无标题页补 L4/L5 空槽，保证正文从 L6 开始
- ✅ `start-3em` / `font-1em30` 章节标题转为 L4 单行 `h1`
- ✅ `start-5em` 和裸数字小节转为 `h2`；首小节放在 L5，后续小节保持正文区独占行
- ✅ 合并多段 ruby 为单段（`<ruby>学<rt>がく</rt>園<rt>えん</rt>` → `<ruby>学園<rt>がくえん</rt>`）
- ✅ `<p><br/></p>` 展平为 `<br/>`
- ✅ 页首/页尾填充 `<br/>` 删除（`<div class="main">` 后与 `</div>` 前）
- ✅ 解包排版 span（`font-1em50`、`em-sesame`→`<b>`、`tcy`、`line-break-loose` 等）

**工作流位置**：
```
bw 原始 EPUB → bw_preprocess（清理噪声 + 分页模板）→ merge_bw_pages（合并分页）→ normalize（最终规范化）
```

- 规则文件：`tools/bw_extract_preprocess.json`（v3，恢复分页合并器所需的头部折叠、标题提取和 L4/L5 槽位规则）。
- 输入 `.epub` 时解包改写后重新打包为 `<原名>.preprocessed.epub`，保留原文件、条目顺序、压缩方式与 `mimetype` 首项；输入目录时**就地**改写。
- `--book-id` 只用于已经确认作品号和内容顺序的 EPUB：第一个内容单元使用 `-01`，后续每遇到一个新的 L4 `h1` 递增内容序；无 h1 的续页和全页插图 XHTML 沿用当前表头。输出名形如 `S4_05-07_p-008.xhtml`；其他 XHTML（标准 `nav.xhtml` 除外）与全部图片加完整作品号前缀。图片保留源语义名和页码，如 `i-030.jpg` → `S4_05-i-030.jpg`，不从分页位置猜测内容序。工具同步更新 OPF、NCX、导航、XHTML、CSS 和 SVG 引用。该选项不能代替中日内容确认，不适用于目录模式。
- `tools/bw_page_header_overrides.json` 保存无法仅凭 `h1` 安全判断的已审计分页映射。映射完整列出该书全部 `p-NNN.xhtml`：正整数表示内容序，`null` 表示作品级包装页；`0`、负数或实际分页与映射不完全一致时直接阻断。`S4_05` 已确认 `p-012/p-013` 是后记作者署名之后的尾声（`-10`），`p-014/p-015` 是作者著作目录包装页，不参与正文配对。`--header-map` 可显式指定同格式文件。
- 保留原文件的 BOM 与换行风格（LF/CRLF），并把孤立 `\r`、`\r\r\n` 等脏换行归一化后再应用规则；规则按 JSON 顺序逐条执行，整体幂等（重复运行不再改写）。
- `--check` 校验模式：内存中应用完整转换但不写盘。除内容文件 L1-L6 固定模板外，配合 `--book-id` 还会模拟 XHTML/图片表头重命名，并检查 EPUB `mimetype`/`container.xml`、全部 XML 语法、XHTML/OPF/NCX/nav/CSS/SVG 内部资源引用以及无表头图片。正常处理同样执行这些门禁；有问题时返回非零并阻止写出产物。
- 页首/页尾填充清理：头部折叠规则删除 `main` 后的源排版 `<br/>` 并建立 L4/L5 槽位；「页尾填充br删除」清除最终 `</div>` 前的填充空段/`<br/>`。若 `merge_bw_pages` 仍检测到残留，会报告警告（说明规则需增强）。

### 分页源合并为章节文件（跨页衔接处理）

```powershell
python tools/merge_bw_pages.py 分页目录 --book S4_05            # 输出 <book>-NN.xhtml
python tools/merge_bw_pages.py 分页目录 --book S4_05 --dry-run   # 只预览
python tools/merge_bw_pages.py 分页目录 --book S4_05 --out 输出目录/
```

把 `bw_preprocess.py` 处理后的分页目录（`p-NNN.xhtml`，或 `--book-id` 生成的 `S4_05-07_p-NNN.xhtml`）按章节标题（`<h1>`）合并为章节文件，落实 AGENTS.md「换页衔接处理」。带表头分页会保留原内容序；`-00`、作品号混用、同单元表头冲突或重复内容序会阻止写盘：

- **页边界按衔接处两侧页型定间距**：文本+文本（连续两页正文）插入 1 行换页标记（独占一行的 `<div style="break-after: page;"></div>`）；跨整页插图（页边界行含 img/image/svg）无缝衔接、前后不插 `<br/>` 或换页标记。
- **全页插图页**（`body.p-image` / SVG）保留为图片行，并入其前一章节单元末尾（无缝）；SVG 折叠为单行。
- **引子**：第一个 `<h1>` 之前的无标题页合并为独立「引子」单元（L4/L5 空行占位）。
- **空占位页**（无文本无图）跳过并报告。
- **页首/页尾 `<br/>` 残留检测**：合并时检测页首/页尾是否有残留填充 `<br/>`（应由 `bw_preprocess` 清理），若发现则报告警告并删除；小节/章节标题（`<h1>/<h2>`）边界的页边界不套换页标记（标题自带分隔），并输出「标题边界」待核对。
- 输出**待人工确认清单**：文本+文本页边界是否同一段落断续（须按语义拼回、勿套换页标记）、标题边界、全页插图归属是否应调整、预处理残留的 `<br/>`。

`process_split_pages.py` 是保留用于复现旧产物的兼容入口，会在运行时打印警告；新导入不得与本流程混用。

#### 输出文件命名与后续处理

推荐流程先由 `bw_preprocess.py --book-id` 给分页建立稳定表头；`merge_bw_pages.py` 会直接保留该内容序，并要求它从 01 开始，不得再按合并单元重排。只有未带表头的历史 `p-NNN.xhtml` 输入才回退为 01 起的临时顺序号。合并文件仍需在中日内容确认后补语义后缀，形成 `<表头>_<语义后缀>.xhtml`。

**重命名规则表**（以 S4_05 为例）：

| 带表头分页 | 合并输出 | 最终文件名示例 | 说明 |
|------------|----------|----------------|------|
| S4_05-01_p-001.xhtml | S4_05-01.xhtml | S4_05-01_Before_the_Prologue.xhtml | 序章前的无标题正文是引子，占首个内容序 01 |
| S4_05-02_p-002.xhtml | S4_05-02.xhtml | S4_05-02_Prologue.xhtml | 序章占内容序 02 |
| S4_05-03_p-003.xhtml | S4_05-03.xhtml | S4_05-03_Chapter1.xhtml | 第一章占内容序 03 |
| S4_05-09_p-011.xhtml | S4_05-09.xhtml | S4_05-09_Afterwords.xhtml | 后记独立成单元 |
| S4_05-10_p-012.xhtml、p-013 | S4_05-10.xhtml | S4_05-10_After_the_Epilogue.xhtml | 后记作者署名之后的正文聚合为尾声 |

**重命名要点**：
1. **内容序从 01 起**：引子若参与配对就占内容序 01，序章及后续单元依次顺移；不得生成或保留 00。
2. **语义后缀规则**：
   - 引子（第一个 Prologue 之前）→ `Before_the_Prologue`
   - 序章 → `Prologue`
   - 普通章节 → `Chapter1`, `Chapter2`, ...
   - 行间 → `Between_the_Lines1`, `Between_the_Lines2`, ...
   - 终章 → `Epilogue`
   - 后记 → `Afterwords`
   - 尾声（第一个 Afterwords 之后）→ `After_the_Epilogue`
3. **中日对齐**：按日文侧临时文件的内容和位置，匹配中文侧对应文件，确定最终内容序后统一重命名。中日两侧同一位置的视觉间隔数量须一致（本工具只合并日文分页，中文侧对齐时按日文间隔数对齐）。
4. **OPF/NCX/nav 更新**：重命名后需同步更新 EPUB 元数据文件中的文件引用。

既有作品需要整体顺移内容序时，使用 `shift_content_sequences.py`，不要逐个替换导致相邻序号级联覆盖。工具默认预览，写入时会同步更新 XHTML、OPF、NCX、nav、CSS、SVG 和 XML 引用；若旧目录仍引用裸 `p-NNN.xhtml`，仅在目录中不存在同名真实文件且目标唯一时修复为新表头文件名，歧义情况保持不动并交由资源引用验证报告：

```powershell
python tools/shift_content_sequences.py 解包书籍目录 --work-id S4_05 --offset 1
python tools/shift_content_sequences.py 解包书籍目录 --work-id S4_05 --offset 1 --apply
```

### EPUB → DOCX（交稿格式，ruby 还原为 |基文[注音]）

```powershell
python tools/epub2docx.py 某书.epub
python tools/epub2docx.py 解包的书目录/                      # 目录会先打包再转换
python tools/epub2docx.py --out 输出目录/ 书1.epub 书2.epub
python tools/epub2docx.py --pattern "*S1_01*" EPUB/          # 批量（按书名 glob 筛选）
python tools/epub2docx.py --dry-run 某书.epub                # 只统计 ruby 改写，不生成 docx
python tools/epub2docx.py --keep-src-epub 某书.epub          # 保留中间 .ruby.epub
```

调用本机 calibre 的 `ebook-convert` 完成 EPUB→DOCX 转换；转换前先把成品 EPUB 中的
`<ruby>基文<rt>注音</rt></ruby>` 反向还原为《翻译与修嵌规范》交稿层面的注音记号
`|基文[注音]`（成品里已由该记号转为 `<ruby>`，本工具做反向还原，便于取回交稿稿）。

- 只改写含 `<ruby>` 的 XHTML：块内 `<rt>` 拼接为注音、`<rp>` 丢弃、无 `<rt>` 时只留基文；
  块外字节原样保留（含 BOM、CRLF、条目顺序与压缩方式），支持嵌套 ruby。
- 输入 `.epub` 直接处理；输入解包书目录先按 `package_cache_epubs` 同款规则打包。
- docx 默认输出在输入同目录（用 `--out` 指定）；中间 `.ruby.epub` 默认用后即删。
- 依赖：本机安装 calibre（自动探测 `ebook-convert`，可用 `--ebook-convert` 覆盖）；
  额外转换参数用 `--extra` 透传（如 `--extra --docx-page-size=A4`）。

### DOCX → EPUB（交稿稿 -> X 版特色成品）

```powershell
python tools/docx2epub.py 某稿.docx
python tools/docx2epub.py --out 输出目录/ 书1.docx 书2.docx
python tools/docx2epub.py 交稿目录/ --pattern "*S1_01*"      # 批量（按文件名 glob 筛选）
python tools/docx2epub.py --series S4 --volume 06 未带编号.docx  # 文件名不含 [S..] 表头时
python tools/docx2epub.py --title 书名 --author 作者 --language zh-CN 稿.docx
python tools/docx2epub.py --images-from 日文原版.epub --cover 封面.jpg 稿.docx
python tools/docx2epub.py --unpacked 解包目录/ 稿.docx       # 同时输出解包目录
python tools/docx2epub.py --dry-run 稿.docx                  # 只统计，不生成
```

`epub2docx.py` 的反向：把交稿 .docx 转成 X 版特色成品 EPUB。正文中的
`|基文[注音]` 交稿记号还原为 `<ruby>基文<rt>注音</rt></ruby>`，正文文件套用
统一固定行模板（L1-L6，LF 无 BOM），并按 X 版命名规范生成
`<表头>-<内容序>_<语义后缀>.xhtml` 与 mimetype / container.xml / content.opf /
nav.xhtml / toc.ncx / style.css 全套骨架。

- 表头默认取自文件名 `[S4_06]某书(6).docx`（支持 S5 外典三段式与 S6 日期
  `[S6_22.06.10]xxx.docx`），否则用 `--series/--volume` 指定；书名/作者/语言可
  分别用 `--title/--author/--language` 覆盖。输出文件名与解包目录名统一为
  `[表头]书名`。
- 章节拆分：`Heading` 段落中非纯数字者为章标题（序章/第N章/行間/終章/あとがき，
  中日简繁均可，样式 id 兼容 `Heading 1`/`Heading1`/`normal` 大小写差异），每个
  章标题生成一个文件（Prologue/ChapterN/Between_the_LinesN/Epilogue/Afterwords，
  无法识别用 SectionN）；纯数字者为小节，生成 `<h2 id="toc_N">`。
- 正文中 docx 直接写出的可信行内 HTML 标签（`<b>`/`<i>`/`<small>`/`<sup>` 等）原样
  保留为标签，其余尖括号内容一律转义。
- 首章为序章时，其前的无标题正文自动生成为内容序 `01` 的 `Before_the_Prologue` 文件，序章从 `02` 起依次顺移；其他首章前文本并入首章。docx 内嵌图片按字节去重提取。
- **插图占位符**：正文中的 `【插图-N】` 占位符可用 `--images-from 日文原版.epub`
  自动替换为图片行（按 spine 中正文内容页的图片出现顺序对应），无对应图时保留
  占位符原样便于人工补图。
- **注释另起文件**：正文中的行内译注 `【*译注：...】` / `（*译注：...）` 自动提取为
  `<表头>-Note.xhtml` 译注页（`<li id="noteN">`），正文原位替换为
  `<a epub:type="noteref" href="...Note.xhtml#noteN"><sup>㊟</sup></a>` 引用，
  并在 OPF/nav/ncx 中登记，符合 X 版「译注页」成品规范。
- **封面/彩页**：`--cover 图.jpg` 指定封面（覆盖源封面）；`--illustrations-before`
  与 `--illustrations-after`（可多次）在源彩页前后追加图，例如
  `--images-from 日文.epub --cover 中文封面.jpg --illustrations-before 中文副封面.jpg
  --illustrations-after 中文目录页.jpg`。仅用中文彩页时可不带源彩页。
- 卷首目录/注意事项与卷末奥付等非正文样式段落自动丢弃并在输出中报告（含其中的
  ruby 记号，属预期）；正文字样（含 Para 02 等）完整保留。
- 输出 `.epub` 在 `--out` 目录（默认输入同目录）；`--unpacked` 额外写解包目录，
  `--no-pack` 只写解包目录。内置精简 style.css，可用 `--css FILE` 换成成品同款。

### 对齐检查（只读）

```powershell
python tools/check_alignment.py
```

逐文件检查模板符合性（L1-L3 头部结构、L4=h1 独占或空、L5=h2 独占或空（中文 Note 等包装页可为 `<ul>`/`<ol>` 列表包装占位）、L6=正文），并对中日配对文件检查总行数、h2 位置、图片行和独立 `<br/>` 行位置是否一致。`gaiji`/`height-2em` 内嵌字形不计为图片；`S2_14-04/07/10/13` 因图片已文本化，同时豁免图片行和独立 `<br/>` 位置检查。报告写入 `.cache/epub-work/alignment-check.tsv`。纯图片页/无正文页不适用；仅单侧存在的 EPUB、日文独有包装页不参与。

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

仅把“位于两个编号文件之间、正文无文本且无图片/SVG”的 XHTML 视为空占位页；应用后会删除该页，将同目录后续文件的表头序号及数字页码后缀依次前移，并同步更新 OPF/NCX/nav/其他 XHTML 中的文件引用。支持普通系列、S5 三段作品号和 S6 日期作品号。默认只扫描，不修改缓存。注意与模板中的“空行占位”区分：本工具处理的是空占位**页**（整个文件无内容），模板空行是正文文件内部的第 4/5 行占位。

### Note 注释顺序检查（只读）

```powershell
python tools/check_note_order.py
python tools/check_note_order.py --pattern "*S1_01*"   # 按书名筛选
```

检查中文缓存 `*-Note.xhtml`（译注页）中的 `<li id="noteN">` 条目顺序与编号是否和正文 `epub:type="noteref"` 首次引用顺序一致。正文文件按表头内容序排序后逐行扫描，取每个注释 id 的首次引用位置作为“书中出现顺序”；无内容序的包装页排在编号正文之后。

报告以下问题：Note 列表顺序 != 正文首次出现顺序、正文引用但 Note 未定义、Note 已定义但正文未引用（孤儿注释）、id 数值顺序乱序（含 `note2.1` 这类补充编号）。报告写入 `.cache/epub-work/note-order-check.md` 与 `note-order-check.json`。只读，不修改缓存。

可用参数：`--cache` 指定中文缓存根目录（默认 `.cache/epub-work/chinese-text`）、`--output` 指定报告输出目录、`--pattern` 按书名子串筛选（支持 `*` 通配）。

### Note 注释顺序重排（写缓存，自动备份）

```powershell
python tools/reorder_notes.py --dry-run          # 预览
python tools/reorder_notes.py                    # 执行
python tools/reorder_notes.py --pattern "*S2_07*" # 按书名筛选
```

按正文 `epub:type="noteref"` 首次出现顺序重排 `*-Note.xhtml` 的 `<li>` 条目并重编号为 `note1..noteN`，同时单遍映射更新正文所有引用。写盘前会把涉及文件备份到 `.cache/reorder-backup/`；`--dry-run` 只打印旧顺序/新顺序/映射，不写盘。

自动跳过两类情况（需人工处理）：Note 文件含非注释 `<li>`（如 S0_00 的说明条目）、定义集合与引用集合不一致（孤儿/悬空引用）。可与 `tools/check_note_order.py` 配合：先用检查工具确认问题，再用本工具重排。

可用参数：`--cache` 指定中文缓存根目录、`--backup` 指定备份目录、`--pattern` 按书名子串筛选（支持 `*` 通配）。

### 翻译与修嵌规范检查（只读）

```powershell
python tools/check_translation_spec.py
python tools/check_translation_spec.py --pattern "*S3_10*"   # 按书名筛选
```

依据《翻译与修嵌规范.docx》中**落实到 EPUB 最终正文**的条款检查中文缓存正文（`.cache/epub-work/chinese-text/**/OEBPS/Text/*.xhtml`）。交稿层面的机制（`|基文[注文]` 注音、内联 `（*译注：）`、空行规则、docx 交稿格式、漫画修嵌）在 EPUB 成品中已转换为 `<ruby>` / Note 脚注页 / 固定行模板，不做反向检查。只读，不修改缓存。

检查类别（对剥离标签后的正文文本逐行判定，`<rt>` 注音内容不参与正文文本检查）：

- `P1` 半角标点（中文语境应为全角）；`P2` 半角波浪号 `~`（应为 `～`）
- `P3` 问叹顺序 `！？`（问号应在感叹号左边）
- `P4` 省略号写成连续句号（`。。`/`。。。`）；`P5` 省略号后带句号/点号（`……。`/`……・`）
- `P6` 弯引号 `“”‘’`（中文语境应使用直角引号 `「」『』`）
- `P7` 日文点号 `・`（与全书主导的间隔号 `·` 不一致；Note 页引用日文原文豁免）
- `P8` 正文假名残留（需人工确认：形状描述 `コ字形`/`く字形`、原文引用、御坂电波噪音等属合法）
- `P9` 单位（`公斤/公里`，规范建议 `千克/千米`）
- `P10` 注音 ruby 问题（`<rt>` 内日文假名应译为汉语、空 `rt`、ruby 缺 `rt`）
- `P11` 语气词/音译（`切！`、`啊啦`、`呀嘞呀嘞` 等规范示例词，提示级）
- `P12` 单个省略号 `…`；`P13` 连续 ASCII 空格（3+，仅正文文件，标题行除外）
- `P14` 小数应使用阿拉伯数字（如 `0.7`），不得写成汉字数字+小数点（如 `〇.七`、`三·五`）

`/return`、`/escape` 等 VN 控制符**不**报错：它们是说话人的习惯性措辞（御坂网络风格），属小说特色。

报告写入 `.cache/epub-work/translation-spec-check.tsv`（逐条）、`translation-spec-check.json`（结构化）与 `translation-spec-check.md`（按书/按类别汇总及样例）。可用 `--cache` 指定中文缓存根目录、`--output` 指定报告输出目录、`--top` 控制每类样例数。

### 术语审计

```powershell
python tools/epub_audit.py
```

读取中日工作缓存，对比中日译法差异，报告写入 `.cache/epub-work/report.json` 与 `report.md`。只读，不提供重建或覆盖缓存的功能。

默认读取 `.cache/epub-work/japanese-text/` 和 `.cache/epub-work/chinese-text/`；其中日文缓存只有在刚运行 `pull.ps1` 后才是原样解压快照，规范化或校对后以工作源状态为准。如需保留原样快照，请先拉取到临时缓存；如需读取其他中文目录，使用 `--cn`。

生成内容位于 `.cache/epub-work/`：

- `japanese-text/`：日文 EPUB 工作缓存；刚由 `pull.ps1` 生成时保留 EPUB 原样目录、文件名、标签和换行，规范化后允许按规约折叠排版包装
- `report.json`：机器可读的逐条命中记录
- `report.md`：按卷汇总的中文译法差异及上下文

`.cache/epub-work/` 已加入 `.gitignore`，不会提交到 GitHub。

定位命中内容时，直接打开 `japanese-text/<卷>/` 下对应的原始 XHTML 文件。报告中的上下文仅用于快速检索，不替代原始文件行号。

### 字数统计与页数换算（只读）

```powershell
python tools/epub_char_count.py <epub 或目录> [--pages-per 400] [--all] [--json] [--label-map map.json]
```

探测 EPUB 各**正文成分**的字数并换算为页数。参数可为单个 `.epub` 文件或目录（目录会递归收集全部 `.epub`）。只读，不修改 EPUB。

- **正文成分**：按 spine 顺序取含文字的 XHTML 页；跳过固定版式包装页（pre-paginated / svg，如封面、扉页、卷首插画）与导航文档，也跳过文件名或标题命中包装页关键词（`cover` / `colophon` / `奥付` / `toc` / `目次` / `contents` / `fmatter` / `bmatter` / `bookwalker` / `titlepage` / `caution` / `注意` / `nav` / `版权` / `広告` / `banner` 等）的页面。连包装页一起统计用 `--all`。
- **字数口径**：去 HTML 标签、去注音假名（`<rt>/<rb>/<rp>`，注音不重复计数）、解实体、去全部空白。「全字符」= 剩余全部字符（含标点、数字、字母）；「占比」= 汉字与假名占全字符的比例（0.xx 两位小数）。
- **子成分（精确到小节）**：成分内若含 `<h2>`，按 `<h2>` 切分为子成分（标签取自小节标题，全角数字转半角，如 `１` → `1`），h1 前的开场文字并入第一节；无 `<h2>` 的成分按整体统计。子成分行不含 h1 标题文字，因此「子成分字数之和 + h1 标题字数 = 成分总字数」，且章级页数 = 子成分页数之和。
- **页数换算**：每个成分/子成分页数 `= max(1, ceil(全字符 / --pages-per))`，`--pages-per` 默认 `400`（全字符含标点约 400 字/页）。章级（含子成分）页数 = 子成分页数之和。合计行给出「连续排版约 X 页」与「成分整体口径（每成分至少 1 页）」两种参考。文本输出为对齐表格（数字右对齐，子成分以缩进行展示）。
- **成分命名**：优先取文件 `<h1>` 标题，无标题时用文件名（如 `S4_03-01-p-001`）。可用 `--label-map map.json` 提供成分名映射，键为文件名（去掉 `.xhtml`）或 zip 内路径，如 `{"S4_03-01-p-001": "引子"}`。
- **成分名规范化**（默认开启，`--raw-labels` 关闭）：章节标题截断为「序章/第N章/终章」（去掉副标题）；常用日文词替换为中文（`行間`→`行间`、`終`→`终`、`あとがき`→`后记`）并去掉标签内空白；位置规则：第一个「序章」之前的成分 → 「引子」，第一个「后记」之后的成分 → 「尾声」。
- `--min-chars` 忽略全字符数低于阈值的页面（默认 `1`）；`--json` 输出机器可读结构；`--csv` 输出扁平 CSV（UTF-8 带 BOM，Excel 可直接打开；列 = 成分/子成分/全字符/占比/换算页数 + 合计行，多本书时自动追加「书籍」列）。
