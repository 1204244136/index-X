# 图片核对工具补专用测试（2026-10-09）

## 范围

`tools/compare_epub_images.py` 此前**零专用测试**，却是剩余无测试工具里判定最复杂的一个（中日引用位置比对、双页对连续单页、字节／像素／感知三层分类）。本批补上 27 项测试，**未修改任何 EPUB 内容**，也未改动该工具的实现——只补测试与工具合同里的测试列。

## 覆盖

| 组 | 项数 | 覆盖 |
| --- | --- | --- |
| 页角色与图片族 | 2 | `page_role` 的包装页分类（cover／back_cover／allcover／bookwalker／contents／toc-*／illustrations／kuchie／body）；`image_name_family` 的作品号前缀剥离（S1/S4/S5 独立作品/S6 日期）与语义族映射（含 `kuchie-00N` → `illustration N-1`、`kuchie-001` → `deputy_cover`） |
| 正文编号与页型 | 3 | `body_number_key` 的三种命名（`p016-p017`／`i-016-017`／`p000-00-16-1` 的 `legacy:` 命名空间）；`body_number_parts` 只对双页区间给值；`_layout_from_ratio` 的阈值边界（≥1.10 双页／≤0.90 单页／其余模糊）；`_uses_s1_illustration_sequence` 的适用范围 |
| 命名规则配对 | 8 | `name_rule_match` 的分支：族不同不配、位置必须相交、cover 族按位置配对、正文编号相同且页型类别相同才配、双方均为规范编号时不再靠槽位兜底、历史 `p000-00-XX-1` 命名回落到同一槽位、插画编号必须一致、非 S1 序列的插画族需视觉证据支持 |
| 引用收集 | 5 | `collect_book` 的三种位置键（正文图 → `header:<表头>:<slot>`、包装图 → `family:<族>:<号>`）；`references` 与 `pages`／`locations` 的去重差异；收集阶段不解码、`feature()` 首次读取才写入尺寸与页型；损坏图片记 `decode_error` |
| 比对与报告 | 5 | `compare_book` 的分类：字节相同（同名／异名）、未配对两侧、中文双页 ↔ 日文两张连续单页（合成一条记录并保留两张日文图）、缺一张时不强行配对、命名规则先于感知比对；`scan` 端到端（中日两本书配对 → `exact_bytes_same_name`、报告与 Markdown 小节）+ 只有单侧时进 `unpaired_books` |

## 补测过程中被测试纠正的四处错误预期

写测试时我按印象写了断言，被实现纠正——这几处本身就是值得钉住的行为，已写进测试文档串：

1. `collect_book` **不解码图片**：`width`／`height`／`layout` 要等 `feature()` 首次读取才写入。报告里未配对资源带尺寸，靠的是 `compare_book` 开头的统一 `feature()`，不是收集阶段。
2. `references` 按**引用出现次数**记录（同一页引用两次就两条），而 `pages`／`locations` 去重；报告消费方需自行去重。
3. 包装页表头经 `pairing_header_of` 统一成**大写**（`S1_01-Illustrations.xhtml` → `S1_01-ILLUSTRATIONS`）。
4. 端到端的字节命中计数键是 `summary["matched_images"]`（另有 `name_rule_matches`／`exact_bytes_name_different` 等分项键）。

## 有意不测

`compare()` 的感知指标阈值与 `possible_same_content`／`possible_same_content_text_or_font_changed` 分级：需要真实的渲染／字体差异样本，合成图代表不了；这些分级在报告里本就标注「待视觉复核」，阈值属经验参数，写死会阻碍后续调整。本批只把**确定性的命名、位置与分类口径**钉住。

## 验证

- `python -m unittest discover -s tools/tests -p "test_*.py"` → **639 tests, OK (skipped=2)**（本批前 612，新增 27）。
- `python tools/check_project_docs.py` → 问题 0 条。
- 真实数据冒烟：`python tools/compare_epub_images.py --pattern "*S2_14*" --output <临时目录>` → exit 0，报告正常生成。
- 工具合同 C4 成员表 `compare_epub_images.py` 行的「测试」列由「无专用测试；只读诊断」改为 `test_compare_epub_images.py`。

## 补记：本批引入的 CI 中断与修复（2026-10-09 晚）

本批把 Pillow 依赖带进了测试采集阶段，中断了当晚的 Build EPUB Release 流水线，属**本批引入的回归**，同日修复。

**现象**：`release-epubs` 任务在「Validate tools and publication source」一步失败——`Ran 613 tests`、`FAILED (errors=1, skipped=19)`、`ImportError: Failed to import test module: test_compare_epub_images`、`ModuleNotFoundError: No module named 'PIL'`，job 以 exit 1 结束。同一 `run` 块里其后的 `check_project_docs.py` 与 `publish_preflight.py --source EPUB` 因 `set -euo pipefail` 未执行，EPUB 打包、合并 ZIP 与 release 全部未发生。

**根因**：`test_compare_epub_images.py` 在模块顶层硬导入 `PIL`，而 CI 只跑 `actions/setup-python`、不装任何第三方包。`unittest discover` 在**采集阶段**导入失败会让整个发现过程报错，不是只跳过这一个模块。此前 `tools/tests/` 的第三方依赖（`openpyxl`）已在 `test_read_xlsx.py` 按「可选依赖整组跳过」处理，本批未沿用该口径。本机装有 Pillow 11.3.0，全量测试 639 项通过，缺陷在本地不可见。

**修复**：`test_compare_epub_images.py` 改为与 `test_read_xlsx.py` 一致的口径——`try` 内导入 `PIL` 与 `compare_epub_images`（工具模块在缺 Pillow 时主动 `raise SystemExit`，故连 `SystemExit` 一起兜住），失败时八个测试类按 `@requires_pillow` 整组跳过。不改 workflow，保持「CI 只用官方 Python 环境、不装第三方包」的既有假设。

**验证**（本机）：

| 场景 | 结果 |
| --- | --- |
| 有 Pillow：`python -m unittest discover -s tools/tests -p "test_*.py"` | exit 0，`Ran 639 tests`，`OK (skipped=2)` |
| 无 Pillow（`PYTHONPATH` 注入屏蔽 `PIL` 的 `sitecustomize.py` 模拟 CI） | 修复前 exit 1、`Ran 613`、`FAILED (errors=1, skipped=2)`，与 CI 原始报错一致；修复后 exit 0、`Ran 639`、`OK (skipped=29)`，多出的 27 项即本模块 |
| 单模块直跑 `python tools/tests/test_compare_epub_images.py` | 有 Pillow `Ran 27 tests, OK`；无 Pillow `Ran 27 tests, OK (skipped=27)` |
| `python tools/publish_preflight.py --source EPUB` | exit 0，79 本，问题 0 条 |

`check_project_docs.py` 在本机当前工作区曾报 3 条，全部是同期 `AGENTS.md` 版式规范拆分新增的三份 `docs/epub-*-spec.md` 尚未登记进 `docs/README.md`，与本次修复无关；该拆分由 45d108ce 登记完成后已回到 0 条。

