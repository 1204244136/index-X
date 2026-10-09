from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_project_docs import audit, single_source_issues, tool_cluster_issues


MEMBER_HEAD = "| 工具 | 入口命令 | 读写范围 | 门禁与失败边界 | 测试 |\n| --- | --- | --- | --- | --- |\n"


def member(name: str, command: str = "`python tools/a.py --check`", boundary: str = "【无】") -> str:
    return f"| `{name}` | {command} | 只读 | 边界{boundary} | `test_a.py` |\n"


def cluster(name: str, rows: str) -> str:
    return f"## {name}\n\n{MEMBER_HEAD}{rows}\n"


def readme(*, index: str, router: str, clusters: str, plans: str = "| P1 | 信号 | 判定 | 允许 | 禁止 | C1 | — |\n") -> str:
    return (
        "# 工具\n\n"
        "## 路由\n\n| 你要做什么 | 簇 | 入口 |\n| --- | --- | --- |\n" + router + "\n"
        "## 阻塞与恢复\n\n| # | 触发信号 | 判定 | 允许动作 | 禁止动作 | 簇 | 证据留档 |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n" + plans + "\n"
        "## 簇索引\n\n| 簇 | 定位 | 入口数 | 主要门禁 |\n| --- | --- | --- | --- |\n" + index + "\n"
        + clusters
    )


def write_tool(root: Path, name: str, main: bool = True) -> None:
    (root / "tools" / name).write_text(
        'if __name__ == "__main__":\n    pass\n' if main else "VALUE = 1\n", encoding="utf-8")


