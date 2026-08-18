# 中文 Note 注释规范治理（2026-08-18）

## 结论

对 `.cache/epub-work/chinese-text/` 全部 71 本带 `*-Note.xhtml`（译注页）的中文书籍完成注释规范治理，最终状态：**0 本问题**——所有 Note 文件均为整数编号、从 `note1` 开始、连续无空号，且条目顺序与正文 `epub:type="noteref"` 首次出现顺序完全一致；无孤儿注释、无悬空引用。

原状：14 本存在顺序/编号问题，其中 4 本含小数编号（`note2.1`、`note6.1`、`note8.1`、`note10.1`）、1 本从 `note0` 起始、多本存在缺号，3 本含已定义但正文未引用的孤儿注释。

## 范围与统计

- 检查：`tools/check_note_order.py`（只读）逐本提取 Note 定义顺序与正文首次引用顺序，报告写入 `.cache/epub-work/note-order-check.md` / `.json`。
- 编号规范化（整数、从 1 开始、顺延）：11 本，共改写 Note 文件 id 与正文引用若干处。
  - S1_01（note0→note1 起始修正）、S1_23、S2_04、S2_21、S2_23、S3_02、S3_04、S3_05、S4_03、S5_01_01、S5_02_02。
- 孤儿注释处理：3 本。
  - S3_08：`note13` 补在尾章「飞车与角行」后（顺序天然一致）。
  - S4_01：`note7` 补在第一章「你这打扮是在发什么纸巾啊」后，并按出现顺序重排重编号。
  - S5_04_01：参考《某魔法的禁书目录 外典书库 4》还原 11 条孤儿注释位置（膛线/泵动式/乙醇/甲醇/诺斯特拉达穆斯/含氧酸/弁庆/毕达哥拉斯/昆哈特/千日手/定式），随后整本重排为 note1~note26。
- 全量顺序重排：11 本，按正文出现顺序重排 Note 文件并重编号、单遍更新正文引用。
  - S1_01、S1_02、S2_04、S2_07、S2_22、S3_02、S3_04、S3_05、S3_09、S4_02、S4_03。

## 工具

- `tools/check_note_order.py`（只读）：检查 Note 顺序/编号/孤儿/悬空；支持 `--pattern`、`--cache`、`--output`。
- `tools/reorder_notes.py`（写缓存，自动备份）：按正文出现顺序重排 Note 文件并重编号，同步更新引用；支持 `--dry-run`、`--pattern`、`--cache`、`--backup`。
- 说明已写入 `tools/README.md`。

## 必要样例

- S2_07：`note4` 原排在列表最后，但第一章先出现 → 重排后成为 `note1`，其余顺延。
- S3_04：`note47` 原在末尾，实际在第 21 条位置出现 → 提前为 `note23`，后续 24 条顺延。
- S4_03：原 `note6.1`（已规范为整数）实际在 `note9` 之后出现 → 重排为 `note10`。

## 遗留项

- `S0_00-Note.xhtml` 含一个不带 `id` 的非注释 `<li>`（说明条目）。`check_note_order.py` 不受影响（S0_00 检查通过）；`reorder_notes.py` 为防丢条目会跳过此类文件，需人工处理时先明确该 `<li>` 归属。

## 备注

- 所有改动仅作用于缓存工作区 `.cache/epub-work/`，未发布到 `EPUB/` 或 OneDrive。
- 备份（未提交，可回滚）：`.cache/renumber-backup/`（52 文件）、`.cache/restore-s5_04_01-backup/`（7 文件）、`.cache/reorder-backup/`（51 文件）。
- 后续发布前建议先运行 `python tools/check_note_order.py` 确认 0 问题。
