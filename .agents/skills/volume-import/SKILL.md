---
name: volume-import
description: index-X 新书成品生成工作流（交稿 docx＋图片素材＋制作信息＋简介＋日文原文 → EPUB/ 成品）。用于「把某卷做成成品／交稿转成品／入库」：先做材料核对，材料不齐必须停下来向用户索取，不得自行编造封面、简介或制作信息；齐备后按日文工作源逐行比对中日结构，把取舍写进导入计划，再用原子工具链分别渲染正文、图片、包装页与容器文件，跑门禁、发布并提交。触发词：新书导入、成品生成、交稿转成品、入库、把某卷做出来、volume import。
---

# 新书成品生成（index-X）

文档职责与入口见 [文档索引](../../../docs/README.md)。命令合同见 [工具说明](../../../tools/README.md)，
仓库级规约（编号、表头、固定行模板、写入边界）见 [AGENTS.md](../../../AGENTS.md)。

本 skill 管「把一份交稿 + 一套素材做成一卷可发布的成品」。译文用词、译名取舍不在本流程内：
那属于 `translation-term-unification` 与 `proofread-review`，本流程**只做结构**——不改译文用词，
只按日文工作源把段落边界、空行、插图与注脚位置对齐。

## 一、材料核对（不齐不动手）

成品需要**七项材料**，缺任何一项都必须停下来找用户要，不许自己补：

| 材料 | 说明 | 缺失时的典型坏做法（禁止） |
| --- | --- | --- |
| 交稿正文 | `.docx`，带 Heading 1 章标题、`\|基文[注音]`、`【*译注：…】`、`【*插图】` | 用上一卷正文凑、自己转写 |
| 图片素材 | 目录，含封面、彩页（Contents／Illustrations）、正文插图 | 用日文原图顶替用户指定的压缩版、漏掉封面 |
| 制作信息 | 制作信息页正文块（L4 起，含「翻译：／校对：／美工：」署名） | 抄上一卷的署名、留空占位 |
| 简介 | 简介页正文块（L4 起：h1 ＋ 空行 ＋ 导语 ＋ 正文段） | 自己写简介、拿后记凑 |
| 作品号与书目录名 | 如 `S4_04` 与 `[S4_04]某暗部的少女共栖 4X` | 猜卷号、按中文标题编目录名 |
| 日文原文 | 已同步进 `.cache/epub-work/japanese-text` 的该作品号书目录 | 拿另一卷日文对齐、跳过对齐直接写 |
| 模板书 | 同系列已入库的一卷（取样式表、容器形状与 calibre 元数据块） | 凭空写 style.css／content.opf |

核对命令（缺项非零退出，并把要补的东西列成可直接发给用户的话）：

```powershell
python tools/import_materials.py --docx 交稿.docx --images 图片素材目录 `
    --info 制作信息.txt --intro 简介.txt --work S4_04 `
    --book-dir "[S4_04]某暗部的少女共栖 4X" `
    --jp-root .cache/epub-work/japanese-text --template "EPUB/[S4_03]某暗部的少女共栖 3X"
