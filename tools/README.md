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

### 正文文件结构（引子与尾声）

- 序章（`Prologue`）之前的内容，无论页数多少，只写为一个文件「引子」，语义后缀用 `Before_the_Prologue`；不得按量拆分或并入 `Prologue` 文件。
- 后记（`Afterwords`）之后的内容，无论页数多少，只写为一个文件「尾声」，语义后缀用 `After_the_Epilogue`；连续出现第二个尾声时用 `After_after_the_Epilogue`。
- 判定以表头内容序为准：引子位于第一个 `Prologue` 之前，尾声位于第一个 `Afterwords` 之后。该位置规则与 `epub_char_count` 的成分名规范化（第一个「序章」前的成分 → 引子、第一个「后记」后的成分 → 尾声）一致。
- `docx2epub` 目前把首章标题前的无标题引言并入首个章节文件；若引言位于序章之前且内容独立，应按本节规约人工拆为引子文件。

### 换页衔接处理（跨页文件合并）

分页源（BookWalker 等）合并为章节文件时，换页衔接处按下述规则处理：

- 正文段落按行续接直接拼接，跨页连续段不插入空行或 `<br/>`；被分页切断的半句/半段按原文语义拼接为完整段落，不得残留残缺行。
- 页首/页尾的填充 `<br/>` 属排版噪声，合并时删除。
- 整页无文本且无图/SVG 的空占位页删除并前移后续文件序号（见「空占位页清理」）。
- 全页插图页（SVG 或 `body.p-image`）保留为图片行，随归属章节合并，两侧图片行一一对应（见「对齐检查」）。

## 拉取与发布流程

三处中文文件副本各有固定角色，不得互相替代：

- `.cache/epub-work/`（解包工作区，不提交）：唯一编辑点。`pull.ps1` 从 OneDrive 解包生成，可随时删除重建。
- `EPUB/`（解包归档，提交到 git）：版本控制真源，diff 友好；仅由 `publish.py` 从缓存同步覆盖。
- OneDrive（打包 `.epub`，外部）：分发与阅读副本；既是 `pull.ps1` 的输入，也是 `publish.py` 的上传目标。

编辑边界：

- 只在 `.cache/epub-work/` 中编辑。直接修改 `EPUB/` 不会同步回 OneDrive，因为 `publish.py` 只读取缓存。
- 若确实直接改了 `EPUB/`，可用 `publish_epub.py`（流程 C）把改动打包上传 OneDrive 并增量覆盖回缓存；这是唯一把 `EPUB/` 改动回流到 OneDrive 与缓存的正规路径。运行前务必 `--dry-run` 预览。
- 不得直接修改 OneDrive 中的 `.epub`。若已修改，切勿在发布前运行 `pull.ps1`，否则 OneDrive 的改动会被当作新基线拉入缓存，覆盖缓存中的编辑。
- 缓存中的改动必须经 `publish.py` 才会同步到 `EPUB/` 和 OneDrive。发布后中文缓存与 `EPUB/` 逐字节一致属预期行为。
- `.cache/` 可丢弃：删除后运行 `./tools/pull.ps1` 即可完整重建。

### 三种常用工作流（均增量处理，不做全量写入）

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

### bw 提取预处理（BookWalker 原始 EPUB -> 模板友好形态）

```powershell
python tools/bw_preprocess.py 某本bw提取.epub            # 输出 某本bw提取.preprocessed.epub
python tools/bw_preprocess.py --dry-run 某本bw提取.epub   # 只预览
python tools/bw_preprocess.py --out 输出目录/ 某本bw提取.epub
python tools/bw_preprocess.py 已解包的目录/               # 就地改写目录下全部 .xhtml/.html/.htm
python tools/bw_preprocess.py --rules 自定义.rules.json 某本bw提取.epub
python tools/bw_preprocess.py --check 某本bw提取.epub     # 校验模式，不写盘
```

对 BookWalker 解包后的原始 XHTML 应用查找/替换规则集，是 `normalize_epub_cache.py` 之前的预处理步骤：合并双 ruby、`<p><br/></p>` 展平、头部折叠为 L3 单行、`start-3em/start-5em` 容器折叠为 h1/h2 独占行、裸数字小节转 `<h2>`、解包 `font-1em50`/`line-break-loose`/`em-sesame`/`tcy` 等排版包装。

- 规则文件：`tools/bw_extract_preprocess.json`（与原始 `bw提取预处理.json` 同格式，可编辑；脚本以此为准，缺失时报错提示用 `--rules`）。
- 输入 `.epub` 时解包改写后重新打包为 `<原名>.preprocessed.epub`，保留原文件、条目顺序、压缩方式与 `mimetype` 首项；输入目录时**就地**改写。
- 保留原文件的 BOM 与换行风格（LF/CRLF），并把孤立 `\r`、`\r\r\n` 等脏换行归一化后再应用规则；规则按 JSON 顺序逐条执行，整体幂等（重复运行不再改写）。
- `--check` 校验模式：内存中应用规则后检查内容文件（`<body class="p-text">`）的 L1-L6 固定行模板符合度，报告不符合清单；不写盘。常规模式也会统计内容/非内容文件数，便于发现漏处理。

> 相对原始规则集的三处修正（均由真实数据验证得出）：
>
> 1. 规则「头部整体合并为L3单行」中结构标签间的 `\s*` 收紧为 `\s+`，只命中原始多行头部、不命中已折叠单行头部，避免重复运行时向 `main>` 后追加空行。
> 2. 规则「bw提取预处理-ruby修正」标记 `"iterative": true`：脚本对其循环应用到稳定，把 4 段以上多段 ruby（如 `<ruby>学<rt>がく</rt>園<rt>えん</rt>…`）一次合并为单段 `<ruby>学園…<rt>…</rt></ruby>`。原规则每遍只合并相邻一对，重复运行会继续改写（非幂等）。
> 3. 辅助格式规则重排：`em-sesame`→`<b>`、`tcy` 解包移到外层 `line-break-loose word-break-break-all` wrapper 解包**之前**。原顺序下 wrapper 的惰性 `.*?` 会把外层开标签与内层 span 的闭标签错误配对，产生非平衡嵌套 span 且残留不幂等。

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
- 第一章之前的引言并入第一章文件（序章之前的独立内容按「正文文件结构」规约拆为引子文件）；docx 内嵌图片按字节去重提取。
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

读取日文缓存与项目内中文 EPUB，对比中日译法差异，报告写入 `.cache/epub-work/report.json` 与 `report.md`。只读，不提供重建或覆盖缓存的功能。

默认读取 `.cache/epub-work/japanese-text/` 和项目内 `EPUB/`；其中日文缓存只有在刚运行 `pull.ps1` 后才是原样解压快照，规范化或校对后以工作源状态为准。如需保留原样快照，请先拉取到临时缓存；如需读取其他中文目录，使用 `--cn`。

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
