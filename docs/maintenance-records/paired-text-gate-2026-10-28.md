# 中日对照完整性门禁（2026-10-28）

- 范围：新增 `tools/check_paired_text.py` 与 `tools/tests/test_paired_text.py`；把整句截断检查接入 `publish_preflight.py`；`tools/README.md` 增加工具合同，`docs/translation-spec.md` §七 补 `P10` 的机器检查边界。
- 背景：读者反馈 `S5_01_02` 的「必要之恶教会」缺注音。回查发现该处不只是注音问题：`S5_01_02-06` L488 的整句台词被截成只剩术语 `『必要之恶教会』`，日文原文是完整长句「……まだ、『必要悪の教会』への道が残っているとでも？」。该行由 2026-10-05 的整卷复审重写 `6b34bc3f` 写入（提交前旧译是完整句「你难道还觉得『必要之恶教会』能够收留我们吗？」），此后四道既有门禁（text_norm／alignment／health／translation_spec）全绿。同卷「必要之恶教会」43 次仅 2 次注音，而日文源 42 次全部带 ruby、同系列 `S5_01_01` 48/48、`S5_01_03` 3/3 均为 100%。

## 缺口判定

- `check_translation_spec.py` 的 `P10` 只查 ruby 结构：缺 `<rt>`、空 `<rt>`、`<rt>` 含日文假名。它不比对日文侧，因此「原文注过音而中文漏注」不在命中范围，严重度也只有 info。
- `check_epub_health.py` 的 `ruby` 项同样只查「缺 `<rt>`／开闭不配对」，且该工具按设计不读日文侧（注音义务不在其职责内）。
- `check_semantic_alignment.py`／`diff_paired_lines.py` 的长度比只用于对齐打分（`len_penalty` 为软扣分），不产生「截断」命中；`S5_01_02` 的错位窗口数为 0，未拦住 L488。
- 结论：**整句截断没有门禁**；注音义务则属术语级语义判断，机器无法可靠自动化。

## 判定口径

- `truncation`（error）：中文行整行由一对引号包裹、引号内不含句末标点与拖长音（`。？！…、，,.—―‐~～㊟♪☆★` 与空白）、长度不超过 `TRUNCATION_MAX_INNER`（10），且日文对应行可见长度不小于 `TRUNCATION_MIN_JP`（20）。
  - 判据只覆盖对话行；叙述行的截断不在本条范围（库内叙述截断会同时触发语义对齐或人工复核）。
  - 回测：修复前全库命中 1 行（`S5_01_02-06` L488），修复后 0 行；单元测试覆盖正例与四类反例（完整台词、日文短句、拖长音、叙述行）。
- `ruby-coverage`（报告项，不产生命中）：按配对单元统计日文术语型 ruby 行数与中文 ruby 行数。术语型指读音为片假名或拉丁、且基文含汉字；平假名读音属普通读音，不参与统计。日文术语行达到 `RUBY_MIN_TERM_LINES`（10）且比值低于 `RUBY_COVERAGE_FLOOR`（0.15）时列入报告。
  - 不做命中判定的原因：规范三.1 要求普通词、生僻字读音与单纯外来语不注音，而日文源里的术语型 ruby 混有 `煙草／タバコ`、`天鵞絨／ビロード`、`模擬戦／ロールプレイ` 这类不该注音的词条。实测「基文汉字与中文行重合 ≥2」的候选全库 385 条，其中大半是普通词，无法作为门禁。
  - 回测：修复前 `S5_01_02-08`（`英国女王／クイーンレグナント` 10 行、`聖／セント` 2 行）与 `S5_01_02-06` 等单元比值低于下限；修复后该卷主体单元回到阈值以上。

## 接入点

- `publish_preflight.py`：带 `--jp-root` 的发布预检在术语锚点检查之后追加对照完整性检查，截断命中并入阻断问题列表；注音覆盖只打印、不进阻断。
- 覆盖口径与 `check_term_anchors.py` 一致：同一套 `books_by_id`／`header_index`／结构例外，未核对单元单列，不计通过。

## 验证

- `python -m unittest discover -s tools/tests -p "test_*.py"`：新增 12 个测试（`test_paired_text.py`），相关簇 `test_publish_preflight.py`、`test_check_term_anchors.py`、`test_paired_text.py` 共 49 项通过。
- `python tools/check_paired_text.py`：774 个配对单元已核对、21 未核对、豁免作品 2／单元 16；截断命中 0 行，注音覆盖异常 5 个单元。
- `python tools/publish_preflight.py --source EPUB --jp-root .cache/epub-work/japanese-text`：新增检查无截断命中；既有的 18 条「双语覆盖未完成」为 `require_reference` 路径的存量覆盖缺口，与本次改动无关。
- `python tools/check_translation_spec.py`、`check_epub_health.py --strict`、`check_alignment.py`：0 问题，未因新工具改动回归。
