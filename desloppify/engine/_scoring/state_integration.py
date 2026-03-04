"""Bridge between state persistence and scoring computation.

This module owns the score-recomputation step that runs before state is written.
The dependency direction is: _scoring/state_integration -> _state (reads state),
_scoring/state_integration -> _scoring (calls scoring functions).
State persistence calls this module, never the reverse.
"""

from __future__ import annotations

from copy import deepcopy

from desloppify.base.coercions import coerce_confidence
from desloppify.base.enums import issue_status_tokens
from desloppify.engine._scoring.detection import merge_potentials
from desloppify.engine._scoring.policy.core import matches_target_score
from desloppify.engine._scoring.results.core import (
    compute_health_score,
    compute_score_bundle,
)
from desloppify.engine._state.filtering import path_scoped_issues
from desloppify.engine._state.schema import StateModel, ensure_state_defaults
from desloppify.languages._framework.base.types import ScanCoverageRecord

_EMPTY_COUNTERS = tuple(sorted(issue_status_tokens()))
_SUBJECTIVE_TARGET_RESET_THRESHOLD = 2


def _resolve_lang_from_state(state: StateModel) -> str | None:
    """Best-effort language detection from state (scan_history > lang_capabilities)."""
    history = state.get("scan_history")
    if isinstance(history, list):
        for entry in reversed(history):
            if isinstance(entry, dict):
                lang = entry.get("lang")
                if isinstance(lang, str) and lang.strip():
                    return lang.strip().lower()
    capabilities = state.get("lang_capabilities")
    if isinstance(capabilities, dict) and len(capabilities) == 1:
        only_lang = next(iter(capabilities.keys()))
        if isinstance(only_lang, str) and only_lang.strip():
            return only_lang.strip().lower()
    return None


def _count_issues(issues: dict) -> tuple[dict[str, int], dict[int, dict[str, int]]]:
    """Tally per-status counters and per-tier breakdowns."""
    counters = dict.fromkeys(_EMPTY_COUNTERS, 0)
    tier_stats: dict[int, dict[str, int]] = {}

    for issue in issues.values():
        if issue.get("suppressed"):
            continue
        status = issue["status"]
        tier = issue.get("tier", 3)
        counters[status] = counters.get(status, 0) + 1
        tier_counter = tier_stats.setdefault(tier, dict.fromkeys(_EMPTY_COUNTERS, 0))
        tier_counter[status] = tier_counter.get(status, 0) + 1

    return counters, tier_stats


def _coerce_subjective_score(value: dict | float | int | str | None) -> float:
    """Normalize a subjective assessment score payload to a 0-100 float."""
    raw = value.get("score", 0) if isinstance(value, dict) else value
    try:
        score = float(raw)
    except (TypeError, ValueError):
        score = 0.0
    return max(0.0, min(100.0, score))


def _subjective_target_matches(
    subjective_assessments: dict, *, target: float
) -> list[str]:
    """Return dimension keys whose subjective score matches the target band."""
    matches = [
        dimension
        for dimension, payload in subjective_assessments.items()
        if matches_target_score(_coerce_subjective_score(payload), target)
    ]
    return sorted(matches)


def _subjective_integrity_baseline(target: float | None) -> dict[str, object]:
    """Create baseline subjective-integrity metadata for scan/reporting output."""
    return {
        "status": "disabled" if target is None else "pass",
        "target_score": None if target is None else round(float(target), 2),
        "matched_count": 0,
        "matched_dimensions": [],
        "reset_dimensions": [],
    }


def _apply_subjective_integrity_policy(
    subjective_assessments: dict,
    *,
    target: float,
) -> tuple[dict, dict[str, object]]:
    """Apply anti-gaming penalties for subjective scores clustered on the target."""
    normalized_target = max(0.0, min(100.0, float(target)))
    matched_dimensions = _subjective_target_matches(
        subjective_assessments,
        target=normalized_target,
    )
    meta = _subjective_integrity_baseline(normalized_target)
    meta["matched_count"] = len(matched_dimensions)
    meta["matched_dimensions"] = matched_dimensions

    if len(matched_dimensions) < _SUBJECTIVE_TARGET_RESET_THRESHOLD:
        meta["status"] = "warn" if matched_dimensions else "pass"
        return subjective_assessments, meta

    adjusted = deepcopy(subjective_assessments)
    for dimension in matched_dimensions:
        payload = adjusted.get(dimension)
        if isinstance(payload, dict):
            payload["score"] = 0.0
            payload["integrity_penalty"] = "target_match_reset"
        else:
            adjusted[dimension] = {
                "score": 0.0,
                "integrity_penalty": "target_match_reset",
            }

    meta["status"] = "penalized"
    meta["reset_dimensions"] = matched_dimensions
    return adjusted, meta


