"""Handler for ``plan triage`` subcommand."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.app.commands.plan.triage import confirmations as _confirmations_mod
from desloppify.app.commands.plan.triage import display as _display_mod
from desloppify.app.commands.plan.triage import helpers as _helpers_mod
from desloppify.app.commands.plan.triage import _stage_completion_commands as _completion_mod
from desloppify.app.commands.plan.triage import _stage_flow_commands as _flow_mod
from desloppify.app.commands.plan.triage import _stage_validation as _validation_mod
from desloppify.app.commands.plan.triage_playbook import TRIAGE_CMD_OBSERVE
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import (
    append_log_entry,
    build_triage_prompt,
    collect_triage_input,
    detect_recurring_patterns,
    extract_issue_citations,
    load_plan,
    save_plan,
)

_MIN_ATTESTATION_LEN = _confirmations_mod._MIN_ATTESTATION_LEN
_validate_attestation = _confirmations_mod._validate_attestation
_triage_coverage = _helpers_mod._triage_coverage


_TRIAGE_SUBMODULES = (
    _helpers_mod, _display_mod, _confirmations_mod,
    _flow_mod, _completion_mod, _validation_mod,
)


def _sync_triage_module_bindings() -> None:
    """Propagate monkeypatch-friendly bindings into split triage modules.

    Each submodule imports ``command_runtime``, ``load_plan``, etc. at the
    top level.  Tests monkeypatch those names on *this* handler module; this
    function copies the (potentially patched) references into every submodule
    that already has the name, so mocks propagate automatically.

    Adding a new submodule: append it to ``_TRIAGE_SUBMODULES``.
    Adding a new patchable function: add it to the ``bindings`` dict below
    *and* import it at the top of this file — submodules that import the same
    name will pick it up automatically via ``hasattr``.
    """
    bindings = {
        "command_runtime": command_runtime,
        "save_plan": save_plan,
        "load_plan": load_plan,
        "collect_triage_input": collect_triage_input,
        "detect_recurring_patterns": detect_recurring_patterns,
        "append_log_entry": append_log_entry,
        "extract_issue_citations": extract_issue_citations,
    }
    for mod in _TRIAGE_SUBMODULES:
        for name, fn in bindings.items():
            if hasattr(mod, name):
                setattr(mod, name, fn)


def _cmd_triage_start(args: argparse.Namespace) -> None:
    """Manually inject triage stage IDs into the queue and clear prior stages."""
    _sync_triage_module_bindings()
    plan = load_plan()

    if _helpers_mod._has_triage_in_queue(plan):
        print(colorize("  Planning mode stages are already in the queue.", "yellow"))
        meta = plan.get("epic_triage_meta", {})
        stages = meta.get("triage_stages", {})
        if stages:
            print(
                colorize(
                    f"  {len(stages)} stage(s) in progress — clearing to restart.", "yellow"
                )
            )
            meta["triage_stages"] = {}
            _helpers_mod._inject_triage_stages(plan)
            save_plan(plan)
            append_log_entry(
                plan,
                "triage_start",
                actor="user",
                detail={"action": "restart", "cleared_stages": list(stages.keys())},
            )
            save_plan(plan)
            print(colorize("  Stages cleared. Begin with observe:", "green"))
        else:
            print(colorize("  Begin with observe:", "green"))
        print(colorize(f"    {TRIAGE_CMD_OBSERVE}", "dim"))
        return

    _helpers_mod._inject_triage_stages(plan)
    meta = plan.setdefault("epic_triage_meta", {})
    meta["triage_stages"] = {}
    save_plan(plan)

    append_log_entry(plan, "triage_start", actor="user", detail={"action": "start"})
    save_plan(plan)

    runtime = command_runtime(args)
    si = collect_triage_input(plan, runtime.state)
    print(colorize("  Planning mode started (4 stages queued).", "green"))
    print(f"  Open review issues: {len(si.open_issues)}")
    print(colorize("  Begin with observe:", "dim"))
    print(colorize(f"    {TRIAGE_CMD_OBSERVE}", "dim"))


def cmd_plan_triage(args: argparse.Namespace) -> None:
    """Run epic triage: staged workflow OBSERVE → REFLECT → ORGANIZE → COMMIT."""
    _sync_triage_module_bindings()
    runtime = command_runtime(args)
    state = runtime.state
    if not require_completed_scan(state):
        return

    if getattr(args, "start", False):
        _cmd_triage_start(args)
        return
    if getattr(args, "confirm", None):
        _confirmations_mod._cmd_confirm_stage(args)
        return
    if getattr(args, "complete", False):
        _completion_mod._cmd_triage_complete(args)
        return
    if getattr(args, "confirm_existing", False):
        _completion_mod._cmd_confirm_existing(args)
        return

    stage = getattr(args, "stage", None)
    if stage == "observe":
        _flow_mod._cmd_stage_observe(args)
        return
    if stage == "reflect":
        _flow_mod._cmd_stage_reflect(args)
        return
    if stage == "organize":
        _flow_mod._cmd_stage_organize(args)
        return

    if getattr(args, "dry_run", False):
        plan = load_plan()
        si = collect_triage_input(plan, state)
        prompt = build_triage_prompt(si)
        print(colorize("  Epic triage — dry run", "bold"))
        print(colorize("  " + "─" * 60, "dim"))
        print(f"  Open review issues: {len(si.open_issues)}")
        print(f"  Existing epics: {len(si.existing_epics)}")
        print(f"  New since last: {len(si.new_since_last)}")
        print(f"  Resolved since last: {len(si.resolved_since_last)}")
        print(colorize("\n  Prompt that would be sent to LLM:", "dim"))
        print()
        print(prompt)
        return

    _display_mod._cmd_triage_dashboard(args)

__all__ = [
    "_MIN_ATTESTATION_LEN",
    "_triage_coverage",
    "_validate_attestation",
    "cmd_plan_triage",
]
