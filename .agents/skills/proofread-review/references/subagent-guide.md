# 校对复核子智能体执行速查卡

文档职责与入口见 [文档索引](../../../../docs/README.md)。本文件是切片子智能体的独立执行速查卡；完整流程与主报告契约见 [SKILL.md](../SKILL.md) 与 [复核契约](review-contract.md)。

## 一、核心判据（只回原文）

- **判定依据唯一**：判定唯一依据是冻结取证包中的**日文原文**，不是中文顺畅度、习惯搭配或主观好恶。
- **重点核查维度**：
  - **数字与单位**：数量、倍数、量级、物理单位、时间跨度。
  - **逻辑与否定**：肯定/否定反转、双重否定、反问与设问、因果关系。
  - **主体与时序**：行为施受者错配、动作先后顺序、时态与体貌（已完成/进行中/未发生）。
  - **词义方向**：正反褒贬方向、词义理解偏差。
  - **专名与术语**：专有名词、口癖与敬称分层。
- **明显删减（`del_large`）**：
  - 若旧译明显长于本行日文，必须结合 `N-1/N/N+1` 邻接行核查，确认是否属跨行并段、拆段或真实漏译。
- **原文刻意留白与悬念**：
  - 作者刻意省略的行为主体或宾语严禁擅自补全，保持留白。
- **术语与专名规范核验**：
  - 查验 [译名裁定总表](../../../../docs/translation-name-rulings.md) 与 [译名选取规范](../../../../docs/translation-name-selection-spec.md)（§一 已定名单、§四 防日语中转直译）。

## 二、标准三步执行流（严禁手写脚本或盲搜）

### 1. 分页读取取证包
内置 UTF-8 输出、自动折叠无注音重复行并展示 `local/tiny` 最小差异：

```powershell
python tools/proofread_session.py read --report-root <report-root> --slice <slice-id> --page 1 --page-size 30
```

- 120 条切片仅需调用 4 次（`--page 1..4`）。
- **严禁**手写 `python -c` 裸调 `print`（在 Windows PowerShell 下易触发 GBK 乱码）或盲猜 `EPUB/` 目录结构。
- 如 `N±1` 窗口不足以判断，记录具体 `item_id` 与所需行号范围交还 Lead 用 `context` 补包，不得自行通读整章。

### 2. 填写逐条决策草稿（支持紧凑 TSV 或预生成 JSON 骨架）
- **方式 A（推荐，最省 Token）**：直接用 `write_file` 写 `<report-root>/slices/decisions/<slice-id>.a<attempt>.tsv`（Tab 分隔，不写多余 JSON 括号与重复键名）：

  ```tsv
  item_id	decision	reason	proposed_cn	original_fix
  C000001	保留新译	原文「率直に」对应「坦率地」，句意吻合
  C000002	确认误改	原文「見上げていた」指仰望天空而非看上条	她正仰望着天空。
  C000003	保留新译	原文「五〇キロなんて話じゃない」表远不止五十千克		否定与逻辑方向|旧译「不也有五十千克吗」误译为反问|新译「可不止五十千克」还原否定比较|纠正负重事实
  ```

- **方式 B（JSON 骨架）**：运行命令生成草稿骨架后填入：

  ```powershell
  python tools/proofread_session.py scaffold --report-root <report-root> --slice <slice-id> --attempt <1|2> --apply
  ```

  在生成的 `<report-root>/slices/decisions/<slice-id>.a<attempt>.json` 中填入每条的 `decision / reason / proposed_cn / original_fix`。

### 3. 装配与独立校验

```powershell
python tools/proofread_session.py assemble --report-root <report-root> --slice <slice-id> --decisions <草稿路径.tsv或.json> --attempt <1|2> --apply
python tools/proofread_session.py validate --report-root <report-root> --result <report-root>/slices/<slice-id>.a<attempt>.json --json
```

## 三、字段与校验硬规则（一次通过不返工）

- **`decision` 仅限四值**：`保留新译`、`确认误改`、`待人工`、`未覆盖`，四者互斥且穷尽。
- **`reason` 严禁通用套话**：
  - 禁止“新译准确传达了原文含义”“润色自然”等空泛表述；每条必须点出具体日文词句与中文译词的对应。
  - 对于无争议的 `保留新译`，采用 **15–35 字极简锚点句**（如 `原文「…」对应「…」，语意一致`），避免长篇大论消耗输出 Token。
  - `待人工` 必须说明仍缺事实或依赖（如上下文不足）；`未覆盖` 必须说明未读或故障原因。
- **`proposed_cn` 填报规则**：
  - 仅 `确认误改` 填入最小中文替换行文本。
  - 其余三种判定必须留空（TSV）或填 `null`（JSON）。
- **`original_fix` 填写条件**：
  - 仅在**初始批次（无 `parent_id`）**、**`decision=保留新译`**、且**旧译有重大事实/逻辑/主体/漏译错误已被原校对新译纠正**时填写（常规润色不填）。
  - **`category` 仅限五选一**：
    - `否定与逻辑方向`：肯定否定倒错、反问误译为陈述、因果颠倒。
    - `数字与单位`：数量级错误、单位换算错误、倍数关系搞反。
    - `主体与动作时序`：施受事者颠倒、动作先后次序颠倒、完成态与未发生错乱。
    - `关键漏译与专名`：整句核心实词漏译、专有名词与固定术语译错。
    - `其他重大语义问题`：严重脱离原文主旨或事实陈述的硬伤。
  - **机械校验铁律**：`old_error` 必须用中文引号 `「…」` 直接括起冻结 `old` 中的原字面短句（≥2字），`new_fix` 必须用 `「…」` 直接括起冻结 `new` 中的原字面短句（≥2字），否则 `assemble / validate` 会报 `evidence` 错误！
  - **TSV 表达**：`original_fix` 列填 `category|old_error|new_fix|impact`（四段用半角 `|` 分隔）或 JSON 对象字符串。
- **日文引用默认省略**：
  - 默认省略 `jp_location` 与 `jp_quote`，由 `assemble` 自动从本条冻结证据附入；仅当引用邻接行或补包行时才成对显式提供。
- **范围外发现（`discoveries`）**：
  - 仅记录偶然注意到的切片外严重排版或错漏，字段固定为 `location / issue / needed_context`，不影响本片覆盖与判定。
- **自检四项核对**：
  1. 条目数与 ID 是否恰好等于切片分配？无重复、无遗漏、无越界。
  2. 是否存在空泛理由？`保留新译` 理由均含有日文与中文对应短句。
  3. `确认误改` 是否均给出了非空最小中文替换 `proposed_cn`？
  4. `original_fix` 引用的 `old_error` 与 `new_fix` 是否被 `「…」` 包裹且字面吻合？
- **任务结束回复**：
  - 子智能体回复仅需说明 `slice_id`、`attempt`、正式结果文件路径及阻断依赖（如有），无需将逐条结论或大段分析贴回聊天窗口。
