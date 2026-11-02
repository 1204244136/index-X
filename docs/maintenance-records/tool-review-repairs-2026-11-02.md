# 工具审查问题修复（2026-11-02）

文档职责与入口见 [文档索引](../README.md)。本记录保存当次修复范围与验收事实；当前命令行为以 [工具合同](../../tools/README.md) 为准。

## 范围

基于 `d760abde` 的工具目录审查，修复本轮确认的 14 项问题。改动限工具、回归测试、工具合同及受影响的导入／复核 skill 说明；不修改 EPUB 成品、日文参考、同步基线或外部分发副本，不执行发布。

| 审查项 | 修复结果 | 回归测试 |
| --- | --- | --- |
| 1 计划章节名越界写入 | `fname` 限单文件名且大小写不敏感判重；全部最终目标在写前解析并验证 | `test_import_review_regressions.py` |
| 2 预览报告覆盖交稿 | 报告写前保护计划、实际交稿、参考、素材及成品；报告与正文失败共同回滚 | `test_import_review_regressions.py` |
| 3 内容序平移回滚不完整 | 源、临时名、目标及引用纳入共享回滚事务，覆盖单次重命名失败与引用写入失败 | `test_shift_content_sequences.py` |
| 4 DOCX 译注二次转义 | 保留已安全转义的行内 XML，实体与 ruby 正常渲染 | `test_import_review_regressions.py` |
| 5 混合译注记号顺序 | 两种记号在一次从左到右匹配中提取；初始 ID 与列表均遵循首引顺序 | `test_import_review_regressions.py` |
| 6 已暂存改动漏出复核 | `--worktree` 提取 HEAD 到当前文件的净差，覆盖暂存、未暂存和已暂存新增文件 | `test_proofread_review.py` |
| 7 实义改动误判规范级 | 删除“儿”交语义复核；语气词仅在整条独立表达时自动归规范级 | `test_proofread_review.py` |
| 8 单侧空正文 L2 满分 | 严格模式在模型加载前拒绝单侧正文缺失；L2 空段落豁免限双侧均空 | `test_check_semantic_alignment.py` |
| 9 覆盖缓存残留旧改动 | 显式 `--overwrite-cache` 全量镜像受影响书，清除缓存独有增删改 | `test_publish_auto.py` |
| 10 冲突跳过仍成功退出 | 冲突书计入失败，正常书可完成，整批返回 1 且仅成功书推进清单 | `test_publish_auto.py` |
| 11 选书预检漏跨范围 UUID | 与全中文根比对 UUID，只阻断所选书参与的冲突 | `test_publish_preflight.py` |
| 12 混合整书删除被阻断 | 从实际变化确认整本删除，分离现存候选后严格预检，支持删除与修改同批 | `test_publish_auto.py` |
| 13 译名核对覆盖重复目录 | 所选范围内同侧重复作品号明确报输入错误，包含无正文的重复目录 | `test_check_translation_table.py` |
| 14 同章图锚丢失 | 全部图锚按实际字符位置参与估算；修正小节偏移与锚点归属；单锚点保留已知页码 | `test_epub_composition_metrics.py` |

## 验证

- 全套 `python -m unittest discover -s tools/tests -p "test_*.py"`：1148 项，1143 通过、5 跳过；无失败。相较审查基线新增 30 项回归，新增跳过项为当前 Windows 环境无符号链接权限的别名保护测试。
- 发布修复使用临时目录中的真实 B／C CLI 验证，覆盖缓存独有增删改、混合冲突批次、混合删除批次及清单范围；使用 `--no-upload`。
- 导入修复使用临时材料执行真实 CLI，验证越界与报告冲突整批不写、合法预览报告、混合译注顺序、ruby／实体保真，以及正常平移引用更新。故障注入测试另覆盖事务回滚。
- 语义检查使用真实 NumPy 和带调用计数的模型桩：正常双侧正文编码两次；单侧空正文返回 1、编码零次；双侧纯图范围编码零次。实际 CLI 的单侧空正文在模型加载前阻断；此验证不代表真实模型语义准确率验收。
- 译名表实际 CLI 使用临时表格与重复作品目录，返回 2、列出冲突路径且无 traceback。
- `check_project_docs.py` 问题 0 条；两个改动 skill 通过 `quick_validate.py`；`git diff --check` 通过。
- 已人工复核新增／修改的注释、docstring 与帮助文本，并由其他智能体交叉复核导入、复核分级及页数分析的修复差异。

skill 校验初次在基础环境因缺少 PyYAML 无法运行，改用已有向量环境并启用 UTF-8 后通过，未安装或更新依赖。
