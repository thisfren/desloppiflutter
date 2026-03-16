"""Tests for desloppify.engine.detectors.test_coverage — test coverage gap detection."""

from __future__ import annotations

import math

import pytest

from desloppify.engine.detectors.coverage.mapping import (
    _map_test_to_source,
    _strip_test_markers,
    analyze_test_quality,
    get_test_files_for_prod,
    import_based_mapping,
    transitive_coverage,
)
from desloppify.engine.detectors.coverage.mapping_imports import (
    _infer_lang_name,
    _parse_test_imports,
)
from desloppify.engine.detectors.test_coverage.detector import detect_test_coverage
from desloppify.engine.detectors.test_coverage.io import (
    clear_coverage_read_warning_cache_for_tests,
)
from desloppify.engine.detectors.test_coverage.metrics import _file_loc
from desloppify.engine.policy.zones import FileZoneMap, Zone, ZoneRule

# ── Helpers ────────────────────────────────────────────────


def _make_zone_map(file_list: list[str]) -> FileZoneMap:
    """Build a minimal FileZoneMap with standard test-detection rules."""
    rules = [
        ZoneRule(Zone.TEST, ["test_", ".test.", ".spec.", "/tests/", "/__tests__/", "_test.dart", "/test/"])
    ]
    return FileZoneMap(file_list, rules)


def _write_file(tmp_path, relpath: str, content: str = "") -> str:
    """Write a file under tmp_path and return its absolute path."""
    p = tmp_path / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return str(p)


@pytest.fixture(autouse=True)
def _reset_read_warning_cache():
    clear_coverage_read_warning_cache_for_tests()
    yield
    clear_coverage_read_warning_cache_for_tests()


# ── _strip_test_markers ───────────────────────────────────


class TestStripTestMarkers:
    def test_dart_test_suffix(self):
        assert _strip_test_markers("utils_test.dart", "dart") == "utils.dart"

    def test_dart_no_marker(self):
        assert _strip_test_markers("utils.dart", "dart") is None

    def test_typescript_test_marker(self):
        assert _strip_test_markers("utils.test.ts", "typescript") == "utils.ts"

    def test_typescript_spec_tsx(self):
        assert _strip_test_markers("utils.spec.tsx", "typescript") == "utils.tsx"

    def test_typescript_no_marker(self):
        assert _strip_test_markers("utils.ts", "typescript") is None

    def test_typescript_spec_ts(self):
        assert _strip_test_markers("helpers.spec.ts", "typescript") == "helpers.ts"

    def test_dart_test_suffix_nested(self):
        assert _strip_test_markers("deep_module_test.dart", "dart") == "deep_module.dart"


# ── _infer_lang_name ──────────────────────────────────────


class TestInferLangName:
    def test_prefers_language_with_matching_extensions(self):
        result = _infer_lang_name({"test/utils_test.dart"}, {"lib/utils.dart"})
        assert result == "dart"

    def test_detects_typescript_from_ts_files(self):
        result = _infer_lang_name({"tests/http.test.ts"}, {"src/http.ts"})
        assert result == "typescript"

    def test_returns_none_when_no_languages_available(self, monkeypatch):
        monkeypatch.setattr("desloppify.languages.available_langs", lambda: [])
        result = _infer_lang_name(set(), set())
        assert result is None

    def test_returns_none_when_paths_have_no_known_extensions(self):
        result = _infer_lang_name({"docs/test_notes.txt"}, {"docs/notes.txt"})
        assert result is None


# ── _map_test_to_source ──────────────────────────────────


