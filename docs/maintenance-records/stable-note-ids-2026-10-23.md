# 译注稳定 ID 与条目排序调整

文档入口见 [文档索引](../README.md)。

## 范围与行为

本次共修改 13 个文件（含本记录），涉及译注结构规则、翻译规范中的关联说明、工具合同、注释检查与重排工具、测试、CI 说明和新书导入 skill；涉及书籍 0 本，未改动任何 EPUB 成品，也未执行内容同步。

- 已有 `noteN` 保持不变；允许缺号、数字顺序与阅读次序不同。新增按当前最大 N 加 1 分配，删除不压缩其余 ID；新书首次生成仍可连续分配。
- Note 页的物理条目顺序继续遵守正文首次引用顺序。例如在 `note1` 与 `note2` 之间插入 `note7` 后，条目顺序为 `note1、note7、note2`，原有引用不变。
- `check_note_order.py` 取消 ID 数值排序检查，继续检查首引顺序与引用完整性，并显式报告重复定义。
- `reorder_notes.py` 只移动完整条目，不再改写 ID 或正文引用；重复定义、缺失定义及孤儿条目继续拒绝写入。报告保留恒等 `mapping`、值为 0 的 `ref_rewrites` 与仅列 Note 页的 `files_touched`。
- ID 格式与属性沿用 `check_epub_health.py` 的结构门禁；导入生成器的初始 ID 分配行为不变，存量无需迁移。

## 验证

- `python -m unittest discover -s tools/tests -p "test_*.py" -v`：907 项，成功，3 项跳过。新增与调整的回归覆盖乱序／缺号 ID、插删不重编号、正文保持原字节、重复定义拒写、备份、预览与失败回滚。
- `python tools/check_note_order.py --root EPUB`：75 本含译注作品，问题 0。
- `python tools/reorder_notes.py --root EPUB --dry-run --no-backup`：扫描 81 本，需重排 0 本。S0 阅读说明含既有非注释条目，按原合同显式跳过，未写入。
- `python tools/check_project_docs.py`：问题 0。
- 新书导入 skill 的 `quick_validate.py` 校验通过；Windows 下以 Python UTF-8 模式执行。
- `git diff --check`：通过。

本次只调整工具与规则；未重排或重新编号现有书籍，未执行内容同步或推送。
