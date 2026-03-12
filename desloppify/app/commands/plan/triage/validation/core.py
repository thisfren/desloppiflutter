"""Validation and guardrail helpers for triage stage workflow."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan_state import save_plan
from desloppify.engine.plan_triage import (
    collect_triage_input,
    detect_recurring_patterns,
    extract_issue_citations,
)
from desloppify.state_io import utc_now

from ..confirmations.basic import MIN_ATTESTATION_LEN, validate_attestation
from ..helpers import (
    cluster_issue_ids,
    manual_clusters_with_issues,
    observe_dimension_breakdown,
)
from ..stages.helpers import unclustered_review_issues, unenriched_clusters
from .completion_policy import (
    _completion_clusters_valid,
    _completion_strategy_valid,
    _confirm_existing_stages_valid,
    _confirm_note_valid,
    _confirm_strategy_valid,
    _confirmed_text_or_error,
    _note_cites_new_issues_or_error,
    _require_prior_strategy_for_confirm,
    _resolve_completion_strategy,
    _resolve_confirm_existing_strategy,
)
from .completion_stages import (
    _auto_confirm_enrich_for_complete,
    _auto_confirm_stage_for_complete,
    _require_enrich_stage_for_complete,
    _require_organize_stage_for_complete,
    _require_sense_check_stage_for_complete,
)
from .enrich_checks import (
    _cluster_file_overlaps,
    _clusters_with_directory_scatter,
    _clusters_with_high_step_ratio,
    _enrich_report_or_error,
    _require_organize_stage_for_enrich,
    _steps_missing_issue_refs,
    _steps_referencing_skipped_issues,
    _steps_with_bad_paths,
    _steps_with_vague_detail,
    _steps_without_effort,
    _underspecified_steps,
)


@dataclass(frozen=True)
class AutoConfirmStageRequest:
    """Configuration for one fold-confirm stage auto-confirmation."""

    stage_name: str
    stage_label: str
    blocked_heading: str
    confirm_cmd: str
    inline_hint: str
    dimensions: list[str] | None = None
    cluster_names: list[str] | None = None


@dataclass(frozen=True)
class StagePrerequisite:
    """One required upstream stage for a triage workflow seam."""

    stage_name: str
    require_confirmation: bool = False


@dataclass(frozen=True)
class ReflectAutoConfirmDeps:
    triage_input: object | None = None
    command_runtime_fn: object | None = None
    collect_triage_input_fn: object = collect_triage_input
    detect_recurring_patterns_fn: object = detect_recurring_patterns
    save_plan_fn: object | None = None


_STAGE_PREREQUISITES = {
    "organize": (
        StagePrerequisite("observe"),
        StagePrerequisite("reflect"),
    ),
    "enrich": (
        StagePrerequisite("observe"),
        StagePrerequisite("reflect"),
        StagePrerequisite("organize"),
    ),
    "sense-check": (
        StagePrerequisite("enrich", require_confirmation=True),
    ),
    "complete:organize": (
        StagePrerequisite("observe"),
        StagePrerequisite("organize"),
    ),
    "complete:enrich": (
        StagePrerequisite("observe"),
        StagePrerequisite("organize"),
        StagePrerequisite("enrich"),
    ),
    "complete:sense-check": (
        StagePrerequisite("observe"),
        StagePrerequisite("organize"),
        StagePrerequisite("enrich"),
        StagePrerequisite("sense-check"),
    ),
}


def _missing_stage_prerequisite(
    stages: dict,
    *,
    flow: str,
) -> StagePrerequisite | None:
    """Return the first missing upstream stage required by one triage flow."""
    for prerequisite in _STAGE_PREREQUISITES.get(flow, ()):
        stage_record = stages.get(prerequisite.stage_name)
        if stage_record is None:
            return prerequisite
        if prerequisite.require_confirmation and not stage_record.get("confirmed_at"):
            return prerequisite
    return None


def require_stage_prerequisite(
    stages: dict,
    *,
    flow: str,
    messages: dict[str, tuple[str, str]],
) -> bool:
    """Print consistent prerequisite guidance for simple triage stage gates."""
    missing = _missing_stage_prerequisite(stages, flow=flow)
    if missing is None:
        return True
    blocked_heading, command_hint = messages[missing.stage_name]
    print(colorize(blocked_heading, "red"))
    print(colorize(command_hint, "dim"))
    return False


def _auto_confirm_stage(
    *,
    plan: dict,
    stage_record: dict,
    attestation: str | None,
    request: AutoConfirmStageRequest,
    save_plan_fn=None,
) -> bool:
    """Shared auto-confirm flow for stage fold-confirm operations."""
    if save_plan_fn is None:
        save_plan_fn = save_plan
    if stage_record.get("confirmed_at"):
        return True
    if not attestation or len(attestation.strip()) < MIN_ATTESTATION_LEN:
        print(colorize(f"  {request.blocked_heading}", "red"))
        print(colorize(f"  Run: {request.confirm_cmd}", "dim"))
        print(colorize(f"  {request.inline_hint}", "dim"))
        return False

    confirmed_text = attestation.strip()
    validation_err = validate_attestation(
        confirmed_text,
        request.stage_name,
        dimensions=request.dimensions,
        cluster_names=request.cluster_names,
    )
    if validation_err:
        print(colorize(f"  {validation_err}", "red"))
        return False

    stage_record["confirmed_at"] = utc_now()
    stage_record["confirmed_text"] = confirmed_text
    save_plan_fn(plan)
    print(colorize(f"  ✓ {request.stage_label} auto-confirmed via --attestation.", "green"))
    return True


def _auto_confirm_observe_if_attested(
    *,
    plan: dict,
    stages: dict,
    attestation: str | None,
    triage_input,
    save_plan_fn=None,
) -> bool:
    observe_stage = stages.get("observe")
    if observe_stage is None:
        return False
    _by_dim, dim_names = observe_dimension_breakdown(triage_input)
    return _auto_confirm_stage(
        plan=plan,
        stage_record=observe_stage,
        attestation=attestation,
        request=AutoConfirmStageRequest(
            stage_name="observe",
            stage_label="Observe",
            blocked_heading="Cannot reflect: observe stage not confirmed.",
            confirm_cmd="desloppify plan triage --confirm observe",
            inline_hint="Or pass --attestation to auto-confirm observe inline.",
            dimensions=dim_names,
        ),
        save_plan_fn=save_plan_fn,
    )


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
    print(colorize("  Your report must mention at least one recurring dimension name.", "dim"))
    return False


# ---------------------------------------------------------------------------
# Disposition types
# ---------------------------------------------------------------------------

DecisionKind = Literal["cluster", "permanent_skip"]


@dataclass(frozen=True)
class ReflectDisposition:
    """One issue's intended disposition as declared by the reflect stage."""

    issue_id: str
    decision: DecisionKind
    target: str  # cluster name or skip reason tag

    def to_dict(self) -> dict:
        """Serialize for JSON persistence in plan.json."""
        return {"issue_id": self.issue_id, "decision": self.decision, "target": self.target}

    @classmethod
    def from_dict(cls, d: dict | ReflectDisposition) -> ReflectDisposition:
        """Deserialize from persisted plan.json dict, or pass through if already typed."""
        if isinstance(d, cls):
            return d
        return cls(
            issue_id=d.get("issue_id", ""),
            decision=d.get("decision", "cluster"),  # type: ignore[arg-type]
            target=d.get("target", ""),
        )


