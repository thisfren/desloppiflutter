"""Direct tests for desloppify.languages.dart.review module."""

from __future__ import annotations

import re

from desloppify.languages.dart.review import (
    HOLISTIC_REVIEW_DIMENSIONS,
    LOW_VALUE_PATTERN,
    MIGRATION_MIXED_EXTENSIONS,
    MIGRATION_PATTERN_PAIRS,
    REVIEW_GUIDANCE,
    api_surface,
    module_patterns,
)


# ---------------------------------------------------------------------------
# HOLISTIC_REVIEW_DIMENSIONS
# ---------------------------------------------------------------------------


class TestHolisticReviewDimensions:
    def test_is_non_empty_list(self):
        assert isinstance(HOLISTIC_REVIEW_DIMENSIONS, list)
        assert len(HOLISTIC_REVIEW_DIMENSIONS) > 0

    def test_entries_are_strings(self):
        for dim in HOLISTIC_REVIEW_DIMENSIONS:
            assert isinstance(dim, str), f"Expected str, got {type(dim)} for {dim!r}"

    def test_no_duplicates(self):
        assert len(HOLISTIC_REVIEW_DIMENSIONS) == len(set(HOLISTIC_REVIEW_DIMENSIONS))

    def test_expected_dimensions_present(self):
        expected = {
            "cross_module_architecture",
            "error_consistency",
            "abstraction_fitness",
            "authorization_consistency",
            "test_strategy",
            "design_coherence",
        }
        assert set(HOLISTIC_REVIEW_DIMENSIONS) == expected


# ---------------------------------------------------------------------------
# REVIEW_GUIDANCE
# ---------------------------------------------------------------------------


class TestReviewGuidance:
    def test_is_dict(self):
        assert isinstance(REVIEW_GUIDANCE, dict)

    def test_has_expected_keys(self):
        assert "patterns" in REVIEW_GUIDANCE
        assert "auth" in REVIEW_GUIDANCE
        assert "naming" in REVIEW_GUIDANCE

    def test_patterns_is_list(self):
        assert isinstance(REVIEW_GUIDANCE["patterns"], list)
        assert len(REVIEW_GUIDANCE["patterns"]) > 0

    def test_auth_is_list(self):
        assert isinstance(REVIEW_GUIDANCE["auth"], list)
        assert len(REVIEW_GUIDANCE["auth"]) > 0

    def test_naming_is_string(self):
        assert isinstance(REVIEW_GUIDANCE["naming"], str)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_migration_pattern_pairs_is_list(self):
        assert isinstance(MIGRATION_PATTERN_PAIRS, list)

    def test_migration_mixed_extensions_is_set(self):
        assert isinstance(MIGRATION_MIXED_EXTENSIONS, set)

    def test_low_value_pattern_is_compiled_regex(self):
        assert isinstance(LOW_VALUE_PATTERN, re.Pattern)

    def test_low_value_matches_part_of(self):
        assert LOW_VALUE_PATTERN.search("  part of my_library;")

    def test_low_value_matches_export(self):
        assert LOW_VALUE_PATTERN.search("export 'src/foo.dart';")

    def test_low_value_no_match_on_class(self):
        assert LOW_VALUE_PATTERN.search("class Foo {}") is None


# ---------------------------------------------------------------------------
# module_patterns()
# ---------------------------------------------------------------------------


class TestModulePatterns:
    def test_extracts_import(self):
        code = "import 'package:flutter/material.dart';"
        result = module_patterns(code)
        assert result == ["package:flutter/material.dart"]

    def test_extracts_export(self):
        code = "export 'src/widget.dart';"
        result = module_patterns(code)
        assert result == ["src/widget.dart"]

    def test_extracts_part(self):
        code = "part 'src/model.g.dart';"
        result = module_patterns(code)
        assert result == ["src/model.g.dart"]

    def test_extracts_multiple(self):
        code = (
            "import 'package:flutter/material.dart';\n"
            "import 'package:provider/provider.dart';\n"
            "export 'src/api.dart';\n"
        )
        result = module_patterns(code)
        assert len(result) == 3

    def test_empty_content(self):
        assert module_patterns("") == []

    def test_no_imports(self):
        assert module_patterns("class Foo {}") == []


# ---------------------------------------------------------------------------
# api_surface()
# ---------------------------------------------------------------------------


class TestApiSurface:
    def test_extracts_public_class(self):
        files = {"a.dart": "class MyWidget extends StatelessWidget {}"}
        result = api_surface(files)
        assert "MyWidget" in result["public_types"]

    def test_excludes_private_class(self):
        files = {"a.dart": "class _InternalWidget {}"}
        result = api_surface(files)
        assert "_InternalWidget" not in result["public_types"]

    def test_extracts_enum(self):
        files = {"a.dart": "enum Color { red, green, blue }"}
        result = api_surface(files)
        assert "Color" in result["public_types"]

    def test_extracts_mixin(self):
        files = {"a.dart": "mixin Scrollable on Widget {}"}
        result = api_surface(files)
        assert "Scrollable" in result["public_types"]

    def test_extracts_extension(self):
        files = {"a.dart": "extension StringUtils on String {}"}
        result = api_surface(files)
        assert "StringUtils" in result["public_types"]

    def test_extracts_typedef(self):
        files = {"a.dart": "typedef VoidCallback = void Function();"}
        result = api_surface(files)
        assert "VoidCallback" in result["public_types"]

    def test_extracts_public_function(self):
        files = {"a.dart": "void initApp() {\n  print('hello');\n}"}
        result = api_surface(files)
        assert "initApp" in result["public_functions"]

    def test_excludes_private_function(self):
        files = {"a.dart": "void _setup() {\n  print('setup');\n}"}
        result = api_surface(files)
        assert "_setup" not in result["public_functions"]

    def test_empty_files(self):
        result = api_surface({})
        assert result == {"public_types": [], "public_functions": []}

    def test_results_are_sorted(self):
        files = {
            "a.dart": "class Zebra {}\nclass Alpha {}",
        }
        result = api_surface(files)
        assert result["public_types"] == sorted(result["public_types"])

    def test_deduplicates_across_files(self):
        files = {
            "a.dart": "class Shared {}",
            "b.dart": "class Shared {}",
        }
        result = api_surface(files)
        assert result["public_types"].count("Shared") == 1

    def test_multiple_files(self):
        files = {
            "a.dart": "class Foo {}",
            "b.dart": "class Bar {}",
        }
        result = api_surface(files)
        assert "Foo" in result["public_types"]
        assert "Bar" in result["public_types"]
