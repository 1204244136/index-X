# EPUB 维护工具

本文只说明工具入口、参数、数据流和可验证行为。作品编号、文件命名、固定行模板及 Agent 操作边界以仓库根目录 `AGENTS.md` 为唯一规范来源；下文出现的规则摘要用于解释命令效果，不另立一套规则。**本文不记录历次修订记录与验收结论**（每轮改动规模、通过哪些门禁、遗留项处置等）——这类内容记入 `docs/maintenance-records/`（长期保留的检查结论）。`docs/changelog.md` 已冻结并归档为 `docs/archive/legacy-changelog.md`，禁止继续编辑。

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
- **说明**：配对文件只有在两侧均可重建且重建后行数相同时才写入。

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

归档目录   → check_epub_health.py（EPUB/ 单侧机械体检）→ 报告（CI 每日，只读）
```
- **工具**：`check_alignment.py`、`check_translation_spec.py`、`check_note_order.py`、`check_epub_health.py` 等
- **职责**：只读检查，不修改文件
- **输出**：`.cache/epub-work/` 下的检查报告（TSV/JSON/Markdown）；`check_epub_health.py` 只写 `--tsv`/`--json` 指定路径，默认不落盘
- **两侧分工**：前三个读中日缓存、需要对照；`check_epub_health.py` 只读 `EPUB/` 中文侧、只判「不需要对照就能判定」的机械问题，因此可以放进 CI

### 阶段 6：发布
```
publish_auto.py（判别改动位置，选择方向）
  ├─ 缓存有改动     → publish.py（增量同步 + 打包 + 上传）      → EPUB/ + OneDrive
  ├─ EPUB/ 有改动   → publish_epub.py（打包 + 上传 + 覆盖缓存） → OneDrive + 缓存
  └─ OneDrive 有外部更新 → pull.ps1 -SyncToEpub（解压 + 同步）   → 缓存 + EPUB/
```
- **入口**：`publish_auto.py`（日常只需这一条命令）
- **工具**：`publish.py`（缓存为准）、`publish_epub.py`（归档为准）、`pull.ps1 -SyncToEpub`（OneDrive 为准）
- **职责**：与 `manifest.json` 基线比对，判断改动只出现在哪一处，再调用对应工具；只处理变化的书籍和文件
- **流程**：
  1. 对比 `manifest.json` 检测变更
  2. 中文变更增量写入 `EPUB/`（含删除传播）
  3. 打包为 `.epub`（输出到 `.cache/epub-work/packed-epubs/`）
  4. 上传到 OneDrive 并更新 `pull-state.tsv`
- **反向流程**：若直接修改了 `EPUB/`，用 `publish_epub.py` 回流到 OneDrive 和缓存；统一入口会自动选中这个方向

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

- `epub_ids.py`：作品号、表头、内容序和包装页角色解析；历史异常只接受明确别名，不做模糊配对。中日两侧使用**同一个作品号**（`japanese_book_id` 是恒等映射），不按合订卷推导。
- `alignment_rules.py`：人工确认的配对例外——非配对作品、手工对齐表头、文本化图片、SP 标题、已确认的配对差异规则（`PAIR_RULES`）与模板检查豁免名单（`TEMPLATE_EXEMPT_WORK_IDS`）。
- `xhtml_template.py`：固定行模板的纯重建规则；由两个 normalize 入口共同调用。
- `notes_core.py`：Note 条目解析、正文引用收集和阅读顺序。
- `sync_core.py`：清单差异、文件增量镜像和 `pull-state.tsv` 更新。
- `path_safety.py`：解包路径安全（拒绝绝对路径、`..`、反斜杠与盘符的 ZIP 条目）和 `.extract-*` 残留目录识别。

修改上述共享规则或其调用方后运行：

```powershell
python -m unittest discover -s tools/tests -p "test_*.py" -v
```

体检类工具（`check_epub_health.py`）额外要求**负向自检**：每个检查项都要有一个能触发它的最小反例，否则判定写错（正则静默失配、路径没匹配上）会表现为「永远报 0」而看不出异常。见 `tools/tests/test_check_epub_health.py`。

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
- 同一文件中日两侧的 h1/h2/独立 `<br/>` 行位置一一对应；总行数一致。`S2_14-02/04/07/10/13` 的图片文本化页面是已确认例外（配对检查整体豁免）。
- 正文区每条物理行只能有一个同级顶层块。`<p>…</p><p>…</p>`、正文后直接拼 `<hr/>`、`</body>` 或 `</html>` 都会被视为原子性错误；一对多段落只能在语义确认后真正合并为一个 `<p>`，不能靠删除换行凑总行数。
- `python tools/check_alignment.py --strict` 在发现模板、原子性或配对问题时返回非零状态；普通模式仍生成完整报告并返回成功，便于人工审计。缓存只存在一侧时，缺失的另一侧按空集合处理，不因目录不存在中断。
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

- **文本 + 图片 + 文本**（3 页，跨整页插图）：图片包裹的 `<p>` 标签中加入 `class="pb"`，图片与前后文本无缝衔接，前后文本段落不额外追加换页标记，不插入 `<br/>`：

  ```html
  <p>…前一页文本…</p>
  <p class="fit pb"><img …/></p>
  <p>…下一页文本…</p>
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

### 统一发布入口（日常只需这一条命令）

```powershell
python tools/publish_auto.py --dry-run   # 预览方向、书籍与文件差异
python tools/publish_auto.py             # 检查并发布
```

把缓存、`EPUB/`、OneDrive 三份副本分别与 `manifest.json` 基线比对，判断改动只出现在哪一处，
再调用对应的底层流程工具，因此不必自己记住三条命令。判定口径：

- 只有缓存有未发布修改 -> 流程 B；只有 `EPUB/` 有改动 -> 流程 C；两侧改动属于**不同书**时两个方向都执行。
- **同一本书**在缓存与 `EPUB/` 两侧都有改动时，先逐文件比较实际内容：缓存改动若已全部体现在 `EPUB/` 中，按流程 C 推进清单；只有缓存仍有 `EPUB/` 未包含的内容时才报告冲突并要求用 `--from` 选边。OneDrive 的 `.epub` 被外部更新而本地对同一本书也有未发布修改时仍直接停止。
- OneDrive 的 `.epub` 与 `pull-state.tsv` 不一致（外部更新）时按流程 A 拉回；`--from cache` / `--from epub` 显式指定本地方向时不隐式拉取，只提示。
- 各流程原有门禁全部保留：`publish.py` 的严格对齐检查、`publish_epub.py` 的缓存未发布修改冲突跳过、清单基线整侧缺失检查。
- `EPUB/` 相对基线只差换行符时额外警告：归档检出时的 CRLF/LF 转换不是真实编辑，先 `git restore EPUB/` 再重跑。

