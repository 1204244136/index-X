from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from check_epub_validity import (  # noqa: E402
    CATEGORY_DESCRIPTIONS,
    STRUCTURAL_EXCLUDES,
    Target,
    check_target,
    classify,
    collect_targets,
    failure_issue,
    filter_results,
    issue_to_dict,
    keep_issue,
    main,
    message_signature,
    position_of,
    severity_of,
    split_categories,
    worker_configuration,
    write_json_report,
    write_text_report,
    write_tsv_report,
)


# ---------------------------------------------------------------------------
# 测试替身：calibre 的错误对象只需要 类名/level/name/line/col/__str__
# 类名必须可控——分类器读的就是 type(error).__name__。
# ---------------------------------------------------------------------------

def fake_issue(type_name: str, message: str, line: int | None = None,
               col: int | None = None, level: int | None = None,
               name: str = "OEBPS/Text/chapter.xhtml") -> object:
    attributes: dict[str, object] = {
        "name": name,
        "_message": message,
        "__str__": lambda self: self._message,
    }
    if line is not None:
        attributes["line"] = line
    if col is not None:
        attributes["col"] = col
    if level is not None:
        attributes["level"] = level
    return type(type_name, (), attributes)()


def make_book(root: Path, name: str = "book") -> Path:
    """在 root 下造一个最小书籍解包目录。"""
    book = root / name
    (book / "META-INF").mkdir(parents=True)
    (book / "mimetype").write_text("application/epub+zip", encoding="utf-8")
    (book / "META-INF" / "container.xml").write_text("<container/>", encoding="utf-8")
    (book / "OEBPS").mkdir()
    return book


