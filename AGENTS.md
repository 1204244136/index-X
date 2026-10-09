# index-X Agent 维护规约

文档职责与入口见 [文档索引](docs/README.md)。本文件只写**每轮都要在场的流程与边界**；命名、行模板、排版等按需查阅的细节在「版式规范」一节的指针里。

## 项目定位

本仓库是某系列 EPUB 档案及其构建、校对工具仓库。`EPUB/` 是需要版本化保存的档案主体；维护工具用于可重复地同步、检查和打包档案。

## 目录约定

- `EPUB/`：版本化的 EPUB 解压目录，属于发布源文件。
- `docs/`：规范、裁定与长期维护记录；各文件职责及新增／改名流程统一在 [文档索引](docs/README.md) 维护。版式规范正文在 `epub-naming-spec.md`／`epub-structure-spec.md`／`epub-css-layout-spec.md`；动任何译名前先查 `docs/translation-name-rulings.md`。
- `tools/`：可重复使用、经过验证的维护工具。
- `.github/workflows/`：发布和自动化流程。
- `.agents/skills/`：项目级任务流程与配套模板，属于项目规约、应提交。当前日文源导入、新书成品生成、术语统一与校对复核的流程在各 skill 维护；语言／取舍规范按文档索引定位。
- `.cache/`：本地参考副本与分析产物，不提交；书籍内容写入限制、同步器权限与报告目录按「数据流与编辑边界」执行。

## 系列编号

- `S0`：阅读说明等非正文内容。
- `S1`：旧约主系列，按本仓库的收录顺序编号；SS、SP 也占用顺序号，因此编号不一定等于原作单行本卷号。
- `S2`：新约主系列，按本仓库的收录顺序编号。
- `S3`：创约主系列，按本仓库的收录顺序编号。
- `S4`：《某暗部的少女共栖》系列。
- `S5`：外典系列。日文以「外典书库」合订卷保存，中文以合订卷内的独立作品保存。`S5_AA_BB` 中 `AA` 是日文外典书库卷号，`BB` 是该合订卷内的独立作品号；中间缺号必须保留，不得重排。例如日文 `[S5_01]外典书库(1)` 内的 `S5_01_03-*` 对应中文 `[S5_01_03]…通向恩底弥翁之路X`。
- `S6`：按日期标识的短篇或特别作品，作品号格式为 `S6_YY.MM.DD`。点分隔的日期整体是一个作品标识，不是卷号、章节号或多级后缀。中日两侧可能只收录其中一侧，不得因缺少对应文件而猜测配对。

## 版式规范

命名、行模板、标题分层、译注页结构、分页衔接与移动端排版**不在本文件展开**，按主题查下表；本节只留每轮都要在场的核心不变量。

核心不变量：

- 中日配对靠「表头」这一稳定内容标识，不是目录名、EPUB 页码或语言侧描述后缀。形态为普通主系列 `S<系列>_<卷序>-<内容序>`（`S1_03-05`）、外典 `S5_<合订卷>_<独立作品>-<内容序>`（`S5_01_03-02`）、日期短篇 `S6_YY.MM.DD-<内容序>`、SP 等用稳定名称（`S1_25-Uiharu_Kazari`）。配对先提取完整作品号，不得截断 `S5` 的独立作品号或 `S6` 的日期。
- 数字内容序从 `-01` 开始，`-00` 非法。
- 中文文件名用 `<表头>_<语义后缀>.xhtml` 或 `<作品号>-<包装后缀>.xhtml`；语义后缀保留原有拼写，不为格式化批量改名。
- 图片资源必须带完整作品号前缀，格式为 `<作品号>-<原稳定图片名>.<扩展名>`；重命名后同步 XHTML、OPF、NCX、nav、CSS 与 SVG 引用。
- 中日配对文件两侧总行数一致，L1–L6 固定行模板不随内容有无偏移。