class ClusterContractTests(unittest.TestCase):
    """工具簇合同：每个工具一个归属格，索引、入口、预案与路由都必须自洽。"""

    def case(self, *, index: str, router: str, clusters: str,
             tools: tuple[tuple[str, bool], ...] = (("a.py", True),),
             plans: str = "| P1 | 信号 | 判定 | 允许 | 禁止 | C1 | — |\n") -> list[str]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "tools").mkdir()
        for name, main in tools:
            write_tool(root, name, main)
        return tool_cluster_issues(root, readme(index=index, router=router, clusters=clusters, plans=plans))

    def test_compliant_document_has_no_issue(self):
        issues = self.case(
            index="| C1 同步与发布 | 定位 | 1 | 门禁 |\n",
            router="| 发布 | C1 | `python tools/a.py` |\n",
            clusters=cluster("C1 同步与发布", member("a.py")),
        )
        self.assertEqual(issues, [])

    def test_member_tables_require_exactly_one_owner(self):
        issues = self.case(
            tools=(("a.py", True), ("b.py", True)),
            index="| C1 同步与发布 | 定位 | 2 | 门禁 |\n",
            router="| 发布 | C1 | `python tools/a.py` |\n",
            clusters=cluster("C1 同步与发布", member("a.py") + member("a.py")),
        )
        self.assertTrue(any("重复登记" in issue and "a.py" in issue for issue in issues), issues)
        self.assertTrue(any("未被任何簇成员表登记" in issue and "b.py" in issue for issue in issues), issues)

    def test_main_boundary_and_entry_command_columns(self):
        issues = self.case(
            tools=(("m.py", False), ("c.py", True)),
            index="| C1 同步与发布 | 定位 | 1 | 门禁 |\n| C0 共享内核 | 定位 | 1 | 门禁 |\n",
            router="| 发布 | C1 | `python tools/c.py` |\n",
            clusters=(
                cluster("C1 同步与发布", member("m.py", command="`python tools/m.py`"))
                + cluster("C0 共享内核", member("c.py"))
            ),
        )
        self.assertTrue(any("无 __main__ 的模块必须登记在 C0" in issue for issue in issues), issues)
        self.assertTrue(any("有 __main__ 的工具不得登记在 C0" in issue for issue in issues), issues)
        self.assertTrue(any("C0 的入口命令列必须写" in issue for issue in issues), issues)

    def test_index_counts_and_coverage(self):
        issues = self.case(
            index="| C1 同步与发布 | 定位 | 3 | 门禁 |\n| C9 幽灵簇 | 定位 | 1 | 门禁 |\n",
            router="| 发布 | C1 | `python tools/a.py` |\n",
            clusters=cluster("C1 同步与发布", member("a.py")),
        )
        self.assertTrue(any("入口数与成员表不一致" in issue for issue in issues), issues)
        self.assertTrue(any("登记了没有成员表的 C9" in issue for issue in issues), issues)

    def test_boundary_column_must_point_at_defined_plan(self):
        issues = self.case(
            index="| C1 同步与发布 | 定位 | 2 | 门禁 |\n",
            router="| 发布 | C1 | `python tools/a.py` |\n",
            clusters=cluster("C1 同步与发布", member("a.py", boundary="") + member("a.py", boundary="【P9】")),
        )
        self.assertTrue(any("门禁与失败边界必须写" in issue for issue in issues), issues)
        self.assertTrue(any("P9 未在「阻塞与恢复」定义" in issue for issue in issues), issues)

    def test_router_tools_must_exist_in_member_tables(self):
        issues = self.case(
            index="| C1 同步与发布 | 定位 | 1 | 门禁 |\n",
            router="| 发布 | C1 | `python tools/zzz.py` |\n",
            clusters=cluster("C1 同步与发布", member("a.py")),
        )
        self.assertTrue(any("路由表引用的工具不在任何簇成员表" in issue and "zzz.py" in issue for issue in issues), issues)

    def test_missing_structure_is_reported_not_skipped(self):
        legacy = "## 职责与覆盖矩阵\n\n| 工具 | 输入 | 写入 | 门禁 | 测试 |\n| --- | --- | --- | --- | --- |\n| `a.py` | | | | |\n"
        issues = self.case(
            index="| C1 同步与发布 | 定位 | 1 | 门禁 |\n",
            router="| 发布 | C1 | `python tools/a.py` |\n",
            clusters=legacy,
        )
        self.assertTrue(any("缺少簇节与成员表" in issue for issue in issues), issues)

    def test_missing_index_is_reported(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "tools").mkdir()
        write_tool(root, "a.py")
        text = "# 工具\n## 路由\n\n| 你要做什么 | 簇 | 入口 |\n| --- | --- | --- |\n| 发布 | C1 | `python tools/a.py` |\n" \
               + cluster("C1 同步与发布", member("a.py")) \
               + "## 阻塞与恢复\n\n| # | 触发信号 | 判定 | 允许 | 禁止 | 簇 | 证据留档 |\n| --- | --- | --- | --- | --- | --- | --- |\n| P1 | 信号 | 判定 | 允许 | 禁止 | C1 | — |\n"
        issues = tool_cluster_issues(root, text)
        self.assertTrue(any("缺少「## 簇索引」表" in issue for issue in issues), issues)


