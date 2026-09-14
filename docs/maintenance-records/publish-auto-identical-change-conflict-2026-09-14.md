# 统一发布入口相同改动冲突判定修复（2026-09-14）

- 范围：`tools/publish_auto.py`、`tools/publish_epub.py`、对应回归测试与 `tools/README.md`
- 问题：缓存与 `EPUB/` 已包含同一项修改时，双方都相对旧清单显示为已修改，统一入口按书判定为冲突，要求人工指定 `--from`。

## 根因

`publish_auto.py` 只比较缓存和 `EPUB/` 各自相对 `manifest.json` 的变化，再按书取交集；没有比较两侧当前内容是否已经一致。
`publish_epub.py` 的冲突保护同样只检查缓存相对清单是否有变化，即使对应文件与 `EPUB/` 逐字节相同，也会阻止反向发布。

实际触发场景是两处修改都未经过发布流程推进清单：

1. 风力发电螺旋桨修正同时写入缓存和 `EPUB/`，两边内容相同，但清单仍是修改前状态。
2. 创约 1、2 的部分重校只修改了 `EPUB/`，与上一步的相同改动叠加在同一本书上。

## 修复

- `find_conflicts` 改为逐文件比较缓存、`EPUB/` 和清单：缓存改动与 `EPUB/` 当前内容相同的文件不再列为冲突。
- `publish_auto.py` 对两侧重叠的书籍先执行上述逐文件分类：
  - 缓存侧没有 `EPUB/` 未包含的内容时，走流程 C，正常推进缓存、OneDrive 和清单。
  - 缓存侧仍有独占内容时，才停止并要求 `--from cache` 或 `--from epub --overwrite-cache`。
- 显式 `--from cache` 仍以缓存为准；显式 `--from epub` 只有存在缓存独占内容时才要求 `--overwrite-cache`。

## 验证

- 新增两侧相同改动、相同改动叠加 `EPUB/` 独有文件、底层冲突函数相同内容豁免、真实工具链推进清单等回归用例。
- `python -m unittest discover -s tools/tests -p "test_*.py" -v`：129 passed。
- `python -m ruff check tools`、`python -m compileall -q tools`、`git diff --check` 与仓库 `publish_auto.py --dry-run` 均通过。

## 边界

- 同一文件的缓存与 `EPUB/` 内容不同仍属于真实冲突，必须显式选边。
- OneDrive 外部更新与本地同书修改并存的分叉保护不变。
