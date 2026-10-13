import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from title_rules import audit_title_contract, heading_label, heading_problems


CSS = b""".heading-lines > .heading-main, .heading-lines > .heading-subtitle,
.heading-lines > .heading-code { display: block; }
.font08 { font-size: 0.8em; } .font06 { font-size: 0.6em; }"""
LAYERED = ('<h1 class="heading-lines"><span class="heading-main">第一章</span>'
           '<span class="font08 heading-subtitle"><ruby>处刑塔<rt>伦敦塔</rt></ruby>等待</span>'
           '<span class="heading-code font06">Rebirth_the...</span></h1>')


def entries(title=LAYERED, label="第一章 处刑塔等待 Rebirth_the...", fragment=""):
    return {
        "OEBPS/Text/S1_01-01.xhtml": (
            '<html><head><link rel="stylesheet" href="../Styles/style.css"/></head><body>'
            + title + '</body></html>').encode(),
        "OEBPS/Styles/style.css": CSS,
        "nav.xhtml": ('<html xmlns:epub="http://www.idpf.org/2007/ops"><body>'
                      '<nav epub:type="toc"><a href="OEBPS/Text/S1_01-01.xhtml'
                      + fragment + '">' + label + '</a></nav></body></html>').encode(),
        "toc.ncx": ('<ncx><navMap><navPoint><navLabel><text>' + label
                    + '</text></navLabel><content src="OEBPS/Text/S1_01-01.xhtml'
                    + fragment + '"/></navPoint></navMap></ncx>').encode(),
    }