```

**缺项时的动作**：把缺失清单原样转达用户并停下，例如「还缺：图片素材目录（封面／彩页／正文插图）、
简介正文块。请提供这两项后我再继续。」——不要先做能做的部分，不要用占位图或自拟简介开工。
日文原文缺失时先按 [工具说明](../../../tools/README.md)「拉取」把外部源同步进缓存，再重跑核对。

另需人工确认（工具不代查）：`python tools/publish_auto.py --dry-run` 显示三副本无待发布改动。

## 二、六步流程（每步一个原子入口）

| 步骤 | 入口 | 写什么 | 失败怎么办 |
| --- | --- | --- | --- |
| 1 交稿清单 | `import_docx_outline.py` | 只写显式 `--out` 报告 | 有阻断项 → 回交稿修，不改工具 |
| 2 结构比对 | `import_align_plan.py` | 计划骨架 `plan.json` ＋ 缺口报告 | 章节数对不上 → 交稿或日文源有问题，先查清 |
| 3 正文 | `import_build_text.py` | `<书目录>/OEBPS/Text/*.xhtml` | 行数不齐 → 补计划改动，**不写盘** |
| 4 图片 | `import_images.py` | `<书目录>/OEBPS/Images/*` | 指纹低置信 → 打开图看过再落位 |
| 5 包装页与容器 | `import_build_wrappers.py` | 包装页 ＋ nav/ncx/opf/mimetype/container/style.css | 缺正文或缺图 → 先补前两步 |
| 6 规范化与门禁 | `text_norm.py` 等既有门禁 | 字符级规范化 | 门禁非零 → 按报告修，不许放宽门禁 |

### 1. 交稿清单（材料形状门禁）

```powershell
python tools/import_docx_outline.py 交稿.docx --check
python tools/import_docx_outline.py 交稿.docx --out .cache/epub-work/import/outline.tsv
```

输出段落清单（idx／样式／行类型／行内记号统计）与章结构。阻断项包括：没有 Heading 1、
**段内换行（`w:br`）**、注音或译注记号未闭合；提示项包括全角空格、段内制表符、独占成段的译注。
段内换行必须先回交稿拆段——固定行模板一段一行，工具不会替你猜。

### 2. 结构比对与计划

```powershell
python tools/import_align_plan.py 交稿.docx --work S4_04 --book-dir "[S4_04]某暗部的少女共栖 4X" `
    --out .cache/epub-work/import/plan.json --report .cache/epub-work/import/gaps.txt
```

把交稿按 Heading 1 切章，与日文工作源内容文件一一对应，再按**日文物理行**逐行比对，
输出缺口窗口与建议改动。对齐口径与 BetweenLines 的跨语言对齐同形：日文一行＝一个行单元，
中文侧允许 1:2，绝不允许多段日文并成一行；关系词表就是计划里该填的改动：

| 关系 | 含义 | 建议 op | 判据 |
| --- | --- | --- | --- |
| `1:1` | 一一对应 | — | 不动 |
| `1:0`（日文是 `<br/>`） | 日文有场景分隔行、中文没有 | `insert_br_after` | 补在该行之前的正文段之后 |
| `1:0`（日文是 `<p>`） | 日文这段被并进了相邻中文段 | `split` | 按语义边界拆回两段，`into` 必须来自译文本身 |
| `0:1`（中文是空段） | 中文多出排版空段 | `drop` | 插图前后、章末的多余空段 |
| `0:1`（中文是独占译注） | 独占成段的译注 | `note_to_prev` | 若确认是制作指示而非读者内容，改 `drop` |
| `1:2`／`2:2` | 中文侧多出一行 | `merge_prev`／`split` | 中文多拆的并回上一段；日文两段被并成一段的拆开 |

**纪律**：

1. 只动结构，不改用词。`split` 的 `into` 只能是原句按语义切分（最多补一个句末「。」），
   不得改写、增译、漏字。
2. 不为凑行数添加原始作品里不存在的空行或标签；`insert_br_after` 只在日文真有 `<br/>` 时用。
3. 日文原文是只读参考，不修改；不齐的账记在计划里，不记在日文侧。
4. 拿不准的（换序、疑似漏译、制作指示）先问用户或留待后续校对，不要在计划里蒙一条。
5. 计划文件是任务工作产物，放 `.cache/epub-work/import/`，**不提交**；结论由成品与提交承载。

### 3. 正文

```powershell
python tools/import_build_text.py .cache/epub-work/import/plan.json `
    --out "EPUB/[S4_04]某暗部的少女共栖 4X" --apply
```

写盘前逐章比对物理行数：**任何一章与日文不符就整批不写**，非零退出。段落首尾的 ASCII 空格
与不换行空格会被清掉（交稿排版噪声）；段内的全角空格是排版意图（分字、对齐），原样保留。

### 4. 图片

```powershell
python tools/import_images.py suggest --src 图片素材目录 --jp-dir .cache/epub-work/japanese-text/[S4_04]…/item/image --work S4_04
python tools/import_images.py apply .cache/epub-work/import/plan.json --out "EPUB/[S4_04]某暗部的少女共栖 4X" --apply
```

`dst` 必须带作品号前缀（`S4_04-cover` 形式）；封面／彩页／正文插图在计划里用
`role` 分别标成 `cover`／`illustration`／`body`，正文插图按出现顺序落行。指纹距离大的建议
必须打开图看过后再落位。

### 5. 包装页与容器

```powershell
python tools/import_build_wrappers.py .cache/epub-work/import/plan.json `
    --template "EPUB/[S4_03]某暗部的少女共栖 3X" --info 制作信息.txt --intro 简介.txt `
    --out "EPUB/[S4_04]某暗部的少女共栖 4X" --apply
```

生成 Cover／Illustrations／Information／Introduction 四个包装页与 `nav.xhtml`、`toc.ncx`、
`content.opf`、`mimetype`、`META-INF/container.xml`、`OEBPS/Styles/style.css`。
前置是正文与图片都已就位，缺一即阻断不写盘。`--info`／`--intro` 是页面 **L4 起**的内容行
（第 1 行 h1、第 2 行空行占位），由用户素材决定，工具不内置署名或简介。

### 6. 规范化与门禁

```powershell
python tools/text_norm.py --root "EPUB/[S4_04]某暗部的少女共栖 4X" --apply   # 或 --staging 处理暂存
python tools/check_alignment.py --root EPUB --jp-root .cache/epub-work/japanese-text --book S4_04 --strict
python tools/check_epub_health.py --root EPUB --pattern "*S4_04*" --strict
python tools/check_note_order.py --root EPUB --pattern "*S4_04*"
python tools/check_translation_spec.py --cache EPUB --pattern "*S4_04*"
python tools/publish_preflight.py --source EPUB --jp-root .cache/epub-work/japanese-text
python tools/check_epub_validity.py "EPUB/[S4_04]某暗部的少女共栖 4X" --structural --strict
```

门禁非零就修内容或计划后重跑，不得放宽门禁。`check_translation_spec` 的 P6／P7／P15 之类
属于用词与写法层，按用户当轮的范围决定是否处理；要处理就走术语／校对 skill，不在本流程里顺手改。

## 三、发布与提交

```powershell
python tools/publish_auto.py            # 流程 C：EPUB/ → OneDrive ＋ 缓存镜像，并更新清单
git add EPUB && git commit -F 提交信息.txt
```

* 单本修改以提交承载，不留档；一次落在两本及以上作品才在 `docs/maintenance-records/` 留档。
* 提交信息写清：成品构成（正文／包装页／图片）、来源（交稿、素材、日文卷）、
  结构改动条数（如「补 `<br/>` 4 处、还原被并段 9 处」）、门禁结果与发布方式。
* 只暂存本任务文件，不 push、不建 release。
* 图片素材、交稿、计划文件等外部输入不进仓库。

## 四、实测坑位（都踩过）

1. **独占成段的译注**：整段只有 `【*译注：…】` 时，直接渲染会多出一行；必须 `note_to_prev`。
   其中「居中。上下各空三行。」这类是**制作指示**，确认后 `drop`。
2. **插图前后的空段**：交稿常在 `【*插图】` 前后留空段，日文没有对应行 → `drop`。
3. **章末空段**：下一章标题之前的尾随空段 → `drop`。
4. **`<b>` 段内标点**：渲染后跑 `text_norm.py`，加粗段里的标点会被移到加粗外；
   不要为了好看在渲染期手改标签，否则 `check_epub_health` 的 `bold-punct` 会阻断发布。
5. **OPF 的 id 冲突**：manifest 的 item id 不要用 `id-1`／`id-2`（metadata 已占用），
   否则 calibre 报 `DuplicateId`。包装页工具统一用 `id-t{n}`。
6. **引号与注脚**：注脚引用必须是 `<a class="nodeco" epub:type="noteref" href="S4_04-Note.xhtml#noteN">`，
   且 Note 页条目 id 与正文首次出现顺序一致，`check_note_order.py` 会核对。
7. **全角空格**：段内的 `U+3000` 可能是对齐或分字效果，不要「顺手清理」。
8. **对齐工具不是语义判据**：`import_align_plan.py` 用「汉字重叠＋长度比」替代 BetweenLines 的
   多语言向量打分，只为离线可用；语义级复核仍走 `check_semantic_alignment.py --betweenlines-dir`。