| 主题 | 规范正文 | 什么时候读 |
| --- | --- | --- |
| 表头、中文文件名与包装后缀、图片资源命名 | [EPUB 命名规范](docs/epub-naming-spec.md) | 新增／重命名／配对文件、导入图片、处理历史别名时 |
| 固定行模板、行对齐原子、标题分层、译注页结构、换页衔接、日文侧规范化、包装页与附录边界 | [EPUB 结构规范](docs/epub-structure-spec.md) | 改任何 XHTML 结构、合并分页源、修行对齐、写 Note 页时 |
| 移动端多列分页与插图 CSS 防御 | [EPUB 排版规范](docs/epub-css-layout-spec.md) | 动书籍 `style.css`、插图分页表现或 Reasily 类阅读器版式时 |

## 维护流程

本流程只适用于 EPUB 内容修改。工具和文档改动按 [工具合同](tools/README.md) 中的门禁与测试验证，不执行内容同步。

1. **写前同步**：运行 `python tools/publish_auto.py`，使工作站缓存、归档与 OneDrive 的最新有效内容同步；需要预览时加 `--dry-run`。同步冲突按下一节逐项分析。
2. **分析与写入**：分析优先读缓存；已确认的内容只写 `EPUB/`。新书导入可在显式暂存目录预处理，最终结果必须落到归档；成品生成按 `.agents/skills/volume-import/SKILL.md` 走（交稿、图片、制作信息、简介、日文原文、模板书等材料不齐不动手，先向用户索取）。规范化、修复等写工具默认预览，明确 `--apply` 才写入；暂存模式与路径限制见工具合同。
3. **验证**：按修改类型运行对应门禁，检查 `git status`、变更文件数、`git diff --stat` 并抽查 diff。批量校对产出按 `.agents/skills/proofread-review/SKILL.md` 复核；术语收敛按 `.agents/skills/translation-term-unification/SKILL.md` 执行。
   - 任何改写行内文字的改动（重译、通校、回改、术语替换、标点调整）都可能重新划定加粗边界或挪动标点，写盘后必须重跑字符级规范化并确认 0 命中：`python tools/text_norm.py --dry-run`（可加 `--pattern "*S3_09*"` 限定书籍）。`<b>` 段内含标点同时是 `check_epub_health.py --strict` 与 `publish_auto.py` 发布预检的**阻断项**——留着不修会卡住写后同步，或由每日规范化 CI 代为提交、使「结论 ↔ 落地」分家。加粗口径见 `docs/translation-spec.md` 一.8。
   - 通校／重译这类整批改写同样算「动译名」：整批 `rewrite` 里的用词也要比对 `docs/translation-name-rulings.md`，不得只按日文字面直译；比对方法与案例见 `.agents/skills/proofread-review/SKILL.md` §二.5。
4. **写后同步**：立即再次运行 `python tools/publish_auto.py`，把本次修改发布到 OneDrive，并更新缓存、清单与拉取状态。
5. **留档与提交**：一次内容修改落在两本及以上作品时，在 `docs/maintenance-records/` 记录范围、文件数、依据、统计、验证与必要样例；中日同一作品算一本。单本修改以提交承载，不另留档。留档忠实反映修改事实，候选取舍登记 `docs/translation-name-rulings.md`；明显错误订正与规范执行不算裁定。只暂存本任务文件，成功同步后直接提交，不 push。

拉取、A/B/C 单方向发布、初始设置与全量重建的命令合同见 [工具合同](tools/README.md) 的 C1（同步与发布）。

## 数据流与编辑边界

三处副本各有固定角色：

- `.cache/epub-work/`：只读分析源，不提交。agent 不得编辑、规范化、修复或删除其中的书籍内容；只有拉取与发布同步器可以更新该副本及其清单。工具可在报告／备份目录写工作产物，它们不属于书籍内容；该权限不允许改写缓存书籍或把构建产物放进参考书目录。
- `EPUB/`：唯一版本化内容写入落点。正文、标题、CSS、OPF、NCX/nav 与资源引用的成品修改均在这里完成。
- OneDrive：外部分发与阅读副本，既是拉取输入，也是发布输出。不得直接编辑其中的 `.epub`。

