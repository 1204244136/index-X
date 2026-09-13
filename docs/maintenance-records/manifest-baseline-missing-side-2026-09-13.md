# 发布清单基线整侧缺失（日文侧）调查与修复（2026-09-13）

- 范围：`.cache/epub-work/manifest.json` 与日文缓存的基线一致性；只读调查 + 一次基线重建
- 相关提交：`b62b2066`（前置检查）、`c44e6ff3`（文档）、`48a3319b`（同期发布的 pb 内容修复）

## 现象

`python tools/publish.py --dry-run` 报告 **89 本书籍有变更**：

- 中文 2 本（`S5_01_03`、`S5_02_03`，各 1 个文件）——正是本次要发的 pb 修复
- 日文 **87 本、4736 个文件全部被判为「新增」**

日文侧此前没有任何编辑，不该出现变更。

## 证据链

1. **基线缺整侧**：`manifest.json` 的 `files` 共 2720 条，按侧分组只有 `chinese-text: 2720`，字符串 `japanese-text` 出现 **0 次**。
2. **缓存 = 上次打包态**：87 本日文缓存与 `.cache/epub-work/packed-epubs/japanese-text/` 的 87 个 `.epub` 逐条比对，**4736 个文件全部逐字节相同**，0 新增、0 删除、0 修改。
3. **打包态 = OneDrive 分发副本**：那 87 个 packed `.epub` 与 `OneDrive\某系列\日文原文` 的 87 个 `.epub` 做 SHA-256 比对，**87/87 全等**；`pull-state.tsv` 记录的 87 个日文 size 也逐个与 packed 相等。
4. **中文侧对照健康**：同一张基线里中文只有 2 本有差异（pb 修复），说明中文基线是新的、可用的，缺的只有日文侧。

结论：日文缓存 == 上次打包 == OneDrive 分发副本，**日文侧没有未发布内容**；89 本里的 87 本是纯粹的假阳性。

## 根因

`manifest.json` 的日文条目只有两条路径会建立：

- `pull.ps1` 在清单已存在时，对「本次重新解压的书籍」执行 `manifest.py --update-books`（`$extractedBooks.Add("$($source.Name)/$book")`，两侧都含）；清单不存在时全量扫描一次；
- `python tools/manifest.py`（不带参数）全量扫描。

而 `publish.py` / `publish_epub.py` 只会用 `update_manifest_for_book` 重建**被成功发布的那本书（中文）**的记录，永远不会新增日文条目。因此：当基线建立时该侧尚未进入缓存、此后又没有日文书籍经 `pull.ps1` 重新解压（`pull-state` 里它们的 OneDrive mtime/size 未变，脚本就不会重解压），该侧基线会一直空缺且无人发现。

本次的旁证：日文缓存 4736 个文件中有 **4335 个集中在 2026-09-04 17 一次性写入**，形态更像整批替换而非经 `pull.ps1` 增量解压。

另注：`publish_epub.py` 中本就有一段注释，说明「EPUB/ 只镜像 chinese-text，所以要把基线里的 japanese-text 条目排除、不能当成删除」——即基线**本应**包含日文条目，当前状态是偏离设计的。

## 影响

`detect_changes` 对基线里不存在的路径一律判 `added`，于是每次 `publish.py`（不限 `--side`）都会把日文侧整侧重新打包并**重新上传 OneDrive，约 696 MB / 87 本**，内容却完全没变；同时推进它们的 `pull-state`。数据不会损坏，但「发布范围」失去意义，也掩盖了日文侧真正的改动。

## 修复

只重建日文侧基线，不动中文：

```powershell
$keys = Get-ChildItem -LiteralPath .cache/epub-work/japanese-text -Directory | ForEach-Object { "japanese-text/$($_.Name)" }
python tools/manifest.py --cache .cache/epub-work --update-books @keys
```

结果：条目 **2720 → 7456**（+4736，全部是 `japanese-text`）。事后核对：中文 2720 条**零修改、零删除、零新增**，即尚未上传的 pb 修复仍可被检出；随后 `publish.py --dry-run` 从 89 本收敛为 **2 本**，`--side japanese` 显示无变更。

**为什么不是全量扫描**：`python tools/manifest.py` 会把两侧一起重设基线，从而把当时尚未上传的改动静默标记为「已发布」，下次发布就会跳过它。要全量扫描必须先把待发布内容发完。

## 新增门禁

`sync_core.missing_baseline_sides(cache_root, baseline, sides)`：返回「缓存里有书、基线里却一条记录都没有」的侧；缓存里本来就没有书的侧不算缺失（避免误报）。`publish.py` 按 `--side` 决定本次范围、`publish_epub.py` 固定作用于中文侧，二者都在加载基线之后、任何写入之前拦截，命中时报出缺失侧与修复命令并返回退出码 1；`--force`（语义即「忽略基线、全量重做」）跳过该检查。

验证：修复前该检查确实拦下发布（退出码 1）；`--side chinese` 不触发（日文不在范围）、`publish_epub.py` 不触发、`--force` 跳过；`tools/tests` 新增 2 例（整侧缺失被检出、空侧不误报）。

## 遗留与注意

- 本门禁只覆盖「整侧缺失」。**单本书**没有基线时仍会被判为全部新增，这与「确实新加入的书」无法区分，属既有行为，未加限制。
- 反向情形（基线有某侧记录、缓存里该侧已整体不存在）未加限制：那会被当成整侧删除，属需要人工确认的操作。
- 若日文缓存再次被 `pull.ps1` 之外的途径整批替换，基线会再次静默失真——此时该门禁会在下次发布前直接报错，按上文「修复」重建即可。
