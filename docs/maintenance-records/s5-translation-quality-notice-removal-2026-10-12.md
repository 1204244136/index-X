# 移除 5 本 S5 作品的「翻译质量提醒」（2026-10-12）

- **触发**：用户指示——移除全部正文中「翻译质量提醒」相关的标签和内容。
- **范围**：5 本作品（中日同一作品算一本）：`[S5_01_01]`、`[S5_01_02]`、`[S5_01_03]`、`[S5_02_01]`、`[S5_02_02]`。
- **性质**：口径订正（移除已过期的翻译质量声明），不构成裁定，不登记[译名裁定总表](../translation-name-rulings.md)。

## 一、改动

每本的 `OEBPS/Text/<作品号>-Information.xhtml` 删除原 L10–L12 的三行块（含 `<div class="box1">` 容器）：

```
<div class="box1"><p class="font12 center">翻译质量提醒</p>
<p class="center">本书翻译质量未能达到预期</p>
<p class="center">请不要反馈关于本书的内容，耐心等待重制</p></div>
```

删除后「制作信息」页由四行固定模板直接进入署名区；L4–L6 槽位、署名区与尾部声明均未改动，未增删其它行。

## 二、统计

- 文件：**5 个**（每本 1 个 Information 页），各删 3 行，合计 **−15 行**，无新增。
- 全库残留 `class="box1"` 使用：**0**（该块是 `.box1` 在全库的唯一使用者）。

## 三、验证

| 门禁 | 结果 |
| --- | --- |
| `text_norm.py --pattern "*S5_*"` | 0 命中（0 行、0 字符、0 文件） |
| `check_epub_health.py --pattern "*S5_*" --strict`（9 本、111 个 XHTML、13 项） | 0 问题（error 0 / warning 0） |
| `check_alignment.py --strict`（5 本、54 个正文文件） | 0 问题 |
| `check_epub_validity.py --structural --strict`（5 本，calibre 9.14） | 0 问题 |

## 四、发布

`publish_auto.py` 走**流程 C**（`EPUB/` → OneDrive ＋ 缓存镜像），5 本「全部方向执行成功」；复验 dry-run 无待发布。

## 五、未纳入本次（待办）

- **样式表统一（backlog）**：本批一度删除这 5 本 `style.css` 里的 `.box1` 规则（删除后该规则在全库已无使用者），经用户裁定**回滚**、改为待办排队。实测口径：改动前 81 本中 **80 本 `style.css` 逐字节相同**，唯一形态差异本是 `[S6_24.06.07]`（`.nodeco:hover`／`span.frame1` 用 Tab 缩进，`p:has(> img), p.fit, p.center`／`.pb, p:has(> img) + p:has(> img)`／`svg` 三条规则位于文件尾部，功能等价）。两条统一路线：以标准形态为基准（保留 `.box1`，只需拉平 1 本）或以「不含 `.box1`」为基准（需改 76 本、重发约 600 MB）。
- `.box1` 规则本身仍在 81 本 `style.css` 中保留（当前无使用者）。

## 六、回退

`git revert` 本次提交即可（涉及 5 个文件）。
