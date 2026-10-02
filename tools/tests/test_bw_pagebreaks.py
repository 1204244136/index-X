from __future__ import annotations

import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from bw_preprocess import inject_pb_css
from merge_bw_pages import add_class_pb, group_units, merge_unit, parse_page_content


SVG = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
       'id="outer" width="100%" height="100%" viewBox="0 0 100 200">'
       '<image class="inside" xlink:href="../image/i-001.jpg" width="100" height="200"/></svg>')


def page(number: int, body: list[str], *, image: bool = False, h1: str = "") -> dict:
    raw = '\n'.join([
        '<?xml version="1.0"?>', '<!DOCTYPE html>',
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title/></head>'
        + ('<body>' if image else '<body class="p-text">') + '<div class="main">',
        h1, '', *body, '</div></body></html>',
    ])
    result = parse_page_content(f'S9_99-01_p-{number:03d}.xhtml', raw)
    assert result is not None
    return result


def merged(pages: list[dict]) -> list[str]:
    notes: list[str] = []
    units = group_units(pages, notes)
    assert len(units) == 1
    result = merge_unit(units[0], notes)
    assert result is not None
    ET.fromstring('\n'.join(result))
    return result


class OuterPagebreakTokenTests(unittest.TestCase):
    def test_child_class_stays_on_child_when_outer_paragraph_has_no_class(self):
        line = '<p id="outer"><img class="fit" src="i.jpg"/></p>'
        result = add_class_pb(line)
        self.assertEqual(result, '<p class="pb" id="outer"><img class="fit" src="i.jpg"/></p>')

    def test_svg_and_img_without_class_are_supported(self):
        for line in (SVG, '<img id="outer" src="i.jpg"/>'):
            with self.subTest(line=line):
                result = add_class_pb(line)
                self.assertEqual(ET.fromstring(result).get('class'), 'pb')
                self.assertEqual(add_class_pb(result), result)
        self.assertIn('<image class="inside"', add_class_pb(SVG))

    def test_class_quote_style_spacing_and_tokens_are_preserved(self):
        for line, expected in (
            ("<p id='a' class = 'fit  center '><b>X</b></p>",
             "<p id='a' class = 'fit  center pb'><b>X</b></p>"),
            ('<svg id="a" class="fit"><image class="inside"/></svg>',
             '<svg id="a" class="fit pb"><image class="inside"/></svg>'),
            ('<img class="no-pb" src="i.jpg"/>', '<img class="no-pb pb" src="i.jpg"/>'),
            ('<p class="">X</p>', '<p class="pb">X</p>'),
        ):
            with self.subTest(line=line):
                self.assertEqual(add_class_pb(line), expected)
                self.assertEqual(add_class_pb(expected), expected)

    def test_pb_already_present_is_byte_identical(self):
        for line in ('<p class="pb fit">X</p>', "<svg class='fit pb  center'>x</svg>",
                     '<img class="pb" src="i.jpg"/>'):
            self.assertEqual(add_class_pb(line), line)

    def test_class_text_inside_an_attribute_value_is_not_an_attribute(self):
        line = '<p title=\'class="inside" > test\' id="x"><b class="child">X</b></p>'
        result = add_class_pb(line)
        self.assertEqual(result, '<p class="pb"' + line[2:])
        self.assertIn('<b class="child">', result)

    def test_unsupported_outer_block_is_untouched(self):
        line = '<div><p class="fit">X</p></div>'
        self.assertEqual(add_class_pb(line), line)


