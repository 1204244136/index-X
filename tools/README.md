# EPUB 审计工具

```powershell
# 读取本地缓存和项目内中文 EPUB，并生成审计报告
python tools/epub_audit.py
```

`epub_audit.py` 只读取现有日文缓存，不再提供重建或覆盖缓存的功能。若缓存不存在，工具会直接报错。日文缓存需要通过外部解压或人工准备后，再运行本工具生成报告。

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

### 1. 拉取（OneDrive -> 缓存）

```powershell
./tools/pull.ps1
```

将 OneDrive 中的中文和日文 EPUB 解压到审计缓存，并生成哈希清单用于后续增量发布。

默认读取：

- `C:\Users\<用户名>\OneDrive\某系列\X系列\EPUB` -> `.cache/epub-work/chinese-text/`
- `C:\Users\<用户名>\OneDrive\某系列\日文原文` -> `.cache/epub-work/japanese-text/`

脚本会逐本先解压到缓存内临时目录（`.extract-` 前缀），校验 `mimetype` 和 `META-INF/container.xml` 后再替换对应书目录，因此重复运行不会保留旧文件。启动时会自动清理上次中断遗留的 `.extract-*` 临时目录。可用 `-ChineseSourceDirectory`、`-JapaneseSourceDirectory`、`-CacheDirectory` 覆盖路径，或用 `-Side chinese` / `-Side japanese` 只处理一侧；用 `-Pattern '*S2_14*'` 可筛选书名；`-WhatIf` 只预览，不写入缓存。

解压完成后自动调用 `python tools/manifest.py` 生成 `.cache/epub-work/manifest.json`，记录每个缓存文件的 SHA-256 哈希，作为增量发布的基线。

### 2. 修改缓存（Agent 或手动）

使用 agent 或手动修改 `.cache/epub-work/` 中的文件。可先运行 `python tools/normalize_epub_cache.py` 规范化缓存，再进行内容校对。

### 3. 发布（缓存 -> EPUB/ + 打包 + OneDrive）

```powershell
python tools/publish.py --dry-run    # 预览变更
python tools/publish.py              # 执行发布
```

对比 `manifest.json` 检测自上次拉取以来哪些文件被修改、新增或删除，只处理受影响的书籍：

1. **中文变更**镜像同步到 `EPUB/` 目录（包含缓存中已删除文件的删除，不影响未修改的书籍）
2. **重新打包**受影响的书籍为 `.epub`（输出到 `.cache/epub-work/packed-epubs/`）
3. **上传**到 OneDrive 对应目录（中文 -> `某系列\X系列\EPUB`，日文 -> `某系列\日文原文`）
4. **更新清单**，记录已成功发布的书籍状态

可用参数：

- `--side chinese` / `--side japanese`：只处理一侧
- `--pattern "*S1_01*"`：按书名筛选
- `--force`：忽略清单，处理所有文件（首次发布或全量重传）
- `--no-upload`：跳过 OneDrive 上传，仅同步 EPUB/ 并打包
- `--dry-run`：仅预览，不执行任何操作

发布失败的书籍不会更新清单，下次运行时会自动重试。

若需要让全部中文缓存与项目 `EPUB/`、以及两侧 OneDrive 打包文件重新建立一致，使用 `python tools/publish.py --force`；该命令会重建并覆盖全部 154 本 EPUB，执行前应先确认缓存就是预期发布源。

### 哈希清单工具

```powershell
python tools/manifest.py              # 重新生成清单
python tools/manifest.py --cache path # 指定缓存目录
```

`manifest.py` 扫描 `chinese-text/` 和 `japanese-text/` 下所有文件，计算 SHA-256 哈希并写入 `manifest.json`。`pull.ps1` 在解压后自动调用此工具；也可手动运行以重置基线。

### 初始设置或全量重建 EPUB/

```powershell
./tools/pull.ps1
python tools/publish.py --force --no-upload
```

`pull.ps1` 把 OneDrive 的 EPUB 解包到缓存并生成清单；`publish.py --force --no-upload` 忽略清单把全部中文书籍从缓存同步到 `EPUB/` 并打包，跳过 OneDrive 上传。不要直接解包 OneDrive 的 `.epub` 到 `EPUB/`，那会绕过清单与规范化流程。

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
缓存规范化：

```powershell
python tools/normalize_epub_cache.py
```

该脚本只处理 `.cache/epub-work/`，会保留在 `tools/` 中供后续维护重复使用，不修改 `EPUB/` 源文件。

脚本还会校正文件头后的首个正文块：若第 5 行仍是多余 `<br/>` 且正文被推迟到后续行，会删除多余换行直到正文落在第 5 行。

带表头的章节文件会统一为 `XML → DOCTYPE → HTML 与章节标题 → 小节编号 → 正文`；旧式 `start-3em` 标题也会并入 HTML 行，使首个正文段落固定在第 5 行。

独占一行的数字段落（例如 `<p>１</p>` 或 `<p>1</p>`）按二级标题处理，不计入首个正文块定位；差异结构分析也会将其归类为标题。

