from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_cache_epubs import PackageError, package_book, validate_book


def make_book(book: Path, text: str = "<p>正文</p>", *, layout: bool = False) -> Path:
    """最小成品：容器 + 包文档 + 正文 + 构成必备件（`docs/epub-artifact-spec.md`）。

    `dc:title` 等于书目录名，导航与封面／制作信息页齐备——发布预检会把成品构成的
    error 级纳入阻断，夹具不满足它就跑不出「成功发布」路径。
    """
    wid = book.name.split("]")[0].lstrip("[") if book.name.startswith("[") else "S1_01"
    (book / "META-INF").mkdir(parents=True, exist_ok=True)
    (book / "OEBPS" / "Text").mkdir(parents=True, exist_ok=True)
    (book / "mimetype").write_bytes(b"application/epub+zip")
    (book / "META-INF/container.xml").write_text(
        '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>', encoding="utf-8")
    items = [
        f'<item id="cover" href="Text/{wid}-Cover.xhtml" media-type="application/xhtml+xml"/>',
        f'<item id="info" href="Text/{wid}-Information.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="chapter" href="Text/S1_01-01_Chapter.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="nav" href="../nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="../toc.ncx" media-type="application/x-dtbncx+xml"/>',
    ]
    if layout:
        from docx2epub import _CSS
        (book / "OEBPS/style.css").write_text(_CSS, encoding="utf-8")
        items.append('<item id="css" href="style.css" media-type="text/css"/>')
    (book / "OEBPS/content.opf").write_text(
        '<package><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:title id="id">{book.name}</dc:title>'
        f'<dc:identifier id="BookId">uuid:test-{wid}</dc:identifier></metadata>'
        f'<manifest>{"".join(items)}</manifest>'
        '<spine toc="ncx"><itemref idref="cover"/><itemref idref="info"/>'
        '<itemref idref="chapter"/></spine></package>', encoding="utf-8")
    head = ["<?xml version='1.0' encoding='utf-8'?>", "<!DOCTYPE html>", "<html><head/><body>"]
    path = book / "OEBPS/Text/S1_01-01_Chapter.xhtml"
    path.write_text("\n".join(head + ["", "", text, "</body></html>"]), encoding="utf-8")
    for name, title in ((f"{wid}-Cover.xhtml", "封面"), (f"{wid}-Information.xhtml", "制作信息")):
        (book / "OEBPS/Text" / name).write_text(
            "\n".join(head + [f"<h1>{title}</h1>", "", f"<p>{title}</p>", "</body></html>"]),
            encoding="utf-8")
    (book / "nav.xhtml").write_text(
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<head><title>Navigation</title></head>'
        '<body><nav epub:type="toc"><ol>'
        f'<li><a href="OEBPS/Text/{wid}-Information.xhtml">制作信息</a></li>'
        '</ol></nav></body></html>', encoding="utf-8")
    (book / "toc.ncx").write_text(
        f'<ncx><docTitle><text>{book.name}</text></docTitle><navMap>'
        '<navPoint id="num_1" playOrder="1"><navLabel><text>制作信息</text></navLabel>'
        f'<content src="OEBPS/Text/{wid}-Information.xhtml"/></navPoint>'
        '</navMap></ncx>', encoding="utf-8")
    return path


class PackageContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.book = self.root / "[S1_01]测试"
        self.text = make_book(self.book)

    def test_valid_book_uses_stored_first_mimetype(self):
        dest = self.root / "out.epub"
        package_book(self.book, dest)
        with zipfile.ZipFile(dest) as archive:
            self.assertEqual(archive.infolist()[0].filename, "mimetype")
            self.assertEqual(archive.infolist()[0].compress_type, zipfile.ZIP_STORED)

    def test_bad_container_is_blocked_before_replacing_previous_output(self):
        (self.book / "META-INF/container.xml").write_text("<container/>", encoding="utf-8")
        dest = self.root / "out.epub"
        dest.write_bytes(b"previous")
        with self.assertRaises(PackageError):
            package_book(self.book, dest)
        self.assertEqual(dest.read_bytes(), b"previous")

    def test_bad_xml_and_missing_resource_are_rejected(self):
        for content in ("<html>", '<html><body><img src="missing.jpg"/></body></html>'):
            with self.subTest(content=content):
                self.text.write_text(content, encoding="utf-8")
                with self.assertRaises(PackageError):
                    validate_book(self.book)

    def test_invalid_spine_and_unprefixed_image_are_rejected(self):
        opf = self.book / "OEBPS/content.opf"
        good = opf.read_text(encoding="utf-8")
        opf.write_text(good.replace('idref="chapter"', 'idref="missing"'), encoding="utf-8")
        with self.assertRaises(PackageError):
            validate_book(self.book)
        opf.write_text(good, encoding="utf-8")
        (self.book / "OEBPS/cover.jpg").write_bytes(b"jpeg")
        with self.assertRaises(PackageError):
            validate_book(self.book)

    def test_css_url_and_import_references_are_rejected(self):
        css = self.book / "OEBPS/style.css"
        for content in ('body { background:url(missing.png); }', '@import "missing.css";'):
            with self.subTest(content=content):
                css.write_text(content, encoding="utf-8")
                with self.assertRaises(PackageError):
                    validate_book(self.book)


if __name__ == "__main__":
    unittest.main()
