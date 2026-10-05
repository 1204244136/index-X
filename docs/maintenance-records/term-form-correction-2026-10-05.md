# 术语写法按译名表订正（2026-10-05）

- 范围：`EPUB/` 中文归档与 `.cache/epub-work/` 中日配对文本
- 涉及书籍：S2_11、S3_02、S3_04、S5_01_02（4 本）
- 修改文件：8 个中文 XHTML
- 行内替换：25 处

## 本次修改的判定依据

> 留档只忠实反映本次修改内容；翻译方案以 [译名裁定总表](../translation-name-rulings.md) 的裁定为准。

本次处置的是全库译名表落地核对（`python tools/check_translation_table.py --table <译名表>`）报出的待判项。维护者 2026-10-05 决定：**按译名表直接改成品**。

| 日文锚点 | 译名表写法 | 本次改动 | 处数 |
| --- | --- | --- | ---: |
| `神道` | 神道教 | 神道 → 神道教 | 1 |
| `ファイブオーバー【OS】` | `FIVE_Over. 【OS】`（`【】` 是振假名标记，实际写法 `FIVE_Over. OS`） | FIVE_Over OS → FIVE_Over. OS | 24 |

同批的 `トートタロット` 待判项另行裁定为**按语境分轨**（牌组语境→托特塔罗牌；魔道书语境→托特塔罗），两侧均未改动，登记见裁定总表 §十。

## 修订明细

| 文件 | 行 | 修订 |
| --- | ---: | --- |
| `S5_01_02-07_Chapter6.xhtml` | 167 | 神道 → 神道教 |
| `S2_11-07_Chapter3.xhtml` | 290、338、367、373 | FIVE_Over OS → FIVE_Over. OS |
| `S2_11-09_Chapter4.xhtml` | 11、15、225、228、248、276、286、292、306、308、405、417、420、422、427 | 同上（15 处） |
| `S3_02-05_Chapter2.xhtml` | 78 | FIVE_Over → FIVE_Over.（`<ruby>OS<rt>OutSider</rt></ruby>` 前补句点） |
| `S3_02-07_Chapter3.xhtml` | 145 | 同上 |
| `S3_04-03_Chapter1.xhtml` | 363 | FIVE_Over OS → FIVE_Over. OS |
| `S3_04-05_Chapter2.xhtml` | 925 | 同上 |
| `S3_04-09_Chapter4.xhtml` | 149 | 同上 |

## 统计与验证

- 全部为行内替换，不增删物理行：8 个文件 25 行变更，`git diff --stat` 增删各 25。
- `python tools/text_norm.py --dry-run`：0 行命中。
- `python tools/check_alignment.py --strict`：已验证正文文件 1105，问题 0。
- `python tools/check_epub_health.py --strict`：78 本书、1197 个 XHTML，error 0／warning 0。
- `python tools/publish_auto.py`：4 本已打包上传 OneDrive 并回流缓存。
- 回退：`git revert <commit>`
