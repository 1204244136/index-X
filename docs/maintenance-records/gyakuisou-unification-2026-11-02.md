# 「逆位相」译名收敛为「逆相位」记录（2026-11-02）

- 范围：`EPUB/` 中文归档与 `.cache/epub-work/` 中日配对文本
- 涉及书籍：S2_06、S2_12（2 本）
- 修改文件：2 个中文 XHTML
- 行内替换：2 处（2 行；行数中性）

## 本次修改的判定依据

> 留档只忠实反映本次修改内容；**翻译方案以 [译名裁定总表](../translation-name-rulings.md) 的裁定为准**，本节只记本次为何这样改，不重复登记方案。

| 日文写法 | 本次改动 |
| --- | --- |
| `逆位相` | 反相位 → 逆相位 |

依据：维护者裁定（登记见[译名裁定总表](../translation-name-rulings.md) §五 `逆位相` 行）。日文 `逆位相` 全库 5 处，中文侧改前「逆相位」3 处、「反相位」2 处，属同一锚点的取形分裂；`位相` 在物理学即中文「相位」，取「相位」不取日语借形「位相」。

## 修订明细

| 作品号 | 文件 | 行 | 修订 |
| --- | --- | ---: | --- |
| S2_06 | `S2_06-05_Chapter6.xhtml` | 773 | 利用反相位声波 → 利用逆相位声波 |
| S2_12 | `S2_12-02_Chapter1.xhtml` | 240 | 发出反相位音波 → 发出逆相位音波 |

对应日文：`S2_06-05` `逆位相の音波でそれ以上の声を封じてみた`；`S2_12-02` `逆位相の音波を発する特殊な防音壁`。

## 保留项

- 其余 3 处（`S1_04-02:212`、`S1_21-06:494`、`S3_01-05:181`）改前即为「逆相位」，未动。

## 统计与验证

- 修订前 / 修订后：`反相位` 2 → **0**；`逆相位` 3 → **5**。`EPUB/` 与 `.cache/epub-work/chinese-text/` 两侧一致。
- 全部为行内替换：2 文件、2 行；`git diff --stat` 为 2 insertions／2 deletions。
- `python tools/text_norm.py --pattern "*S2_06*"`（`*S2_12*` 同）`--dry-run`：均 0 行命中。
- `python tools/check_alignment.py --strict`：已验证正文文件 1129，问题 0。
- `python tools/check_epub_health.py --strict`：81 本书、1249 个 XHTML，问题 0 条。
- `python tools/check_term_anchors.py --strict`：6 个锚点、774 个文件，命中 0 行（部分覆盖，属既有状态）。
- `python tools/check_echo.py --book S2_06`（`S2_12` 同）：两卷候选报告中无「相位」组；`S2_12-06` 另有 L795／797／799 行类型错位，属既有状态，与本次改动无关。
- `python tools/check_project_docs.py`：0 条。
- `python tools/check_translation_table.py --table <项目译名表> --audit-rulings`：问题 0 条。
- `python tools/publish_auto.py --only-books "<2 本>"`：见下方同步记录。
- 回退：`git revert <本次提交>`。