参数：`--cache` / `--epub`、`--from auto|cache|epub|onedrive`、`--side`、`--pattern`、`--only-books`、
`--dry-run`、`--no-upload`、`--force`（需配合 `--from`）、`--overwrite-cache`、
`--chinese-onedrive` / `--japanese-onedrive`。退出码 1 表示被阻塞或发布失败；
`--dry-run` 只预览，不写入任何副本，也不触发严格对齐检查。

下面三条是统一入口内部调用的底层流程，需要单方向重做或排查时仍可单独运行。

### 底层流程 A/B/C（均增量处理，不做全量写入）

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

`bw_preprocess.py` 与 `split_s5_epubs.py` 在解包前拒绝绝对路径、`..`、反斜杠以及含冒号/盘符的 ZIP 条目，并确认解析后的目标仍位于输出根目录之下。`.extract-*` 按相对路径的任一层组件识别，因此遗留的 `.cache/epub-work/*/.extract-*` 目录不会被 `manifest.py`、发布扫描或全量镜像当成书籍内容。

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

> 日常改用统一入口 `python tools/publish_auto.py` 即可自动选中本流程；只有需要单方向强制执行时
> 才直接调用 `publish.py`（例如 `--force` 全量重建、`--sync-only` 只同步 `EPUB/`）。

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

**基线前置检查**：发布前会核对清单基线是否覆盖本次处理范围内的每一侧。若某一侧在缓存里有书、基线里却**一条记录都没有**，该侧全部文件都会被判成「新增」，发布会把整侧重新打包并重传——而内容其实没变（实测曾出现 87 本日文、约 696 MB 的整侧重传）。这种情况直接报错并给出修复命令，不再静默全量重发：

```powershell
# 确认该侧缓存就是已发布状态后，只重建该侧基线（另一侧不受影响）
$keys = Get-ChildItem -LiteralPath .cache/epub-work/japanese-text -Directory | ForEach-Object { "japanese-text/$($_.Name)" }
python tools/manifest.py --cache .cache/epub-work --update-books @keys
```

用 `--side` 或 `--only-books` 把该侧排除在本次范围外即可正常发布；确认确实要整侧重发时用 `--force`（该模式跳过此项检查）。日文侧基线只在 `pull.ps1` 重新解压某书、或 `manifest.json` 不存在时全量扫描才会建立，所以缓存若被 `pull.ps1` 之外的途径整批替换过，基线会静默缺失——这条检查即为此设。

### 4. 反向发布（`EPUB/` -> OneDrive + 缓存，流程 C）

```powershell
python tools/publish_epub.py --dry-run    # 预览变更
python tools/publish_epub.py              # 执行反向发布
```

> 日常改用统一入口 `python tools/publish_auto.py` 即可自动选中本流程（检测到 `EPUB/` 有改动时）；
> 直接调用 `publish_epub.py` 适用于强制方向或排查的场景。

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
- `--overwrite-cache`：允许覆盖缓存中 `EPUB/` 未包含的未发布修改（默认会跳过并报告冲突）
- `--dry-run`：仅预览，不执行任何操作

**冲突保护**：默认情况下，工具会比较缓存相对清单的未发布新增、修改、删除，以及这些文件在 `EPUB/` 中的当前内容。缓存与 `EPUB/` 已经逐字节相同的改动不算冲突，会正常反向发布并推进清单；只有缓存侧仍有 `EPUB/` 未包含的内容时才列为冲突并跳过该书，不打包、不上传、不更新清单。确认要以 `EPUB/` 覆盖缓存独占内容时用 `--overwrite-cache`，或先用 `publish.py` 把缓存修改发布掉。

**基线前置检查**：与 `publish.py` 同一项检查，作用于中文侧——中文基线整侧缺失时 `EPUB/` 会被判成「全部新增」并触发整侧重传，此时直接报错并给出重建命令（`--force` 跳过该检查）。

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