新书导入和测试可写显式暂存目录：目录必须位于归档、仓库缓存与 OneDrive 之外；归档修复入口使用 `--staging` 声明该模式；新书导入入口按合同传入显式输出目录。暂存产物经过验证后才进入 `EPUB/`。共享 `edit_safety.py` 执行写入目标限制，不因传入 `--apply` 而允许写仓库缓存或 OneDrive。配对修复只修改归档中文，日文缓存只读；需要修改日文源结构时在双侧暂存目录完成并按导入合同回流。

接收到文本分析指令时优先读取缓存，因为日文参考更完整；缓存缺失、核对发布状态或实际写入时再读取归档。缓存里的日文文件是处理后的工作源，核对 BW 原始码位、注音、傍点等制作信息必须读取原始分页源，不得称工作源为原样快照。

同一本书有多处未发布改动时，先逐书、逐文件分析差异并自行合并。双方都有有效内容时，把合并结果写入 `EPUB/` 后重新同步；不得默认用 `--from` 或 `--overwrite-cache` 选边。只有依内容与规约无法可靠判断时才询问用户。若曾直接修改 OneDrive，在保全和比较双方改动前不得拉取，以免把外部改动当作新基线覆盖本地内容。

同步成功后中文缓存与 `EPUB/` 逐字节一致、日文缓存与对应 OneDrive 解包内容逐字节一致。缓存可由 `pull.ps1` 重建；重建前必须确认没有尚未发布的工具同步产物。

处理外部目录时使用显式路径，并避免把 OneDrive、临时目录或个人环境信息写入仓库文件。

**CI 例外**：自动规范化 workflow 只修改、验证和提交版本化成品，不连接 OneDrive，也不宣称完成工作站三副本同步。工作站拉取该提交后运行 `publish_auto.py` 回流。CI 无日文参考时只执行单侧门禁，不能据此宣布中日配对已通过。

## 版本控制边界

- 应提交：可重复使用的维护脚本、工具说明、项目规约，以及确认过的档案内容修改。
- commit 信息应使用中文并遵守 Conventional Commits 风格。
- 不应提交：`.cache/`、临时 `scan_*` 脚本、一次性术语修复工具及其映射表、一次性诊断输出、机器本地路径和中间报告。
- `docs/translation-name-rulings.md` 的裁定登记**不单独提交**：与触发该裁定的 `EPUB/` 成品改动**同批提交**，使「结论 ↔ 落地」在同一提交内可对照；只有新建本表或对全表整体整理（判据重订、结构重排）时才单独提交。
- `docs/changelog.md` 已冻结并归档为 `docs/archive/legacy-changelog.md`；两者均禁止继续编辑。
- 不要为了格式化而批量改写 EPUB；保持文件名、目录结构、编码和换行行为稳定。
- 对换行符不敏感：`.gitattributes` 已统一声明文本文件出口为 LF（`text eol=lf`），由 Git 在入库与检出时管理，行尾差异不进版本控制 diff，也不影响阅读和中日行数对齐。项目内部及脚本对换行符（CRLF/LF）不敏感，不作无谓的换行符检查，脚本也不对换行符差异输出任何警告；日常修改文本时无需关心或刻意还原行尾格式，禁止为了「统一换行」而专门批量改写文件。

## Agent 操作边界

