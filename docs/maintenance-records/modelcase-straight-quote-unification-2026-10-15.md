# Modelcase 引号格式全库收敛为直引号（2026-10-15）

## 范围

- **涉及书籍**：2 本
  - `【S3_04】创约 某魔法的禁书目录 04`（2 个文件，4 处）
  - `【S6_24.06.07】某魔法的禁书目录外传 王牌御坂美琴对女王食蜂操祈！！`（1 个文件，1 处）
- **修改类型**：行内符号替换，不增删物理行。

## 依据与口径

1. **作者原文格式**：
   - 全系列中 `Modelcase` 标识型号名（如 `Modelcase_"RAILGUN".` 或 `Modelcase"ACCELERATOR"`）时，作者刻意使用半角 ASCII 直双引号 `""`（`"`），属于技术代码类格式标记，不按普通中文引号体例转换为弯引号 `“”` 或直角引号 `「」`。
   - `docs/translation-name-rulings.md` 第 130 行已明确裁定：`FIVE_Over.Modelcase_"…"` 使用半角直引号。
2. **全库既有实现**：
   - `S2_01`、`S2_04`、`S2_11`、`S2_15`、`S3_02` 全库共 15 处均已稳定使用半角直引号 `"`。
   - `S3_04` 日文源虽以外字图片（gaiji `alt="二重引用符"`）承载，中文统一按 `""` 直引号落地，与全库体例对齐。
   - 本次清理全库仅存的使用弯引号 `“”` 的 5 处残留。

## 改动清单

| 作品 | 文件 | 行号 | 原写法 | 收敛后写法 | 备注 |
| --- | --- | --- | --- | --- | --- |
| S3_04 | `S3_04-03_Chapter1.xhtml` | 353 | `Modelcase“RAIL_GUN”` | `Modelcase"RAIL_GUN"` | 标签货签台词 |
| S3_04 | `S3_04-03_Chapter1.xhtml` | 354 | `Modelcase“MELT_DOWNER”` | `Modelcase"MELT_DOWNER"` | 标签货签台词 |
| S3_04 | `S3_04-03_Chapter1.xhtml` | 364 | `Modelcase“ACCELERATOR”` | `Modelcase"ACCELERATOR"` | 集装箱货签正文 |
| S3_04 | `S3_04-09_Chapter4.xhtml` | 150 | `Modelcase“Accelerator”.` | `Modelcase"Accelerator".` | 武器铭牌正文 |
| S6_24.06.07 | `S6_24.06.07-03_Chapter2.xhtml` | 196 | `Modelcase_“RAILGUN”.` | `Modelcase_"RAILGUN".` | 驱动铠正文 |

## 验证

- `python tools/text_norm.py --dry-run`：0 命中。
- `python tools/check_alignment.py --root EPUB --jp-root .cache/epub-work/japanese-text --strict`：1129 文件 0 问题。
- `python tools/check_epub_health.py --root EPUB --strict`：全项通过（0 问题）。
- `python tools/publish_auto.py`：发布至 OneDrive 并更新缓存、拉取状态基线。
