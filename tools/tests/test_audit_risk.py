from __future__ import annotations

import sys
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
        flags = audit_risk_flags("它由圣金属制成", "它由Saintium制成")
        self.assertIn("controlled_term", flags)

    def test_large_deletion_and_addition(self):
        del_flags = audit_risk_flags("这是一段非常非常长的文字内容，包含了很多重要的实义成分", "文字")
        self.assertIn("del_large", del_flags)

        add_flags = audit_risk_flags("文字", "这是一段新增加的非常非常长的解释性说明文字")
        self.assertIn("add_large", add_flags)


if __name__ == "__main__":
    unittest.main()
