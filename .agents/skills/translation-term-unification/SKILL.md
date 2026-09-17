---
name: translation-term-unification
description: index-X（某系列 EPUB 档案）译名／术语统一工作流。用于收敛同一日文锚点的多种中文异译、统一角色口癖与专有写法、裁定敬称与术语分层：以日文写法为锚逐点定位、显式映射逐条预检、只改 EPUB/ 行内文字、跑门禁并留档。触发词：译名统一、术语统一、译法不一致、异译、口癖统一、译名订正、敬称统一、术语审计、term unification、translation consistency。
---

# 译名／术语统一工作流（index-X）

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
3. **只改行内文字，不增删物理行**，不动标签、属性、注音、资源引用、标题结构；改完中日行数必须不变。
4. **写入落点只有 `EPUB/`**（内容写入的唯一权威落点）。`.cache/` 一律只读，仅用于分析与中日对照。改完由 `publish_auto.py` 回流 OneDrive 与缓存。
5. **任务脚本与映射数据不留仓库**：一次性修订属 `AGENTS.md`「工具与记录的边界」，不新增 `tools/fix_*.py`、`tools/*_overrides.json`。定位／替换脚本丢在 `.cache/` 或临时目录，跑完删除；复核与回退用 `git show` / `git revert`。
6. **不留档则不算完成**：改动落在两本及以上书籍（中日两侧同一作品算一本）→ 写 `docs/maintenance-records/`；只落在一本内 → 不留档，由提交承载。

## 三、判定口径

### 3.1 锚点与分层

- 锚点是**日文写法**，不是中文现状、不是台版／网翻／维基旧译。同一日文词形在系列内出现多种译法时，选**覆盖率最高且与其它义项冲突最小**的候选（冲突率要实测，见 §四 步骤 3）。
- 同一日文有**两层用法**时必须分层（范例：`サイド`＝术语「阵营」，带 `こちら／あちら／むこう` 等指示注音的 `側`＝指示代词「侧／那边」）。两层不得互串：术语层不得落成「势力／侧／方／世界」，指示层不得升格为「阵营」。**同一行同时出现两个锚点时按日文写法分别判定。**
- 译名表是**锚点的第一顺位来源**（见 §3.3）；表里没有才走「日文原文 + 语料统计」裁定，并在留档中写明理由。

### 3.2 检索时的三个必守口径

- **剥离标签先剥 `<rt>`**：`<ruby>魔術<rt>まじゆつ</rt></ruby>サイド` 若只去标签会变成 `魔ま術じゆつサイド` 而**漏检**（`epub_audit.text_of` 就是只去标签的那种，用它之前必须先剥注音）。这个口径 bug 曾导致「科学阵营」改完而「魔法阵营」漏改 31 处。
- **2 字词不当强证据**：「時代」「科学」这类在正文里常以普通词义出现，只有达到门槛的长别名才可作为「译名不一致」的强证据（`docs/translation-spec.md` 五.5）。
- **风格化行默认跳过**：带「符号 + ruby 注音」的段落（如 `<ruby>〼<rt>是</rt></ruby>`、`<ruby>◎<rt>若</rt></ruby>`）繁简混用与符号是风格的一部分，不得当错字／繁体残留处理，术语判定跳过后交人工。

### 3.3 锚点数据源（本机，不写进仓库文件）

| 数据 | 位置 |
| --- | --- |
| 译名对照表 | BetweenLines 仓库 `src/workbenches/translation-compare/ai/profiles/local/work-profile.js` 的 `termTables` 声明（本机 xlsx，**路径随本机环境变化，按该声明现读，不要硬编码**） |
| 说话习惯表（角色口癖、固定语尾，52 条已内化） | BetweenLines `src/workbenches/translation-compare/ai/profiles/demo.js` |
| 表格字段 | `base_ori`/`original`（日文原词）、`ruby_ori`（特殊读音）、`base_trans`/`translation`（中文译名）、`type`（人名／术语）、`other_fandom`（其他译法） |

口癖类任务先查说话习惯表：**同一角色的同一句日文在不同卷必须逐字相同**，跨卷不一致就是要收敛的对象。

### 3.4 注音义务的锚点是 BW 源的特殊读音

判定「原文是否带注音」必须回 BookWalker 分页源核对，不能只看缓存：`bw_preprocess.py` 已把多段 ruby 合并、只保留特殊注音，源里普通汉字词也标读音（`<ruby>学<rt>がく</rt>園<rt>えん</rt>…`）。因此「日文有特殊注音则译文必须有注音」的锚点是源中的**特殊读音（当て字／外来语）**，普通读音不构成译文注音义务。这条只在任务涉及注音增减时使用；单纯换汉字写法不动 `<rt>`。

## 四、执行流程

### S0 读既有裁定，避免重开已决口径

