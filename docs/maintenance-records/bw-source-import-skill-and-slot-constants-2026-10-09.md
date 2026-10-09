# 槽位常量单一化与日文源导入 skill（2026-10-09）

## 范围

按既定设计（Q14 读法二、Q11 交接点、Q6 判据）做两件事：①把固定行模板 L1–L6 的槽位定义收敛为唯一来源；②补上缺失的「日文 BW 源导入」skill 并联动文档。**未修改任何 EPUB 内容**，未执行发布与上传。

## 一、槽位定义单一化（`tools/xhtml_slots.py`）

**事实**：模板的行号与槽位名散落在多处——`fix_legacy_pagebreak_br.py` 的 `FIRST_BODY_LINE = 6`、`check_alignment.check_file` 与 `bw_preprocess.template_issues` 各自的 `len(lines) < 6` 与 `lines[3]/[4]/[5]`、`xhtml_template.rebuild` 的 `lines[:2]`。

**处置**：新增 C0 模块 `tools/xhtml_slots.py`，导出 `LINE_XML`／`LINE_DOCTYPE`／`LINE_HEAD`／`LINE_H1`／`LINE_H2`／`LINE_BODY_FIRST`／`SLOT_COUNT` 与 `slot_name()`，四个调用点改为引用它（`lines[:2]` → `lines[:LINE_HEAD - 1]`）。

**明确不做**：不合并三个入口的**判定策略**。配对契约（`check_file`：容忍 L4/L5 前导空白、允许 L5 列表包装、L6 要求同行闭 `</p>`）、分页／合并契约（`template_issues`：L3 是否必须含 `main` 容器、L6 只要求以 `<p` 开头）、模板重建（`rebuild`）三者的宽严要求本就不同，各自有独立测试；合并等于重写两个门禁。`xhtml_slots.py` 的模块文档写明这条边界。L1–L3 仍以 `lines[0..2]` 直接引用（相邻三行、与各自的报错文本同处一行，不影响一致性）。

## 二、日文源导入 skill

**事实**：日文 BW 源 → 工作源这一段在三个 SKILL 里 **0 次提及**（`volume-import` 从「已同步进 `.cache/epub-work/japanese-text`」起步），而 `tools/README.md` 的 C2 有完整命令合同。

**处置**：新增 `.agents/skills/bw-source-import/SKILL.md`，交接点定在**日文侧已进 `.cache/epub-work/japanese-text/<作品号>书目录` 且能跑单侧 `check_alignment.py`**（这个位置由 `volume-import` 的材料表「日文原文」一项定义，交接后它的材料门禁才核得到东西）。skill 内容只做三件事：先确认的三项（作品号与内容序、逐页映射、源的类型）／四步流程（拆分合订卷 → 分页预处理 → 分页合并 → 入库与交接）／交接检查与禁止事项；命令全部指向 `tools/README.md`，规范全部指向 `AGENTS.md`，不重写条文。

**文档联动**：`docs/README.md` 索引新增该 skill 行（插在 `volume-import` 之前，体现上游关系）；`AGENTS.md` 目录约定改为「日文源导入、新书成品生成、术语统一与校对复核」；`tools/README.md` 的 C2 定位段与「路由」行补该 skill 链接；`volume-import` 的材料缺失处置改为「源未加工先走日文源导入 skill，源已在 OneDrive 日文目录则按 C1 拉取」。

## 三、同批修正

- `volume-import/SKILL.md` 的第 5 步命令补 `--calibre-id`（`tools/README.md` 的示例一直有、skill 没有）。语义以工具为准：它把 `<dc:identifier>calibre:<号></dc:identifier>` 写进 OPF，缺省不写该行，取值由用户按其 calibre 库给出。

## 四、有意不做：不合并三份 skill 的门禁命令块

三份 skill 各有一段收口门禁命令（`text_norm` → `check_alignment --strict` → `check_epub_health --strict` → 各自的范围门禁）。它们是**带各自范围参数的任务实例**（`--book S4_04`／`--pattern`／`--worktree`），不是同一规则的重复实现；换成指针会迫使执行者回查参数，反而降低可用性。按既定判据（同一规则多处实现才算冗余；命令数量不构成理由），这里只统一**指向**（规范指向 AGENTS、命令指向工具合同），不合并命令块。

## 五、验证

- `python -m unittest discover -s tools/tests -p "test_*.py"` → **587 tests, OK (skipped=2)**。
- `python tools/check_project_docs.py` → 问题 0 条（新增 `.py` 已登记进 C0 成员表与「负责与不负责」表，`## 簇索引` 的 C0 入口数由 14 改为 15；新 skill 的回指与链接通过）。
- **槽位常量行为保持 A/B**（旧版取自 `git show HEAD:`）：10 组破坏性夹具（缺 XML／缺 DOCTYPE／缺头部行／L4 非 h1／L5 非 h2／L6 非 p／L6 空／不足 6 行／列表包装页／合规页）× `check_file` 两模式与 `template_issues` 两模式，**旧新判定差异 0 处**；`xhtml_template.rebuild` 对 120 个真实文件重建输出**差异 0 个**；`check_alignment --strict` 对缓存全量 1108 个正文文件旧新同为 0 问题、退出码一致。
- 新增 skill 的结构自查：frontmatter 含 `name`／`description`／触发词，开头回指文档索引，命令均可从工具合同复核。
