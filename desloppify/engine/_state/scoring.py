"""State suppression accounting helpers.

Scoring recomputation lives in :mod:`desloppify.engine._scoring.state_integration`.
"""

from __future__ import annotations

__all__ = [
    "suppression_metrics",
]

from desloppify.engine._state.schema import StateModel


def _empty_suppression_metrics() -> dict[str, int | float]:
    return {
        "last_ignored": 0,
        "last_raw_issues": 0,
        "last_suppressed_pct": 0.0,
        "last_ignore_patterns": 0,
        "recent_scans": 0,
        "recent_ignored": 0,
        "recent_raw_issues": 0,
        "recent_suppressed_pct": 0.0,
    }


def suppression_metrics(state: StateModel, *, window: int = 5) -> dict[str, int | float]:
    """Summarize ignore suppression from recent scan history."""
    history = state.get("scan_history", [])
    if not history:
        return _empty_suppression_metrics()

    scans_with_suppression = [
        entry
        for entry in history
        if isinstance(entry, dict)
        and (
            "ignored" in entry
            or "raw_issues" in entry
            or "suppressed_pct" in entry
            or "ignore_patterns" in entry
        )
    ]
    if not scans_with_suppression:
        return _empty_suppression_metrics()

    recent = scans_with_suppression[-max(1, window) :]
    last = recent[-1]

    recent_ignored = sum(int(entry.get("ignored", 0) or 0) for entry in recent)
    recent_raw = sum(int(entry.get("raw_issues", 0) or 0) for entry in recent)
    recent_pct = round(recent_ignored / recent_raw * 100, 1) if recent_raw else 0.0

    last_ignored = int(last.get("ignored", 0) or 0)
    last_raw = int(last.get("raw_issues", 0) or 0)
    if "suppressed_pct" in last:
        last_pct = round(float(last.get("suppressed_pct") or 0.0), 1)
    else:
        last_pct = round(last_ignored / last_raw * 100, 1) if last_raw else 0.0

    return {
        "last_ignored": last_ignored,
        "last_raw_issues": last_raw,
        "last_suppressed_pct": last_pct,
        "last_ignore_patterns": int(last.get("ignore_patterns", 0) or 0),
        "recent_scans": len(recent),
        "recent_ignored": recent_ignored,
        "recent_raw_issues": recent_raw,
        "recent_suppressed_pct": recent_pct,
    }
