# 工具与文档维护流程

文档职责与入口见 [文档索引](../README.md)。修改工具、测试、CI 脚本或规范说明前读取本文件；通用写入与版本控制边界见 [AGENTS.md](../../AGENTS.md)，命令行为合同见 [工具说明](../../tools/README.md)。

维护工具的行为变更应同步更新 `tools/README.md`；但该文件只写工具的定位、入口、参数、数据流、判定口径与可验证行为，**不写历次修订记录与验收结论**（每轮改动规模、通过哪些门禁、遗留项处置等）——这类内容记入 `docs/maintenance-records/`（长期保留的检查结论）。`docs/changelog.md` 已冻结并归档为 `docs/archive/legacy-changelog.md`，两者均禁止继续编辑。工具改动按工具自身测试、检查和文档门禁验证，不执行 EPUB 文本修改的写入前后通用同步。如果新增缓存目录、报告目录或构建产物，必须同时更新 `.gitignore` 和 `AGENTS.md`。新增或调整版式规范时，正文写进对应的 `docs/epub-*-spec.md`，`AGENTS.md` 只更新指针与核心不变量，不复制条文。

### 脚本说明软门禁

修改 `tools/` 脚本、测试或 `.github/` 内嵌脚本后，人工复核本次 diff 中的注释、docstring 与帮助文本：

- 代码内说明当前行为、约束与必要的设计原因；命令与行为合同写入 `tools/README.md`，带日期的功能修订、阶段记录与验收统计写入 `docs/maintenance-records/`，代码按需保留文档指针。清理既有历史说明时，先确认已有记录承载或迁入记录，再将仍有效的约束改写为当前行为。
- 日期按用途判断：业务日期、时间格式、S6 作品号、测试样例、协议版本、版权声明与文档引用可以保留；“某日新增／修复／清零／升级为阻断”等叙述归入历史记录。
- 完成标准：本次新增或修改的说明均已归位，并与实现一致；保留的日期用途明确。此项为人工软门禁，不增加日期正则、测试或 CI 阻断。

### 工具与记录的边界

`tools/` 只放**会反复使用**的流程工具：拉取、解包、规范化、对齐检查、审计、打包发布，以及新书导入管线（`pull.ps1`、`normalize_paired.py`／`normalize_single.py`、`check_alignment.py`／`check_translation_spec.py`／`check_note_order.py`、`bw_preprocess.py`、`merge_bw_pages.py`、`publish_auto.py`／`publish.py`／`publish_epub.py` 等）。判断标准只有一条：**这个动作会不会在后续新拉取或新导入的书籍上再次发生？**

一次性的内容修订**不新增复用工具，也不保留其临时脚本与映射数据**，改完即删，只把结论落盘：

- 单一术语统一（锚点级收敛，例见[译名裁定总表](../translation-name-rulings.md)）、单点错字或译名订正、单卷结构调整、历史遗留的一次性迁移，均属此类。
- 执行口径（显式映射、逐条预检、预检不过则不写盘、只改行内文字不增删行）见 `.agents/skills/translation-term-unification/SKILL.md`；本条只规定：这类修订不新增复用工具，也不把工具与映射数据留在仓库里。
- 留档、裁定登记与提交按 [内容维护流程](content-maintenance.md) 和 [版本控制边界](../../AGENTS.md#版本控制边界) 执行。
- 不保留的形式包括 `tools/fix_<具体词变体>.py`、`tools/check_<具体术语>.py`、`tools/<术语>_overrides.json` 之类的单点术语工具与映射表，以及写在 `.cache/` 下的 `scan_*`／一次性分析脚本。
- 已执行完毕的一次性判定如需复核或回退，用提交历史（`git show`／`git revert`），而不是重跑工具。