正文中的意外换行（例如 `<p>`、`<rt>` 或注释链接结束后，下一行直接出现文本）会自动合并回上一行；`<code>` 代码块中的换行保持原样。

单个对齐容器内的段落若被拆成 `<div ...>`、`<p>...</p>`、`</div>` 多行，或 `<div ...>` 与 `<p>...</p></div>` 两行，会合并为一个逻辑行；该规则适用于全文缓存。

除一级标题 `<h1>` 外，`<br/>` 必须独占一行；与段落、容器等标签粘连时会拆分为独立换行。若拆分后仅因新增的独立 `<br/>` 造成中日缓存行数不一致，应删除该换行，不删除正文内容。

图片段落若被拆成 `<p><img .../>` 与独立 `</p>`，会先合并回完整的 `<p><img .../></p>`；随后再处理紧邻的数字标题、换行和正文，避免标题识别因标签错位失效。

若 `<h1>`、`<h2>` 或被识别为标题的独立数字段落（如 `<p>４</p>`）前后紧邻的独立 `<br/>` 恰好造成中日行数差异，仅删除造成该差异的换行。

仅针对 `<h2>` 标题前后换行的对齐：当日文 `<h2>`（含从 `start-3em`/`start-5em` 折叠而来）前后存在独立 `<br/>` 而中文对应位置没有，且这些换行数不少于中日行数差时，删除日文侧的 `<br/>` 来对齐（删除数量等于行数差，非全部删除）。此规则不涉及 `<h1>` 前后的换行，避免因 h1 相关的补偿性差异导致误判。

日文侧 `</p></div>` 节末闭合标签后若紧跟独立 `<br/>`，而中文对应位置没有，且这些换行数不少于中日行数差时，删除日文侧的多余 `<br/>` 来对齐。此规则针对日文用 `<div><p>` 包裹 `<h2>` 标题、闭合后多出一个换行的结构。

后记文件中日文独有的短标题行（如 `<p>あとがき</p>`）会合并到前面的 HTML 行中，并删除标题后紧跟的 `<br/>`，以避免 `split_inline_breaks` 在后续规范化中拆回独立行。

包含 `class="align-end"` 或 `class="right"` 的署名/对齐行同样适用：仅在其前后换行完全造成中日行数差异时删除换行。

正文中若中文存在连续 3 行独立 `<br/>`、日文对应位置更多，且多出的换行数恰好等于中日总行数差，则删除日文多出的换行，直到该段与中文同为 3 行。

独占一行的 `<h2>`，或 `<div class="start-3em"><p>N</p></div>`、`<div class="start-5em"><p>10</p></div>` 这类数字小节标题若被冗余容器包裹，会折叠为独立 `<h2>`；`<div class="start-3em"><p><h1>N</h1></p></div>` 或 `<div class="start-3em"><p>N<h1></h1></p></div>` 等含 `<h1>` 的变体同样折叠为 `<h2>`。若标题前后换行因此造成中日行数差异，再按标题邻接换行规则移除。

若 `<body>` 后的 `<div class="main">` 被拆到独立行，也会合并回 `<body>` 行；独立容器标签不会被误判为正文。
当日文使用 `main` 容器而中文缺失时，改为折叠日文侧的结构：若日文 `<div class="main">` 独占一行则合并到 `<body>` 行，若 `</div>` 独占一行则合并到 `</body>` 行。通过对日文侧的行折叠代替向中文添加容器，避免修改中文原始内容。`S2_19-13` 的跨页后记页尾换行属于特例，保留六个连续换行并保持其原始闭合标签布局。

后记署名块会固定为单独一行，纯结束标签固定在下一行；不会为了补偿结束标签的拆行差异而添加无语义的 `<br/>`。

后记中的连续 `<br/>` 会压缩为一个；同一行或跨多行的连续换行符均适用。文件名含 `after_the_afterword` 的页面明确不按后记处理。

短后记按“寒暄与主题介绍 → 空行 → 插画/编辑/读者致谢 → 空行 → 收束语 → 空行 → 作者吐槽 → 署名”的结构处理；仅当中日行数差恰好由这些分段 `<br/>` 造成时，才在较长一侧删除多余换行。长后记和 `after_the_afterword` 不套用此平衡规则。

独占一行的 `<div class="h-indent-1em">` 仅作为排版包装时会被移除，并同步移除对应的闭合标签；与正文位于同一行的缩进容器保持不变。

独占一行的通用 `<div>` 开标签（如 `<div>`、`<div class="center">`、`<div class="in0">`、`<div class="box2">` 等）会先合并到下一行；确认只是单块排版包装后，裸 `<div>`/`</div>` 标签会被清除，带 class 的语义容器保留。若相邻裸开闭标签形成 `<div></div>`，会删除该空行。`<div class="main">` 和 `<div class="h-indent-1em">` 由其他规则单独处理，不在此规则范围内。

当日文用单行图片替代中文中连续的 `<del>` 删除文本时，会按中日行数差在图片后补充独立 `<br/>`，仅处理短文件中的同类占位结构。

