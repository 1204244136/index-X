from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from xhtml_structure import PB_RE, iter_content_pairs, line_kind, pair_structure_problems
from sync_pb_tags import plan_sync, extract_header
from restore_cn_scene_breaks import plan
from fix_legacy_pagebreak_br import find_legacy_br


def xhtml(*body):
    return ['<?xml version="1.0"?>', '<!DOCTYPE html>', '<html><body>',
            '<h1>章</h1>', '', *body, '</body></html>']


class SharedStructureTests(unittest.TestCase):
    def test_line_types_distinguish_structure_and_ignore_inline_gaiji(self):
        for line, kind in (('<br/>', 'br'), ('', 'blank'), ('<h2>节</h2>', 'h2'),
                           ('<p><img src="i.jpg"/></p>', 'img'),
                           ('<p>字<img class="gaiji" src="g.jpg"/></p>', 'p'),
                           ('</body></html>', 'close')):
            self.assertEqual(line_kind(line), kind)

    def test_equal_counts_with_shifted_image_slot_are_rejected(self):
        japanese = xhtml('<p class="pb">A</p>', '<p><img src="i.jpg"/></p>')
        chinese = xhtml('<p><img src="i.jpg"/></p>', '<p>B</p>')
        self.assertTrue(pair_structure_problems(japanese, chinese))
        out, reason, _, _ = plan_sync(japanese, chinese)
        self.assertIsNone(out)
        self.assertIn('行类型错位', reason)

    def test_pb_refuses_length_difference_and_chinese_only_marker(self):
        out, reason, _, _ = plan_sync(xhtml('<p class="pb">A</p>'), xhtml('<p>B</p>', '<p>C</p>'))
        self.assertIsNone(out)
        self.assertIn('行数不同', reason)
        out, reason, _, _ = plan_sync(xhtml('<p>A</p>'), xhtml('<p class="pb">B</p>'))
        self.assertIsNone(out)
        self.assertIn('无日文对应', reason)

    def test_pb_refuses_xml_errors(self):
        out, reason, _, _ = plan_sync(xhtml('<p class="pb">A</p>'), xhtml('<p>B</p></x>'))
        self.assertIsNone(out)
        self.assertIn('XML', reason)

    def test_pb_is_a_class_token_and_applies_to_paragraph_only(self):
        self.assertIsNone(PB_RE.search('<p class="no-pb">A</p>'))
        self.assertIsNone(PB_RE.search('<p class="PB">A</p>'))
        japanese = xhtml('<p class="pb"><img class="fit" src="i.jpg"/></p>')
        chinese = xhtml('<p><img class="fit" src="i.jpg"/></p>')
        out, reason, _, added = plan_sync(japanese, chinese)
        self.assertEqual(reason, '')
        self.assertEqual(added, 1)
        self.assertEqual(out[5], '<p class="pb"><img class="fit" src="i.jpg"/></p>')

    def test_complete_stable_headers_are_shared(self):
        self.assertEqual(extract_header('S5_01_03-02_Chapter1.xhtml'), 'S5_01_03-02')
        self.assertEqual(extract_header('S6_24.06.07-02_Chapter1.xhtml'), 'S6_24.06.07-02')
        self.assertEqual(extract_header('S1_25-Uiharu_Kazari.xhtml'), 'S1_25-UIHARU_KAZARI')

    def test_duplicate_headers_fail_instead_of_selecting_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn, jp = Path(tmp) / 'cn', Path(tmp) / 'jp'
            cn_book, jp_book = cn / '[S1_01]书', jp / '[S1_01]本'
            cn_book.mkdir(parents=True)
            jp_book.mkdir(parents=True)
            for name in ('S1_01-01_Chapter1.xhtml', 'S1_01-01_Chapter2.xhtml'):
                (cn_book / name).write_text('')
            (jp_book / 'S1_01-01.xhtml').write_text('')
            with self.assertRaisesRegex(ValueError, '重复表头'):
                list(iter_content_pairs(cn, jp))

    def test_known_pair_exception_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            cn, jp = Path(tmp) / 'cn', Path(tmp) / 'jp'
            for side in (cn, jp):
                book = side / '[S5_01_03]书'
                book.mkdir(parents=True)
                (book / 'S5_01_03-06.xhtml').write_text('')
            self.assertEqual(list(iter_content_pairs(cn, jp)), [])

    def test_scene_restore_does_not_relocate_chinese_separator(self):
        japanese = xhtml('<p>A</p>', '<br/>', '<p>B</p>', '<p>C</p>', '<br/>')
        chinese = xhtml('<p>甲</p>', '<p>乙</p>', '<br/>', '<p>丙</p>')
        out, reason = plan(japanese, chinese)
        self.assertIsNone(out)
        self.assertIn('不擅自搬动', reason)

    def test_legacy_cleanup_refuses_structure_drift(self):
        japanese = xhtml('<p class="pb">A</p>', '<h2>节</h2>')
        chinese = xhtml('<p>甲</p>', '<br/>', '<p>乙</p>')
        self.assertEqual(find_legacy_br(japanese, chinese), [])


if __name__ == '__main__':
    unittest.main()
