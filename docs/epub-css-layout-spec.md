# EPUB 排版规范（移动端多列分页与插图）

文档职责与入口见 [文档索引](README.md)。

本文件是**移动端阅读器版式**的规范正文：全库书籍主样式表必须写入的分页与插图防御规则，以及对应的自动化门禁。结构、行模板与换页标记见 [EPUB 结构规范](epub-structure-spec.md)；译文语言规范见 [翻译规范](translation-spec.md)。

## 一、全局盒模型与边距归零

全库书籍主样式表（`style.css`）必须包含 `*, *::before, *::after { box-sizing: border-box; }`；`html, body` 左右边距必须归零（`margin-left: 0%; margin-right: 0%; padding: 0%;`），严禁在 `body` 上硬编码非零百分比左右边距（避免在 Reasily 等移动端 WebView 多列分页模式下因容器超出 100vw 产生逐页线性累加漂移）。外层页面留白由阅读器自适应管理。

## 二、插图块级居中与缩进清除

插图类 `.fit` 必须使用块级居中与列断点保护：`display: block; margin-left: auto; margin-right: auto; text-indent: 0; break-inside: avoid; -webkit-column-break-inside: avoid; page-break-inside: avoid; max-height: 100%; max-width: 100%; box-sizing: border-box;`。同时必须包含 `p:has(> img), p.fit, p.center { text-indent: 0; text-align: center; }`，彻底阻断全局 `p { text-indent: 2em; }` 污染图片导致横向溢出 2em（约 32px）撑破列宽、图片跨列劈裂切片等故障。

## 三、分页类 `.pb` 强声明与连续插图隔离

全库样式表必须显式声明 `.pb`（`page-break-before: always; -webkit-column-break-before: always; break-before: column;`），并配套声明 `p:has(> img) + p:has(> img)` 规则，保证彩页集中页（`Illustrations.xhtml`）等连续多图场景下每图自动独占一整页/整列，杜绝翻页露边；正文中的跨整页插图、章尾插图应配合 `class="center pb"` 使用。

## 四、篇首 `<svg>` 独立分列

使用篇首矢量插图的文件，样式表必须包含 `svg { display: block; margin: 0 auto; break-after: column; -webkit-column-break-after: always; page-break-after: always; }`，保证篇首图片独占首屏，后续标题与正文干净地在新一列开始。

## 五、门禁检查

`check_epub_health.py` 包含 `css-layout` 检查项，对全库样式表的盒模型、`body` 边距、`.pb` 和 `.fit` 保护规则实施自动化门禁阻断，防止旧版样式回流。命令与失败边界见 [工具合同](../tools/README.md)。
