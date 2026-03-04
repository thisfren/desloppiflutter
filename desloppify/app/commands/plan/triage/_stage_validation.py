"""Validation and guardrail helpers for triage stage workflow."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.plan.triage_playbook import TRIAGE_CMD_ORGANIZE
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import (
    collect_triage_input,
    detect_recurring_patterns,
    extract_issue_citations,
    save_plan,
)
from desloppify.state import utc_now

from .confirmations import _MIN_ATTESTATION_LEN, _validate_attestation
from .display import _show_plan_summary
from .helpers import _manual_clusters_with_issues, _observe_dimension_breakdown
from .stage_helpers import _unenriched_clusters
from ._stage_rendering import _print_new_issues_since_last


def _auto_confirm_observe_if_attested(
    *,
    plan: dict,
    stages: dict,
    attestation: str | None,
    triage_input,
) -> bool:
    if stages["observe"].get("confirmed_at"):
        return True
    if not attestation or len(attestation.strip()) < _MIN_ATTESTATION_LEN:
        print(colorize("  Cannot reflect: observe stage not confirmed.", "red"))
        print(colorize("  Run: desloppify plan triage --confirm observe", "dim"))
        print(colorize("  Or pass --attestation to auto-confirm observe inline.", "dim"))
        return False
    _by_dim, dim_names = _observe_dimension_breakdown(triage_input)
    validation_err = _validate_attestation(
        attestation.strip(),
        "observe",
        dimensions=dim_names,
    )
    if validation_err:
        print(colorize(f"  {validation_err}", "red"))
        return False
    stages["observe"]["confirmed_at"] = utc_now()
    stages["observe"]["confirmed_text"] = attestation.strip()
    save_plan(plan)
    print(colorize("  ✓ Observe auto-confirmed via --attestation.", "green"))
    return True


def _validate_recurring_dimension_mentions(
    *,
    report: str,
    recurring_dims: list[str],
    recurring: dict,
) -> bool:
    if not recurring_dims:
        return True
    report_lower = report.lower()
    mentioned = [dim for dim in recurring_dims if dim.lower() in report_lower]
    if mentioned:
        return True
    print(colorize("  Recurring patterns detected but not addressed in report:", "red"))
    for dim in recurring_dims:
        info = recurring[dim]
        print(
            colorize(
                f"    {dim}: {len(info['resolved'])} resolved, "
                f"{len(info['open'])} still open — potential loop",
                "yellow",
            )
        )
    print(
        colorize(
            "  Your report must mention at least one recurring dimension name.",
            "dim",
        )
    )
    return False


def _require_reflect_stage_for_organize(stages: dict) -> bool:
    if "reflect" in stages:
        return True
    if "observe" not in stages:
        print(colorize("  Cannot organize: observe stage not complete.", "red"))
        print(colorize('  Run: desloppify plan triage --stage observe --report "..."', "dim"))
        return False
    print(colorize("  Cannot organize: reflect stage not complete.", "red"))
    print(colorize('  Run: desloppify plan triage --stage reflect --report "..."', "dim"))
    return False


def _auto_confirm_reflect_for_organize(
    *,
    args: argparse.Namespace,
    plan: dict,
    stages: dict,
    attestation: str | None,
) -> bool:
    if stages["reflect"].get("confirmed_at"):
        return True
    if not attestation or len(attestation.strip()) < _MIN_ATTESTATION_LEN:
        print(colorize("  Cannot organize: reflect stage not confirmed.", "red"))
        print(colorize("  Run: desloppify plan triage --confirm reflect", "dim"))
        print(colorize("  Or pass --attestation to auto-confirm reflect inline.", "dim"))
        return False

    runtime = command_runtime(args)
    triage_input = collect_triage_input(plan, runtime.state)
    recurring = detect_recurring_patterns(
        triage_input.open_issues,
        triage_input.resolved_issues,
    )
    _by_dim, observe_dims = _observe_dimension_breakdown(triage_input)
    reflect_dims = sorted(set((list(recurring.keys()) if recurring else []) + observe_dims))
    reflect_clusters = [
        name for name in plan.get("clusters", {}) if not plan["clusters"][name].get("auto")
    ]
    validation_err = _validate_attestation(
        attestation.strip(),
        "reflect",
        dimensions=reflect_dims,
        cluster_names=reflect_clusters,
    )
    if validation_err:
        print(colorize(f"  {validation_err}", "red"))
        return False
    stages["reflect"]["confirmed_at"] = utc_now()
    stages["reflect"]["confirmed_text"] = attestation.strip()
    save_plan(plan)
    print(colorize("  ✓ Reflect auto-confirmed via --attestation.", "green"))
    return True


def _manual_clusters_or_error(plan: dict) -> list[str] | None:
    manual_clusters = _manual_clusters_with_issues(plan)
    if manual_clusters:
        return manual_clusters
    any_clusters = [
        name for name, cluster in plan.get("clusters", {}).items() if cluster.get("issue_ids")
    ]
    if any_clusters:
        print(colorize("  Cannot organize: only auto-clusters exist.", "red"))
        print(colorize("  Create manual clusters that group issues by root cause:", "dim"))
    else:
        print(colorize("  Cannot organize: no clusters with issues exist.", "red"))
    print(colorize('    desloppify plan cluster create <name> --description "..."', "dim"))
    print(colorize("    desloppify plan cluster add <name> <issue-patterns>", "dim"))
    return None


def _clusters_enriched_or_error(plan: dict) -> bool:
    gaps = _unenriched_clusters(plan)
    if not gaps:
        return True
    print(colorize(f"  Cannot organize: {len(gaps)} cluster(s) need enrichment.", "red"))
    for name, missing in gaps:
        print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
    print()
    print(colorize("  Each cluster needs a description and action steps:", "dim"))
    print(
        colorize(
            '    desloppify plan cluster update <name> --description "what this cluster addresses" '
            '--steps "step 1" "step 2"',
            "dim",
        )
    )
    return False


def _organize_report_or_error(report: str | None) -> str | None:
    if not report:
        print(colorize("  --report is required for --stage organize.", "red"))
        print(colorize("  Summarize your prioritized organization:", "dim"))
        print(colorize("  - Did you defer contradictory issues before clustering?", "dim"))
        print(colorize("  - What clusters did you create and why?", "dim"))
        print(
            colorize(
                "  - Explicit priority ordering: which cluster 1st, 2nd, 3rd and why?",
                "dim",
            )
        )
        print(colorize("  - What depends on what? What unblocks the most?", "dim"))
        return None
    if len(report) < 100:
        print(colorize(f"  Report too short: {len(report)} chars (minimum 100).", "red"))
        print(colorize("  Explain what you organized, your priorities, and focus order.", "dim"))
        return None
    return report


def _require_organize_stage_for_complete(
    *,
    plan: dict,
    meta: dict,
    stages: dict,
) -> bool:
    if "organize" in stages:
        return True
    if "observe" not in stages:
        print(colorize("  Cannot complete: no stages done yet.", "red"))
        print(colorize('  Start with: desloppify plan triage --stage observe --report "..."', "dim"))
        return False

    print(colorize("  Cannot complete: organize stage not done.", "red"))
    gaps = _unenriched_clusters(plan)
    if gaps:
        print(colorize(f"  {len(gaps)} cluster(s) still need enrichment:", "yellow"))
        for name, missing in gaps:
            print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
        print(
            colorize(
                '  Fix: desloppify plan cluster update <name> --description "..." --steps "step1" "step2"',
                "dim",
            )
        )
        print(colorize(f"  Then: {TRIAGE_CMD_ORGANIZE}", "dim"))
    else:
        manual = _manual_clusters_with_issues(plan)
        if manual:
            print(colorize("  Clusters are enriched. Record the organize stage first:", "dim"))
            print(colorize(f"    {TRIAGE_CMD_ORGANIZE}", "dim"))
        else:
            print(colorize("  Create enriched clusters first, then record organize:", "dim"))
            print(colorize(f"    {TRIAGE_CMD_ORGANIZE}", "dim"))
    if meta.get("strategy_summary"):
        print(
            colorize(
                '  Or fast-track: --confirm-existing --note "why plan is still valid" --strategy "..."',
                "dim",
            )
        )
    return False


def _auto_confirm_organize_for_complete(
    *,
    plan: dict,
    stages: dict,
    attestation: str | None,
) -> bool:
    if stages["organize"].get("confirmed_at"):
        return True
    if not attestation or len(attestation.strip()) < _MIN_ATTESTATION_LEN:
        print(colorize("  Cannot complete: organize stage not confirmed.", "red"))
        print(colorize("  Run: desloppify plan triage --confirm organize", "dim"))
        print(colorize("  Or pass --attestation to auto-confirm organize inline.", "dim"))
        return False

    organize_clusters = [
        name for name in plan.get("clusters", {}) if not plan["clusters"][name].get("auto")
    ]
    validation_err = _validate_attestation(
        attestation.strip(),
        "organize",
        cluster_names=organize_clusters,
    )
    if validation_err:
        print(colorize(f"  {validation_err}", "red"))
        return False
    stages["organize"]["confirmed_at"] = utc_now()
    stages["organize"]["confirmed_text"] = attestation.strip()
    save_plan(plan)
    print(colorize("  ✓ Organize auto-confirmed via --attestation.", "green"))
    return True


def _completion_clusters_valid(plan: dict) -> bool:
    manual_clusters = _manual_clusters_with_issues(plan)
    if not manual_clusters:
        any_clusters = [
            name
            for name, cluster in plan.get("clusters", {}).items()
            if cluster.get("issue_ids")
        ]
        if not any_clusters:
            print(colorize("  Cannot complete: no clusters with issues exist.", "red"))
            print(colorize('  Create clusters: desloppify plan cluster create <name> --description "..."', "dim"))
            return False

    gaps = _unenriched_clusters(plan)
    if not gaps:
        return True
    print(colorize(f"  Cannot complete: {len(gaps)} cluster(s) still need enrichment.", "red"))
    for name, missing in gaps:
        print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
    print(
        colorize(
            '  Fix: desloppify plan cluster update <name> --description "..." --steps "step1" "step2"',
            "dim",
        )
    )
    return False


def _resolve_completion_strategy(
    strategy: str | None,
    *,
    meta: dict,
) -> str | None:
    if strategy:
        return strategy
    print(colorize("  --strategy is required.", "red"))
    existing = meta.get("strategy_summary", "")
    if existing:
        print(colorize(f"  Current strategy: {existing}", "dim"))
        print(colorize('  Use --strategy "same" to keep it, or provide a new summary.', "dim"))
    else:
        print(
            colorize(
                '  Provide --strategy "execution plan describing priorities, ordering, and verification approach"',
                "dim",
            )
        )
    return None


def _completion_strategy_valid(strategy: str) -> bool:
    if strategy.strip().lower() == "same":
        return True
    if len(strategy.strip()) >= 200:
        return True
    print(colorize(f"  Strategy too short: {len(strategy.strip())} chars (minimum 200).", "red"))
    print(colorize("  The strategy should describe:", "dim"))
    print(colorize("    - Execution order and priorities", "dim"))
    print(colorize("    - What each cluster accomplishes", "dim"))
    print(colorize("    - How to verify the work is correct", "dim"))
    return False


def _require_prior_strategy_for_confirm(meta: dict) -> bool:
    if meta.get("strategy_summary", ""):
        return True
    print(colorize("  Cannot confirm existing: no prior triage has been completed.", "red"))
    print(colorize("  The full OBSERVE → REFLECT → ORGANIZE → COMMIT flow is required the first time.", "dim"))
    print(colorize(f"  Create and enrich clusters, then: {TRIAGE_CMD_ORGANIZE}", "dim"))
    return False


def _confirm_existing_stages_valid(
    *,
    stages: dict,
    has_only_additions: bool,
    si,
) -> bool:
    if has_only_additions:
        _print_new_issues_since_last(si)
        return True
    if "observe" not in stages:
        print(colorize("  Cannot confirm existing: observe stage not complete.", "red"))
        print(colorize("  You must read issues first.", "dim"))
        print(colorize('  Run: desloppify plan triage --stage observe --report "..."', "dim"))
        return False
    if "reflect" not in stages:
        print(colorize("  Cannot confirm existing: reflect stage not complete.", "red"))
        print(colorize("  You must compare against completed work first.", "dim"))
        print(colorize('  Run: desloppify plan triage --stage reflect --report "..."', "dim"))
        return False
    return True


def _confirm_note_valid(note: str | None) -> bool:
    if not note:
        print(colorize("  --note is required for confirm-existing.", "red"))
        print(colorize('  Explain why the existing plan is still valid (min 100 chars).', "dim"))
        return False
    if len(note) < 100:
        print(colorize(f"  Note too short: {len(note)} chars (minimum 100).", "red"))
        return False
    return True


def _resolve_confirm_existing_strategy(
    strategy: str | None,
    *,
    has_only_additions: bool,
    meta: dict,
) -> str | None:
    if strategy:
        return strategy
    if has_only_additions:
        return "same"
    print(colorize("  --strategy is required.", "red"))
    existing = meta.get("strategy_summary", "")
    if existing:
        print(colorize('  Use --strategy "same" to keep it, or provide a new summary.', "dim"))
    return None


def _confirm_strategy_valid(strategy: str) -> bool:
    if strategy.strip().lower() == "same":
        return True
    if len(strategy.strip()) >= 200:
        return True
    print(colorize(f"  Strategy too short: {len(strategy.strip())} chars (minimum 200).", "red"))
    return False


def _confirmed_text_or_error(
    *,
    plan: dict,
    state: dict,
    confirmed: str | None,
) -> str | None:
    if confirmed and len(confirmed.strip()) >= _MIN_ATTESTATION_LEN:
        return confirmed.strip()
    print(colorize("  Current plan:", "bold"))
    _show_plan_summary(plan, state)
    if confirmed:
        print(
            colorize(
                f"\n  --confirmed text too short ({len(confirmed.strip())} chars, min {_MIN_ATTESTATION_LEN}).",
                "red",
            )
        )
    print(colorize('\n  Add --confirmed "I validate this plan..." to proceed.', "dim"))
    return None


def _note_cites_new_issues_or_error(note: str, si) -> bool:
    new_ids = si.new_since_last
    if not new_ids:
        return True
    valid_ids = set(si.open_issues.keys())
    cited = extract_issue_citations(note, valid_ids)
    new_cited = cited & new_ids
    if new_cited:
        return True
    print(colorize("  Note must cite at least 1 new/changed issue.", "red"))
    print(colorize(f"  {len(new_ids)} new issue(s) since last triage:", "dim"))
    for fid in sorted(new_ids)[:5]:
        print(colorize(f"    {fid}", "dim"))
    if len(new_ids) > 5:
        print(colorize(f"    ... and {len(new_ids) - 5} more", "dim"))
    return False


__all__ = [
    "_auto_confirm_observe_if_attested",
    "_auto_confirm_organize_for_complete",
    "_auto_confirm_reflect_for_organize",
    "_clusters_enriched_or_error",
    "_completion_clusters_valid",
    "_completion_strategy_valid",
    "_confirm_existing_stages_valid",
    "_confirm_note_valid",
    "_confirm_strategy_valid",
    "_confirmed_text_or_error",
    "_manual_clusters_or_error",
    "_note_cites_new_issues_or_error",
    "_organize_report_or_error",
    "_require_organize_stage_for_complete",
    "_require_prior_strategy_for_confirm",
    "_require_reflect_stage_for_organize",
    "_resolve_completion_strategy",
    "_resolve_confirm_existing_strategy",
    "_validate_recurring_dimension_mentions",
]
