"""Assessment storage helpers for review imports."""

from __future__ import annotations

from typing import Any

from desloppify.base.text_utils import is_numeric
from desloppify.engine._state.schema import StateModel, utc_now
from desloppify.intelligence.review.dimensions import normalize_dimension_name


def _clean_judgment(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Validate and clean a dimension judgment payload. Returns None if empty."""
    strengths_raw = raw.get("strengths")
    strengths: list[str] = []
    if isinstance(strengths_raw, list):
        strengths = [
            str(s).strip()
            for s in strengths_raw[:5]
            if isinstance(s, str) and str(s).strip()
        ]

    issue_character = ""
    ic = raw.get("issue_character")
    if isinstance(ic, str) and ic.strip():
        issue_character = ic.strip()

    score_rationale = ""
    sr = raw.get("score_rationale")
    if isinstance(sr, str) and sr.strip():
        score_rationale = sr.strip()

    if not strengths and not issue_character and not score_rationale:
        return None

    result: dict[str, Any] = {}
    if strengths:
        result["strengths"] = strengths
    if issue_character:
        result["issue_character"] = issue_character
    if score_rationale:
        result["score_rationale"] = score_rationale
    return result


def store_assessments(
    state: StateModel,
    assessments: dict[str, Any],
    source: str,
    *,
    utc_now_fn=utc_now,
    dimension_judgment: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Store dimension assessments in state.

    *assessments*: ``{dim_name: score}`` or ``{dim_name: {score, ...}}``.
    *source*: ``"per_file"`` or ``"holistic"``.
    *dimension_judgment*: optional ``{dim_name: {strengths, issue_character, score_rationale}}``.

    Holistic assessments overwrite per-file for the same dimension.
    Per-file assessments don't overwrite holistic.
    """
    store = state.setdefault("subjective_assessments", {})
    now = utc_now_fn()
    judgments = dimension_judgment or {}

    for dimension_name, value in assessments.items():
        value_obj = value if isinstance(value, dict) else {}
        score = value if is_numeric(value) else value_obj.get("score", 0)
        score = max(0, min(100, score))
        dimension_key = normalize_dimension_name(str(dimension_name))
        if not dimension_key:
            continue

        existing = store.get(dimension_key)
        if existing and existing.get("source") == "holistic" and source == "per_file":
            continue

        cleaned_components: list[str] = []
        components = value_obj.get("components")
        if isinstance(components, list):
            cleaned_components = [
                str(item).strip()
                for item in components
                if isinstance(item, str) and item.strip()
            ]

        component_scores = value_obj.get("component_scores")
        cleaned_scores: dict[str, float] = {}
        if isinstance(component_scores, dict):
            for key, raw in component_scores.items():
                if not isinstance(key, str) or not key.strip():
                    continue
                if not is_numeric(raw):
                    continue
                cleaned_scores[key.strip()] = round(max(0.0, min(100.0, float(raw))), 1)

        # Clean and attach judgment if available
        judgment_raw = judgments.get(dimension_name) or judgments.get(dimension_key)
        cleaned_judgment: dict[str, Any] | None = None
        if isinstance(judgment_raw, dict):
            cleaned_judgment = _clean_judgment(judgment_raw)

        store[dimension_key] = {
            "score": score,
            "source": source,
            "assessed_at": now,
            **({"components": cleaned_components} if cleaned_components else {}),
            **({"component_scores": cleaned_scores} if cleaned_scores else {}),
            **({"judgment": cleaned_judgment} if cleaned_judgment else {}),
        }
