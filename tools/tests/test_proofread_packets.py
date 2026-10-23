from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import proofread_packets as packets


class Fixture:
    def __init__(self, base: Path, rows: list[dict] | None = None):
        self.root = base / "review-run"
        self.cn = base / "cn-source"
        self.jp = base / "jp-source"
        self.root.mkdir(parents=True)
        self.cn.mkdir()
        self.jp.mkdir()
        self.rows = rows or [self.row()]
        for row in self.rows:
            header = packets.header_of(row["file"])
            cn = self.cn / row["file"]
            jp = self.jp / (header + ".xhtml")
            if not cn.exists():
                cn.write_text("<html>\n<body>\n<p>新甲</p>\n<p>新乙</p>\n</body>\n</html>\n", encoding="utf-8")
            if not jp.exists():
                jp.write_text("<html>\n<body>\n<p><ruby>不幸<rt>ふこう</rt></ruby>だ。</p>\n"
                              "<p>次の文。</p>\n</body>\n</html>\n", encoding="utf-8")
        self.write_changes()

    @staticmethod
    def row(**values) -> dict:
        return dict({"commit": "worktree", "work": "S1_01", "file": "S1_01-01_Chapter.xhtml",
                     "line": "3", "old": "旧甲", "new": "新甲", "grade": "local",
                     "flags": "ruby,risk"}, **values)

    def write_changes(self):
        with (self.root / "changes.tsv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.rows[0]), delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(self.rows)

    def init(self):
        return packets.initialize_manifest(self.root, apply=True)

    def plan(self, slices: list[dict] | None = None) -> Path:
        self.plan_path = self.root / "plan.json"
        slices = slices if slices is not None else [{"slice_id": "s01",
            "item_ids": [f"C{i:06d}" for i, row in enumerate(self.rows, 1) if row["grade"] != "spec"],
            "diff_lines": len(self.rows) * 2}]
        self.plan_path.write_text(json.dumps({"slices": slices}), encoding="utf-8")
        return self.plan_path

    def prepare(self, **kwargs):
        return packets.prepare_session(self.root, jp_base=self.jp, cn_base=self.cn,
                                       plan_path=self.plan_path, **kwargs)

    def freeze(self):
        self.init()
        self.plan()
        self.prepare(apply=True)
        return self

    def reseal_session(self, session: dict):
        data = (json.dumps(session, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (self.root / "session.json").write_bytes(data)
        (self.root / "session.sha256").write_text(hashlib.sha256(data).hexdigest() + "\n", encoding="ascii")


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="proofread-packets-")
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def fixture(self, rows=None, name="case"):
        base = self.base / name
        base.mkdir()
        return Fixture(base, rows)

    def test_init_preview_and_stable_quoted_tsv(self):
        f = self.fixture([Fixture.row(old='旧文\t"引号"\n第二行')])
        result = packets.initialize_manifest(f.root)
        self.assertFalse(result["applied"])
        self.assertFalse((f.root / "manifest.tsv").exists())
        f.init()
        manifest = packets.load_manifest(f.root)
        self.assertEqual(manifest[0]["item_id"], "C000001")
        self.assertEqual(manifest[0]["old"], f.rows[0]["old"])
        before = (f.root / "manifest.tsv").read_bytes()
        self.assertTrue(f.init()["reused"])
        self.assertEqual((f.root / "manifest.tsv").read_bytes(), before)

    def test_manifest_preserves_explicit_reclassification(self):
        f = self.fixture()
        f.init()
        path = f.root / "manifest.tsv"
        text = path.read_text(encoding="utf-8").replace("local\tlocal", "local\tspec")
        path.write_text(text, encoding="utf-8")
        self.assertEqual(f.init()["stats"]["grades"], {"spec": 1})
        f.plan([])
        session = f.prepare(apply=True)
        self.assertEqual(session["spec_ids"], ["C000001"])
        self.assertEqual(packets.load_session(f.root)["slices"], [])

    def test_prepare_preview_has_no_outputs_then_freezes_minimal_two_tracks(self):
        f = self.fixture()
        f.init()
        f.plan()
        session = f.prepare()
        self.assertFalse(session["applied"])
        self.assertFalse((f.root / "session.json").exists())
        self.assertFalse((f.root / "slices/packets").exists())
        f.prepare(apply=True)
        item = packets.load_packet(f.root, "s01")["items"][0]
        self.assertEqual(item["evidence"][0]["plain"], "不幸だ。")
        self.assertEqual(item["evidence"][0]["markup"], "|不幸[ふこう]だ。")
        self.assertEqual([row["line"] for row in item["context"]], [2, 4])
        self.assertEqual(item["context"][1]["cn"], "新乙")
        self.assertTrue((f.root / "session.sha256").is_file())
        self.assertEqual(len(packets.load_session(f.root)["source_files"]), 2)

    def test_no_overwrite_and_no_partial_write(self):
        f = self.fixture().freeze()
        before = (f.root / "session.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "禁止覆盖"):
            f.prepare(apply=True)
        self.assertEqual((f.root / "session.json").read_bytes(), before)

    def test_read_filter_page_and_render_do_not_modify_packets(self):
        f = self.fixture([Fixture.row(), Fixture.row(line="4", new="新乙", flags="other")]).freeze()
        packet_path = f.root / "slices/packets/s01.json"
        before = packet_path.read_bytes()
        data = packets.read_packet(f.root, "s01", page=2, page_size=1, context=0)
        self.assertEqual(data["items"][0]["item_id"], "C000002")
        self.assertEqual(data["items"][0]["context"], [])
        self.assertEqual(data["pages"], 2)
        data = packets.read_packet(f.root, "s01", flag="ruby")
        self.assertEqual(data["total"], 1)
        rendered = packets.render_packet(data)
        self.assertIn("底字: 不幸だ。", rendered)
        self.assertIn("注音: |不幸[ふこう]だ。", rendered)
        self.assertIn("CN: 新乙", rendered)
        self.assertEqual(packet_path.read_bytes(), before)

    def test_read_rejects_foreign_id_and_invalid_pagination(self):
        f = self.fixture().freeze()
        for kwargs in ({"item_ids": ["C999999"]}, {"page": 0}, {"page_size": True}, {"context": 2}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                packets.read_packet(f.root, "s01", **kwargs)

    def test_item_context_supplement_is_read_only_and_bounded(self):
        f = self.fixture().freeze()
        packet_path = f.root / "slices/packets/s01.json"
        before = packet_path.read_bytes()
        data = packets.source_context(f.root, "s01", "C000001", radius=2)
        self.assertEqual(data["item_id"], "C000001")
        self.assertEqual([row["line"] for row in data["context"]], [1, 2, 4, 5])
        self.assertEqual(set(data["source_files"]), {"jp:S1_01-01", "cn:S1_01-01"})
        self.assertEqual(data["evidence"][0]["plain"], "不幸だ。")
        self.assertEqual(packet_path.read_bytes(), before)
        self.assertFalse((f.root / "slices/context").exists())
        for kwargs in ({"radius": 0}, {"radius": 11}, {"radius": True}):
            with self.assertRaises(ValueError):
                packets.source_context(f.root, "s01", "C000001", **kwargs)
        with self.assertRaisesRegex(ValueError, "不属于本片"):
            packets.source_context(f.root, "s01", "C999999")

    def test_plan_requires_exact_unique_ownership(self):
        cases = [[], [{"slice_id": "s01", "item_ids": ["C000001", "C000001"]}],
                 [{"slice_id": "s01", "item_ids": ["C000002"]}],
                 [{"slice_id": "s01", "item_ids": ["C000001"]},
                  {"slice_id": "s02", "item_ids": ["C000001"]}],
                 [{"slice_id": "../escape", "item_ids": ["C000001"]}]]
        for index, plan in enumerate(cases):
            f = self.fixture(name=str(index))
            f.init()
            f.plan(plan)
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                f.prepare(apply=True)
            self.assertFalse((f.root / "session.json").exists())

    def test_id_text_plan_is_supported(self):
        f = self.fixture()
        f.init()
        target = f.root / "slices/ids/s01.txt"
        target.parent.mkdir(parents=True)
        target.write_text("# owned\nC000001\n", encoding="utf-8")
        result = packets.prepare_session(f.root, jp_base=f.jp, cn_base=f.cn)
        self.assertEqual(result["slices"][0]["item_ids"], ["C000001"])
        self.assertFalse(result["diff_budget_verified"])
        self.assertTrue(result["warnings"])

    def test_slice_ids_cannot_alias_on_case_insensitive_filesystems(self):
        f = self.fixture([Fixture.row(), Fixture.row(line="4", new="新乙")])
        f.init()
        f.plan([{"slice_id": "s01", "item_ids": ["C000001"]},
                {"slice_id": "S01", "item_ids": ["C000002"]}])
        with self.assertRaisesRegex(ValueError, "slice_id 无效或重复"):
            f.prepare(apply=True)
        self.assertFalse((f.root / "session.json").exists())

    def test_cn_actual_line_must_match_frozen_new_translation(self):
        f = self.fixture([Fixture.row(new="历史版本")])
        f.init()
        f.plan()
        with self.assertRaisesRegex(ValueError, "新译与中文源实际行不符"):
            f.prepare(apply=True)
        self.assertFalse((f.root / "session.json").exists())

    def test_pair_alignment_and_line_range_are_enforced(self):
        f = self.fixture()
        f.init()
        f.plan()
        jp = next(f.jp.glob("*.xhtml"))
        jp.write_text(jp.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"CN=6 JP=7.*-1"):
            f.prepare()
        f = self.fixture([Fixture.row(line="99")], name="range")
        f.init()
        f.plan()
        with self.assertRaisesRegex(ValueError, "行号越界"):
            f.prepare()

    def test_multiline_ruby_blocks_without_changing_line_basis(self):
        f = self.fixture()
        f.init()
        f.plan()
        jp = next(f.jp.glob("*.xhtml"))
        jp.write_text(jp.read_text(encoding="utf-8").replace("<body>", "<body><ruby>"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "跨物理行 ruby"):
            f.prepare()

    def test_only_relevant_headers_must_be_unique(self):
        f = self.fixture()
        f.init()
        f.plan()
        for name in ("a", "b"):
            unrelated = f.jp / name
            unrelated.mkdir()
            (unrelated / "S9_99-01.xhtml").write_text("ignored", encoding="utf-8")
        self.assertEqual(len(f.prepare()["slices"]), 1)
        (f.jp / "a/S1_01-01_duplicate.xhtml").write_text("duplicate", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "同侧重复表头"):
            f.prepare()

    def test_budgets_block_before_any_packet_write(self):
        f = self.fixture()
        f.init()
        f.plan()
        with self.assertRaisesRegex(ValueError, "超过预算"):
            f.prepare(max_input_chars=1, apply=True)
        self.assertFalse((f.root / "slices/packets").exists())
        f.plan([{"slice_id": "s01", "item_ids": ["C000001"], "diff_lines": 401}])
        with self.assertRaisesRegex(ValueError, "硬边界"):
            f.prepare()
        f.plan([{"slice_id": "s01", "item_ids": ["C000001"], "diff_lines": True}])
        with self.assertRaisesRegex(ValueError, "diff_lines 必须"):
            f.prepare()
        f = self.fixture([Fixture.row() for _ in range(151)], name="many")
        f.init()
        f.plan()
        with self.assertRaisesRegex(ValueError, "硬边界"):
            f.prepare()
        f = self.fixture([Fixture.row(file=f"S1_01-{i:02d}_Chapter.xhtml") for i in range(1, 5)], name="files")
        f.init()
        f.plan()
        with self.assertRaisesRegex(ValueError, "硬边界"):
            f.prepare()

    def test_every_frozen_input_is_checked_for_drift(self):
        for target in ("cn", "jp", "changes.tsv", "manifest.tsv", "slices/packets/s01.json", "session.json"):
            f = self.fixture(name=target.replace("/", "-")).freeze()
            if target in {"cn", "jp"}:
                path = next(getattr(f, target).glob("*.xhtml"))
            else:
                path = f.root / target
            path.write_bytes(path.read_bytes() + b" ")
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "已变化"):
                packets.load_packet(f.root, "s01")

    def test_even_resealed_session_cannot_drop_or_duplicate_ownership(self):
        f = self.fixture().freeze()
        session = packets.load_session(f.root)
        session["slices"] = []
        f.reseal_session(session)
        with self.assertRaisesRegex(ValueError, "ID 归属"):
            packets.load_session(f.root)

    def test_report_targets_reject_distribution_books_and_reference_cache(self):
        repo = self.base / "repo"
        repo.mkdir()
        report_base = repo / ".cache/epub-work/proofread-review"
        with mock.patch.object(packets, "REPO_ROOT", repo), mock.patch.object(packets, "REPORT_BASE", report_base):
            for path in (repo / "EPUB/report.json", repo / ".cache/epub-work/japanese-text/report.json",
                         repo / "OneDrive/review/report.json", repo / "【S1_01】Book/review/report.json",
                         report_base, repo):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    packets.require_report_target(path)
            self.assertEqual(packets.require_report_target(report_base / "new-run"), report_base / "new-run")
        book = self.base / "staged-book"
        book.mkdir()
        (book / "page.xhtml").write_text("<p>book</p>", encoding="utf-8")
        (book / "META-INF").mkdir()
        (book / "META-INF/container.xml").write_text("container", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "书籍源目录"):
            packets.require_report_target(book / "reports/file.json")

    def test_report_source_overlap_is_rejected(self):
        f = self.fixture()
        f.init()
        f.plan()
        with self.assertRaisesRegex(ValueError, "重叠"):
            packets.prepare_session(f.root, jp_base=f.jp, cn_base=f.root.parent, plan_path=f.plan_path)

    def test_atomic_artifacts_do_not_overwrite_and_rollback_only_new_files(self):
        first, second = self.base / "out/one.json", self.base / "out/two.json"
        packets.write_new_artifacts({first: b"one"})
        self.assertFalse(first.parent.exists())
        original_link = packets.os.link
        def fail_second(source, target):
            if target == second:
                second.write_bytes(b"concurrent")
                raise FileExistsError(str(second))
            return original_link(source, target)
        with mock.patch.object(packets.os, "link", side_effect=fail_second):
            with self.assertRaises(FileExistsError):
                packets.write_new_artifacts({first: b"one", second: b"two"}, apply=True)
        self.assertFalse(first.exists())
        self.assertEqual(second.read_bytes(), b"concurrent")
        self.assertEqual(list(first.parent.glob(".proofread-*")), [])
        with self.assertRaisesRegex(ValueError, "禁止覆盖"):
            packets.write_new_artifacts({second: b"replace"}, apply=True)
        self.assertEqual(second.read_bytes(), b"concurrent")


if __name__ == "__main__":
    unittest.main()
