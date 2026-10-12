from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from epub_structure import (  # noqa: E402
    ManifestItem, OpfRelations, ResourceReference, SpineItemref,
    artifact_contract_issues, container_contract_issues, css_references,
    opf_relations, resolve_reference, xml_references,
)


class ResourceReferenceTests(unittest.TestCase):
    def test_xml_preserves_order_namespace_raw_values_and_duplicates(self):
        root = ET.fromstring(
            '<root xmlns:x="urn:test" href="  a%20b.xhtml#note  " data-src="ignored">'
            '<image x:href="same.svg" src="same.svg" poster="poster.png" '
            'full-path="OEBPS/content.opf" style="url(ignored.png)"/></root>'
        )
        self.assertEqual(xml_references(root, attribute_case="lower"), (
            ResourceReference("  a%20b.xhtml#note  ", False),
            ResourceReference("same.svg", False),
            ResourceReference("same.svg", False),
            ResourceReference("poster.png", False),
            ResourceReference("OEBPS/content.opf", True),
        ))

    def test_xml_keeps_the_callers_attribute_case_difference(self):
        # Element 输入可直接带任意属性名；不把解析器拒绝的名称冒充合法 XML。
        root = ET.Element("root", {"SRC": "first", "\u017frc": "second"})
        self.assertEqual(xml_references(root, attribute_case="lower"), (
            ResourceReference("first", False),
        ))
        self.assertEqual(xml_references(root, attribute_case="casefold"), (
            ResourceReference("first", False), ResourceReference("second", False),
        ))

    def test_collection_does_not_resolve_or_filter_urls(self):
        root = ET.fromstring('<root href="http://[invalid" src="#note"/>')
        self.assertEqual(xml_references(root, attribute_case="lower"), (
            ResourceReference("http://[invalid", False), ResourceReference("#note", False),
        ))
        self.assertEqual(css_references(b'body { background:url("http://[invalid"); }'), (
            ResourceReference("http://[invalid", False),
        ))
        with self.assertRaises(ValueError):
            resolve_reference("chapter.xhtml", "http://[invalid")

    def test_css_ignores_comments_and_keeps_url_then_import_order(self):
        data = (b'/* url(ignored.png) \xff */ @import "first.css"; '
                b'body { background:URL("same font.woff"); src:url(same font.woff); } '
                b"@IMPORT 'last.css';")
        self.assertEqual(css_references(data), (
            ResourceReference("same font.woff", False),
            ResourceReference("same font.woff", False),
            ResourceReference("first.css", False),
            ResourceReference("last.css", False),
        ))

    def test_css_keeps_strict_decode_errors_inside_and_outside_urls(self):
        for data in (b'body { background:url("\xff"); }', b'body {} \xff'):
            with self.subTest(data=data), self.assertRaises(UnicodeDecodeError):
                css_references(data)

    def test_resolution_keeps_paths_fragments_and_external_urls_distinct(self):
        source = "OEBPS/Text/chapter.xhtml"
        for value, root_relative, expected in (
            (" ../Images/a%20b.svg#note ", False, "OEBPS/Images/a b.svg"),
            (r"..\Images\a.svg", False, "OEBPS/Images/a.svg"),
            ("OEBPS/content.opf", True, "OEBPS/content.opf"),
            ("/OEBPS/content.opf", False, "OEBPS/content.opf"),
            ("#note", False, None),
            ("", False, None),
            ("https://example.invalid/a.svg", False, None),
            ("//example.invalid/a.svg", False, None),
        ):
            with self.subTest(value=value, root_relative=root_relative):
                self.assertEqual(resolve_reference(source, value, root_relative=root_relative), expected)


