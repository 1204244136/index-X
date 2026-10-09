from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from PIL import Image  # noqa: E402  模块本身强依赖 Pillow

from compare_epub_images import (  # noqa: E402
    Asset,
    _layout_from_ratio,
    _uses_s1_illustration_sequence,
    body_number_key,
    body_number_parts,
    collect_book,
    compare_book,
    feature,
    image_name_family,
    name_rule_match,
    page_role,
    render_markdown,
    scan,
)


def asset(name: str, *, locations: tuple[str, ...] = (), layout: str | None = None,
          sha256: str | None = None) -> Asset:
    """构造一个只带判定所需字段的 Asset；路径故意不存在，`feature()` 会记为解码失败。"""
    return Asset(path=Path("/nonexistent") / name, relative=f"OEBPS/Images/{name}",
                 name=name, size=1, sha256=sha256 if sha256 is not None else f"sha:{name}",
                 locations=list(locations), layout=layout)


def write_png(path: Path, size: tuple[int, int] = (40, 60), color: tuple[int, int, int] = (200, 30, 30)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


class PageRoleTests(unittest.TestCase):
    def test_page_role_classifies_packaging_pages(self):
        cases = {
            "S1_01-Cover.xhtml": "cover",
            "S1_01-hyoushi.xhtml": "cover",
            "S1_01-hyou4.xhtml": "back_cover",
            "S1_01-Back_cover.xhtml": "back_cover",
            "S1_01-p-allcover-001.xhtml": "allcover",
            "S1_01-p-bookwalker-001.xhtml": "bookwalker",
            "S1_01-Contents.xhtml": "contents",
            "S1_01-toc-001.xhtml": "contents",
            "S1_01-Illustrations.xhtml": "illustrations",
            "S1_01-kuchie.xhtml": "illustrations",
            "S1_01-01_Chapter1.xhtml": "body",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(page_role(name), expected)


class ImageFamilyTests(unittest.TestCase):
    def test_family_strips_work_prefix_across_series_forms(self):
        cases = {
            "S4_05-i-030.jpg": ("body", None),
            "S5_01_03-i-030.jpg": ("body", None),
            "S6_24.06.07-i-030.jpg": ("body", None),
            "S1_01-cover.jpg": ("cover", None),
            "S5_02_03-hyoushi-2.jpg": ("cover", None),
            "S1_01-hyou4.jpg": ("back_cover", None),
            "S1_01-toc-002.jpg": ("contents", None),
            "S1_01-deputy_cover.jpg": ("deputy_cover", 1),
            "S1_01-kuchie-001.jpg": ("deputy_cover", 1),
            "S1_01-kuchie-003.jpg": ("illustration", 2),
            "S1_01-illustrations1.jpg": ("illustration", 1),
            "S6_24.06.07-illustrations12.jpg": ("illustration", 12),
            "S1_01-unknown-asset.jpg": ("other", None),
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(image_name_family(name), expected)


class BodyNumberTests(unittest.TestCase):
    def test_body_number_key_normalises_the_known_naming_schemes(self):
        cases = {
            "S2_09-p016-p017.jpg": "16-17",
            "p016-p017.jpg": "16-17",
            "S4_05-i-016-017.jpg": "16-17",
            "S4_05-i-030.jpg": "30",
            "S4_05-p030.jpg": "30",
            "S1_03-p000-00-16-1.jpg": "legacy:16-1",
            "cover.jpg": None,
            "S1_01-illustrations1.jpg": None,
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(body_number_key(name), expected)

    def test_body_number_parts_only_for_double_page_ranges(self):
        self.assertEqual(body_number_parts("S4_05-i-232-233.jpg"), (232, 233))
        self.assertIsNone(body_number_parts("S4_05-i-232.jpg"))
        self.assertIsNone(body_number_parts("S1_03-p000-00-16-1.jpg"))


class LayoutTests(unittest.TestCase):
    def test_layout_thresholds(self):
        self.assertEqual(_layout_from_ratio(2.0), "double_page_candidate")
        self.assertEqual(_layout_from_ratio(1.10), "double_page_candidate")
        self.assertEqual(_layout_from_ratio(1.09), "ambiguous_aspect_ratio")
        self.assertEqual(_layout_from_ratio(0.90), "single_page_candidate")
        self.assertEqual(_layout_from_ratio(0.5), "single_page_candidate")
        self.assertEqual(_layout_from_ratio(1.0), "ambiguous_aspect_ratio")

    def test_s1_sequence_scope(self):
        self.assertTrue(_uses_s1_illustration_sequence("S1_03-illustrations1.jpg"))
        self.assertTrue(_uses_s1_illustration_sequence("s1_03-kuchie-002.jpg"))
        self.assertFalse(_uses_s1_illustration_sequence("S2_09-illustrations1.jpg"))


class NameRuleMatchTests(unittest.TestCase):
    def test_family_must_match(self):
        matched, label = name_rule_match(asset("S1_01-cover.jpg", locations=("family:cover:0",)),
                                        asset("S1_01-i-010.jpg", locations=("family:cover:0",)))
        self.assertFalse(matched)
        self.assertEqual(label, "")

    def test_shared_location_is_required(self):
        matched, _ = name_rule_match(asset("S1_01-cover.jpg"), asset("S1_01-cover.jpg"))
        self.assertFalse(matched)

    def test_cover_family_matches_on_shared_location(self):
        matched, label = name_rule_match(asset("S1_01-cover.jpg", locations=("family:cover:0",)),
                                        asset("S1_01-cover.jpg", locations=("family:cover:0",)))
        self.assertTrue(matched)
        self.assertEqual(label, "Cover/cover")

    def test_body_same_number_requires_same_layout_class(self):
        locations = ("header:s1_01-01:0",)
        same = name_rule_match(asset("S4_05-i-030.jpg", locations=locations, layout="single_page_candidate"),
                               asset("S4_05-p030.jpg", locations=locations, layout="single_page_candidate"))
        self.assertTrue(same[0])
        self.assertIn("正文图片编号相同", same[1])
        mismatched = name_rule_match(asset("S4_05-i-030.jpg", locations=locations, layout="double_page_candidate"),
                                     asset("S4_05-p030.jpg", locations=locations, layout="single_page_candidate"))
        self.assertFalse(mismatched[0])

    def test_body_different_numbers_do_not_fall_back_to_slot(self):
        """双方都是规范 i-NNN/pNNN 命名时，编号不同不再靠槽位兜底。"""
        locations = ("header:s1_01-01:0",)
        matched, _ = name_rule_match(asset("S4_05-i-030.jpg", locations=locations),
                                     asset("S4_05-p031.jpg", locations=locations))
        self.assertFalse(matched)

    def test_legacy_body_package_falls_back_to_shared_slot(self):
        """历史 p000-00-XX-1 命名：编号不同（且含 legacy）时仍按同一槽位配对。"""
        locations = ("header:s1_03-02:0",)
        matched, label = name_rule_match(asset("S1_03-p000-00-16-1.jpg", locations=locations),
                                         asset("S1_03-p000-00-17-1.jpg", locations=locations))
        self.assertTrue(matched)
        self.assertIn("正文图片编号", label)

    def test_illustration_numbers_must_agree(self):
        locations = ("family:illustration:1",)
        matched, _ = name_rule_match(asset("S1_01-illustrations1.jpg", locations=locations),
                                     asset("S1_01-illustrations2.jpg", locations=locations))
        self.assertFalse(matched)

    def test_illustration_without_visual_support_needs_s1_sequence(self):
        locations = ("family:illustration:1",)
        # 非 S1 序列且图片无法解码（拿不到视觉证据）→ 不配对
        not_s1 = name_rule_match(asset("S2_09-illustrations1.jpg", locations=locations),
                                 asset("S2_09-kuchie-002.jpg", locations=locations))
        self.assertFalse(not_s1[0])
        # S1 序列走既有包内命名约定，无需额外视觉证据
        s1 = name_rule_match(asset("S1_03-illustrations1.jpg", locations=locations),
                             asset("S1_03-kuchie-002.jpg", locations=locations))
        self.assertTrue(s1[0])
        self.assertEqual(s1[1], "IllustrationsN/kuchie-(N+1)")


class CollectBookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.book = Path(temporary.name) / "[S1_01]测试"
        write_png(self.book / "OEBPS/Images/S1_01-i-010.jpg")
        write_png(self.book / "OEBPS/Images/S1_01-kuchie-002.jpg", color=(10, 20, 30))

    def _page(self, name: str, body: str) -> None:
        path = self.book / "OEBPS/Text" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<html><body>" + body + "</body></html>", encoding="utf-8")

    def test_body_image_gets_header_slot_location(self):
        self._page("S1_01-01_Chapter1.xhtml", '<p><img src="../Images/S1_01-i-010.jpg"/></p>')
        assets = {a.name: a for a in collect_book(self.book)}
        body = assets["S1_01-i-010.jpg"]
        self.assertEqual(body.references, ["OEBPS/Text/S1_01-01_Chapter1.xhtml"])
        self.assertEqual(body.pages, ["S1_01-01"])
        self.assertEqual(body.locations, ["header:s1_01-01:0"])

    def test_packaging_image_gets_family_location(self):
        self._page("S1_01-Illustrations.xhtml", '<p><img src="../Images/S1_01-kuchie-002.jpg"/></p>')
        assets = {a.name: a for a in collect_book(self.book)}
        packaging = assets["S1_01-kuchie-002.jpg"]
        self.assertEqual(packaging.locations, ["family:illustration:1"])
        # 包装页表头由 pairing_header_of 统一成大写形式
        self.assertEqual(packaging.pages, ["S1_01-ILLUSTRATIONS"])

    def test_references_keep_every_occurrence_but_pages_and_locations_are_deduped(self):
        self._page("S1_01-01_Chapter1.xhtml",
                   '<p><img src="../Images/S1_01-i-010.jpg"/></p><p><img src="../Images/S1_01-i-010.jpg"/></p>')
        body = {a.name: a for a in collect_book(self.book)}["S1_01-i-010.jpg"]
        self.assertEqual(body.locations, ["header:s1_01-01:0", "header:s1_01-01:1"])
        # references 按引用出现次数记录（同一页两次引用就两条），报告消费方需自行去重
        self.assertEqual(body.references, ["OEBPS/Text/S1_01-01_Chapter1.xhtml"] * 2)
        self.assertEqual(body.pages, ["S1_01-01"])

    def test_layout_is_derived_from_real_dimensions(self):
        """collect_book 不解码图片；尺寸与单双页类别由 feature() 首次读取时写入。"""
        write_png(self.book / "OEBPS/Images/S1_01-i-011.jpg", size=(300, 120))
        self._page("S1_01-01_Chapter1.xhtml", '<p><img src="../Images/S1_01-i-011.jpg"/></p>')
        asset_row = {a.name: a for a in collect_book(self.book)}["S1_01-i-011.jpg"]
        self.assertIsNone(asset_row.width)                      # 收集阶段不解码
        feature(asset_row)
        self.assertEqual((asset_row.width, asset_row.height), (300, 120))
        self.assertEqual(asset_row.layout, "double_page_candidate")
        self.assertIsNone(asset_row.decode_error)

    def test_undecodable_image_records_decode_error(self):
        broken = self.book / "OEBPS/Images/S1_01-i-099.jpg"
        broken.write_bytes(b"not an image")
        asset_row = {a.name: a for a in collect_book(self.book)}["S1_01-i-099.jpg"]
        self.assertIsNone(feature(asset_row))
        self.assertIsNotNone(asset_row.decode_error)


class CompareBookTests(unittest.TestCase):
    def test_identical_bytes_match_by_hash(self):
        matches, cn_only, jp_only = compare_book(
            [asset("S1_01-cover.jpg", sha256="same")],
            [asset("S1_01-cover.jpg", sha256="same")])
        self.assertEqual([m.kind for m in matches], ["exact_bytes_same_name"])
        self.assertEqual((cn_only, jp_only), ([], []))

    def test_identical_bytes_with_different_name_is_flagged(self):
        matches, _, _ = compare_book([asset("S1_01-cover.jpg", sha256="same")],
                                     [asset("S1_01-cover-2.jpg", sha256="same")])
        self.assertEqual([m.kind for m in matches], ["exact_bytes_name_different"])

    def test_unmatched_assets_are_reported_as_unpaired(self):
        matches, cn_only, jp_only = compare_book([asset("S1_01-cover.jpg", sha256="a")],
                                                 [asset("S1_01-cover.jpg", sha256="b")])
        self.assertEqual(matches, [])
        self.assertEqual([a.name for a in cn_only], ["S1_01-cover.jpg"])
        self.assertEqual([a.name for a in jp_only], ["S1_01-cover.jpg"])

    def test_double_page_asset_matches_two_consecutive_singles(self):
        """中文双页范围编号 ↔ 日文两张连续单页：合成一条对应记录并标记两张日文图。"""
        chinese = asset("S4_05-i-232-233.jpg", sha256="cn", layout="double_page_candidate")
        first = asset("S4_05-i-232.jpg", sha256="jp1", layout="single_page_candidate")
        second = asset("S4_05-i-233.jpg", sha256="jp2", layout="single_page_candidate")
        matches, cn_only, jp_only = compare_book([chinese], [first, second])
        self.assertEqual([m.kind for m in matches], ["name_rule_same_content"])
        self.assertEqual(matches[0].reason, "中文双页范围编号对应日文两张连续单页")
        self.assertEqual([a.name for a in matches[0].japanese_parts], ["S4_05-i-233.jpg"])
        self.assertEqual((cn_only, jp_only), ([], []))

    def test_double_page_skipped_when_a_part_is_missing(self):
        chinese = asset("S4_05-i-232-233.jpg", sha256="cn", layout="double_page_candidate")
        matches, cn_only, _ = compare_book([chinese], [asset("S4_05-i-232.jpg", sha256="jp1",
                                                            layout="single_page_candidate")])
        self.assertEqual(matches, [])
        self.assertEqual([a.name for a in cn_only], ["S4_05-i-232-233.jpg"])

    def test_name_rule_matches_before_perceptual_matching(self):
        """命名规则先于感知比对：位置族相同即配对，不要求像素相似。"""
        locations = ("family:illustration:1",)
        chinese = asset("S1_03-illustrations1.jpg", locations=locations, sha256="cn")
        japanese = asset("S1_03-kuchie-002.jpg", locations=locations, sha256="jp")
        matches, _, _ = compare_book([chinese], [japanese])
        self.assertEqual([m.kind for m in matches], ["name_rule_same_content"])
        self.assertIn("IllustrationsN/kuchie-(N+1)", matches[0].reason)
        self.assertIn("共同位置键", matches[0].reason)


class ScanReportTests(unittest.TestCase):
    def test_scan_pairs_books_and_reports_matches(self):
        """端到端：缓存下中日两本书按作品号配对，字节相同的封面进「精确字节匹配」。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        cache = Path(temporary.name) / "epub-work"
        chinese = cache / "chinese-text" / "[S1_01]测试书"
        japanese = cache / "japanese-text" / "[S1_01]テスト"
        write_png(chinese / "OEBPS/Images/S1_01-cover.jpg", size=(30, 40))
        write_png(japanese / "OEBPS/Images/S1_01-cover.jpg", size=(30, 40))
        for book, image in ((chinese, "S1_01-cover.jpg"), (japanese, "S1_01-cover.jpg")):
            page = book / "OEBPS/Text/S1_01-Cover.xhtml"
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(f'<html><body><img src="../Images/{image}"/></body></html>', encoding="utf-8")

        report = scan(cache, "*S1_01*")
        self.assertEqual(len(report["books"]), 1)
        entry = report["books"][0]
        self.assertEqual([m["classification"] for m in entry["matches"]], ["exact_bytes_same_name"])
        self.assertEqual(report["summary"]["paired_books"], 1)
        self.assertEqual(report["summary"]["matched_images"], 1)
        self.assertEqual(report["summary"]["missing_chinese"], 0)
        self.assertEqual(report["summary"]["missing_japanese"], 0)
        self.assertEqual(report["unpaired_books"], [])
        self.assertIn("精确字节匹配", render_markdown(report))

    def test_scan_reports_unpaired_book(self):
        """只有中文侧时进 unpaired_books，不伪造匹配。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        cache = Path(temporary.name) / "epub-work"
        chinese = cache / "chinese-text" / "[S1_01]测试书"
        write_png(chinese / "OEBPS/Images/S1_01-cover.jpg", size=(30, 40))
        (cache / "japanese-text").mkdir(parents=True)
        report = scan(cache, "*S1_01*")
        self.assertEqual(report["books"], [])
        self.assertEqual([row["book"] for row in report["unpaired_books"]], ["[S1_01]测试书"])


if __name__ == "__main__":
    unittest.main()
