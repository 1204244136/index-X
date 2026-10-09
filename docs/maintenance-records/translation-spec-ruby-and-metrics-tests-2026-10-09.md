# 规范检查注音口径合并与字数工具补测（2026-10-09）

## 范围

收掉上一批记录里列出的两条遗留：①`check_translation_spec.py` 的注音剥除口径（全仓最后一处与共享实现不同的「检查用剥离」）；②`epub_char_count.py`／`epub_composition_metrics.py` 两个零专用测试的只读工具。**未修改任何 EPUB 内容**，未执行发布与上传。

## 一、规范检查的注音剥除合并

**事实**：`strip_to_text` 用 `RT_FULL_RE = re.compile(r"<rt\b[^>]*>.*?</rt>", re.S)` 只剥 `<rt>`、保留 `<rp>`；而 `<rt>`/`<rp>` 的剥除规则在批 B 已单一起源到 `xhtml_text.strip_ruby_annotations`。两者对含 `<rp>` 的行会给出不同输入文本。

**影响面实测**（`.cache/epub-work/chinese-text` ＋ `EPUB/`）：**2584 个 XHTML、555,676 行**中，含 `<rp>` 的只有 **2 行**（同一文件两处，`S5_04_01-04_Chapter3.xhtml` 的 `<ruby>驱动铠<rp>（</rp><rt class="co">Powered Suit</rt><rp>）</rp></ruby>`）。

**处置**：`strip_to_text` 改为调用共享实现，删除 `RT_FULL_RE`。**改前改后 `check_translation_spec` 的 TSV／JSON／Markdown 三份报告逐字节一致**（P7 命中 3、P8 命中 20、P15 命中 1 不变，退出码相同）——即合并是零行为影响的单纯单一化。注释如实写明：当前规则集对该残留没有命中，合并的理由是「不留第二份实现」，不是「修了一个误判」。

## 二、两个字数工具补专用测试

此前 `epub_char_count.py` 与 `epub_composition_metrics.py` 都**零专用测试**（工具合同里写「无专用测试；只读诊断」）。批 B 收敛它们之间的规则重复时，验证只能靠一次性 A/B（15 本书输出对比），没有回归网。本批补上：

| 新增 | 覆盖 |
| --- | --- |
| `tools/tests/test_epub_char_count.py`（14 项） | 字数口径（去注音、去标签、解实体、去全部空白）；成分名规范化（章节截断、`あとがき`→后记、`行間`→行间、全角数字转半角）；位置规则（引子／尾声）；`<h2>` 子成分切分与「子成分字数之和 ＋ h1 字数 ＝ 成分总字数」守恒；页数 `max(1, ceil)` 与章级＝子成分之和；包装页／固定版式（`pre-paginated` 在 spine itemref 上）／nav 的过滤与 `include_wrapper`；`--min-chars`；`--label-map` 覆盖；解包目录按单本处理 |
| `tools/tests/test_epub_composition_metrics.py`（11 项） | 印刷页解析（`i-045`→45、`i-314-315`→314-315、倒序归一、`kuchie` 不出锚点、`cover` 无页码）；锚点保持文档顺序；`ref_str` 单页／区间／无锚点；`sub_offsets` 与 `<h2>` 对齐；端到端印刷页区间（实测锚点 10→50、区间单调、子成分严格递增不重叠、锚点覆盖率、包装页 `include_all`） |

**顺带记录一个现状口径（不判缺陷）**：`<head>` 里的文字（如 `<title>`）计入「全字符」，两个工具共用该口径。测试 `test_head_text_is_counted_today` 把它钉住并注明：若要改成只统计正文，须同时改实现、`tools/README.md` 的字数口径说明与本测试。

**不合并两个 CLI 入口**（沿用既有裁定）：两者 CLI 面与输出列互不包含（占比列 vs 印刷页区间），`tools/README.md` 的 C6 已写明取舍；现在有了测试兜底，「要不要合并成带开关的超集入口」今后可基于测试判断，而不是靠一次性比对。

## 验证

- `python -m unittest discover -s tools/tests -p "test_*.py"` → **612 tests, OK (skipped=2)**（本批前 587，新增 25）。
- `python tools/check_project_docs.py` → 问题 0 条。
- 工具合同同步：C6 成员表两行的「测试」列由「无专用测试；只读诊断」改为对应测试文件名（簇合同检查通过）。
