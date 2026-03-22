"""Direct tests for desloppify.app.commands.scan.reporting.subjective helpers."""

from __future__ import annotations

from desloppify.app.commands.scan.reporting.subjective import (
    SubjectiveFollowup,
    build_subjective_followup,
    coerce_notice_count,
    coerce_str_keys,
    flatten_cli_keys,
    render_subjective_names,
    render_subjective_scores,
    subjective_entries_for_dimension_keys,
    subjective_integrity_followup,
    subjective_integrity_notice_lines,
    subjective_rerun_command,
)


# ---------------------------------------------------------------------------
# flatten_cli_keys
# ---------------------------------------------------------------------------


def test_flatten_cli_keys_empty() -> None:
    assert flatten_cli_keys([]) == ""


def test_flatten_cli_keys_merges_across_items() -> None:
    items = [
        {"cli_keys": ["a", "b"]},
        {"cli_keys": ["b", "c"]},
    ]
    result = flatten_cli_keys(items)
    assert result == "a,b,c"


def test_flatten_cli_keys_respects_max_items() -> None:
    items = [
        {"cli_keys": ["a"]},
        {"cli_keys": ["b"]},
        {"cli_keys": ["c"]},
        {"cli_keys": ["d"]},
    ]
    result = flatten_cli_keys(items, max_items=2)
    assert "d" not in result
    assert "c" not in result


# ---------------------------------------------------------------------------
# render_subjective_scores
# ---------------------------------------------------------------------------


def test_render_subjective_scores_single() -> None:
    entries = [{"name": "Elegance", "strict": 75.0}]
    result = render_subjective_scores(entries)
    assert "Elegance" in result
    assert "75.0%" in result


def test_render_subjective_scores_uses_score_fallback() -> None:
    entries = [{"name": "Quality", "score": 80.0}]
    result = render_subjective_scores(entries)
    assert "80.0%" in result


# ---------------------------------------------------------------------------
# render_subjective_names
# ---------------------------------------------------------------------------


def test_render_subjective_names_under_max() -> None:
    entries = [{"name": "A"}, {"name": "B"}]
    result = render_subjective_names(entries, max_names=5)
    assert result == "A, B"


def test_render_subjective_names_over_max() -> None:
    entries = [{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}]
    result = render_subjective_names(entries, max_names=2)
    assert "+2 more" in result


# ---------------------------------------------------------------------------
# coerce_notice_count
# ---------------------------------------------------------------------------


def test_coerce_notice_count_int() -> None:
    assert coerce_notice_count(5) == 5


def test_coerce_notice_count_bool() -> None:
    assert coerce_notice_count(True) == 0


def test_coerce_notice_count_string() -> None:
    assert coerce_notice_count("3") == 3


def test_coerce_notice_count_invalid_string() -> None:
    assert coerce_notice_count("abc") == 0


def test_coerce_notice_count_float() -> None:
    assert coerce_notice_count(3.7) == 3


def test_coerce_notice_count_none() -> None:
    assert coerce_notice_count(None) == 0


# ---------------------------------------------------------------------------
# coerce_str_keys
# ---------------------------------------------------------------------------


def test_coerce_str_keys_list() -> None:
    assert coerce_str_keys(["a", "b"]) == ["a", "b"]


def test_coerce_str_keys_filters_non_strings() -> None:
    assert coerce_str_keys(["a", 1, "", "b"]) == ["a", "b"]


def test_coerce_str_keys_non_iterable() -> None:
    assert coerce_str_keys("not_a_list") == []


def test_coerce_str_keys_set() -> None:
    result = coerce_str_keys({"a", "b"})
    assert set(result) == {"a", "b"}


# ---------------------------------------------------------------------------
# subjective_rerun_command
# ---------------------------------------------------------------------------


def test_subjective_rerun_command_with_open_issues() -> None:
    items = [{"failing": 1, "cli_keys": ["elegance"]}]
    result = subjective_rerun_command(items)
    assert "show review" in result


def test_subjective_rerun_command_no_prior_review() -> None:
    items = [{"failing": 0, "cli_keys": ["elegance"]}]
    result = subjective_rerun_command(items, has_prior_review=False)
    assert "--prepare" in result
    assert "--force-review-rerun" not in result


