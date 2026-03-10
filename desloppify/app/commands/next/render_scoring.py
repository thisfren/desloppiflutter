"""Score-impact and explain rendering helpers for next terminal output."""

from __future__ import annotations


def _normalized_dimension_key(value: str | None) -> str:
    return str(value or "").lower().replace(" ", "_")


def render_dimension_context(
    detector: str,
    dim_scores: dict,
    *,
    colorize_fn,
    get_dimension_for_detector_fn,
) -> None:
    if not dim_scores:
        return
    dimension = get_dimension_for_detector_fn(detector)
    if not dimension or dimension.name not in dim_scores:
        return
    dimension_score = dim_scores[dimension.name]
    strict_val = dimension_score.get("strict", dimension_score["score"])
    print(
        colorize_fn(
            f"\n  Dimension: {dimension.name} — {dimension_score['score']:.1f}% "
            f"(strict: {strict_val:.1f}%) "
            f"({dimension_score.get('failing', 0)} of {dimension_score['checks']:,} checks failing)",
            "dim",
        )
    )


def render_detector_impact_estimate(
    detector: str,
    dim_scores: dict,
    potentials: dict,
    *,
    colorize_fn,
    log_fn,
    compute_score_impact_fn,
    get_dimension_for_detector_fn,
) -> None:
    try:
        impact = compute_score_impact_fn(dim_scores, potentials, detector, issues_to_fix=1)
        if impact > 0:
            print(
                colorize_fn(
                    f"  Impact: fixing this is worth ~+{impact:.1f} pts on overall score",
                    "cyan",
                )
            )
            return

        dimension = get_dimension_for_detector_fn(detector)
        if not dimension or dimension.name not in dim_scores:
            return
        issues = dim_scores[dimension.name].get("failing", 0)
        if issues <= 1:
            return
        bulk = compute_score_impact_fn(dim_scores, potentials, detector, issues_to_fix=issues)
        if bulk > 0:
            print(
                colorize_fn(
                    f"  Impact: fixing all {issues} {detector} issues → ~+{bulk:.1f} pts",
                    "cyan",
                )
            )
    except (ImportError, TypeError, ValueError, KeyError) as exc:
        log_fn(f"  score impact estimate skipped: {exc}")


def render_review_dimension_drag(
    item: dict,
    dim_scores: dict,
    *,
    colorize_fn,
    log_fn,
    compute_health_breakdown_fn,
) -> None:
    try:
        dim_key = item.get("detail", {}).get("dimension", "")
        if not dim_key:
            return
        breakdown = compute_health_breakdown_fn(dim_scores)
        target_key = _normalized_dimension_key(dim_key)
        for entry in breakdown.get("entries", []):
            if not isinstance(entry, dict):
                continue
            if _normalized_dimension_key(entry.get("name", "")) != target_key:
                continue
            drag = float(entry.get("overall_drag", 0) or 0)
            if drag > 0.01:
                print(
                    colorize_fn(
                        f"  Dimension drag: {entry['name']} costs -{drag:.2f} pts on overall score",
                        "cyan",
                    )
                )
            return
    except (ImportError, TypeError, ValueError, KeyError) as exc:
        log_fn(f"  dimension drag estimate skipped: {exc}")


def render_score_impact(
    item: dict,
    dim_scores: dict,
    potentials: dict | None,
    *,
    colorize_fn,
    log_fn,
    compute_health_breakdown_fn,
    compute_score_impact_fn,
    get_dimension_for_detector_fn,
) -> None:
    detector = item.get("detector", "")
    render_dimension_context(
        detector,
        dim_scores,
        colorize_fn=colorize_fn,
        get_dimension_for_detector_fn=get_dimension_for_detector_fn,
    )
    if potentials and detector and dim_scores:
        render_detector_impact_estimate(
            detector,
            dim_scores,
            potentials,
            colorize_fn=colorize_fn,
            log_fn=log_fn,
            compute_score_impact_fn=compute_score_impact_fn,
            get_dimension_for_detector_fn=get_dimension_for_detector_fn,
        )
        return
    if detector == "review" and dim_scores:
        render_review_dimension_drag(
            item,
            dim_scores,
            colorize_fn=colorize_fn,
            log_fn=log_fn,
            compute_health_breakdown_fn=compute_health_breakdown_fn,
        )


def _explain_base_text(
    item: dict,
    detail: dict,
    confidence: str,
) -> str:
    count_weight = item.get("explain", {}).get("count", int(detail.get("count", 0) or 0))
    return (
        f"ranked by confidence={confidence}, "
        f"count={count_weight}, id={item.get('id', '')}"
    )


def _detector_dimension_explain(
    detector: str,
    dim_scores: dict,
    *,
    get_dimension_for_detector_fn,
) -> str:
    if not dim_scores or not detector:
        return ""
    dimension = get_dimension_for_detector_fn(detector)
    if not dimension or dimension.name not in dim_scores:
        return ""
    ds = dim_scores[dimension.name]
    return (
        f". Dimension: {dimension.name} at {ds['score']:.1f}% "
        f"({ds.get('failing', 0)} open issues)"
    )


def _format_score_value(value) -> str:
    if isinstance(value, int | float):
        return f"{value:.1f}"
    return str(value)


def _review_dimension_explain(item: dict, dim_scores: dict) -> str:
    if item.get("detector") != "review" or not dim_scores:
        return ""
    dim_key = _normalized_dimension_key(item.get("detail", {}).get("dimension", ""))
    if not dim_key:
        return ""
    for ds_name, ds_data in dim_scores.items():
        if _normalized_dimension_key(ds_name) != dim_key:
            continue
        score_str = _format_score_value(ds_data.get("score", "?"))
        return f". Subjective dimension: {ds_name} at {score_str}%"
    return ""


def render_item_explain(
    item: dict,
    detail: dict,
    confidence: str,
    dim_scores: dict,
    *,
    colorize_fn,
    get_dimension_for_detector_fn,
) -> None:
    detector = item.get("detector", "")
    explanation = item.get("explain", {})
    base = _explain_base_text(
        item,
        detail,
        confidence,
    )
    base += _detector_dimension_explain(
        detector,
        dim_scores,
        get_dimension_for_detector_fn=get_dimension_for_detector_fn,
    )
    base += _review_dimension_explain(item, dim_scores)
    policy = explanation.get("policy")
    if policy:
        base = f"{base}. {policy}"
    print(colorize_fn(f"  explain: {base}", "dim"))


__all__ = ["render_item_explain", "render_score_impact"]
