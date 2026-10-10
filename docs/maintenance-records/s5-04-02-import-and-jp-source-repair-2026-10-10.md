# S5_04_02 中文成品入库与日文源目录修复（2026-10-10）

本记录只反映本轮实际做了什么、依据是什么、验证结果如何。规范条文以 [AGENTS.md](../../AGENTS.md) 与 [版式规范三份](../../docs/README.md) 为准，命令合同以 [工具说明](../../tools/README.md) 为准，本文件不复制条文。

## 一、范围

| 项 | 内容 |
| --- | --- |
| 新增作品 | `S5_04_02`（外典书库 4 第二篇）中文成品 `EPUB/[S5_04_02]某魔法的禁书目录外传 让御坂美琴和食蜂操祈卿卿我我的完全乱来的方法X` |
| 材料来源 | 中文合订卷 `某魔法的禁书目录 外典书库 4.epub`（他人制作）下半部分 `p-010`~`p-024`；日文工作源 `.cache/epub-work/japanese-text/[S5_04_02]…`；封面 `S5_04_02-Cover.jpg`；译名与注音沿用日文侧已有工作源 |
| 涉及工具 | `import_align_plan.py`／`import_build_text.py`／`import_build_wrappers.py`／`import_images.py`／`text_norm.py`／`publish_auto.py`／`sync_core.py`／`alignment_rules.py` |
| 涉及书籍数 | **1 本**（中日同一作品计一本），按 AGENTS「单本修改以提交承载」本可只留提交；因同时改了 6 个共享工具，按工具改动的记录要求补本档 |

## 二、日文源修了什么（同步工具失败的根因）

用户先用 calibre 给没有目录的日文成品补了目录，之后 `pull.ps1 -SyncToEpub`（即 `publish_auto.py` 流程 A）一直失败。复现与定位结论：

1. calibre「生成目录」把 8 个带小节锚点的 XHTML（`S5_04_02-03/04/05/06/08/09/10/11`）重新序列化，**丢掉了 `<!DOCTYPE html>` 行与 `<head>` 里的 `<meta charset="UTF-8"/>`**，XML 声明也换成了单引号写法。
2. 直接后果：违反固定行模板（L2 必须是 DOCTYPE），`check_alignment` 报「L2 非 DOCTYPE／L3 非头部合并行…」，`publish.py --sync-only` 的发布预检阻断 → `pull.ps1` 解压成功但清单与 `pull-state` 不推进。
3. 二次后果：每个文件**少一行**，该 8 个文件全部物理行号整体上移一位，中日按行对齐跟着错位（本轮初次对齐时 `深度七`~`深度一` 首段各多出一行即由此而来）。
4. 三次后果：缓存内容已是新的 OneDrive 内容、而清单基线未推进，`publish_auto.py` 把它判成「OneDrive 与本地对同一本书都有改动（已分叉）」，给出的两条命令都会再次撞上同一个门禁——状态无法自愈。

处置：

- 只恢复 L1／L2（XML 声明、DOCTYPE 行、head 里的 meta charset），不动任何正文行，保留 calibre 为目录加的 `<h2 id="toc_N">` 锚点；修复后的 15 个文件逐个通过 `check_alignment.check_file`。
- 修复包按日文源导入合同回流：写入 OneDrive 日文源 → `./tools/pull.ps1 -Side japanese -Pattern "*S5_04_02*" -SyncToEpub` 重新解压并推进清单与 `pull-state`。**该路径此前必失败，现报「发布预检：1 本；…；问题 0 条」「成功: 1 本」，退出码 0。**
- `publish_auto.py` 增加「已完成的拉取」判定（见第三节），避免同类状态再次要求人工在两条都走不通的命令里选边。

## 三、工具改动

| 工具 | 改动 | 依据 |
| --- | --- | --- |
| `import_align_plan.py` | `split_title` 先折叠 `行　间` 的排版空格；新增 `深度N` → 语义后缀 `DepthN`（保留了副标题的 h1）；`行间` 带副标题时保留副标题，不再当序号丢掉 | 命名规范二「某些作品使用与正文标题对应的专用语义后缀…应按作品原有命名保留」；外典书库本篇的章题是 `深度八…深度一`，工具原先识别不出、骨架留空 `fname` |
| `import_build_wrappers.py` | 彩页改为可选项（无 `role=illustration` 时不再阻断，也不生成 Illustrations 页）；新增计划字段 `intro_fname`，简介页可占某个内容序 | S5 外典书库各卷的既有形状是「封面＋制作信息＋占 `-01` 的简介页」，日文侧 `-01` 是整页作品扉页、中文侧是文本化简介（`alignment_rules.TEXTUAL_IMAGE_HEADERS` 已登记）；原实现要求每本都有彩页与正文插图，6 本既有 S5 作品都不满足 |
| `import_images.py` | 去掉「至少一张 `role=body` 正文插图」的硬门槛 | 同上；正文插图数量与计划是否一致由 `import_build_text.py` 渲染时逐行断言，不需要第二道更严的门槛 |
| `import_build_text.py` | 译注页正文改为**原样写入**，不再二次 `esc_ruby` | 译注正文来自 `extract_notes(esc_ruby(...))`，已是可安全嵌入的行内 XML；二次转义把译注里的 `<ruby>` 变成 `&lt;ruby&gt;` 字面文本（本篇 note12 复现，全库仅此一处） |
| `text_norm.py` | 问叹顺序改为**整段连段重排**（`？` 在前、`！` 在后），不再只交换相邻一对 | 旧规则 `！[？?]` → `？！` 对 `！！！？？？` 不收敛：反复替换在 `！？`／`？！` 之间摆动且长度变化，产出的交错形态也不满足「问号始终在感叹号左边」。全库归档混排连段主导形态是 `？？？！！！`（235 处），新规则对既有文本是空操作 |
| `publish_auto.py`／`sync_core.py` | 新增 `onedrive_book_matches_cache()`；漂移书中「缓存与 OneDrive 新内容逐字节相同」的判为**已完成的拉取**，按流程 A 补跑并跳过流程 B，不再要求人工选边 | 见第二节第 4 点：该状态下没有任何会被覆盖的本地改动，两条人工选项命令实际上都走不通 |
| `alignment_rules.py` | `TEXTUAL_IMAGE_HEADERS` 登记 `S5_04_02-01` | 与 S5 其余 6 部作品同一族例外（日文整页作品扉页 ↔ 中文文本化简介页） |