class DocumentationTests(unittest.TestCase):
    def test_links_anchors_and_missing_tool_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tools").mkdir()
            (root / "docs").mkdir()
            (root / "README.md").write_text("# 项目\n[有效](docs/spec.md#内容)\n[失效](missing.md)\n[锚点](docs/spec.md#错误)\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# 规约\n", encoding="utf-8")
            (root / "docs/spec.md").write_text("# 内容\n", encoding="utf-8")
            (root / "tools/check_example.py").write_text('if __name__ == "__main__":\n    pass\n', encoding="utf-8")
            # 结构合规、且已登记 check_example.py：只剩链接与锚点两条问题
            (root / "tools/README.md").write_text(readme(
                index="| C1 同步与发布 | 定位 | 1 | 门禁 |\n",
                router="| 检查 | C1 | `python tools/check_example.py` |\n",
                clusters=cluster("C1 同步与发布", member("check_example.py")),
            ), encoding="utf-8")
            issues = audit(root)
            self.assertEqual(len(issues), 2, issues)
            self.assertTrue(any("missing.md" in issue for issue in issues))
            self.assertTrue(any("标题锚点" in issue for issue in issues))
            # 工具未登记 → 覆盖检查报出
            (root / "tools/README.md").write_text("工具职责\n", encoding="utf-8")
            issues = audit(root)
            self.assertTrue(any("check_example.py" in issue for issue in issues), issues)

    def test_fenced_examples_and_external_links_are_not_local_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tools").mkdir()
            for path in (root / "README.md", root / "AGENTS.md", root / "tools/README.md"):
                path.write_text('```markdown\n[示例](missing.md)\n```\n[外部](https://example.com/a)\n', encoding="utf-8")
            self.assertEqual(audit(root), [])

    def _active_tree(self, root: Path) -> None:
        """最小合规树：索引已登记 spec.md，各活跃文档开头均有回指。"""
        (root / "tools").mkdir()
        (root / "docs").mkdir()
        (root / "README.md").write_text("# 项目\n[文档索引](docs/README.md)\n", encoding="utf-8")
        (root / "AGENTS.md").write_text("# 规约\n[文档索引](docs/README.md)\n", encoding="utf-8")
        (root / "tools/README.md").write_text("# 工具\n[文档索引](../docs/README.md)\n", encoding="utf-8")
        (root / "docs/README.md").write_text("# 文档索引\n[规范](spec.md)\n", encoding="utf-8")
        (root / "docs/spec.md").write_text("# 规范\n[文档索引](README.md)\n", encoding="utf-8")

    def test_top_level_docs_must_be_registered_in_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._active_tree(root)
            self.assertEqual(audit(root), [])
            (root / "docs/new-spec.md").write_text("# 新规范\n[文档索引](README.md)\n", encoding="utf-8")
            issues = audit(root)
            self.assertEqual(len(issues), 1)
            self.assertIn("缺少文档登记：new-spec.md", issues[0])
            (root / "docs/README.md").write_text("# 文档索引\n[规范](spec.md)\n[新规范](new-spec.md)\n", encoding="utf-8")
            self.assertEqual(audit(root), [])

    def test_active_docs_must_link_back_to_index_near_the_top(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._active_tree(root)
            # skill 的三级相对路径同样算有效回指
            skill = root / ".agents/skills/demo/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("# 流程\n[文档索引](../../../docs/README.md)\n", encoding="utf-8")
            self.assertEqual(audit(root), [])
            # 回指缺失 → 报错
            (root / "AGENTS.md").write_text("# 规约\n", encoding="utf-8")
            issues = audit(root)
            self.assertEqual(len(issues), 1)
            self.assertIn("AGENTS.md", issues[0])
            self.assertIn("回指", issues[0])
            # 回指放在开头范围之外 → 仍报错
            (root / "AGENTS.md").write_text("# 规约\n" + "\n" * 25 + "[文档索引](docs/README.md)\n", encoding="utf-8")
            self.assertEqual(len(audit(root)), 1)


HEADER = "| 日文锚点 | 裁定 | 被否决或并存的候选 | 理由 |\n| --- | --- | --- | --- |\n"


def build(root: Path, rulings: str, spec: str = "") -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "translation-name-rulings.md").write_text(rulings, encoding="utf-8")
    (root / "docs" / "translation-spec.md").write_text(spec, encoding="utf-8")