class ArtifactReferenceContractTests(unittest.TestCase):
    def test_artifact_includes_htm_and_casefolded_attributes(self):
        issues = artifact_contract_issues({
            "META-INF/container.xml": b"<container/>",
            "chapter.htm": b'<html><img src="first.dat"/></html>',
            "chapter.xhtml": b'<html><img SRC="second.dat"/></html>',
        }, None)
        self.assertEqual(issues, [
            ("chapter.htm", "资源引用不存在：first.dat -> first.dat"),
            ("chapter.xhtml", "资源引用不存在：second.dat -> second.dat"),
        ])

    def test_invalid_xml_is_reported_and_next_file_is_checked(self):
        issues = artifact_contract_issues({
            "META-INF/container.xml": b"<container/>",
            "broken.xhtml": b"<html>",
            "next.xhtml": b'<html src="missing.dat"/>',
        }, None)
        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0][0], "broken.xhtml")
        self.assertTrue(issues[0][1].startswith("XML 解析失败："))
        self.assertEqual(issues[1], ("next.xhtml", "资源引用不存在：missing.dat -> missing.dat"))

    def test_fragment_validation_remains_outside_artifact_contract(self):
        self.assertEqual(artifact_contract_issues({
            "META-INF/container.xml": b"<container/>",
            "chapter.xhtml": b'<html href="#missing"/>',
        }, None), [])

    def test_diagnostics_keep_resource_opf_and_file_order(self):
        issues = artifact_contract_issues({
            "META-INF/container.xml": b"<container/>",
            "content.opf": (b'<package><manifest><item id="chapter" href="missing.xhtml"/>'
                            b'</manifest><spine><itemref idref="missing"/></spine></package>'),
            "style.css": b'@import "import.css"; body {background:url(image.dat);}',
            "next.xhtml": b'<html src="next.dat"/>',
        }, None)
        self.assertEqual(issues, [
            ("content.opf", "资源引用不存在：missing.xhtml -> missing.xhtml"),
            ("content.opf", "OPF spine idref 不存在于 manifest：missing"),
            ("style.css", "CSS 资源引用不存在：image.dat -> image.dat"),
            ("style.css", "CSS 资源引用不存在：import.css -> import.css"),
            ("next.xhtml", "资源引用不存在：next.dat -> next.dat"),
        ])

    def test_artifact_resolves_each_file_before_collecting_the_next(self):
        with self.assertRaises(ValueError):
            artifact_contract_issues({
                "META-INF/container.xml": b"<container/>",
                "first.xhtml": b'<html href=" http://[invalid"/>',
                "last.css": b"\xff",
            }, None)


class OpfRelationTests(unittest.TestCase):
    def test_direct_scope_uses_only_the_first_direct_sections(self):
        root = ET.fromstring(
            '<package xmlns="urn:opf"><metadata><item id="outside" href="outside.dat"/></metadata>'
            '<manifest><item id="first" href="first.dat" media-type="text/plain"/>'
            '<group><item id="nested" href="nested.dat"/></group></manifest>'
            '<manifest><item id="later" href="later.dat"/></manifest>'
            '<spine><itemref idref="first"/><group><itemref idref="nested"/></group></spine>'
            '<spine><itemref idref="later"/></spine></package>'
        )
        self.assertEqual(opf_relations(root, scope="direct", tag_case="exact"), OpfRelations(
            (ManifestItem("first", "first.dat", "text/plain"),),
            (SpineItemref("first"),),
        ))

    def test_descendants_keep_duplicates_empty_values_and_tag_case(self):
        root = ET.fromstring(
            '<package><metadata><item id="same" href="first.dat"/></metadata>'
            '<manifest><group><item id="same" href="second.dat"/></group>'
            '<ITEM id="upper" href="upper.dat"/><item/></manifest>'
            '<spine><itemref idref="same"/><ITEMREF idref="upper"/><itemref/></spine></package>'
        )
        self.assertEqual(opf_relations(root, scope="descendants", tag_case="casefold"), OpfRelations(
            (ManifestItem("same", "first.dat", ""), ManifestItem("same", "second.dat", ""),
             ManifestItem("upper", "upper.dat", ""), ManifestItem("", "", "")),
            (SpineItemref("same"), SpineItemref("upper"), SpineItemref("")),
        ))
        exact = opf_relations(root, scope="descendants", tag_case="exact")
        self.assertEqual([item.id for item in exact.items], ["same", "same", ""])
        self.assertEqual([ref.idref for ref in exact.itemrefs], ["same", ""])

    def test_xml_facts_use_precise_attributes_and_ignore_comments(self):
        root = ET.fromstring(
            "<o:package xmlns:o='urn:opf' xmlns:x='urn:attrs'>"
            "<!-- <item id='fake' href='fake.dat'/> -->"
            "<o:manifest><o:item data-id='wrong' x:id='wrong' id = 'real' "
            "data-href='wrong.dat' href = 'a&amp;b.dat'/></o:manifest>"
            "<o:spine><o:itemref data-idref='wrong' idref='real'/></o:spine></o:package>"
        )
        self.assertEqual(opf_relations(root, scope="direct", tag_case="exact"), OpfRelations(
            (ManifestItem("real", "a&b.dat", ""),), (SpineItemref("real"),),
        ))

    def test_results_copy_values_without_enforcing_opf_contracts(self):
        root = ET.fromstring('<other><manifest><item id="a" href="before"/></manifest></other>')
        result = opf_relations(root, scope="direct", tag_case="exact")
        root.find("manifest/item").set("href", "after")
        self.assertEqual(result, OpfRelations((ManifestItem("a", "before", ""),), ()))
        self.assertEqual(opf_relations(ET.fromstring("<other/>"), scope="direct", tag_case="exact"),
                         OpfRelations((), ()))

    def test_unknown_scope_or_tag_case_is_a_programming_error(self):
        root = ET.fromstring("<package/>")
        for scope, tag_case in (("all", "exact"), ("direct", "lower")):
            with self.subTest(scope=scope, tag_case=tag_case), self.assertRaises(ValueError):
                opf_relations(root, scope=scope, tag_case=tag_case)


