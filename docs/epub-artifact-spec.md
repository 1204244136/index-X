# EPUB 成品构成规范（部件、必备性与元数据对齐）

文档职责与入口见 [文档索引](README.md)。

本文件是 `EPUB/` **单本成品构成**的规范正文：一本成品由哪些部件组成、各自的职责与必备性、书目录名与包文档元数据的对齐口径、目录条目口径，以及构成变更的执行前置。**部件内部长什么样不在本文件展开**——命名形态见 [EPUB 命名规范](epub-naming-spec.md)，XHTML 行模板与结构见 [EPUB 结构规范](epub-structure-spec.md)，样式表声明见 [EPUB 排版规范](epub-css-layout-spec.md)，译文语言见 [翻译规范](translation-spec.md)；命令、参数与门禁入口见 [工具合同](../tools/README.md)。仓库目录角色（`EPUB/`、`docs/`、`tools/`、`.cache/`…）见 [AGENTS.md](../AGENTS.md)。

## 一、成品的两种形态

- **解包成品**：`EPUB/<书目录名>/`。这是本仓库版本化保存与编辑的对象，含 `mimetype`、`META-INF/container.xml` 与 `OEBPS/` 子树；前两者同时也是「这是一个解包成品」的识别标志。
- **打包成品**：由解包成品打包得到的 `.epub`（OCF 容器），是分发对象。容器层的硬性要求（`mimetype` 为 ZIP 首项且不压缩、内容严格为 `application/epub+zip`、`container.xml` 必须声明 OPF rootfile、manifest 与 spine 自洽、图片必须被 manifest 声明）由打包与校验入口判定。

日文工作源不适用本节：它以 BookWalker 原样布局保存在 `.cache/epub-work/japanese-text/<书目录名>/`（`item/standard.opf`、`item/image/`、`item/xhtml/` 等），是**只读参考**，不受本规范约束。两种布局不得互相套用。

## 二、部件清单、职责与必备性

| 部件 | 位置 | 职责 |
| --- | --- | --- |
| 包文档 | `OEBPS/content.opf` | 元数据（`dc:title` 等）、manifest、spine |
| 导航 | `nav.xhtml`、`toc.ncx`（均位于书目录根） | EPUB3 导航与 EPUB2 NCX 目录；两者条目集合与顺序一致 |
| 样式 | `OEBPS/Styles/style.css` | 主样式表（声明内容见排版规范） |
| 正文 | `OEBPS/Text/<表头>.xhtml` | 章节正文；作品级包装页亦在此目录 |
| 资源 | `OEBPS/Images/*` | 封面、彩页、正文插图 |
| 容器 | `mimetype`、`META-INF/container.xml` | OCF 容器声明 |

**作品级包装页**（无内容序，命名见命名规范）分两组，**成员以实现常量为准**（`tools/epub_ids.py`），本文件只写分组语义与必备性：

- **纯图片页**：封面、封底、彩页——只承载图片，不承载正文文本；不得开放 L5 列表槽位（见结构规范）。
- **列表型包装页**：制作信息、简介、译注、特别篇——可承载文本块，是 L5 列表槽位规则的适用范围。

**必备性**：`Cover`（封面）与 `Information`（制作信息）**必备**；`Illustrations`（彩页）、`Introduction`（简介）、`Note`（译注）、`Special`（特别篇）**按作品实际**（有素材才做，缺页本身不是缺陷）。

## 三、书目录名与元数据对齐

- 书目录名形如 `【作品号】<标题>`：全角方括号内是完整作品号（编号规则见 AGENTS「系列编号」）。定界符**必须用全角 `【】`**：它不是文件系统、PowerShell／bash 通配、glob 或正则的元字符；半角 `[]` 会在路径匹配与转义上反复踩坑（旧形态已于 2026-10-12 全库迁移）。
- **`dc:title` 必须逐字节等于书目录名**（含 `【作品号】` 前缀）。书名内部原有的半角／全角空格照目录名保留。
- `file-as` 若存在，其值必须与 `dc:title` 相同。
- `toc.ncx` 的 `docTitle` 必须等于 `dc:title`。
- `toc.ncx` 的 `dtb:uid` 必须等于包文档的 `unique-identifier`（即 `id="BookId"` 那条 `dc:identifier` 的值）。
- `unique-identifier`（`dc:identifier id="BookId"`）在库内必须唯一。

## 四、目录条目口径

- `nav.xhtml` 与 `toc.ncx` 的条目集合与顺序必须一致。
- `nav.xhtml` 必须符合 HTML5 的 XHTML 语法：`<html>` 的直接子元素只有 `head` 与 `body`，`<head>` 内只放元数据类元素（`title`／`meta`／`link`／`style`／`base`／`script` 等），且 `<title>` 非空。历史遗留的杂散元素（如 `head` 或 `html` 下的裸 `<br/>`）属阻断项。
- 首条目为「制作信息」；**封面不进目录**（封面是阅读起点，不作为跳转项）。
- 中文独有的作品级包装页（制作信息、简介、译注）不参与中日行对齐；日文独有的原样快照包装页（`p-fmatter-*` 等）不受本节约束。
- 译注页排在 `spine` 末尾；是否进目录按现有各卷口径，不在本规范强制。

## 五、机器判定与级别

判定实现、检查项名称、参数与失败边界统一见 [工具合同](../tools/README.md)；本文件不复制常量、正则与例外清单，已确认的例外只登记在 `tools/alignment_rules.py`。

级别口径：**必备部件缺失、书目录名与 `dc:title` 不对齐、`docTitle` 与 `dc:title` 不对齐、目录条目口径、`nav.xhtml` 头部结构不合 HTML5 语法、`unique-identifier` 不唯一、`dtb:uid` 与包文档 identifier 不对齐**属阻断项（八项存量已于 2026-10-12 全部清零）。判定实现、库级复核方式与例外清单见 [工具合同](../tools/README.md) 与 `tools/alignment_rules.py`；历史存量与排队情况见 `docs/maintenance-records/`。

## 六、构成变更的执行前置

书目录改名在同步链路上等于「旧名删除 ＋ 新名新增」（C1 簇无改名通道）：**先在工作区完成改名与内容改动，再移除缓存中的旧目录，最后以 `--from cache` 发布**；在中间态不得运行默认方向的发布——那会把旧名从归档与 OneDrive 一并清掉。命令、检查点与回退见工具合同。

## 七、维护约定

本文件按「同一规则只在一处写正文」维护：部件与必备性的**正文**在本文件，判定实现在 `tools/`，例外在 `tools/alignment_rules.py`，流程在 `.agents/skills/`。新增或调整构成规则时，同步更新 [文档索引](README.md) 与 [工具合同](../tools/README.md) 的相应指针，不在此复制工具参数。
