# S6 两本书名对齐与制作信息页补齐（2026-10-12）

- **触发**：读者反馈「S6 番外两处小问题」——两本 `dc:title` 与书目录名不一致；`[S6_22.06.10]` 缺制作信息页。
- **范围**：2 本作品（`[S6_22.06.10]`、`[S6_24.06.07]`）；中日同一作品算一本，计 2 本。
- **性质**：明显错误订正与规范执行，不构成裁定，不登记 [译名裁定总表](../translation-name-rulings.md)。
- **依据**：[AGENTS.md](../../AGENTS.md) 的编号与目录口径、[EPUB 命名规范](../epub-naming-spec.md)（作品级包装页命名）、[EPUB 结构规范](../epub-structure-spec.md)（作品级包装页 L4–L6 槽位）。本次不改译文用词。

## 一、改动

1. **书目录改名（补结尾 `X`）**，`content.opf` 的 `dc:title`／`file-as` 与 `toc.ncx` 的 `docTitle` 同步为目录名（逐字节相等）：
   - `[S6_22.06.10]某科学的超电磁炮 SS` → `[S6_22.06.10]某科学的超电磁炮 SSX`
   - `[S6_24.06.07]某魔法的禁书目录外传 王牌御坂美琴对女王食蜂操祈！！` → `…！！X`
   - `[S6_24.06.07]` 的标题／`file-as`／`docTitle` 原用全角空格 `U+3000`，已改为半角空格，与目录名一致。
2. **`[S6_22.06.10]` 新建制作信息页** `OEBPS/Text/S6_22.06.10-Information.xhtml`（19 行，作品级包装页），并同步 `content.opf`（manifest 新增 `id37`、spine 置于封面之后）、`nav.xhtml` 与 `toc.ncx`（新增「制作信息」条目；同时移除全库唯一残留的「封面」条目，首条目由「封面」变为「制作信息」）。

## 二、署名素材来源

外部中文源 edition（用户提供）的 `xhtml/p-colophon.xhtml`。血缘校验：该源 Chapter4 的 `Halberd`／`斧枪` 计数为 **44 / 1**，与 2026-10-09 通校提交 `6639aa77` 记录的「基线实践为 Halberd 44 / 斧枪 1」一致（归档当前为 46 / 1）；章节切分 `p-001…p-007` 与 `01_Prologue…07_Afterwords` 一一对应；源 `p-note.xhtml` 首条译注与归档 `S6_22.06.10-Note.xhtml` note1 同文——可确认为本卷直接前身。

署名**照源字面与顺序**：翻译 `icerush、star、大头梦想、胖头鱼、万象之金、上黑`；校对 `白河修、滑膛、亚麻、Cd`；美工 `侠之大者、知一一`；`ePub制作：Drew`。来源标记行取 `网翻`（全库 80 本该槽位无一留空）。

## 三、统计

- 文件：**5 个既有文件改动**（`content.opf`×2、`toc.ncx`×2、`nav.xhtml`×1）＋ **1 个新增文件**；书目录重命名 **77 条路径**。
- `git diff --stat -M`：`5 files changed, 10 insertions(+), 8 deletions(-)`；新增页 19 行。

## 四、验证

| 门禁 | 结果 |
| --- | --- |
| `text_norm.py --pattern "*S6_22.06.10*"` / `"*S6_24.06.07*"` | 0 命中（0 行、0 字符、0 文件） |
| `check_alignment.py --book … --strict`（两本） | 0 问题（9／15 个正文文件） |
| `check_epub_health.py --pattern … --strict`（两本，13 项） | 0 问题（error 0 / warning 0） |
| `check_note_order.py --pattern "*S6_22.06.10*"` | Note 顺序与正文首引一致 |
| `check_epub_validity.py … --structural --strict`（两本，calibre 9.14） | 0 问题 |

## 五、发布

书目录改名在同步链路上等于「旧名删除 ＋ 新名新增」（C1 簇无改名通道，流程 C 对整本删除直接拒绝）。执行序列：`git mv` → 人工删除 `.cache/epub-work/chinese-text/` 下两个旧目录 → `publish_auto.py --from cache`，一次同时完成 **流程 B（旧名 retire：删 OneDrive 旧 `.epub`、清 `pull-state`、丢清单旧键）** 与 **流程 C（新名发布：上传、镜像缓存、加新键）**。

两本执行均报「全部方向执行成功」；复验 `publish_auto.py --dry-run` 为「没有检测到需要发布的内容」；缓存 **81** 本、`manifest.json` 旧键 **0**、`pull-state.tsv` 旧记录 **0**，缓存成品的 `dc:title` 已等于新目录名。

## 六、未纳入本次（另行处理）

- `[S6_22.06.10]` 仍无简介页与 `dc:description`：全库 16/81 同缺（本卷同族多卷亦缺），非本卷独有缺陷；「简介页是否必备」属成品构成规范议题。
- 6 本共用同一 `unique-identifier` 的问题另立项裁定。
- 全库「翻译质量提醒」（5 本）的移除另批执行。

## 七、回退

`git revert` 本次提交可恢复归档内容与制作信息页；但 OneDrive 旧 `.epub` 已由流程 B 删除，如需还原须由缓存／git 内容重新打包上传。
