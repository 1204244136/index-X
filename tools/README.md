# EPUB 维护工具

文档职责与入口见 [文档索引](../docs/README.md)。本文维护工具的命令合同：职责、输入输出、读写范围、门禁和验证入口。系列编号、文件命名、固定行模板与写入边界以 [AGENTS.md](../AGENTS.md) 为准；成品语言规范以 [翻译规范](../docs/translation-spec.md) 为准。历史验收与修改统计只在维护记录和提交中保存。

## 职责与覆盖矩阵

“只读”指不修改输入书籍，允许写显式报告或临时产物。`--help` 是完整参数与默认值的命令入口；本表说明使用和修改该工具时必须核对的合同。测试文件位于 `tools/tests/`。

| 工具／能力 | 输入与读取范围 | 写入范围 | 门禁／失败边界 | 对应测试 |
| --- | --- | --- | --- | --- |
| `publish_auto.py` | 缓存、归档、OneDrive 状态与基线 | 调用 A/B/C 同步器 | 冲突与方向计划，失败非零；预览不发布 | `test_publish_auto.py` |
| `pull.ps1` | OneDrive 打包源、拉取状态 | 缓存；`-SyncToEpub` 时归档 | 解包路径安全、保全未发布变化；增量更新基线 | 共享能力：`test_sync_and_rename.py`／`test_path_safety.py`；PowerShell 入口无专用测试 |
| `publish.py`／`publish_epub.py` | B：缓存；C：归档中文及只读日文参考 | 缓存、归档、打包与 OneDrive | 共享发布前检查、基线缺失与冲突阻断 | `test_sync_and_rename.py`、`test_publish_preflight.py` |
| `package_cache_epubs.py` | 显式 `--source` 或缓存书目录 | `--output` 构建目录 | 容器、XML、资源引用；`mimetype` 首项不压缩 | `test_package_cache_epubs.py` |
| `bw_preprocess.py` | BW `.epub`／显式分页暂存目录 | 显式产物／暂存目录 | 分页或合并后契约、映射完整性、资源与 XML | `test_bw_preprocess.py`、`test_import_output_boundaries.py`、`test_bw_pagebreaks.py` |
| `merge_bw_pages.py` | 已预处理分页目录 | 显式章节输出 | 表头、作品号、序号冲突阻断；边界疑点报告人工 | `test_xhtml_and_merge.py`、`test_image_title_merge.py`、`test_import_output_boundaries.py`、`test_bw_pagebreaks.py` |
| `split_s5_epubs.py` | 显式合订卷源与 `SPLIT_SPECS` | 显式打包／解包暂存目录 | 全部源、页区间和产物先预检；失败不输出 | `test_split_s5_epubs.py`、`test_bw_preprocess.py` |
| `normalize_single.py`／`normalize_paired.py` | 指定单侧文件；归档中文与只读日文参考或双侧暂存 | `EPUB/`；显式 `--staging` 暂存 | 共用模板规则；配对写入验证行数，不靠重排凑齐 | CLI：`test_edit_safety.py`；模板规则：`test_xhtml_and_merge.py` |
| `migrate_heading_breaks.py` | 归档或显式暂存书籍 XHTML/CSS | 同一书 XHTML/CSS | 全书预检未知结构、CSS 路径和按层文字不变 | `test_heading_breaks.py` |
| `shift_content_sequences.py`／`fix_empty_placeholders.py` | 指定归档／暂存书籍 | 序号、文件与关联引用 | 重命名碰撞／不合法序号、空页资格、悬空引用 | `test_shift_content_sequences.py`、`test_sync_and_rename.py` |
| `fix_legacy_pagebreak_br.py`／`restore_cn_scene_breaks.py`／`sync_pb_tags.py` | 归档中文＋只读日文参考 | 中文归档／显式暂存中文 | 逐边界数量、块对应与行数条件；不猜语义分段 | `test_fix_legacy_pagebreak_br.py`、`test_restore_cn_scene_breaks.py`、`test_edit_safety.py` |
| `wrap_cn_image_lines.py` | 中文归档；删结构行时需日文参考 | 中文归档／显式暂存中文 | 图片专用容器、配平和行数不变量 | `test_wrap_cn_image_lines.py` |
| `reorder_notes.py` | 中文归档阅读顺序与 Note | Note 和正文引用；可选备份 | 共用 notes 规则、完整引用映射预检 | CLI：`test_edit_safety.py`；共享规则：`test_docx_and_notes.py` |
| `docx2epub.py` | 显式 DOCX | 显式成品构建输出 | 源不覆盖，资源／容器验证 | `test_docx_and_notes.py`、`test_import_output_boundaries.py` |
| `epub2docx.py` | 显式 EPUB | 显式交稿输出 | 源不覆盖，需 calibre | 输出边界：`test_import_output_boundaries.py`；转换依赖外部 calibre |
| `check_alignment.py` | 中日缓存或显式配对参考 | 报告 | 模板、原子块、完整表头、行数与 h1/h2/图片/br/pb 位置；strict 非零 | `test_alignment.py` |
| `diff_paired_lines.py` | 单对 XHTML／中日缓存 | TSV／HTML 诊断 | 行号对齐；不等长时序列诊断，不修正文 | `test_diff_paired_lines.py` |
| `check_semantic_alignment.py` | 中日缓存；L2 模型运行时 | 语义诊断报告 | strict 全范围 L2；环境失败及未通过结果非零 | `test_check_semantic_alignment.py`、`test_diff_paired_lines.py` |
| `compare_epub_images.py` | 中日缓存图片与引用 | 图片核对报告 | 字节／像素相同与感知候选分开；候选需视觉确认 | 无专用测试；只读诊断 |
| `check_note_order.py` | 中文缓存或 `--root` | TSV／JSON／Markdown | 未定义／重复／未引用与阅读顺序问题 | `test_check_note_order.py`；共享规则：`test_docx_and_notes.py` |
| `check_translation_spec.py` | 中文缓存或 `--cache EPUB` | TSV／JSON／Markdown | P1–P16 规则报告；提示不自动当缺陷 | `test_translation_spec.py` |
| `text_norm.py` | 中文归档 | 字符级成品修改与显式报告 | 确定性规则、XML 与行数不变，默认预览 | `test_text_norm.py` |
| `check_epub_health.py` | 中文归档 | 显式 TSV／JSON | 单侧项目规约，strict 遇 error 非零 | `test_check_epub_health.py`（每项含负例） |
| `check_epub_validity.py` | EPUB 成品／解包书籍 | 显式报告；系统临时解包 | calibre 补充检查，环境错误明确非零 | `test_calibre_validity.py` |
| `check_translation_table.py` | 外部 xlsx＋日文缓存＋中文归档＋译名裁定总表 | 本地核对报告 | 折叠→同形例外→裁定表（含注音判定）→译名表；同形词待语义判断 | `test_check_translation_table.py` |
| `proofread_review.py` | Git 改动与日文参考 | 分级 TSV／聚类 | 精确行级配对，分级和风险提示不等于裁定 | `test_proofread_review.py` |
| `japanese_lookup.py`／`audit_risk.py` | 作品／文件／行；单处旧新日文 | 终端／JSON | 前者只定位原文；后者仅启发式风险（受控词表可并入裁定表生成的「成品旧译」提示） | `test_japanese_lookup.py`、`test_audit_risk.py` |
| `epub_char_count.py`／`epub_composition_metrics.py` | EPUB／解包目录 | 终端、CSV／JSON | 共用字数口径；印刷页推算明确估算范围 | 无专用测试；只读诊断 |
| `check_project_docs.py` | 活跃文档、文档索引、归档链接、工具目录清单与单一来源 | 终端报告 | 本地链接／锚点、索引登记与回指、工具说明覆盖、裁定表锚点唯一／规范不嵌裁定取值／规范不复制检查词表／§ 引用可解析，缺项非零 | `test_check_project_docs.py` |
| `read_xlsx.py`／`search_text.py` | 外部表格；缓存或归档文本 | 终端与显式导出 | 表列选择／注音三轨检索；无语义裁定 | `test_read_xlsx.py`、`test_search_text.py` |
| `bw_extract_preprocess.json`／`bw_page_header_overrides.json` | BW 分页预处理规则与已审计逐页映射 | 只读配置 | 仅供 `bw_preprocess.py` 读取；未知页不得默认继承上一单元 | `test_bw_preprocess.py` |
| `alignment_rules.py`／`edit_safety.py`／`epub_ids.py`／`epub_structure.py`／`file_transaction.py`／`manifest.py`／`notes_core.py`／`path_safety.py`／`publish_preflight.py`／`sync_core.py`／`xhtml_structure.py`／`xhtml_template.py`／`xhtml_text.py` | 内部共享规则与原子写入能力 | 由调用方决定；共享模块不另建 CLI 工作流 | 只提供单一实现；不得承担入口编排或语义裁定 | 对应调用方测试矩阵 |

