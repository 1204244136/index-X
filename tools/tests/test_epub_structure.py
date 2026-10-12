from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from epub_structure import (  # noqa: E402
    ResourceReference, artifact_contract_issues, css_references,
    resolve_reference, xml_references,
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


if __name__ == "__main__":
    unittest.main()
