"""State-path and scan-gating helpers for command modules."""

from __future__ import annotations
import argparse
from pathlib import Path

from desloppify.app.commands.helpers.lang import auto_detect_lang_name
from desloppify.base.output.terminal import colorize
from desloppify.base.discovery.paths import get_project_root


def _sole_existing_lang_state_file() -> Path | None:
    """Return the only existing language-specific state file, if unambiguous."""
    state_dir = get_project_root() / ".desloppify"
    if not state_dir.exists():
        return None
    candidates = sorted(path for path in state_dir.glob("state-*.json") if path.is_file())
    if len(candidates) == 1:
        return candidates[0]
    return None


def _allow_lang_state_fallback(args: argparse.Namespace) -> bool:
    """Whether command can safely fallback to the sole existing lang state file."""
    # Scan should always honor detected/explicit language mapping to avoid cross-lang merges.
    return getattr(args, "command", None) != "scan"


def state_path(args: argparse.Namespace) -> Path | None:
    """Get state file path from args, or None for default."""
    path_arg = getattr(args, "state", None)
    if path_arg:
        return Path(path_arg)
    lang_name = getattr(args, "lang", None)
    if not lang_name:
        lang_name = auto_detect_lang_name(args)
    if lang_name:
        resolved = get_project_root() / ".desloppify" / f"state-{lang_name}.json"
        if resolved.exists() or not _allow_lang_state_fallback(args):
            return resolved
        fallback = _sole_existing_lang_state_file()
        if fallback is not None:
            return fallback
        return resolved

    if _allow_lang_state_fallback(args):
        fallback = _sole_existing_lang_state_file()
        if fallback is not None:
            return fallback
    return None


def require_completed_scan(state: dict) -> bool:
    """Return True when the state contains at least one completed scan."""
    has_completed_scan = bool(state.get("last_scan"))
    if not has_completed_scan:
        print(colorize("No scans yet. Run: desloppify scan", "yellow"))
    return has_completed_scan


def _saved_plan_review_ids(plan: dict | None) -> list[str]:
    """Return review/concerns IDs recoverable from saved plan metadata."""
    if not isinstance(plan, dict):
        return []

    ordered: list[str] = []
    seen: set[str] = set()

    def _append(issue_id: object) -> None:
        if not isinstance(issue_id, str):
            return
        normalized = issue_id.strip()
        if not normalized:
            return
        if not (
            normalized.startswith("review::")
            or normalized.startswith("concerns::")
        ):
            return
        if normalized in seen:
            return
        seen.add(normalized)
        ordered.append(normalized)

    for issue_id in plan.get("queue_order", []):
        _append(issue_id)

    clusters = plan.get("clusters", {})
    if isinstance(clusters, dict):
        for cluster in clusters.values():
            if not isinstance(cluster, dict):
                continue
            for issue_id in cluster.get("issue_ids", []):
                _append(issue_id)
            for step in cluster.get("action_steps", []):
                if not isinstance(step, dict):
                    continue
                for issue_id in step.get("issue_refs", []):
                    _append(issue_id)

    return ordered


def has_saved_plan_without_scan(state: dict, plan: dict | None) -> bool:
    """Whether a saved plan can be resumed without a current scan state.

    This is a narrow recovery path for plan/triage surfaces when ``plan.json``
    still contains user-authored queue/cluster metadata but the matching
    ``state-*.json`` file is gone.
    """
    if state.get("last_scan"):
        return False
    if not isinstance(plan, dict):
        return False
    meta = plan.get("epic_triage_meta")
    triage_meta = meta if isinstance(meta, dict) else {}
    return bool(
        plan.get("queue_order")
        or plan.get("clusters")
        or triage_meta.get("triage_stages")
        or triage_meta.get("strategy_summary")
    )


def recover_state_from_saved_plan(state: dict, plan: dict | None) -> dict:
    """Hydrate placeholder review issues from a saved plan when scan state is gone."""
    if not has_saved_plan_without_scan(state, plan):
        return state

    recovered = dict(state)
    issues = state.get("issues", {})
    recovered_issues = dict(issues) if isinstance(issues, dict) else {}

    for issue_id in _saved_plan_review_ids(plan):
        if issue_id in recovered_issues:
            continue
        parts = issue_id.split("::")
        detector = "concerns" if issue_id.startswith("concerns::") else "review"
        recovered_issues[issue_id] = {
            "status": "open",
            "detector": detector,
            "file": parts[1] if len(parts) > 1 else "",
            "summary": issue_id,
            "confidence": "medium",
            "tier": 2,
            "detail": {
                "dimension": "unknown",
                "recovered_from_plan": True,
            },
        }

    recovered["issues"] = recovered_issues
    return recovered
