# 工具规则收敛（同一规则多处实现）（2026-10-09）

## 范围

按 `tool-responsibility-cleanup-2026-09-19.md` 的判据（**只有「同一规则多处实现、共享能力寄居在不相关入口」才算冗余；命令数量与文件长度不构成理由**）收敛五处重复实现、补一处负例、修三处失效路径与一个 CI 盲区。**未修改任何 EPUB 内容**，未执行发布与上传，工具清单与文件名不变。

## 逐项处置

| 项 | 事实 | 处置 |
| --- | --- | --- |
| 注音剥除（`<rt>`/`<rp>`） | 同一规则在 4 处各写一套：`japanese_lookup.py`、`.agents/skills/proofread-review/references/lookup_source.py`、`check_translation_table.py`，加 `translation-term-unification/SKILL.md` 的手写示例；另有「只剥 `<rt>` 取可见文本」在 `diff_paired_lines.py` 与 `check_semantic_alignment.py` 各写一份（两处逐字相同） | 规则唯一实现移入 `xhtml_text.py`：`RUBY_ELEMENT`／`strip_ruby_annotations`（剥 rt+rp）与 `RT_ELEMENT`／`visible_text_of`（剥 rt 取可见文本），并补 `text_of_without_ruby` 作为原文检索口径；六个调用点全部改为引用，skill 示例同步改写 |
| 字数成分规则 | `epub_composition_metrics.normalize_labels` 逐行复制了 `epub_char_count.apply_label_rules` 的位置规则（序章→引子、后记→尾声）；`epub_composition_metrics.split_sections` 重写了同名切分并自带 `FW_DIGITS` 副本、少一步 `html.unescape`；`analyze()` 已于 `:123` 解析一次，`:135` 又切分取文本一次 | `normalize_labels` 改为调用 `apply_label_rules`；子成分直接复用 `analyze()` 返回的 `sub_components`，删除 `epub_composition_metrics.split_sections` 与重复解析 |
| dHash 与汉明距离 | `compare_epub_images._dhash` 与 `image_signature.dhash_image` 是同一算法两份实现，而 `image_signature.py` 自述「已被 compare_epub_images 共用」与实际不符；`_hamming` 亦与 `image_signature.hamming` 重复 | `compare_epub_images` 改 import `dhash_image`／`hamming`，删除本地两份实现；自述由此成立 |
| 引用后缀常量 | `shift_content_sequences.REFERENCE_SUFFIXES` 与 `fix_empty_placeholders.REFERENCE_SUFFIXES` **同名不同值**（前者含 css/xml/svg/htm，后者只含 opf/ncx/xhtml/html） | 两者移入 `epub_structure.py`，分别命名为 `REFERENCE_SUFFIXES`（书内引用改写面）与 `METADATA_SUFFIXES`（会被删条目面的文件类型），取值与原实现**逐项相同** |
| `is_empty()` 无负例 | 空页资格只有一条正向用例，缺 `<img>`/`<svg>`、`<head>` 剥离与前后邻居条件的反例，与工具合同「体检与门禁必须有能触发失败的最小反例」不符 | 新增 4 项负例：图形内容不算空、`<head>` 内容不算正文、缺一侧邻居不成候选、编号断档不成候选 |
| 技能侧失效路径 | `unify_terms_template.py:4,8` 与 `test_unify_terms_template.py:3` 写 `.dsh/skills/…`（该路径在仓库中不存在，正确为 `.agents/skills/…`） | 三处改为仓库实际路径，写法与 `SKILL.md:87/98` 对齐 |
| CI 盲区 | `test_unify_terms_template.py` 是自定义 `check()` 的纯函数脚本，不是 `unittest.TestCase`，`unittest discover` 采集数为 0，而 CI 只跑 `tools/tests` | `check-epub-health.yml` 在「工具测试」后新增「技能模板回归测试」步骤直跑该脚本（触发条件已含 `.agents/**`，无需改） |

## 验证

- `python -m unittest discover -s tools/tests -p "test_*.py"` → **587 tests, OK (skipped=2)**（本批前 583；新增 `test_xhtml_text.py` 8 项与空页负例 4 项）。
- `python tools/check_project_docs.py` → 问题 0 条。
- `python .agents/skills/translation-term-unification/references/test_unify_terms_template.py` → 13/13（已纳入 CI 步骤）。
- **行为保持的证据**（逐项对照改前实现，旧版取自 `git show HEAD:`）：
  - 注音剥除：对 `.cache` 真实日文 XHTML **200 个文件**逐文件比较新旧正则结果，差异 0；可见文本口径对 `.cache` **81,884 行**比较，差异 0。
  - 字数成分：`epub_char_count`／`epub_composition_metrics` 对 **15 本书**输出 JSON 逐字节比较（含 254 KB 成分页数报告），差异 0。
  - dHash／汉明：对 `.cache` **300 张真实图片**比较新旧哈希，差异 0；`compare_epub_images` 对 `*S4_0*`（实测触发 119 次哈希与 42 次距离比较）输出 `report.json`（101 KB）与 `report.md` 逐字节一致。
  - 引用后缀：新旧集合逐项相等断言通过（曾发现首版 `METADATA_SUFFIXES` 误含 `.htm`，已改回原取值）。
  - 真实入口冒烟：`japanese_lookup.py`（markup/raw）、skill 自带 `lookup_source.py jp …`、`check_translation_table.py --book S1_01`（exit 0，产出 82 KB JSON）均正常。

## 有意保留的差异（不是遗漏）

- `epub_char_count.strip_ruby` 仍保留自己的口径：它额外剥 `<rb>` 与自闭合 `<rt>`，并去全部空白，属**字数统计口径**；2026-09-19 记录已判「字数统计使用的去注音、去空白口径不同，不强行合并」。
- `check_translation_spec.py` 的 `RT_FULL_RE` 只剥 `<rt>`、保留 `<rp>` 括号，服务于 P1–P16 的正文文本检查。合并到 `visible_text_of` 会同时移除 `<rp>`（可能改变 P 规则命中），属会改门禁输出的改动，需单独做改前改后 A/B，留待后续批次。
- `epub_structure.IMAGE_SUFFIXES`（打包校验用的宽集合）与 `image_signature.IMAGE_SUFFIXES`（Pillow 可解码集合）同名不同值：用途不同，已在 `image_signature.py` 就地注释固化差异，避免被当作笔误替换。