class TitleRulesTests(unittest.TestCase):
    def test_projection_preserves_base_spacing_and_code_punctuation(self):
        self.assertEqual(heading_label(ET.fromstring(LAYERED)), "第一章 处刑塔等待 Rebirth_the...")
        h = ET.fromstring('<h1>行间　<ruby>六<rt>six</rt></ruby> &amp; 七</h1>')
        self.assertEqual(heading_label(h), "行间　六 & 七")
        self.assertEqual(audit_title_contract(entries()), [])
        namespaced = ET.fromstring(
            '<h1 xmlns="http://www.w3.org/1999/xhtml">处<ruby>刑塔<rt>伦敦塔</rt></ruby>等待</h1>')
        self.assertEqual(heading_label(namespaced), "处刑塔等待")

    def test_styles_and_unknown_inline_structures_are_blocked(self):
        for h in ('<h1 class="color1">简介</h1>', '<h2 style="color:red">2</h2>',
                  '<h1><span class="font08">题</span></h1>', '<h1><br/>题</h1>',
                  '<h1><div>题</div></h1>', '<h1><img src="x"/></h1>',
                  '<h1 class="unknown">题</h1>'):
            with self.subTest(h=h):
                self.assertTrue(heading_problems(ET.fromstring(h)))
        self.assertEqual(heading_problems(ET.fromstring('<h2 id="toc_1">2</h2>')), [])

    def test_layer_roles_order_emptiness_and_font_ratio(self):
        for h in (LAYERED.replace("font08 heading-subtitle", "heading-subtitle"),
                  LAYERED.replace("heading-main", "heading-code"),
                  LAYERED.replace("第一章", ""),
                  LAYERED.replace('<span class="heading-main">第一章</span>', "第一章"),
                  LAYERED.replace('class="heading-lines"', 'class="heading-lines center"')):
            with self.subTest(h=h):
                self.assertTrue(heading_problems(ET.fromstring(h)))
        self.assertEqual(heading_problems(ET.fromstring(LAYERED.replace("h1", "h2"))), [])
        code_only = ('<h1 class="heading-lines"><span class="heading-main">题</span>'
                     '<span class="heading-code font06">Code.</span></h1>')
        self.assertEqual(heading_problems(ET.fromstring(code_only)), [])

    def test_chapter_spacing_does_not_change_independent_title(self):
        for text in ("序章", "终 章", "序　　章 副题"):
            self.assertTrue(heading_problems(ET.fromstring(f"<h1>{text}</h1>")))
        for text in ("序　章 副题", "终章之后", "前夜祭"):
            self.assertEqual(heading_problems(ET.fromstring(f"<h1>{text}</h1>")), [])

    def test_numeric_section_cannot_bypass_default_style_with_layers(self):
        self.assertTrue(heading_problems(ET.fromstring(
            '<h2 class="heading-lines"><span class="heading-main">1</span>'
            '<span class="heading-subtitle font08">2</span></h2>')))
        self.assertTrue(heading_problems(ET.fromstring(
            '<h2 class="heading-lines"><span class="heading-main">1</span>'
            '<span class="heading-subtitle font08">Aug.31</span></h2>')))

    def test_css_must_be_referenced_and_supply_layer_display_and_ratios(self):
        for css in (CSS.replace(b"display: block", b"display: inline"),
                    CSS.replace(b"0.8em", b"0.7em"), CSS.replace(b"0.6em", b"1em"),
                    CSS + b".font08 { font-size: 12px; }",
                    CSS + b".heading-lines > .heading-main { display: inline; }"):
            book = entries()
            book["OEBPS/Styles/style.css"] = css
            self.assertTrue(any(f[0] == "title-style" for f in audit_title_contract(book)))
        book = entries()
        book["OEBPS/Text/S1_01-01.xhtml"] = book["OEBPS/Text/S1_01-01.xhtml"].replace(
            b"../Styles/style.css", b"missing.css")
        self.assertTrue(any(f[0] == "title-style" for f in audit_title_contract(book)))

    def test_both_catalogs_follow_actual_title_not_reading(self):
        book = entries(label="第一章 处刑塔伦敦塔等待 Rebirth_the...")
        hits = [f for f in audit_title_contract(book) if f[0] == "title-catalog"]
        self.assertEqual(len(hits), 2)
        book = entries()
        book["toc.ncx"] = book["toc.ncx"].replace(b"Rebirth_the...", b"Rebirth_the")
        self.assertTrue(any("顺序必须一致" in f[3] for f in audit_title_contract(book)))
        book = entries(label="第一章 <ruby>处刑塔<rt>伦敦塔</rt></ruby>等待 Rebirth_the...")
        self.assertTrue(any("纯文本" in f[3] for f in audit_title_contract(book)))

    def test_fragment_h3_is_checked_and_nonheading_anchor_is_not_invented(self):
        self.assertEqual(audit_title_contract(entries('<h3 id="a">实际标题</h3>', "实际标题", "#a")), [])
        self.assertTrue(audit_title_contract(entries('<h3 id="a">实际标题</h3>', "简称", "#a")))
        self.assertEqual(audit_title_contract(entries('<p id="a">正文</p>', "自定标签", "#a")), [])

    def test_illustrations_and_special_collection_contract(self):
        for name, body in (("S1_01-Illustrations.xhtml", '<p><img src="a.jpg"/></p>'),
                           ("S1_01-Special.xhtml", '<h1>特别篇</h1>'),
                           ("S1_01-Special.xhtml", '<h1>特典短篇</h1><h2>GAMERS特典 篇名</h2>')):
            self.assertTrue(audit_title_contract({"OEBPS/Text/" + name: f"<html>{body}</html>".encode()}))
        self.assertEqual(audit_title_contract({
            "OEBPS/Text/S1_01-Illustrations.xhtml": "<html><h1>彩页</h1></html>".encode(),
            "OEBPS/Text/S1_01-Special.xhtml": "<html><h1>特典短篇</h1><h2>GAMERS特典</h2></html>".encode(),
        }), [])

    def test_packaging_title_cannot_use_otherwise_legal_layer_structure(self):
        book = entries()
        book["OEBPS/Text/S1_01-Introduction.xhtml"] = book["OEBPS/Text/S1_01-01.xhtml"]
        self.assertTrue(any("首标题必须" in f[3] for f in audit_title_contract(book)))


if __name__ == "__main__":
    unittest.main()