def _aggregate_scores(dim_scores: dict) -> dict[str, float]:
    """Derive the four aggregate scores from dimension-level data."""
    mechanical = {
        n: d
        for n, d in dim_scores.items()
        if "subjective_assessment" not in d.get("detectors", {})
    }
    return {
        "overall_score": compute_health_score(dim_scores),
        "strict_score": compute_health_score(dim_scores, score_key="strict_score"),
        "objective_score": compute_health_score(mechanical),
        "verified_strict_score": compute_health_score(
            mechanical,
            score_key="verified_strict_score",
        ),
    }


def _active_scan_coverage(state: StateModel) -> ScanCoverageRecord:
    scan_coverage = state.get("scan_coverage", {})
    if not isinstance(scan_coverage, dict) or not scan_coverage:
        return {}

    lang_name = state.get("lang")
    if isinstance(lang_name, str) and lang_name:
        payload = scan_coverage.get(lang_name, {})
        return payload if isinstance(payload, dict) else {}

    if len(scan_coverage) == 1:
        only = next(iter(scan_coverage.values()))
        return only if isinstance(only, dict) else {}
    return {}


def _apply_scan_coverage_to_dimension_scores(
    state: StateModel,
    *,
    dimension_scores: dict[str, dict],
) -> None:
    coverage_payload = _active_scan_coverage(state)
    detectors_payload = coverage_payload.get("detectors", {})
    if not isinstance(detectors_payload, dict):
        state["score_confidence"] = {
            "status": "full",
            "confidence": 1.0,
            "detectors": [],
            "dimensions": [],
        }
        return

    reduced_detectors: dict[str, dict[str, object]] = {}
    for detector, raw in detectors_payload.items():
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status", "full")).lower()
        confidence = coerce_confidence(raw.get("confidence"), default=1.0)
        if status != "reduced" and confidence >= 1.0:
            continue
        reduced_detectors[str(detector)] = dict(raw)

    reduced_dimensions: list[str] = []
    score_confidence_detectors: list[dict[str, object]] = []
    for detector, payload in reduced_detectors.items():
        score_confidence_detectors.append(
            {
                "detector": detector,
                "status": str(payload.get("status", "reduced")),
                "confidence": round(
                    coerce_confidence(payload.get("confidence"), default=1.0),
                    2,
                ),
                "summary": str(payload.get("summary", "") or ""),
                "impact": str(payload.get("impact", "") or ""),
                "remediation": str(payload.get("remediation", "") or ""),
                "tool": str(payload.get("tool", "") or ""),
                "reason": str(payload.get("reason", "") or ""),
            }
        )

    for dim_name, dim_data in dimension_scores.items():
        if not isinstance(dim_data, dict):
            continue
        detectors = dim_data.get("detectors", {})
        if not isinstance(detectors, dict):
            continue

        impacts: list[dict[str, object]] = []
        for detector_name, detector_meta in detectors.items():
            reduced = reduced_detectors.get(str(detector_name))
            if not isinstance(detector_meta, dict):
                continue
            if reduced is None:
                detector_meta.pop("coverage_status", None)
                detector_meta.pop("coverage_confidence", None)
                detector_meta.pop("coverage_summary", None)
                continue
            confidence = coerce_confidence(reduced.get("confidence"), default=1.0)
            status = str(reduced.get("status", "reduced"))
            summary = str(reduced.get("summary", "") or "")
            detector_meta["coverage_status"] = status
            detector_meta["coverage_confidence"] = round(confidence, 2)
            detector_meta["coverage_summary"] = summary
            impacts.append(
                {
                    "detector": str(detector_name),
                    "status": status,
                    "confidence": round(confidence, 2),
                    "summary": summary,
                }
            )

        if not impacts:
            dim_data.pop("coverage_status", None)
            dim_data.pop("coverage_confidence", None)
            dim_data.pop("coverage_impacts", None)
            continue

        reduced_dimensions.append(str(dim_name))
        dim_data["coverage_status"] = "reduced"
        dim_data["coverage_confidence"] = round(
            min(
                coerce_confidence(item.get("confidence"), default=1.0)
                for item in impacts
            ),
            2,
        )
        dim_data["coverage_impacts"] = impacts

    if not score_confidence_detectors:
        state["score_confidence"] = {
            "status": "full",
            "confidence": 1.0,
            "detectors": [],
            "dimensions": [],
        }
        return

    state["score_confidence"] = {
        "status": "reduced",
        "confidence": round(
            min(
                coerce_confidence(item.get("confidence"), default=1.0)
                for item in score_confidence_detectors
            ),
            2,
        ),
        "detectors": score_confidence_detectors,
        "dimensions": sorted(set(reduced_dimensions)),
    }


