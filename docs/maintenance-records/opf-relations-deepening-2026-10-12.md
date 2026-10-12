# OPF manifest/spine 事实采集集中维护（2026-10-12）

## 范围

在既有 `epub_structure.py` 集中 OPF 有序条目读取，接入容器合同、入库合同与体检的 spine 读取。本次涉及 6 个文件：共享模块、体检调用方、两份测试、工具合同与本记录。依据为 [工具合同 C0](../../tools/README.md#c0-共享内核) 的共享实现要求。

未修改书籍内容，未执行真实同步或发布；不调整 OPF 根文件位置、必备包装页范围、其他包装页存在性和 manifest 声明判定，也不调整发布计划。

## 实现与保留合同

`opf_relations(root, scope=..., tag_case=...)` 接收已解析 XML，返回有序 `ManifestItem`／`SpineItemref`。缺值为空字符串，重复项全部保留，不选择重复 ID 的优先项，不解析资源路径，不输出合同诊断。

| 调用方 | 范围与标签口径 | 保留的判定 |
| --- | --- | --- |
| 容器合同 | 首个直接 manifest/spine 的直接条目；exact | 空 ID 仍登记；重复 ID 报错，最后媒体类型参与 spine 内容类型检查 |
| 入库合同 | 全树条目；casefold | 非空 ID 的成员关系、重复报告与顺序；所有重复条目的资源目标均参与图片声明检查 |
| 体检 spine 读取 | 全树条目；exact | 最后非空 ID/href 生效；空 idref 忽略，未知 idref 保留空 href |

容器／入库的 XML 解析、错误消息与继续检查策略不变。无新增索引、缓存、插件或工作流入口。

## 明确允许的体检行为修正

移除正则 OPF 条目读取，改为 XML 解析：支持单引号、命名空间前缀、实体解码及属性间空白；注释和 CDATA 中的伪条目不再被当作声明。仅精确 `id`／`href`／`idref` 属性定义关系，`data-*` 与带命名空间的属性不再冒充它们。

非法 OPF 返回空 spine，不从部分坏文本提取关系；容器与入库入口继续按原合同报告 XML 错误。体检继续执行必备包装页检查。

## 验证

- 新增 19 项测试：共享入口 5 项、容器／入库合同 6 项、体检读取与包装页集成 8 项。
- 修改前源码通过 8 项合同保全反例；4 项解析修正测试能复现旧实现缺陷，修改后全部通过。
- 全套工具测试执行 690 项：688 项通过、2 项因 Windows symlink 创建权限跳过，无失败。
- 归档 81 本的 spine href、包装页、容器与入库检查结果逐书与修改前基线完全一致，均为 0 问题；OPF 字节指纹亦完全一致。基线仅存系统临时目录。
- 实际运行 `python tools/check_epub_health.py --root EPUB --only dir-name,metadata-title,packaging-required --strict`：81 本、1249 个 XHTML，0 问题。
- 项目文档检查、`python -m compileall -q tools` 与 `git diff --check` 通过。
- 全库 Ruff 仍有 67 条既有诊断，未通过；对照修改前源码，本次修改的 Python 文件诊断类别和消息均未增加。