先查 `docs/maintenance-records/` 的同类记录与本文件 §六 索引。**已裁定过的锚点不得再换目标译法**；同一锚点二次统一要说明前次结论哪里不适用。

### S1 写前同步

```powershell
python tools/publish_auto.py            # 预览可加 --dry-run
```

确认三副本（`EPUB/`、`.cache/`、OneDrive）在最新状态。**有冲突先按 `AGENTS.md` 合并，不得选边覆盖。**

### S2 锚点检索（只读）

- 分析源优先 `.cache/epub-work/japanese-text/`（日文完整）与 `chinese-text/`；写作目标是 `EPUB/`。
- 检索一律用 `rg` 或直读，**不用 CodeGraph**：正文是字面文本，不构成符号。
- 中日配对：同作品号目录；文件按**表头 + 内容序**对齐（`01`＝序章／引子、`02`＝行间一、`03`＝第一章…）。作品号／表头解析用 `tools/epub_ids.py`（`book_id`／`work_id`／`header_of`／`content_sequence`），不要自己写正则。
- 逐点产出三列：日文锚点位置 → 中文同行现状 → 判定（应改 / 保留 / 待人工）。**中文未收录的作品不纳入**（如 S3_12–S3_16 长期未收录），在统计中单列。

### S3 裁定目标译法

对每个候选给出「全书频次 → 改动面 → 与其它义项冲突率 → 是否与日文对仗」四项依据，取多数派且无冲突者。冲突率要实测（例：`势力` 段 71 行中 4 行与作品固有「势力」义项压平，`阵营` 段 173 行中仅 1 行）。裁定结果写进留档的口径表。

### S4 生成显式映射并预检

按 §五 的命令生成业务映射（书籍、文件、行号、原串、新串）。执行器用本 skill 附带的模板：

```powershell
Copy-Item .agents/skills/translation-term-unification/references/unify_terms_template.py .cache/_unify_terms.py
# 填 MAPPINGS 后：
python .cache/_unify_terms.py                  # 预检：只打印，不写盘
python .cache/_unify_terms.py --apply           # 预检全过才写 EPUB/
python .cache/_unify_terms.py --apply --tsv .cache/_unify.tsv   # 顺带产出可粘进留档的明细表
Remove-Item .cache/_unify_terms.py             # 用完删除，不提交
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
python tools/check_alignment.py --strict        # 中日行数 / 模板 / h2 / 图片行；当前基线 913 正文文件 0 问题
python tools/check_epub_health.py --strict      # 单侧结构（XML、ruby、加粗、悬空引用等）
python tools/check_translation_spec.py          # 涉及标点／注音／单位时跑；报告在 .cache/epub-work/
```

`check_alignment.py` 的输出行数异常（如「913 个正文文件」变成别的数字）要先解释再继续，不得当成噪声跳过。

### S7 写后同步、留档、提交

```powershell
python tools/publish_auto.py            # 打包上传 OneDrive + 回流缓存 + 更新清单
```

- 跨作品 → 新建 `docs/maintenance-records/<锚点 slug>-<YYYY-MM-DD>.md`（模板见 §七）。
- 单作品 → 不留档。
- 提交：中文 + Conventional Commits（如 `fix(S4_03): 统一白鸟炽媚口癖「当方」译为「本人」`）。**只暂存本任务涉及的文件**，不纳入用户其它未提交改动；不 push。
- 若工作区有其他任务的未提交改动，与该改动同处一批文件时：按口径改完但只提交本任务部分，并在留档里写明工作区状态与未纳入原因（范例：`benizome-zerifish-catchphrase-translation-consistency-2026-09-16.md` §「工作区状态说明」）。

## 五、常用命令

```powershell
# 日文锚点：全库计数与逐点位置（-n 带行号；.cache 为分析源）
rg -n --no-heading "サイド" .cache/epub-work/japanese-text --glob "*.xhtml" | Measure-Object -Line

# 中文现状：某译法分布
rg -n --no-heading "科学势力|科学侧|科学方" EPUB --glob "*.xhtml"

# 剥标签后比对（务必先剥 <rt>）
# `epub_audit.text_of` 只剥标签、**不剥注音**，直接用它检索会把「魔術サイド」拆成「魔術 まじゆつ サイド」
# 现成实现（先剥 <rt> 再 text_of，已封装路径与内容序）：见 proofread-review skill 的 references/lookup_source.py
# 逐行取纯文本时的最小写法（复用既有口径，不另写一套剥离逻辑）：
#   stripped = re.sub(r"<(rt|rp)\b[^>]*>.*?</\1>", "", raw, flags=re.S)
#   lines = [epub_audit.text_of(ln.encode("utf-8")) for ln in stripped.split("\n")]

# 只读审计
python tools/epub_audit.py                      # 术语审计：中日译法差异报告 → .cache/epub-work/report.json|md
python tools/check_translation_spec.py --pattern "*S3_10*"

# 复核某次改动的语义影响（提交级）
python tools/proofread_review.py <commit>       # 产物 .cache/epub-work/proofread-review/
```