含行内 `gaiji` 图片的日文段落若后方缺少独立 `<br/>`，而中文对应位置存在该换行，会补回日文换行；普通行内图片不会触发此规则。


收尾标签 </div>、</body>、</html> 应尽可能在同一行，中日两侧统一处理。若这三行被拆成独立的三行，会合并为单行 </div></body></html>；若 </body> 和 </html> 被拆成两行，也合并为 </body></html>。该规则不区分语言，统一应用于所有缓存文件。S2_19-13 跨页换行不受此规则影响。
建立中日表头行数对比：

```powershell
python tools/compare_cache_lines.py
```

差异报告写入 `.cache/epub-work/normalized-line-diff.md`，其中的中日文件链接使用相对于报告目录的路径，VS Code 可直接打开；不会写入机器绝对路径或 `docs/`。

分析剩余差异的结构类别：

```powershell
python tools/analyze_cache_diffs.py
```

后记署名前换行候选分析：

```powershell
python tools/analyze_afterword_breaks.py
```

扫描孤立图片页：

```powershell
python tools/analyze_orphan_image_pages.py
```

图片必须与中日正文逐行对应。扫描图片数量、行号和资源名不一致的文件：

```powershell
python tools/analyze_image_alignment.py
```

图片错位只生成“人工复核”候选，不自动修改缓存；分析时以日文图片的相对位置为基准，优先提出调整中文的方案。报告同时附带图片前后中日片段和建议，确认后再手动修改。

若日文图片本身是食材清单、注释或其他纯文字版面，且中文已将其内容翻译为 XHTML 文本，则标记为“文本化图片”，排除出图片人工复核候选；目前已确认的例外为 `S2_14-04`、`S2_14-07`、`S2_14-10`、`S2_14-13`。

段落内的 `gaiji` / `gaiji-line` 字形、表情素材不计入插图对齐；这类资源属于内嵌文字素材，不要求中日单独成行对应。

若日文连续两张单页图片在中文中被完整合并为一张跨页图，中文保留合并图，并增加一个隐藏的 `data-image-continuation` 续页行，使图片逻辑行数与日文一致；不得仅通过排除状态跳过行数差异。

图片行即使已经对应，只要中日文件总行数不同，报告仍标记为“行数未对齐”，要求先修复行数再判断图片位置。只有总行数一致的文本化图片例外才可排除人工复核。

统筹报告：

```powershell
python tools/analyze_unified_alignment.py
```

该工具生成 `.cache/epub-work/unified-alignment.tsv` 和 `.cache/epub-work/unified-alignment.md`，把每个表头的行数状态、图片数量、图片行位置和处理优先级放在同一行。判定顺序固定为“先行数、后图片”：行数不一致时记录图片资源但标记为“图片暂不判定”；只有行数一致时才判定图片行已对齐、图片行错位、图片数量差异或文本化图片。

若中日总行数相同、图片数量与顺序一致，且差异只涉及图片插入位置，则按日文相对位置对中文图片行直接重新排序；正文文本的相对顺序保持不变。若日文仅比中文多一个独立 `<br/>`，且该换行正好造成后续图片整体偏移一行，也自动补回该换行并重排图片。若图片数量或顺序不同，或无法仅靠图片/单行换行修复，则保留为人工复核候选。

手动迁移中日排版格式时，必须先检查目标 XHTML 实际引用的 CSS 文件，并只使用目标语言样式表中已定义、效果对应的类名；不得把日文的 `align-end`、`h-indent-*` 等类直接照搬到中文。若中文样式表提供 `.right`、`.in1`、`.in2`、`.in4` 等本地类，应使用这些类表达相同的右对齐或缩进效果。

扫描或删除编号序列中的实际空占位页：

```powershell
python tools/fix_empty_placeholders.py
python tools/fix_empty_placeholders.py --apply
```

脚本仅把“位于两个编号文件之间、正文无文本且无图片/SVG”的 XHTML 视为空占位页；应用后会删除该页，并将同目录后续文件的表头序号及数字页码后缀依次前移。默认命令只扫描，不修改缓存。

默认读取 `.cache/epub-work/japanese-text/` 和项目内 `EPUB/`；其中日文缓存只有在刚运行 `pull.ps1` 后才是原样解压快照，规范化或校对后以工作源状态为准。如需保留原样快照，请先拉取到临时缓存；如需读取其他中文目录，使用 `--cn`。

生成内容位于 `.cache/epub-work/`：

- `japanese-text/`：日文 EPUB 工作缓存；刚由 `pull.ps1` 生成时保留 EPUB 原样目录、文件名、标签和换行，规范化后允许按规约折叠排版包装
- `report.json`：机器可读的逐条命中记录
- `report.md`：按卷汇总的中文译法差异及上下文

`.cache/epub-work/` 已加入 `.gitignore`，不会提交到 GitHub。

定位命中内容时，直接打开 `japanese-text/<卷>/` 下对应的原始 XHTML 文件。报告中的上下文仅用于快速检索，不替代原始文件行号。
