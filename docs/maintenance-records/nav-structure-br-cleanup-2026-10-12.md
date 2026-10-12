# `nav.xhtml` 头部杂散 `<br/>` 清理 ＋ `nav-structure` 门禁（2026-10-12）

- **触发**：用户建议「尽量贴合 EPUB3 规范」；对全库 `nav.xhtml` 头部普查后确认违规面。
- **范围**：**79 本**内容改动（`nav.xhtml` 删 1 行）＋ **新增一项构成门禁**。
- **性质**：规范执行与历史生成痕迹清理，不构成裁定。

## 一、诊断

| 形态 | 本数 | 位置 |
| --- | --- | --- |
| A | **29** | `<br/>` 是 `<html>` 的直接子元素（在 `<head>` 之前） |
| B | **50** | `<br/>` 是 `<head>` 的子元素（在 `<title>` 之前） |
| 干净 | 2 | `<head><title>Navigation</title></head>` |

两者都违反 HTML5 的 XHTML 语法：`<html>` 只允许 `head` 与 `body`，`<head>` 只允许元数据类元素。**未被更早发现的原因**是文件仍属良构 XML——XML 解析器（含 `check_epub_health` 的 XML 项）照收，calibre 校验器也不报；只有按 HTML5 解析规则处理的实现才会受影响：在 `head` 内遇到 `<br>` 会**提前关闭 head 并开启 body**，其后的 `<title>` 可能落进 body、`document.title` 变空；形态 A 里那个显式 `<head>` 标签甚至会被忽略。

**顺带发现（未处理、未立规则）**：形态 B 那 50 本没有 `<?xml …?>` 声明。EPUB3 允许省略，故不视为缺陷，也不建议为此单独动 81 本。

## 二、改动

- 79 个 `nav.xhtml` 各删 1 行（`+0 / −79`），其余行未动。
- 清理后全库一致：**81 本的 `<html>` 顶层子元素均为 `head>body`，`<head>` 内仅 `title`**（脚本与独立复核两次确认）。
- 一次性修订用临时脚本（默认预览、`--apply` 才写、逐本预检「`</head>` 之前恰好 1 处、只删 1 行」，任一不符整批拒写），按 AGENTS「工具与记录的边界」**改完即删**。

## 三、新增门禁 `nav-structure`（error）

判：`nav.xhtml` 可解析为 XML；`<html>` 的直接子元素只有 `head`、`body`；`<head>` 内只允许元数据类元素（`title`／`meta`／`link`／`style`／`base`／`script`／`noscript`／`template`）且 `<title>` 非空。逐本判定，自动经 `publish_preflight` 接入发布阻断。

测试补两类反例（`<head>` 内插 `<br/>`、`</head>` 后插 `<br/>`）并断言恢复后零命中；既有夹具的 `nav.xhtml` 原来**没有 `<head>`**，本次补上（这正是新门禁立刻抓到的问题）。`docs/epub-artifact-spec.md` 第四节新增该条文，第五节级别口径更新为**八项全部阻断**；`tools/README.md` 同步。

## 四、验证

| 门禁 | 结果 |
| --- | --- |
| `check_epub_health.py --root EPUB --strict` | 退出 0，**问题 0 条（error 0 / warning 0）**——21 项检查全库归零 |
| `check_epub_validity.py EPUB --structural --strict`（calibre 9.14） | 81 本、0 问题 |
| `python -m unittest discover -s tools/tests -p "test_*.py"` | 652 tests OK（2 skipped） |
| `check_project_docs.py` | 0 问题 |

## 五、发布

`publish_auto.py` 走**流程 C**，79 本「全部方向执行成功」；复验 dry-run 无待发布。

## 六、回退

`git revert` 本次提交恢复 79 行；门禁回退需另改 `SEVERITY` 与判据（有测试兜底）。