`tools/README.md` 已同步 C1 统一入口、C2 成员表与六步说明、C5 幂等要求。

## 四、中文成品构成

- 正文 14 个文件（`-02_Prologue` … `-15_After_the_Epilogue`），内容序与日文侧 `S5_04_02-02`~`-15` 一一对应；`深度八`~`深度一` 按作品原有命名取后缀 `Depth8`~`Depth1`。
- 包装页 3 个：`-Cover`、`-Information`（源版权页署名「翻译：虹岛喵姬」，模板同 S6_24.06.07 的「网翻」块）、`-01_Introduction`（简介取自合订卷 OPF 的该作品宣传语）。
- 译注页 1 个，12 条，全部来自合订卷 `p-note` 中属于本篇的条目，编号按正文首次引用顺序重排。
- 容器文件 `nav.xhtml`／`toc.ncx`／`OEBPS/content.opf`／`mimetype`／`META-INF/container.xml`／`OEBPS/Styles/style.css`，图片 1 张（用户指定封面）。
- 中日行数：日文侧 15 个文件合计 5058 行，中文侧 14 个正文文件合计 5051 行，差额即日文 `-01` 整页图片页的 7 行（该对属已登记例外）。

### 对齐改动

| 类型 | 数量 | 说明 |
| --- | --- | --- |
| `drop` | 123 | 汉化组在各 h2 前后插入的排版空段；日文侧对应 h2 前后没有空行 |
| `merge_prev` | 2 | 日文一段被中文拆成两段（`S5_04_02-03`、`S5_04_02-11` 各 1 处） |
| `split` | 2 | 日文两行被中文并成一段，按语义边界拆回（`S5_04_02-11`：`何か。`／`何かないのか？`、`ころっとであった。`） |
| `insert_br_after` | 2 | 日文有独占场景分隔行、中文侧缺失（`S5_04_02-03`、`S5_04_02-11` 各 1 处） |

另有字符级规范化 100 处（10 个文件），全部是问叹连段重排。

## 五、验证

| 门禁 | 结果 |
| --- | --- |
| `import_align_plan.py --check` | 14 章「行数全部对齐」，退出码 0 |
| `import_build_text.py --apply` | 逐章物理行数与日文一致后写盘（14 章 + Note） |
| `text_norm.py --dry-run`（全库） | 0 命中 |
| `check_alignment.py --book S5_04_02 --strict` | 问题记录 0，退出码 0 |
| `check_epub_health.py --pattern "*S5_04_02*" --strict` | 各项 0，退出码 0 |
| `check_note_order.py --pattern "*S5_04_02*"` | 顺序与 ID 与正文首次出现顺序一致 |
| `check_translation_spec.py --pattern "*S5_04_02*"` | 16 条，全部 warning／info（P11×10、P16×1、P23×4、P24×1），**无 error 级** |
| `check_epub_validity.py <书目录> --structural --strict` | calibre 9.14 校验 0 问题 |
| `publish_preflight.py --only-books chinese-text/<书目录>` | 「2 本；问题 0 条」，退出码 0 |
| `python -m unittest discover -s tools/tests` | 640 项通过（跳过 2 项） |
| `check_project_docs.py` | 问题 0 条 |

## 六、遗留项（不在本轮范围，未改）

1. `S5_04_02-04_Depth7.xhtml:435` 汉化源残留日文片段「自由調整空気抵抗和升力」（`P16` warning）：属译文用词问题，按 AGENTS「工具与记录的边界」不在导入流程内顺手改，留待通校。
2. `P11` 10 处「あら」译作「啊啦」：规范提示级，且既有裁定只收敛上条诗菜一人，食蜂操祈的用法不在裁定范围。
3. `P23`／`P24` 共 5 条译注起句与谓语词项属存量批次项，与本轮格式无关。
4. 后记署名行 `S5_04_02-14_Afterwords.xhtml` 作裸 `<p>镰池和马</p>`：当前 `import_build_text.py` 没有输出 `class="right"` 的通路，同系列 3 本既有归档是 `<p class="right">`。属版式细节，未手改工具产物，记录待后续统一。