def test_subjective_rerun_command_with_prior_review() -> None:
    items = [{"failing": 0, "cli_keys": ["elegance"]}]
    result = subjective_rerun_command(items, has_prior_review=None)
    assert "--force-review-rerun" in result


# ---------------------------------------------------------------------------
# subjective_entries_for_dimension_keys
# ---------------------------------------------------------------------------


def test_subjective_entries_for_dimension_keys_maps_existing() -> None:
    entries = [{"name": "Elegance", "cli_keys": ["elegance"], "score": 80.0}]
    result = subjective_entries_for_dimension_keys(["elegance"], entries)
    assert len(result) == 1
    assert result[0]["name"] == "Elegance"


def test_subjective_entries_for_dimension_keys_creates_placeholder() -> None:
    result = subjective_entries_for_dimension_keys(["missing_key"], [])
    assert len(result) == 1
    assert result[0]["score"] == 0.0
    assert result[0]["cli_keys"] == ["missing_key"]


# ---------------------------------------------------------------------------
# subjective_integrity_followup
# ---------------------------------------------------------------------------


def test_subjective_integrity_followup_no_integrity_state() -> None:
    state: dict = {}
    entries = [{"name": "Elegance", "score": 80.0, "strict": 80.0, "placeholder": False, "cli_keys": ["elegance"]}]
    result = subjective_integrity_followup(state, entries, threshold=90)
    # 80 < 90, so not at_target
    assert result is None


def test_subjective_integrity_followup_penalized() -> None:
    state: dict = {
        "subjective_integrity": {
            "status": "penalized",
            "reset_dimensions": ["elegance"],
        }
    }
    entries = [{"name": "Elegance", "score": 80.0, "strict": 80.0, "placeholder": False, "cli_keys": ["elegance"]}]
    result = subjective_integrity_followup(state, entries)
    assert result is not None
    assert result["status"] == "penalized"


# ---------------------------------------------------------------------------
# subjective_integrity_notice_lines
# ---------------------------------------------------------------------------


def test_subjective_integrity_notice_lines_empty() -> None:
    assert subjective_integrity_notice_lines(None) == []


def test_subjective_integrity_notice_lines_penalized() -> None:
    notice = {"status": "penalized", "count": 2, "target": 90.0, "rendered": "A, B", "command": "`cmd`"}
    lines = subjective_integrity_notice_lines(notice)
    assert len(lines) > 0
    assert any("WARNING" in msg for _, msg in lines)


def test_subjective_integrity_notice_lines_warn() -> None:
    notice = {"status": "warn", "count": 1, "target": 90.0, "rendered": "A", "command": "`cmd`"}
    lines = subjective_integrity_notice_lines(notice)
    assert len(lines) > 0


def test_subjective_integrity_notice_lines_at_target() -> None:
    notice = {"status": "at_target", "count": 1, "command": "`cmd`"}
    lines = subjective_integrity_notice_lines(notice)
    assert len(lines) > 0


def test_subjective_integrity_notice_lines_unknown_status() -> None:
    notice = {"status": "unknown_status"}
    lines = subjective_integrity_notice_lines(notice)
    assert lines == []


# ---------------------------------------------------------------------------
# build_subjective_followup
# ---------------------------------------------------------------------------


def test_build_subjective_followup_returns_dataclass() -> None:
    state: dict = {}
    entries = [
        {"name": "Elegance", "score": 70.0, "strict": 70.0, "placeholder": False, "cli_keys": ["elegance"]},
    ]
    result = build_subjective_followup(state, entries, threshold=90)
    assert isinstance(result, SubjectiveFollowup)
    assert len(result.low_assessed) == 1
    assert result.threshold == 90.0


def test_build_subjective_followup_no_low_entries() -> None:
    state: dict = {}
    entries = [
        {"name": "Elegance", "score": 95.0, "strict": 95.0, "placeholder": False, "cli_keys": ["elegance"]},
    ]
    result = build_subjective_followup(state, entries, threshold=90)
    assert result.low_assessed == []
