from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_project_docs import audit


class DocumentationTests(unittest.TestCase):
    def test_links_anchors_and_missing_tool_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tools").mkdir()
            (root / "docs").mkdir()
            (root / "README.md").write_text("# 项目\n[有效](docs/spec.md#内容)\n[失效](missing.md)\n[锚点](docs/spec.md#错误)\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# 规约\n", encoding="utf-8")
            (root / "docs/spec.md").write_text("# 内容\n", encoding="utf-8")
            (root / "tools/README.md").write_text("工具职责\n", encoding="utf-8")
            (root / "tools/check_example.py").write_text("", encoding="utf-8")
            issues = audit(root)
            self.assertEqual(len(issues), 3)
            self.assertTrue(any("missing.md" in issue for issue in issues))
            self.assertTrue(any("标题锚点" in issue for issue in issues))
            self.assertTrue(any("check_example.py" in issue for issue in issues))
            (root / "tools/README.md").write_text("`check_example.py`：只读检查\n", encoding="utf-8")
            self.assertEqual(len(audit(root)), 2)

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


if __name__ == "__main__":
    unittest.main()
