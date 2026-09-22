# 移动端多列分页漂移排查与全库排版样式表规范化（2026-09-22）

## 背景与用户反馈

用户反馈：在 Android 移动端阅读器 Reasily 阅读《某科学的超电磁炮 SS》（`[S6_22.06.10]`）第四章时，整体文字从第 1 节开始位置逐渐向右偏离居中，到第 11 节明显偏移，到第 19 节整列文字被推到最右侧（左侧被裁切、右侧露出下一列字）。同时伴随插图被纵向切成两半（第 3 章）、插图右侧超出屏幕（尾声）、纯彩页（`Illustrations.xhtml`）翻页时左侧露上一张图边条等故障。

用户怀疑是插图原因。项目经过深入的排版引擎与视口坐标模拟实测，证实该反馈击中了一项全库共性的底层布局缺陷。

## 根因剖析

Reasily 等基于 Android WebView 的阅读器在横向分页模式下采用 Chromium 的 **CSS3 多列布局（Multi-column Layout）**，按固定整数步长 `scrollLeft = 页码 × 视口宽度` 翻页。

引发连锁崩溃的三个核心成因：

1. **段落缩进污染插图导致列宽溢出（造成切片与右溢出的元凶）**：
   - 源代码中正文插图写为 `<p><img class="fit" src="..."/></p>`；
   - 全局样式设定了首行缩进 `p { text-indent: 2em; }`；
   - 原 `.fit` 为行内块（`display: inline-block; max-width: 100%`），被强制向右推进 2em（约 32px），整张插图占据总宽度达到 **`100% + 32px`**，直接横向冲出当前列；
   - 溢出的 32px 被 Chromium 多列引擎切断分配至下一列（表现为插图被横切两半或右侧裁切），并撑大整章的 `scrollWidth`，永久破坏列坐标系。
2. **`body` 左右百分比边距导致多列容器超出 102%**：
   - 全库原有样式表均写有 `body { margin-left: 1%; margin-right: 1%; }` 且为默认盒模型（`box-sizing: content-box`）；
   - 容器总宽度达到 `102%`，使每一页翻页距离与实际列宽产生约 1%（~4px）的基础位移。
3. **缺少分页控制类 `.pb`**：
   - 全库样式表中遗漏了关键的 `.pb` 强分页类声明，使插图与文字挤在同一屏无法分页。
4. **超长章节线性累积放大误差**：
   - 短章节（20~30 页）位移只有几十像素不易察觉；第四章长达 1519 行、排版超 100 页，误差持续叠加至大半屏，在后半部分爆发。

## 规范化方案与全库治理

遵循项目规约中「不拆分大章节、中日行数绝对对齐、全库整体统一处理」的要求，实施以下三层治理：

### 1. 全库 78 本书样式表（`OEBPS/Styles/style.css`）标准化升级

全库 78 本书的 `style.css` 统一替换升级（升级后全库 MD5 绝对一致：`83f70ca136b9e6955359b438d86a0107`）：

- **引入标准盒模型**：`*, *::before, *::after { box-sizing: border-box; }`；
- **边距归零**：`html, body` 边距清零（`margin-left: 0%; margin-right: 0%; padding: 0%;`），避免容器宽度超出 100vw，页面留白交由阅读器自适应管理；
- **重构 `.fit` 图片类**：
  ```css
  p:has(> img), p.fit, p.center {
    text-indent: 0;
    text-align: center;
  }
  .fit {
    display: block;
    margin-left: auto;
    margin-right: auto;
    text-indent: 0;
    break-inside: avoid;
    -webkit-column-break-inside: avoid;
    page-break-inside: avoid;
    max-height: 100%;
    max-width: 100%;
    box-sizing: border-box;
  }
  ```
- **补充三层声明的分页类 `.pb` 并加入连续图片保护**：
  ```css
  .pb,
  p:has(> img) + p:has(> img) {
    page-break-before: always;
    -webkit-column-break-before: always;
    break-before: column;
  }
  ```
  连续插图（如 64 本书的 `Illustrations.xhtml` 彩页）自动实现每图独占一列，彻底解决彩页翻页露边问题。
- **篇首 `<svg>` 独立分列**：
  ```css
  svg {
    display: block;
    margin: 0 auto;
    break-after: column;
    -webkit-column-break-after: always;
    page-break-after: always;
  }
  ```

### 2. 构建工具与体检门禁同步更新

- **`tools/docx2epub.py`**：
  - 更新内置 `_CSS` 模板至最新规范；
  - 规范化插图生成逻辑，正文插图与封面均生成 `<p class="center"><img class="fit" .../></p>`，彩页自动附带 `pb` 属性。
- **`tools/check_epub_health.py`**：
  - 新增 `css-layout` 单侧体检项（级别 `error`，受 `--strict` 门禁约束）；
  - 自动检查全库书籍的盒模型、`body` 边距、`.pb` 类及 `.fit` 列防断规则，防止旧样式回流；
  - 补充 `tools/tests/test_check_epub_health.py` 负向自检单元测试（3 项缺陷反例全覆盖，22 个单测全绿）。
- **`AGENTS.md` & `tools/README.md`**：
  - 在 `AGENTS.md` 中新增「移动端多列分页与插图排版规范」专节，写死排版防御要求；
  - 更新 `tools/README.md` 中的体检表格与工具行为说明。

### 3. 《某科学的超电磁炮 SS》（`[S6_22.06.10]`）针对性修复

- 在保持 1519 行中日行数严格一致的前提下，将所有正文插图行、尾声插图行及彩页段落规范化为带有 `class="center"` / `class="center pb"` 的独立段落。

## 验证结论

1. **视口多列渲染模拟验证（Chromium 390×844）**：
   - 第四章整整 101 列中，第 1 节（Col 1）、第 11 节（Col 46）、第 19 节（Col 85）以及全章所有插图的列对齐偏差均为 **`0.00px`**，彻底消除漂移；
   - 第三章插图完美居中对齐当前列（`diff = 0.00px`），不再被劈成两半；
   - 8 张彩页各自独立居中占满一列（8 列，`diff = 0.00px`），翻页不再露出上一页边条。
2. **全库门禁通过情况**：
   - `python tools/check_alignment.py --strict`：1105 个配对文件全部通过，**异常：0**；
   - `python tools/check_epub_health.py --strict`：78 本书全部通过，12 项单侧检查（含新增的 `css-layout`）**问题：0**；
   - `python tools/check_translation_spec.py`：翻译规范检查通过。