class SingleSourceTests(unittest.TestCase):
    def test_duplicate_anchor_reported(self):
        """同一锚点 + 相同义项标识重复登记 → 报。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build(root, "## 五、设定\n\n" + HEADER
                  + "| `サイド` | 阵营 | 势力 | |\n"
                  + "| `サイド` | 阵营 | 势力 | |\n")
            issues = single_source_issues(root)
            self.assertTrue(any("裁定条目重复" in issue for issue in issues), issues)

    def test_ruby_anchor_without_backticks_is_collected(self):
        """锚点列的注音锚点写成裸 `<ruby>…</ruby>` → 计入锚点，重复登记仍能报出。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build(root, "## 五、设定\n\n" + HEADER
                  + "| <ruby>時間割り<rt>カリキュラム</rt></ruby> | 课程 | 表侧 | |\n"
                  + "| <ruby>時間割り<rt>カリキュラム</rt></ruby> | 课程 | 表侧 | |\n")
            issues = single_source_issues(root)
            self.assertTrue(any("裁定条目重复" in issue for issue in issues), issues)

    def test_layered_anchor_allowed(self):
        """同一锚点带不同义项标识（分层）→ 不报。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build(root, "## 五、设定\n\n" + HEADER
                  + "| `人払い`（术式层） | 闲人驱散 | | |\n"
                  + "| `人払い`（世俗清场） | 人群疏散 | | |\n")
            self.assertEqual(single_source_issues(root), [])

    def test_layer_may_live_in_note_column(self):
        """锚点列只写锚点、义项区分落在「备注」列（原「理由」列）→ 不报。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build(root, "## 五、设定\n\n"
                  + "| 日文锚点 | 裁定 | 被否决或并存的候选 | 备注 |\n| --- | --- | --- | --- |\n"
                  + "| `スフィア` | 天体仪 | — | 装备义项 |\n"
                  + "| `スフィア` | 天体 | — | 组织义项 |\n")
            self.assertEqual(single_source_issues(root), [])

    def test_same_anchor_and_same_note_still_reported(self):
        """锚点与备注都相同 → 仍判重复（列内只写锚点后，义项标识回落到备注列）。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build(root, "## 五、设定\n\n"
                  + "| 日文锚点 | 裁定 | 被否决或并存的候选 | 备注 |\n| --- | --- | --- | --- |\n"
                  + "| `スフィア` | 天体仪 | — | 装备义项 |\n"
                  + "| `スフィア` | 天体仪 | — | 装备义项 |\n")
            issues = single_source_issues(root)
            self.assertTrue(any("裁定条目重复" in issue for issue in issues), issues)

    def test_spec_embedding_reported(self):
        """规范正文出现裁定锚点且同行带映射标记 → 报。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build(root, "## 五、设定\n\n" + HEADER + "| `サイド` | 阵营 | 势力 | |\n",
                  "示例：`サイド` → 「阵营」。\n")
            issues = single_source_issues(root)
            self.assertTrue(any("出现裁定取值" in issue for issue in issues), issues)

    def test_spec_pointer_line_allowed(self):
        """规范里的指针行（含裁定表链接）→ 不报。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build(root, "## 五、设定\n\n" + HEADER + "| `サイド` | 阵营 | 势力 | |\n",
                  "已裁定锚点见 [译名裁定总表](translation-name-rulings.md)（如 `サイド` → 阵营）。\n")
            self.assertEqual(single_source_issues(root), [])

    def test_whitelist_marker_allowed(self):
        """带行内白名单标记 → 不报。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build(root, "## 五、设定\n\n" + HEADER + "| `サイド` | 阵营 | 势力 | |\n",
                  "示例：`サイド` → 「阵营」。<!-- single-source-ok -->\n")
            self.assertEqual(single_source_issues(root), [])

    def test_bad_section_ref_reported(self):
        """引用不存在的裁定表小节 → 报。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build(root, "## 五、设定\n\n" + HEADER + "| `サイド` | 阵营 | 势力 | |\n",
                  "见裁定表 §11.9。\n")
            issues = single_source_issues(root)
            self.assertTrue(any("§11.9" in issue for issue in issues), issues)

    def test_existing_section_ref_allowed(self):
        """引用存在的裁定表小节 → 不报。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build(root, "## 五、设定\n\n" + HEADER + "| `サイド` | 阵营 | 势力 | |\n\n### 11.1 纠错\n\n"
                  + HEADER + "| `甲` | 乙 | | |\n",
                  "见裁定表 §11.1 与 §五。\n")
            self.assertEqual(single_source_issues(root), [])


if __name__ == "__main__":
    unittest.main()
