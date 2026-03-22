"""Direct tests for Dart phase runners and complexity signals."""

from __future__ import annotations

import re
from types import SimpleNamespace

from desloppify.languages.dart.phases import (
    DART_COMPLEXITY_SIGNALS,
    phase_firebase,
)


# ── DART_COMPLEXITY_SIGNALS regex coverage ───────────────────


def _signal_by_name(name: str):
    return next(s for s in DART_COMPLEXITY_SIGNALS if s.name == name)


def test_imports_signal_matches_import():
    sig = _signal_by_name("imports")
    assert re.search(sig.pattern, "import 'package:flutter/material.dart';")


def test_imports_signal_matches_export():
    sig = _signal_by_name("imports")
    assert re.search(sig.pattern, "export 'src/widget.dart';")


def test_imports_signal_matches_part():
    sig = _signal_by_name("imports")
    assert re.search(sig.pattern, "part 'model.g.dart';")


def test_imports_signal_no_match_plain():
    sig = _signal_by_name("imports")
    assert not re.search(sig.pattern, "var imported = true;")


def test_todos_signal_matches_todo():
    sig = _signal_by_name("TODOs")
    assert re.search(sig.pattern, "// TODO: fix this")


def test_todos_signal_matches_fixme():
    sig = _signal_by_name("TODOs")
    assert re.search(sig.pattern, "// FIXME: broken")


def test_todos_signal_no_match_code():
    sig = _signal_by_name("TODOs")
    assert not re.search(sig.pattern, "doSomething();")


def test_control_flow_matches_if():
    sig = _signal_by_name("control flow")
    assert re.search(sig.pattern, "if (x > 0) {")


def test_control_flow_matches_switch():
    sig = _signal_by_name("control flow")
    assert re.search(sig.pattern, "switch (value) {")


def test_control_flow_matches_for():
    sig = _signal_by_name("control flow")
    assert re.search(sig.pattern, "for (var i = 0; i < n; i++) {")


def test_control_flow_matches_catch():
    sig = _signal_by_name("control flow")
    assert re.search(sig.pattern, "} catch (e) {")


def test_classes_signal_matches_class():
    sig = _signal_by_name("classes")
    assert re.search(sig.pattern, "class MyWidget extends StatelessWidget {")


def test_classes_signal_matches_abstract():
    sig = _signal_by_name("classes")
    assert re.search(sig.pattern, "abstract class Repository {")


def test_classes_signal_no_match_variable():
    sig = _signal_by_name("classes")
    assert not re.search(sig.pattern, "var className = 'Foo';")


# ── phase_firebase smoke test ────────────────────────────────


def test_phase_firebase_smoke(tmp_path):
    dart_file = tmp_path / "lib" / "service.dart"
    dart_file.parent.mkdir(parents=True)
    dart_file.write_text(
        "class Service {\n"
        "  void fetch() {\n"
        "    FirebaseFirestore.instance.collection('items').get();\n"
        "  }\n"
        "}\n"
    )

    lang = SimpleNamespace(
        file_finder=lambda _path: [str(dart_file)],
        zone_map=None,
    )
    entries, metrics = phase_firebase(tmp_path, lang)
    assert metrics["firebase"] == 1
    assert len(entries) > 0
    assert any(e.get("detail", {}).get("kind") == "firebase_hardcoded_collection" for e in entries)