@dataclass(frozen=True)
class ActualDisposition:
    """What actually happened to an issue in plan state."""

    kind: Literal["clustered", "skipped", "unplaced"]
    cluster_name: str = ""  # non-empty when kind == "clustered"

    def describe(self, intended: ReflectDisposition | None = None) -> str:
        """Human-readable description for error messages."""
        if self.kind == "skipped":
            return "permanently skipped"
        if self.kind == "clustered":
            if intended and intended.decision == "cluster" and self.cluster_name != intended.target:
                return f'in cluster "{self.cluster_name}" (expected "{intended.target}")'
            return f'clustered in "{self.cluster_name}"'
        if self.kind == "unplaced":
            if intended and intended.decision == "cluster":
                return "not in any cluster"
            return "not skipped, not clustered"
        return "unknown state"


def _build_actual_disposition_index(plan: dict) -> dict[str, ActualDisposition]:
    """Build a lookup from issue ID to its actual disposition in plan state."""
    index: dict[str, ActualDisposition] = {}

    for cluster_name, cluster in plan.get("clusters", {}).items():
        if cluster.get("auto"):
            continue
        for fid in cluster_issue_ids(cluster):
            index[fid] = ActualDisposition(kind="clustered", cluster_name=cluster_name)

    for fid in (plan.get("skipped", {}) or {}):
        if isinstance(fid, str):
            index[fid] = ActualDisposition(kind="skipped")

    return index


