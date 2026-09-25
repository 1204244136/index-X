# calibre EPUB 合法性校验工具与全库基线（2026-09-26）

## 背景与口径

新增 `tools/check_epub_validity.py`，用 calibre 编辑器「Check book」的同一套内部检查器
（`calibre.ebooks.oeb.polish.check.main` / `container`）批量校验全库 EPUB。判定口径全部来自
calibre，工具只负责收集目标、控制并行、归类分级与输出，不自行实现第二套规范检查器。

与既有的 `tools/check_epub_health.py` 分工：后者只读 `EPUB/` 中文侧、只判「不需要中日对照
就能判定」的机械问题，可进 CI；本工具是第三方完整口径，能覆盖 ZIP/OPF 容器层、清单与 spine
一致性、链接与锚点、字体图片、ID、编码与 CSS 语法，但依赖本机 calibre，只在本地定期跑。

工具实现上相对其来源（本地 `Calibre-EPUB-Checker` 项目的单脚本）的调整：

- 支持**解包书籍目录**（`EPUB/` 下含 `mimetype` 与 `META-INF/container.xml` 的目录），
  不必先打包即可校验归档源；
- 报告**默认不落盘**（只在 `--report/--json/--tsv` 时写），避免污染仓库根目录；
- 新增**类别层**：calibre 把样式风格问题也标成 `ERROR` 级，`CSSError` 一项就能淹没真信号，
  因此按其类名归入 18 个类别，`--structural` 可排除四个样式风格类别；
- 入口解释器不必是 calibre 自带的 Python：校验统一在子进程里做，非 calibre 环境自动用
  `calibre-debug` 拉起，修掉了原脚本在 `tools/` 下运行时子进程无法导入自身模块的隐患；
- `run_checkers.cpu_count` 这类内部旋钮拿不到时降级为警告，不再中断整批。

## 全库基线结论

校验对象共 243 个，全部完成、0 个检查失败：

| 范围 | 目标数 | 结果 |
| --- | --- | --- |
| `EPUB/` 解包归档源（中文） | 78 | **0 问题** |
| `packed-epubs/chinese-text`（中文成品） | 78 | **0 问题** |
| `packed-epubs/japanese-text`（日文源成品） | 87 | 20416 项（结构性 119，样式风格 20297） |

中文侧 156 个目标在 calibre 全套检查下**零命中**：容器、OPF 与清单、XML 良构性、内部链接与
锚点、字体图片、ID、编码、CSS 语法均无问题，解包源与打包成品结论一致（打包未引入容器层问题）。

日文侧 87 本中 83 本有命中，全部为 BookWalker 原样快照的固有特征，不构成本仓库产出物的缺陷：

| 类别 | 类型 | 条数 | 说明 |
| --- | --- | --- | --- |
| `resource` | `UnreferencedResource` | 95 | 源内附带未被引用的样式与图片（如 `style-check.css`、`fixed-layout-jp.css`、`logo-dengeki.png`） |
| `resource` | `UnreferencedDoc` | 1 | 未被引用的文档 |
| `link` | `BadDestinationFragment` | 12 | 目录页链接指向目标文件中不存在的锚点 |
| `nav` | `MissingNav` | 10 | EPUB2 式结构缺 EPUB3 导航文档 |
| `opf` | `IncorrectIdref` | 1 | `idref` 指向未知 id |

被 `--structural` 排除的样式风格项共 20297 条，集中来自 KADOKAWA 系样式表：选择器书写顺序
15416、空规则块 4827、重复选择器 46、单文件体积过大 8。这些只影响 EPUB 内部观感，不影响
阅读器行为；剔除后日文侧只剩上述 119 条结构性条目。

## 验证

- `python -m unittest discover -s tools/tests -p "test_calibre_validity.py"` 通过（40 项，不依赖
  calibre）：覆盖目标收集（解包目录与 `--recursive` 的差别）、类别映射、级别与位置解析、
  过滤与 `--strict` 语义、报告写出、单本失败收敛与入口退出码。
- `python -m unittest discover -s tools/tests` 全量 284 项通过。
- `python tools/check_epub_validity.py EPUB` 与 `... .cache/epub-work/packed-epubs --recursive`
  均退出 0；全量报告写入 `.cache/epub-validity/`（不提交，可重跑重建）。
- 单本对照：`--structural` 后仅剩结构性条目、`--strict` 按预期返回 1；`--list-categories`
  与 `--help` 正常。
- 本次只新增工具、测试与文档，未修改 EPUB 正文、未执行发布或 push。归档源与打包成品的
  `0 问题` 是运行时结论，未对输入文件做任何写入。