## 共享规则模块

内部模块不另建工作流入口。同一规则只维护一份实现：

| 模块 | 负责 | 不负责 |
| --- | --- | --- |
| `epub_ids.py` | 作品号、表头、内容序、文件角色与明确历史别名 | 猜测配对或按章名反推序号 |
| `alignment_rules.py` | 有依据的配对、模板与语义归属例外 | 为消除错误扩大豁免 |
| `xhtml_template.py` | 固定模板纯重建 | 文件选择与历史标题语义迁移 |
| `xhtml_structure.py` | 物理行类型、保守配对与页边界修复前提 | 语义拆合或猜测未确认偏移 |
| `notes_core.py` | Note 解析和阅读顺序 | 同步、发布方向 |
| `manifest.py` | 哈希快照读取／扫描／更新 | 选择来源 |
| `sync_core.py` | 差异、镜像、上传状态与拉取状态 | 冲突取舍和方向选择 |
| `publish_preflight.py` | 发布候选的项目门禁与容器／XML／资源检查 | 编辑输入、选择发布方向、替代译文人工核对 |
| `edit_safety.py` | 写目标与显式暂存范围的限制 | 决定修改语义是否正确 |
| `path_safety.py` | ZIP 路径安全和解包残留识别 | 内容／语言规范 |
| `epub_structure.py` | 从 BW 导入共用的容器、OPF spine、XML 与资源引用检查 | 工具编排与成品模板选择 |
| `xhtml_text.py` | 保留注音的复核纯文本提取 | 扫描与报告；原文检索须由调用方先去注音 |

