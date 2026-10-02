# 文档索引

本文件是**文档的唯一定位入口**：说明各文档写什么、什么时候看，以及它们之间的边界。新增、改名或调整文档角色时更新本索引及受影响的引用；活跃文档开头保留回指本文件的入口。冻结归档不补回指、不改正文。

## 一、按角色分类

| 文档 | 写什么 | 什么时候看 |
| --- | --- | --- |
| [`README.md`](../README.md) | 面向读者：项目介绍、下载、反馈、版本对比 | 了解 X 系列是什么、怎么获取 |
| [`AGENTS.md`](../AGENTS.md) | 仓库级规约：系列编号、表头命名、固定行模板、数据流与编辑边界、版本控制边界 | 任何维护动作前；命名／落点／边界的**唯一规范来源** |
| [`tools/README.md`](../tools/README.md) | 工具入口、参数、数据流、判定口径与可验证行为 | 运行任何 `tools/` 命令前 |
| [`translation-term-unification/SKILL.md`](../.agents/skills/translation-term-unification/SKILL.md) | 流程：译名／术语统一**怎么做** | 收敛异译、统一角色口癖与专名、裁定敬称与术语分层 |
| [`proofread-review/SKILL.md`](../.agents/skills/proofread-review/SKILL.md) | 流程：批量译文改动**怎么复核** | 复核校对产出、判定误改并回改 |

## 二、翻译类文档的分工

本索引统一登记文档职责；以下只描述各文件负责的主题，不复制规范条文：

| 文档 | 写什么 |
| --- | --- |
| [翻译规范（EPUB 成品层）](translation-spec.md) | 译文**该写成什么样**：标点、字形、注音、译注、语义与证据边界（规范执行类以此为准） |
| [译名选取规范](translation-name-selection-spec.md) | 一个译名在多个候选之间**怎么取舍**：从俗 → 从官 → 自拟、原语还原与防日语中转 |
| [X 版译名差异说明](x-translation-differences.md) | 本项目与灰机 Wiki 译名表之间**人为制定的固有差异**（取舍而非缺陷，两侧各自维持）；差异清单是一张 Markdown 表格，同时作为 `tools/check_translation_table.py` 的**门禁**被机器读取 |
| [译名裁定总表](translation-name-rulings.md) | **已经作出过的裁定**：某锚点在多个成立候选间定了哪个、否决了什么、哪些不作统一 |
| [`maintenance-records/`](maintenance-records/) | **只忠实反映本次修改内容**：范围、涉及书籍与文件数、统计、验证、样例。**不是翻译方案的来源** |

选译法的**原则**看前三份；**已决的取舍**看裁定总表；**这次改了什么、改了多少**看留档与提交。

## 三、归档与冻结

| 文档 | 状态 |
| --- | --- |
| [`archive/legacy-changelog.md`](archive/legacy-changelog.md) | 原 `docs/changelog.md`，已冻结归档，**禁止继续编辑** |

## 四、维护约定

- 本文件**不承载规范条文、裁定结论或工具参数**——那些仍在各自文档中维护，保持单一来源，不在本文件复制。
- 同一规则只在一处写正文，其余处只留指针：规范条文以 `translation-spec.md` 为准，译名选取以 `translation-name-selection-spec.md` 为准，已决裁定以 `translation-name-rulings.md` 为准，机器可判定的词表以对应 `tools/check_*.py` 的常量为准。
- 职责变化只在本索引登记；其他入口保留指针，文件新增／改名时修复受影响的相对链接。工具行为变更更新 `tools/README.md` 合同和对应验证，不在索引复制参数。
- 外部规范、译名表和 BetweenLines 的动态定位、版本证据及缺失时的处理统一见 `translation-spec.md`「外部依赖与核验」；私人机器路径不写入活跃文档。
- `maintenance-records/` 保留当次事实和当时口径；旧流程不能作为当前操作依据。允许修复链接或有提交证据的日期错误，必须保留更正说明。
