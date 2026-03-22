"""Tests for Dart pubspec.yaml parsing."""

from __future__ import annotations

from pathlib import Path

from desloppify.languages.dart.pubspec import PUBSPEC_NAME_RE, read_package_name


# --- PUBSPEC_NAME_RE ---


def test_pubspec_name_re_matches_simple_name():
    m = PUBSPEC_NAME_RE.search("name: my_app\n")
    assert m is not None
    assert m.group(1) == "my_app"


def test_pubspec_name_re_matches_with_leading_whitespace():
    m = PUBSPEC_NAME_RE.search("  name: my_app\n")
    assert m is not None
    assert m.group(1) == "my_app"


def test_pubspec_name_re_matches_hyphenated_name():
    m = PUBSPEC_NAME_RE.search("name: my-cool-app\n")
    assert m is not None
    assert m.group(1) == "my-cool-app"


def test_pubspec_name_re_rejects_empty_value():
    m = PUBSPEC_NAME_RE.search("name: \n")
    assert m is None


def test_pubspec_name_re_rejects_numeric_start():
    m = PUBSPEC_NAME_RE.search("name: 123app\n")
    assert m is None


def test_pubspec_name_re_matches_among_other_fields():
    content = "version: 1.0.0\nname: sample\ndescription: A project\n"
    m = PUBSPEC_NAME_RE.search(content)
    assert m is not None
    assert m.group(1) == "sample"


# --- read_package_name ---


def test_read_package_name_returns_name(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: flutter_app\nversion: 1.0.0\n")
    assert read_package_name(tmp_path) == "flutter_app"


def test_read_package_name_no_pubspec(tmp_path):
    assert read_package_name(tmp_path) is None


def test_read_package_name_missing_name_field(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("version: 1.0.0\ndescription: test\n")
    assert read_package_name(tmp_path) is None


def test_read_package_name_empty_file(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("")
    assert read_package_name(tmp_path) is None


def test_read_package_name_malformed_yaml(tmp_path):
    (tmp_path / "pubspec.yaml").write_text(":::not valid yaml:::\ngarbage{{\n")
    assert read_package_name(tmp_path) is None


def test_read_package_name_with_extra_spacing(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name:   spaced_app  \n")
    assert read_package_name(tmp_path) == "spaced_app"


def test_read_package_name_name_in_comment_not_matched(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("# name: commented\nversion: 1.0.0\n")
    # The regex requires name at start-of-line (possibly with whitespace),
    # but '# name:' starts with '#' so should not match
    assert read_package_name(tmp_path) is None


def test_read_package_name_underscore_prefix(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: _private_app\n")
    assert read_package_name(tmp_path) == "_private_app"