两个入口共享 `xhtml_template.py` 的重建实现。`normalize_paired.py` 只处理 `.cache/epub-work/` 中可确认的配对/单侧中文正文，并在成对写入前验证行数相等；`normalize_single.py` 只处理命令行明确指定的文件或目录，不保证中日对齐。两者都不修改 `EPUB/`。

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
python tools/bw_preprocess.py --merged --check .cache/epub-work/japanese-text # 校验已合并的缓存
python tools/bw_preprocess.py --merged .cache/epub-work/japanese-text/某卷   # 就地修复缓存
```

**两套 L1-L6 契约**：默认是**分页契约**，要求 L3 含 `<div class="main">`——那是 `merge_bw_pages.parse_page_content` 定位正文的锚点，缺了会静默不合并，必须拦。但 `merge_unit` 不把 main 容器写进输出，所以对 `merge_bw_pages` 之后的章节文件（即 `.cache/epub-work` 工作源）沿用默认契约会把每个文件都误报成「L3 未折叠」。加 `--merged` 切到**合并后契约**：L3 只要求折叠的 `<html …><head>…</head><body…>` 单行，L4/L5/L6 与 XML 语法检查照旧。`--merged` 仅适用于目录输入，与 `.epub` 同用会直接报错；默认分页契约在遇到"已含 `<body>` 但无 main"的形态时，会追加一条提示告知应改用 `--merged`。

在 2000 个日文缓存文件上实测：默认契约产生 514 条误报；`--merged` 下只剩 1 条真实违规（`S1_13-01` 的 L6 是 `<div class="gfont">` 开标签而非 `<p>`），这类问题在误报里完全不可见。注意 `check_alignment.py` 只查 L6 是否为空、不查它是否为 `<p>`，两者互补。

对 BookWalker 解包后的原始 XHTML 应用查找/替换规则集，清理排版噪声，并建立 `merge_bw_pages.py` 所依赖的 L1-L5 固定槽位。

**本工具职责**（v3）：
- ✅ 正文页头部折叠为 L1-L3；无标题页补 L4/L5 空槽，保证正文从 L6 开始
- ✅ `start-3em` / `font-1em30` 章节标题转为 L4 单行 `h1`
- ✅ `start-5em` 和裸数字小节转为 `h2`；首小节放在 L5（含无 h1 续页首行的裸数字段落），后续小节保持正文区独占行
- ✅ 合并多段 ruby 为单段（`<ruby>学<rt>がく</rt>園<rt>えん</rt>` → `<ruby>学園<rt>がくえん</rt>`）
- ✅ `<p><br/></p>` 展平为 `<br/>`
- ✅ 页首/页尾填充 `<br/>` 删除（`<div class="main">` 后与 `</div>` 前）
- ✅ 解包排版 span（`font-1em50`、`tcy`、`line-break-loose` 等）
- ✅ `bold` 与 `em-sesame`（着重号）span 转 `<b>`，按 **class token** 匹配（前瞻 `(?=[^"]*\bbold\b)` / `(?=[^"]*\bem-sesame\b)`）而非整串精确匹配，因此 `bold em-sesame`、`tcy bold` 这类组合 class 同样会转成 `<b>`：强调语义保留、`tcy` 排版语义丢弃。纯 `tcy` 仍走解包规则

**工作流位置**：
```
bw 原始 EPUB → bw_preprocess（清理噪声 + 分页模板）→ merge_bw_pages（合并分页）→ normalize（最终规范化）
```

- 规则文件：`tools/bw_extract_preprocess.json`（v7，32 条，恢复分页合并器所需的头部折叠、标题提取和 L4/L5 槽位规则；v6 把单段排版 div 容器折叠从 `align-end` 推广到白名单类名并前置到图片 br 清理之前；v7 把加粗/着重号 span 转为按 class token 匹配，修掉组合 class 漏转）。
- 输入 `.epub` 时解包改写后重新打包为 `<原名>.preprocessed.epub`，保留原文件、条目顺序、压缩方式与 `mimetype` 首项；输入目录时**就地**改写。
- `--book-id` 只用于已经确认作品号和内容顺序的 EPUB：第一个内容单元使用 `-01`，后续每遇到一个新的 L4 `h1` 递增内容序；**章名整页图片扉页**（非正文页且 `main` 容器带原版导航锚点 id，如 `<div class="main" id="toc-002">`）同样是新单元起点，递增内容序（`S6_22.06.10` 六个章名均以 SVG 扉页图片承载，全凭此信号切分）；无 h1 的续页和普通全页插图（`main` 无 id）沿用当前表头。输出名形如 `S4_05-07_p-008.xhtml`；其他 XHTML（标准 `nav.xhtml` 除外）与全部图片加完整作品号前缀。图片保留源语义名和页码，如 `i-030.jpg` → `S4_05-i-030.jpg`，不从分页位置猜测内容序。工具同步更新 OPF、NCX、导航、XHTML、CSS 和 SVG 引用。该选项不能代替中日内容确认，不适用于目录模式。
- `tools/bw_page_header_overrides.json` 保存无法仅凭 `h1` 安全判断的已审计分页映射。映射完整列出该书全部 `p-NNN.xhtml`：正整数表示内容序，`null` 表示作品级包装页；`0`、负数或实际分页与映射不完全一致时直接阻断。`S4_05` 已确认 `p-012/p-013` 是后记作者署名之后的尾声（`-10`），`p-014/p-015` 是作者著作目录包装页，不参与正文配对。`S3_02`~`S3_05`、`S3_07`~`S3_11` 已确认后记（あとがき）之后的连续正文页为尾声（后记内容序+1，单页或多页聚合为一个单元），其后的预览插图页仍为包装页（`null`）。未使用显式映射时同样自动识别：后记（`h1` 允许内层 `span` 等行内标签包裹）之后的**连续**正文文本页聚合为单一尾声单元（`sequence+1`），纯插图页与著者介绍/版权页保留原名不合并。**书末附录闩锁**：后记之后一旦遇到非正文页即记为附录起点，其后所有页一律保留原名——该拦截放在 `has_new_h1` 分支**之前**，因为附录里的解说/收录短篇/次卷预告自带 `h1`，只在后记分支内检查会让它们绕过去拿到内容序。**尾声边界是单向的**：后记之后一旦遇到任何非正文页（纯插图页、封底 `hyou4`、著者介绍/版权页），即从该页起进入**书末附录**，其后的页即使本身是文本页（如紧跟照片页的著者/插画师介绍页）也不再获得内容序，避免附录被误当成故事性「尾声」（`S1_15` 的 `p-016` 即此情形）。**著者介绍/版权页的判定只适用于短包装页**：正文段数 ≤ 12 且「著者近影/プロフィール/著者紹介/奥付」等标记出现在页首两段之内才生效；长正文页里叙述性出现这些词（如 `S4_01` 尾声第 63 段「プロフィールを作るのが…」）不会被误判为包装页而丢弃。未使用显式映射时，首个 `p-001` 中以 `※本書`、`※本巻` 或 `※この本` 开头的阅读提示也会自动命名为作品级包装页，从 `p-002` 开始分配正文表头。`--header-map` 可显式指定同格式文件。
- 保留原文件的 BOM 与换行风格（LF/CRLF），并把孤立 `\r`、`\r\r\n` 等脏换行归一化后再应用规则；规则按 JSON 顺序逐条执行，整体幂等（重复运行不再改写）。
- `--check` 校验模式：内存中应用完整转换但不写盘。除内容文件 L1-L6 固定模板外，配合 `--book-id` 还会模拟 XHTML/图片表头重命名，并检查 EPUB `mimetype`/`container.xml`、全部 XML 语法、XHTML/OPF/NCX/nav/CSS/SVG 内部资源引用以及无表头图片。正常处理同样执行这些门禁；有问题时返回非零并阻止写出产物。
- 页首/页尾填充清理：头部折叠规则删除 `main` 后的源排版 `<br/>` 并建立 L4/L5 槽位；「页尾填充br删除」清除最终 `</div>` 前的填充空段/`<br/>`。小节标题折叠为 `h2` 后，`h2` 前后独立的填充 `<br/>` 由「h2前填充br清理」「h2后填充br清理」删除，保证 `h2` 独占一行、两侧无 `<br/>` 排版噪声。「图片前填充br清理」「图片后填充br清理」删除紧贴整段插图（`<p><img/></p>` 或 `<svg>`）上下的填充 `<br/>`，仅匹配纯图片段落，不影响 gaiji 内嵌字形与正文间场景分隔 `<br/>`。「单段排版容器折叠为带类名的p」把只含**一个裸 `<p>`** 的排版 div 容器折叠为 `<p class="…">` 单行（后记署名块、居中插图、章尾右对齐收束句等），白名单为 `align-end`/`align-center`/`align-right`/`gfont`/`font-1em30 start-2em`/`start-4em`/`h-indent-1em`/`h-indent-5em`；多段容器、内层 `<p>` 自带属性的容器一律不折叠。该规则**必须排在「图片前/后填充br清理」之前**：否则折叠后新暴露的 `<br/>`+图片邻接要到第二遍才被清掉，行数随重跑漂移（`S1_14-02` 实测差 3 行）。折叠采用行锚定匹配（`^…\n…\n…$` + `[^\n]*`）而非惰性 `.*?`，因此不会把容器内两段并成一行——旧版 `align-end` 规则的 `</div>` 吞噬缺陷已随之消除。源标题开标签与内容跨行的（如旧约 10 卷 `<p id="toc-001"><span class="font-130per">` 与内容分两行），由「跨行h1折叠为单行」在 h1 折叠后把内部换行折叠掉，保证 L4 `h1` 独占一个物理行。若 `merge_bw_pages` 仍检测到残留，会报告警告（说明规则需增强）。

### 分页源合并为章节文件（跨页衔接处理）

```powershell
python tools/merge_bw_pages.py 分页目录 --book S4_05            # 输出 <book>-NN.xhtml
python tools/merge_bw_pages.py 分页目录 --book S4_05 --dry-run   # 只预览
python tools/merge_bw_pages.py 分页目录 --book S4_05 --out 输出目录/
```

把 `bw_preprocess.py` 处理后的分页目录（`p-NNN.xhtml`，或 `--book-id` 生成的 `S4_05-07_p-NNN.xhtml`）按章节标题（`<h1>`）合并为章节文件，落实 AGENTS.md「换页衔接处理」。带表头分页会保留原内容序；`-00`、作品号混用、同单元表头冲突或重复内容序会阻止写盘：

- **页边界按衔接处两侧页型定间距**：文本+文本（连续两页正文）在前一页末尾段落追加 `class="pb"`，不插入额外空白行；跨整页插图（文本+图片+文本）在图片包裹的 `<p>` 标签中追加 `class="pb"`（如 `<p class="fit pb"><img …/></p>`），图片与前后文本无缝衔接且前后文本段落不额外加换页标记。
- **全页插图页**（`body.p-image` / SVG）保留为图片行，并入其前一章节单元末尾（无缝）；SVG 折叠为单行。
- **图片扉页承载章名**（BW 有些书整章无 `<h1>` 文本，章名画在扉页图里，如 `S6_22.06.10`）：单元开头连续的整页插图页按「篇首插图」并入 **L3 头部行**（`<body…>` 之后、标题前），不在正文区占行；此时 **L3 头部必须取自单元内首个文本页**，否则会沿用图片页的 `fixed-layout-jp.css`、丢掉 `body class="p-text"` 与 `html class="vrtl"`，正文被按固定版面渲染（且会被 `bw_preprocess` 误判为非内容文件而跳过模板校验）。随后来自后续分页头部的首个 `<h2>` 提回 **L5** 槽位，保证正文落在 L6。**章名扉页本身是章节边界**：无表头输入中，非正文整页插图页若 `main` 容器带导航锚点 id（`<div class="main" id="toc-NNN">`），必开启新章节单元（输出「章名扉页」备注），防止后继各章全部并入首章单元（`S6_22.06.10` 曾因此把序章～终章 16 页并成 2937 行单文件）；带表头输入以内容序变化优先，不重复切分。
- **L4 章名从原版目录补回**：上述无文本 h1 的单元，用 EPUB 导航文档（`*navigation*.xhtml`）里指向该单元首页的锚点文本生成 `<h1>`（`attach_nav_titles`）。仅在导航条目与单元首页文件名**精确相等**时补，对不上就留空槽并输出「缺目录标题」待核对——不做模糊猜测。导航文件名匹配用 `^(?:[\w.-]*[-_])?navigation…` 以兼容加过作品号前缀的名字。
- **引子**：第一个 `<h1>` 之前的无标题页合并为独立「引子」单元（L4/L5 空行占位）。
- **后记边界**：后记（`h1` 含あとがき/後記等）之后的正文页不并入后记，作为独立单元（尾声）并输出「后记边界」待核对；全页插图页同理。
- **空占位页**（无文本无图）跳过并报告。
- **页首/页尾 `<br/>` 残留检测**：合并时检测页首/页尾是否有残留填充 `<br/>`（应由 `bw_preprocess` 清理），若发现则报告警告并删除；小节/章节标题（`<h1>/<h2>`）边界的页边界不套换页标记（标题自带分隔），并输出「标题边界」待核对。
- 输出**待人工确认清单**：文本+文本页边界是否同一段落断续（须按语义拼回、勿套换页标记）、标题边界、全页插图归属是否应调整、预处理残留的 `<br/>`。

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

### 外典书库（S5）合订卷拆分（仅限新书导入）

```powershell
python tools/split_s5_epubs.py "<BW 提取源目录>"
python tools/split_s5_epubs.py "<BW 提取源目录>" --packed-out 打包输出目录 --unpacked-out 解包输出目录
```

外典书库的日文原版是合订卷（`とある魔術の禁書目録 外典書庫（N）.epub`），一本含 2–3 个独立作品；中文侧按独立作品分别收录。本工具按 `SPLIT_SPECS` 把合订卷拆成各自独立的作品，并对每一份跑一遍与主工作流相同的导入管线，产出的日文缓存即可直接用 `S5_AA_BB-BB` 表头与中文侧配对。

**拆分范围**（页区间写死在 `SPLIT_SPECS`，按合订卷内的 `p-NNN.xhtml` 划分）：

| 合订卷 | 目标作品 | 页区间 |
| --- | --- | --- |
| 外典書庫（1） | `S5_01_01` 神裂火織編 / `S5_01_02` 『必要悪の教会』特別編入試験編 / `S5_01_03` ロード・トゥ・エンデュミオン | p-001~009 / 010~018 / 019~027 |
| 外典書庫（2） | `S5_02_01` 学芸都市編 / `S5_02_02` 能力実演旅行編 / `S5_02_03` コールドゲーム | p-001~009 / 010~018 / 019~021 |
| 外典書庫（3） | `S5_03_01` アニェーゼの魔術サイドお仕事体験編 / `S5_03_02` バイオハッカー編 | p-001~009 / 010~019 |
| 外典書庫（4） | `S5_04_01` ステートバリウス編 / `S5_04_02` 御坂美琴と食蜂操祈をイチャイチャさせる完全にキレたやり方 | p-001~009 / 010~024 |

**每部作品的处理步骤**：

1. 固定基础设施整体拷贝：`mimetype`、`META-INF/`、全部 `.css`；
2. 按页区间取 `p-NNN.xhtml`（区间内的每一页都必须存在，缺页不会被补齐）；
3. 收集这些页引用到的图片：`img src` 与 `svg` 的 `href`／`xlink:href`，按 OPF 相对路径解析，解析不到或不在包内的引用直接丢弃；
4. 重建独立 OPF：manifest 只保留仍存在于拆分包内的 item，spine 再按保留下来的 item id 过滤，`dc:title` 改写为作品标题；
5. 保存时 `mimetype` 用 `ZIP_STORED`、其余用 `ZIP_DEFLATED`（与 EPUB 容器要求一致）；
6. 复用主工作流的 `bw_preprocess`／`merge_bw_pages`：规则预处理 → 分配 `S5_AA_BB` 表头前缀与资源重命名 → 分页合并为章节 → 注入 pb 样式 → 契约校验（`artifact_contract_issues`）。

**输出**：打包 `.cache/epub-work/packed-epubs/japanese-text/[S5_AA_BB]标题.epub` 与解包目录 `.cache/epub-work/japanese-text/[S5_AA_BB]标题/`（同名目录已存在时先整目录删除再重建）。每部作品打印章节数与契约校验结果，「[校验通过] 契约校验 0 问题」为正常。

**注意**：

- **源目录必须显式传入**（`src` 位置参数）：存放「とある魔術の禁書目録 外典書庫（N）.epub」的 BW 提取目录。传错或目录不存在时按卷打印「[跳过] 不存在」并以退出码 0 正常结束——不会报错，别把它当成已经跑完。输出目录默认在 `.cache/epub-work/` 下，可用 `--packed-out`／`--unpacked-out` 覆盖。
- **页区间与合订卷内的实际分页强绑定**。新卷、或出版社重新排版后，必须回到 BW 提取源核对页区间再更新 `SPLIT_SPECS`；区间错会静默拆出内容错位的作品，且不会报错。
- 依赖 `bw_preprocess` 的内部辅助函数（`load_rules`、`transform_bytes`、`pairing_header_renames`、`apply_entry_renames`、`merge_epub_pages`、`inject_pb_css`、`artifact_contract_issues`、`_resolved_reference`）；改动这些函数的签名或语义会连带影响本工具。
- 输出目标在 `.cache/` 下，且会覆盖同名日文目录。若该作品的日文缓存已有校对成果，先确认再跑。

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

逐文件检查模板符合性（L1-L3 头部结构、L4=h1 独占或空、L5=h2 独占或空（中文 Note 等包装页可为 `<ul>`/`<ol>` 列表包装占位）、L6=正文），并对中日配对文件检查总行数、h2 位置、图片行和独立 `<br/>` 行位置是否一致。`gaiji`/`height-2em` 内嵌字形不计为图片。报告写入 `.cache/epub-work/alignment-check.tsv`。日文独有包装页（`p-*`、`navigation-*`）不参与。

**文本化图片例外**（`alignment_rules.TEXTUAL_IMAGE_HEADERS`，整表头豁免）：中文侧把分页源的整页图片改成文本，行数/h2/图片行/`<br/>` 本就与日文侧不同。两族：

| 表头 | 形态 |
| --- | --- |
| `S2_14-02/04/07/10/13` | 中文把整页「材料」图片重排为样式文本行 |
| `S5_01_01-01`…`S5_04_01-01`（7 部作品的扉页） | 日文是一张整页作品扉页图，中文改为文本化的「简介」页 |

**只有一侧有正文时默认报告**：`一侧有正文另一侧无` 是真实结构差异，不做模板检查也不报差异是缺陷——`S5` 全部 7 部作品的扉页曾因此在报告里完全消失。只有登记在 `TEXTUAL_IMAGE_HEADERS` 里的表头才豁免；两侧都无正文才跳过。

**配对口径**：中日两侧按**同一个作品号**配对（`epub_ids.japanese_book_id` 是恒等映射——日文侧同样是独立作品目录，`split_s5_epubs.py` 用两段作品号命名输出）。

**没有对应作品的书也要检查**：`NON_PAIR_WORK_IDS` 只用于「已确认非同一作品」的常态跳过（如 `S5_02_03` 日文是一页式固定版式、`S6_24.12.10` 日文是画集）；其余单侧存在的作品，缺少对应侧也照常做单侧模板检查，报告里留一行「无日文/中文对应作品，仅单侧模板检查」。这段逻辑曾在配对循环内部，导致没有日文对应的书完全没有检查，且不报错。

**已确认的配对差异例外**：`alignment_rules.PAIR_RULES`（表头 → 规则名）登记逐条确认过的合法结构差异，命中后**只抵消该规则解释得了的问题项**，其余差异照报；报告中留一行备注说明依据：

| 表头 | 规则 | 依据 |
| --- | --- | --- |
| `S5_01_03-06` | `afterword-moved` | 中文侧后记被有意并入同一合订卷的另一部作品（`S5_01_03-Information.xhtml` 明写「后记在 [S5_01_01]…」）。要求截断后行数相等且 `<br/>` 位置一致才生效。 |
| `S5_01_02-09` | `section-order` | 中文侧把小节标题放在分页边界之前、日文快照放在之后。要求是通过「行类型序列」验证的纯互换才生效。 |

**已裁定不纳入模板检查的作品**在 `alignment_rules.TEMPLATE_EXEMPT_WORK_IDS`（`S0_00`、`S6_10.06.26`、`S6_24.12.10`），`check_alignment.py` 与 `check_epub_health.py` 共用这一份；豁免只作用于模板项，`-00`、重复表头等仍会报告。

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

### 中文侧旧合页 `<br/>` 清理

```powershell
python tools/fix_legacy_pagebreak_br.py                 # 全缓存预览
python tools/fix_legacy_pagebreak_br.py --book S4_01    # 指定卷预览
python tools/fix_legacy_pagebreak_br.py --apply         # 写盘
```

中文缓存早期用「该页最后一段之后紧跟 1~2 个独占 `<br/>`」表达 BookWalker 分页边界；现行方案改由日文侧在边界段落上注入 `class="pb"`（见 `merge_bw_pages.add_class_pb`）承载，不再占行，因此这些中文 `<br/>` 已成为纯多余的物理行，直接造成中日行数差。

工具把中日正文行按顺序 1:1 走查，在每个 `class="pb"` 边界上**比较两侧的 `<br/>` 连段数量**：数量相同说明是真场景分隔（一行都不删），只有中文侧多出来的部分才判为旧合页遗留。安全闸：日文侧本来更长、或该文件遗留数超过总行数差（说明别处还缺行、属位置错配）时整体不删除，只报告交人工。模板 L1–L6 槽位内的行不参与删除。

### 中文侧场景分隔 `<br/>` 补回

```powershell
python tools/restore_cn_scene_breaks.py                       # 全缓存预览
python tools/restore_cn_scene_breaks.py --book S6_22.06.10    # 指定卷
python tools/restore_cn_scene_breaks.py --apply               # 写盘
```

上一条工具的反向操作。BW 制作源用独占一行的 `<br/>` 表达段落/场景分隔（旁白↔对话块、视角或时间跳转）；部分中文出版管线丢掉这些空行，而中文样式是 `p { margin: 0 }`，同一位置渲染成平贴排版——既丢视觉分隔，又直接造成中日行数差。按 AGENTS.md「结构元素只要在制作源中真实存在、仅被某侧制作管线丢失，允许在对应位置补回」补回中文侧。

三项硬前提，任一不满足即拒绝写入该文件（宁可留问题，绝不靠插删行硬凑）：

1. **去掉 `<br/>` 后两侧行类型序列逐位相等**（h1/h2/img/div/p 全对得上）——确保只是补空行，而不是拿补行去掩盖段落级差异；
2. 中文侧不得有日文侧没有的 `<br/>`（避免搬错位置或吃掉中文自有分隔）；
3. 补完后中文行数必须**恰好等于**日文行数。

保留中文侧 BOM 与换行风格；`MANUAL_ALIGNMENT_HEADERS` 与不配对文件不参与。实测：`S6_22.06.10` 补回 107 行后该卷问题记录归零；全缓存另有 19 个文件补回 38 行（多为 `Afterwords`/`After_the_Epilogue` 的源内分隔），74 个文件因前提不满足被拒。

### 中日换页标记 pb 同步（写缓存）

```powershell
python tools/sync_pb_tags.py             # 预览（默认，不写盘）
python tools/sync_pb_tags.py --apply     # 写盘
```

落实 AGENTS.md「中日两侧同一位置的换页标记与视觉间隔数量一致」：分页源合并时在日文侧段落追加了 `class="pb"`（不占行），中文侧同一位置若缺 `pb`，本工具补上。与「中文侧旧合页 `<br/>` 清理」是一对——那条负责删掉旧写法的多余物理行，这条负责把不占行的换页标记补齐。

**配对与判定**：从文件名提取表头建立日文→中文映射（支持 `S1_01-02`、`S5_01_03-02`、`S6_22.06.10-06` 三种形式，允许其后跟随 `_语义后缀`；`p-NNN.xhtml` 等包装页不参与），然后**按物理行号**逐行比对：

- 日文行含独立单词 `pb` 的 `class` 属性 → 该行是换页边界；
- 中文同行已有 `pb` → 计入「中文已有 pb」；
- 中文同行没有 `pb` 且是 `<p>` 段 → 在既有 `class` 值末尾追加 `pb`（保留原有 class；无 `class` 属性时写成 `<p class="pb">`）；
- 中文同行不是 `<p>` → 计「非段落」；
- 中文行数不足 → 计「越界」。

后两类计入「异常/不匹配」并逐条打印，**不猜测位置、不做模糊匹配**，也不会为了对齐而插删行。日文侧完全没有 `pb` 的文件直接跳过。

**输出**：逐条打印 `[补全 pb]` 的中日对照（日文原行／中文旧行／中文新行），末尾统计 `日文 pb 总数 / 中文已有 pb / 本次补充 pb / 异常·不匹配 / 涉及修改文件数`。

**实测（2026-09-13 缓存）**：日文 pb 67、中文已有 64、待补 3（`S5_01_03-06_Chapter5.xhtml` 2 处、`S5_02_03-01_Main.xhtml` 1 处）、异常 0，涉及 2 个文件。

**注意**：

- 中日缓存根目录写死为 `.cache/epub-work/{japanese-text,chinese-text}`，无 `--cache` 参数。
- 写盘时按行重写**整个文件**（`"\n".join(lines) + "\n"`），且 Python 默认文本模式把 `\n` 落成平台换行——在 Windows 上即 CRLF。仓库 `.gitattributes` 对 `*.xhtml` 声明 `text eol=lf` 并在入库时归一化，所以行尾差异不进入 `git diff` 与提交内容（`git status` 只会提示「CRLF will be replaced by LF」）；但请留意它是整文件重写，不是逐处替换。
- 行号配对以中日行数对齐为前提：行数不一致只会报「越界」而不会误改，但**两侧行数相同、内容错位**的情形本工具发现不了，需另跑 `check_alignment.py` 把关。
- 只改中文缓存；产物需经 `publish.py` 才会同步到 `EPUB/` 与 OneDrive。

### 段落级差异不做自动拆合

被上面前提 1 拒绝的文件中，真正属于「一段 ↔ 两段」的仅少数，且逐处核对后确认是**中文译本自身的分段/漏译差异**（如 `S1_11-02` 缺日文「うっそだぁ！お前絶対怒ってるし！」整段对白、`S1_19-03` 缺「声が、聞こえた。」、`S1_21-02` 缺「一方通行は、遮断するように言い放った。」）。拆分需补写译文、合并无从下手，按 AGENTS.md「无法安全合并时保留问题并交由人工决策」处理，不由工具代劳。

### 中文侧裸图片行包 `<p>`

```powershell
python tools/wrap_cn_image_lines.py                    # 预览
python tools/wrap_cn_image_lines.py --book S1_25       # 指定卷预览
python tools/wrap_cn_image_lines.py --apply            # 写盘
```

中文侧存在「独占一行的裸 `<img/>`」（不属任何块级段落）。按 AGENTS.md「正文区以顶层块为行对齐原子」「正文中的图片正常占正文行」，图片行应与段落一样写成 `<p><img …/></p>`。工具规则：

- 裸 `<img/>` 独占行 → `<p><img …/></p>`；
- **只**解开「图片专用 div 容器」：一段连续的、内容仅为 `<img/>` 与 `<div>`/`</div>` 且开闭在段内配平的区段，逐图输出 `<p>`，div 去掉；div 上的 class 合并到 `<p>`（如 `<div class="center">` 包三张漫画跨页图 → 三行 `<p class="center"><img/></p>`），居中语义不丢；
- 令牌按**出现顺序**处理：闭标签行上的图片仍取该层 div 的 class（先弹栈会把末图的 `center` 弄丢）；
- 已包在 `<p>` 内的图片、`<svg>` 内的 `<image>`、篇首插图（已在 L3 头部行内）、`nav.xhtml` 一律不碰；含正文文字的 div 容器一律不碰。

安全闸：解包后只剩结构标签的行才允许删除，且**该表头在日文侧有对应文件时禁止删除任何行**（配对文件行数一旦变化即拒绝写入）；写盘前逐文件做 `ET.fromstring` XML 校验。实测：34 个文件、69 行图片转为 `<p>`，除 1 个无日文对应的作品级包装页（`S1_03-Illustrations.xhtml`，14→12）外行数全部不变；图片 `src` 序列与可见文本逐字不变。

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

### 文本字符级规范化（写 `EPUB/`）

```powershell
python tools/text_norm.py                          # 只读报告（根目录默认 EPUB/）
python tools/text_norm.py --apply                  # 写盘
python tools/text_norm.py --pattern "*S4_*"        # 按书目录名筛选
python tools/text_norm.py --apply --report r.md --summary s.txt
```

`check_translation_spec.py` 的**可写执行器**：只落地「替换值唯一 + 1:1 字符映射 + 全库全量命中逐条核对无例外」的规则，其余一律留在检查器里报告、不自动写盘。与检查器的分工是**窄**而不是等价的——本工具的规则表刻意比 `P1`–`P14` 少。

| 规则 | 替换 | 依据 |
| --- | --- | --- |
| `interrobang` | `！？`/`！?` → `？！` | translation-spec 一.4 |
| `ellipsis-period` | 删省略号后的句号（`(?!…)` 排除「……。……」两段独立停顿） | 一.5 |
| `ellipsis-ascii-dot` | 删省略号后的半角句点（`(?!\d)` 避开 `….5`） | 一.5 |
| `dash-codepoint` | `─`(U+2500) → `—`(U+2014) | 一.1 |
| `halfwidth-comma` | 中文后半角逗号 → `，`（吞 ASCII 空格；前导须为中文，故千分位不匹配） | 一.1 |
| `bold-punct` | 把 `<b>` 段内的标点移到加粗外（在该处闭合 `</b>`、写出标点、另起 `<b>`） | 一.8 |

`bold-punct` 是唯一的**行级**规则，不进 `RULES` 表（它处理的是整行内的 `<b>` 段，而不是标签外文本），但和其它规则共用同一套报告口径。判定标准取自**日文傍点自身的字符构成**（实测日文 8397 个傍点段）：允许留在加粗内的是汉字假名、`ー`、`＝`、`〇`、`々`、全角英数字、`％＆♯＃×`、`/` 与空白，中文侧对应保留 `·`（≈`＝`）和 `～`（≈`ー`）；`，。、？！：；「」『』（）…—` 及半角 `,.;:?!()[]`、弯引号等标点一律移出。文字（含中文增译）一律留在加粗内——对齐的是**含义**而不是逐字，一句情感强烈的话不因中日段数对不上就把增译晾在加粗外。

三条保护片段整体保留、不参与切分：XML 实体（`&amp;` 的分号若被拆开会得到非法的 `&amp`，XML 直接报废）、作品号（`[S5_01_01]` 是中文项目的本地化标识，方括号属标识符一部分）、缩写点与小数字（`Mr.`、`A.A.A.`、`.50`）。该规则会增删 `<b>` 标签但**不增删物理行**，可见文字与标点顺序完全不变；执行后纯文本与执行前逐字节相同。

边界与安全闸：

- **标签感知替换**：只改标签之外的文本。标签自身（属性里的 `class`/`href`/内联 `style`）与 `<rt>` 注音、`<style>`/`<script>` 块内容一律原样保留，避免改坏 XML 属性与 CSS。
- **不改行结构**：除 `bold-punct` 只重写标签外，其余规则为 1:1 或缩短替换；两者都不增删物理行，因此不影响中日行数对齐；处理逐字节保留 BOM 与换行风格。
- **fail-safe**：遇到跨行注释、`CDATA` 段或额外行分隔符（U+2028/U+2029/`\x0b`/`\x0c`/`\x85`）的文件拒绝处理并列入报告，不猜测、不部分替换。
- **只写 `EPUB/`**：不写 `.cache/epub-work/`。按流程 C（`EPUB/` 为准）的权威方向，本地 `publish_auto.py` 会把这里的改动回流到 OneDrive 与缓存。
- 明确**不**纳入的规则（各有误报或需判断，理由逐条记在工具源码注释里）：儿化音、NBSP、半角括号、弯引号、单独半角 `!`/`?`、半角句号（枪械口径 `.50`）、系列名、拟声破折号变体、全角 `＆％＝＊＋／`、`・`/`‧`、`!？？` 混合、连续 ASCII 空格、引号不配对。改动规则表前必须先做一次全库全量核对。

`.github/workflows/normalize-epub-text.yml` 每日 04:30（UTC+8）跑 `--apply`，有实际修改才提交，无命中则完全不提交。该 workflow 用 `GITHUB_TOKEN` 推送，GitHub 的防递归机制使其不会触发 `Build EPUB Release`——修复进仓库但不自动发版，需要发版时手动触发。

### EPUB 单侧体检（只读）

```powershell
python tools/check_epub_health.py                    # 终端汇总
python tools/check_epub_health.py --strict           # 有 error 级命中时非零退出
python tools/check_epub_health.py --pattern "*S3_*"
python tools/check_epub_health.py --only bold-punct,ruby,dangling
python tools/check_epub_health.py --tsv r.tsv --json r.json
```

把「**不需要中日对照就能判定**」的机械问题一次报全，作为每日规范化 CI 之外的检查闸。它是**汇总入口**，不是新判定口径的来源：每条判定都取自既有规约或既有工具，报告只输出到终端与 `--tsv`/`--json` 指定路径，**不写 `EPUB/`、不写 `.cache/`、不提交**。

| 检查项 | 判定 |
| --- | --- |
| `XML` | 每个 XHTML 能被 `xml.etree` 解析，且 `<img>` 都带 `src` |
| `template` | 固定行模板与正文行原子性（直接调用 `check_alignment.check_file`） |
| `bold-punct` | `<b>` 段内含标点（直接调用 `text_norm.split_bold_punct`，与每日 CI 同源） |
| `bold-empty` | 空 `<b>` 段 |
| `bold-pair` | `<b>` 开闭标签数量不一致 |
| `ruby` | `<ruby>` 缺 `<rt>` 注音 / ruby 开闭不配对 |
| `seq-00` | 非法内容序 `-00` |
| `dup-header` | 同一本书内重复表头 |
| `seq-gap` | 同一作品内内容序缺号 |
| `img-prefix` | 图片文件名缺完整作品号前缀 |
| `dangling` | XHTML/OPF/CSS 引用的资源或锚点不存在 |

与 `text_norm.py` 同源是有意的：体检报告说「有 N 处 `<b>` 含标点」时，规范化 CI 一定会去改同样这 N 处；两个工具的判定不会漂移。

**检出能力上限**：CI 只有中文 `EPUB/`，看不到 `.cache/` 里的日文侧，所以**中日行错位、加粗范围是否对应日文傍点、注音义务**这类必须对照的问题在 CI 里结构上做不到。单侧检查的上限就是「不需要对照就能判定的问题」；中日对照仍需本地定期跑 `check_alignment.py`。

**刻意不纳入的检查项**（判定不唯一或有误报，纳进来只会制造噪声）：

- **引号配对**：全库有 21 处「开/闭不在同一段」的写法——引语跨段、强调性收尾（`……仍可继续进行。』`）、把原文截断以模拟通讯中断（`「喂，我好歹还是知道要保留点警戒d`）。逐条都需要人工判断该补还是该删，不满足「替换值唯一」。需要时单独逐本人工核查。
- **Note 列表项编号**：它与正文条目号是两套编号，且条目号与普通正文行（如「4.5 个榻榻米的大小」）形式上无法区分，任何判据都会误报。Note 编号一致性由 `check_note_order.py` 在缓存上按「定义顺序 vs 正文首次引用顺序」判定，口径更强。
- **换行符**：`AGENTS.md` 明确「换行符不作为修改对象」，`EPUB/` 出现 CRLF 属仓库容忍的既有态，不是问题，不检查也不报告。

**豁免名单**（`EXEMPT_BOOKS`）：按「书 + 检查项」豁免，不是整本跳过。目前只有三本、只豁免 `template`，且都不是「待修的问题书」而是**已裁定不纳入正文模板检查**的文件：`S0_00`（读前必看，非正文作品）、`S6_10.06.26` 与 `S6_24.12.10`（无 BW 分页源，明确不处理）。豁免外的模板命中数为 0，因此这三本的既有结构差异不会淹没真信号；往名单里加条目等于放宽体检口径，必须同时写明依据。

**负向自检**：`tools/tests/test_check_epub_health.py` 对每个检查项都构造一个能触发它的最小反例，另用一份正常样本确认不误报。体检类工具最大的风险不是漏报，而是判定写错却**永远报 0** 却看上去一切正常，所以这一层测试是必需的：

```powershell
python -m unittest discover -s tools/tests -p "test_check_epub_health.py" -v
```

`.github/workflows/check-epub-health.yml` 每日 06:00（UTC+8，排在每日规范化之后）跑全量测试与 `--strict` 体检，只报告不修复，发现 error 级问题时让 workflow 变红；完整 TSV/JSON 作为 artifact 上传 30 天。`permissions` 只有 `contents: read`。

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

### 译文校对复核（提交级，只读）

```powershell
python tools/proofread_review.py b7515335 2d44cb26     # 复核指定提交
python tools/proofread_review.py --worktree            # 复核未提交的工作区改动
python tools/proofread_review.py b7515335 --path EPUB --out 输出目录/
```

复核「重新校对」这类批量提交时，先把改动从 git 里片段化，再按重要度分级，便于判断哪些必须逐条回原文、哪些可以批量放行。只读，不修改 `EPUB/` 与缓存正文。

产物（默认 `.cache/epub-work/proofread-review/`）：

- `changes.tsv`：`commit / 作品 / 文件 / 行号 / 级别 / 子类 / 旧 / 新`
- `semantic.tsv`：需要回原文判断的片段（`tiny` / `local` / `rewrite`）
- `spec.tsv`：规范确定性改动（`spec`），可批量放行，不进 `semantic.tsv`
- `groups.txt`：语义级按「最小差异」聚类，样例只给**差异前后各 14 字**的上下文

分级口径：

| 级别 | 判定 | 处置 |
|---|---|---|
| `spec` | 改动由 `docs/translation-spec.md` 的条款决定 | 规范级，可批量放行 |
| `rewrite` | 最小差异 > 12 字，或某处整段增删（两侧片段数不等） | 整句/整段重写，抽查 |
| `local` | 最小差异 ≤ 12 字 | 术语、用词、数字等局部替换，逐条看 |
| `tiny` | 最小差异 ≤ 2 字，且差异两侧全是虚词/语气词 | 虚词级微调，仍需回原文但一眼能看完 |

`spec` 子类（`kind` 列）：`punct`（只动标点/空白）、`quote`（引号体例 `「」`/`『』`/弯引号互转）、`glyph`（数字或字母的全半角写法）、`erhua`（去儿化音）、`particle`（规范点名的语气词替换，如 `チッ`→「啧」）。

**规范级是这一层的关键前提**：校对产出物本身遵循 `docs/translation-spec.md`，所以「旧文本的不规范写法 → 规范写法」（半角标点、弯引号、儿化音、非规范语气词）是规范化的必然结果，不是语义改动；把它们混进 `semantic.tsv` 会让真正需要人工判断的改动被淹没。判据只认规范里能确定性判定的形状，且要求**最小差异整体**落在条款内——差异里只要掺着语义成分就交回 `local` / `rewrite`，不做宽松猜测。

两条容易踩的口径：

- **数字与字母不是标点**。判定「只动了标点排版」时只剥标点与空白：若把 `0-9a-zA-Z` 也剥掉，「删掉/改掉数字」（事实性纠错的高发区）会被静默判成 `punct` 放行。
- **`tiny` 不能只看字数**。单看最小差异字数，「念动力 → 念动能力」「第10位 → 第位」都只有 2 字，却是术语与事实改动；因此 `tiny` 要求差异两侧的每个字都落在虚词白名单里，清单外一律按 `local` 处理。

输出同时给出「明显增补」「明显删减」统计（按整片段净长度变化，规范级不计入）；**删减是误删实义成分的高发区**，应重点抽查。

回查原文：`semantic.tsv` / `groups.txt` 只给「旧 => 新」，判定对错必须回日文原文。日文缓存 `S3_01-NN.xhtml` 与中文 `S3_01-NN_*.xhtml` 按内容序 `NN` 一一对应（01=序章 / 02=行间一 / 03=第一章 … 11=终章）；文件内部不是逐行对齐，按关键字检索。需要把日文抽成纯文本时复用 `epub_audit.text_of`，本工具不重复实现。

依赖：`epub_ids.work_id`（作品号解析）、`epub_audit.text_of`（XHTML → 纯文本）。

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
- 输入既可以是 `.epub` 文件，也可以是**已解包的书目录**（按 `META-INF/container.xml` 定位 OPF，缺失时回退 `item/standard.opf`）；目录输入按单本处理，不会被当成「递归找 .epub」。

### 成分与页数分析（含书内实测印刷页，只读）

```powershell
python tools/epub_composition_metrics.py <目录或epub> [--csv OUT.csv] [--pages-per 400] [--all] [--json] [--chars-only]
```

在 `epub_char_count` 的同一套字数口径上追加**印刷页**维度：BookWalker 分页源的正文插图文件名带印刷页码（`S3_13-i-045.jpg` → 第 45 页、`S3_13-i-314-315.jpg` → 第 314-315 页跨页图），且图片在章节 XHTML 中保留原始先后位置，因此「正文累计字符数 → 印刷页」可以标定：

- **密度** = 相邻锚点「字符差 / 页差」的中位数（相邻页差是实测硬事实，不受单张插图占页影响）；
- **锚点之间**按字符比例在实测页差内插值，锚点之外用密度外推，页号单调、不跨章累积漂移；
- 每个成分/子成分按字符累计位置取起止页区间；同一成分内子成分区间按顺序压实，严格递增不重叠。

输出列：`成分 / 子成分 / 全字符 / 页数（换算）/ 印刷页区间 / 印刷页数`（合计行给出全书正文印刷页推算区间）。成分名规范化（序章/第N章/终章、行间、后记、引子/尾声位置规则）与 `epub_char_count` 完全一致；正文按 `<h2>` 展开子成分，`--chars-only` 只按成分输出。

**估算边界**：锚点页本身是实测的，锚点之间按字数比例分配；书首（首个插图之前，通常 30~50 页）无锚点、只能靠密度外推，误差最大，单成分页数约 ±10%。页区间是推算值，不是书内页码标记。默认只读，不修改输入；CSV 默认写到 `.cache/epub-work/composition-metrics/<书目录名>.csv`，不落进书籍目录，避免被 `package_cache_epubs.py` 打进 EPUB。