`bw_extract_preprocess.json` 维护可重复预处理规则；`bw_page_header_overrides.json` 维护已审计的逐页内容映射。映射必须覆盖实际分页，不能把未知页默认为上一章节。

共享路径／结构保护另有 `test_edit_safety.py` 和 `test_xhtml_structure.py`；作品号／表头解析由 `test_epub_ids.py` 验证；发布前检查由 `test_publish_preflight.py`、打包由 `test_package_cache_epubs.py` 验证。修改共享模块或其调用方后运行对应矩阵测试及：

```powershell
python -m unittest discover -s tools/tests -p "test_*.py" -v
```

体检与门禁必须有能触发失败的最小反例。新报告／构建目录同步 `.gitignore`，不写进书内或提交临时产物。

## 写入与预览合同

归档规范化和修复入口默认只预览，显式 `--apply` 才写。`--staging` 只允许显式暂存目录；共享路径保护始终拒绝仓库 `.cache` 和 OneDrive 内容写入。同步器负责三副本回流，构建输出不应放回输入书目录。

同一批次的文件写入使用 `file_transaction.py` 的临时文件／临时目录和失败回滚：`normalize_single.py` 的目录模式、`normalize_paired.py`、`reorder_notes.py`、发布入口的单书镜像与 `sync_file_changes()` 在捕获到写入异常时恢复本批次原始字节。发布流程的每本书以书目录为事务边界；多本书之间不组成一个跨目录事务，成功书籍可以提交、失败书籍保留变更等待重试。进程被强制终止或文件系统本身拒绝回滚时，工具只能保留恢复副本并报告，不能宣称断电级事务。

单侧修改指定 `EPUB/`；配对修改使用 `--root EPUB --jp-root .cache/epub-work/japanese-text`，日文目录仅读。双侧暂存处理使用 `--cache <暂存根> --staging`，暂存根包含 `chinese-text/` 和 `japanese-text/`。`--dry-run` 保留为预览兼容参数，与 `--apply` 互斥；它不代替写入授权或路径验证。

标题／页边界的语义未确认时，工具输出待人工项并保留内容。译文选词不由结构工具自动处理；执行流程见两份项目 skill。

## 同步与发布

### 统一入口

```powershell
python tools/publish_auto.py --dry-run
python tools/publish_auto.py
```

读取三处副本与 `manifest.json`／`pull-state.tsv` 的差异，输出逐书方向计划；只处理变更书和文件。同一本地书的缓存修改已包含在归档时选择 C，否则报告冲突；OneDrive 外部更新与本地未发布修改冲突时停止。冲突合并的操作边界在 AGENTS，`--from` 不代表可以丢弃另一边有效内容。

参数：`--cache`／`--epub`、`--from auto|cache|epub|onedrive`、`--side`、`--pattern`、`--only-books`、`--dry-run`、`--no-upload`、`--force`（配合显式方向）、`--overwrite-cache`、`--chinese-onedrive`／`--japanese-onedrive`。退出码 1 表示被阻塞或失败；dry-run 只预览，不执行发布门禁与同步。

