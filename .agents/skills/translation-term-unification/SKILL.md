---
name: translation-term-unification
description: index-X（某系列 EPUB 档案）译名／术语统一工作流。用于收敛同一日文锚点的多种中文异译、统一角色口癖与专有写法、裁定敬称与术语分层：以日文写法为锚逐点定位、显式映射逐条预检、只改 EPUB/ 行内文字、跑门禁并留档。触发词：译名统一、术语统一、译法不一致、异译、口癖统一、译名订正、敬称统一、术语审计、term unification、translation consistency。
---

# 译名／术语统一工作流（index-X）

文档职责与入口见 [文档索引](../../../docs/README.md)。

本 skill 是**读改译文用词**这一类任务的操作正文。仓库级规约仍以 `AGENTS.md` 为准；译文该写成什么样以 `docs/translation-spec.md`（尤其「五、译名与专有写法」）为准；本文件只写「怎么做」。

## 一、先分清任务类型

| 任务 | 归属 |
| --- | --- |
| 同一日文锚点的多种中文异译收敛、角色口癖、专名／敬称、术语分层（阵营／侧 这类） | **本 skill** |
| 标点、字形、加粗移出标点等字符级规范化 | `tools/text_norm.py`（有固定规则表，不要手改） |
| 结构、行模板、中日对齐、图片行 | `AGENTS.md`「Agent 操作边界」＋ `tools/check_alignment.py` |
| 错字／病句／整卷重新校对 | 逐条回原文判断，走 `tools/proofread_review.py` 复核口径，不是本 skill |

判据：**改动是否需要一个「日文锚点」才能判定**。需要锚点就是本 skill 的活。

## 二、六条铁律

1. **以日文写法为锚**，逐点替换。禁止 `科学.?势力 → 科学阵营` 式无锚点全局替换——实测有 6% 命中会误伤真实的「势力」义项（`docs/maintenance-records/science-magic-side-translation-consistency-2026-09-12.md` §6.3）。
2. **显式映射 + 逐条预检**：每条映射写死「书籍、文件、行号、原串、新串」；预检要求文件唯一、行号有效、**原串在该行恰好出现一次**。任一不满足 → **整批不写盘**，报出来交人工。
3. **只改行内文字，不增删物理行**，不动标签、属性、注音、资源引用、标题结构；标题语言保护规则见 `docs/translation-spec.md` 五.6；改完中日行数必须不变。
4. **写入落点只有 `EPUB/`**（内容写入的唯一权威落点）。`.cache/` 一律只读，仅用于分析与中日对照。改完由 `publish_auto.py` 回流 OneDrive 与缓存。
5. **任务脚本与映射数据不留仓库**：一次性修订属 `AGENTS.md`「工具与记录的边界」，不新增 `tools/fix_*.py`、`tools/*_overrides.json`。定位／替换脚本放在临时目录，跑完删除；复核与回退用 `git show` / `git revert`。
6. **留档与裁定登记分工**：`docs/maintenance-records/` **只忠实反映本次修改内容**（范围、文件数、统计、验证、样例），不承载翻译方案。「什么算裁定」的判据见 `docs/translation-name-rulings.md` §一，本文件不复述。**新增裁定条目必须经维护者确认；agent 只能提出候选与依据，不得自行写入裁定表**。改动落在两本及以上书籍（中日两侧同一作品算一本）→ 写留档；只落在一本内且裁定已登记 → 不留档。

## 三、判定口径

### 3.1 锚点与分层

- 锚点是日文写法；先读裁定与现译名表。语料频次和覆盖率用于发现冲突及估算改动面，不能据此决定候选优劣；取舍按 `translation-name-selection-spec.md`，查独立权威资料。
- 分层锚点按裁定表分别定位；同一行有两个锚点时分别判定，不能因同处一行就套同一个目标译法。
- 译名表是**锚点的第一顺位来源**（见 §3.3）；表里没有才走「日文原文 + 语料统计」裁定，并把结论与理由登记进 `docs/translation-name-rulings.md`。
- 日文锚点写法、查询折叠和逐字引证的规则正文见 `docs/translation-spec.md` 六.5。核注音／码位时读取原始 BW 分页源；缓存是工作产物。

### 3.2 检索时的三个必守口径