class IndependentImagePagebreakTests(unittest.TestCase):
    def test_trailing_svg_page_gets_a_break_without_changing_text_or_line_count(self):
        output = merged([page(1, ['<p>正文</p>'], h1='<h1>第一章</h1>'), page(2, [SVG], image=True)])
        self.assertEqual(len(output), 8)
        self.assertEqual(output[5], '<p>正文</p>')
        self.assertEqual(output[6].replace(' class="pb"', '', 1), SVG)
        self.assertEqual(ET.fromstring(output[6]).get('class'), 'pb')

    def test_image_between_text_pages_marks_only_the_image(self):
        output = merged([page(1, ['<p>A</p>'], h1='<h1>第一章</h1>'),
                         page(2, [SVG], image=True), page(3, ['<p>B</p>'])])
        self.assertEqual(output[5], '<p>A</p>')
        self.assertEqual(ET.fromstring(output[6]).get('class'), 'pb')
        self.assertEqual(output[7], '<p>B</p>')
        self.assertEqual(output[6].count('class="pb"'), 1)

    def test_consecutive_independent_images_each_have_one_break(self):
        output = merged([page(1, ['<p>A</p>'], h1='<h1>第一章</h1>'),
                         page(2, [SVG], image=True), page(3, [SVG], image=True),
                         page(4, ['<p>B</p>'])])
        self.assertEqual([ET.fromstring(line).get('class') for line in output[6:8]], ['pb', 'pb'])
        self.assertEqual(output[5], '<p>A</p>')
        self.assertEqual(output[8], '<p>B</p>')

    def test_image_wrapped_in_a_paragraph_marks_the_outer_wrapper(self):
        output = merged([page(1, ['<p>A</p>'], h1='<h1>第一章</h1>'),
                         page(2, [f'<p class="fit">{SVG}</p>'], image=True)])
        document = ET.fromstring(output[6])
        self.assertEqual(document.get('class'), 'fit pb')
        self.assertIsNone(document[0].get('class'))
        self.assertEqual(document[0][0].get('class'), 'inside')

    def test_inline_illustration_on_a_text_page_is_not_an_independent_image_page(self):
        inline = '<p><img class="fit" src="i.jpg"/></p>'
        output = merged([page(1, ['<p>A</p>', inline], h1='<h1>第一章</h1>'),
                         page(2, ['<p>B</p>'])])
        self.assertEqual(output[6], inline)
        self.assertFalse(any('class="pb"' in line for line in output))

    def test_text_to_text_keeps_the_previous_last_paragraph_marker(self):
        output = merged([page(1, ['<p>A</p>'], h1='<h1>第一章</h1>'), page(2, ['<p>B</p>'])])
        self.assertEqual(output[5], '<p class="pb">A</p>')
        self.assertEqual(output[6], '<p>B</p>')

    def test_leading_images_fold_to_l3_without_break_before_the_chapter(self):
        output = merged([page(1, [SVG], image=True), page(2, [SVG], image=True),
                         page(3, ['<p>A</p>'])])
        self.assertEqual(output[2].count('<svg'), 2)
        self.assertNotIn('class="pb"', output[2])
        self.assertEqual(output[5], '<p>A</p>')

    def test_image_only_unit_keeps_subsequent_image_pages_separate(self):
        output = merged([page(1, [SVG], image=True), page(2, [SVG], image=True)])
        self.assertIsNone(ET.fromstring(output[5]).get('class'))
        self.assertEqual(ET.fromstring(output[6]).get('class'), 'pb')


class SvgPagebreakCssTests(unittest.TestCase):
    def test_css_injection_adds_targeted_svg_rule_and_is_idempotent(self):
        entries = {'item/style/book-style.css': b'p {margin:0;}', 'image.jpg': b'unchanged'}
        inject_pb_css(entries)
        once = dict(entries)
        self.assertIn(b'svg.pb {\n  display: block;', entries['item/style/book-style.css'])
        self.assertNotRegex(entries['item/style/book-style.css'], rb'(?m)^svg\s*\{')
        inject_pb_css(entries)
        self.assertEqual(entries, once)

    def test_existing_pagebreak_rule_is_preserved_when_svg_rule_is_added(self):
        css = b'.pb { break-before: column; }\n'
        entries = {'book.css': css}
        inject_pb_css(entries)
        self.assertTrue(entries['book.css'].startswith(css))
        self.assertEqual(len(re.findall(rb'(?m)^\.pb\s*\{', entries['book.css'])), 1)

    def test_existing_complete_svg_rule_does_not_change(self):
        css = b'.pb{break-before:column;}\nsvg.pb { display : block }\n'
        entries = {'book.css': css}
        inject_pb_css(entries)
        self.assertEqual(entries['book.css'], css)

    def test_commented_out_rules_are_not_treated_as_active(self):
        entries = {'book.css': b'/* .pb {break-before:column;} svg.pb{display:block;} */'}
        inject_pb_css(entries)
        self.assertIn(b'\n.pb {', entries['book.css'])
        self.assertIn(b'\nsvg.pb {', entries['book.css'])


if __name__ == '__main__':
    unittest.main()
