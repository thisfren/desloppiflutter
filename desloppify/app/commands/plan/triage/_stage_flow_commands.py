"""Observe/reflect/organize command handlers for triage flow."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import (
    append_log_entry,
    collect_triage_input,
    detect_recurring_patterns,
    extract_issue_citations,
    load_plan,
    save_plan,
)
from desloppify.state import utc_now

from .display import _print_organize_result, _print_reflect_result
from .helpers import (
    _cascade_clear_later_confirmations,
    _has_triage_in_queue,
    _inject_triage_stages,
    _print_cascade_clear_feedback,
)
from ._stage_records import (
    _record_observe_stage,
    _record_organize_stage,
    _resolve_reusable_report,
)
from ._stage_rendering import (
    _print_observe_report_requirement,
    _print_reflect_report_requirement,
)
from ._stage_validation import (
    _auto_confirm_observe_if_attested,
    _auto_confirm_reflect_for_organize,
    _clusters_enriched_or_error,
    _manual_clusters_or_error,
    _organize_report_or_error,
    _require_reflect_stage_for_organize,
    _validate_recurring_dimension_mentions,
)


def _cmd_stage_observe(args: argparse.Namespace) -> None:
    """Record the OBSERVE stage: agent analyses themes and root causes.

    No citation gate — the point is genuine analysis, not ID-stuffing.
    Just requires a 100-char report describing what the agent observed.
    """
    report: str | None = getattr(args, "report", None)

    runtime = command_runtime(args)
    state = runtime.state
    plan = load_plan()

    # Auto-start: inject triage stage IDs if not present
    if not _has_triage_in_queue(plan):
        _inject_triage_stages(plan)
        meta = plan.setdefault("epic_triage_meta", {})
        meta["triage_stages"] = {}
        save_plan(plan)
        print(colorize("  Planning mode auto-started (4 stages queued).", "cyan"))

    meta = plan.setdefault("epic_triage_meta", {})
    stages = meta.setdefault("triage_stages", {})
    existing_stage = stages.get("observe")

    # Jump-back: reuse existing report if no --report provided
    report, is_reuse = _resolve_reusable_report(report, existing_stage)
    if not report:
        _print_observe_report_requirement()
        return

    si = collect_triage_input(plan, state)
    issue_count = len(si.open_issues)

    # Edge case: 0 issues
    if issue_count == 0:
        cleared = _record_observe_stage(
            stages,
            report=report,
            issue_count=0,
            cited_ids=[],
            existing_stage=existing_stage,
            is_reuse=is_reuse,
        )
        save_plan(plan)
        print(colorize("  Observe stage recorded (no issues to analyse).", "green"))
        if is_reuse:
            print(colorize("  Observe data preserved (no changes).", "dim"))
            if cleared:
                _print_cascade_clear_feedback(cleared, stages)
        return

    # Validation: report length (no citation counting)
    min_chars = 50 if issue_count <= 3 else 100
    if len(report) < min_chars:
        print(colorize(f"  Report too short: {len(report)} chars (minimum {min_chars}).", "red"))
        print(colorize("  Describe themes, root causes, contradictions, and how issues relate.", "dim"))
        return

    # Save stage (still extract citations for analytics, but don't gate on them)
    valid_ids = set(si.open_issues.keys())
    cited = extract_issue_citations(report, valid_ids)

    cleared = _record_observe_stage(
        stages,
        report=report,
        issue_count=issue_count,
        cited_ids=sorted(cited),
        existing_stage=existing_stage,
        is_reuse=is_reuse,
    )

    save_plan(plan)

    append_log_entry(
        plan,
        "triage_observe",
        actor="user",
        detail={"issue_count": issue_count, "cited_ids": sorted(cited), "reuse": is_reuse},
    )
    save_plan(plan)

    print(
        colorize(
            f"  Observe stage recorded: {issue_count} issues analysed.",
            "green",
        )
    )
    if is_reuse:
        print(colorize("  Observe data preserved (no changes).", "dim"))
        if cleared:
            _print_cascade_clear_feedback(cleared, stages)
    else:
        print(colorize("  Now confirm your analysis.", "yellow"))
        print(colorize("    desloppify plan triage --confirm observe", "dim"))


def _cmd_stage_reflect(args: argparse.Namespace) -> None:
    """Record the REFLECT stage: compare current issues against completed work.

    Forces the agent to consider what was previously resolved and whether
    similar issues are recurring. Requires a 100-char report (50 if ≤3 issues).
    If recurring patterns are detected, the report must mention at least one
    recurring dimension name.
    """
    report: str | None = getattr(args, "report", None)
    attestation: str | None = getattr(args, "attestation", None)

    runtime = command_runtime(args)
    state = runtime.state
    plan = load_plan()

    if not _has_triage_in_queue(plan):
        print(colorize("  No planning stages in the queue — nothing to reflect on.", "yellow"))
        return

    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})

    # Jump-back: reuse existing report if no --report provided
    existing_stage = stages.get("reflect")
    is_reuse = False
    if not report and existing_stage and existing_stage.get("report"):
        report = existing_stage["report"]
        is_reuse = True
    elif not report:
        _print_reflect_report_requirement()
        return

    if "observe" not in stages:
        print(colorize("  Cannot reflect: observe stage not complete.", "red"))
        print(colorize('  Run: desloppify plan triage --stage observe --report "..."', "dim"))
        return

    si = collect_triage_input(plan, state)

    # Fold-confirm: auto-confirm observe if attestation provided
    if not _auto_confirm_observe_if_attested(
        plan=plan,
        stages=stages,
        attestation=attestation,
        triage_input=si,
    ):
        return

    issue_count = len(si.open_issues)

    # Validation: report length
    min_chars = 50 if issue_count <= 3 else 100
    if len(report) < min_chars:
        print(colorize(f"  Report too short: {len(report)} chars (minimum {min_chars}).", "red"))
        print(colorize("  Describe how current issues relate to previously completed work.", "dim"))
        return

    # Detect recurring patterns
    recurring = detect_recurring_patterns(si.open_issues, si.resolved_issues)
    recurring_dims = sorted(recurring.keys())

    # If recurring patterns exist, report must mention at least one dimension
    if not _validate_recurring_dimension_mentions(
        report=report,
        recurring_dims=recurring_dims,
        recurring=recurring,
    ):
        return

    # Save stage
    stages = meta.setdefault("triage_stages", {})
    reflect_stage = {
        "stage": "reflect",
        "report": report,
        "cited_ids": [],
        "timestamp": utc_now(),
        "issue_count": issue_count,
        "recurring_dims": recurring_dims,
    }
    stages["reflect"] = reflect_stage

    # Jump-back: preserve or clear confirmation
    if is_reuse and existing_stage and existing_stage.get("confirmed_at"):
        stages["reflect"]["confirmed_at"] = existing_stage["confirmed_at"]
        stages["reflect"]["confirmed_text"] = existing_stage.get("confirmed_text", "")
    cleared = _cascade_clear_later_confirmations(stages, "reflect")

    save_plan(plan)

    append_log_entry(
        plan,
        "triage_reflect",
        actor="user",
        detail={
            "issue_count": issue_count,
            "recurring_dims": recurring_dims,
            "reuse": is_reuse,
        },
    )
    save_plan(plan)

    _print_reflect_result(
        issue_count=issue_count,
        recurring_dims=recurring_dims,
        recurring=recurring,
        report=report,
        is_reuse=is_reuse,
        cleared=cleared,
        stages=stages,
    )


def _cmd_stage_organize(args: argparse.Namespace) -> None:
    """Record the ORGANIZE stage: validates cluster enrichment.

    Instead of gating on a text report, validates that the plan data
    itself has been enriched: each manual cluster needs description +
    action_steps. This forces the agent to actually think about each
    cluster's execution plan.
    """
    report: str | None = getattr(args, "report", None)
    attestation: str | None = getattr(args, "attestation", None)

    plan = load_plan()

    if not _has_triage_in_queue(plan):
        print(colorize("  No planning stages in the queue — nothing to organize.", "yellow"))
        return

    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})

    # Jump-back: reuse existing report if no --report provided
    existing_stage = stages.get("organize")
    is_reuse = False
    if not report and existing_stage and existing_stage.get("report"):
        report = existing_stage["report"]
        is_reuse = True

    if not _require_reflect_stage_for_organize(stages):
        return

    # Fold-confirm: auto-confirm reflect if attestation provided
    if not _auto_confirm_reflect_for_organize(
        args=args,
        plan=plan,
        stages=stages,
        attestation=attestation,
    ):
        return

    # Validate: at least 1 manual cluster with issues
    manual_clusters = _manual_clusters_or_error(plan)
    if manual_clusters is None:
        return

    # Validate: all manual clusters are enriched
    if not _clusters_enriched_or_error(plan):
        return

    report = _organize_report_or_error(report)
    if report is None:
        return

    stages = meta.setdefault("triage_stages", {})
    cleared = _record_organize_stage(
        stages,
        report=report,
        issue_count=len(manual_clusters),
        existing_stage=existing_stage,
        is_reuse=is_reuse,
    )

    save_plan(plan)

    append_log_entry(
        plan,
        "triage_organize",
        actor="user",
        detail={"cluster_count": len(manual_clusters), "reuse": is_reuse},
    )
    save_plan(plan)

    _print_organize_result(
        manual_clusters=manual_clusters,
        plan=plan,
        report=report,
        is_reuse=is_reuse,
        cleared=cleared,
        stages=stages,
    )


__all__ = [
    "_cmd_stage_observe",
    "_cmd_stage_organize",
    "_cmd_stage_reflect",
]