**同步的元数据不在中日配对范围内**，但同属术语一致性，需按内容单独判定并同步：`content.opf` 简介、`nav.xhtml` / `toc.ncx` 目录标签、`*-Introduction.xhtml`（与 OPF 简介同文，必须同步）、无日文对照本的作品（如 `S6_10.06.26`）。

## 六、已裁定结论索引

做新任务前先查这里；命中就沿用，不要在无关任务里顺手改动。

| 记录 | 锚点 → 结论 |
| --- | --- |
| `science-magic-side-translation-consistency-2026-09-12.md` | `サイド` → 阵营；带指示注音的 `側` → 侧／那边（分层，不得互串） |
| `esper-rank-term-unification-2026-09-13.md` | 超能力者排名 `第X位` 写法；比赛名次／序数＋量词等 32 处保留 |
| `sisters-plural-number-ruling-2026-09-12.md` | `妹達（シスターズ）` 汉字写「妹妹」还是「妹妹们」按原文指代判定 |
| `screen-term-unification-2026-02-14.md` | `大画面`（`<rt>エキシビジョン</rt>`）→ 大屏幕 |
| `portable-terminology-unification-2026-09-14.md` | 便携类 → 便携式；游戏机类 → 掌上游戏机 |
| `treatment-room-term-unification-2026-09-14.md` | `処置室` 统一；`応急処置` → 应急处置 |
| `wind-power-propeller-term-unification-and-fix-2026-09-14.md` | 风力发电螺旋桨，清理历史机械替换残留 |
| `sprengel-honorific-unification-2026-09-15.md` | `シュプレンゲル嬢` 敬称统一 |
| `handcuffs-operation-name-translation-consistency-2026-09-15.md` | `オペレーションネーム・ハンドカフス` → 作战名称·手铐行动；指物时仍作「手铐」 |
| `benizome-zerifish-catchphrase-translation-consistency-2026-09-16.md` | 红染·洁莉菲修口癖 `やめてよね` → 可别啦（口癖优先于单句语感） |
| `air-disintegration-semantic-rails-2026-09-14.md` | `空中分解` 按语义分轨，不一律同译 |
| （提交 `defc1b50`） | 白鸟炽媚口癖 `当方` → 本人（自称，不得与「我方／阵营」串层） |

## 七、留档模板

```markdown
# <锚点>翻译统一记录（YYYY-MM-DD）

- 范围：`EPUB/` 中文归档与 `.cache/epub-work/` 中日配对文本
- 涉及书籍：S3_03、S3_05
- 修改文件：N 个中文 XHTML
- 行内替换：M 处

## 判定口径

| 日文写法 | 中文规范 |
| --- | --- |
| `<日文锚点>` | <目标译法> |

<选它的依据：频次、覆盖率、冲突率、对仗；口癖类写明排他性证据>

## 修订明细

| 文件 | 行 | 修订 |
| --- | ---: | --- |
| `S3_05-05_Chapter2.xhtml` | 604 | 别呀 → 可别啦 |

## 保留项

- <逐条列出未改的同类命中及日文依据>

## 统计与验证

- 修订前 / 修订后：<译法分布与残留数>
- 全部为行内替换，不增删物理行：<各文件 行数/行数 中日一致>
- `python tools/check_alignment.py --strict`：913 个正文文件，0 个问题
- `python tools/publish_auto.py`：<哪些书已上传并回流缓存>
- 回退：`git revert <commit>`
```

留档只写结论、范围、统计、保留项与必要样例，**不复制完整文本**；也不要写进已冻结的 `docs/archive/legacy-changelog.md`。

## 八、坑清单

| 坑 | 规避 |
| --- | --- |
| 全局替换误伤真实义项 | 必须逐点显式映射；先测冲突率 |
| 剥标签忘剥 `<rt>` 导致漏检 | **先剥 `<rt>` 再** `epub_audit.text_of`（`text_of` 不去注音）；或直接用 proofread-review skill 的 `lookup_source.py` |
| 把风格化 ruby 行当错字 | 跳过（§3.2） |
| 把口癖按单句语感各译各的 | 口癖优先；同一台词跨卷必须逐字相同 |
| 只改正文，漏了 OPF 简介／nav／Introduction | 一并判定并同步（§五 末） |
| 为凑行数增删行 | 行内替换天然保行数；行数变了说明改错了 |
| 顺手把 CRLF 改成 LF | 换行符不作为修改对象（`AGENTS.md`） |
| 把未配对作品当「无问题」 | 统计时单列「中文未收录」，不要静默丢弃 |
| 工具或映射表留在 `tools/` | 用完即删；复核用 `git show` |
| 把机器本地路径写进仓库文件 | 译名表路径按 BetweenLines 声明现读，不落盘 |