class TestMapTestToSource:
    def test_dart_test_suffix_same_dir(self):
        prod_set = {"lib/utils.dart"}
        result = _map_test_to_source("lib/utils_test.dart", prod_set, "dart")
        assert result == "lib/utils.dart"

    def test_dart_test_suffix_parent_dir(self):
        prod_set = {"lib/utils.dart"}
        result = _map_test_to_source("test/utils_test.dart", prod_set, "dart")
        assert result == "lib/utils.dart"

    def test_typescript_test_marker(self):
        prod_set = {"src/utils.ts"}
        result = _map_test_to_source("src/utils.test.ts", prod_set, "typescript")
        assert result == "src/utils.ts"

    def test_typescript_spec_marker(self):
        prod_set = {"src/utils.tsx"}
        result = _map_test_to_source("src/utils.spec.tsx", prod_set, "typescript")
        assert result == "src/utils.tsx"

    def test_typescript_tests_dir(self):
        prod_set = {"src/utils.ts"}
        result = _map_test_to_source("src/__tests__/utils.ts", prod_set, "typescript")
        assert result == "src/utils.ts"

    def test_no_match_returns_none(self):
        prod_set = {"lib/other.dart"}
        result = _map_test_to_source("test/utils_test.dart", prod_set, "dart")
        assert result is None

    def test_no_match_typescript(self):
        prod_set = {"src/other.ts"}
        result = _map_test_to_source("src/utils.test.ts", prod_set, "typescript")
        assert result is None


# ── _file_loc ─────────────────────────────────────────────


class TestFileLoc:
    def test_counts_lines(self, tmp_path):
        path = _write_file(tmp_path, "sample.py", "line1\nline2\nline3\n")
        assert _file_loc(path) == 3

    def test_empty_file(self, tmp_path):
        path = _write_file(tmp_path, "empty.py", "")
        assert _file_loc(path) == 0

    def test_nonexistent_file(self):
        assert _file_loc("/nonexistent/path/file.py") == 0

    def test_single_line_no_newline(self, tmp_path):
        path = _write_file(tmp_path, "one.py", "hello")
        assert _file_loc(path) == 1


# ── _import_based_mapping ────────────────────────────────


class TestImportBasedMapping:
    def test_test_imports_production(self):
        graph = {
            "test/foo_test.dart": {"imports": {"lib/foo.dart", "lib/bar.dart"}},
        }
        test_files = {"test/foo_test.dart"}
        production_files = {"lib/foo.dart", "lib/bar.dart", "lib/baz.dart"}
        result = import_based_mapping(graph, test_files, production_files)
        assert result == {"lib/foo.dart", "lib/bar.dart"}

    def test_test_imports_non_production_excluded(self):
        graph = {
            "test/foo_test.dart": {"imports": {"external_lib"}},
        }
        test_files = {"test/foo_test.dart"}
        production_files = {"lib/foo.dart"}
        result = import_based_mapping(graph, test_files, production_files)
        assert result == set()

    def test_test_not_in_graph_skipped(self):
        graph = {}
        test_files = {"test/foo_test.dart"}
        production_files = {"lib/foo.dart"}
        # The test file isn't in graph, so it falls through to _parse_test_imports
        # which tries to read the file — nonexistent file returns empty set
        result = import_based_mapping(graph, test_files, production_files)
        assert result == set()

    def test_external_test_file_parsed(self, tmp_path):
        """External test files not in graph are parsed from source.

        _import_based_mapping builds prod_by_module from absolute paths, so
        the test import must reference the last component of the production
        module name (basename without extension) which is also indexed.
        """
        (tmp_path / "pubspec.yaml").write_text("name: myapp\n")
        (tmp_path / "lib").mkdir(exist_ok=True)
        prod_file = _write_file(tmp_path, "lib/utils.dart", "// production code\n" * 15)
        # Import "utils" — _import_based_mapping indexes basename "utils" → prod_file
        test_file = _write_file(
            tmp_path,
            "external_tests/utils_test.dart",
            "import 'package:myapp/utils.dart';\nvoid main() { test('it', () { expect(true, isTrue); }); }\n",
        )
        graph = {}
        test_files = {test_file}
        production_files = {prod_file}
        result = import_based_mapping(graph, test_files, production_files, "dart")
        assert prod_file in result

    def test_multiple_test_files(self):
        graph = {
            "test/a_test.dart": {"imports": {"lib/a.dart"}},
            "test/b_test.dart": {"imports": {"lib/b.dart"}},
        }
        test_files = {"test/a_test.dart", "test/b_test.dart"}
        production_files = {"lib/a.dart", "lib/b.dart", "lib/c.dart"}
        result = import_based_mapping(graph, test_files, production_files)
        assert result == {"lib/a.dart", "lib/b.dart"}

    def test_typescript_parses_dynamic_imports_even_when_graph_entry_exists(self, tmp_path):
        prod_file = _write_file(tmp_path, "src/utils.ts", "export const x = 1;\n")
        test_file = _write_file(
            tmp_path,
            "src/utils.test.ts",
            (
                'test("loads", async () => {\n'
                "  await import('./utils');\n"
                "  expect(true).toBe(true);\n"
                "});\n"
            ),
        )
        graph = {
            test_file: {"imports": set()},
            prod_file: {"imports": set(), "importer_count": 0},
        }
        result = import_based_mapping(graph, {test_file}, {prod_file}, "typescript")
        assert prod_file in result


