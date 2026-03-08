"""Per-stage subagent prompt builders for triage runners."""

from __future__ import annotations

import argparse
from pathlib import Path

from desloppify.base.discovery.paths import get_project_root
from desloppify.engine.plan import TriageInput, build_triage_prompt

from ..services import TriageServices, default_triage_services
from .stage_prompts_instructions import (
    _CLI_REFERENCE,
    _PREAMBLE,
    _STAGES,
    _STAGE_INSTRUCTIONS,
)
from .stage_prompts_observe import (
    _observe_batch_instructions,
    build_observe_batch_prompt,
)
from .stage_prompts_sense import (
    build_sense_check_content_prompt,
    build_sense_check_structure_prompt,
)
from .stage_prompts_validation import _validation_requirements


def build_stage_prompt(
    stage: str,
    triage_input: TriageInput,
    prior_reports: dict[str, str],
    *,
    repo_root: Path,
) -> str:
    """Build a complete subagent prompt for a triage stage."""
    parts: list[str] = []

    # Preamble
    parts.append(_PREAMBLE.format(stage=stage.upper(), repo_root=repo_root))

    # Issue data
    issue_data = build_triage_prompt(triage_input)
    parts.append("## Issue Data\n\n" + issue_data)

    # Prior stage reports
    if prior_reports:
        parts.append("## Prior Stage Reports\n")
        for prior_stage, report in prior_reports.items():
            parts.append(f"### {prior_stage.upper()} Report\n{report}\n")

    # Stage-specific instructions
    instruction_fn = _STAGE_INSTRUCTIONS.get(stage)
    if instruction_fn:
        parts.append(instruction_fn())

    # CLI reference
    parts.append(_CLI_REFERENCE)

    # Validation requirements
    parts.append(_validation_requirements(stage))

    return "\n\n".join(parts)


def cmd_stage_prompt(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Print the current prompt for a triage stage, built from live plan data."""
    stage = args.stage_prompt
    resolved_services = services or default_triage_services()
    plan = resolved_services.load_plan()
    runtime = resolved_services.command_runtime(args)
    state = runtime.state
    si = resolved_services.collect_triage_input(plan, state)
    repo_root = get_project_root()

    # Extract real prior reports from plan.json
    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})
    prior_reports: dict[str, str] = {}
    for prior_stage in _STAGES:
        if prior_stage == stage:
            break
        report = stages.get(prior_stage, {}).get("report", "")
        if report:
            prior_reports[prior_stage] = report

    prompt = build_stage_prompt(stage, si, prior_reports, repo_root=repo_root)
    print(prompt)


__all__ = [
    "build_observe_batch_prompt",
    "build_sense_check_content_prompt",
    "build_sense_check_structure_prompt",
    "build_stage_prompt",
    "cmd_stage_prompt",
    "_observe_batch_instructions",
    "_validation_requirements",
]
