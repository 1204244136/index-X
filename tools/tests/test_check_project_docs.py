from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_project_docs import audit, single_source_issues


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

    def test_layered_anchor_allowed(self):
        """同一锚点带不同义项标识（分层）→ 不报。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build(root, "## 五、设定\n\n" + HEADER
                  + "| `人払い`（术式层） | 闲人驱散 | | |\n"
                  + "| `人払い`（世俗清场） | 人群疏散 | | |\n")
            self.assertEqual(single_source_issues(root), [])

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