def _update_objective_health(
    state: StateModel,
    issues: dict,
    *,
    subjective_integrity_target: float | None = None,
) -> None:
    """Compute canonical score tuple from current detector issues/potentials."""
    pots = state.get("potentials", {})
    if not pots:
        return

    merged = merge_potentials(pots)
    if not merged:
        return

    subjective_assessments = state.get("subjective_assessments") or None
    integrity_target = (
        max(0.0, min(100.0, float(subjective_integrity_target)))
        if isinstance(subjective_integrity_target, int | float)
        else None
    )
    integrity_meta = _subjective_integrity_baseline(integrity_target)
    if subjective_assessments and integrity_target is not None:
        subjective_assessments, integrity_meta = _apply_subjective_integrity_policy(
            subjective_assessments,
            target=integrity_target,
        )
    state["subjective_integrity"] = integrity_meta

    has_active_checks = any((count or 0) > 0 for count in merged.values())
    if not has_active_checks and not subjective_assessments:
        state["dimension_scores"] = {}
        state["overall_score"] = 100.0
        state["objective_score"] = 100.0
        state["strict_score"] = 100.0
        state["verified_strict_score"] = 100.0
        return

    allowed_subjective: set[str] | None = None
    lang_name = _resolve_lang_from_state(state)
    if lang_name:
        try:
            from desloppify.intelligence.review.dimensions.data import (
                load_dimensions_for_lang,
            )

            dims, _, _ = load_dimensions_for_lang(lang_name)
            if dims:
                allowed_subjective = set(dims)
        except (ImportError, AttributeError) as exc:
            _ = exc

    bundle = compute_score_bundle(
        issues,
        merged,
        subjective_assessments=subjective_assessments,
        allowed_subjective_dimensions=allowed_subjective,
    )
    lenient_scores = bundle.dimension_scores
    strict_scores = bundle.strict_dimension_scores
    verified_strict_scores = bundle.verified_strict_dimension_scores

    prev_dim_scores = dict(state.get("dimension_scores", {}))

    state["dimension_scores"] = {
        name: dict(
            score=lenient_scores[name]["score"],
            strict_score=strict_scores[name]["score"],
            verified_strict_score=verified_strict_scores[name]["score"],
            checks=lenient_scores[name]["checks"],
            failing=lenient_scores[name]["failing"],
            tier=lenient_scores[name]["tier"],
            detectors=lenient_scores[name].get("detectors", {}),
        )
        for name in lenient_scores
    }
    for data in state["dimension_scores"].values():
        data["strict"] = data["strict_score"]

    for dim_name, prev_data in prev_dim_scores.items():
        if dim_name in state["dimension_scores"]:
            continue
        if not isinstance(prev_data, dict):
            continue
        if "subjective_assessment" in prev_data.get("detectors", {}):
            continue
        carried = {**prev_data, "carried_forward": True}
        carried.setdefault("score", 0.0)
        carried.setdefault("strict", carried.get("score", 0.0))
        carried.setdefault(
            "strict_score",
            carried.get("strict", carried.get("score", 0.0)),
        )
        carried.setdefault(
            "verified_strict_score",
            carried.get(
                "strict_score",
                carried.get("strict", carried.get("score", 0.0)),
            ),
        )
        state["dimension_scores"][dim_name] = carried

    _apply_scan_coverage_to_dimension_scores(
        state,
        dimension_scores=state["dimension_scores"],
    )
    state.update(_aggregate_scores(state["dimension_scores"]))


def recompute_stats(
    state: StateModel,
    scan_path: str | None = None,
    *,
    subjective_integrity_target: float | None = None,
) -> None:
    """Recompute stats and canonical health scores from issues."""
    ensure_state_defaults(state)
    issues = path_scoped_issues(state["issues"], scan_path)
    counters, tier_stats = _count_issues(issues)
    state["stats"] = {
        "total": sum(counters.values()),
        **counters,
        "by_tier": {
            str(tier): tier_counts for tier, tier_counts in sorted(tier_stats.items())
        },
    }
    _update_objective_health(
        state,
        issues,
        subjective_integrity_target=subjective_integrity_target,
    )


__all__ = [
    "_count_issues",
    "_update_objective_health",
    "recompute_stats",
]