- **剥离标签先剥 `<rt>`**：`<ruby>魔術<rt>まじゆつ</rt></ruby>サイド` 若只去标签会变成 `魔ま術じゆつサイド` 而**漏检**（`xhtml_text.text_of` 就是只去标签的那种，用它之前必须先剥注音）。这个口径 bug 曾导致「科学阵营」改完而「魔法阵营」漏改 31 处。
- 证据强度与风格化行的准入按 `docs/translation-spec.md` 五.4／五.5；先标记跳过范围再产出映射，不把短词或刻意风格自动当异译。


### 3.3 锚点数据源

按 `docs/translation-spec.md`「外部依赖与核验」动态定位译名表、说话习惯、BetweenLines 版本与 BW 原始源，并在工作报告记录版本／哈希。读表字段通常为 `Base_Ori`、`Ruby_Ori`、`Base_Trans`、`Ruby_Trans`、`Type`，以当前表头为准。

口癖类任务先查说话习惯与已裁定条目。线上魔禁维基的 [译名表](https://toaru.huijiwiki.com/wiki/Project:%E8%AF%91%E5%90%8D%E8%A1%A8) 可帮助定位词条，但它与项目表共享来源，不能作为候选取舍的独立证据。Wiki 文件由站点维护，本仓库不保留副本或部署状态；外部表／档案无法读取时明确未核验范围。

### 3.4 注音相关任务

涉及注音增减时按 `docs/translation-spec.md` 三.1 回 BW 原始分页源核特殊读音；单纯换基文不动 `<rt>`。

## 四、执行流程

### S0 读既有裁定，避免重开已决口径

先查 `docs/translation-name-rulings.md`（已裁定总表，§六 为其入口）；同类维护记录只用于追溯修改事实，不用来重开取舍。**已裁定过的锚点不得再换目标译法**；同一锚点二次统一要说明前次结论哪里不适用。

### S1 写前同步

```powershell
python tools/publish_auto.py            # 预览可加 --dry-run
```

确认三副本（`EPUB/`、`.cache/`、OneDrive）在最新状态。**有冲突先按 `AGENTS.md` 合并，不得选边覆盖。**

### S2 锚点检索（只读）

- 分析源优先 `.cache/epub-work/japanese-text/`（日文完整）与 `chinese-text/`；写作目标是 `EPUB/`。
- 检索一律用 `rg` 或直读，**不用 CodeGraph**：正文是字面文本，不构成符号。
- 中日配对：同作品号目录；文件按**表头 + 内容序**对齐（内容序只表达对齐顺序，章节语义以文件内容与导航为准）。作品号／表头解析用 `tools/epub_ids.py`（`book_id`／`work_id`／`header_of`／`content_sequence`），不要自己写正则。
- 逐点产出三列：日文锚点位置 → 中文同行现状 → 判定（应改 / 保留 / 待人工）。**中文未收录的作品不纳入**，在统计中单列。

### S3 裁定目标译法

先沿用已决裁定和当前译名表；缺项时按译名选取规范查证独立来源，再比较候选与原文的所指、义项冲突及作品语域。全库频次只用来发现不一致、测定修改规模，不能替代取舍依据。多个候选都成立时登记裁定；明显错误或规范执行直接订正，留档只记录修改事实。

### S4 生成显式映射并预检

按 §五 的命令生成业务映射（书籍、文件、行号、原串、新串）。执行器用本 skill 附带的模板：

```powershell
Copy-Item .agents/skills/translation-term-unification/references/unify_terms_template.py (Join-Path $env:TEMP "unify_terms_task.py")
# 填 MAPPINGS 后：
python (Join-Path $env:TEMP "unify_terms_task.py")                  # 预检：只打印，不写盘
python (Join-Path $env:TEMP "unify_terms_task.py") --apply           # 预检全过才写 EPUB/
python (Join-Path $env:TEMP "unify_terms_task.py") --apply --tsv (Join-Path $env:TEMP "unify_terms_task.tsv")   # 顺带产出可粘进留档的明细表
Remove-Item -LiteralPath (Join-Path $env:TEMP "unify_terms_task.py")             # 用完删除，不提交
```

模板自带回归测试（改动模板后跑一次；无第三方依赖、不触碰 `EPUB/`）：

```powershell
python .agents/skills/translation-term-unification/references/test_unify_terms_template.py
```

预检不通过时**不要**放宽条件（改成模糊匹配、加 `--force`）：把该条移到「保留项／待人工」，其余照常。

### S5 写入与自检

执行器已内置写前自检：行数不变、XML 可解析、同一行的多条映射逐条重校验（互不干扰）。写盘后自查：

- `git diff --stat` 的 `+/-` 行数**必须相等**（纯行内替换的特征）；
- 抽查 `git diff` 若干条，确认方向没有译反（历史先例：`S2_18-05:481` 曾把「科学サイド」译成「魔法阵营」）；
- 同一台词／口癖的重复句改后应逐字相同。

### S6 门禁

```powershell
python tools/text_norm.py --dry-run             # 字符级规范化：必须 0 命中，有命中先 --apply 再复跑
python tools/check_alignment.py --strict        # 中日行数 / 模板 / h2 / 图片行
python tools/check_epub_health.py --strict      # 单侧结构（XML、ruby、加粗、悬空引用等）
python tools/check_translation_spec.py          # 涉及标点／注音／单位时跑；报告在 .cache/epub-work/
```

记录本次选定范围的实际文件数、未配对范围与问题数；数量变化先核对输入范围和收录状态，不能套用历史全库数字。

### S7 写后同步、留档、提交

```powershell
python tools/publish_auto.py            # 打包上传 OneDrive + 回流缓存 + 更新清单
```

- 跨作品 → 新建 `docs/maintenance-records/<锚点 slug>-<YYYY-MM-DD>.md`（模板见 §七），只写本次修改内容。
- 无论跨本与否，**只要在多个都成立的候选间作出了新选择，先向维护者提出候选与依据，经确认后再登记进 `docs/translation-name-rulings.md`**；未经确认不得自行写入裁定。明显错误直接订正，不算裁定、不登记（判据见该表 §一）。
- 单作品 → 不留档。
- 提交与登记的同批关系按 `AGENTS.md`「版本控制边界」执行。
- 提交：中文 + Conventional Commits（如 `fix(S4_03): 统一白鸟炽媚口癖「当方」译为「本人」`）。**只暂存本任务涉及的文件**，不纳入用户其它未提交改动；不 push。
- 若工作区有其他任务的未提交改动，与该改动同处一批文件时：按口径改完但只提交本任务部分，并在留档里写明工作区状态与未纳入原因（范例：`benizome-zerifish-catchphrase-translation-consistency-2026-09-16.md` §「工作区状态说明」）。

## 五、常用命令

```powershell
# 日文锚点：全库计数与逐点位置（-n 带行号；.cache 为分析源）
rg -n --no-heading "サイド" .cache/epub-work/japanese-text --glob "*.xhtml" | Measure-Object -Line

# 中文现状：某译法分布
rg -n --no-heading "科学势力|科学侧|科学方" EPUB --glob "*.xhtml"

# 剥标签后比对（务必先剥 <rt>）
# `xhtml_text.text_of` 只剥标签、**不剥注音**，直接用它检索会把「魔術サイド」拆成「魔術 まじゆつ サイド」
# 现成实现（先剥 <rt> 再 text_of，已封装路径与内容序）：见 proofread-review skill 的 references/lookup_source.py
# 逐行取纯文本时的最小写法（复用既有口径，不另写一套剥离逻辑）：
#   stripped = re.sub(r"<(rt|rp)\b[^>]*>.*?</\1>", "", raw, flags=re.S)
#   lines = [xhtml_text.text_of(ln.encode("utf-8")) for ln in stripped.split("\n")]

# 只读审计
python tools/check_translation_spec.py --pattern "*S3_10*"

# 复核某次改动的语义影响（提交级）
python tools/proofread_review.py <commit>       # 产物 .cache/epub-work/proofread-review/
```

元数据不在正文行配对范围内，但术语修改涉及同文简介时同步判定 `content.opf` 与 `*-Introduction.xhtml`；标题与 nav/NCX 的语言保护规则见 `docs/translation-spec.md` 五.6。没有日文参考的作品单列未核验范围。

## 六、已裁定结论索引

**已生效的译名裁定集中在 `docs/translation-name-rulings.md`（译名裁定总表）**：只收「多个都成立的候选之间必须选一个」的决定，逐条给出「日文锚点 → 裁定 → 被否决或并存的候选 → 备注」，并列出裁定为「不作统一／按语义分轨」的锚点，以及**不算裁定的纠错与规范执行**清单（该表 §十一）。

做新任务前先查该表；命中就沿用，不要在无关任务里顺手改动。标「不作统一／按语义分轨」的锚点，复核时不得再当异译翻出；「被否决或并存的候选」列列出的写法不得沿用。

本节只留入口，**不重复维护结论表**：新裁定落盘后同步更新 `docs/translation-name-rulings.md`，避免两处漂移。

## 七、留档模板

```markdown
# <锚点>翻译统一记录（YYYY-MM-DD）

- 范围：`EPUB/` 中文归档与 `.cache/epub-work/` 中日配对文本
- 涉及书籍：S3_03、S3_05
- 修改文件：N 个中文 XHTML
- 行内替换：M 处

## 本次修改的判定依据

> 留档只忠实反映本次修改内容；**翻译方案以 `docs/translation-name-rulings.md` 的裁定为准**，本节只记本次为何这样改，不重复登记方案。引用规范或裁定条款时只写链接与条款号，不复制条文。

| 日文写法 | 本次改动 |
| --- | --- |
| `<日文锚点>` | <目标译法> |

<本次引用的裁定／规范条款或独立权威证据；语料统计只说明修改范围>

## 修订明细

| 文件 | 行 | 修订 |
| --- | ---: | --- |
| `S3_05-05_Chapter2.xhtml` | 604 | 别呀 → 可别啦 |

## 保留项

- <逐条列出未改的同类命中及日文依据>

## 统计与验证

- 修订前 / 修订后：<译法分布与残留数>
- 全部为行内替换，不增删物理行：<各文件 行数/行数 中日一致>
- `python tools/check_alignment.py --strict`：<本次范围、文件数、问题数、未配对项>
- `python tools/publish_auto.py`：<哪些书已上传并回流缓存>
- 回退：`git revert <commit>`
```

留档只写范围、涉及书籍与文件数、统计、验证与必要样例（**忠实反映本次修改内容**），**不复制完整文本**，也不登记翻译方案（方案见 `docs/translation-name-rulings.md`）；不要写进已冻结的 `docs/archive/legacy-changelog.md`。

## 八、坑清单

| 坑 | 规避 |
| --- | --- |
| 全局替换误伤真实义项 | 必须逐点显式映射；先测冲突率 |
| 剥标签忘剥 `<rt>` 导致漏检 | **先剥 `<rt>` 再** `xhtml_text.text_of`（`text_of` 不去注音）；或直接用 proofread-review skill 的 `lookup_source.py` |
| 把风格化 ruby 行当错字 | 跳过（§3.2） |
| 把口癖按单句语感各译各的 | 口癖优先；同一台词跨卷必须逐字相同 |
| 只改正文，漏了 OPF 简介／nav／Introduction | 一并判定并同步（§五 末） |
| 为凑行数增删行 | 行内替换天然保行数；行数变了说明改错了 |
| 顺手把 CRLF 改成 LF | 项目对换行符不敏感（`AGENTS.md`），无需关注换行符 |
| 把未配对作品当「无问题」 | 统计时单列「中文未收录」，不要静默丢弃 |
| 把标题原本是英文的外文题名汉化 | **标题原本是英文的绝对不能改**（如 `BIFROST.` 必须保留英文） |
| 工具或映射表留在 `tools/` | 用完即删；复核用 `git show` |
| 改动前不查该行/该句的既有提交决定，把前一轮刻意定下的写法当「异译」改掉 | 生成映射后、写盘前，对每条原串跑 `git log -S '<原串>' -- <文件>`：命中**非批量导入**的既有提交（尤其 `fix(...) 通校／复核／统一` 类）时，先读该提交信息确认它的判定，再决定动不动。历史案例：`わーい、ミサカがミサカが一番乗り` 已由 `5168175b` 定为「好耶，御坂御坂第一个吃上！」（该提交专门把最后之作的 9 种开场感叹分层，避免与固定口癖 `いやっほう` 混淆），引句统一批次 2 却改成「哇啊，御坂御坂第一个到！」，回退了既有决定 |
| 取形与「库内多数形」相反，或同源词只改了被抽样到的几处 | 写盘**后**对每个新形／旧形做全库计数（`rg -o --no-filename <形> EPUB \| Measure-Object`）：新形应≥旧形且旧形归零；旧形仍有残留时先查是不是同源词的其他译法（如 `ビジネスモデル` 同卷并存「经济地位／经济模式／商业垄断／商业模式」四种）或既有统一提交的回退残留（如 `5da0bc5f` 统一 `FIVE_Over` 后 `S2_11-09` 仍留 9 处 `Five_over`）。历史案例：批次 3 按提案把「诸神之门」取成「自天而降」，终检发现全库另有 29 处作「从天而降」，只得撤回取形 |
| 把机器本地路径写进仓库文件 | 译名表路径按 BetweenLines 声明现读，不落盘 |
