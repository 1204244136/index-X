# 工具链路径、缓存与发布边界加固（2026-09-14）

- 范围：`tools/bw_preprocess.py`、`tools/split_s5_epubs.py`、`tools/manifest.py`、`tools/sync_core.py`、`tools/publish_epub.py`、`tools/check_alignment.py` 及静态清理；未修改 `EPUB/` 或归档内容
- 目标：修复审查确认的 ZIP 路径穿越、孤儿临时目录误识别、反向发布冲突漏检、单侧缓存崩溃，并清零 `ruff` 静态问题

## 修复结论

1. **ZIP 路径**
   - 新增共享模块 `tools/path_safety.py`。
   - `bw_preprocess.py` 与 `split_s5_epubs.py` 在写盘前拒绝空条目、绝对路径、`..`、反斜杠、冒号/盘符和越出输出根目录的目标。
   - 回归用例构造 `../escaped.txt`：工具在创建 EPUB/解包目录前返回阻塞，目标目录外无文件写入。

2. **`.extract-*` 临时目录**
   - 临时目录标记改为检查相对路径的每一层组件，覆盖 `.cache/epub-work/chinese-text/.extract-*`、书籍目录内的嵌套临时目录以及 `EPUB/` 中的同级残留。
   - `manifest.py`、`publish_epub.py` 扫描和 `sync_file_changes(..., full_mirror=True)` 均不再收录这些路径。

3. **反向发布冲突保护**
   - `find_conflicts` 不再只看本次 `EPUB/` 变化文件，而是比较缓存中该书的完整快照与基线同书子集。
   - 缓存侧未发布新增、修改、删除都会阻止流程 C；只有显式 `--overwrite-cache` 才跳过。

4. **单侧对齐检查**
   - `check_alignment.py` 在中文侧或日文侧目录缺失时按空集合处理，不再因 `iterdir()` 抛出 `FileNotFoundError`。

5. **静态检查**
   - 清理未使用导入/变量、歧义变量名、重复 `image_anchors` 定义、无效 f-string 及本地导入的 Ruff E402；未改变工具业务行为。

## 验证

- 定向回归覆盖：路径穿越阻断、所有相对路径层级的 `.extract-*` 过滤、全量镜像过滤、三类缓存冲突、单侧缓存不崩溃。
- `python -m unittest discover -s tools/tests -p "test_*.py" -v`
- `python -m ruff check tools`
- `python -m compileall -q tools`
- `python tools/check_alignment.py --strict`
- `python tools/publish_auto.py --dry-run`
- `git diff --check`

## 遗留与边界

- 路径校验只针对当前两个 ZIP 解包入口；若后续新增其他归档解包入口，应复用 `path_safety.py`，不得另写宽松匹配。
- 反向发布冲突仍以「书」为处理粒度：命中任一缓存差异即跳过整本书，符合保守覆盖策略。
- 本次只运行发布预检，没有执行 OneDrive 上传或归档发布。
