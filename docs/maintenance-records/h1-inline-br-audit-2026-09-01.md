# h1/h2 内嵌 `<br/>` 审计与迁移基线（2026-09-01）

## 范围与结论

- 范围：版本化 `EPUB/` 下全部 XHTML，只统计 h1/h2 标签内部与标签同行的 `<br/>`。
- h1：410 个文件，分布于 65 本书。
- h2：1 个文件中的 2 个标题，文件为 `S4_01-Special.xhtml`。
- `EPUB/` 中的上述数量是迁移前版本化基线；同日已在中文缓存完成批量迁移，并通过 `publish.py` 同步到 `EPUB/`。

复查残留可使用；迁移完成后应无输出：

```powershell
rg -n "<h[12][^>]*>.*<br\s*/?>" EPUB --glob "*.xhtml"
```

## h1 分类

| 类型 | 文件数 | 处理方式 |
|---|---:|---|
| 三层嵌套标题 | 365 | 将主标题、副标题、英文题名改为语义 span，由 CSS `display: block` 保留视觉分行 |
| 两层嵌套标题 | 18 | 将主标题、副标题改为语义 span；删除末层尾随排版换行 |
| 直接副标题 | 10 | 将主标题和现有 `font08` span 改为两个语义层 |
| `sup` 特殊编码层 | 1 | 保留 `sup`，外包 `heading-code` 语义层 |
| 单层标题末尾 `<br/>` | 16 | 直接删除末尾排版噪声 |

h2 的 2 个标题均为直接文本二层结构，迁移为 `heading-main` + `heading-subtitle`。

代表性历史结构：

```xhtml
<h1><div style="text-align: center;"><span>第一章 <br/></span><span class="font08">副标题 <br/></span><span class="font06">English_Title.</span></div></h1>
<h1>第一章 <br/></h1>
<h1>严重的损伤 <br/><sup>ル9ニ1bカケrサ991マ</sup></h1>
```

规范目标：

```xhtml
<h1 class="heading-lines"><span class="heading-main">第一章</span><span class="heading-subtitle font08">副标题</span><span class="heading-code font06">English_Title.</span></h1>
```

书内已引用的 CSS 同步加入：

```css
.heading-lines > .heading-main,
.heading-lines > .heading-subtitle,
.heading-lines > .heading-code {
  display: block;
}
```

## 缓存迁移结果

执行：

```powershell
python tools/migrate_heading_breaks.py
python tools/migrate_heading_breaks.py --apply
```

- 涉及 65 本书、412 个标题、411 个 XHTML 和 63 个 `style.css`。
- 类型统计：三层 365、两层 18、直接副标题 12（含 2 个 h2）、`sup` 编码层 1、单层尾随噪声 16。
- 写入后中文缓存标题内嵌 `<br/>` 残留为 0；395 个 XHTML 含 396 个语义多层标题，63 个样式表含对应 `display:block` 规则。
- 中文缓存 1276 个 XHTML 全部通过 XML 解析；`check_alignment.py --strict` 扫描 1015 个配对文件，问题为 0；工具测试与全仓库工具测试均通过。
- 迁移工具只修改 `.cache/epub-work`，没有直接批量编辑 `EPUB/`；校验后由 `publish.py` 同步到版本化档案。发布后的 `publish.py --dry-run --side chinese` 未发现待发布变更。

## 迁移与验收边界

1. 只在 `.cache/epub-work` 中编辑，以整本书为迁移原子，同时修改 XHTML 和该书 CSS。
2. 按标题层分别比较迁移前后的可见文本、顺序、标点和字号类，不允许直接删除语义换行后粘连文字。
3. 每本至少抽查一个二层标题和一个三层标题的阅读器显示；存在特殊 `ruby`/`sup` 时另行抽查。
4. 运行 XML 解析、标题内嵌 `<br/>` 审计、`check_alignment.py --strict` 和 `publish.py --dry-run`。
5. 发布后确认缓存与 `EPUB/` 一致。已经完成迁移的书不得重新出现标题内嵌 `<br/>`。
6. 缓存全量清零后，已把该规则加入 `check_alignment.py --strict` 的全局门禁；后续旧源回流必须先重新迁移，不得绕过检查。
