"""Triage stage pipeline entrypoint — Codex subprocess runner and Claude orchestrator."""

from __future__ import annotations

import argparse

from desloppify.base.output.terminal import colorize

from ..services import TriageServices
from .orchestrator_claude import run_claude_orchestrator
from .orchestrator_codex_pipeline import run_codex_pipeline
from .orchestrator_common import STAGES


def _parse_only_stages(raw: str | None) -> list[str]:
    """Parse --only-stages comma-separated string into validated stage list."""
    if not raw:
        return list(STAGES)
    stages = [s.strip().lower() for s in raw.split(",") if s.strip()]
    for stage in stages:
        if stage not in STAGES:
            raise ValueError(f"Unknown stage: {stage!r}. Valid: {', '.join(STAGES)}")
    return stages


def do_run_triage_stages(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Run triage stages via the selected runner."""
    runner = str(getattr(args, "runner", "codex")).strip().lower()

    try:
        stages_to_run = _parse_only_stages(getattr(args, "only_stages", None))
    except ValueError as exc:
        print(colorize(f"  {exc}", "red"))
        return

    if runner == "claude":
        run_claude_orchestrator(args, services=services)
    elif runner == "codex":
        run_codex_pipeline(args, stages_to_run=stages_to_run, services=services)
    else:
        print(colorize(f"  Unknown runner: {runner}. Use 'codex' or 'claude'.", "red"))


__all__ = ["_parse_only_stages", "do_run_triage_stages"]
