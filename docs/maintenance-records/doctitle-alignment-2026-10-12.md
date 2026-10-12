# 全库 `toc.ncx` 的 `docTitle` 对齐书名（2026-10-12）

- **触发**：批 3 门禁上线后，`ncx-doctitle`（报告级）存量 67 处，经裁定排队清理；用户指示执行。
- **范围**：**68 本**（`toc.ncx` 的 `<docTitle><text>` 对齐为书目录名；`dc:title` 已是基准，不改）。
- **依据**：[EPUB 成品构成规范](../epub-artifact-spec.md) 第三节「`toc.ncx` 的 `docTitle` 必须等于 `dc:title`」。
- **性质**：规范执行与明显错误订正，不构成裁定；不涉正文译文用词，不登记[译名裁定总表](../translation-name-rulings.md)。

## 一、改动

- 68 个 `toc.ncx`，每个**恰好替换 1 行**（`<text>` 内容），合计 **+68 / −68**；另有 13 本原本已一致，未动。
- 一次性修订用临时脚本预览后写入（默认预览、`--apply` 才写、单文件变更超过一行即拒写），按 AGENTS「工具与记录的边界」**改完即删**，不留在仓库里。

**9 处「非缺前缀」的差异**（其余 59 本只是缺 `[作品号]` 前缀）均按书名收敛：

| 书 | 原 `docTitle` | 差异性质 |
| --- | --- | --- |
| `[S2_23]新约 某魔法的禁书目录 22REVERSEX` | `…22RX` | 卷号被缩写 |
| `[S4_01]某暗部的少女共栖 1X` | `某暗部的少女共栖` | 缺卷号 |
| `[S4_02]某暗部的少女共栖 2X` | `[S4_02]某暗部的少女共栖2X` | 缺空格 |
| `[S5_02_01]`／`[S5_02_02]`／`[S6_14.09.10]` | 如 `某科学的超电磁炮 SS 学艺都市篇X` | 空格与书名不一致 |
| `[S5_04_01]某科学的超电磁炮SS3 斯塔蒂瓦里篇X` | `某科学的超电磁炮 SS3 史迪特拉第瓦里篇X` | **译名不一致**（旧译）——按书名的 X 版写法收敛 |
| `[S6_20.05.09]创约 某魔法的禁书目录SS 黑夜海鸟篇X` | `创约 某魔法的禁书目录 SSX` | **丢了卷名** |
| `[S6_24.01.10]某科学的心理掌握 女王的戏剧X` | `[S6_24.01.10]某科学的心理掌握 女王的演戏X` | **错字「演戏」** |
| `[S0_00]读前必看` | `读前必看` | 缺作品号前缀（阅读说明，非卷） |

## 二、副作用收口（同批）

`[S0_00]` 对齐后，构成门禁豁免清单里那条 `ncx-doctitle` 条目已无对象，**予以移除**（`tools/alignment_rules.py`，注释写明理由：留空条目只会掩盖将来的回归）；`tools/check_epub_health.py` 的模块说明、`tools/README.md` 与测试同步为「`S0_00` 的 `dir-name`／`toc-entry` 两项」。

## 三、验证

| 门禁 | 结果 |
| --- | --- |
| `check_epub_health.py --root EPUB --only ncx-doctitle` | **0 命中**（含豁免计数 0） |
| `check_epub_health.py --root EPUB --strict` | 退出 0（error 0；warning 8 = `toc-entry` 2 ＋ `identifier-unique` 6） |
| `python -m unittest discover -s tools/tests -p "test_*.py"` | 649 tests OK（2 skipped） |
| `check_epub_validity.py EPUB --structural --strict`（calibre 9.14） | 81 本、0 问题 |
| `check_project_docs.py` | 0 问题 |

## 四、发布

`publish_auto.py` 走**流程 C**（`EPUB/` → OneDrive ＋ 缓存镜像），68 本「全部方向执行成功」；复验 dry-run 无待发布。

## 五、未纳入（队列不变）

- `toc-entry`：`[S6_24.01.10]` 目录首条目为「1」（nav 与 ncx 一致），单本内容改动待办。
- `identifier-unique`：6 本共用同一 uuid，已裁定另立项。
- 全库 `style.css` 统一：路线 A（保留 `.box1`、只需拉平 1 本）／路线 B（全库删，76 本重发）。

## 六、回退

`git revert` 本次提交可恢复 68 个 `toc.ncx`；OneDrive 上的旧包会被重新打包覆盖，无需另行处理。