# ---------------------------------------------------------------------------
# Coverage Ledger parsing — shared infrastructure
# ---------------------------------------------------------------------------

def _build_id_resolution_maps(
    valid_ids: set[str],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Build short-ID lookup structures from a set of full issue IDs."""
    short_id_buckets: dict[str, list[str]] = {}
    short_hex_map: dict[str, str] = {}
    for issue_id in sorted(valid_ids):
        short_id = issue_id.rsplit("::", 1)[-1]
        short_id_buckets.setdefault(short_id, []).append(issue_id)
        if re.fullmatch(r"[0-9a-f]{8,}", short_id):
            existing = short_hex_map.get(short_id)
            if existing is None:
                short_hex_map[short_id] = issue_id
            elif existing != issue_id:
                short_hex_map.pop(short_id, None)
    return short_id_buckets, short_hex_map


def _clean_ledger_token(raw: str) -> str:
    """Strip backticks, brackets, and whitespace from a ledger token."""
    token = raw.strip().strip("`").strip()
    if token.startswith("[") and token.endswith("]"):
        token = token[1:-1].strip()
    return token


def _extract_ledger_entry(line: str) -> tuple[str, str | None, str | None]:
    """Parse a ledger line into (token, decision, target).

    Supported formats:
    - ``- token -> decision "target"``  (canonical)
    - ``- token -> decision target``    (unquoted)
    - ``- token -> ...``                (bare arrow)
    - ``- token: decision target``      (colon-separated)
    - ``- token, decision, target``     (comma-separated)
    - ``- token``                       (bare slug/hash on a list line)

    Returns ``("", None, None)`` when nothing is parseable.
    """
    # Try full structured form: - token -> decision "target"
    match = re.match(r"-\s*(.+?)\s*->\s*(\w+)\s+[\"']([^\"']+)[\"']", line)
    if match:
        token = _clean_ledger_token(match.group(1))
        return token, match.group(2).strip().lower(), match.group(3).strip()

    # Try unquoted: - token -> decision target-slug
    match = re.match(r"-\s*(.+?)\s*->\s*(\w+)\s+(\S+.*)", line)
    if match:
        token = _clean_ledger_token(match.group(1))
        target = match.group(3).strip().strip("\"'")
        return token, match.group(2).strip().lower(), target

    # Bare arrow: - token -> (anything or nothing)
    match = re.match(r"-\s*(.+?)\s*->", line)
    if match:
        token = _clean_ledger_token(match.group(1))
        return token, None, None

    # Colon-separated: - token: decision target
    match = re.match(r"-\s*(.+?)\s*:\s*(\w+)\s+[\"']?([^\"']+?)[\"']?\s*$", line)
    if match:
        token = _clean_ledger_token(match.group(1))
        return token, match.group(2).strip().lower(), match.group(3).strip()

    # Comma-separated: - token, decision, target
    match = re.match(r"-\s*([^,]+),\s*(\w+),\s*[\"']?([^\"',]+?)[\"']?\s*$", line)
    if match:
        token = _clean_ledger_token(match.group(1))
        return token, match.group(2).strip().lower(), match.group(3).strip()

    # Bare slug/hash on a list line: - token
    match = re.match(r"-\s+(\S+)\s*$", line)
    if match:
        token = _clean_ledger_token(match.group(1))
        if token:
            return token, None, None

    return "", None, None


def _resolve_token_to_id(
    token: str,
    valid_ids: set[str],
    short_id_buckets: dict[str, list[str]],
    short_hex_map: dict[str, str],
    short_id_usage: Counter[str],
) -> str | None:
    """Resolve a ledger token to a full issue ID, or None."""
    if token in valid_ids:
        return token
    bucket = short_id_buckets.get(token)
    if bucket:
        bucket_index = short_id_usage[token]
        issue_id = bucket[bucket_index] if bucket_index < len(bucket) else bucket[-1]
        short_id_usage[token] += 1
        return issue_id
    # Hex-substring fallback
    for hex_token in re.findall(r"[0-9a-f]{8,}", token):
        resolved = short_hex_map.get(hex_token)
        if resolved:
            return resolved
    # Slug-prefix match: token might be the detector_slug part of "detector_slug::hash"
    token_lower = token.lower()
    matches = [vid for vid in valid_ids if vid.startswith(token_lower + "::")]
    if len(matches) == 1:
        return matches[0]
    # Substring match: token appears as a component of exactly one issue ID
    if len(token) >= 6:
        matches = [vid for vid in valid_ids if token_lower in vid.lower()]
        if len(matches) == 1:
            return matches[0]
    return None


# Canonical decision values for dispositions
_CLUSTER_DECISIONS = frozenset({"cluster"})
_SKIP_DECISIONS = frozenset({"skip", "dismiss", "defer", "drop", "remove"})


def _normalize_decision(raw: str) -> str:
    """Normalize a ledger decision to 'cluster' or 'permanent_skip'."""
    lower = raw.lower()
    if lower in _CLUSTER_DECISIONS:
        return "cluster"
    if lower in _SKIP_DECISIONS:
        return "permanent_skip"
    return lower


# ---------------------------------------------------------------------------
# Single-pass ledger walker — produces both accounting and dispositions
# ---------------------------------------------------------------------------

@dataclass
class _LedgerParseResult:
    """Combined output of a single pass over the Coverage Ledger section."""

    hits: Counter[str]  # issue_id -> mention count (for accounting)
    dispositions: list[ReflectDisposition]  # structured dispositions
    found_section: bool  # True if ## Coverage Ledger was present


def _walk_coverage_ledger(
    report: str,
    valid_ids: set[str],
) -> _LedgerParseResult:
    """Single-pass parse of the Coverage Ledger section.

    Extracts both hit counts (for accounting validation) and structured
    dispositions (for the execution contract) in one walk.
    """
    short_id_buckets, short_hex_map = _build_id_resolution_maps(valid_ids)
    hits: Counter[str] = Counter()
    dispositions: list[dict] = []
    short_id_usage: Counter[str] = Counter()
    in_ledger = False
    found_section = False

    for raw_line in report.splitlines():
        line = raw_line.strip()
        if re.fullmatch(r"##\s+Coverage Ledger", line, re.IGNORECASE):
            in_ledger = True
            found_section = True
            continue
        if in_ledger and re.match(r"##\s+", line):
            break
        if not in_ledger:
            continue

        token, decision, target = _extract_ledger_entry(line)
        if not token:
            continue

        issue_id = _resolve_token_to_id(
            token, valid_ids, short_id_buckets, short_hex_map, short_id_usage,
        )
        if not issue_id:
            # Last resort: scan entire line for hex IDs
            for hex_token in re.findall(r"[0-9a-f]{8,}", line):
                resolved = short_hex_map.get(hex_token)
                if resolved:
                    issue_id = resolved
                    break

        if issue_id:
            hits[issue_id] += 1
            if decision and target:
                normalized = _normalize_decision(decision)
                if normalized in ("cluster", "permanent_skip"):
                    dispositions.append(ReflectDisposition(
                        issue_id=issue_id,
                        decision=normalized,  # type: ignore[arg-type]
                        target=target,
                    ))

    return _LedgerParseResult(
        hits=hits,
        dispositions=dispositions,
        found_section=found_section,
    )


# ---------------------------------------------------------------------------
# Public API — thin wrappers over the shared walker
# ---------------------------------------------------------------------------

def parse_reflect_dispositions(
    report: str,
    valid_ids: set[str],
) -> list[ReflectDisposition]:
    """Parse the Coverage Ledger into structured dispositions.

    Returns an empty list if no Coverage Ledger section is found.
    """
    return _walk_coverage_ledger(report, valid_ids).dispositions


def _analyze_reflect_issue_accounting(
    *,
    report: str,
    valid_ids: set[str],
) -> tuple[set[str], list[str], list[str]]:
    """Return cited, missing, and duplicate issue IDs referenced by reflect."""
    result = _walk_coverage_ledger(report, valid_ids)

    if result.found_section and result.hits:
        cited = set(result.hits)
        duplicates = sorted(
            issue_id for issue_id, count in result.hits.items() if count > 1
        )
        missing = sorted(valid_ids - cited)
        return cited, missing, duplicates

    # Fallback for reports without a Coverage Ledger section
    short_id_buckets, short_hex_map = _build_id_resolution_maps(valid_ids)
    cited = extract_issue_citations(report, valid_ids)
    for issue_id in valid_ids:
        if issue_id in report:
            cited.add(issue_id)
    # Merge hex-suffix matches into cited (previously only used for duplicates)
    short_hits: Counter[str] = Counter()
    for token in re.findall(r"[0-9a-f]{8,}", report):
        resolved = short_hex_map.get(token)
        if resolved:
            cited.add(resolved)
            short_hits[resolved] += 1
    duplicates = sorted(
        issue_id for issue_id, count in short_hits.items() if count > 1
    )
    missing = sorted(valid_ids - cited)
    return cited, missing, duplicates


def _validate_reflect_issue_accounting(
    *,
    report: str,
    valid_ids: set[str],
) -> tuple[bool, set[str], list[str], list[str]]:
    """Ensure the reflect blueprint accounts for every open review issue exactly once."""
    cited, missing, duplicates = _analyze_reflect_issue_accounting(
        report=report,
        valid_ids=valid_ids,
    )
    if not missing and not duplicates:
        return True, cited, missing, duplicates
    print(
        colorize(
            "  Reflect report must account for every open review issue exactly once.",
            "red",
        )
    )
    if missing:
        missing_short = ", ".join(issue_id.rsplit("::", 1)[-1] for issue_id in missing[:10])
        print(colorize(f"    Missing: {missing_short}", "yellow"))
    if duplicates:
        duplicate_short = ", ".join(
            issue_id.rsplit("::", 1)[-1] for issue_id in duplicates[:10]
        )
        print(colorize(f"    Duplicated: {duplicate_short}", "yellow"))
    print(colorize("  Fix the reflect blueprint before running organize.", "dim"))
    if missing:
        print(colorize("  Expected format — include a ## Coverage Ledger section:", "dim"))
        print(colorize('    - <hash> -> cluster "cluster-name"', "dim"))
        print(colorize('    - <hash> -> skip "reason"', "dim"))
        print(colorize("  Also accepted: bare hashes, colon-separated, comma-separated.", "dim"))
    return False, cited, missing, duplicates


def _require_reflect_stage_for_organize(stages: dict) -> bool:
    return require_stage_prerequisite(
        stages,
        flow="organize",
        messages={
            "observe": (
                "  Cannot organize: observe stage not complete.",
                '  Run: desloppify plan triage --stage observe --report "..."',
            ),
            "reflect": (
                "  Cannot organize: reflect stage not complete.",
                '  Run: desloppify plan triage --stage reflect --report "..."',
            ),
        },
    )


def _auto_confirm_reflect_for_organize(
    *,
    args: argparse.Namespace,
    plan: dict,
    stages: dict,
    attestation: str | None,
    deps: ReflectAutoConfirmDeps | None = None,
) -> bool:
    reflect_stage = stages.get("reflect")
    if reflect_stage is None:
        return False

    deps = deps or ReflectAutoConfirmDeps()
    resolved_triage_input = deps.triage_input
    if resolved_triage_input is None:
        runtime_factory = deps.command_runtime_fn or command_runtime
        runtime = runtime_factory(args)
        resolved_triage_input = deps.collect_triage_input_fn(plan, runtime.state)

    valid_ids = set(resolved_triage_input.open_issues.keys())
    accounting_ok, cited_ids, missing_ids, duplicate_ids = _validate_reflect_issue_accounting(
        report=str(reflect_stage.get("report", "")),
        valid_ids=valid_ids,
    )
    if not accounting_ok:
        return False
    reflect_stage["cited_ids"] = sorted(cited_ids)
    reflect_stage["missing_issue_ids"] = missing_ids
    reflect_stage["duplicate_issue_ids"] = duplicate_ids

    recurring = deps.detect_recurring_patterns_fn(
        resolved_triage_input.open_issues,
        resolved_triage_input.resolved_issues,
    )
    _by_dim, observe_dims = observe_dimension_breakdown(resolved_triage_input)
    reflect_dims = sorted(set((list(recurring.keys()) if recurring else []) + observe_dims))
    reflect_clusters = [name for name in plan.get("clusters", {}) if not plan["clusters"][name].get("auto")]
    return _auto_confirm_stage(
        plan=plan,
        stage_record=reflect_stage,
        attestation=attestation,
        request=AutoConfirmStageRequest(
            stage_name="reflect",
            stage_label="Reflect",
            blocked_heading="Cannot organize: reflect stage not confirmed.",
            confirm_cmd="desloppify plan triage --confirm reflect",
            inline_hint="Or pass --attestation to auto-confirm reflect inline.",
            dimensions=reflect_dims,
            cluster_names=reflect_clusters,
        ),
        save_plan_fn=deps.save_plan_fn,
    )


def _manual_clusters_or_error(
    plan: dict,
    *,
    open_review_ids: set[str] | None = None,
) -> list[str] | None:
    manual_clusters = manual_clusters_with_issues(plan)
    if manual_clusters:
        return manual_clusters
    if open_review_ids is not None and not open_review_ids:
        return []
    any_clusters = [
        name for name, cluster in plan.get("clusters", {}).items()
        if cluster_issue_ids(cluster)
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
    gaps = unenriched_clusters(plan)
    if not gaps:
        return True
    print(colorize(f"  Cannot organize: {len(gaps)} cluster(s) need enrichment.", "red"))
    for name, missing in gaps:
        print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
    print()
    print(colorize("  Each cluster needs a description and action steps:", "dim"))
    print(colorize('    desloppify plan cluster update <name> --description "what this cluster addresses" --steps "step 1" "step 2"', "dim"))
    return False


def _unclustered_review_issues_or_error(plan: dict, state: dict) -> bool:
    """Block if open review issues aren't in any manual cluster. Return True if OK."""
    unclustered = unclustered_review_issues(plan, state)
    if not unclustered:
        return True
    print(colorize(f"  Cannot organize: {len(unclustered)} review issue(s) have no cluster.", "red"))
    for fid in unclustered[:10]:
        short = fid.rsplit("::", 2)[-2] if "::" in fid else fid
        print(colorize(f"    {short}", "yellow"))
    if len(unclustered) > 10:
        print(colorize(f"    ... and {len(unclustered) - 10} more", "yellow"))
    print()
    print(colorize("  Every review issue needs an action plan. Either:", "dim"))
    print(colorize("    1. Add to a cluster: desloppify plan cluster add <name> <pattern>", "dim"))
    print(colorize('    2. Wontfix it: desloppify plan skip --permanent <pattern> --note "reason" --attest "..."', "dim"))
    return False


def _organize_report_or_error(report: str | None) -> str | None:
    if not report:
        print(colorize("  --report is required for --stage organize.", "red"))
        print(colorize("  Summarize your prioritized organization:", "dim"))
        print(colorize("  - Did you defer contradictory issues before clustering?", "dim"))
        print(colorize("  - What clusters did you create and why?", "dim"))
        print(colorize("  - Explicit priority ordering: which cluster 1st, 2nd, 3rd and why?", "dim"))
        print(colorize("  - What depends on what? What unblocks the most?", "dim"))
        return None
    if len(report) < 100:
        print(colorize(f"  Report too short: {len(report)} chars (minimum 100).", "red"))
        print(colorize("  Explain what you organized, your priorities, and focus order.", "dim"))
        return None
    return report


@dataclass(frozen=True)
class LedgerMismatch:
    """One issue where plan state diverges from the reflect disposition."""

    intended: ReflectDisposition
    actual: ActualDisposition

    @property
    def issue_id(self) -> str:
        return self.intended.issue_id

    @property
    def expected_decision(self) -> str:
        return self.intended.decision

    @property
    def expected_target(self) -> str:
        return self.intended.target

    @property
    def actual_state(self) -> str:
        return self.actual.describe(self.intended)


def _disposition_matches(intended: ReflectDisposition, actual: ActualDisposition) -> bool:
    """True when the actual plan state satisfies the intended disposition."""
    if intended.decision == "permanent_skip":
        return actual.kind == "skipped"
    if intended.decision == "cluster":
        return actual.kind == "clustered" and actual.cluster_name == intended.target
    return False


def validate_organize_against_reflect_ledger(
    *,
    plan: dict,
    stages: dict,
) -> list[LedgerMismatch]:
    """Check that plan mutations match the reflect disposition ledger.

    Returns an empty list when all dispositions are faithfully materialized,
    or a list of mismatches when organize diverged from the reflect plan.

    Silently returns [] for legacy runs without a disposition_ledger.
    """
    raw_ledger = stages.get("reflect", {}).get("disposition_ledger")
    if not raw_ledger:
        return []

    ledger = [ReflectDisposition.from_dict(d) for d in raw_ledger]
    actuals = _build_actual_disposition_index(plan)
    unplaced = ActualDisposition(kind="unplaced")

    return [
        LedgerMismatch(intended=d, actual=actuals.get(d.issue_id, unplaced))
        for d in ledger
        if not _disposition_matches(d, actuals.get(d.issue_id, unplaced))
    ]


def _validate_organize_against_ledger_or_error(
    *,
    plan: dict,
    stages: dict,
) -> bool:
    """Block organize if plan state diverges from the reflect disposition ledger."""
    mismatches = validate_organize_against_reflect_ledger(
        plan=plan, stages=stages,
    )
    if not mismatches:
        return True

    print(
        colorize(
            f"  Cannot organize: {len(mismatches)} issue(s) diverge from the reflect plan.",
            "red",
        )
    )
    for m in mismatches[:10]:
        short_id = m.issue_id.rsplit("::", 1)[-1]
        print(
            colorize(
                f"    {short_id}: reflect said {m.expected_decision} "
                f'"{m.expected_target}", but {m.actual_state}',
                "yellow",
            )
        )
    if len(mismatches) > 10:
        print(colorize(f"    ... and {len(mismatches) - 10} more", "yellow"))
    print()
    print(
        colorize(
            "  Fix the plan to match the reflect ledger, or re-run reflect to update dispositions.",
            "dim",
        )
    )
    return False


__all__ = [
    "_auto_confirm_enrich_for_complete",
    "_auto_confirm_observe_if_attested",
    "AutoConfirmStageRequest",
    "_auto_confirm_stage_for_complete",
    "_auto_confirm_reflect_for_organize",
    "_cluster_file_overlaps",
    "_clusters_with_directory_scatter",
    "_clusters_with_high_step_ratio",
    "_clusters_enriched_or_error",
    "_enrich_report_or_error",
    "_unclustered_review_issues_or_error",
    "_validate_reflect_issue_accounting",
    "_completion_clusters_valid",
    "_completion_strategy_valid",
    "_confirm_existing_stages_valid",
    "_confirm_note_valid",
    "_confirm_strategy_valid",
    "_confirmed_text_or_error",
    "_manual_clusters_or_error",
    "_note_cites_new_issues_or_error",
    "_organize_report_or_error",
    "_require_enrich_stage_for_complete",
    "_require_organize_stage_for_complete",
    "_require_organize_stage_for_enrich",
    "_require_prior_strategy_for_confirm",
    "_require_reflect_stage_for_organize",
    "_require_sense_check_stage_for_complete",
    "_missing_stage_prerequisite",
    "_resolve_completion_strategy",
    "_resolve_confirm_existing_strategy",
    "_underspecified_steps",
    "_steps_missing_issue_refs",
    "_steps_referencing_skipped_issues",
    "_steps_with_bad_paths",
    "_steps_with_vague_detail",
    "_steps_without_effort",
    "_validate_organize_against_ledger_or_error",
    "_validate_recurring_dimension_mentions",
    "LedgerMismatch",
    "ReflectDisposition",
    "parse_reflect_dispositions",
    "require_stage_prerequisite",
    "validate_organize_against_reflect_ledger",
]
