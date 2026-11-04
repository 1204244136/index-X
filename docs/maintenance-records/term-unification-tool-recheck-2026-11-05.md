# 术语统一工具修复后回查与旧形清理（2026-11-05）

- 范围：`EPUB/` 中文归档；按历史术语统一提交回查结果补正 10 本作品、14 个 XHTML 文件。
- 涉及作品：S1_03、S1_07、S1_18、S1_20、S1_25、S2_08、S2_10、S3_08、S5_01_01、S5_04_02。
- 修改规模：177 个物理行、191 个术语出现位置；不增删物理行。

## 本次依据

- 译名表：`Data_Translation.tabx.xlsx`，读取 `data` 工作表，SHA-256 为 `8f033ac98e3f3f7e59bc7055856406d096bb206f46bfbc75ab7fd8eb180dc355`；读取日期为 2026-11-05。
- 人名沿用当前译名表、[译名裁定总表](../translation-name-rulings.md) §五及既有统一结果，不重新选定译法；裸名与全名一起核对，排除译注中现实传说人物的同形写法。
- S1_07-03 L14 对应 BW 原始包 `とある魔術の禁書目録(7).epub` 的 `item/xhtml/p-003.xhtml` L28：`聖ブレイズの伝承を骨組みとした海流操作`。全包仅这一处相关圣名，圣名裸写，无 ruby；源包 SHA-256 为 `40379b2a5c75bd7b1d0f3d1540033a41d990c2a1e585e7e8f8cccf05d3e6d4c1`。沿用[既有人名统一记录](term-unification-batch4-foreign-names-2026-09-27.md)中同一圣人的定名「圣伯拉削」，按[翻译规范](../translation-spec.md)三.1 移除中文原有 `Blaise` 注音。
- S5_01_01 后记 L8、L9 实际对应 S5_01_03-06 L487、L488 的 `主に魔術サイド寄り`、`魔術サイド全体`，按既有 `サイド`／`側` 分层修正。这里按内容定位，未假定同作品同行配对成立。

## 本次修正

- 依当前译名表落地「阿德列登空贼港」6 处与「金崎大学附属机构·肌肉萎缩症研究中心」1 处；两项均不新增译名裁定。
- 清理旧形「席薇亚」26 次、「圣布雷斯」1 处、「迪奥多西亚／伊蕾翠」2 行、「理查／理查·布雷夫」152 次、「H.T.特里斯墨吉斯忒斯」1 处。
- 将跨书后记中对应日文 `魔術サイド` 的「魔法侧」2 处统一为「魔法阵营」。
- 「昼間」普通词「白天」与目录前缀 `Tu` 保留，译名表工具对此两项的报告属于同形误报。

## 验证

- 显式映射预检：177 行、14 文件通过；写后旧形检索全部为 0。独立检查逐文件重建授权替换结果，无额外改动；`git diff --check` 无问题。
- `python tools/check_term_anchors.py --strict`：0 命中；774 文件已核对、16 文件未核对，另有 2 本／21 单元豁免，因部分覆盖退出 2。
- `python tools/check_translation_table.py --table Data_Translation.tabx.xlsx --strict`：本次两项表形差异已消除，仅剩「昼間」与 `Tu` 两项已确认误报，退出 1。
- `python tools/check_translation_table.py --table Data_Translation.tabx.xlsx --audit-rulings`：0 问题；本次未修改裁定表。
- `python tools/check_epub_health.py --strict`：0 问题。
- `python tools/text_norm.py --dry-run`：0 命中。
- `python tools/check_translation_spec.py`：21 条既有 warning/info 级报告，无新增 error。
- `python tools/check_alignment.py --strict --require-jp`：786 个配对单元，1129 个已验证正文文件问题 0；93 个未配对正文，整体因既有缺少日文配对范围退出 2。
- `python tools/check_echo.py` 对上述 10 本生成写后候选；9 本有可靠配对，S1_25 因合并源／人工对齐例外零覆盖，S5_01_01、S5_04_02 部分覆盖。候选不作为全卷语义通过结论；本次仅验收列出的术语修订。
- `python tools/check_project_docs.py`：0 问题。

## 同步

- `python tools/publish_auto.py --only-books "<上述 10 本 chinese-text 目录>"`：完成回流。
- 同范围再次 `--dry-run`：缓存、EPUB/ 与 OneDrive 基线均无待发布差异。
- 上述 10 本的归档与中文缓存共 382 个文件逐字节一致。

回退：`git revert <commit>`。
