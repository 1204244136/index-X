# FIVE_Over 翻译统一记录（2026-09-26）

- 范围：`EPUB/` 中文归档（元数据 OPF／nav／NCX 经检索未出现该词，无需同步）
- 涉及书籍：S2_01、S2_02、S2_04、S2_07、S2_11、S2_12、S2_15、S3_02、S3_04（9 个作品）
- 修改文件：22 个中文 XHTML
- 行内替换：117 处

## 判定口径

| 日文写法 | 中文规范 |
| --- | --- |
| `ファイブオーバー` / `FIVE_Over`（原文拉丁写法本身混用） | **`FIVE_Over`** |

**依据**：译名表 `Data_Translation.tabx.xlsx`（锚点第一顺位，SKILL §3.1）共 4 条相关条目，全部规定 `FIVE_Over`（全大写）：

| 行 | Base_Ori | Base_Trans |
| --- | --- | --- |
| 2199 | `【FIVE_Over.】【Modelcase_“RAILGUN”】` | `FIVE_Over. Modelcase_“RAILGUN”` |
| 2215 | `ファイブオーバー` | `FIVE_Over` |
| 2446 | `ファイブオーバー モデルケース・メンタルアウト` | `FIVE_Over. Modelcase_“MENTAL_OUT”` |
| 2447 | `ファイブオーバー【OS】` | `FIVE_Over. 【OS】`（ruby: Out Sider） |

第 2215 条尤其关键：日文原文为片假名 `ファイブオーバー` 时，译名表仍规定译作 `FIVE_Over`，说明大小写是**译名表硬性规定**，不随原文拉丁写法变化。

**冲突率实测**：`Five_Over` / `FIVE_Over` 是单一专名（学园都市制「再现超能力者能力的机械」系列），全库无同名异义项，替换无冲突风险。

## 修订明细

明细见 `.cache/_unify_five.tsv`（一次性产物，不进仓库）。按作品分布：

| 作品 | 处数 |
| --- | ---: |
| S2_01 | 45 |
| S2_11 | 25 |
| S3_02 | 14 |
| S2_04 | 8 |
| S3_04 | 12 |
| S2_07 | 4 |
| S2_02 | 1 |
| S2_12 | 1 |
| S2_15 | 2 |

单行出现 2 次的 5 行（`S2_01-10_Chapter5.xhtml` L523/606、`S2_11-09_Chapter4.xhtml` L417、`S3_04-09_Chapter4.xhtml` L7/154）已用带上下文的唯一定位串逐条替换，保证「原串在该行恰好出现一次」。

## 保留项

- 无。全库 `Five_Over` 已清零，仅剩译名表规定的 `FIVE_Over`（124 处）。
- 日文源侧拉丁写法仍混用（`FIVE_Over` 3 处 / `Five_Over` 5 处，如 `S3_04-03` L353/354/363、`S3_04-09` L149）。日文侧属原样快照，不属本次中文归档统一范围。

## 统计与验证

- 修订前：`Five_Over` 117 处 / `FIVE_Over` 7 处
- 修订后：`Five_Over` **0 处** / `FIVE_Over` 124 处
- 全部为行内替换，不增删物理行：`git diff --numstat` 各文件 `+/-` 行数全部相等
- `python tools/check_alignment.py --strict`：1105 个正文文件，0 个问题
- `python tools/check_epub_health.py --strict`：仅剩 1 条 `bold-punct`（S3_04-05 L268，由同工作区另一任务的复审改动引入，本次未纳入）
- 回退：`git revert <commit>`

## 工作区状态说明

提交时工作区另有 S3_04 的「重新校对」复审改动（9 个文件、303 处），与本任务在 `S3_04-03_Chapter1.xhtml`、`S3_04-05_Chapter2.xhtml`、`S3_04-07_Chapter3.xhtml`、`S3_04-09_Chapter4.xhtml`、`S3_04-10_Epilogue.xhtml` 5 个文件上重叠。两批改动互不干扰（本任务只改 `Five_Over` 字面），本次提交**仅暂存本任务的 22 个文件中属于本任务的改动行**；复审改动留待后续单独提交。
