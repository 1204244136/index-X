from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from audit_risk import audit_risk_flags, audit_risk_details


class AuditRiskTests(unittest.TestCase):
    def test_negation_change(self):
        flags = audit_risk_flags("没有问题", "有问题", "問題はない")
        self.assertIn("negation", flags)

    def test_number_change(self):
        flags = audit_risk_flags("共12人", "共2人", "一二人")
        self.assertIn("number", flags)

    def test_question_change(self):
        flags = audit_risk_flags("是真的吗？", "是真的。", "本当だろうか？")
        self.assertIn("question", flags)

    def test_kanji_residual(self):
        flags = audit_risk_flags("滨面仕上", "浜面仕上", "浜面仕上")
        self.assertIn("kanji", flags)

    def test_bold_punct(self):
        flags = audit_risk_flags("<b>说到底</b>", "<b>说到底，这件事</b>")
        self.assertIn("bold_punct", flags)

    def test_quote_nesting(self):
        flags = audit_risk_flags("「好。」", "「收集到「变动」挺好。」")
        self.assertIn("quote_nest", flags)

    def test_controlled_term(self):
        flags = audit_risk_flags("她穿着袴", "她穿着和服裤裙")
        self.assertIn("controlled_term", flags)

    def test_ruling_terms_from_table(self):
        """裁定表候选列标「成品旧译」的条目才生成受控术语规则。"""
        from audit_risk import load_ruling_terms
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rulings.md"
            path.write_text(
                "| 日文锚点 | 裁定 | 被否决或并存的候选 | 理由 | 判定 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| `ホテルエアリアル` | 空中饭店 | 空中酒店（成品旧译 7 处，S2_08） | 按指示取表内写法 | |\n"
                "| `リンクス` | 山猫 | 猞猁（`Lynx` 的动物学名式写法） | 语域一致 | |\n",
                encoding="utf-8")
            terms = load_ruling_terms(str(path))
            self.assertEqual(len(terms), 1, "只有标「成品旧译」的条目才生成规则")
            self.assertIn("空中酒店", terms[0][0])
            self.assertEqual(terms[0][1], "空中饭店")

    def test_large_deletion_and_addition(self):
        del_flags = audit_risk_flags("这是一段非常非常长的文字内容，包含了很多重要的实义成分", "文字")
        self.assertIn("del_large", del_flags)

        add_flags = audit_risk_flags("文字", "这是一段新增加的非常非常长的解释性说明文字")
        self.assertIn("add_large", add_flags)


if __name__ == "__main__":
    unittest.main()
