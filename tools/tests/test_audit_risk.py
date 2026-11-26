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

    def test_extra_terms_reach_flags(self):
        """复核入口把裁定表规则传进 audit_risk_flags 时应产生受控术语标记。"""
        flags = audit_risk_flags("使用魔法", "使用魔术", "魔術を使う",
                                 extra_terms=[(r"魔术", "魔法", "裁定表：魔術→魔法")])
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

    def test_ruling_terms_with_note_column_and_role_table(self):
        """备注列标记「成品旧译／成品旧写法」且含多候选、散文说明与角色列时能正确解析并过滤。"""
        from audit_risk import load_ruling_terms
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rulings.md"
            path.write_text(
                "## 五、术语\n\n"
                "| 日文锚点 | 裁定 | 被否决或并存的候选 | 备注 | 判定 | 机检 |\n"
                "| --- | --- | --- | --- | --- | --- |\n"
                "| `セイズ魔術` | **赛尔魔法** | 塞德尔魔法／赛德魔法·塞德／塞兹·赛兹 | 赛德魔法·塞德：成品旧译 | 人读 |  |\n"
                "| `イシス` | 伊西斯 | 伊西丝 | 伊西丝：成品旧写法 |  |  |\n"
                "| `エニーリャ` | 艾妮莉亚；**同作品另有其他角色** | 艾妮莉娅 | 艾妮莉娅：成品旧写法 | 人读 |  |\n"
                "| `〜班` | `〜小队` | 照搬日文「班」；「小组／组／队／人马」等并存写法 | 成品旧译 | 人读 |  |\n\n"
                "## 六、角色\n\n"
                "| 角色 | 日文锚点 | 裁定 | 被否决或并存的候选 | 备注 | 判定 | 机检 |\n"
                "| --- | --- | --- | --- | --- | --- |\n"
                "| 甲 | `テスト` | 测试正译 | 测试旧译 | 成品旧译 |  |  |\n",
                encoding="utf-8",
            )
            terms = load_ruling_terms(str(path))
        by_form = {pat: std for pat, std, _ in terms}
        self.assertEqual(by_form.get("塞德尔魔法"), "赛尔魔法")
        self.assertEqual(by_form.get("赛德魔法"), "赛尔魔法")
        self.assertEqual(by_form.get("伊西丝"), "伊西斯")
        self.assertEqual(by_form.get("艾妮莉娅"), "艾妮莉亚")
        self.assertEqual(by_form.get("测试旧译"), "测试正译")
        self.assertNotIn("赛德", by_form)
        self.assertNotIn("小组", by_form)

    def test_repo_rulings_yields_non_empty_clean_terms(self):
        from audit_risk import load_ruling_terms
        rulings_path = TOOLS.parent / "docs" / "translation-name-rulings.md"
        terms = load_ruling_terms(str(rulings_path))
        self.assertGreater(len(terms), 0)
        forms = {pat for pat, _, _ in terms}
        self.assertIn("巫毒咒术师", forms)
        self.assertIn("伊西丝", forms)
        self.assertIn("艾妮莉娅", forms)
        self.assertIn("赛德魔法", forms)
        self.assertNotIn("赛德", forms)

    def test_large_deletion_and_addition(self):
        del_flags = audit_risk_flags("这是一段非常非常长的文字内容，包含了很多重要的实义成分", "文字")
        self.assertIn("del_large", del_flags)

        add_flags = audit_risk_flags("文字", "这是一段新增加的非常非常长的解释性说明文字")
        self.assertIn("add_large", add_flags)

    def test_bold_attributes_entity_protection_and_plain_term_matching(self):
        # 带属性 bold 含标点应命中，XML 实体内部 ; 不误报
        self.assertIn("bold_punct", audit_risk_flags("<b>词</b>", '<b class="em">重点，词</b>'))
        self.assertNotIn("bold_punct", audit_risk_flags("<b>&amp;</b>", "<b>&amp;</b>"))
        # 属性里的旧词不触发 controlled_term
        self.assertNotIn("controlled_term", audit_risk_flags(
            "正文", '<p><span data-old="和服裤裙">袴之少女</span></p>',
        ))


if __name__ == "__main__":
    unittest.main()