### 底层 A／B／C

| 方向 | 命令 | 实際输入／输出 |
| --- | --- | --- |
| A：外部源变化 | `./tools/pull.ps1 -SyncToEpub` | OneDrive → 缓存；中文变化增量回归档；不打包上传 |
| B：已确认缓存来源 | `python tools/publish.py` | 缓存 → 归档中文＋分别打包上传两侧；同步清单与状态 |
| C：归档内容变化 | `python tools/publish_epub.py` | 归档中文 → 打包上传＋缓存增量镜像；日文参考只读 |

B 不是 agent 的常规编辑入口，只用于同步器／导入流程已生成并确认的缓存来源；成品修改走 C。三个方向都有 `--dry-run`／`-WhatIf`。B/C 用共享发布前检查读取本次候选：模板与对齐、单侧项目规约、合法容器、全部 XML 及书内资源引用。C 验证归档中文与缓存日文，不临时覆盖缓存来做检查。预检失败不推进该书发布与清单基线。发布先在临时副本完成打包和单书镜像；上传或状态更新失败时回滚本书本地镜像，清单只为完整成功的书更新。

`--force` 不表示跳过成品结构门禁。清单中某处理侧全无基线记录时，发布停止并给出重建提示；仅确认缓存即已发布状态后用 `manifest.py --update-books chinese-text/某书目录` 重建，不用清单更新掩盖未发布变化。

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
./tools/pull.ps1 -Side japanese
./tools/pull.ps1 -Force
```

默认外部源由用户 OneDrive 目录推导；可显式传入 `-ChineseSourceDirectory`、`-JapaneseSourceDirectory`、`-CacheDirectory`、`-EpubDirectory`。按书籍修改时间与大小增量解包，首次建立拉取状态。只更新本次解包书的清单，不把未变化书的新缓存修改当新基线。源码读取与包内路径解析由 path safety 共用规则控制。

### 缓存发布与归档发布

```powershell
python tools/publish.py --dry-run
python tools/publish.py --sync-only
python tools/publish_epub.py --dry-run
python tools/publish_epub.py
```

两者支持 `--cache`、`--epub`、`--pattern`、`--only-books`、`--no-upload`、`--force` 和外部目标路径；B 有 `--side`、`--sync-only`，C 有 `--overwrite-cache`。删除随增量镜像传播；`--no-upload` 只省外部上传，不应被描述为完成分发。`--sync-only` 不打包上传，不创建新的已上传事实。

### 哈希清单与初始重建

```powershell
python tools/manifest.py --help
./tools/pull.ps1
python tools/publish.py --force --no-upload
```

`manifest.py` 支持缓存扫描与按书／侧更新；清单是已确认同步状态的基线。全量初始重建按以上流程进行，不直接把外部 `.epub` 解包到归档。

### 打包工具（CI 和手动使用）

```powershell
python tools/package_cache_epubs.py --source EPUB --output output/epubs --dry-run
python tools/package_cache_epubs.py --source EPUB --output output/epubs --pattern "*S3_11*"
```

`--source` 直接指定书目录集合；省略时使用 `--cache` 与 `--side` 选择缓存。`--pattern` 按书目录名筛选，`--output` 指定构建目录。打包验证容器、XML 和书内资源，ZIP 的 `mimetype` 必须首项且未压缩；产物保留书目录名。输入不修改，输出不进入书籍内部或版本化档案。

发布 CI 先运行工具测试与归档 health，再执行共享容器／XML／资源检查后打包；没有日文源的 CI 明确只做单侧检查。calibre 是本地补充合法性校验，不是云端必需运行时。自动规范化 CI 的提交与工作站回流边界见 AGENTS。

## 导入与结构维护

### 固定模板规范化

```powershell
python tools/normalize_single.py --dir EPUB/某书/OEBPS/Text
python tools/normalize_single.py --dir EPUB/某书/OEBPS/Text --apply
python tools/normalize_paired.py --root EPUB --jp-root .cache/epub-work/japanese-text
python tools/normalize_paired.py --root EPUB --jp-root .cache/epub-work/japanese-text --apply
python tools/normalize_paired.py --cache 暂存根 --staging --apply
```

single 只处理命令行指定文件或 `--dir`／`--pattern`，可用 `--side cn|jp` 明确重建侧；归档默认中文，未知暂存路径按路径识别，不保证双侧对齐。paired 负责作品／文件选择和配对约束，归档模式仅读日文，双侧暂存模式才可修改两侧。两者调用 `xhtml_template.py`，不承担历史多层标题语义迁移。行模板规则与豁免事实分别在 AGENTS 和 `alignment_rules.py`。

### 多层标题迁移

```powershell
python tools/migrate_heading_breaks.py --cache EPUB
python tools/migrate_heading_breaks.py --cache EPUB --apply
```

`--book GLOB` 可重复，`--verbose` 逐书列计划。按整书计划同时改变 XHTML／被引用 CSS，预检未知结构、路径越界、样式缺失和分层文字变化，任一失败不开始写入；写入失败回滚该书已写文件。它负责迁移合同，标题正文规范在 AGENTS。

### BW 提取预处理

```powershell
python tools/bw_preprocess.py 原始.epub --book-id S4_05 --check
python tools/bw_preprocess.py 原始.epub --book-id S4_05 --header-map 映射.json --out 暂存输出 --apply --staging
python tools/bw_preprocess.py 显式分页目录 --dry-run
python tools/bw_preprocess.py 显式章节目录 --merged --check
```

默认预览，`--apply` 才写入；`.epub` 写入必须显式 `--out --staging`，保留源文件并产出预处理包。目录目标在 `EPUB/` 可直接 `--apply`；临时目录就地处理需 `--apply --staging`。`--rules` 指定规则表，`--unpacked`／`--unpacked-dir` 指定解包输出。执行写入前使用显式暂存路径并先预览；完整参数由 `--help` 提供。

默认分页契约要求 L3 的 `main` 容器，供合并器定位正文；`--merged` 只适用于目录，按合并后契约验证，不能用分页契约检查已合并章节。`--check` 在内存模拟转换、重命名和资源更新；正常产出使用同一门禁，不只验证标题槽位。

`--book-id` 只用于已确认作品号和内容顺序的包。显式逐页映射保存在 `bw_page_header_overrides.json` 或 `--header-map` 指定文件中，正整数为内容序、null 为包装页；缺页、额外页或非法序号均阻断。图片前缀与全部引用同步更新。无标题尾声／附录边界必须按 AGENTS 内容规则确认，不能以 h1 或页码猜测。

整本纯图册没有文本输入时跳过，不输出产物；`--force-image-only` 是显式强制开关。`S6_24.12.10` 画集本身不归档，其中 SS 的独立转录 EPUB 已恢复常规配对，不能把画集例外套给 SS。

### 分页合并

```powershell
python tools/merge_bw_pages.py 分页目录 --book S4_05 --dry-run
python tools/merge_bw_pages.py 分页目录 --book S4_05 --out 显式章节输出 --apply --staging
```

默认预览，`--apply` 必须显式 `--out`；目标在 `EPUB/` 无需暂存开关，临时输出加 `--staging`。输入须经过 BW 预处理，输出章节已套固定模板。带表头输入保留已确认内容序；作品号混用、非法零序号、冲突或重复序号阻断。没有表头的历史页仅生成临时顺序，最终语义命名须人工确认并更新资源引用。

按 AGENTS 的源衔接规则处理 pb、篇首图片与标题；目录标题仅精确匹配单元首页时补入，缺失则保留槽位并报告。文本跨页是否同一段断续、图片归属、标题边界和残留噪声输出待确认项，不自动改译文。

图片分页标记由共享 `add_class_pb` 写在既有外层块：p 包装图标在 p，整行 SVG 标在 SVG；保留原有 class、图片引用、尺寸与 viewBox，不额外包 p、不增删行。章尾整页图片也属于图片边界。BW 合并入口复用 `inject_pb_css` 注入分页样式及 `svg.pb` 块级显示保护，已有 `.pb` 规则不能成为漏掉 SVG 保护的理由。该合同落实 AGENTS 的换页衔接与图片排版规范，本文不另立规则。

### S5 合订卷拆分

```powershell
python tools/split_s5_epubs.py 显式源目录 --packed-out 显式打包暂存 --unpacked-out 显式解包暂存
python tools/split_s5_epubs.py 显式源目录 --packed-out 显式打包暂存 --unpacked-out 显式解包暂存 --apply
```

默认预览；两个输出路径均必填，视作显式暂存，不能位于仓库缓存或 OneDrive。`SPLIT_SPECS` 是已确认源卷与页区间的唯一实现数据，新增卷／源重排先核对页区间再改规格。全部指定源、规格、页区间、资源与产物契约在输出前完成验证；源缺失、页缺失或任一契约失败非零退出且不输出成功产物。复用 BW 预处理／合并／资源重命名与容器验证，不另维护第二套导入规则。

### 内容序平移与空页清理

```powershell
python tools/shift_content_sequences.py EPUB/某书 --work-id S4_05 --offset 1
python tools/shift_content_sequences.py EPUB/某书 --work-id S4_05 --offset 1 --apply
python tools/fix_empty_placeholders.py --cache 显式书籍根
```

shift 用单次映射改文件与 XHTML/OPF/NCX/nav/CSS/SVG/XML 引用，防止相邻序号级联覆盖；歧义旧裸页引用保持不动并报告。空页工具只删除经判定无文本、无图/SVG 的编号页并前移后续序号，默认预览、`--apply` 写入。日文修改在显式暂存模式完成，不修改参考缓存。

### 配对页边界修复

```powershell
python tools/fix_legacy_pagebreak_br.py --root EPUB --jp-root .cache/epub-work/japanese-text
python tools/restore_cn_scene_breaks.py --root EPUB --jp-root .cache/epub-work/japanese-text --book S6_22.06.10
python tools/sync_pb_tags.py --root EPUB --jp-root .cache/epub-work/japanese-text
```

这些入口默认预览，确认后加 `--apply`；只写中文，日文仅读。legacy 删除逐边界确认的多余旧换页行；restore 只补有源证据且总差额一致的场景分隔；pb 在一一对应段落添加缺失 class，不增删行。行数、块类型或差额条件不足时拒绝；真实一段对多段关系先人工确认语义，不由这些工具拆合。

### 中文图片行包装

```powershell
python tools/wrap_cn_image_lines.py --root EPUB --wrap-only
python tools/wrap_cn_image_lines.py --root EPUB --jp-root .cache/epub-work/japanese-text --apply
```

`--wrap-only` 仅包装裸 img、不删结构行；完整模式只接受配平的图片专用 div 区段，改写删除结构行前需指定日文参考并验证配对行数。普通带语义 div 不处理。输出修改计划与拒绝原因，默认预览。

### Note 顺序重排

```powershell
python tools/check_note_order.py --root EPUB
python tools/reorder_notes.py --root EPUB
python tools/reorder_notes.py --root EPUB --apply --no-backup
```

check 与 reorder 共享 `notes_core.py` 的阅读顺序。后者先计划 Note 条目、编号和正文引用的完整映射，再写入；默认预览，备份默认 `.cache/reorder-backup/`，它是工作产物而非正文编辑目标；可用 `--backup` 指定，`--no-backup` 用于已由 Git 保存的归档或 CI。`--pattern` 限定书籍。参数中的 `--cache` 是读源兼容入口，不能用于写缓存。

## 交稿转换

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

## 只读检查与诊断

### 文档合同检查

```powershell
python tools/check_project_docs.py
```

只读核验本地链接／锚点、顶层 `docs/*.md` 在 [文档索引](../docs/README.md) 的登记、活跃文档开头回指索引的入口（前 20 行内的相对链接；维护记录与冻结归档不逐项要求），以及 `tools/*.py`、`*.ps1`、`*.json` 的说明覆盖；缺项非零，供 CI 和后续文档整改复跑。

**单一来源检查**（同一规则只在一处写正文，其余处只留指针）：① 裁定表主表内「同一锚点 + 相同义项标识」不得重复登记——分层与同词异译以不同义项标识并列属合法；锚点列只写锚点时，义项标识回落到「备注」列（原「理由」列）；② 翻译规范与译名选取规范正文不得出现裁定表锚点的取值，同行带 `→`／`＝`／「译作」等映射标记即视为复述，指针行（含裁定表链接）与带 `<!-- single-source-ok -->` 白名单标记的行除外；③ 规范不得复制 `check_translation_spec.py` 的词表（命中 `P9_EVENT_SUFFIXES` 过半即报）；④ 规范与裁定表内 `§X` 形式的引用必须指向真实存在的小节。它检查可机械覆盖的合同，不替代对文档语义之间是否重复或冲突的判断。


### 对齐检查

```powershell
python tools/check_alignment.py --strict
python tools/check_alignment.py --root EPUB --jp-root .cache/epub-work/japanese-text --strict
```

检查双侧模板及完整表头配对、行数和 h1/h2、图片、独占 br、pb 的物理位置。已确认配对规则只调整有依据的共同范围／顺序，其余结构差异照常阻断；位置规范唯一在 AGENTS。支持 `--cache` 旧双侧根、`--root` 中文与 `--jp-root` 日文独立根、重复 `--book` 与 `--output` 报告；L6 标准正文必须为 p，中文列表包装页可为 li；中文作品级包装页原有多段语义 div 的开标记与完整首段 p 同行也可保留。裸 div 或裸文字不作标准正文豁免。普通模式完整报告后返回成功，strict 有问题非零。缺侧目录按空集合处理，不应据未配对书宣布双侧通过。例外从 `alignment_rules.py` 读取，报告应保留实际检查与未配对范围。

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

### 图片对应核对

```powershell
python tools/compare_epub_images.py --pattern "*S3_*" --output 显式报告目录
```

读两侧图片和 XHTML 引用，区分字节相同、解码像素相同、稳定命名对应与感知候选。双页范围可对应连续单页；旧命名依表头／槽位条件，不把页码猜为内容序。感知相似可能有修嵌或替换，必须视觉确认。`--cache` 指定参考根。

### 翻译规范检查

```powershell
python tools/check_translation_spec.py --cache EPUB --output 显式报告目录
```

P1–P16 与规范条款的完整对应表唯一维护于 [翻译规范](../docs/translation-spec.md) 七。检查器只发现可机械形状，warning／info 与例外须人工判断，不自动改正文。`--pattern` 限定书名，`--top` 只控制样例显示；输出 TSV／JSON／Markdown。

P9 赛事项目名的封闭例外集合唯一维护于 `check_translation_spec.py` 的 `P9_EVENT_SUFFIXES`；P16 繁体字表唯一维护于同文件的 `P16_TRADITIONAL`（由 OpenCC `TSCharacters` 生成，只留中文正文确属繁体形的字）；两处只改集合不复制到文档。改变规则语义才更新规范与合同，并运行 `test_translation_spec.py`。

### 字符级规范化

```powershell
python tools/text_norm.py --root EPUB
python tools/text_norm.py --root EPUB --apply --report 显式报告.md
```

只执行规范可确定的字符替换，XML、行数、标签、文件名与引用保持有效。规则实现唯一在 `text_norm.py`，不另写批量替换器。`--pattern` 限定书籍，`--summary` 供提交摘要，`--top` 控制报告样例。选词需原文的事项走术语或复核 skill。

### 单侧成品体检

```powershell
python tools/check_epub_health.py --root EPUB --strict
python tools/check_epub_health.py --only css-layout --tsv 显式报告.tsv
```

汇总既有项目规则，检查 XML、ruby、正文原子块、标题、加粗、悬空引用、图片资源和 CSS 分页保护；资源检查覆盖全部 CSS url／@import、SVG 和导航引用。主 `style.css` 检查完整布局声明，辅助 CSS 只阻断 html／body 非零左右边距，不能要求每份字体 CSS 重复主样式，不另立规则。`--pattern` 筛书、`--only` 选项、`--top` 控制样例、`--json`／`--tsv` 显式报告。strict 有 error 非零；每项必须有负向测试。

### calibre 补充合法性检查

```powershell
python tools/check_epub_validity.py EPUB --structural --strict
python tools/check_epub_validity.py 成品目录 --recursive --report 显式报告.txt
python tools/check_epub_validity.py --list-categories
```

使用 calibre Check Book，读取包或解包书籍，检查容器／OPF、导航链接／锚点、字体图片、编码、ID 与 CSS。源不改，临时解包使用系统目录；每个 worker 用系统临时 `CALIBRE_CONFIG_DIRECTORY` 隔离配置，不读个人插件、不写用户配置。`--structural` 排除 CSS 顺序／重复／空块与 HTML 大小建议，类别映射按 calibre 类型而非本地化消息；unknown 类别照报。

支持 `--pattern`、`--jobs`、`--calibre-threads`、`--timeout`、`--min-severity`、重复 `--exclude-category`、`--report`／`--json`／`--tsv`、`--quiet`、`--calibre-debug`。0 是完成；strict 过滤后仍有问题为 1；环境／输入前提错误为 2。此为可选补充，未安装时说明未运行，不能替代共享发布前检查。

### 译名表落地核对与术语审计

```powershell
python tools/check_translation_table.py --table 显式译名表.xlsx --strict
python tools/check_translation_table.py --table 显式译名表.xlsx --audit-rulings
```

读取外部表、日文参考、归档中文与《译名裁定总表》；表路径按翻译规范“外部依赖与核验”动态取得。列名支持 `--sheet`、`--ori-col`、`--trans-col`、`--type-col`、`--debuts-col`、`--ruby-ori-col`／`--ruby-trans-col`。`--epub`、`--jp-dir`、`--out`、重复 `--book` 指定范围。判定顺序为**同形例外 → 裁定表 → 译名表**：先按规范折叠查询和源，再查裁定表（锚点列取反引号内容与裸 `<ruby>…</ruby>` 两类——含注音的锚点按裁定表 §12 格式约定不加反引号，预览才渲染注音；同一锚点多条登记合并为候选集合，裁定列 `／` 分隔多写法，判定列标 `人读` 的条目跳过并在报告里单列），未命中才按译名表 `Base_Trans` 判定；裁定未落地单独成节、不并入 `--strict` 阻断。**注音判定**：裁定条目带注音（`<ruby>基文<rt>注文</rt></ruby>`）且该书日文侧存在带注音的该锚点时，中文侧必须出现裁定的复合串 `基文（注文）`——剥注音的判定分不出 `<rt>Gungnir</rt>` 与 `<rt>冈格尼尔</rt>`。**匹配轴**：判定列还可声明日文侧的认定方式——`匹配基文`（默认，注音不参与）、`严格全文`（日文须写出 `<ruby>基文<rt>注文</rt></ruby>` 复合串，裸写基文不在本行范围，既不判落地也不报未落地）、`匹配注文`（只认注文，基文可以是别的字，同一读音的当て字变体）；同一锚点多行须声明同一轴，混用退回默认。

`--rulings` 指定《译名裁定总表》（默认仓库内路径）；`--no-rulings` 是诊断绕过，不可据此要求回改已登记裁定。`--include-suspect` 展示短串候选、`--limit` 是局部调试，不能称全表验收。`alignment_rules.TRANSLATION_HOST` 和 `SETTLED_ANCHORS` 是已确认跨书归属／同形词事实源。`SETTLED_ANCHORS` 每条含 `note`／`scope`／`status`：**抑制只在该锚点被判定过的那本书内生效**；`status=settled`（已判定同形不同义）始终抑制，`status=待裁定`（两案都成立、尚未定）在裁定表登记该锚点后失效、改按裁定判定。

落地未命中只产生待判项，不等于误译；回原文判断普通词／专名、单复数与语境，执行 [术语统一 skill](../.agents/skills/translation-term-unification/SKILL.md)。strict 存在待判未落地项非零。`--audit-rulings` 只核裁定表与译名表：锚点全角英数字母、裁定列解析不出写法（散文格式漏标 `人读`）、锚点 `<rt>` 与 `Ruby_Ori` 不一致（一格多锚点时**逐块**核对，逐字分解的碎片按基文长度跳过）、译名表同锚点多译法未在裁定表登记、同一锚点多行匹配轴混用、声明了匹配轴但锚点不是单段 ruby，出问题非零；改裁定表后重跑。

### 提交级校对复核

```powershell
python tools/proofread_review.py --worktree
python tools/proofread_review.py 提交号 --path EPUB --out 显式报告目录
python tools/japanese_lookup.py S3_03 04 55
python tools/audit_risk.py --old "旧句" --new "新句" --jp "日文"
```

`proofread_review.py` 编排 Git 行级配对、`japanese_lookup.py` 原文提取、`audit_risk.py` 风险提示；不修改正文。支持 `--repo`、`--jp-base`、`--no-jp`、`--no-audit`；未提取／未诊断的侧明确未核验。原文 lookup 的 `--raw` 保留标签，`--jp-base` 指定参考；risk 的 `--json` 输出结构。

产物为 `changes.tsv`、`semantic.tsv`、`spec.tsv`、`groups.txt`。一物理行合一条记录，用最小差异分级：spec 为确定规范形状，tiny 为 ≤2 字且全属虚词，local 为 ≤12 字局部变化，rewrite 为更大变化或整段增删；spec 仅在整段最小差异都能由规范解释时放行。数字／字母不当标点剥除。

`line` 使用 Git 行级配对的新侧行号，纯删除回旧侧行号；不可用 word-diff 物理行推算。`jp` 是当前参考的同行，不证明历史提交对应关系；行数变动时人工检索上下文。risk 标记包括否定、数字、疑问、字形、加粗标点、嵌套引号、受控术语和明显增删；它们只提示复核优先级。人工处置和抽样范围以 [校对复核 skill](../.agents/skills/proofread-review/SKILL.md) 为准。

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
- **文件导出与摘要**：`-o` / `--out` 导出结果到文件；`--info` 打印当前工作表、总匹配行数、展示行数与列数摘要。

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