class CollectTargetsTests(unittest.TestCase):
    def test_collects_epub_files_case_insensitively_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.epub"
            second = root / "second.EPUB"
            ignored = root / "notes.txt"
            for path in (first, second, ignored):
                path.touch()

            targets, warnings = collect_targets([root, first])

            self.assertEqual([target.path for target in targets],
                             sorted([first.resolve(), second.resolve()]))
            self.assertEqual(warnings, [])
            self.assertTrue(all(target.kind == "epub" for target in targets))

    def test_recursive_search_is_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()
            (nested / "book.epub").touch()

            shallow, _ = collect_targets([root])
            self.assertEqual(shallow, [])

            targets, _ = collect_targets([root], recursive=True)
            self.assertEqual([target.path for target in targets], [(nested / "book.epub").resolve()])

    def test_extracted_book_directories_are_targets(self) -> None:
        """EPUB/ 这类解包归档：每本书目录都含 mimetype 与 META-INF/container.xml。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = make_book(root, "[S1_01]某魔法的禁书目录 01X")
            other = make_book(root, "[S1_02]某魔法的禁书目录 02X")

            targets, warnings = collect_targets([root])

            self.assertEqual(warnings, [])
            self.assertEqual([(t.path, t.kind) for t in targets],
                             [(book.resolve(), "dir"), (other.resolve(), "dir")])

    def test_book_directory_passed_directly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            book = make_book(Path(temp_dir))
            targets, _ = collect_targets([book])
            self.assertEqual([(t.path, t.kind) for t in targets], [(book.resolve(), "dir")])

    def test_directory_without_book_markers_is_reported_not_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            half = Path(temp_dir) / "half"
            (half / "OEBPS").mkdir(parents=True)

            targets, warnings = collect_targets([half])

            self.assertEqual(targets, [])
            self.assertTrue(any("mimetype" in warning for warning in warnings))

    def test_missing_path_and_empty_directory_warn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            empty = root / "empty"
            empty.mkdir()

            targets, warnings = collect_targets([empty, root / "nope.txt", root / "ghost"])

            self.assertEqual(targets, [])
            self.assertEqual(len(warnings), 3)

    def test_pattern_filters_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_book(root, "[S1_01]甲")
            make_book(root, "[S3_01]乙")

            targets, _ = collect_targets([root], pattern="*S3_*")

            self.assertEqual([target.path.name for target in targets], ["[S3_01]乙"])

    def test_display_is_relative_inside_repo_and_absolute_outside(self) -> None:
        inside = Target(Path(__file__).resolve(), "epub")
        self.assertFalse(inside.display.startswith("C:"))
        self.assertIn("tools/tests/", inside.display)
        outside = Target(Path("C:/definitely/outside.epub"), "epub")
        self.assertEqual(outside.display, "C:/definitely/outside.epub")


class ClassifyTests(unittest.TestCase):
    def test_css_messages_split_into_style_and_syntax(self) -> None:
        self.assertEqual(classify("CSSError", "…:Unexpected empty block"), "css-empty-block")
        self.assertEqual(
            classify("CSSError", '…:Expected selector ".a" to come before selector ".b"'),
            "css-order",
        )
        self.assertEqual(
            classify("CSSError", '…:Unexpected duplicate selector ".a", first used at line 144'),
            "css-duplicate",
        )
        self.assertEqual(classify("CSSChecker", "…:Invalid property value"), "css-syntax")

    def test_structural_types_are_mapped(self) -> None:
        cases = {
            ("DanglingLink", "链接的资源'p-002.xhtml#toc-001'不存在"): "link",
            ("BadDestinationFragment", "链接指向了目标文件中不存在的位置"): "link",
            ("UnreferencedResource", "文件 x.css 没有被引用"): "resource",
            ("UnreferencedDoc", "文件 x.xhtml 没有被引用"): "resource",
            ("MissingNav", "导航文档缺失"): "nav",
            ("IncorrectIdref", 'idref="start"指向了未知的id'): "opf",
            ("XMLParseError", "not well-formed"): "xml",
            ("OPFError", "spine 引用了不存在的 item"): "opf",
            ("FontError", "missing font"): "font",
            ("ImageError", "corrupt raster image"): "image",
            ("EncodingError", "declared encoding is wrong"): "encoding",
            ("FilenameError", "invalid character in file name"): "filename",
            ("IDError", "duplicate id"): "ids",
            ("MarkupError", "html markup issue"): "markup",
            ("MimetypeError", "wrong mimetype"): "mimetype",
            ("EmptyFile", "empty file"): "empty-file",
            ("LargeHTMLFile", "file is too big"): "html-size",
        }
        for (type_name, message), expected in cases.items():
            with self.subTest(type_name=type_name):
                self.assertEqual(classify(type_name, message), expected)

    def test_unknown_type_falls_into_other_so_it_stays_visible(self) -> None:
        self.assertEqual(classify("BrandNewError", "something happened"), "other")

    def test_every_category_has_a_description(self) -> None:
        for category in set(CATEGORY_DESCRIPTIONS) | set(STRUCTURAL_EXCLUDES):
            self.assertIn(category, CATEGORY_DESCRIPTIONS)

    def test_style_categories_are_exactly_the_structural_exclusions(self) -> None:
        """样式风格类别必须同时出现在描述表与排除表里，避免两处漂移。"""
        for category in STRUCTURAL_EXCLUDES:
            self.assertIn("样式风格", CATEGORY_DESCRIPTIONS[category])


class SeverityAndPositionTests(unittest.TestCase):
    def test_level_maps_to_severity(self) -> None:
        self.assertEqual(severity_of(fake_issue("A", "x", level=1)), "INFO")
        self.assertEqual(severity_of(fake_issue("A", "x", level=2)), "WARN")
        self.assertEqual(severity_of(fake_issue("A", "x", level=3)), "ERROR")

    def test_unknown_level_falls_back_to_class_name_then_error(self) -> None:
        class WarningThing:
            def __str__(self) -> str:
                return "w"

        self.assertEqual(severity_of(WarningThing()), "WARN")
        self.assertEqual(severity_of(object()), "ERROR")

    def test_position_uses_attributes_first(self) -> None:
        self.assertEqual(position_of(fake_issue("A", "x", line=7, col=3)), (7, 3))

    def test_position_falls_back_to_trailing_parentheses(self) -> None:
        issue = fake_issue("CSSError", "CSSError:style.css (74, 8):Unexpected empty block")
        self.assertEqual(position_of(issue), (74, 8))

    def test_position_is_none_when_not_available(self) -> None:
        self.assertEqual(position_of(fake_issue("A", "no coordinates here")), (None, None))


class IssueToDictTests(unittest.TestCase):
    def test_shape_carries_what_the_report_needs(self) -> None:
        issue = issue_to_dict(fake_issue("DanglingLink", "链接的资源'x'不存在",
                                        line=13, col=0, level=2))
        self.assertEqual(issue["severity"], "WARN")
        self.assertEqual(issue["category"], "link")
        self.assertEqual(issue["type"], "DanglingLink")
        self.assertEqual(issue["line"], 13)
        self.assertEqual(issue["column"], 0)
        json.dumps(issue, ensure_ascii=False)

    def test_failure_issue_is_a_structural_container_error(self) -> None:
        issue = failure_issue("FileNotFoundError: x")
        self.assertEqual(issue["severity"], "ERROR")
        self.assertEqual(issue["category"], "container")


class FilterTests(unittest.TestCase):
    def results(self) -> list[dict[str, object]]:
        return [{
            "path": "book",
            "kind": "dir",
            "issue_count": 3,
            "failed": False,
            "seconds": 0.1,
            "issues": [
                issue_to_dict(fake_issue("CSSError", "…:Unexpected empty block", level=3)),
                issue_to_dict(fake_issue("CSSError", '…:Expected selector "a" to come before "b"',
                                        level=3)),
                issue_to_dict(fake_issue("DanglingLink", "链接的资源'x'不存在", level=2)),
            ],
        }]

    def test_min_severity_accepts_lowercase_choices(self) -> None:
        """回归：--min-severity 是小写入参，早先直接查大写键会 KeyError。"""
        expected = {"info": 3, "warn": 3, "error": 2}  # 两个 ERROR + 一个 WARN
        for level, count in expected.items():
            with self.subTest(level=level):
                filtered = filter_results(self.results(), level, set())
                self.assertEqual(len(filtered[0]["issues"]), count)

    def test_structural_excludes_style_categories(self) -> None:
        filtered = filter_results(self.results(), "info", set(STRUCTURAL_EXCLUDES))
        kept = [issue["category"] for issue in filtered[0]["issues"]]
        self.assertEqual(kept, ["link"])
        self.assertEqual(filtered[0]["issue_count"], 1)
        self.assertEqual(filtered[0]["total_issue_count"], 3)

    def test_failed_book_issue_is_kept_by_every_filter(self) -> None:
        issue = failure_issue("boom")
        self.assertTrue(keep_issue(issue, "error", set(STRUCTURAL_EXCLUDES)))
        self.assertTrue(keep_issue(issue, "info", set()))

    def test_unknown_severity_is_treated_as_error_not_dropped(self) -> None:
        issue = {"severity": "MYSTERY", "category": "other", "type": "T", "message": "m"}
        self.assertTrue(keep_issue(issue, "error", set()))


class MessageSignatureTests(unittest.TestCase):
    def test_paths_and_numbers_are_collapsed(self) -> None:
        first = message_signature({"message": "CSSError:OEBPS/Styles/a.css (74, 8):Unexpected empty block"})
        second = message_signature({"message": "CSSError:OEBPS/Styles/b.css (9, 1):Unexpected empty block"})
        self.assertEqual(first, second)
        self.assertIn("Unexpected empty block", first)

    def test_selector_variants_collapse_but_keep_the_shape(self) -> None:
        first = message_signature({"message": 'CSSError:x.css (1, 0):Expected selector ".vrtl .measure-1em" to come before selector ".vrtl .hltr .measure-1em"'})
        second = message_signature({"message": 'CSSError:y.css (2, 0):Expected selector ".vrtl .measure-2em" to come before selector ".vrtl .hltr .measure-2em"'})
        self.assertEqual(first, second)


class WorkerConfigurationTests(unittest.TestCase):
    def test_automatic_configuration_limits_outer_processes(self) -> None:
        self.assertEqual(worker_configuration(20, None, available_cpus=16), 4)
        self.assertEqual(worker_configuration(2, None, available_cpus=16), 2)
        self.assertEqual(worker_configuration(20, None, available_cpus=2), 1)

    def test_requested_jobs_are_limited_by_files_and_cpus(self) -> None:
        self.assertEqual(worker_configuration(20, 1, available_cpus=16), 1)
        self.assertEqual(worker_configuration(3, 20, available_cpus=16), 3)
        self.assertEqual(worker_configuration(20, 20, available_cpus=4), 4)


class SplitCategoriesTests(unittest.TestCase):
    def test_accepts_repeats_and_commas(self) -> None:
        self.assertEqual(split_categories(["a,b", " c ", ""]), ["a", "b", "c"])


class CheckTargetTests(unittest.TestCase):
    def test_uses_and_removes_a_temporary_directory(self) -> None:
        seen: dict[str, Path] = {}

        def get_container(path: str, tdir: str | None = None) -> object:
            seen["tdir"] = Path(tdir)
            (seen["tdir"] / "extracted.xhtml").write_text("x", encoding="utf-8")
            return object()

        def run_checks(container: object) -> list[object]:
            self.assertTrue(seen["tdir"].is_dir())
            return []

        result = check_target(Target(Path("book.epub"), "epub"), get_container, run_checks)

        self.assertEqual(result["issue_count"], 0)
        self.assertFalse(result["failed"])
        self.assertFalse(seen["tdir"].exists())

    def test_extracted_directory_targets_need_no_unpack_directory(self) -> None:
        """解包目录本身就是容器：不应传 tdir，否则 calibre 会尝试解包目录。"""
        calls: list[tuple[str, object]] = []

        def get_container(path: str, tdir: str | None = None) -> object:
            calls.append((path, tdir))
            return object()

        check_target(Target(Path("EPUB/book"), "dir"), get_container, lambda container: [])

        self.assertEqual(calls, [(str(Path("EPUB/book")), None)])

    def test_container_failure_becomes_one_container_issue(self) -> None:
        def get_container(path: str, tdir: str | None = None) -> object:
            raise ValueError("broken epub")

        result = check_target(Target(Path("book.epub"), "epub"), get_container, lambda c: [])

        self.assertEqual(result["issue_count"], 1)
        self.assertTrue(result["failed"])
        self.assertEqual(result["issues"][0]["category"], "container")
        self.assertIn("broken epub", result["issues"][0]["message"])

    def test_check_failure_is_contained_and_keeps_working_books(self) -> None:
        def run_checks(container: object) -> list[object]:
            raise RuntimeError("calibre exploded")

        result = check_target(Target(Path("book.epub"), "epub"),
                              lambda path, tdir=None: object(), run_checks)

        self.assertTrue(result["failed"])
        self.assertEqual(result["issues"][0]["type"], "CheckFailure")

    def test_issues_are_converted_for_the_report(self) -> None:
        issues = [fake_issue("DanglingLink", "链接的资源'x'不存在", line=3, level=2)]
        result = check_target(Target(Path("book.epub"), "epub"),
                              lambda path, tdir=None: object(), lambda container: issues)
        self.assertEqual(result["issue_count"], 1)
        self.assertEqual(result["issues"][0]["category"], "link")


class ReportTests(unittest.TestCase):
    def results(self) -> list[dict[str, object]]:
        issue = issue_to_dict(fake_issue("CSSError", "…:Unexpected empty block",
                                        line=12, col=8, level=2))
        issue["file"] = "OEBPS/Text/chapter.xhtml"
        return [{"path": "EPUB/book", "kind": "dir", "issue_count": 1,
                 "total_issue_count": 1, "failed": False, "seconds": 0.5, "issues": [issue]}]

    def test_text_report_lists_location_and_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "nested" / "report.txt"
            write_text_report(self.results(), report, "header")
            content = report.read_text(encoding="utf-8")

        self.assertIn("Targets checked: 1", content)
        self.assertIn("OEBPS/Text/chapter.xhtml:12:8", content)
        self.assertIn("Unexpected empty block", content)

    def test_json_report_is_parseable_and_keeps_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "report.json"
            write_json_report(self.results(), report, "header")
            payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(payload["targets"], 1)
        self.assertEqual(payload["results"][0]["issues"][0]["category"], "css-empty-block")

    def test_tsv_report_has_header_and_one_row_per_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "report.tsv"
            write_tsv_report(self.results(), report)
            lines = report.read_text(encoding="utf-8").splitlines()

        self.assertEqual(lines[0].split("\t")[:4], ["book", "severity", "category", "type"])
        self.assertEqual(len(lines), 2)
        self.assertIn("css-empty-block", lines[1])


class MainEntryTests(unittest.TestCase):
    def test_list_categories_exits_zero(self) -> None:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--list-categories"]), 0)

    def test_missing_targets_is_a_setup_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            empty = Path(temp_dir) / "empty"
            empty.mkdir()
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(empty)]), 2)

    def test_worker_batch_requires_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            batch = Path(temp_dir) / "batch.json"
            batch.write_text("[]", encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--worker-batch", str(batch)]), 2)


if __name__ == "__main__":
    unittest.main()
