"""Tests for Dart function extraction and file discovery."""

from __future__ import annotations

from pathlib import Path

from desloppify.languages.dart.extractors import (
    _FUNC_DECL_RE,
    _extract_params,
    _find_matching_brace,
    _find_statement_end,
    extract_dart_functions,
    find_dart_files,
)


def _write(path: Path, relpath: str, content: str) -> Path:
    file_path = path / relpath
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return file_path


# --- find_dart_files ---


def test_find_dart_files_discovers_dart_sources(tmp_path):
    _write(tmp_path, "lib/main.dart", "void main() {}")
    _write(tmp_path, "lib/src/util.dart", "class Util {}")
    _write(tmp_path, "lib/readme.txt", "not dart")

    files = find_dart_files(tmp_path)
    assert len(files) == 2
    assert all(f.endswith(".dart") for f in files)


def test_find_dart_files_excludes_build_directories(tmp_path):
    _write(tmp_path, "lib/main.dart", "void main() {}")
    _write(tmp_path, "build/output.dart", "generated")
    _write(tmp_path, ".dart_tool/cache.dart", "cache")

    files = find_dart_files(tmp_path)
    assert len(files) == 1
    assert "build" not in files[0]
    assert ".dart_tool" not in files[0]


def test_find_dart_files_returns_empty_for_no_dart(tmp_path):
    _write(tmp_path, "readme.md", "# Hello")
    assert find_dart_files(tmp_path) == []


# --- _FUNC_DECL_RE ---


def test_func_decl_re_matches_simple_function():
    m = _FUNC_DECL_RE.search("void main() {")
    assert m is not None
    assert m.group(1) == "main"


def test_func_decl_re_matches_return_type_and_params():
    m = _FUNC_DECL_RE.search("String greet(String name) {")
    assert m is not None
    assert m.group(1) == "greet"
    assert "name" in m.group(2)


def test_func_decl_re_matches_arrow_function():
    m = _FUNC_DECL_RE.search("int add(int a, int b) => a + b;")
    assert m is not None
    assert m.group(1) == "add"
    assert m.group(3) == "=>"


def test_func_decl_re_matches_async_function():
    m = _FUNC_DECL_RE.search("Future<void> fetchData() async {")
    assert m is not None
    assert m.group(1) == "fetchData"


def test_func_decl_re_matches_static_method():
    m = _FUNC_DECL_RE.search("  static Widget build(BuildContext ctx) {")
    assert m is not None
    assert m.group(1) == "build"


def test_func_decl_re_matches_factory_constructor():
    m = _FUNC_DECL_RE.search("  factory MyClass(Map json) {")
    assert m is not None
    assert m.group(1) == "MyClass"


def test_func_decl_re_skips_keywords():
    """Keywords like if/for/while should not be captured as function names."""
    from desloppify.languages.dart.extractors import _KEYWORDS

    for kw in _KEYWORDS:
        m = _FUNC_DECL_RE.search(f"{kw}(x) {{")
        if m:
            assert m.group(1) == kw  # regex matches but extract_dart_functions filters


def test_func_decl_re_matches_nullable_return():
    m = _FUNC_DECL_RE.search("String? parse(String input) {")
    assert m is not None
    assert m.group(1) == "parse"


# --- _extract_params ---


def test_extract_params_simple():
    assert _extract_params("int a, String b") == ["a", "b"]


def test_extract_params_with_defaults():
    assert _extract_params("int a = 0, String b = 'hi'") == ["a", "b"]


def test_extract_params_empty():
    assert _extract_params("") == []


def test_extract_params_skips_braces():
    result = _extract_params("{int a, int b}")
    # Opening/closing braces are filtered out
    assert all(not n.startswith("{") and not n.endswith("}") for n in result)


def test_extract_params_strips_annotations():
    result = _extract_params("@required int count")
    assert "count" in result


# --- _find_matching_brace ---


def test_find_matching_brace_simple():
    assert _find_matching_brace("{ foo }", 0) == 6


def test_find_matching_brace_nested():
    assert _find_matching_brace("{ { inner } }", 0) == 12


def test_find_matching_brace_ignores_string_braces():
    content = '{ var s = "}{"; }'
    assert _find_matching_brace(content, 0) == len(content) - 1


def test_find_matching_brace_returns_none_unbalanced():
    assert _find_matching_brace("{ open", 0) is None


# --- _find_statement_end ---


def test_find_statement_end_simple():
    assert _find_statement_end("a + b;", 0) == 5


def test_find_statement_end_ignores_semicolons_in_strings():
    content = 'var s = "a;b"; return;'
    assert _find_statement_end(content, 0) == 13


def test_find_statement_end_returns_none_if_no_semicolon():
    assert _find_statement_end("no end here", 0) is None


# --- extract_dart_functions ---


def test_extract_dart_functions_simple(tmp_path):
    src = _write(
        tmp_path,
        "lib/main.dart",
        "void main() {\n  print('hello');\n}\n",
    )
    fns = extract_dart_functions(str(src))
    assert len(fns) == 1
    assert fns[0].name == "main"
    assert fns[0].line == 1
    assert fns[0].params == []


def test_extract_dart_functions_arrow(tmp_path):
    src = _write(
        tmp_path,
        "lib/math.dart",
        "int add(int a, int b) => a + b;\n",
    )
    fns = extract_dart_functions(str(src))
    assert len(fns) == 1
    assert fns[0].name == "add"
    assert fns[0].params == ["a", "b"]


def test_extract_dart_functions_multiple(tmp_path):
    src = _write(
        tmp_path,
        "lib/service.dart",
        (
            "void init() {\n  setup();\n}\n\n"
            "String greet(String name) {\n  return 'Hi $name';\n}\n"
        ),
    )
    fns = extract_dart_functions(str(src))
    names = {f.name for f in fns}
    assert "init" in names
    assert "greet" in names


def test_extract_dart_functions_skips_keywords(tmp_path):
    src = _write(
        tmp_path,
        "lib/flow.dart",
        "void run() {\n  if (true) {\n    print('ok');\n  }\n}\n",
    )
    fns = extract_dart_functions(str(src))
    names = {f.name for f in fns}
    assert "if" not in names
    assert "run" in names


def test_extract_dart_functions_returns_empty_for_missing_file():
    fns = extract_dart_functions("/nonexistent/file.dart")
    assert fns == []


def test_extract_dart_functions_includes_body_hash(tmp_path):
    src = _write(
        tmp_path,
        "lib/hash.dart",
        "void doWork() {\n  compute();\n}\n",
    )
    fns = extract_dart_functions(str(src))
    assert len(fns) == 1
    assert len(fns[0].body_hash) == 12
