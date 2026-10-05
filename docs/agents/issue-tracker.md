# Issue tracker: GitHub

本仓库的 issue 与 spec 以 GitHub Issues 承载，所有操作使用 `gh` CLI。

## 约定

- **创建 issue**：`gh issue create --title "..." --body "..."`；多行正文用 heredoc。
- **读取 issue**：`gh issue view <number> --comments`，用 `jq` 过滤评论，并同时取回 labels。
- **列出 issue**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，按需加 `--label`、`--state` 过滤。
- **评论 issue**：`gh issue comment <number> --body "..."`
- **加／去标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭**：`gh issue close <number> --comment "..."`

仓库由 `git remote -v` 推断；在 clone 内执行时 `gh` 会自动识别。

## Pull requests as a triage surface

**PRs as a request surface: no.** _（若本仓库把外部 PR 当作功能请求，改为 `yes`；`triage` 会读这个标志。）_

设为 `yes` 时，PR 走与 issue 相同的标签与状态，命令改用 `gh pr` 等价形式：

- **读取 PR**：`gh pr view <number> --comments`；diff 用 `gh pr diff <number>`。
- **列出待 triage 的外部 PR**：`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`，只保留 `authorAssociation` 为 `CONTRIBUTOR`、`FIRST_TIME_CONTRIBUTOR`、`NONE` 的条目（丢弃 `OWNER`/`MEMBER`/`COLLABORATOR`）。
- **评论／打标签／关闭**：`gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub 的 issue 与 PR 共用同一套编号，因此裸写的 `#42` 可能是任意一种：先用 `gh pr view 42` 解析，失败再回退 `gh issue view 42`。

## When a skill says "publish to the issue tracker"

创建一个 GitHub issue。

## When a skill says "fetch the relevant ticket"

运行 `gh issue view <number> --comments`。

## Wayfinding operations

供 `wayfinder` 使用。**map** 是一个 issue，**ticket** 是它的子 issue。

- **Map**：单个带 `wayfinder:map` 标签的 issue，承载 Notes / Decisions-so-far / Fog 正文。`gh issue create --label wayfinder:map`。
- **子 ticket**：作为 GitHub sub-issue 关联到 map（用 `gh api` 调 sub-issues 端点）。若仓库未启用 sub-issue，则把子 issue 加进 map 正文的任务列表，并在子 issue 正文顶部写 `Part of #<map>`。标签用 `wayfinder:<type>`（`research`/`prototype`/`grilling`/`task`）。一旦认领，该 ticket 指派给负责推进的开发者。
- **阻塞关系**：优先用 GitHub **原生 issue dependencies**，这是界面上可见的规范表示。加边：`gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`，其中 `<blocker-db-id>` 是阻塞方的数字**数据库 id**（`gh api repos/<owner>/<repo>/issues/<n> --jq .id`，**不是** `#number` 也不是 `node_id`）。GitHub 通过 `issue_dependencies_summary.blocked_by` 报告未关闭的阻塞方，这就是实时闸门。若该能力不可用，回退为在子 issue 正文顶部写一行 `Blocked by: #<n>, #<n>`。当所有阻塞方都关闭时，该 ticket 解除阻塞。
- **前沿查询**：列出 map 的未关闭子 issue（`gh issue list --state open`，限定在 map 的 sub-issue／任务列表内），剔除存在未关闭阻塞方（`issue_dependencies_summary.blocked_by > 0`，或 `Blocked by` 行中仍有未关闭 issue）或已有 assignee 的条目；按 map 顺序取第一个。
- **认领**：`gh issue edit <n> --add-assignee @me`，这是本会话的第一次写入。
- **结案**：`gh issue comment <n> --body "<答案>"` → `gh issue close <n>` → 在 map 的 Decisions-so-far 追加一条上下文指针（gist + 链接）。