- 默认只修改工作区，不自动 push、创建 release 或删除档案；但修改 EPUB 文本并成功同步后，必须直接提交本次任务相关变更，不得跳过 commit。新增或修改 `tools/` 工具不套用该强制提交流程，按工具自身门禁处理。
- 不回滚用户已有修改；发现同步覆盖或大批量变化时先报告统计和代表性 diff。
- 修改同步、审计或发布工具后，至少运行一次对应命令验证；失败项必须在结果中明确列出。
- 读写目标与暂存、CI 例外按「数据流与编辑边界」执行；工具不得通过默认缓存路径绕过该边界。
- 缓存区内相对应的中文与日文 XHTML 应保持行数对齐，以便按行定位内容；检查发现不对齐时，必须明确报告涉及文件及其行数差异。可用 `python tools/check_alignment.py` 检查，判定细则与固定行模板见 [EPUB 结构规范](docs/epub-structure-spec.md)。
- 译名／术语统一执行 `.agents/skills/translation-term-unification/SKILL.md`；成品语言与证据边界以 `docs/translation-spec.md` 为准，已决取舍以 `docs/translation-name-rulings.md` 为准。
- 代码结构问题取用 CodeGraph：符号在哪定义、谁调用它、改动会波及什么、相关测试在哪。MCP 面当前可用 `codegraph_explore`，另挂了 `codegraph_impact`、`codegraph_status`；CLI 等价入口为 `codegraph explore|impact|status|query|callers|callees`。索引覆盖 `tools/*.py` 的符号与 `EPUB/` 的 XHTML 文件节点。
- 正文文本检索一律用 `rg` 或直读，不用 CodeGraph：日语原文、中文译法、术语出现位置、中日对照都属于字面文本，XHTML 正文不构成符号；分析源按「数据流与编辑边界」优先读 `.cache/`。
- CodeGraph 的使用说明不在本仓库维护：`codegraph` 1.6 起 `install` 不再生成 `.cursor/rules/codegraph.mdc`，口径以 MCP server 的 initialize instructions 与 `~/.codex/AGENTS.md` 中上游维护的标记块为准，不要在仓库内重建第二份说明文件。

## 变更说明

维护工具的行为变更应同步更新 `tools/README.md`；但该文件只写工具的定位、入口、参数、数据流、判定口径与可验证行为，**不写历次修订记录与验收结论**（每轮改动规模、通过哪些门禁、遗留项处置等）——这类内容记入 `docs/maintenance-records/`（长期保留的检查结论）。`docs/changelog.md` 已冻结并归档为 `docs/archive/legacy-changelog.md`，两者均禁止继续编辑。工具改动按工具自身测试、检查和文档门禁验证，不执行 EPUB 文本修改的写入前后通用同步。如果新增缓存目录、报告目录或构建产物，必须同时更新 `.gitignore` 和本文件。新增或调整版式规范时，正文写进对应的 `docs/epub-*-spec.md`，本文件只更新指针与核心不变量，不复制条文。

### 工具与记录的边界

`tools/` 只放**会反复使用**的流程工具：拉取、解包、规范化、对齐检查、审计、打包发布，以及新书导入管线（`pull.ps1`、`normalize_paired.py`／`normalize_single.py`、`check_alignment.py`／`check_translation_spec.py`／`check_note_order.py`、`bw_preprocess.py`、`merge_bw_pages.py`、`publish_auto.py`／`publish.py`／`publish_epub.py` 等）。判断标准只有一条：**这个动作会不会在后续新拉取或新导入的书籍上再次发生？**

一次性的内容修订**不新增复用工具，也不保留其临时脚本与映射数据**，改完即删，只把结论落盘：

- 单一术语统一（锚点级收敛，例见[译名裁定总表](docs/translation-name-rulings.md)）、单点错字或译名订正、单卷结构调整、历史遗留的一次性迁移，均属此类。
- 执行口径（显式映射、逐条预检、预检不过则不写盘、只改行内文字不增删行）见 `.agents/skills/translation-term-unification/SKILL.md`；本条只规定：这类修订不新增复用工具，也不把工具与映射数据留在仓库里。
- 留档、裁定登记与提交按「维护流程」和「版本控制边界」执行。
- 不保留的形式包括 `tools/fix_<具体词变体>.py`、`tools/check_<具体术语>.py`、`tools/<术语>_overrides.json` 之类的单点术语工具与映射表，以及写在 `.cache/` 下的 `scan_*`／一次性分析脚本。
- 已执行完毕的一次性判定如需复核或回退，用提交历史（`git show`／`git revert`），而不是重跑工具。

## Agent skills

### Issue tracker

issue 与 spec 以 GitHub Issues 承载（`1204244136/index-X`），通过 `gh` CLI 读写。详见 `docs/agents/issue-tracker.md`。

### Triage labels

保留默认五角色标签词汇：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`，标签字符串与角色同名。详见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文（single-context）：仓库根 `CONTEXT.md` + `docs/adr/`。详见 `docs/agents/domain.md`。
