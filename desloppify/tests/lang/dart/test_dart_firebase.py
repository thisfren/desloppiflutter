"""Tests for Dart/Flutter Firebase antipattern detector regex patterns."""

from __future__ import annotations

from pathlib import Path

from desloppify.languages.dart.detectors.firebase import (
    _DIRECT_ACCESS_RE,
    _HARDCODED_COLLECTION_RE,
    _RAW_GET_RE,
    _UNHANDLED_FIREBASE_RE,
    _check_unhandled_errors,
    detect_firebase_patterns,
)


# ── _DIRECT_ACCESS_RE ──────────────────────────────────────────


def test_direct_access_matches_firestore_instance():
    assert _DIRECT_ACCESS_RE.search("FirebaseFirestore.instance.collection('users')")


def test_direct_access_matches_auth_instance():
    assert _DIRECT_ACCESS_RE.search("final user = FirebaseAuth.instance.currentUser;")


def test_direct_access_matches_storage_instance():
    assert _DIRECT_ACCESS_RE.search("FirebaseStorage.instance.ref('uploads')")


def test_direct_access_matches_database_instance():
    assert _DIRECT_ACCESS_RE.search("FirebaseDatabase.instance.ref('data')")


def test_direct_access_ignores_repository_wrapper():
    assert not _DIRECT_ACCESS_RE.search("repository.getUser()")


def test_direct_access_ignores_plain_instance():
    assert not _DIRECT_ACCESS_RE.search("MyClass.instance")


# ── _HARDCODED_COLLECTION_RE ───────────────────────────────────


def test_hardcoded_collection_single_quotes():
    m = _HARDCODED_COLLECTION_RE.search(".collection('users')")
    assert m is not None
    assert m.group(1) == "users"


def test_hardcoded_collection_double_quotes():
    m = _HARDCODED_COLLECTION_RE.search('.collection("chat_messages")')
    assert m is not None
    assert m.group(1) == "chat_messages"


def test_hardcoded_collection_nested_path():
    m = _HARDCODED_COLLECTION_RE.search(".collection('users/profiles/settings')")
    assert m is not None
    assert m.group(1) == "users/profiles/settings"


def test_hardcoded_collection_no_match_variable():
    assert not _HARDCODED_COLLECTION_RE.search(".collection(collectionName)")


# ── _UNHANDLED_FIREBASE_RE ─────────────────────────────────────


def test_unhandled_firebase_matches_await_firestore():
    assert _UNHANDLED_FIREBASE_RE.search(
        "await FirebaseFirestore.instance.collection('x').get()"
    )


def test_unhandled_firebase_matches_without_await():
    assert _UNHANDLED_FIREBASE_RE.search(
        "FirebaseAuth.instance.signInAnonymously()"
    )


def test_unhandled_firebase_no_match_custom_class():
    assert not _UNHANDLED_FIREBASE_RE.search("await myService.getData()")


# ── _RAW_GET_RE ────────────────────────────────────────────────


def test_raw_get_matches_doc_get():
    assert _RAW_GET_RE.search(".doc('abc').get()")


def test_raw_get_matches_collection_get():
    assert _RAW_GET_RE.search(".collection('users').get()")


def test_raw_get_no_match_with_source():
    assert not _RAW_GET_RE.search(".doc('abc').get(GetOptions(source: Source.cache))")


# ── _check_unhandled_errors ────────────────────────────────────


def test_check_unhandled_errors_flags_await_outside_try():
    content = "await FirebaseFirestore.instance.collection('x').get();"
    lines = content.splitlines()
    entries: list[dict] = []
    _check_unhandled_errors("lib/main.dart", "lib/main.dart", content, lines, entries)
    assert len(entries) == 1
    assert entries[0]["detail"]["kind"] == "firebase_unhandled_error"


def test_check_unhandled_errors_ignores_inside_try():
    content = (
        "try {\n"
        "  await FirebaseFirestore.instance.collection('x').get();\n"
        "} catch (e) {\n"
        "  print(e);\n"
        "}\n"
    )
    lines = content.splitlines()
    entries: list[dict] = []
    _check_unhandled_errors("lib/main.dart", "lib/main.dart", content, lines, entries)
    assert len(entries) == 0


def test_check_unhandled_errors_ignores_no_await():
    content = "FirebaseAuth.instance.signInAnonymously();"
    lines = content.splitlines()
    entries: list[dict] = []
    _check_unhandled_errors("lib/main.dart", "lib/main.dart", content, lines, entries)
    assert len(entries) == 0


# ── detect_firebase_patterns (integration) ─────────────────────


def test_detect_flags_direct_access_outside_repository(tmp_path):
    dart_file = tmp_path / "lib" / "home_page.dart"
    dart_file.parent.mkdir(parents=True)
    dart_file.write_text(
        "class HomePage {\n"
        "  void load() {\n"
        "    FirebaseFirestore.instance.collection('items').get();\n"
        "  }\n"
        "}\n"
    )
    entries, scanned = detect_firebase_patterns([str(dart_file)], zone_map=None)
    assert scanned == 1
    kinds = {e["detail"]["kind"] for e in entries}
    assert "firebase_direct_access" in kinds
    assert "firebase_hardcoded_collection" in kinds


def test_detect_skips_direct_access_inside_repository(tmp_path):
    dart_file = tmp_path / "lib" / "user_repository.dart"
    dart_file.parent.mkdir(parents=True)
    dart_file.write_text(
        "class UserRepository {\n"
        "  Future<void> save() async {\n"
        "    await FirebaseFirestore.instance.collection('users').add({});\n"
        "  }\n"
        "}\n"
    )
    entries, scanned = detect_firebase_patterns([str(dart_file)], zone_map=None)
    assert scanned == 1
    direct_entries = [e for e in entries if e["detail"]["kind"] == "firebase_direct_access"]
    assert len(direct_entries) == 0


def test_detect_skips_comments(tmp_path):
    dart_file = tmp_path / "lib" / "widget.dart"
    dart_file.parent.mkdir(parents=True)
    dart_file.write_text(
        "class Widget {\n"
        "  // FirebaseFirestore.instance.collection('items').get();\n"
        "  /// FirebaseAuth.instance.currentUser;\n"
        "}\n"
    )
    entries, scanned = detect_firebase_patterns([str(dart_file)], zone_map=None)
    assert scanned == 1
    assert len(entries) == 0


def test_detect_skips_non_dart_files(tmp_path):
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("FirebaseFirestore.instance")
    entries, scanned = detect_firebase_patterns([str(txt_file)], zone_map=None)
    assert scanned == 0
    assert len(entries) == 0
