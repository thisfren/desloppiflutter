"""Pure grouping/description/action strategy for plan auto-clustering."""

from __future__ import annotations

import os

from desloppify.base.registry import DetectorMeta

AUTO_PREFIX = "auto/"


def extract_subtype(issue: dict) -> str | None:
    """Extract the subtype/kind from a issue."""
    detail = issue.get("detail") or {}
    kind = detail.get("kind")
    if kind:
        return kind

    issue_id = issue.get("id", "")
    parts = issue_id.split("::")
    if len(parts) >= 3:
        candidate = parts[-1]
        if "/" not in candidate and "." not in candidate:
            return candidate
    return None


def grouping_key(issue: dict, meta: DetectorMeta | None) -> str | None:
    """Compute a deterministic grouping key for a issue."""
    detector = issue.get("detector", "")

    if meta is None:
        return f"detector::{detector}"

    if detector in ("review", "subjective_review"):
        detail = issue.get("detail") or {}
        dimension = detail.get("dimension", "")
        if dimension:
            return f"review::{dimension}"
        return f"detector::{detector}"

    if meta.needs_judgment and detector in ("structural", "responsibility_cohesion"):
        file_path = issue.get("file", "")
        if file_path:
            basename = os.path.basename(file_path)
            return f"file::{detector}::{basename}"

    if meta.needs_judgment:
        subtype = extract_subtype(issue)
        if subtype:
            return f"typed::{detector}::{subtype}"

    if meta.action_type == "auto_fix" and not meta.needs_judgment:
        return f"auto::{detector}"

    return f"detector::{detector}"


def cluster_name_from_key(key: str) -> str:
    """Convert a grouping key to an ``auto/...`` cluster name."""
    parts = key.split("::")
    if len(parts) == 2:
        prefix_type = parts[0]
        if prefix_type == "review":
            return f"{AUTO_PREFIX}review-{parts[1]}"
        return f"{AUTO_PREFIX}{parts[1]}"
    if len(parts) == 3:
        return f"{AUTO_PREFIX}{parts[1]}-{parts[2]}"
    return f"{AUTO_PREFIX}{key.replace('::', '-')}"


def generate_description(
    cluster_name: str,
    members: list[dict],
    meta: DetectorMeta | None,
    subtype: str | None,
) -> str:
    """Generate a human-readable cluster description."""
    _ = cluster_name
    count = len(members)
    detector = members[0].get("detector", "") if members else ""

    if detector in ("review", "subjective_review"):
        detail = (members[0].get("detail") or {}) if members else {}
        dimension = detail.get("dimension", detector)
        return f"Address {count} {dimension} review issues"

    if detector == "structural":
        files = {os.path.basename(member.get("file", "")) for member in members}
        if len(files) == 1:
            return f"Decompose {next(iter(files))}"
        return f"Decompose {count} large files"

    display = meta.display if meta else detector
    if subtype:
        label = subtype.replace("_", " ")
        return f"Fix {count} {label} issues"

    if meta and meta.action_type == "auto_fix" and not meta.needs_judgment:
        return f"Remove {count} {display} issues"

    return f"Fix {count} {display} issues"


def subtype_has_fixer(meta: DetectorMeta, subtype: str | None) -> str | None:
    """Check if a subtype maps to a detector fixer."""
    if not meta.fixers or not subtype:
        return None
    fixer_name = subtype.replace("_", "-")
    if fixer_name in meta.fixers:
        return fixer_name
    for fixer in meta.fixers:
        if subtype in fixer:
            return fixer
    return None


def strip_guidance_examples(guidance: str) -> str:
    """Strip subtype examples from guidance text."""
    if " — " in guidance:
        return guidance.split(" — ", 1)[0].strip()
    return guidance


_ACTION_TYPE_TEMPLATES: dict[str, str] = {
    "reorganize": "reorganize with desloppify move",
    "refactor": "review and refactor each issue",
    "manual_fix": "review and fix each issue",
}


def generate_action(
    meta: DetectorMeta | None,
    subtype: str | None,
) -> str:
    """Generate an action string from detector metadata."""
    if meta is None:
        return "review and fix each issue"

    if subtype and meta.fixers:
        matched_fixer = subtype_has_fixer(meta, subtype)
        if matched_fixer:
            return f"desloppify autofix {matched_fixer} --dry-run"
    elif meta.action_type == "auto_fix" and meta.fixers and not meta.needs_judgment:
        return f"desloppify autofix {meta.fixers[0]} --dry-run"

    if meta.tool == "move":
        return "desloppify move"

    if meta.guidance:
        if subtype:
            return strip_guidance_examples(meta.guidance)
        return meta.guidance

    return _ACTION_TYPE_TEMPLATES.get(meta.action_type, "review and fix each issue")


__all__ = [
    "cluster_name_from_key",
    "generate_action",
    "generate_description",
    "grouping_key",
    "strip_guidance_examples",
]