# ── _parse_test_imports ──────────────────────────────────


class TestParseTestImports:
    def test_dart_import(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: myapp\n")
        lib = tmp_path / "lib"
        lib.mkdir()
        prod = _write_file(tmp_path, "lib/utils.dart", "int foo() => 1;\n")
        tf = _write_file(tmp_path, "test/utils_test.dart", "import 'package:myapp/utils.dart';\n")
        prod_set = {prod}
        prod_by_module = {"utils": prod}
        result = _parse_test_imports(tf, prod_set, prod_by_module, "dart")
        assert prod in result

    def test_ts_import(self, tmp_path):
        tf = _write_file(tmp_path, "test_x.ts", 'import { foo } from "./utils"\n')
        prod = {str(tmp_path / "utils.ts")}
        prod_by_module = {"utils": str(tmp_path / "utils.ts")}
        result = _parse_test_imports(tf, prod, prod_by_module)
        assert str(tmp_path / "utils.ts") in result

    def test_nonexistent_file(self):
        result = _parse_test_imports("/no/such/file.dart", set(), {})
        assert result == set()


class TestGetTestFilesForProd:
    def test_typescript_dynamic_import_parsed_with_existing_graph_entry(self, tmp_path):
        prod_file = _write_file(tmp_path, "src/a.ts", "export const a = 1;\n")
        test_file = _write_file(
            tmp_path,
            "src/moduleCoverage.test.ts",
            (
                "it('imports module', async () => {\n"
                "  await import('./a');\n"
                "  await expect(import('./a')).resolves.toBeDefined();\n"
                "});\n"
            ),
        )
        graph = {test_file: {"imports": set()}}
        related = get_test_files_for_prod(prod_file, {test_file}, graph, "typescript")
        assert test_file in related


# ── _transitive_coverage ─────────────────────────────────


class TestTransitiveCoverage:
    def test_bfs_chain(self):
        """A→B→C: if A is directly tested, B and C are transitively tested."""
        graph = {
            "a.py": {"imports": {"b.py"}},
            "b.py": {"imports": {"c.py"}},
            "c.py": {"imports": set()},
        }
        production = {"a.py", "b.py", "c.py"}
        directly_tested = {"a.py"}
        result = transitive_coverage(directly_tested, graph, production)
        assert result == {"b.py", "c.py"}

    def test_stops_at_non_production(self):
        """BFS stops at files not in production set."""
        graph = {
            "a.py": {"imports": {"b.py", "vendor/lib.py"}},
            "b.py": {"imports": set()},
        }
        production = {"a.py", "b.py"}
        directly_tested = {"a.py"}
        result = transitive_coverage(directly_tested, graph, production)
        assert "vendor/lib.py" not in result
        assert result == {"b.py"}

    def test_excludes_directly_tested(self):
        """Directly tested files should NOT appear in transitive result."""
        graph = {
            "a.py": {"imports": {"b.py"}},
            "b.py": {"imports": set()},
        }
        production = {"a.py", "b.py"}
        directly_tested = {"a.py"}
        result = transitive_coverage(directly_tested, graph, production)
        assert "a.py" not in result
        assert result == {"b.py"}

    def test_empty_graph(self):
        result = transitive_coverage({"a.py"}, {}, {"a.py", "b.py"})
        assert result == set()

    def test_diamond_dependency(self):
        """A→B, A→C, B→D, C→D: D should only appear once."""
        graph = {
            "a.py": {"imports": {"b.py", "c.py"}},
            "b.py": {"imports": {"d.py"}},
            "c.py": {"imports": {"d.py"}},
            "d.py": {"imports": set()},
        }
        production = {"a.py", "b.py", "c.py", "d.py"}
        directly_tested = {"a.py"}
        result = transitive_coverage(directly_tested, graph, production)
        assert result == {"b.py", "c.py", "d.py"}

    def test_no_directly_tested(self):
        """Empty directly_tested → empty transitive."""
        graph = {"a.py": {"imports": {"b.py"}}}
        result = transitive_coverage(set(), graph, {"a.py", "b.py"})
        assert result == set()


# ── _analyze_test_quality ────────────────────────────────


class TestAnalyzeTestQuality:
    def test_typescript_thorough(self, tmp_path):
        content = (
            'test("does thing", () => {\n'
            "  expect(foo).toBe(1);\n"
            "  expect(bar).toBe(2);\n"
            "  expect(baz).toBe(3);\n"
            "  expect(qux).toBe(4);\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "thorough.test.ts", content)
        result = analyze_test_quality({tf}, "typescript")
        assert tf in result
        assert result[tf]["quality"] == "thorough"
        assert result[tf]["assertions"] >= 4
        assert result[tf]["test_functions"] == 1

    def test_typescript_adequate_simple(self, tmp_path):
        content = (
            'test("does thing", () => {\n'
            "  expect(foo).toBe(1);\n"
            "  expect(bar).toBe(2);\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "adequate.test.ts", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["quality"] in ("thorough", "adequate")

    def test_typescript_assertion_free(self, tmp_path):
        content = 'test("does nothing", () => {});\n'
        tf = _write_file(tmp_path, "noassert.test.ts", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["quality"] == "assertion_free"
        assert result[tf]["assertions"] == 0
        assert result[tf]["test_functions"] == 1

    def test_typescript_counts_multiple_test_functions(self, tmp_path):
        content = (
            'it("a", () => {});\n'
            'it("b", () => {});\n'
            'it("c", () => { expect(foo).toBe(1); });\n'
        )
        tf = _write_file(tmp_path, "multi.test.ts", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["test_functions"] == 3
        assert result[tf]["quality"] == "smoke"

    def test_typescript_snapshot_heavy(self, tmp_path):
        content = (
            'it("renders", () => {\n'
            "  expect(component).toMatchSnapshot();\n"
            "  expect(component).toMatchSnapshot();\n"
            "  expect(component).toMatchSnapshot();\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "utils.test.ts", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["quality"] == "snapshot_heavy"
        assert result[tf]["snapshots"] >= 3

    def test_typescript_smoke(self, tmp_path):
        """TS test function count supports smoke classification (<1 assertion per test)."""
        content = (
            'it("a", () => {});\n'
            'it("b", () => {});\n'
            'it("c", () => {});\n'
            "expect(foo).toBe(1);\n"
        )
        tf = _write_file(tmp_path, "smoke.test.ts", content)
        result = analyze_test_quality({tf}, "typescript")
        # 1 assertion across 3 test functions → ratio < 1 → smoke
        assert result[tf]["quality"] == "smoke"

    def test_typescript_placeholder_smoke(self, tmp_path):
        content = (
            "import './someModule';\n"
            "import { describe, it, expect } from 'vitest';\n\n"
            "describe('coverage smoke: path/to/file.ts', () => {\n"
            "  it('has direct test coverage entry', () => {\n"
            "    expect(true).toBe(true);\n"
            "  });\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "placeholder.test.ts", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["quality"] == "placeholder_smoke"
        assert result[tf]["placeholder"] is True

    def test_typescript_tobedefined_dynamic_import_smoke(self, tmp_path):
        content = (
            "const moduleLoaders = [\n"
            "  () => import('./a'),\n"
            "  () => import('./b'),\n"
            "  () => import('./c'),\n"
            "];\n"
            "it('imports all modules', async () => {\n"
            "  for (const loadModule of moduleLoaders) {\n"
            "    await expect(loadModule()).resolves.toBeDefined();\n"
            "  }\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "moduleCoverage.test.ts", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["quality"] == "placeholder_smoke"
        assert result[tf]["placeholder"] is True

    def test_no_test_functions(self, tmp_path):
        content = "// just a comment\nconsole.log('hello');\n"
        tf = _write_file(tmp_path, "empty.test.ts", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["quality"] == "no_tests"

    def test_nonexistent_file_skipped(self):
        result = analyze_test_quality({"/no/such/file.ts"}, "typescript")
        assert "/no/such/file.ts" not in result

    def test_typescript_adequate(self, tmp_path):
        content = (
            'test("does thing", () => {\n'
            "  expect(foo).toBe(1);\n"
            "  expect(bar).toBe(2);\n"
            "});\n"
        )
        tf = _write_file(tmp_path, "foo.test.ts", content)
        result = analyze_test_quality({tf}, "typescript")
        assert result[tf]["quality"] in ("thorough", "adequate")


# ── detect_test_coverage (integration) ───────────────────


class TestDetectTestCoverage:
    def test_zero_production_files(self, tmp_path):
        """No production files → empty results, potential=0."""
        test_f = _write_file(
            tmp_path, "utils_test.dart", "void main() { test('x', () { expect(true, isTrue); }); }\n"
        )
        zone_map = _make_zone_map([test_f])
        graph = {}
        entries, potential = detect_test_coverage(graph, zone_map, "dart")
        assert entries == []
        assert potential == 0

    def test_zero_test_files_with_production(self, tmp_path):
        """Production files but no tests → untested_module issues."""
        prod_f = _write_file(
            tmp_path, "app.dart", "void main() {}\n" + "// code\n" * 13
        )
        zone_map = _make_zone_map([prod_f])
        graph = {prod_f: {"imports": set(), "importer_count": 0}}
        entries, potential = detect_test_coverage(graph, zone_map, "dart")
        # Potential is LOC-weighted: round(sqrt(14)) = round(3.74) = 4
        assert potential > 0
        assert len(entries) >= 1
        assert entries[0]["detail"]["kind"] == "untested_module"
        assert "loc_weight" in entries[0]["detail"]

    def test_typescript_dynamic_import_smoke_produces_placeholder_issues(
        self, tmp_path
    ):
        prod_a = _write_file(tmp_path, "src/a.ts", ("export function a(v: number) {\n  return v + 1;\n}\n" * 4))
        prod_b = _write_file(tmp_path, "src/b.ts", ("export function b(v: number) {\n  return v + 2;\n}\n" * 4))
        prod_c = _write_file(tmp_path, "src/c.ts", ("export function c(v: number) {\n  return v + 3;\n}\n" * 4))
        test_f = _write_file(
            tmp_path,
            "src/moduleCoverage.test.ts",
            (
                "const moduleLoaders = [\n"
                "  () => import('./a'),\n"
                "  () => import('./b'),\n"
                "  () => import('./c'),\n"
                "];\n"
                "it('imports all modules', async () => {\n"
                "  for (const loadModule of moduleLoaders) {\n"
                "    await expect(loadModule()).resolves.toBeDefined();\n"
                "  }\n"
                "});\n"
            ),
        )
        all_files = [prod_a, prod_b, prod_c, test_f]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_a: {"imports": set(), "importer_count": 0},
            prod_b: {"imports": set(), "importer_count": 0},
            prod_c: {"imports": set(), "importer_count": 0},
            test_f: {"imports": set()},
        }

        entries, potential = detect_test_coverage(graph, zone_map, "typescript")
        assert potential > 0
        placeholders = [
            entry
            for entry in entries
            if entry.get("detail", {}).get("kind") == "placeholder_test"
        ]
        assert placeholders
        assert any(
            entry.get("detail", {}).get("test_file") == test_f for entry in placeholders
        )

    def test_production_with_direct_test(self, tmp_path):
        """Production file with a direct test → no untested issue."""
        prod_f = _write_file(tmp_path, "utils.dart", "int foo() => 1;\n" * 10)
        test_f = _write_file(
            tmp_path,
            "utils_test.dart",
            "void main() { test('foo', () { expect(1, 1); expect(2, 2); expect(3, 3); }); }\n",
        )
        all_files = [prod_f, test_f]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_f: {"imports": set(), "importer_count": 0},
            test_f: {"imports": {prod_f}},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "dart")
        assert potential > 0
        # Should not have any untested_module or untested_critical issues
        untested = [
            e
            for e in entries
            if e["detail"]["kind"] in ("untested_module", "untested_critical")
        ]
        assert untested == []

    def test_transitive_only_issue(self, tmp_path):
        """Production file covered only transitively → transitive_only issue."""
        prod_a = _write_file(
            tmp_path, "a.dart", "import 'b.dart';\nvoid run() {}\n" + "// code\n" * 13
        )
        prod_b = _write_file(
            tmp_path, "b.dart", "void helper() {}\n" + "// code\n" * 13
        )
        test_a = _write_file(
            tmp_path,
            "a_test.dart",
            "void main() { test('a', () { expect(1, 1); expect(2, 2); expect(3, 3); }); }\n",
        )
        all_files = [prod_a, prod_b, test_a]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_a: {"imports": {prod_b}, "importer_count": 0},
            prod_b: {"imports": set(), "importer_count": 1},
            test_a: {"imports": {prod_a}},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "dart")
        assert potential > 0
        trans_entries = [e for e in entries if e["detail"]["kind"] == "transitive_only"]
        assert len(trans_entries) == 1
        assert trans_entries[0]["file"] == prod_b
        assert "loc_weight" in trans_entries[0]["detail"]

    def test_untested_critical_high_importers(self, tmp_path):
        """Untested file with >=10 importers → untested_critical (tier 2).

        Must have at least one test file to enter _generate_issues path
        (otherwise _no_tests_issues is used, which always emits untested_module).
        """
        prod_f = _write_file(
            tmp_path, "core.dart", "void process() {}\n" + "// critical code\n" * 13
        )
        other_prod = _write_file(
            tmp_path, "other.dart", "void run() {}\n" + "// other\n" * 13
        )
        test_other = _write_file(
            tmp_path,
            "other_test.dart",
            "void main() { test('other', () { expect(1, 1); expect(2, 2); expect(3, 3); }); }\n",
        )
        all_files = [prod_f, other_prod, test_other]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_f: {"imports": set(), "importer_count": 15},
            other_prod: {"imports": set(), "importer_count": 0},
            test_other: {"imports": {other_prod}},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "dart")
        assert potential > 0
        critical = [e for e in entries if e["detail"]["kind"] == "untested_critical"]
        assert len(critical) == 1
        assert critical[0]["file"] == prod_f
        assert critical[0]["tier"] == 2
        assert "loc_weight" in critical[0]["detail"]

    def test_untested_module_low_importers(self, tmp_path):
        """Untested file with low importer count → untested_module (tier 3)."""
        prod_f = _write_file(
            tmp_path, "helper.dart", "void helper() {}\n" + "// helper code\n" * 13
        )
        zone_map = _make_zone_map([prod_f])
        graph = {prod_f: {"imports": set(), "importer_count": 2}}
        entries, potential = detect_test_coverage(graph, zone_map, "dart")
        assert potential > 0
        assert len(entries) >= 1
        assert entries[0]["detail"]["kind"] == "untested_module"
        assert entries[0]["tier"] == 3

    def test_extra_test_files(self, tmp_path):
        """extra_test_files parameter adds external test files to coverage."""
        prod_f = _write_file(
            tmp_path, "lib/utils.dart", "int foo() => 1;\n" * 10
        )
        # External test file outside the zone map
        ext_test = _write_file(
            tmp_path,
            "external/utils_test.dart",
            "void main() { test('foo', () { expect(1, 1); expect(2, 2); expect(3, 3); }); }\n",
        )
        # Only production file in zone map
        zone_map = _make_zone_map([prod_f])
        graph = {
            prod_f: {"imports": set(), "importer_count": 0},
            ext_test: {"imports": {prod_f}},
        }
        entries, potential = detect_test_coverage(
            graph,
            zone_map,
            "dart",
            extra_test_files={ext_test},
        )
        assert potential > 0
        # prod_f should be directly tested via ext_test
        untested = [
            e
            for e in entries
            if e["detail"]["kind"] in ("untested_module", "untested_critical")
        ]
        assert untested == []

    def test_loc_weighted_potential(self, tmp_path):
        """Potential is LOC-weighted: sum of sqrt(loc) capped at 50."""
        # 100-LOC file: sqrt(100) = 10
        prod_big = _write_file(
            tmp_path, "big.dart", "void run() {}\n" + "var x = 1;\n" * 98
        )
        # 25-LOC file: sqrt(25) = 5
        prod_small = _write_file(
            tmp_path, "small.dart", "void run() {}\n" + "var x = 1;\n" * 23
        )
        zone_map = _make_zone_map([prod_big, prod_small])
        graph = {
            prod_big: {"imports": set(), "importer_count": 0},
            prod_small: {"imports": set(), "importer_count": 0},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "dart")
        expected = round(math.sqrt(100) + math.sqrt(25))  # 10 + 5 = 15
        assert potential == expected

    def test_small_files_excluded(self, tmp_path):
        """Files below _MIN_LOC threshold are not scorable."""
        tiny = _write_file(tmp_path, "tiny.dart", "var x = 1;\n")
        zone_map = _make_zone_map([tiny])
        graph = {tiny: {"imports": set(), "importer_count": 0}}
        entries, potential = detect_test_coverage(graph, zone_map, "dart")
        assert potential == 0
        assert entries == []

    def test_quality_issue_assertion_free(self, tmp_path):
        """Directly tested file with assertion-free test → quality issue."""
        prod_f = _write_file(tmp_path, "utils.dart", "int foo() => 1;\n" * 10)
        test_f = _write_file(
            tmp_path,
            "utils_test.dart",
            "void main() { test('foo', () {}); }\n",
        )
        all_files = [prod_f, test_f]
        zone_map = _make_zone_map(all_files)
        graph = {
            prod_f: {"imports": set(), "importer_count": 0},
            test_f: {"imports": {prod_f}},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "dart")
        assert potential > 0
        qual_entries = [
            e for e in entries if e["detail"]["kind"] == "assertion_free_test"
        ]
        assert len(qual_entries) == 1
        assert qual_entries[0]["file"] == prod_f

    def test_quality_issue_placeholder_test(self, tmp_path):
        """Placeholder coverage smoke tests should be flagged explicitly."""
        prod_f = _write_file(tmp_path, "utils.ts", "export const foo = 1;\n" * 12)
        test_f = _write_file(
            tmp_path,
            "utils.test.ts",
            (
                "import './utils';\n"
                "import { describe, it, expect } from 'vitest';\n\n"
                "describe('coverage smoke: src/utils.ts', () => {\n"
                "  it('has direct test coverage entry', () => {\n"
                "    expect(true).toBe(true);\n"
                "  });\n"
                "});\n"
            ),
        )
        zone_map = _make_zone_map([prod_f, test_f])
        graph = {
            prod_f: {"imports": set(), "importer_count": 0},
            test_f: {"imports": {prod_f}},
        }
        entries, _potential = detect_test_coverage(graph, zone_map, "typescript")
        placeholder_entries = [
            e for e in entries if e["detail"]["kind"] == "placeholder_test"
        ]
        assert len(placeholder_entries) == 1
        assert placeholder_entries[0]["file"] == prod_f

    def test_placeholder_smoke_not_reported_when_adequate_direct_test_exists(
        self, tmp_path
    ):
        """A good direct test should suppress placeholder-smoke quality noise."""
        prod_f = _write_file(tmp_path, "utils.ts", "export const foo = 1;\n" * 12)
        placeholder_test = _write_file(
            tmp_path,
            "utils.placeholder.test.ts",
            (
                "import './utils';\n"
                "import { describe, it, expect } from 'vitest';\n\n"
                "describe('coverage smoke: src/utils.ts', () => {\n"
                "  it('has direct test coverage entry', () => {\n"
                "    expect(true).toBe(true);\n"
                "  });\n"
                "});\n"
            ),
        )
        adequate_test = _write_file(
            tmp_path,
            "utils.behavior.test.ts",
            (
                "import { describe, it, expect } from 'vitest';\n"
                "import { foo } from './utils';\n\n"
                "describe('utils', () => {\n"
                "  it('keeps value stable', () => {\n"
                "    expect(foo).toBe(1);\n"
                "    expect(typeof foo).toBe('number');\n"
                "    expect(foo > 0).toBe(true);\n"
                "  });\n"
                "});\n"
            ),
        )
        zone_map = _make_zone_map([prod_f, placeholder_test, adequate_test])
        graph = {
            prod_f: {"imports": set(), "importer_count": 0},
            placeholder_test: {"imports": {prod_f}},
            adequate_test: {"imports": {prod_f}},
        }

        entries, _potential = detect_test_coverage(graph, zone_map, "typescript")
        quality_entries = [e for e in entries if e.get("file") == prod_f and e.get("detail", {}).get("kind") in {
            "assertion_free_test",
            "placeholder_test",
            "shallow_tests",
            "over_mocked",
            "snapshot_heavy",
        }]
        assert quality_entries == []

    def test_multiple_weak_direct_tests_emit_single_highest_priority_issue(
        self, tmp_path
    ):
        """Direct-test quality should produce one representative issue per module."""
        prod_f = _write_file(tmp_path, "utils.ts", "export const foo = 1;\n" * 12)
        placeholder_test = _write_file(
            tmp_path,
            "utils.placeholder.test.ts",
            (
                "import './utils';\n"
                "import { describe, it, expect } from 'vitest';\n\n"
                "describe('coverage smoke: src/utils.ts', () => {\n"
                "  it('has direct test coverage entry', () => {\n"
                "    expect(true).toBe(true);\n"
                "  });\n"
                "});\n"
            ),
        )
        smoke_test = _write_file(
            tmp_path,
            "utils.smoke.test.ts",
            (
                "import { describe, it, expect } from 'vitest';\n"
                "import { foo } from './utils';\n\n"
                "describe('utils smoke', () => {\n"
                "  it('a', () => {});\n"
                "  it('b', () => {});\n"
                "  it('c', () => { expect(foo).toBe(1); });\n"
                "});\n"
            ),
        )
        zone_map = _make_zone_map([prod_f, placeholder_test, smoke_test])
        graph = {
            prod_f: {"imports": set(), "importer_count": 0},
            placeholder_test: {"imports": {prod_f}},
            smoke_test: {"imports": {prod_f}},
        }

        entries, _potential = detect_test_coverage(graph, zone_map, "typescript")
        quality_entries = [
            e for e in entries if e.get("file") == prod_f and e.get("detail", {}).get("kind") in {
                "assertion_free_test",
                "placeholder_test",
                "shallow_tests",
                "over_mocked",
                "snapshot_heavy",
            }
        ]
        assert len(quality_entries) == 1
        assert quality_entries[0]["detail"]["kind"] == "placeholder_test"

    def test_naming_convention_mapping(self, tmp_path):
        """Test file matched by naming convention (no graph import edge)."""
        prod_f = _write_file(tmp_path, "utils.dart", "int foo() => 1;\n" * 10)
        test_f = _write_file(
            tmp_path,
            "utils_test.dart",
            "void main() { test('foo', () { expect(1, 1); expect(2, 2); expect(3, 3); }); }\n",
        )
        all_files = [prod_f, test_f]
        zone_map = _make_zone_map(all_files)
        # Test file does NOT import production file via graph
        graph = {
            prod_f: {"imports": set(), "importer_count": 0},
            test_f: {"imports": set()},
        }
        entries, potential = detect_test_coverage(graph, zone_map, "dart")
        assert potential > 0
        # Should be matched by naming convention, not untested
        untested = [
            e
            for e in entries
            if e["detail"]["kind"] in ("untested_module", "untested_critical")
        ]
        assert untested == []

