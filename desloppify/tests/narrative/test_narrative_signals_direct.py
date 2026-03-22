"""Direct tests for desloppify.intelligence.narrative.signals helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from desloppify.base.enums import Status
from desloppify.intelligence.narrative.signals import (
    compute_badge_status,
    compute_primary_action,
    compute_risk_flags,
    compute_strict_target,
    compute_verification_step,
    compute_why_now,
    count_open_by_detector,
    history_for_lang,
    resolve_badge_path,
    resolve_target_strict_score,
    scoped_issues,
    strict_overall_scores,
)


# ---------------------------------------------------------------------------
# resolve_target_strict_score
# ---------------------------------------------------------------------------


def test_resolve_target_strict_score_default_when_no_config() -> None:
    target, warning = resolve_target_strict_score(None)
    assert isinstance(target, int)
    assert warning is None


def test_resolve_target_strict_score_uses_config_value() -> None:
    target, warning = resolve_target_strict_score({"target_strict_score": 85})
    assert target == 85
    assert warning is None


def test_resolve_target_strict_score_invalid_string() -> None:
    target, warning = resolve_target_strict_score({"target_strict_score": "not_a_number"})
    assert warning is not None
    assert "Invalid" in warning


def test_resolve_target_strict_score_out_of_range() -> None:
    target, warning = resolve_target_strict_score({"target_strict_score": 999})
    assert warning is not None


# ---------------------------------------------------------------------------
# compute_strict_target
# ---------------------------------------------------------------------------


def test_compute_strict_target_unavailable_when_no_score() -> None:
    result = compute_strict_target(None, None)
    assert result["state"] == "unavailable"
    assert result["current"] is None
    assert result["gap"] is None


def test_compute_strict_target_below() -> None:
    result = compute_strict_target(70.0, {"target_strict_score": 90})
    assert result["state"] == "below"
    assert result["current"] == 70.0
    assert result["gap"] > 0


def test_compute_strict_target_above() -> None:
    result = compute_strict_target(95.0, {"target_strict_score": 90})
    assert result["state"] == "above"
    assert result["gap"] < 0


def test_compute_strict_target_at() -> None:
    result = compute_strict_target(90.0, {"target_strict_score": 90})
    assert result["state"] == "at"
    assert result["gap"] == 0.0


# ---------------------------------------------------------------------------
# count_open_by_detector
# ---------------------------------------------------------------------------


def test_count_open_by_detector_empty() -> None:
    assert count_open_by_detector({}) == {}


def test_count_open_by_detector_counts_open_only() -> None:
    issues = {
        "a": {"status": Status.OPEN, "detector": "unused"},
        "b": {"status": "fixed", "detector": "unused"},
        "c": {"status": Status.OPEN, "detector": "smells"},
    }
    counts = count_open_by_detector(issues)
    assert counts["unused"] == 1
    assert counts["smells"] == 1


def test_count_open_by_detector_skips_suppressed() -> None:
    issues = {
        "a": {"status": Status.OPEN, "detector": "unused", "suppressed": True},
    }
    assert count_open_by_detector(issues) == {}


def test_count_open_by_detector_merges_structural() -> None:
    issues = {
        "a": {"status": Status.OPEN, "detector": "flat_dirs"},
        "b": {"status": Status.OPEN, "detector": "gods"},
    }
    counts = count_open_by_detector(issues)
    assert counts.get("structural", 0) == 2


# ---------------------------------------------------------------------------
# compute_primary_action
# ---------------------------------------------------------------------------


def test_compute_primary_action_empty() -> None:
    assert compute_primary_action([]) is None


def test_compute_primary_action_no_command() -> None:
    assert compute_primary_action([{"command": "", "description": "x"}]) is None


def test_compute_primary_action_picks_first() -> None:
    actions = [
        {"command": "desloppify scan", "description": "run scan"},
        {"command": "desloppify review", "description": "review"},
    ]
    result = compute_primary_action(actions)
    assert result is not None
    assert result["command"] == "desloppify scan"


# ---------------------------------------------------------------------------
# compute_why_now
# ---------------------------------------------------------------------------


def test_compute_why_now_uses_strategy_hint() -> None:
    result = compute_why_now("maintenance", {"hint": "fix it now"}, None)
    assert result == "fix it now"


def test_compute_why_now_uses_primary_action_description() -> None:
    action = {"command": "desloppify scan", "description": "run the scan"}
    result = compute_why_now("maintenance", {}, action)
    assert result == "run the scan"


def test_compute_why_now_uses_phase_default() -> None:
    result = compute_why_now("first_scan", {}, None)
    assert "baseline" in result.lower()


def test_compute_why_now_unknown_phase() -> None:
    result = compute_why_now("unknown_phase", {}, None)
    assert "highest-impact" in result.lower()


# ---------------------------------------------------------------------------
# compute_verification_step
# ---------------------------------------------------------------------------


def test_compute_verification_step() -> None:
    result = compute_verification_step("anything")
    assert result["command"] == "desloppify scan"
    assert result["reason"]


# ---------------------------------------------------------------------------
# compute_risk_flags
# ---------------------------------------------------------------------------


def test_compute_risk_flags_empty() -> None:
    state: dict = {"ignore_integrity": {}}
    flags = compute_risk_flags(state, {})
    assert flags == []


def test_compute_risk_flags_high_suppression() -> None:
    state: dict = {"ignore_integrity": {"suppressed_pct": 45.0, "ignored": 0}}
    flags = compute_risk_flags(state, {})
    assert len(flags) == 1
    assert flags[0]["type"] == "high_ignore_suppression"
    assert flags[0]["severity"] == "high"


def test_compute_risk_flags_wontfix_gap() -> None:
    state: dict = {"ignore_integrity": {}}
    debt = {"wontfix_count": 10, "overall_gap": 2.0}
    flags = compute_risk_flags(state, debt)
    assert len(flags) == 1
    assert flags[0]["type"] == "wontfix_gap"


def test_compute_risk_flags_sorted_by_severity() -> None:
    state: dict = {"ignore_integrity": {"suppressed_pct": 45.0, "ignored": 0}}
    debt = {"wontfix_count": 10, "overall_gap": 6.0}
    flags = compute_risk_flags(state, debt)
    assert len(flags) == 2
    # Both high severity
    assert all(f["severity"] == "high" for f in flags)


# ---------------------------------------------------------------------------
# history_for_lang
# ---------------------------------------------------------------------------


def test_history_for_lang_no_filter() -> None:
    history = [{"lang": "dart"}, {"lang": "typescript"}]
    assert history_for_lang(history, None) == history


def test_history_for_lang_filters() -> None:
    history = [
        {"lang": "dart"},
        {"lang": "typescript"},
        {"lang": None},
    ]
    result = history_for_lang(history, "dart")
    assert len(result) == 2
    assert all(e.get("lang") in ("dart", None) for e in result)


# ---------------------------------------------------------------------------
# resolve_badge_path
# ---------------------------------------------------------------------------


def test_resolve_badge_path_default(tmp_path: Path) -> None:
    with patch("desloppify.intelligence.narrative.signals._load_config", return_value={}):
        rel_path, full_path = resolve_badge_path(tmp_path)
    assert rel_path == "scorecard.png"
    assert full_path == tmp_path / "scorecard.png"


def test_resolve_badge_path_custom(tmp_path: Path) -> None:
    with patch(
        "desloppify.intelligence.narrative.signals._load_config",
        return_value={"badge_path": "docs/badge.png"},
    ):
        rel_path, full_path = resolve_badge_path(tmp_path)
    assert rel_path == "docs/badge.png"
    assert full_path == tmp_path / "docs" / "badge.png"


# ---------------------------------------------------------------------------
# scoped_issues
# ---------------------------------------------------------------------------


def test_scoped_issues_returns_all_when_no_scan_path() -> None:
    state = {"issues": {"a": {"file": "x.py"}, "b": {"file": "y.py"}}}
    result = scoped_issues(state)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# strict_overall_scores
# ---------------------------------------------------------------------------


def test_strict_overall_scores_missing() -> None:
    state: dict = {}
    strict, overall = strict_overall_scores(state)
    assert strict is None
    assert overall is None