class OpfCallerContractTests(unittest.TestCase):
    @staticmethod
    def entries(text: str, resources: tuple[str, ...] = ("a.xhtml", "b.dat")) -> dict[str, bytes]:
        result = {
            "mimetype": b"application/epub+zip",
            "META-INF/container.xml": (
                b'<container><rootfiles><rootfile full-path="OEBPS/content.opf"/>'
                b'</rootfiles></container>'),
            "OEBPS/content.opf": text.encode("utf-8"),
        }
        result.update(("OEBPS/" + name, b"<html/>" if name.endswith(".xhtml") else b"asset")
                      for name in resources)
        return result

    def test_container_keeps_last_media_type_for_duplicate_ids(self):
        entries = self.entries(
            '<package><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="a" href="b.dat" media-type="image/png"/></manifest>'
            '<spine><itemref idref="a"/></spine></package>'
        )
        self.assertEqual(container_contract_issues(entries), [
            ("OEBPS/content.opf", "无效或重复 manifest item：a"),
            ("OEBPS/content.opf", "spine 引用不存在或不是内容文档：a"),
        ])
        self.assertEqual(artifact_contract_issues(entries, None), [
            ("OEBPS/content.opf", "OPF manifest id 重复：a"),
        ])

    def test_artifact_keeps_image_targets_from_all_duplicate_items(self):
        entries = self.entries(
            '<package><manifest><item id="image" href="one.png" media-type="image/png"/>'
            '<item id="image" href="two.png" media-type="image/png"/></manifest>'
            '<spine><itemref idref="image"/></spine></package>', ("one.png", "two.png"),
        )
        self.assertEqual(artifact_contract_issues(entries, None), [
            ("OEBPS/content.opf", "OPF manifest id 重复：image"),
        ])

    def test_empty_ids_keep_the_callers_different_membership_rules(self):
        entries = self.entries(
            '<package><manifest><item href="a.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref/></spine></package>'
        )
        self.assertEqual(container_contract_issues(entries), [
            ("OEBPS/content.opf", "无效或重复 manifest item："),
        ])
        self.assertEqual(artifact_contract_issues(entries, None), [
            ("OEBPS/content.opf", "OPF spine idref 不存在于 manifest："),
        ])

    def test_missing_href_is_only_blocked_by_the_container_contract(self):
        entries = self.entries(
            '<package><manifest><item id="a" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="a"/></spine></package>'
        )
        self.assertEqual(container_contract_issues(entries), [
            ("OEBPS/content.opf", "无效或重复 manifest item：a"),
            ("OEBPS/content.opf", "manifest 资源不存在："),
        ])
        self.assertEqual(artifact_contract_issues(entries, None), [])

    def test_nested_later_and_uppercase_sections_keep_different_scopes(self):
        for manifest, spine, errors in (
            ('<manifest><group><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/>'
             '</group></manifest>', '<spine><itemref idref="a"/></spine>', [
                 ("OEBPS/content.opf", "OPF 缺少非空 manifest/spine"),
                 ("OEBPS/content.opf", "spine 引用不存在或不是内容文档：a"),
             ]),
            ('<manifest/><manifest><item id="a" href="a.xhtml" '
             'media-type="application/xhtml+xml"/></manifest>', '<spine><itemref idref="a"/></spine>', [
                 ("OEBPS/content.opf", "OPF 缺少非空 manifest/spine"),
                 ("OEBPS/content.opf", "spine 引用不存在或不是内容文档：a"),
             ]),
            ('<MANIFEST><ITEM id="a" href="a.xhtml" media-type="application/xhtml+xml"/></MANIFEST>',
             '<SPINE><ITEMREF idref="a"/></SPINE>', [
                 ("OEBPS/content.opf", "OPF 缺少非空 manifest/spine"),
             ]),
        ):
            with self.subTest(manifest=manifest):
                entries = self.entries("<package>" + manifest + spine + "</package>")
                self.assertEqual(container_contract_issues(entries), errors)
                self.assertEqual(artifact_contract_issues(entries, None), [])

    def test_invalid_xml_keeps_each_error_message_and_continues(self):
        entries = self.entries("<package>")
        entries["META-INF/container.xml"] = (
            b'<container><rootfiles><rootfile full-path="OEBPS/content.opf"/>'
            b'<rootfile full-path="OEBPS/second.opf"/></rootfiles></container>')
        entries["OEBPS/second.opf"] = (
            b'<package><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/>'
            b'</manifest><spine><itemref idref="a"/></spine></package>')
        container = container_contract_issues(entries)
        artifact = artifact_contract_issues(entries, None)
        self.assertEqual(len(container), 1)
        self.assertEqual(container[0][0], "OEBPS/content.opf")
        self.assertTrue(container[0][1].startswith("无法解析 OPF："))
        self.assertEqual(len(artifact), 1)
        self.assertEqual(artifact[0][0], "OEBPS/content.opf")
        self.assertTrue(artifact[0][1].startswith("XML 解析失败："))


if __name__ == "__main__":
    unittest.main()
