# EPUB 维护工具

文档职责与入口见 [文档索引](../docs/README.md)。本文件是 `tools/` 的**命令合同**：每个工具的入口、参数、读写范围、门禁与失败边界、测试与所属簇。规范与边界（写成什么样、什么不许做）以 [AGENTS.md](../AGENTS.md) 与版式规范四份文档（[EPUB 命名规范](../docs/epub-naming-spec.md)、[EPUB 结构规范](../docs/epub-structure-spec.md)、[EPUB 排版规范](../docs/epub-css-layout-spec.md)、[EPUB 成品构成规范](../docs/epub-artifact-spec.md)）为准，本文件只留指针、不复述条文；成品语言规范以 [翻译规范](../docs/translation-spec.md) 为准；需要判断分支的流程以 `.agents/skills/` 为准。历史验收与修改统计只在维护记录和提交中保存。

## 三层职责

| 层 | 写什么 | 什么时候看 |
| --- | --- | --- |
| [AGENTS.md](../AGENTS.md) | **规范与边界**：系列编号、版式规范指针、数据流与编辑边界、提交边界 | 任何维护动作前；本文件不复述 |
| 版式规范四份 | **版式条文**：[命名规范](../docs/epub-naming-spec.md)（表头与文件名）、[结构规范](../docs/epub-structure-spec.md)（行模板与结构）、[排版规范](../docs/epub-css-layout-spec.md)（移动端 CSS）、[成品构成规范](../docs/epub-artifact-spec.md)（部件与必备性、元数据对齐） | 动 XHTML／文件名／图片／CSS／容器文件前 |
| 本文件 | **命令合同**：入口、参数、读写范围、门禁与失败边界、测试、簇归属 | 运行任何 `tools/` 命令前 |
| `.agents/skills/` | **流程与判断分支**：材料核对、执行顺序、人工确认点、失败退路 | 做对应任务时（新书导入、日文源导入、校对复核、术语统一） |

同一规则只在一处写正文：规范在 AGENTS 与版式规范三份，命令在本文件，流程在 skill。本文的四个固定说法：**阻断** = 该工具或门禁直接非零退出；**只读** = 不修改输入书籍，允许写显式报告或系统临时产物；**预览** = 默认只报告、显式开关才写盘（写工具用 `--apply`，发布用 `--dry-run`，PowerShell 入口用 `-WhatIf`）；**成员表** = 各簇内「工具｜入口命令｜读写范围｜门禁与失败边界｜测试」五列表。

## 公共输出约定

- **编码**：Python 工具入口统一调用 `cli_output.configure_output()`，stdout／stderr 均为 UTF-8，包括重定向与 `--help`。导入工具模块不调整宿主流。`pull.ps1` 在执行期间匹配 Python 的 UTF-8 输出，结束或异常时恢复宿主编码；可复制到仓库外运行的术语模板就地初始化双流编码。
- **输出流**：正常进度、业务发现、汇总与导出路径使用 stdout；输入／环境错误、无法执行的诊断及警告使用 stderr。业务检查发现的问题仍属于报告内容，不以 stderr 是否为空代替退出码判断。
- **机器格式**：JSON／TSV／CSV 写到 stdout 时保持该格式完整，统计摘要与附加提示走 stderr；空 JSON 列表输出 `[]`，空 TSV 保留列头。显式导出到文件后，stdout 可以报告导出路径。各工具保留业务字段与报告参数，按所属簇合同读取。
- **数量与覆盖**：汇总及机器报告取完整检查结果。仅用于限制样例的 `--top`／`--limit` 不改变总数或退出码；用于局部执行的同名参数须在工具合同中明确。零命中与未完整检查分别说明，不把拒绝处理的文件计作已通过。
- **模式与失败**：预览明确未生成成品，写入成功后才报告已生成。退出码 0 表示完成该工具声明的工作；运行失败或门禁阻断非零，具体 1／2 语义见各入口。显式报告无法写出时非零退出；截断提示只引用实际生成的报告，否则给出导出参数。

公共输出与 GBK 管道环境下的全入口帮助由 `test_cli_output.py` 验证；业务输出的完整性由各工具专用测试验证。

## 路由

