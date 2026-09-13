# 发布入口统一（`publish_auto.py`）设计与验收（2026-09-13）

- 范围：`tools/publish_auto.py`（新增）+ `tools/tests/test_publish_auto.py`（新增）；既有发布工具行为未改动
- 动机：日常发布要按「改动落在哪一份副本」记得住三条不同指令，选错方向会覆盖另一份副本

## 现状（改动前）

三份副本各有固定角色，对应三个方向、三条指令：

| 方向 | 指令 | 数据流 |
| --- | --- | --- |
| 流程 A | `./tools/pull.ps1 -SyncToEpub` | OneDrive -> 缓存 + `EPUB/`（不打包上传） |
| 流程 B | `python tools/publish.py` | 缓存 -> `EPUB/` + OneDrive |
| 流程 C | `python tools/publish_epub.py` | `EPUB/` -> OneDrive + 缓存 |

三条指令都以 `manifest.json` 为唯一基线，但各自只比较自己那一侧的当前状态：
`publish.py` 比对缓存，`publish_epub.py` 比对 `EPUB/`，`pull.ps1` 比对 `pull-state.tsv`（OneDrive `.epub` 的 mtime/size）。
因此「改动在哪」这件事，代码里本来就已经可判别，只是没有统一入口去读它。

选错方向的代价不对称：流程 B 用缓存覆盖 `EPUB/`，流程 C 用 `EPUB/` 覆盖缓存，两者对同一本书同时成立时，
谁后跑谁赢，且都会连带重新打包上传 OneDrive。

## 方案

新增 `tools/publish_auto.py` 作为统一入口，只做「判别 + 路由 + 串行调用」，不复制任何同步/打包逻辑：

1. 加载 `manifest.json`，先跑与既有工具相同的**基线整侧缺失**前置检查（基线失真时无法判别真实改动位置，必须先修）。
2. 分别扫描缓存与 `EPUB/`，用 `sync_core.detect_changes` 得到两侧的逐书改动；`EPUB/` 按既有口径只认中文侧。
3. 读 `pull-state.tsv` 并与 OneDrive 的 `.epub` 逐本比对 mtime ticks/size，得到「外部更新」书集（与 `pull.ps1` 同一判定）。
4. 按下面的判定表决定执行哪些方向，然后以 `--only-books` 调用对应底层工具。

### 判定表

| 缓存改动 | `EPUB/` 改动 | OneDrive 外部更新 | 行为 |
| --- | --- | --- | --- |
| 有 | 无 | 无 | 流程 B，只处理这些书 |
| 无 | 有 | 无 | 流程 C，只处理这些书 |
| 有 | 有（不同书） | 无 | 两个方向各处理自己的书 |
| 有 | 有（同一本书） | — | **停止**，报告冲突书，要求 `--from` 指定以哪一侧为准 |
| 无 | 无 | 有 | 流程 A 拉回这些书 |
| 有（与外部更新同一本书） | — | 有 | **停止**，报告副本已分叉，要求 `--from` 指定 |
| 有（与外部更新不同书） | — | 有 | 流程 A + 流程 B（书集不相交） |

冲突与分叉都**不自动选边**：`--from cache` 让冲突书走流程 B；`--from epub` 让冲突书走流程 C
（因会丢缓存中未发布的修改，必须显式加 `--overwrite-cache`）；`--from onedrive` 走流程 A
（覆盖本地未发布修改同样需要 `--overwrite-cache`）。`--force` 会忽略基线、失去判别依据，因此必须配合 `--from`。

显式指定 `--from cache` / `--from epub` 时不隐式执行流程 A，只提示 OneDrive 侧有外部更新，避免「指定本地方向」与实际写入方向不符。

## 验证

- 真机（本仓库缓存 7456 个文件 / 中文 78 本 + 日文 87 本、OneDrive 165 个 `.epub` 与 165 条 `pull-state` 记录）：
  `python tools/publish_auto.py --dry-run` 报告三侧均无改动并退出码 0；drift 检测公式与 `pull.ps1` 完全一致（165 条记录 0 偏差）。
- 新增 `tools/tests/test_publish_auto.py` 覆盖：单侧改动路由、两侧不同书双方向、同一本书冲突停止、`--from cache/epub` 的归属与 `--overwrite-cache` 门槛、`--dry-run` 不执行、`--side` 过滤、`--force` 缺 `--from` 报错、清单缺失报错、
  drift 三种情形（无记录 / 记录一致 / 文件被改动）、drift 与本地改动同书时停止、换行符差异警告，以及两个**真调用底层工具**的集成用例（缓存改动经 `publish.py` 落盘 `EPUB/` 并产出 `packed-epubs`，`EPUB/` 改动经 `publish_epub.py` 回写缓存）。
- `python -m pytest tools/tests -q`：116 passed（含既有用例）。

## 保留项与例外

- 三条底层流程原样保留：需要单方向强制（`--force`、`--sync-only`）或排查时仍可直接运行。
- 统一入口不复制底层逻辑，各流程原有门禁不变：`publish.py` 的严格对齐检查、`publish_epub.py` 的缓存未发布修改冲突跳过、两者的基线整侧缺失检查。
- `--dry-run` 不写入任何副本，也不触发严格对齐检查（与 `publish.py --dry-run` 一致）。
- `EPUB/` 相对基线只差换行符时额外警告（归档检出时的 CRLF/LF 转换不是真实编辑），不阻断，交人工确认。
- OneDrive 目录不可用（未同步 / 换了机器）时跳过流程 A 检测并给出提示，其余方向照常判别。

## 遗留

- 冲突判定以「书」为粒度：同一本书两侧都有改动时无法自动判断哪一侧更新（未比较内容时间或差异范围），一律交人工。
- 单本书基线缺失仍会被判为「全部新增」（与既有行为一致，未新增限制；见 `manifest-baseline-missing-side-2026-09-13.md` 的遗留项）。
- `--force` 与自动判别互斥：全量重做仍需人工指明方向。
