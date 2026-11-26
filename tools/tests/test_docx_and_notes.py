from __future__ import annotations

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from docx2epub import (  # noqa: E402
    build_chapters,
    extract_source_images,
    render_content,
    render_cover,
    render_opf,
)
from notes_core import book_order_key, gather_refs  # noqa: E402


class DocxIntroTests(unittest.TestCase):
    def test_text_before_prologue_becomes_numbered_intro_unit(self):
        paragraphs = [
            {"idx": 0, "style": "Normal", "text": "引子正文", "imgs": [], "has_link": False},
            {"idx": 1, "style": "Heading 1", "text": "序章", "imgs": [], "has_link": False},
            {"idx": 2, "style": "Normal", "text": "序章正文", "imgs": [], "has_link": False},
        ]
        chapters, _, front_text, _ = build_chapters(paragraphs)
        self.assertEqual(front_text, ["引子正文"])
        self.assertEqual(chapters[0]["suffix"], "Before_the_Prologue")
        self.assertEqual(chapters[0]["title"], "")
        rendered = render_content(chapters[0], {})
        self.assertEqual(rendered.splitlines()[3], "")
        self.assertEqual(rendered.splitlines()[5], "<p>引子正文</p>")


class NoteOrderTests(unittest.TestCase):
    def test_order_uses_header_sequence(self):
        names = [
            "S5_01_03-10_Chapter1.xhtml",
            "S5_01_03-01_Introduction.xhtml",
            "S5_01_03-02_Chapter9.xhtml",
        ]
        ordered = sorted(names, key=lambda name: book_order_key(name, "S5_01_03-Note.xhtml"))
        self.assertEqual(ordered, [names[1], names[2], names[0]])

    def test_single_quoted_noteref_is_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "S1_01-01_Chapter1.xhtml").write_text(
                "<a epub:type='noteref' href='S1_01-Note.xhtml#note1'>注</a>",
                encoding="utf-8",
            )
            (root / "S1_01-Note.xhtml").write_text("<li id='note1'>注</li>", encoding="utf-8")
            appearance, refs = gather_refs(root, "S1_01-Note.xhtml")
            self.assertEqual(list(appearance), ["note1"])
            self.assertEqual(refs["note1"], [("S1_01-01_Chapter1.xhtml", 1)])


class DocxPackagingRegressionTests(unittest.TestCase):
    def test_cover_no_head_br_and_opf_includes_file_as_and_image_mime(self):
        cover = render_cover("S1_01-Cover.webp")
        head = cover.split("</head>", 1)[0]
        self.assertNotIn("<br", head)
        ET.fromstring(cover.encode("utf-8"))

        opf = render_opf(
            {"title": "【S1_01】测试书", "creator": "作者", "language": "zh-CN"},
            ["S1_01-01.xhtml"],
            ["S1_01-Cover.webp", "S1_01-i-001.svg"],
            "S1_01-Cover.webp",
            "1234",
        )
        self.assertIn('<meta refines="#id" property="file-as">【S1_01】测试书</meta>', opf)
        self.assertIn('media-type="image/webp"', opf)
        self.assertIn('media-type="image/svg+xml"', opf)
        ET.fromstring(opf.encode("utf-8"))

    def test_extract_source_images_resolves_relative_to_xhtml_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub_path = Path(tmp) / "src.epub"
            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr("META-INF/container.xml",
                            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                            'media-type="application/oebps-package+xml"/></rootfiles></container>')
                zf.writestr("OEBPS/content.opf",
                            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
                            '<manifest>'
                            '<item id="ch" href="Text/sub/ch01.xhtml" media-type="application/xhtml+xml"/>'
                            '<item id="img" href="Images/p1.png" media-type="image/png"/>'
                            '</manifest><spine><itemref idref="ch"/></spine></package>')
                zf.writestr("OEBPS/Text/sub/ch01.xhtml",
                            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head>'
                            '<body><p>正文段落</p><p><img src="../../Images/p1.png"/></p></body></html>')
                zf.writestr("OEBPS/Images/p1.png", b"PNGDATA")
            src = extract_source_images(epub_path, "S1_01")
            self.assertIn("S1_01-p1.png", src["images"])
            self.assertEqual(src["images"]["S1_01-p1.png"], b"PNGDATA")


if __name__ == "__main__":
    unittest.main()