正常任务从这张表进；出问题时从下一节的 [阻塞与恢复](#阻塞与恢复) 进。

| 你要做什么 | 簇 | 入口 |
| --- | --- | --- |
| 把本地改动发布到 OneDrive 与缓存 | C1 | `python tools/publish_auto.py --only-books "<side/书目录,...>" --dry-run`，确认后以相同范围执行 |
| 拉 OneDrive 新源进本地参考副本 `.cache/` | C1 | `./tools/pull.ps1 -OnlyBooks "<side/书目录,...>"`（预览 `-WhatIf`） |
| 打发布包／出 release 产物 | C1 | `python tools/package_cache_epubs.py --source EPUB --output output/epubs` |
| 新书交稿做成成品 | C2 | `python tools/import_materials.py …`（材料门禁先行，缺项即停） |
| 日文 BW 源做成工作源 | C2 | `python tools/bw_preprocess.py …`，合并见 `merge_bw_pages.py`；流程见 [bw-source-import skill](../.agents/skills/bw-source-import/SKILL.md) |
| 中日结构／行数对不上 | C4 查 → C3 修 | 查：`python tools/check_alignment.py`，漂移定位加 `python tools/diff_paired_lines.py`；修：`fix_legacy_pagebreak_br.py`／`restore_cn_scene_breaks.py`／`sync_pb_tags.py`（页边界）→ `normalize_paired.py` → `wrap_cn_image_lines.py`／`reorder_notes.py`；预案 P4 |
| 只想检查、不写盘 | C4 | `python tools/check_alignment.py --strict`、`python tools/check_epub_health.py --strict` |
| 查前后呼应有没有被改动改断 | C4 查 → C5 判 | `python tools/check_echo.py --book S1_01`，候选逐条回原文核对（见 [校对复核 skill](../.agents/skills/proofread-review/SKILL.md) 的呼应检查） |
| 核对译名有没有落地 | C4 | `python tools/check_translation_table.py --table 译名表.xlsx --strict` |
| 查彩页上的字在正文哪一行／映射表行号有没有漂 | C4 | `python tools/check_illustration_mapping.py` |
| 复核一批校对改动 | C5 | `python tools/proofread_review.py --worktree` |
| 准备复核取证包、分页阅读或验收子报告 | C5 | `python tools/proofread_session.py --help` |
| 做字符级规范化 | C5 | `python tools/text_norm.py --root EPUB --pattern "*S1_01*" --apply`（默认预览） |
| 查某个词／某句话在哪 | C6 | `python tools/search_text.py "…" --side both` |
| 估算篇幅／换算页数 | C6 | 要「占比」列：`python tools/epub_char_count.py <epub 或目录>`；要「印刷页区间」推算：`python tools/epub_composition_metrics.py <目录或epub>` |

## 阻塞与恢复

工具停下来时的处置预案。每条的「判定」列只写命令，「禁止」列只写不许做的事；规范依据在 [AGENTS.md](../AGENTS.md) 与版式规范三份文档，本条不另立规则。

| # | 触发信号 | 判定 | 允许动作 | 禁止动作 | 簇 | 证据留档 |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | `publish_auto.py` 退出 1：OneDrive 外部更新与本地未发布修改同时存在 | `python tools/publish_auto.py --dry-run` | 逐书逐文件比对三方，把合并结果写入 `EPUB/` 后重新发布 | 不得用 `--from`／`--overwrite-cache` 选边；曾直接改 OneDrive 时，未保全并比较双方改动前不得拉取 | C1 | [publish-auto-identical-change-conflict-2026-09-14.md](../docs/maintenance-records/publish-auto-identical-change-conflict-2026-09-14.md) |
| P2 | 发布停止并给重建提示：某处理侧在清单中全无基线记录 | 侧名取值只有 `chinese-text`／`japanese-text`（`python tools/manifest.py --help`），重建写入 `python tools/manifest.py --update-books <侧>/<书目录>`，例如 `japanese-text/【S5_01】外典书库(1)` | 仅在已确认「缓存即已发布状态」后重建基线 | 不得用清单更新掩盖未发布变化；`--force` 也不跳过成品结构门禁 | C1 | [manifest-baseline-missing-side-2026-09-13.md](../docs/maintenance-records/manifest-baseline-missing-side-2026-09-13.md) |
| P3 | `publish_preflight.py` 非零（预检失败不推进该书发布与基线） | `python tools/publish_preflight.py --source EPUB`（可加 `--jp-root`、`--only-books`） | 按报错类别转到 C3／C4 修，修完重跑预检 | 不得绕过预检发布；不得临时覆盖缓存来做检查 | C1→C3/C4 | — |
| P4 | `check_alignment.py --strict` 或 `check_epub_health.py --strict` 非零 | 对齐用 `--root EPUB --jp-root .cache/epub-work/japanese-text --strict`；漂移定位用 `python tools/diff_paired_lines.py` | 按 C3 的对应工具处理：`fix_legacy_pagebreak_br.py`／`restore_cn_scene_breaks.py`／`sync_pb_tags.py`（页边界）、`wrap_cn_image_lines.py`（图片行）、`normalize_single.py`／`normalize_paired.py`（模板）、`migrate_heading_breaks.py`（标题）、`shift_content_sequences.py`／`fix_empty_placeholders.py`（序号与空页）、`reorder_notes.py`（Note） | 不得临时放宽门禁；不得为凑行数增删结构标签；语义未确认先人工确认 | C4 查→C3 修 | — |
| P5 | `--jp-root` 缺目录或缺书；CI 结构上看不到日文侧 | `./tools/pull.ps1 -WhatIf`、`-Side japanese` | 先拉取建立缓存；确无日文源时只做单侧检查 | 不得据未配对书宣布「双侧通过」 | C1→C4 | — |
| P6 | 上传成功但状态写入失败（`OSError`：外部副本已更新、清单未推进） | 比对 OneDrive 实际内容与 `manifest.json`／`pull-state.tsv` | 按 P1 的冲突流程处理（外部副本当作待合并的一方），必要时重跑发布 | 不得假定「上传失败」直接重传覆盖；不得直接编辑 OneDrive 里的 `.epub` | C1 | [tool-responsibility-cleanup-2026-09-19.md](../docs/maintenance-records/tool-responsibility-cleanup-2026-09-19.md) |
| P7 | CI `normalize-epub-text.yml` 产生了提交（自动规范化／译注自愈／裸图包裹）——非阻塞，属必做后续 | `git log`／`git pull`，比对 CI 提交与本地未发布改动 | 工作站拉取该提交后按 CI 实际作品范围运行 `python tools/publish_auto.py --only-books "<side/书目录,...>"` 回流 | 不得把 CI 提交当作「三副本已同步」；CI 不连 OneDrive | C1 | [AGENTS.md](../AGENTS.md)「CI 例外」 |

## 簇索引

每个工具**只属于一个簇**：有 `__main__` 的 `.py` 进 C1–C6，无 `__main__` 的 `.py` 进 C0；`pull.ps1` 与两个配置 JSON 按消费它们的入口簇归属（`pull.ps1` → C1，BW 规则配置 → C2）。「入口数」是该簇成员表的行数；C0 是横向参考层，排在最后。各簇直达：[C1](#c1-同步与发布)、[C2](#c2-导入与交稿往返)、[C3](#c3-成品结构与配对修复)、[C4](#c4-门禁与体检)、[C5](#c5-内容质量)、[C6](#c6-检索与统计)、[C0](#c0-共享内核)。

| 簇 | 定位（管什么／不管什么） | 入口数 | 主要门禁 |
| --- | --- | --- | --- |
| C1 同步与发布 | 三副本数据流、基线清单、打包与发布前检查；不管内容对错 | 8 | 预检、基线完整性、冲突方向 |
| C2 导入与交稿往返 | 源 ↔ 成品的构建（交稿 → 成品、成品 → 交稿、BW 分页源 → 章节）；不管成品的后续结构与规范 | 13 | 材料七项、逐章物理行数 |
| C3 成品结构与配对修复 | 写盘型结构修复；不负责判定通过与否（判定在 C4） | 10 | 逐边界数量、行数与块对应 |
| C4 门禁与体检 | 只读阻断与诊断；不修内容 | 12 | strict 非零即阻断 |
| C5 内容质量 | 字符级与语义级的内容改动；不决定译名取舍（走 skill） | 5 | 字符级规范化 0 命中 |
| C6 检索与统计 | 只读检索与字数／页数换算；不作语义裁定 | 4 | 无（只读诊断） |
| C0 共享内核 | 无 CLI 的共享规则与原子写入能力；不另建工作流入口 | 19 | 由调用方承担 |

## C1 同步与发布

管三副本之间的数据流与发布门禁；不管内容对错。冲突、基线缺失与上传异常的处置见 [阻塞与恢复](#阻塞与恢复) 的 P1、P2、P6。

| 工具 | 入口命令 | 读写范围 | 门禁与失败边界 | 测试 |
| --- | --- | --- | --- | --- |
| `publish_auto.py` | `python tools/publish_auto.py [--dry-run]` | `--dry-run` 只预览；执行时调用 A／B／C 同步器写缓存、归档与 OneDrive | 完整计划、冲突与范围保护；失败非零，预览不发布【P1】 | `test_publish_auto.py` |
| `pull.ps1` | `./tools/pull.ps1 [-WhatIf] [-Side …] [-OnlyBooks …] [-SyncToEpub]` | 仅处理筛选书；写缓存，`-SyncToEpub` 时写归档 | 写前整批检测选中书的未发布缓存／归档变化，冲突非零且不解包；增量更新基线【P1】 | `test_pull.py`、`test_sync_lock.py`；共享能力：`test_sync_and_rename.py`／`test_path_safety.py` |
| `publish.py` | `python tools/publish.py [--dry-run] [--sync-only]` | 流程 B：缓存 → 归档中文＋打包上传 | 共享发布前检查、基线缺失与冲突阻断【P2】 | `test_sync_and_rename.py`、`test_publish_preflight.py` |
| `publish_epub.py` | `python tools/publish_epub.py [--dry-run]` | 流程 C：归档中文 → 打包上传＋缓存增量镜像；日文只读 | 共享发布前检查、容器／XML／资源【P3】 | `test_sync_and_rename.py`、`test_publish_auto.py` |
| `package_cache_epubs.py` | `python tools/package_cache_epubs.py --source … --output …` | 只读输入；写显式构建目录 | 容器、XML、资源引用；`mimetype` 首项不压缩【无】 | `test_package_cache_epubs.py` |
| `manifest.py` | `python tools/manifest.py --update-books chinese-text/某书目录` | 写 `manifest.json` 基线；与同步入口共用缓存锁 | 只按已确认状态更新，不得掩盖未发布变化【P2】 | `test_publish_auto.py`、`test_sync_and_rename.py`、`test_sync_lock.py` |
| `sync_lock.py` | `python tools/sync_lock.py --cache <缓存根> -- <命令及参数...>` | 缓存级互斥；包装子命令，受控继承同一锁 | 锁忙时退出 1；退出后自动释放；不判断内容取舍【无】 | `test_sync_lock.py` |
| `publish_preflight.py` | `python tools/publish_preflight.py --source EPUB [--jp-root …]` | 只读；写显式报告 | 任一硬错误非零，不推进该书发布与基线；**含 `check_translation_spec.audit_book` 的 error 级**（P1–P25）与 `check_epub_health` 的 `note-structure`【P3】 | `test_publish_preflight.py` |

### 统一入口

```powershell
python tools/publish_auto.py --only-books "chinese-text/【S1_01】某魔法的禁书目录 01" --dry-run
python tools/publish_auto.py --only-books "chinese-text/【S1_01】某魔法的禁书目录 01"
```

读取三处副本与 `manifest.json`／`pull-state.tsv` 的差异，输出逐书方向计划；在所选范围内同步变化文件，打包读取选中书的全部当前内容。省略范围参数会处理全部候选书；共享工作区按 [AGENTS.md](../AGENTS.md)「共享工作区协调」选定本任务范围。同一本地书的缓存修改已包含在归档时选择 C，否则报告冲突；OneDrive 外部更新与本地未发布修改冲突时停止。**例外**：OneDrive 的 `.epub` 与缓存同一本书逐字节相同（解压已完成、清单基线与 `pull-state` 未推进，典型是 `-SyncToEpub` 的下游门禁失败）时不算分叉，报「已完成的拉取」并按流程 A 补跑一次，不要求人工选边。冲突合并的操作边界在 AGENTS，`--from` 不代表可以丢弃另一边有效内容。

参数：`--cache`／`--epub`、`--from auto|cache|epub|onedrive`、`--side`、`--pattern`、`--only-books`、`--dry-run`、`--no-upload`、`--force`（配合显式方向）、`--overwrite-cache`、`--chinese-onedrive`／`--japanese-onedrive`。退出码 1 表示被阻塞或失败；dry-run 只预览，不执行发布门禁与同步。

`prepare_plan(args)` 只读观察本地副本与基线，不输出、不写盘、不调用子命令，返回不可变 `PublicationPlan`：`ready` 包含完整命令，`blocked`／`noop` 的命令为空；预览模式和诊断同时固定。`run_plan(plan)` 只呈现和消费该计划，不重新扫描、选择方向或拼参数。预览零执行，A 预览命令保留 `-WhatIf`；真实执行按 A／B／C 顺序，首个子命令非零后停止。业务阻塞返回 1，空操作与成功返回 0；扫描、解析与进程启动异常不新增吞没处理。

普通和 `--force` 共用命令装配与执行：B 传递所选 `--side` 及两侧 OneDrive 目标，C 只传中文目标，不传它不支持的 side／日文参数；目标目录在计划中解析为绝对路径。`--only-books` 为逗号分隔的精确 `side/书目录` 键，A 传给 `pull.ps1 -OnlyBooks`，B/C 传给对应发布器；与 side、pattern 求交。发布预检仍由实际执行的下游入口承担；单独调用 `prepare_plan` 不锁定磁盘，真实 CLI 在持有缓存锁期间重新准备并执行计划。

### 同步互斥

真实写入入口（统一发布、底层 B/C、拉取及清单 CLI）通过同一缓存根的 `.sync.lock` 协调登记，每个 Python／PowerShell 参与者分别持有自己的系统锁，覆盖扫描、差异判断、镜像／上传和清单／拉取状态更新。其它事务占用时非零退出，全部参与者结束后可重试；父进程中途退出时，存活子进程仍保持保护。明确启动的下游进程继承同一事务标识并持有自己的成员锁，避免 A/B/C 内部调用互相阻塞。异常或进程退出由操作系统释放对应锁，失活成员由下次登记清理，保留的锁文件无需手动删除。`--dry-run`／`-WhatIf` 不创建锁文件，也不执行写入；预览结果不是后续写入的状态保证。锁不隔离同书未完成编辑，任务交接仍按 AGENTS 执行。

### 底层 A／B／C

| 方向 | 命令 | 实际输入／输出 |
| --- | --- | --- |
| A：外部源变化 | `./tools/pull.ps1 -SyncToEpub -OnlyBooks "<side/书目录,...>"` | OneDrive → 缓存；中文变化增量回归档；不打包上传 |
| B：已确认缓存来源 | `python tools/publish.py --only-books "<side/书目录,...>"` | 缓存 → 归档中文＋分别打包上传两侧；同步清单与状态 |
| C：归档内容变化 | `python tools/publish_epub.py --only-books "<chinese-text/书目录,...>"` | 归档中文 → 打包上传＋缓存增量镜像；日文参考只读 |

B 不是 agent 的常规编辑入口，只用于同步器／导入流程已生成并确认的缓存来源；成品修改走 C。三个方向都有 `--dry-run`／`-WhatIf`。B/C 用共享发布前检查读取本次候选：模板与对齐、单侧项目规约、合法容器、全部 XML 及书内资源引用。C 验证归档中文与缓存日文，不临时覆盖缓存来做检查。预检失败不推进该书发布与清单基线。发布先在临时副本完成打包和单书镜像；上传或状态更新失败时回滚本书本地镜像，清单只为完整成功的书更新。

两者支持 `--cache`、`--epub`、`--pattern`、`--only-books`、`--no-upload`、`--force` 和外部目标路径；B 有 `--side`、`--sync-only`，C 有 `--overwrite-cache`。删除随增量镜像传播；`--no-upload` 只省外部上传，不应被描述为完成分发。`--sync-only` 不打包上传，不创建新的已上传事实。

`--force` 不表示跳过成品结构门禁；限定书籍时只重做所选书，保留其它书的已发布清单记录。清单中某处理侧全无基线记录时，发布停止并给出重建提示；仅确认缓存即已发布状态后用 `python tools/manifest.py --update-books chinese-text/某书目录` 重建，不用清单更新掩盖未发布变化。

### 共享发布前检查

```powershell
python tools/publish_preflight.py --source EPUB
python tools/publish_preflight.py --source EPUB --jp-root .cache/epub-work/japanese-text
python tools/publish_preflight.py --source EPUB --only-books chinese-text/某书目录
python tools/publish_preflight.py --source EPUB --calibre
```

`--source` 为中文候选根；`--jp-root` 是可选只读日文参考，省略时输出“仅单侧检查”。`--only-books` 以逗号分隔的 `side/book` 限定书籍，`--calibre` 显式启用全 source 的补充校验，不与 `--only-books` 合用；任一硬错误非零。内部 `validate_publication(cn_root, jp_root=None, book_keys=None)` 返回 bool，复用 alignment、health、note 和 package 的判定实现。

### 拉取

```powershell
./tools/pull.ps1
./tools/pull.ps1 -WhatIf
./tools/pull.ps1 -Side japanese -OnlyBooks "japanese-text/【S4_04】とある暗部の少女共棲(4)"
./tools/pull.ps1 -OnlyBooks "<side/书目录,...>" -Force
```

默认外部源由用户 OneDrive 目录推导；可显式传入 `-ChineseSourceDirectory`、`-JapaneseSourceDirectory`、`-CacheDirectory`、`-EpubDirectory`。`-Side`、`-Pattern` 与 `-OnlyBooks` 求交筛书；按修改时间与大小增量解包，首次建立拉取状态。解包前检查全部待拉取书的缓存差异；`-SyncToEpub` 还检查对应归档差异。本地相对基线的变化若未包含在外部包中，整批停止，不替换缓存、不推进清单或拉取状态；已完成解包而状态未推进的相同内容可继续。`-Force` 只强制重解包，不跳过未发布保护。只更新本次成功书的清单，不把未变化书的新缓存修改当新基线，也不清理范围外书目录。源码读取与包内路径解析由 path safety 共用规则控制。

`-SyncToEpub` 转交发布器时保留 `-Pattern` 中的 `*`、`?` 和 `[]`，不按调用目录的文件展开；筛书结果不受调用目录影响。

### 哈希清单与初始重建

```powershell
python tools/manifest.py --help
./tools/pull.ps1
python tools/publish.py --force --no-upload
```

`manifest.py` 支持缓存扫描与按书／侧更新；`--update-books` 至少给一个键，空选择非零且不写入，首次无清单时也只为指定书建立基线。省略该参数才全量扫描；清单是已确认同步状态的基线。全量初始重建按以上流程进行，不直接把外部 `.epub` 解包到归档。

### 打包工具（CI 和手动使用）

```powershell
python tools/package_cache_epubs.py --source EPUB --output output/epubs --dry-run
python tools/package_cache_epubs.py --source EPUB --output output/epubs --pattern "*S3_11*"
```

`--source` 直接指定书目录集合；省略时使用 `--cache` 与 `--side` 选择缓存。`--pattern` 按书目录名筛选，`--output` 指定构建目录。打包验证容器、XML 和书内资源，ZIP 的 `mimetype` 必须首项且未压缩；产物保留书目录名。输入不修改，输出不进入书籍内部或版本化档案。

发布 CI 先运行工具测试与归档 health，再执行共享容器／XML／资源检查后打包；没有日文源的 CI 明确只做单侧检查。calibre 是本地补充合法性校验，不是云端必需运行时。自动规范化 CI 的提交与工作站回流边界见 AGENTS（预案 P7）。

## C2 导入与交稿往返

管「源 → 成品」的构建：交稿 docx ＋素材 → EPUB 成品，以及 BW 分页源 → 章节文件、S5 合订卷拆分、成品 ↔ 交稿往返。不管成品的后续结构修复（C3）与规范检查（C4）。流程见两个 skill：日文源侧 [bw-source-import skill](../.agents/skills/bw-source-import/SKILL.md)（源 → 日文工作源），交稿侧 [volume-import skill](../.agents/skills/volume-import/SKILL.md)（交稿 → 成品）；本簇只写命令合同。

| 工具 | 入口命令 | 读写范围 | 门禁与失败边界 | 测试 |
| --- | --- | --- | --- | --- |
| `bw_preprocess.py` | `python tools/bw_preprocess.py 原始.epub --book-id S4_05 --check` | 预览默认；写显式产物／暂存；目录目标在 `EPUB/` 可直接 `--apply` | 分页或合并后契约、映射完整性、资源与 XML【无】 | `test_bw_preprocess.py`、`test_import_output_boundaries.py`、`test_bw_pagebreaks.py` |
| `merge_bw_pages.py` | `python tools/merge_bw_pages.py 分页目录 --book S4_05 --dry-run` | 预览默认；`--apply` 必须显式 `--out` | 表头、作品号、序号冲突阻断；边界疑点报告人工【无】 | `test_xhtml_and_merge.py`、`test_image_title_merge.py`、`test_import_output_boundaries.py`、`test_bw_pagebreaks.py` |
| `split_s5_epubs.py` | `python tools/split_s5_epubs.py 源目录 --packed-out … --unpacked-out …` | 预览默认；两个输出路径必填，视作显式暂存 | 全部源、页区间与产物先预检；失败不输出【无】 | `test_split_s5_epubs.py`、`test_bw_preprocess.py` |
| `import_materials.py` | `python tools/import_materials.py --docx … --images … --info … --intro … --work … --book-dir … --jp-root … --template …` | 只读；终端报告 | 七类材料逐项核对，缺项非零并给索取清单【无】 | `test_import_tools.py`（含缺项反例） |
| `import_docx_outline.py` | `python tools/import_docx_outline.py 交稿.docx --check` | 只读；写显式 `--out` | 无 Heading 1、段内换行、注音／译注记号未闭合即阻断【无】 | `test_import_tools.py` |
| `import_align_plan.py` | `python tools/import_align_plan.py 交稿.docx --work S4_04 --book-dir … --out …` | 只读；写显式清单／计划骨架／缺口报告 | 交稿形状门禁；章节一一对应与关系报告【无】 | `test_import_tools.py` |
| `import_build_text.py` | `python tools/import_build_text.py 计划.json --out "EPUB/…" --apply` | 写 `<书目录>/OEBPS/Text/*.xhtml` | 逐章物理行数必须等于日文，任何一章不齐整批不写【无】 | `test_import_tools.py`（含不写盘反例） |
| `import_images.py` | `python tools/import_images.py suggest --src 素材目录 --jp-dir … --work S4_04` | 写 `<书目录>/OEBPS/Images/*` | 归档名必须带作品号前缀、源文件可解码；低置信指纹需人工确认。正文插图可为 0（数量是否与计划一致由 `import_build_text.py` 渲染时逐行断言）【无】 | `test_import_tools.py` |
| `import_build_wrappers.py` | `python tools/import_build_wrappers.py 计划.json --template … --info … --intro … --out … --apply` | 写包装页、`nav.xhtml`／`toc.ncx`／`content.opf`／`mimetype`／`container.xml`／`style.css` | 正文／封面缺失即阻断；彩页为可选项；manifest 与 spine 互指、id 唯一【无】 | `test_import_tools.py` |
| `docx2epub.py` | `python tools/docx2epub.py 交稿.docx --out … --apply --staging` | 预览默认，明确未生成 EPUB；`--quiet` 只保留错误与汇总；写显式成品构建输出 | 源不覆盖，资源／容器验证【无】 | `test_docx_and_notes.py`、`test_import_output_boundaries.py` |
| `epub2docx.py` | `python tools/epub2docx.py 源.epub --out … --apply --staging` | 预览默认；写显式交稿输出 | 源不覆盖，需 calibre【无】 | 输出边界：`test_import_output_boundaries.py`；转换依赖外部 calibre |
| `bw_extract_preprocess.json` | 无 CLI（配置，供 `bw_preprocess.py` 读取） | 只读配置 | 未知页不得默认继承上一内容单元【无】 | `test_bw_preprocess.py` |
| `bw_page_header_overrides.json` | 无 CLI（配置，供 `bw_preprocess.py` 读取） | 只读配置 | 映射必须覆盖实际分页，缺页／额外页／非法序号阻断【无】 | `test_bw_preprocess.py` |

### 交稿 → 成品（六步）

流程与材料清单见 [volume-import skill](../.agents/skills/volume-import/SKILL.md)；本节只写命令合同。六步 = 六个工具／阶段（下面的代码块因 `--check` 与 `suggest`／`apply` 拆成多行），各自只写自己的作用域，任一门禁不过都不写盘：

```powershell
python tools/import_materials.py --docx 交稿.docx --images 素材目录 --info 制作信息.txt `
    --intro 简介.txt --work S4_04 --book-dir "【S4_04】某暗部的少女共栖 4" `
    --jp-root .cache/epub-work/japanese-text --template "EPUB/【S4_03】某暗部的少女共栖 3"
python tools/import_docx_outline.py 交稿.docx --check
python tools/import_docx_outline.py 交稿.docx --out .cache/epub-work/import/outline.tsv
python tools/import_align_plan.py 交稿.docx --work S4_04 --book-dir "【S4_04】某暗部的少女共栖 4" `
    --out .cache/epub-work/import/plan.json --report .cache/epub-work/import/gaps.txt
python tools/import_build_text.py .cache/epub-work/import/plan.json --out "EPUB/【S4_04】…" --apply
python tools/import_images.py suggest --src 素材目录 --jp-dir .cache/…/item/image --work S4_04
python tools/import_images.py apply .cache/epub-work/import/plan.json --out "EPUB/【S4_04】…" --apply
python tools/import_build_wrappers.py .cache/epub-work/import/plan.json --template "EPUB/【S4_03】…" `
    --info 制作信息.txt --intro 简介.txt --out "EPUB/【S4_04】…" --apply --calibre-id 197
```

- `import_materials.py` 是**材料门禁**：交稿、图片素材、制作信息、简介、作品号与书目录名、日文工作源、模板书七项逐项核对。缺项非零退出，并把要补的东西列成可直接发给用户的清单——材料不齐不许开工，不得自拟封面、简介或制作信息。三副本待发布状态需人工用 `publish_auto.py --dry-run` 确认。
- `import_docx_outline.py` 只读诊断，写显式 `--out`。阻断项：无 Heading 1、段内换行（`w:br`）、注音／译注记号未闭合；提示项：全角空格、段内制表符、独占成段的译注。
- `import_align_plan.py` 按**日文物理行**逐行比对（日文一行＝一个行单元，中文侧允许 1:2），输出 `1:1`／`1:2`／`1:0`／`0:1` 关系与建议改动，并生成计划骨架。改动类型只有 `split`／`merge_prev`／`insert_br_after`／`drop`／`note_to_prev` 五种，`para` 用清单里的段落序号。章标题识别覆盖 `引子／序章／第N章／行间（可带副标题，`行　间` 的排版空格先折叠）／深度N（外典书库的专用后缀，写作 `DepthN`）／终章／后记／尾声`；识别不出的条目骨架留空 `fname`，由人工在计划里补。计划是任务工作产物，放 `.cache/epub-work/import/`，不提交。
- `import_build_text.py` 渲染正文（固定行模板、`<ruby>`、Note 页与脚注引用）。**写盘前逐章断言物理行数与日文一致，任何一章不齐整批不写**；只清段落首尾的 ASCII 空格与不换行空格，段内全角空格（对齐／分字）原样保留。译注正文在正文渲染时已由 `esc_ruby` 转成可安全嵌入的行内 XML（含 `<ruby>`／`<b>`），写 Note 页时**原样写入**，不得二次转义（否则译注里的注音会退化成 `&lt;ruby&gt;` 字面文本）。
- `import_images.py`：`suggest` 用 dHash 把素材对到日文原图给命名建议；`apply` 复制并校验作品号前缀、可解码性与指纹，低置信项必须人工看图。`apply` 子命令与 `import_build_wrappers.py` 的显式 `--report` 在预览时也写计划报告，标明未产出；执行成功的报告标明已写入。两入口在任何写入前检查报告目标，拒绝覆盖计划／制作材料，或落入素材、模板、日文参考及成品目录，路径别名同样检查；报告原子写入，执行模式的报告与本批成品写入一并回滚。
- `import_build_wrappers.py` 从模板书取样式表、container 与 calibre 元数据块，生成包装页（Cover／Information／Introduction，计划里有 `role=illustration` 彩页时再加 Illustrations）与 `nav.xhtml`／`toc.ncx`／`content.opf`／`mimetype`。`--info`／`--intro` 是页面 L4 起的内容行（第 1 行 h1、第 2 行空行占位），由用户素材决定；简介页文件名默认 `<作品号>-Introduction.xhtml`，计划里写 `intro_fname` 可让它占某个内容序（S5 外典书库用 `-01`，与日文侧整页作品扉页同序）；manifest 的 item id 用 `id-t{n}`，避免与 metadata 的 `id-1`／`id-2` 冲突（calibre 会报 `DuplicateId`）。
- 六步之后按 C4 跑 `text_norm.py`、`check_alignment.py --strict`、`check_epub_health.py --strict`、`check_note_order.py`、`publish_preflight.py`、`check_epub_validity.py`，再走 C1 的发布。

### BW 提取预处理

```powershell
python tools/bw_preprocess.py 原始.epub --book-id S4_05 --check
python tools/bw_preprocess.py 原始.epub --book-id S4_05 --header-map 映射.json --out 暂存输出 --apply --staging
python tools/bw_preprocess.py 显式分页目录 --dry-run
python tools/bw_preprocess.py 显式章节目录 --merged --check
```

默认预览，`--apply` 才写入；`.epub` 写入必须显式 `--out --staging`，保留源文件并产出预处理包。目录目标在 `EPUB/` 可直接 `--apply`；临时目录就地处理需 `--apply --staging`。`--rules` 指定规则表，`--unpacked`／`--unpacked-dir` 指定解包输出。完整参数由 `--help` 提供。

默认分页契约要求 L3 的 `main` 容器，供合并器定位正文；`--merged` 只适用于目录，按合并后契约验证，不能用分页契约检查已合并章节。`--check` 在内存模拟转换、重命名和资源更新；正常产出使用同一门禁，不只验证标题槽位。

`--book-id` 只用于已确认作品号和内容顺序的包。显式逐页映射保存在 `bw_page_header_overrides.json` 或 `--header-map` 指定文件中，正整数为内容序、null 为包装页；缺页、额外页或非法序号均阻断。图片前缀与全部引用同步更新。无标题尾声／附录边界必须按 [EPUB 命名规范](../docs/epub-naming-spec.md) 与 [EPUB 结构规范](../docs/epub-structure-spec.md) 的附录边界确认，不能以 h1 或页码猜测。

整本纯图册没有文本输入时跳过，不输出产物；`--force-image-only` 是显式强制开关。`S6_24.12.10` 画集本身不归档，其中 SS 的独立转录 EPUB 已恢复常规配对，不能把画集例外套给 SS。

### 分页合并

```powershell
python tools/merge_bw_pages.py 分页目录 --book S4_05 --dry-run
python tools/merge_bw_pages.py 分页目录 --book S4_05 --out 显式章节输出 --apply --staging
```

默认预览，`--apply` 必须显式 `--out`；目标在 `EPUB/` 无需暂存开关，临时输出加 `--staging`。输入须经过 BW 预处理，输出章节已套固定模板。带表头输入保留已确认内容序；作品号混用、非法零序号、冲突或重复序号阻断。没有表头的历史页仅生成临时顺序，最终语义命名须人工确认并更新资源引用。

按 [EPUB 结构规范](../docs/epub-structure-spec.md) 的换页衔接与图片行规则处理 pb、篇首图片与标题；目录标题仅精确匹配单元首页时补入，缺失则保留槽位并报告。文本跨页是否同一段断续、图片归属、标题边界和残留噪声输出待确认项，不自动改译文。

图片分页标记由共享 `add_class_pb` 写在既有外层块：p 包装图标在 p，整行 SVG 标在 SVG；保留原有 class、图片引用、尺寸与 viewBox，不额外包 p、不增删行。章尾整页图片也属于图片边界。BW 合并入口复用 `inject_pb_css` 注入分页样式及 `svg.pb` 块级显示保护，已有 `.pb` 规则不能成为漏掉 SVG 保护的理由。该合同落实 [EPUB 结构规范](../docs/epub-structure-spec.md) 的换页衔接与 [EPUB 排版规范](../docs/epub-css-layout-spec.md) 的图片排版，本文不另立规则。

### S5 合订卷拆分

```powershell
python tools/split_s5_epubs.py 显式源目录 --packed-out 显式打包暂存 --unpacked-out 显式解包暂存
python tools/split_s5_epubs.py 显式源目录 --packed-out 显式打包暂存 --unpacked-out 显式解包暂存 --apply
```

默认预览；两个输出路径均必填，视作显式暂存，不能位于仓库缓存或 OneDrive。`SPLIT_SPECS` 是已确认源卷与页区间的唯一实现数据，新增卷／源重排先核对页区间再改规格。全部指定源、规格、页区间、资源与产物契约在输出前完成验证；源缺失、页缺失或任一契约失败非零退出且不输出成功产物。复用 BW 预处理／合并／资源重命名与容器验证，不另维护第二套导入规则。

### EPUB → DOCX

```powershell
python tools/epub2docx.py 源.epub --out 显式交稿输出 --dry-run
python tools/epub2docx.py 源.epub --out 显式交稿输出 --apply --staging
```

默认预览；`--apply` 必须显式 `--out`，临时输出需 `--staging`。读包或单本解包目录，在临时副本把 ruby 还原为 `|基文[注音]`，调用 calibre `ebook-convert`。`--ebook-convert` 指定转换器，`--extra` 可重复传参数，`--keep-src-epub` 保留转换中间包，`--pattern` 筛选目录，`--quiet` 仅错误与汇总。源不修改。

### DOCX → EPUB

```powershell
python tools/docx2epub.py 交稿.docx --out 显式构建输出 --dry-run
python tools/docx2epub.py 交稿.docx --out 显式构建输出 --unpacked 显式解包输出 --apply --staging
```

默认预览；`--apply` 必须显式 `--out`，或 `--no-pack` 时显式 `--unpacked`；临时输出需 `--staging`。读交稿并生成 X 版 EPUB，恢复 ruby、Note 与模板。作品身份不足时显式 `--series`／`--volume`，可传 `--title`／`--author`／`--language`、`--css`、`--images-from`、`--cover`、重复 `--illustrations-before`／`--illustrations-after`。`--no-pack` 只生成解包产物，`--pattern` 筛选、`--quiet` 控制显示。有包输出复用 `package_book`，`--no-pack` 也执行资源／容器校验。推荐先转换到暂存并验证后再进入归档；交稿规范不在成品规范里反向要求。

## C3 成品结构与配对修复

写盘型结构修复：模板、标题、序号、页边界、图片行、Note。判定通过与否属于 C4，本簇不负责宣布「已对齐」。标题／页边界的语义未确认时，工具输出待人工项并保留内容；译文选词不由结构工具自动处理。

归档规范化和修复入口默认只预览，显式 `--apply` 才写。`--staging` 只允许显式暂存目录；共享路径保护始终拒绝仓库 `.cache` 和 OneDrive 内容写入。单侧修改指定 `EPUB/`；配对修改使用 `--root EPUB --jp-root .cache/epub-work/japanese-text`，日文目录仅读。双侧暂存处理使用 `--cache <暂存根> --staging`，暂存根包含 `chinese-text/` 和 `japanese-text/`。`--dry-run` 保留为预览兼容参数，与 `--apply` 互斥；它不代替写入授权或路径验证。

| 工具 | 入口命令 | 读写范围 | 门禁与失败边界 | 测试 |
| --- | --- | --- | --- | --- |
| `normalize_single.py` | `python tools/normalize_single.py --dir EPUB/某书/OEBPS/Text [--apply]` | 预览默认；写 `EPUB/`；`--staging` 写显式暂存 | 共用模板规则；未知暂存路径按路径识别，不保证双侧对齐【无】 | CLI：`test_edit_safety.py`；模板规则：`test_xhtml_and_merge.py` |
| `normalize_paired.py` | `python tools/normalize_paired.py --root EPUB --jp-root .cache/epub-work/japanese-text --book S1_01 [--apply]` | 预览默认；归档模式只写中文，日文只读；双侧暂存模式才可改两侧 | 配对写入验证行数，不靠重排凑齐【无】 | CLI：`test_normalize_paired_scope.py`、`test_edit_safety.py`；模板规则：`test_xhtml_and_merge.py` |
| `migrate_heading_breaks.py` | `python tools/migrate_heading_breaks.py --cache EPUB --book "*S1_01*" [--apply]` | 预览默认；写同一书 XHTML 与被引用 CSS | 全书预检未知结构、路径越界、样式缺失与按层文字不变，任一失败不开始写入【无】 | `test_heading_breaks.py` |
| `shift_content_sequences.py` | `python tools/shift_content_sequences.py EPUB/某书 --work-id S4_05 --offset 1 [--apply]` | 预览默认；改序号、文件名与 XHTML／OPF／NCX／nav／CSS／SVG 引用 | 重命名碰撞、不合法序号；歧义旧裸页引用保持不动并报告【无】 | `test_shift_content_sequences.py`、`test_sync_and_rename.py` |
| `fix_empty_placeholders.py` | `python tools/fix_empty_placeholders.py --cache 显式书籍根 [--apply]` | 预览默认；删除编号空页、前移后续序号与引用 | 空页资格（无文本、无图/SVG）与前后邻居条件；OPF／NCX／nav 条目连带删除【无】 | `test_sync_and_rename.py`、`test_edit_safety.py`（动态） |
| `fix_legacy_pagebreak_br.py` | `python tools/fix_legacy_pagebreak_br.py --root EPUB --jp-root .cache/epub-work/japanese-text --book S1_01 [--apply]` | 预览默认；只写中文，日文只读 | 逐边界比较两侧 `<br/>` 连段数量；数量一致不得删，超差拒删交人工【P4】 | `test_fix_legacy_pagebreak_br.py`、`test_edit_safety.py`、`test_xhtml_structure.py` |
| `restore_cn_scene_breaks.py` | `python tools/restore_cn_scene_breaks.py --root EPUB --jp-root … --book S6_22.06.10 [--apply]` | 预览默认；只写中文 | 只补有源证据且总差额一致的场景分隔；条件不足拒绝【P4】 | `test_restore_cn_scene_breaks.py`、`test_edit_safety.py` |
| `sync_pb_tags.py` | `python tools/sync_pb_tags.py --root EPUB --jp-root .cache/epub-work/japanese-text --book S1_01 [--apply]` | 预览默认；只写中文 | 段落一一对应时补 class，不增删行；不一一对应即拒绝【P4】 | `test_xhtml_structure.py`、`test_edit_safety.py` |
| `wrap_cn_image_lines.py` | `python tools/wrap_cn_image_lines.py --root EPUB --book S1_01 [--wrap-only] [--apply]` | 预览默认；写中文归档／显式暂存中文 | 图片专用容器、配平与行数不变量；`--wrap-only` 仅包装裸 img、不删结构行【无】 | `test_wrap_cn_image_lines.py`、`test_edit_safety.py`（动态） |
| `reorder_notes.py` | `python tools/reorder_notes.py --root EPUB --pattern "*S1_01*" [--apply] [--no-backup]` | 预览默认；只重排 Note 条目，保留 ID 与正文引用；备份默认 `.cache/reorder-backup/` | 完整引用预检（条目、ID、正文引用），不通过不写；**容器非 `<ul>…</ul>` 时显式拒绝并报告**（规范要求 `<ul>`，`<ol>` 不抛异常）【无】 | CLI：`test_edit_safety.py`；共享规则：`test_docx_and_notes.py` |

局部任务的范围入口：single 选显式文件／`--dir`／文件 pattern；paired 选重复 `--book`／`--file` 或单书根；heading 选重复 `--book` glob；shift 与 empty 指定单书根；legacy／restore／pb／wrap 用 `--book`；notes 用书名 `--pattern`。省略筛选时可能处理整个根目录，`--apply` 仅切换写入模式，不缩小范围。

### 固定模板规范化

```powershell
python tools/normalize_single.py --dir EPUB/某书/OEBPS/Text
python tools/normalize_single.py --dir EPUB/某书/OEBPS/Text --apply
python tools/normalize_paired.py --root EPUB --jp-root .cache/epub-work/japanese-text --book S1_01
python tools/normalize_paired.py --root EPUB --jp-root .cache/epub-work/japanese-text --book S1_01 --apply
python tools/normalize_paired.py --root EPUB --jp-root .cache/epub-work/japanese-text --file "EPUB/某书/OEBPS/Text/S1_01-01_Prologue.xhtml"
python tools/normalize_paired.py --cache 暂存根 --staging --apply
```

single 只处理命令行指定文件或 `--dir`／`--pattern`，可用 `--side cn|jp` 明确重建侧；归档默认中文，未知暂存路径按路径识别，不保证双侧对齐。paired 的 `--root`／`--jp-root` 接受库根或单书目录；`--book <完整作品号>` 与 `--file <中文 XHTML 路径>` 均可重复，文件路径相对当前目录，二者求交后才索引和预检。未知作品、无效／越界文件及空交集非零退出；选中表头有重复仍阻断，无关作品或表头不参与检查。不加筛选参数处理所给根目录全部内容。无日文书与已裁定结构特例仍按原合同跳过；缺单个日文文件时仅规范化中文。归档模式仅读日文，双侧暂存模式只修改选中的中日文件。两者调用 `xhtml_template.py`，不承担历史多层标题语义迁移。行模板规则与豁免事实分别在 [EPUB 结构规范](../docs/epub-structure-spec.md) 和 `alignment_rules.py`。

### 多层标题迁移

```powershell
python tools/migrate_heading_breaks.py --cache EPUB --book "*S1_01*"
python tools/migrate_heading_breaks.py --cache EPUB --book "*S1_01*" --apply
```

`--book GLOB` 可重复，`--verbose` 逐书列计划。按整书计划同时改变 XHTML／被引用 CSS，预检未知结构、路径越界、样式缺失和分层文字变化，任一失败不开始写入；写入失败回滚该书已写文件。它负责迁移合同，标题正文规范在 [EPUB 结构规范](../docs/epub-structure-spec.md)。

### 内容序平移与空页清理

```powershell
python tools/shift_content_sequences.py EPUB/某书 --work-id S4_05 --offset 1
python tools/shift_content_sequences.py EPUB/某书 --work-id S4_05 --offset 1 --apply
python tools/fix_empty_placeholders.py --cache 显式书籍根
```

shift 用单次映射改文件与 XHTML/OPF/NCX/nav/CSS/SVG/XML 引用，防止相邻序号级联覆盖；歧义旧裸页引用保持不动并报告。空页工具只删除经判定无文本、无图/SVG 的编号页并前移后续序号，默认预览、`--apply` 写入。日文修改在显式暂存模式完成，不修改参考缓存。

### 配对页边界修复

```powershell
python tools/fix_legacy_pagebreak_br.py --root EPUB --jp-root .cache/epub-work/japanese-text --book S1_01
python tools/restore_cn_scene_breaks.py --root EPUB --jp-root .cache/epub-work/japanese-text --book S6_22.06.10
python tools/sync_pb_tags.py --root EPUB --jp-root .cache/epub-work/japanese-text --book S1_01
```

这些入口默认预览，确认后加 `--apply`；只写中文，日文仅读。legacy 删除逐边界确认的多余旧换页行；restore 只补有源证据且总差额一致的场景分隔；pb 在一一对应段落添加缺失 class，不增删行。行数、块类型或差额条件不足时拒绝；真实一段对多段关系先人工确认语义，不由这些工具拆合。

### 中文图片行包装

```powershell
python tools/wrap_cn_image_lines.py --root EPUB --book S1_01 --wrap-only
python tools/wrap_cn_image_lines.py --root EPUB --jp-root .cache/epub-work/japanese-text --book S1_01 --apply
```

`--wrap-only` 仅包装裸 img、不删结构行；完整模式只接受配平的图片专用 div 区段，改写删除结构行前需指定日文参考并验证配对行数。普通带语义 div 不处理。输出修改计划与拒绝原因，默认预览。

### Note 顺序重排

```powershell
python tools/reorder_notes.py --root EPUB --pattern "*S1_01*"
python tools/reorder_notes.py --root EPUB --pattern "*S1_01*" --apply --no-backup
```

写入前先检查条目可解析、ID 无重复且条目与正文引用完整对应，再按正文首次引用顺序计划 Note 列表的物理排列；只移动已有 `<li>`，不重写条目内容、`id`、`href` 或正文。缺号或数字顺序不同不触发修改；稳定标识与新增 ID 分配规则见 [EPUB 结构规范](../docs/epub-structure-spec.md) 四。报告保留兼容字段：`mapping` 中每个旧 ID 映射到自身，`ref_rewrites` 恒为 0，`files_touched` 只列实际改动的 Note 文件。默认预览，备份默认 `.cache/reorder-backup/`，它是工作产物而非正文编辑目标；可用 `--backup` 指定，`--no-backup` 用于已由 Git 保存的归档或 CI。`--pattern` 限定书籍。参数中的 `--cache` 是读源兼容入口，不能用于写缓存。顺序判定本身在 C4 的 `check_note_order.py`。

## C4 门禁与体检

只读阻断与诊断：判定通过与否，不改内容。修的理由与工具在 C3，内容级改动在 C5。门禁必须有能触发失败的最小反例（见 C0 的验证要求）。

| 工具 | 入口命令 | 读写范围 | 门禁与失败边界 | 测试 |
| --- | --- | --- | --- | --- |
| `check_alignment.py` | `python tools/check_alignment.py --root EPUB --jp-root .cache/epub-work/japanese-text --strict` | 只读；写 `--output` 报告 | 模板、原子块、完整表头、行数与 h1/h2/图片/br/pb 位置；strict 非零【P4】 | `test_alignment.py` |
| `diff_paired_lines.py` | `python tools/diff_paired_lines.py --work S3_01 --tsv 显式报告.tsv` | 只读；写 TSV／HTML 诊断 | 行号对齐；不等长时序列诊断，不修正文【无】 | `test_diff_paired_lines.py` |
| `check_semantic_alignment.py` | `python tools/check_semantic_alignment.py --work S3_01 --strict` | 只读；写语义诊断报告；L2 模型运行时只读 | strict 全范围 L2；环境失败及未通过结果非零【P4】 | `test_check_semantic_alignment.py`、`test_diff_paired_lines.py` |
| `check_note_order.py` | `python tools/check_note_order.py --root EPUB` | 只读；写 TSV／JSON／Markdown | 未定义／重复／未引用与阅读顺序问题【无】 | `test_check_note_order.py`；共享规则：`test_docx_and_notes.py` |
| `check_epub_health.py` | `python tools/check_epub_health.py --root EPUB --strict` | 只读；写显式 TSV／JSON | 单侧项目规约；strict 遇 error 非零【P4】 | `test_check_epub_health.py`（每项含负例） |
| `check_translation_spec.py` | `python tools/check_translation_spec.py --cache EPUB --output 显式报告目录` | 只读；写 TSV／JSON／Markdown | P1–P25 规则报告；**error 级由 `publish_preflight.py` 接入发布阻断**【P3】，warning／info 不自动当缺陷 | `test_translation_spec.py` |
| `check_translation_table.py` | `python tools/check_translation_table.py --table 显式译名表.xlsx --strict` | 只读外部 xlsx＋日文缓存＋中文归档＋译名裁定总表；写本地核对报告 | 折叠 → 同形例外 → 裁定表（含注音判定）→ 译名表；strict 存在待判未落地项非零【无】 | `test_check_translation_table.py` |
| `compare_epub_images.py` | `python tools/compare_epub_images.py --pattern "*S3_*" --output 显式报告目录` | 只读；写图片核对报告 | 字节／像素相同与感知候选分开；候选需视觉确认【无】 | `test_compare_epub_images.py` |
| `check_epub_validity.py` | `python tools/check_epub_validity.py EPUB --structural --strict` | 只读；写显式报告；系统临时解包 | calibre 补充检查；strict 过滤后仍有问题为 1，环境／输入前提错误为 2【无】 | `test_calibre_validity.py` |
| `check_project_docs.py` | `python tools/check_project_docs.py` | 只读；终端报告 | 本地链接／锚点、索引登记与回指、工具簇归属与单一来源；缺项非零【无】 | `test_check_project_docs.py` |
| `check_echo.py` | `python tools/check_echo.py --book S1_01 --book S1_02`／`--convention "<日文正则>" --convention-words "<中文正则表>"` | 只读；写 `--out` 候选清单或惯例报告 | 只定位呼应候选（片段多译／同源复现／引述回指）与全库用词分布，不判定、不阻断【无】 | `test_check_echo.py` |
| `check_illustration_mapping.py` | `python tools/check_illustration_mapping.py [--doc …] [--jp-root …] [--json …]` | 只读 `docs/illustration-text-mapping.md` 与日文缓存；写 `--json` 显式报告 | 逐行回查物理行号；不符时按「正文原句」重定位并给建议行号，未解析非零；缓存缺失为 2【无】 | `test_check_illustration_mapping.py` |

- **依赖**：`compare_epub_images.py` 需要 `Pillow`（`python -m pip install Pillow`），与 `image_signature.py` 同一口径：属**可选依赖**，CI 只用官方 Python 环境、不预装第三方包。因此 `test_compare_epub_images.py` 在无 Pillow 环境下整组跳过，而不是让测试采集失败；采集阶段失败会中断整个 `unittest discover`，使发布流水线在「Validate tools and publication source」一步整条中止。

### 呼应检查

```powershell
python tools/check_echo.py --book S1_01 --book S1_02
python tools/check_echo.py --book S1_01 --out .cache/epub-work/echo-check
python tools/check_echo.py --book S1_01 --include-marker-quotes   # 实验分支，候选量大
```

定位作品内「应当一致」的呼应点候选：**同一日文片段在作品内出现多次而中文译法不一致**（并按 `实词／语体／虚词` 标注差异性质、据此排序）、**日文相似行对**（原句及其引述／复现形态）、**日语侧引文回全文找出的疑似出处**（`『…』` 引用符，或 `って／とか` 引述助词——后者默认关闭）。默认读 `EPUB/` 与 `.cache/epub-work/japanese-text/`，按内容序配平行号；输出 `--out` 目录下每作品一份 `*-呼应候选.md` 与 `summary.md`。

配对使用 `xhtml_structure.py` 的共享表头索引，排除包装页；`alignment_rules.py` 已登记的非同一形态作品、人工对齐、文本化图片与特殊配对单元不做通用逐行比较，逐项说明跳过原因。普通单元缺对照、行数不等或行类型错位时跳过该单元；同侧重复表头时跳过整部作品，均不猜测偏移或把不可靠记录送入候选／惯例统计。

相似行召回使用覆盖全部起点的 n-gram 倒排索引，单字插入／删除造成的位移不会因奇偶起点不同而丢失全部公共键；相似度阈值和高频片段降噪仍单独生效。全位置桶超过 40 行时回退原有偶数起点桶，该桶仍超过 40 行则忽略，避免扩充索引反而滤掉原先由稀疏桶召回的句对。

引述候选带两级证据：`relation` = `exact`（日语逐字同形）／`wraps`（**引述升级**：引述比被引处更完整更逐字，被引处必须就是引述的版本）／`within`／`fuzzy`；`cn_class` = 中文两侧差异性质。`--include-marker-quotes` 额外扫 `って／とか` 形态的改写式引述（日文措辞与全文不同、中文仍保留引号与回指词），**候选量约为默认的 3 倍且需人工筛**，只在通校收尾专查时开。

**降噪规则**（每条都有实测依据，见分片报告）：元数据行（`<title>`／`<meta>`／`<link>`／XML 声明）不参与——各文件这些行同号，会造出假同源对；含长音／重复假名串的行（惨叫、拟声）不进类 2——S6_24.06.07 的 190 对里 79 对属此类；类 3 要求**出处必须在引述处之前**（引述是回指前文，方向相反的配对多是误配）；`fuzzy`（仅 n-gram 相似、互不包含）要求覆盖率 ≥ 0.8；引文不含平假名（纯专名／名词短语，如 `『ブラフマーアストラ』`）不列为候选。实测降噪幅度：类 3 在 S5_04_01 由 31→2、S5_03_02 由 7→1、S5_01_03 由 86→27；类 2 在 S6_24.06.07 由 190→101。

只读、不判定、不设阈值：输出是**候选**，构成呼应与否、哪一侧该改，必须逐条回日文原文核对（流程与判定纪律见 [校对复核 skill](../.agents/skills/proofread-review/SKILL.md)）。差异性质只是提示——`实词` 不必然是异译（同义改写同样命中），`虚词` 也不必然能并存；中文两侧字形不同不等于必须统一，判断依据是日语侧的语气层。它补的是既有门禁查不到的一维——同一句日文被译成多种说法时，行数、模板、XML、加粗、术语裁定全部照常通过。

### 全库惯例统计

候选只说明「应当一致」，不说明往哪边一致。涉及**高频叙述定型**（同一表达在全库出现数十次以上，如 `息を吐く`、`微笑む`、`顔を上げる`）时，只看本卷会得出反向结论——实测 S5_03_02 卷内 `そっと息を吐く` 以「吐气」居多（26 行中吐气 14、叹气 10），据这个局部多数把一处「轻叹一口气」改成「吐气」；而全库该说法是「叹气」占优（226 行中叹气 135、吐气 41），改动方向与全书相反，随后回退（`cbee10ca`）。

```powershell
python tools/check_echo.py --convention "呆れたように息を吐" --convention "そっと息を吐" --convention-words "叹[气了息]|叹息|无奈,吐[出了气]|呼[出了]|呼气"
python tools/check_echo.py --convention "そっと息を吐" --convention-books "S5_03_02,S3_04" --convention-min-book 5
```

多个 `--convention` 各成一组、按给出顺序取首个命中（互斥分组）；日文正则按**连续文本**写即可，注音剥除留下的空格（`呆 れ たように`）会自动忽略。`--convention-words` 是中文侧词表，**词条按正则解释**——中文说法在句中被助词隔开（「叹气」常写作「叹了口气」），按字面比对会大面积漏判（实测 92.5% 的行落进「未分类」）。`--convention-books` 限定作品，`--convention-min-book` 控制分卷分布只列达到该行数的作品。

输出含匹配总数、各词占比、**分卷分布**（用于识别例外卷——同一说法在各卷的倾向可能相反）与未分类样例（据此补词表）。终端与 `convention.md` 同时列出请求作品数、有可靠配对的作品数、模式命中作品数、可靠配对行数，以及部分覆盖、零覆盖的作品号和全部配对告警／跳过原因；重复作品号只统计一次。缺少根目录或没有中日目录交集也明确报告；有可靠配对但模式未命中的作品不算零覆盖。未分类只统计可靠配对中未命中词表的行，跳过的配对不计入它；未分类占比高说明词表覆盖不全，不代表该行没有译法，`0` 命中的词条同理。只统计、不判定，取形方向仍须回原文并结合裁定。

### 对齐检查

```powershell
python tools/check_alignment.py --strict
python tools/check_alignment.py --root EPUB --jp-root .cache/epub-work/japanese-text --strict
```

检查双侧模板及完整表头配对、行数和 h1/h2、图片、独占 br、pb 的物理位置。已确认配对规则只调整有依据的共同范围／顺序，其余结构差异照常阻断；位置规范唯一在 [EPUB 结构规范](../docs/epub-structure-spec.md)。支持 `--cache` 旧双侧根、`--root` 中文与 `--jp-root` 日文独立根、重复 `--book` 与 `--output` 报告；L6 标准正文必须为 p，中文列表包装页可为 li；中文作品级包装页原有多段语义 div 的开标记与完整首段 p 同行也可保留。裸 div 或裸文字不作标准正文豁免。普通模式完整报告后返回成功，strict 有问题非零。缺侧目录按空集合处理，不应据未配对书宣布双侧通过。例外从 `alignment_rules.py` 读取，报告应保留实际检查与未配对范围。

### 逐行漂移诊断

```powershell
python tools/diff_paired_lines.py --work S3_01 --tsv 显式报告.tsv
python tools/diff_paired_lines.py 日文.xhtml 中文.xhtml --html 显式诊断.html
```

同长度直接按物理行对齐，不等长才回退序列诊断；结果为结构／语义启发式候选，不作文字写入。支持 `--cache`、重复 `--work`、`--batch`、`--only-diff`、`--all`、`--no-progress`。批量问题非零，HTML／TSV 只写报告。

### 语义逐行对齐

```powershell
python tools/check_semantic_alignment.py --l1-only
python tools/check_semantic_alignment.py --auto-audit --top 20
python tools/check_semantic_alignment.py --work S3_01 --strict
python tools/check_semantic_alignment.py --strict --betweenlines-dir 显式BetweenLines目录
```

L1 是 CPU 初筛，L2 使用多语言矢量模型分析窗口。非 strict 的 `--auto-audit` 默认只诊断前 20 项，`--top` 限制诊断数量；该输出不能称全范围门禁。

strict 先执行结构前检，再对所选作品／表头范围执行 L2 完整检查，禁止与 `--l1-only` 或 `--top` 合用。已确认 `PAIR_RULES` 只解释对应结构差异；后记迁出时只检查共同正文，并在 TSV“结构范围说明”列标明实际范围，未被规则解释的尾部缺行仍失败。模型、运行时或输入不完整时非零退出，不降级成“无问题”。`--include-exempt` 可用于人工诊断已登记豁免；`--cache`、`--out` 指定输入报告。

L2 运行时由 `--vector-python`／`--betweenlines-dir`、`BETWEENLINES_PYTHON`／`BETWEENLINES_DIR` 或相邻 BetweenLines checkout 动态定位；不写私人机器路径。记录模型、环境与外部 checkout 版本，模型结果仍需结合原文判断。

### Note 顺序检查

```powershell
python tools/check_note_order.py --root EPUB
```

只读检查 Note 条目的物理顺序是否等于正文首次引用顺序，并报告重复 ID、悬空引用与未引用条目；允许缺号与数字顺序不同，不检查数值连续性或数值排序。ID 格式与属性由 `check_epub_health.py` 的 `note-structure` 检查。在输出目录生成 `note-order-check.tsv`／JSON／Markdown。TSV 每本 Note 一行，列为 `book`、`note_file`、`defined_order`、`appearance_order`、`first_appearance`、`issues`，复杂值用 JSON 单元格保全。输入根目录无效或报告写入失败时 stderr 诊断并返回 2；检查发现的问题仍按既有 strict 语义阻断。重排写入在 C3 的 `reorder_notes.py`，两者共享 `notes_core.py` 的阅读顺序。

### 单侧成品体检

```powershell
python tools/check_epub_health.py --root EPUB --strict
python tools/check_epub_health.py --only css-layout --tsv 显式报告.tsv
```

汇总既有项目规则，检查 XML、ruby、正文原子块、标题、加粗、悬空引用、图片资源、CSS 分页保护、**译注页结构**与**成品构成**；资源检查覆盖全部 CSS url／@import、SVG 和导航引用。主 `style.css` 检查完整布局声明，辅助 CSS 只阻断 html／body 非零左右边距，不能要求每份字体 CSS 重复主样式，不另立规则。`--pattern` 筛书、`--only` 选项、`--top` 控制样例、`--json`／`--tsv` 显式报告。strict 有 error 非零；每项必须有负向测试。

成品构成项（规范见 [EPUB 成品构成规范](../docs/epub-artifact-spec.md)）：`dir-name`（书目录名的 `【作品号】` 前缀）、`metadata-title`（`dc:title` 逐字节等于书目录名）、`packaging-required`（`content.opf`／`nav.xhtml`／`toc.ncx` 与封面、制作信息页存在，且两张包装页已被 manifest 声明、已在 spine 中）、`nav-structure`（`nav.xhtml` 的 `<html>` 只含 `head`／`body`、`<head>` 只含元数据类元素且 `<title>` 非空）、`ncx-doctitle`（`docTitle` 等于 `dc:title`）、`toc-entry`（首条目为制作信息、封面不入目录）、`ncx-uid`（`toc.ncx` 的 `dtb:uid` 等于包文档 `unique-identifier`）、`identifier-unique`（跨书 `unique-identifier` 唯一）为 **error 级，接入发布预检**。`identifier-unique` 需跨书汇总：`check_epub_health` 在 `main()` 层计算，`publish_preflight` 在库级复核同一实现；豁免按「作品 + 检查项」登记在 `alignment_rules.HEALTH_EXEMPT_WORK_IDS`（当前仅 `S0_00` 的 `toc-entry` 一项）。

`title-style` 检查中文默认标题样式、分层角色／字号与引用 CSS、序终章间距、彩页及特典集合标题；`title-catalog` 检查 nav/NCX 的纯文本标签与 h1/h2/h3 投影及两套目录的目标／标签／顺序一致性。未知结构／样式与目录差异为 error，并通过共享 `audit_book` 进入本地发布和 CI 预检；不自动修复、不推断层数，非标题目标只由资源／锚点检查验证跳转。规范正文见 [结构规范](../docs/epub-structure-spec.md) 三和 [成品构成规范](../docs/epub-artifact-spec.md) 四。

`note-structure` 只对 `*-Note.xhtml` 判定，覆盖外壳（XML 声明引号、`<head>` 与 `<link>` 间距、空 `<title>`）、L4 固定 h1、L5 容器必须是 `<ul>`、`<li>` 属性顺序与完整性（含 `noteN` ID 格式）、缩进、行内标签白名单，规范见 [EPUB 结构规范](../docs/epub-structure-spec.md)「译注页（Note）结构规约」。ID 唯一性、引用完整性及条目物理顺序由 `check_note_order.py` 检查；数字连续性和数值排序均不要求。`S0_00-Note.xhtml` 第 7 行的说明型条目是登记在案的唯一豁免。

### 图片对应核对

```powershell
python tools/compare_epub_images.py --pattern "*S3_*" --output 显式报告目录
```

读两侧图片和 XHTML 引用，区分字节相同、解码像素相同、稳定命名对应与感知候选。双页范围可对应连续单页；旧命名依表头／槽位条件，不把页码猜为内容序。感知相似可能有修嵌或替换，必须视觉确认。`--cache` 指定参考根。

### 插图映射表核对

```powershell
python tools/check_illustration_mapping.py
```

核对 [插图文字映射表](../docs/illustration-text-mapping.md) 的每一行：`行号` 是否还指着 `正文原句`。表里的行号是日文缓存的**物理行号**，而缓存由 `pull.ps1` 重建——日文源一重导、一规范化就可能整体位移，所以每次拉取后跑一次。

行号不符时按 `正文原句` 在该卷正文里重新定位，给出建议行号；重新定位也找不到才计入未解析并非零退出。`--jp-root` 换参考根，`--json` 写完整报告，`--limit` 只控制终端样例条数（0 显示全部，负数返回 2），不改变问题总数、JSON 或退出码。**缓存缺失返回 2（前提不成立）**，与「有漂移」的 1 区分开，避免在没拉取的环境里误报。

### 翻译规范检查

```powershell
python tools/check_translation_spec.py --cache EPUB --output 显式报告目录
```

P1–P25 与规范条款的完整对应表唯一维护于 [翻译规范](../docs/translation-spec.md) 七。检查器只发现可机械形状，warning／info 与例外须人工判断，不自动改正文。`--pattern` 限定书名，`--top` 只控制样例显示；输出 TSV／JSON／Markdown。

`audit_book(text_dir)` 是 `main()` 与 `publish_preflight.py` 共用的入口，返回 `(file, line, category, severity, message, example)`；发布预检只取 `severity == "error"`。**注意两处计数粒度不同**：`main()` 的 `emit` 按「行×类别」去重，`audit_book` 不去重、按命中逐条返回——引用计数时须注明粒度。

**P17–P25 只对 `*-Note.xhtml` 判定**（口径见 [翻译规范](../docs/translation-spec.md) 三.2）。其中只有 **`P17`（中文语境半角括号）与 `P20`（括号不配对）是 error 级**并接入发布阻断——这两条在 Note 页回测为零误报。其余七项为 warning／info：`P23`（译注起句）存量 349 条、`P24`（谓语词收敛）81 条，属按批次收敛的存量项，**接入阻断会挡住全部 73 本**，故刻意留在报告级。

词表与判据常量的唯一来源都在本文件：`P9_EVENT_SUFFIXES`（赛事项目名例外）、`P16_TRADITIONAL`（繁体字表，由 OpenCC `TSCharacters` 生成）、`NOTE_LANG_LABELS`（译注语言标签，取规范译名而非库内多数派）、`NOTE_PREDICATE_CONVERGENCE`（译注同义谓语词收敛）、`NOTE_PREDICATE_GUARD`（词表里的复合词陷阱豁免）、`NOTE_LEAD_PATTERNS`（译注起句三类白名单）、`NOTE_METADISCOURSE_LEAD`（元话语起句黑名单）、`NOTE_INVIS_BAD`／`NOTE_INVIS_KEEP`（不可见字符）。只改集合不复制到文档；改变规则语义才更新规范与合同，并运行 `test_translation_spec.py`。

**P23 白名单必须配 `NOTE_METADISCOURSE_LEAD` 黑名单**：白名单只能判断「开头像不像甲类」，判断不了「开头是不是被注词」。2026-10 实测，甲类的 `[，]?指` 形式放宽后，`这里「龙王的一闪」指的就是…`、`本文中均指日文版的ISBN码`、`此处的抛物线花园可能是指…` 一类**元话语起句**会被白名单误放行；命中黑名单的一律作废，该轮拦下 49 条。

**`NOTE_PREDICATE_CONVERGENCE` 里有两族不可盲替换，改写时须逐条判断**：`原文中`／`原文是`／`原文注释` 是**收敛目标**（统一为 `原文为`），但原句常带 `写作`／`误记为` 一类成分，直接替换会写出病句（`作者在原文中误记为Salvere000` → `作者在原文为误记为…`）；`原为` 表**词源变迁**，按三族划分归 `原指` 而非 `是`。

### 译名表落地核对与术语审计

```powershell
python tools/check_translation_table.py --table 显式译名表.xlsx --strict
python tools/check_translation_table.py --table 显式译名表.xlsx --audit-rulings
```

读取外部表、日文参考、归档中文与《译名裁定总表》；表路径按翻译规范“外部依赖与核验”动态取得。列名支持 `--sheet`、`--ori-col`、`--trans-col`、`--type-col`、`--debuts-col`、`--ruby-ori-col`／`--ruby-trans-col`。`--epub`、`--jp-dir`、`--out`、重复 `--book` 指定范围。判定顺序为**同形例外 → 裁定表 → 译名表**：先按规范折叠查询和源，再查裁定表（锚点列取反引号内容与裸 `<ruby>…</ruby>` 两类——含注音的锚点按裁定表 §12 格式约定不加反引号，预览才渲染注音；同一锚点多条登记合并为候选集合，裁定列 `／` 分隔多写法，判定列标 `人读` 的条目跳过并在报告里单列），未命中才按译名表 `Base_Trans` 判定；裁定未落地单独成节、不并入 `--strict` 阻断。**注音判定**：裁定条目带注音（`<ruby>基文<rt>注文</rt></ruby>`）且该书日文侧存在带注音的该锚点时，中文侧必须出现裁定的复合串 `基文（注文）`——剥注音的判定分不出 `<rt>Gungnir</rt>` 与 `<rt>冈格尼尔</rt>`。**匹配轴**：判定列还可声明日文侧的认定方式——`匹配基文`（默认，注音不参与）、`严格全文`（日文须写出 `<ruby>基文<rt>注文</rt></ruby>` 复合串，裸写基文不在本行范围，既不判落地也不报未落地）、`匹配注文`（只认注文，基文可以是别的字，同一读音的当て字变体）；同一锚点多行须声明同一轴，混用退回默认。

`--rulings` 指定《译名裁定总表》（默认仓库内路径）；`--no-rulings` 是诊断绕过，不可据此要求回改已登记裁定。`--include-suspect` 展示短串候选、`--limit` 是局部调试，不能称全表验收。`alignment_rules.TRANSLATION_HOST` 和 `SETTLED_ANCHORS` 是已确认跨书归属／同形词事实源。`SETTLED_ANCHORS` 每条含 `note`／`scope`／`status`：**抑制只在该锚点被判定过的那本书内生效**；`status=settled`（已判定同形不同义）始终抑制，`status=待裁定`（两案都成立、尚未定）在裁定表登记该锚点后失效、改按裁定判定。

正文与 h1/h2/h3 分开收集：标题命中不为正文补足译名落地，也不计入 `--strict`；另写同一报告目录下的 `translation-title-check.tsv`，主 JSON 的 `title_records` 和 Markdown 的标题人工核对节同时展示。标题中的状态仅供人工结合原文判断，不直接产生替换要求。落地未命中只产生待判项，不等于误译；回原文判断普通词／专名、单复数与语境，执行 [术语统一 skill](../.agents/skills/translation-term-unification/SKILL.md)。strict 存在待判未落地项非零。`--audit-rulings` 只核裁定表与译名表：锚点全角英数字母、裁定列解析不出写法（散文格式漏标 `人读`）、锚点 `<rt>` 与 `Ruby_Ori` 不一致（一格多锚点时**逐块**核对，逐字分解的碎片按基文长度跳过）、译名表同锚点多译法未在裁定表登记、同一锚点多行匹配轴混用、声明了匹配轴但锚点不是单段 ruby，出问题非零；改裁定表后重跑。

### calibre 补充合法性检查

```powershell
python tools/check_epub_validity.py EPUB --structural --strict
python tools/check_epub_validity.py 成品目录 --recursive --report 显式报告.txt
python tools/check_epub_validity.py --list-categories
```

使用 calibre Check Book，读取包或解包书籍，检查容器／OPF、导航链接／锚点、字体图片、编码、ID 与 CSS。源不改，临时解包使用系统目录；每个 worker 用系统临时 `CALIBRE_CONFIG_DIRECTORY` 隔离配置，不读个人插件、不写用户配置。`--structural` 排除 CSS 顺序／重复／空块与 HTML 大小建议，类别映射按 calibre 类型而非本地化消息；unknown 类别照报。

支持 `--pattern`、`--jobs`、`--calibre-threads`、`--timeout`、`--min-severity`、重复 `--exclude-category`、`--report`／`--json`／`--tsv`、`--quiet`、`--calibre-debug`。0 是完成；strict 过滤后仍有问题为 1；环境／输入前提错误为 2。此为可选补充，未安装时说明未运行，不能替代共享发布前检查。

### 文档合同检查

```powershell
python tools/check_project_docs.py
```

只读核验：本地链接与标题锚点；顶层 `docs/*.md` 在 [文档索引](../docs/README.md) 的登记；活跃文档开头回指索引的入口（前 20 行内的相对链接；维护记录与冻结归档不逐项要求）；`tools/*.py`、`*.ps1`、`*.json` 的说明覆盖；**工具簇归属**。缺项非零，供 CI 和后续文档整改复跑。

**工具簇归属**（本文件必须满足的结构合同）：①每个 `tools/` 顶层文件在**恰好一个**簇成员表里出现且只出现一次，成员表的列固定为「工具｜入口命令｜读写范围｜门禁与失败边界｜测试」；②`## 簇索引` 必须覆盖全部簇，且每簇登记的入口数与成员表行数一致；③C1–C6 的行必须给出反引号入口命令，C0 的行必须写「无 CLI」；④「门禁与失败边界」列必须以 `【P<n>】` 指向 [阻塞与恢复](#阻塞与恢复) 的预案或写 `【无】`；⑤`## 路由` 中出现的工具名必须存在于某个成员表；⑥找不到 `## 簇索引` 或任何簇节时报错，不静默跳过。**单一来源检查**（同一规则只在一处写正文，其余处只留指针）：①裁定表主表内「同一锚点 + 相同义项标识」不得重复登记——分层与同词异译以不同义项标识并列属合法；锚点列只写锚点时，义项标识回落到「备注」列（原「理由」列）；②翻译规范与译名选取规范正文不得出现裁定表锚点的取值，同行带 `→`／`＝`／「译作」等映射标记即视为复述，指针行（含裁定表链接）与带 `<!-- single-source-ok -->` 白名单标记的行除外；③规范不得复制 `check_translation_spec.py` 的词表（命中 `P9_EVENT_SUFFIXES` 过半即报）；④规范与裁定表内 `§X` 形式的引用必须指向真实存在的小节。它检查可机械覆盖的合同，不替代对文档语义之间是否重复或冲突的判断。

## C5 内容质量

内容级改动与它的技术性审计：字符规范化、批量改动的分级复核、原文定位与风险提示。译文选词与译名取舍不在这里决定，走 [术语统一 skill](../.agents/skills/translation-term-unification/SKILL.md) 与 [校对复核 skill](../.agents/skills/proofread-review/SKILL.md)。

| 工具 | 入口命令 | 读写范围 | 门禁与失败边界 | 测试 |
| --- | --- | --- | --- | --- |
| `text_norm.py` | `python tools/text_norm.py --root EPUB --pattern "*S1_01*" [--apply] [--report 显式报告.md]` | 预览默认；字符级改写成品行内文字，不增删物理行 | 确定性规则、XML 与行数不变；规则实现唯一在本文件【无】 | `test_text_norm.py`、`test_edit_safety.py` |
| `proofread_review.py` | `python tools/proofread_review.py --worktree` | 只读 Git 改动与日文参考；写分级 TSV／聚类 | 精确行级配对；分级和风险提示不等于裁定【无】 | `test_proofread_review.py` |
| `proofread_session.py` | `python tools/proofread_session.py --help` | 只读清单、中日源与判定；默认预览，`--apply` 只写独立复核报告目录 | ID 对账、冻结来源、引句及报告结构；机械通过不等于语义验收【无】 | `test_proofread_session.py`、`test_proofread_packets.py`、`test_proofread_results.py` |
| `japanese_lookup.py` | `python tools/japanese_lookup.py S3_03 04 55 --mode markup` | 只读日文缓存 | 只定位原文，不作语义判定【无】 | `test_japanese_lookup.py` |
| `audit_risk.py` | `python tools/audit_risk.py --old "旧句" --new "新句" --jp "日文"` | 只读；终端／JSON | 仅启发式风险提示，不是裁定【无】 | `test_audit_risk.py` |

### 字符级规范化

```powershell
python tools/text_norm.py --root EPUB
python tools/text_norm.py --root EPUB --pattern "*S1_01*" --apply --report 显式报告.md
```

只执行规范可确定的字符替换，XML、行数、标签、文件名与引用保持有效。规则实现唯一在 `text_norm.py`，不另写批量替换器。`--pattern` 限定书籍，`--summary` 供 CI 提交信息正文的「字符级规范化」一行（提交主语取实际 diff，见 `.github/workflows/normalize-epub-text.yml`），`--top` 控制报告样例。遇到不支持的结构而拒绝处理文件时，终端／Markdown／summary 都明确检查不完整，警告走 stderr 并返回 1；完整检查且零命中仍返回 0。选词需原文的事项走术语或复核 skill。任何改写行内文字的改动写盘后必须重跑本工具并确认 0 命中。

规则必须**幂等**：同一份文本反复运行结果必须稳定。跨多个标记的连段要整段重排，不能只换相邻一对——`！[？?]` → `？！` 对 `！！！？？？` 既不收敛、产出的交错形态也不满足「问号始终在感叹号左边」，问叹顺序按整段「？在前、！在后」重排（`test_text_norm.py` 有幂等性反例）。

译注页相关规则两条，依据 [翻译规范](../docs/translation-spec.md) 三.2：

- `nbsp-to-ideographic-space`：`U+00A0` → `U+3000`。日文原版以**全角空格**做散字排版（`S3_06-02.xhtml:58` 用 17 个 `U+3000`），中文侧误用 `U+00A0`——后者在 CJK 字体中宽度随字体浮动，多列分页下散开程度会因设备而异。全库 161 处已逐条核对（159 处散字排版或署名分隔，2 处在 `<h2>` 标题内、由存量修复删除）。
- `tortoise-bracket-aside`：`〔〕` → `（）`。全库仅 `S1_05-Note.xhtml:21` 两处共 4 个字符。**刻意不纳入 `【】`／`〈〉`／`［］`**——`【】` 另有标题式标记的合法用途（`S0_00-Information.xhtml:5` 的「【汉化组招新】」即属此类，改写会破坏语义），`〈〉` 是国标单书名号；这三类由 `P18` 报告、人工判断，不得自动改写。
- `xref-prev-text` / `xref-next-text`：`前文` → `上文`、`后文` → `下文`，依据 `docs/translation-spec.md` 三.2「互参」。全库实测 `前文` 1 处（在正文 `S5_01_02-04_Chapter3.xhtml`）、`后文` 7 处（均在 Note 页）、`前后文` 2 处——后者是复合词、不指涉，用负向后视 `(?<!前)` 豁免。替换值唯一确定、零歧义。

### 提交级校对复核

```powershell
python tools/proofread_review.py --worktree
python tools/proofread_review.py 提交号 --path EPUB --out 显式报告目录
python tools/japanese_lookup.py S3_03 04 55
python tools/audit_risk.py --old "旧句" --new "新句" --jp "日文"
```

`proofread_review.py` 编排 Git 行级配对、`japanese_lookup.py` 原文提取、`audit_risk.py` 风险提示；不修改正文。支持 `--repo`、`--jp-base`、`--no-jp`、`--no-audit`；未提取／未诊断的侧明确未核验。原文 lookup 的 `--raw` 保留标签，`--jp-base` 指定参考；risk 的 `--json` 输出结构。

产物为 `changes.tsv`、`semantic.tsv`、`spec.tsv`、`groups.txt`。TSV 使用标准 tab 分隔和 CSV 字段引用，保留字段里的双引号、制表符及换行，读取用 `csv.DictReader`。一物理行合一条记录，用最小差异分级：spec 为确定规范形状，tiny 为 ≤2 字且全属虚词，local 为 ≤12 字局部变化，rewrite 为更大变化或整段增删；spec 仅在整段最小差异都能由规范解释时放行。数字／字母不当标点剥除。

`line` 使用 Git 行级配对的新侧行号，纯删除回旧侧行号；不可用 word-diff 物理行推算。`jp` 是当前参考的同行，不证明历史提交对应关系；行数变动时人工检索上下文。risk 标记包括否定、数字、疑问、字形、加粗标点、嵌套引号、受控术语和明显增删；它们只提示复核优先级。人工处置和抽样范围以 [校对复核 skill](../.agents/skills/proofread-review/SKILL.md) 为准。

### 校对复核会话

`proofread_session.py` 接续 `proofread_review.py` 的分级产物，供主控和子智能体共用。它只处理 `C` 片段清单，不自动决定语义单元或切片归属，也不替代 R4 的 `E` 呼应候选复核。流程、取舍和固定数据格式见 [复核契约](../.agents/skills/proofread-review/references/review-contract.md)。

```powershell
python tools/proofread_review.py --worktree --out .cache/epub-work/proofread-review/<run-id>
python tools/proofread_session.py init --report-root <report-root>
python tools/proofread_session.py init --report-root <report-root> --apply
# Lead 核完 spec／重分类、写好 slices/ids/*.txt 或显式 plan.json 后：
python tools/proofread_session.py prepare --report-root <report-root> --plan <plan.json>
python tools/proofread_session.py prepare --report-root <report-root> --plan <plan.json> --apply
python tools/proofread_session.py read --report-root <report-root> --slice <slice-id> --page 1
python tools/proofread_session.py read --report-root <report-root> --slice <slice-id> --ids C000001 --json
python tools/proofread_session.py assemble --report-root <report-root> --slice <slice-id> --decisions <decisions.json> --apply
python tools/proofread_session.py validate --report-root <report-root> --result <result.json> --json
python tools/proofread_session.py coverage --report-root <report-root> --selection <selection.json>
```

- **初始化与冻结**：`init` 按 `changes.tsv` 数据顺序建 `manifest.tsv`；已有清单只核对并复用，不覆盖重分类或 `parent_id`。`prepare` 接受 `slices/ids/*.txt` 或 `--plan` 的 JSON，核对语义 ID 恰归一片，解析完整作品号与内容序，读取 `--jp-base`／`--cn-base`（默认日文缓存／中文归档）。配对缺失、行数不同、输入不匹配或预算超限阻断，不自动重切。HEAD、输入提交／diff 快照、任务授权边界和 R2 放行依据仍由 Lead 记入 `baseline.md`。
- **产物**：`session.json` 保存清单／初始 TSV／源文件及每片取证包的 SHA-256，以 `session.sha256` 封存；`slices/packets/<slice-id>.json` 保存原始行、连续底字、注音记号和默认 N−1/N/N+1 中日上下文。新产物拒绝覆盖；日文缓存、归档和 OneDrive 全程只读。报告放现有 `.cache/epub-work/proofread-review/<run-id>/` 或显式仓库外目录；禁止写书籍目录、其它缓存目录或 OneDrive。跨物理行的 ruby／rt／rp 及无法与单行清单匹配的增删目前阻断，需提供行号稳定且匹配的工作源。
- **预算**：每片至多 150 条、3 文件、400 行 diff，实际输入字符预算默认 60000，可用 `--max-input-chars` 显式调整并在计划说明依据。工具不凭估计宣布实际 diff 门禁通过；未提供实测值时明确列为 Lead 待核。字节数、输入字符数和 token 数不等价。
- **阅读**：`read` 支持 `--ids`、单个 `--flag`、`--page`／`--page-size`、`--context 0|1` 和 `--json`。分页和过滤只改变展示，不减少分配分母；越界 ID 直接失败。每次读取核对冻结输入与来源，漂移须另建轮次。
- **补充上下文**：Lead 用 `context --report-root … --slice … --item-id … --radius 2 --revision 1 [--apply]` 按具体依赖输出该条补包到 `slices/context/<slice-id>/<item-id>.c1.json`；窗口限制 1–10 行，来自同一冻结源，不改变原包和所属 ID。更远或跨文件依赖由 Lead 明确取证并按契约处理，不把整章作为默认窗口。
- **装配**：子智能体逐条填写决策 JSON，再用 `assemble` 添加身份与冻结原文引用；已有显式引用必须成对提供，工具保留并验证。缺判定、缺理由、漏项、重复或越界都失败，不自动补成保留。`--attempt 1|2` 对应语义取证轮次；`--revision N` 只保存同 attempt 的格式修订 `.rN.json`，不能改已记录的语义判定与证据。
- **独立验收与覆盖**：`validate` 返回 `structure / evidence / input` 问题及具体 ID，实际对照所引日文位置，允许原始行、连续底字和注音记号的等价表示；位置有效不等于引句通过。`coverage` 按显式 selection 的结果路径、在计划顺序中统计 `T/S/M/K/R/H/U`，失效或缺失结果整片归 U；H/U 阻断完成。`ready_for_lead_acceptance` 只说明可以交 Lead 语义验收，不授权回改、同步或提交，也不自动生成通过结论。回改前的覆盖快照与新验收轮生命周期见复核契约。

`init / prepare / context / assemble / coverage` 默认只预览；显式 `--apply` 才写新报告产物。`coverage --apply` 还须给本轮目录内的 `--output`。`read / validate` 只输出；`validate` 或 `coverage` 有阻断返回 1，成功返回 0。格式修复和语义重审的分支以复核契约为准。

## C6 检索与统计

只读的检索、表格查看与字数／页数换算，用于任务准备与篇幅判断；不作语义裁定，也不写书。

| 工具 | 入口命令 | 读写范围 | 门禁与失败边界 | 测试 |
| --- | --- | --- | --- | --- |
| `search_text.py` | `python tools/search_text.py "レールガン" --side jp` | 只读缓存与归档 | 无语义裁定；注音三轨检索【无】 | `test_search_text.py` |
| `read_xlsx.py` | `python tools/read_xlsx.py 文件.xlsx --list-sheets` | 只读外部表格；`--out` 显式导出 | 无语义裁定；依赖可选 `openpyxl`【无】 | `test_read_xlsx.py` |
| `epub_char_count.py` | `python tools/epub_char_count.py <epub 或目录> --pages-per 400` | 只读 | 字数口径与包装页过滤；输出占比列【无】 | `test_epub_char_count.py` |
| `epub_composition_metrics.py` | `python tools/epub_composition_metrics.py <目录或epub>` | 只读；CSV 默认写 `.cache/epub-work/composition-metrics/` | 印刷页是推算值，锚点之外靠密度外推【无】 | `test_epub_composition_metrics.py` |

### 全库文本与术语检索（注音保全 + 中日联动，只读）

```powershell
python tools/search_text.py <query> [-s both|cn|jp] [-w <WORK_ID>] [-m <MAX>]
python tools/search_text.py "レールガン" --side jp
python tools/search_text.py "超电磁炮" --side cn -w "S1_*" -C 1
python tools/search_text.py "カリキュラム" --format markdown
```

用于在 EPUB 工作缓存（`.cache/epub-work/`）及归档中进行精准的全文与术语检索，支持注音假名搜索、汉字长词跨标签搜索、BW 源假名妥协折叠与中日双向对齐联动。只读，不修改文件。

- **注音完整保全（绝不丢失读音信息）**：自动将 HTML 中冗长的 `<ruby>基文<rt>注音</rt></ruby>` 解析并转化为精炼的 `基文(注音)` 纯文本展示（如 `超電磁砲(レールガン)`），彻底清除 `<p>`/`<div>`/`<span>` 排版标签，同时汉字基文与特殊读音假名一个不漏。
- **三轨匹配引擎**：
  - **基文轨（base）**：消除假名与 `<rt>` 标签打断汉字的问题，搜纯汉字「超電磁砲」「超能力者」「上条当麻」匹配，展示时依然完整保留注音；
  - **注音轨（ruby）**：专门匹配 `<rt>` 内的假名/英文，搜「レールガン」「イマジンブレイカー」「カリキユラム」直接命中读音；
  - **综合轨（formatted）**：直接匹配格式化后的整句或整词。
- **假名与英数折叠归一化**：
  - 自动打通小字假名（`ゃゅょっ` 等）与大字假名（`ヤユヨツ` 等），兼容 BookWalker 源注音大小字混用，输入《译名表》不妥协小字写法亦可命中源文；
  - 自动归一化全角英数与半角 ASCII（如 `５` ↔ `5`，`＝` ↔ `=`）。
- **中日双向自动联动（Bilingual Pair Linkage）**：
  - 搜中文行时，自动关联展示日文对应文件的同一行原文及其注音（`= [JP] Lxx: ...`）；
  - 搜日文行时，自动关联展示中文对应文件的成品译文（`= [CN] Lxx: ...`）；
  - 用于术语定位与对齐核验；若无需联动可传 `--no-pair`。
- **作用域过滤与上下文**：`-w` / `--work` 按作品号通配过滤（如 `"S1_*"`, `"S3_01"`）；`-s` / `--side` 指定检索侧（`both` / `cn` / `jp`）；`-C N`（或 `--context N`）显示前后 N 行上下文；`-m N` 限制最大匹配数（默认 50）；`-f` 输出为 `text`（高亮终端）、`markdown`、`json` 或 `tsv`。

### Excel 解析与预览（只读）

```powershell
python tools/read_xlsx.py <file.xlsx> [--list-sheets] [--sheet <NAME/IDX>] [--cols <COLS>]
python tools/read_xlsx.py <file.xlsx> [-q <KEYWORD>] [--head <N>] [--format <markdown|tsv|csv|json>]
```

用于快速查看、过滤、提取并转换 `.xlsx` 格式文件（如术语表、人名对照表、校对任务表）为模型友好或易读的格式，避免在对话交互中重复临时编写一次性解析脚本。只读，不修改原始文件。

- **依赖**：需要 `openpyxl`（`python -m pip install openpyxl`）。该库是**可选依赖**：未安装时本工具只有在实际调用相关函数时才报错并提示安装命令，不影响 `tools/` 其余工具的导入与运行；对应的 `tools/tests/test_read_xlsx.py` 也在无该库的干净环境（如 CI）下整组跳过，而不是让测试采集失败。
- **工作表查看与选择**：`--list-sheets`（`-l`）列出所有 Sheet 及其行/列规模；`-s` / `--sheet` 按名称或 0-based 序号指定 Sheet（默认读取首个 Sheet）。
- **格式转换**：`--format markdown`（默认，精美 Markdown 表格，自动转义内部竖线与换行符）、`tsv`、`csv`、`json`（支持 `--json-mode records` 字典列表或 `rows` 二维数组）。
- **上下文截取与分页**：`--head N`（`-n N`）取前 N 行；`--tail N` 取后 N 行；`--offset N --limit M` 分页切片，防止大表格撑爆大模型上下文。
- **列提取**：`--cols`（或 `-c`）仅提取指定列，支持逗号分隔的列名（如 `"Base_Ori,Base_Trans,Type"`）、列字母（如 `"A,B,D"`）或 1-based 数字（如 `"1,2,4"`）。
- **行关键词搜索**：`-q` / `--search` 直接在选定列中全文匹配关键词，仅输出包含该关键词的行（默认不区分大小写，`--match-case` 区分大小写）。
- **文件导出与摘要**：`-o` / `--out` 导出结果到文件；`--info` 将当前工作表、总匹配行数、展示行数与列数摘要打印到 stderr，不混入 stdout 的 JSON／TSV／CSV。显式导出成功时 stdout 报告导出路径。

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

输出列：`成分 / 子成分 / 全字符 / 页数（换算）/ 印刷页区间 / 印刷页数`（合计行给出全书正文印刷页推算区间）。成分名规范化（序章/第N章/终章、行间、后记、引子/尾声位置规则）与 `epub_char_count` 完全一致；正文按 `<h2>` 展开子成分，`--chars-only` 只按成分输出。与 `epub_char_count` 的取舍：要「占比」列用前者，要「印刷页推算」用后者——两者的 CLI 面与输出列不互相包含。

**估算边界**：锚点页本身是实测的，锚点之间按字数比例分配；书首（首个插图之前，通常 30~50 页）无锚点、只能靠密度外推，误差最大，单成分页数约 ±10%。页区间是推算值，不是书内页码标记。默认只读，不修改输入；CSV 默认写到 `.cache/epub-work/composition-metrics/<书目录名>.csv`，不落进书籍目录，避免被 `package_cache_epubs.py` 打进 EPUB。CSV 完成提示走 stderr，`--json` 的 stdout 保持纯 JSON；`--no-csv` 只打印、不生成 CSV。

## C0 共享内核

无 CLI 的共享规则与原子写入能力。**同一规则只维护一份实现**，模块不另建工作流入口、不承担入口编排或语义裁定。修改共享模块或其调用方后运行对应矩阵测试及：

```powershell
python -m unittest discover -s tools/tests -p "test_*.py" -v
```

同一批次的文件写入使用 `file_transaction.py` 的临时文件／临时目录和失败回滚：`normalize_single.py` 的目录模式、`normalize_paired.py`、`reorder_notes.py`、发布入口的单书镜像与 `sync_file_changes()` 在捕获到写入异常时恢复本批次原始字节。发布流程的每本书以书目录为事务边界；多本书之间不组成一个跨目录事务，成功书籍可以提交、失败书籍保留变更等待重试。进程被强制终止或文件系统本身拒绝回滚时，工具只能保留恢复副本并报告，不能宣称断电级事务。

体检与门禁必须有能触发失败的最小反例。新报告／构建目录同步 `.gitignore`，不写进书内或提交临时产物。`bw_extract_preprocess.json` 维护可重复预处理规则；`bw_page_header_overrides.json` 维护已审计的逐页内容映射——两者是 C2 的配置数据，映射必须覆盖实际分页，不能把未知页默认为上一章节。

| 工具 | 入口命令 | 读写范围 | 门禁与失败边界 | 测试 |
| --- | --- | --- | --- | --- |
| `alignment_rules.py` | 无 CLI（共享模块） | 由调用方决定；只提供规则数据 | 【无】 | `test_alignment.py`、`test_check_epub_health.py`、`test_check_translation_table.py`、`test_epub_ids.py` |
| `cli_output.py` | 无 CLI（共享模块） | 仅由 CLI 入口初始化 stdout／stderr 的 UTF-8 编码；兼容内存捕获流 | 【无】 | `test_cli_output.py` |
| `docx_source.py` | 无 CLI（共享模块） | 交稿 docx 段落流与行内记号的单一解析 | 【无】 | `test_docx_and_notes.py`、`test_import_tools.py`（间接） |
| `edit_safety.py` | 无 CLI（共享模块，含 argparse 辅助） | 写目标与显式暂存范围的限制 | 【无】 | `test_edit_safety.py` |
| `epub_ids.py` | 无 CLI（共享模块） | 作品号、表头、内容序与文件角色解析；`is_packaging_header`（是否包装页，7 类）与 `is_list_packaging_header`（能否在 L5 写列表，4 类）**刻意分开** | 【无】 | `test_epub_ids.py` |
| `epub_structure.py` | 无 CLI（共享模块） | 容器／OPF manifest-spine 事实／XML／资源引用采集、解析与检查 | 【无】 | `test_epub_structure.py`；调用方：`test_check_epub_health.py`、`test_package_cache_epubs.py`、`test_bw_preprocess.py` |
| `file_transaction.py` | 无 CLI（共享模块） | 临时文件／临时目录与失败回滚 | 【无】 | 无专用测试；由调用方验证 |
| `image_signature.py` | 无 CLI（共享模块） | 图片 dHash 指纹与尺寸（Pillow 可选） | 【无】 | 无专用测试；由调用方验证 |
| `import_plan.py` | 无 CLI（共享模块） | 导入计划的结构校验与逐条改动装配 | 【无】 | `test_import_tools.py` |
| `notes_core.py` | 无 CLI（共享模块） | Note 解析和阅读顺序 | 【无】 | `test_docx_and_notes.py` |
| `path_safety.py` | 无 CLI（共享模块） | ZIP 路径安全、解包残留识别与显式报告目标冲突检查 | 【无】 | `test_path_safety.py` |
| `proofread_packets.py` | 无 CLI（共享模块） | 复核清单、冻结来源与逐片读取，写入仅由显式 apply 入口触发 | 【无】 | `test_proofread_packets.py` |
| `proofread_results.py` | 无 CLI（共享模块） | 显式判定装配、日文引句核验和有效报告对账 | 【无】 | `test_proofread_results.py` |
| `sync_core.py` | 无 CLI（共享模块） | 差异、镜像、上传状态与拉取状态 | 【无】 | `test_publish_auto.py`、`test_sync_and_rename.py` |
| `xhtml_slots.py` | 无 CLI（共享模块） | 固定行模板 L1–L6 的槽位行号与名称常量；译注页固定 h1 常量 `NOTE_H1` | 【无】 | 由调用方测试覆盖：`test_alignment.py`、`test_bw_preprocess.py`、`test_heading_breaks.py` |
| `xhtml_structure.py` | 无 CLI（共享模块） | 物理行类型、保守配对与页边界修复前提 | 【无】 | `test_xhtml_structure.py` |
| `xhtml_template.py` | 无 CLI（共享模块） | 固定模板纯重建 | 【无】 | `test_xhtml_and_merge.py` |
| `xhtml_text.py` | 无 CLI（共享模块） | XHTML → 纯文本的唯一口径（保留注音／去注音／可见文本三种） | 【无】 | `test_xhtml_text.py`；另有调用方测试 |
| `title_rules.py` | 无 CLI（共享模块） | 中文标题样式／层级／目录投影的只读合同与正文／标题文本分流 | 未覆盖结构、标题投影差异由调用方阻断【无】 | `test_title_rules.py`、`test_publish_preflight.py` |

### 负责与不负责

| 模块 | 负责 | 不负责 |
| --- | --- | --- |
| `epub_ids.py` | 作品号、表头、内容序、文件角色与明确历史别名；`PACKAGING_SUFFIXES`（7 类，判定「是不是包装页」）与 `LIST_PACKAGING_SUFFIXES`（4 类，判定「能否在 L5 写列表」） | 猜测配对或按章名反推序号；**不得用 7 类集合放行 L5 列表槽位**——纯图片页无列表用例，`check_alignment`／`check_epub_health`／`normalize_paired`／`check_semantic_alignment`／`xhtml_template` 五处必须共用 `is_list_packaging_header` |
| `docx_source.py` | 交稿 docx 段落流与行内记号（注音、译注、可信标签）的单一实现 | 章节装配、模板渲染、写盘与他人裁定 |
| `import_plan.py` | 导入计划的结构校验与逐条改动装配 | 裁定改动对错、写盘、发布方向 |
| `image_signature.py` | 图片 dHash 指纹与尺寸（Pillow 可选） | 判定图片语义角色、写盘 |
| `alignment_rules.py` | 有依据的配对、模板与语义归属例外 | 为消除错误扩大豁免 |
| `xhtml_template.py` | 固定模板纯重建 | 文件选择与历史标题语义迁移 |
| `xhtml_slots.py` | 固定行模板 L1–L6 的槽位行号与名称常量（唯一来源）；译注页固定 h1 常量 `NOTE_H1`（唯一来源，`docx2epub.py` 与 `import_build_text.py` 共用） | 槽位判定策略：配对／分页／合并三类契约的宽严不同，留在各入口实现；译注页结构判据留在 `check_epub_health.find_note_structure_problems` |
| `xhtml_structure.py` | 物理行类型、保守配对与页边界修复前提 | 语义拆合或猜测未确认偏移 |
| `notes_core.py` | Note 解析和阅读顺序 | 同步、发布方向 |
| `sync_core.py` | 差异、镜像、上传状态与拉取状态 | 冲突取舍和方向选择 |
| `edit_safety.py` | 写目标与显式暂存范围的限制 | 决定修改语义是否正确 |
| `path_safety.py` | ZIP 路径安全、解包残留识别及报告与受保护输入／输出路径的冲突检查 | 内容／语言规范 |
| `epub_structure.py` | 共用的容器、OPF spine、XML 与资源引用检查；`opf_relations` 返回有序 manifest/spine 事实，`xml_references`／`css_references` 返回有序原始引用，`resolve_reference` 解析书内路径 | 工具编排与成品模板选择；事实采集入口不负责文件选择、XML 解析与异常处理、重复 ID／缺项／媒体类型判定、锚点采集及体检的存在性／越界／fragment 策略 |
| `xhtml_text.py` | XHTML → 纯文本的三种口径（保留注音／去注音／可见文本）；`<rt>`、`<rp>` 剥除规则的唯一实现 | 扫描与报告；该用哪种口径由调用方决定 |
| `file_transaction.py` | 异常安全的文件系统写入（临时文件／目录 + 回滚） | 发布策略与冲突取舍 |
| `title_rules.py` | 中文标题样式／层级／目录投影的只读合同；正文与标题文本分流 | 译法裁定、分层推断、自动修复及逐标题预期清单 |

`tools/README.md` 自身的说明覆盖、簇归属与单一来源合同由 C4 的 `check_project_docs.py` 检查；改本文件的结构后先跑它。

资源引用采集不检查目标存在性，也不提前解析 URL。`xml_references(root, attribute_case=...)` 接收已解析的 XML，调用方必须明确选择 `lower`（体检）或 `casefold`（入库合同）；保留元素与属性顺序、重复引用及 `full-path` 的根相对标记。`css_references(data)` 在原始字节上去注释后先返回全部 `url()`、再返回引号形式的 `@import`，保留重复项并严格 UTF-8 解码。`ResourceReference` 只含原始 `value` 与 `root_relative`；采集不吞掉解码异常。体检先收齐引用再判定，入库／打包逐文件判定；两侧保留各自的后缀范围、XML 错误处理与诊断顺序。

`opf_relations(root, scope=..., tag_case=...)` 接收已解析 XML，返回 `OpfRelations.items`／`itemrefs`：每条 manifest 声明保留 `id`、`href`、`media_type`，每条 spine 声明保留 `idref`；缺值以空字符串表示，保留文档顺序与全部重复项，不预先折叠 ID。`scope="direct"` 只取首个直接 manifest/spine 的直接条目，`"descendants"` 取全树条目；`tag_case="exact"|"casefold"` 在去元素命名空间后控制标签匹配。非法选项抛 `ValueError`，不转成 EPUB 诊断。

容器合同使用 direct/exact，保留最后一条重复 ID 的媒体类型；入库合同使用 descendants/casefold，所有重复声明的资源目标都参与图片声明检查。体检的 `opf_spine_hrefs` 使用 XML 读取与 descendants/exact，按精确属性名读取，支持单引号、命名空间前缀、实体解码与属性间空白，忽略注释／CDATA；最后一个非空 ID/href 生效，空 idref 忽略，未知 idref 返回空 href。非法 OPF 返回空 spine，容器／入库入口继续按原合同报告 XML 错误；体检继续检查必备包装页。其他包装页存在性、manifest 声明判定与诊断口径保留在原调用方。
