# Domain Docs

工程类 skill 在探索本仓库代码库时，应如何消费本仓库的领域文档。

## 探索之前先读这些

- 仓库根的 **`CONTEXT.md`**，或
- 若存在仓库根的 **`CONTEXT-MAP.md`**：它指向每个上下文各一份 `CONTEXT.md`，读取与主题相关的每一份。
- **`docs/adr/`**：读取涉及你即将改动的区域的 ADR。多上下文仓库还应查看 `src/<context>/docs/adr/` 中的上下文级决策。

若上述文件不存在，**静默继续**。不要指出其缺失，也不要主动建议先创建它们。`domain-modeling` skill（经 `grill-with-docs` 与 `improve-codebase-architecture` 抵达）会在术语或决策真正定下来时按需创建。

## 文件结构

单上下文仓库（大多数仓库）：

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

多上下文仓库（根目录存在 `CONTEXT-MAP.md`）：

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← 系统级决策
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← 上下文专属决策
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## 使用术语表的词汇

当你的产出提到某个领域概念时（issue 标题、重构提案、假设、测试名），使用 `CONTEXT.md` 中定义的术语，不要漂移到术语表明确回避的同义词。

若需要的概念尚未进入术语表，这本身是个信号：要么你在发明项目不使用的语言（重新考虑），要么确实存在缺口（记下来交给 `domain-modeling`）。

## 标记 ADR 冲突

若你的产出与既有 ADR 矛盾，明确暴露出来，而不是静默覆盖：

> _与 ADR-0007（event-sourced orders）矛盾，但值得重新讨论，因为……_
