# 书内资源引用采集集中维护（2026-10-12）

## 范围与目标

将单侧体检与入库／打包合同重复维护的 XML 属性、CSS 引用采集集中到既有 `epub_structure.py`，保持现有行为不变。本次涉及 6 个文件：共享模块、体检调用方、两份测试、工具合同与本记录；未修改书籍内容，未执行真实同步或发布。

依据为 [工具合同 C0](../../tools/README.md#c0-共享内核) 的「同一规则只维护一份实现」与体检反例要求。此次只集中引用语法知识，不统一体检与入库合同，不重构 OPF manifest／spine 关系，不调整发布计划。

## 落地

- `ResourceReference` 仅保存原始引用值与根相对标记。
- `xml_references` 接收已解析 XML，集中命名空间属性处理与引用属性识别；调用方显式选择已有的 `lower`／`casefold` 口径。
- `css_references` 集中字节级去注释、`url()` 和引号形式 `@import` 的采集。
- `resolve_reference` 的实现与已有导入位置保持不变。
- `find_dangling` 与 `artifact_contract_issues` 使用共享采集，不保留第二份 XML／CSS 引用提取实现。

## 保留的行为

引用顺序、重复项、原始值、严格 UTF-8 解码及异常传播保持不变。体检先完成全部文件采集，再进行目标判定；入库合同逐文件判定引用，随后执行该文件的 OPF 检查。

文件后缀范围、XML 解析与错误处理、原始外链过滤、锚点采集、片段判定、实际路径越界检查与诊断措辞仍在原调用方。采集入口不提前解析 URL，不增加 inline style 等引用语法支持。

## 验证

- 新增 16 项测试：共享入口与入库合同 11 项，体检合同 5 项。覆盖引用顺序、重复项、命名空间、属性归一化、CSS 注释及解码、目标解析时机、`.htm` 范围、非法 XML 继续检查、诊断顺序、同页／跨页锚点、实际存在的越界文件及外链预过滤。
- 将其中 10 项调用方合同测试用于修改前源码，也全部通过；确认这些断言约束既有行为。
- 全套工具测试执行 671 项，669 项通过、2 项跳过，无失败。两项跳过为当前 Windows 环境不允许创建 symlink 的写入安全测试。
- 归档 81 本的 `find_dangling` 与 `artifact_contract_issues` 返回结果逐书与修改前基线完全一致，均为 0 问题；基线只存系统临时目录，不进入版本化档案。
- 实际运行 `python tools/check_epub_health.py --root EPUB --only dangling --strict`：81 本、1249 个 XHTML，0 问题。
- `python tools/check_project_docs.py`：0 问题。
- `python -m compileall -q tools` 与 `git diff --check` 通过。
- 全库 `python -m ruff check tools` 未通过，现有 67 条诊断。对照修改前源码，本次修改的 Python 文件诊断类别与消息均未增加，新测试文件为 0 条；存量 lint 问题不在此次范围内。
