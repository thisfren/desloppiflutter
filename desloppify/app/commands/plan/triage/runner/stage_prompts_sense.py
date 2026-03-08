"""Sense-check prompt builders for triage runner."""

from __future__ import annotations

from pathlib import Path


def build_sense_check_content_prompt(
    *,
    cluster_name: str,
    plan: dict,
    repo_root: Path,
) -> str:
    """Build a content-verification prompt for a single cluster."""
    cluster = plan.get("clusters", {}).get(cluster_name, {})
    steps = cluster.get("action_steps", [])
    issue_ids = cluster.get("issue_ids", [])

    parts: list[str] = []
    parts.append(
        f"You are sense-checking cluster `{cluster_name}` "
        f"({len(steps)} steps, {len(issue_ids)} issues).\n"
        f"Repo root: {repo_root}"
    )

    parts.append(
        "## Your job\n"
        "For EVERY step in this cluster, read the actual source file and verify\n"
        "every factual claim. Then fix anything wrong or vague.\n"
    )

    parts.append(
        "## What to check and fix\n"
        "1. LINE NUMBERS: Does the code at the claimed lines match what the step describes?\n"
        "   Fix: update the line range to match current file state.\n"
        "2. NAMES: Do the function/variable/type names in the step exist in the file?\n"
        "   Fix: correct the names.\n"
        "3. COUNTS: \"Update the 3 imports\" — are there actually 3? Or 5?\n"
        "   Fix: correct the count.\n"
        "4. STALENESS: Is the problem the issue describes still present in the code?\n"
        "   If already fixed, note in your report.\n"
        "5. VAGUENESS: Could a developer with zero context execute this step without\n"
        "   asking a single question? If not:\n"
        "   - Replace \"refactor X\" with the specific transformation\n"
        "   - Replace \"update imports\" with the specific file list\n"
        "   - Replace \"extract into new hook\" with the filename, function signature, return type\n"
        "6. EFFORT TAGS: Does the tag match the actual scope? A one-line rename is \"trivial\",\n"
        "   not \"small\". Decomposing a 400-line file is \"large\", not \"medium\".\n"
        "7. DUPLICATES: If you notice this step does the same thing as a step in another\n"
        "   cluster, note it in your report.\n"
        "8. OVER-ENGINEERING: Would this change make the codebase *worse*? Flag steps that:\n"
        "   - Add abstractions, wrappers, or indirection for a one-time operation\n"
        "   - Introduce unnecessary config, feature flags, or generalization\n"
        "   - Make simple code harder to read for marginal benefit\n"
        "   - Gold-plate beyond what the issue actually requires\n"
        "   - Trade one smell for a worse one (e.g. fix duplication by adding a fragile base class)\n"
        "   If a step is net-negative, recommend removing it or simplifying the approach.\n"
        "   If the entire cluster is net-negative, say so clearly in your report.\n"
    )

    parts.append(
        "## How to fix\n"
        f"desloppify plan cluster update {cluster_name} "
        "--update-step N --detail \"corrected...\" --effort <tag>\n"
    )

    parts.append(
        "## What NOT to do\n"
        "- Do NOT reorder steps (the structure subagent handles that)\n"
        "- Do NOT add --depends-on (the structure subagent handles that)\n"
        "- Do NOT add new steps for missing cascade updates (the structure subagent handles that)\n"
        "- Do NOT run any other desloppify commands\n"
    )

    # Include cluster steps
    parts.append("## Current Steps\n")
    for i, step in enumerate(steps, 1):
        title = step.get("title", str(step)) if isinstance(step, dict) else str(step)
        detail = step.get("detail", "") if isinstance(step, dict) else ""
        effort = step.get("effort", "") if isinstance(step, dict) else ""
        refs = step.get("issue_refs", []) if isinstance(step, dict) else []
        line = f"{i}. **{title}**"
        if effort:
            line += f" [{effort}]"
        if refs:
            line += f" (refs: {', '.join(refs[:3])})"
        if detail:
            line += f"\n   {detail[:300]}"
        parts.append(line)

    parts.append(
        "\n## Output\n"
        "Write a plain-text report of your findings. The orchestrator records the stage."
    )

    return "\n\n".join(parts)


def build_sense_check_structure_prompt(
    *,
    plan: dict,
    repo_root: Path,
) -> str:
    """Build a structure-verification prompt for cross-cluster dependency checking."""
    clusters = plan.get("clusters", {})

    parts: list[str] = []
    parts.append(
        "You are checking cross-cluster dependencies for the entire triage plan.\n"
        f"Repo root: {repo_root}"
    )

    parts.append(
        "## Your job\n"
        "Build a file-touch graph: for each cluster, which files do its steps reference?\n"
        "Then check for unsafe relationships between clusters.\n"
    )

    parts.append(
        "## What to check and fix\n"
        "1. SHARED FILES: If cluster A and cluster B both have steps touching the same file,\n"
        "   and neither depends on the other → add a dependency.\n"
        "   Fix: desloppify plan cluster update {later_cluster} --depends-on {earlier_cluster}\n"
        "2. MISSING CASCADE: If a step renames/removes a function or export, check whether\n"
        "   any other file imports it. If those importers aren't covered by any step in any\n"
        "   cluster → add a cascade step.\n"
        "   Fix: desloppify plan cluster update {cluster} --add-step \"Update importers of {name}\"\n"
        "        --detail \"Files importing {old}: {list}. Update import to {new}.\"\n"
        "        --effort trivial --issue-refs {hash}\n"
        "3. CIRCULAR DEPS: If adding a dependency would create a cycle, flag it in your report\n"
        "   instead of adding it.\n"
    )

    parts.append(
        "## What NOT to do\n"
        "- Do NOT modify step detail text (the content subagent handles that)\n"
        "- Do NOT change effort tags (the content subagent handles that)\n"
        "- Do NOT remove steps or deduplicate (the content subagent handles that)\n"
        "- Do NOT run any other desloppify commands besides cluster update --depends-on and --add-step\n"
    )

    # Include all clusters with their steps and dependencies
    parts.append("## Clusters\n")
    for name, c in sorted(clusters.items()):
        if c.get("auto"):
            continue
        steps = c.get("action_steps", [])
        deps = c.get("depends_on_clusters", [])
        issues = c.get("issue_ids", [])
        header = f"### {name} ({len(steps)} steps, {len(issues)} issues)"
        if deps:
            header += f"\n  depends_on: {', '.join(deps)}"
        parts.append(header)
        for i, step in enumerate(steps, 1):
            title = step.get("title", str(step)) if isinstance(step, dict) else str(step)
            detail = step.get("detail", "") if isinstance(step, dict) else ""
            line = f"  {i}. {title}"
            if detail:
                line += f"\n     {detail[:200]}"
            parts.append(line)

    parts.append(
        "\n## Output\n"
        "Write a plain-text report of your findings. The orchestrator records the stage."
    )

    return "\n\n".join(parts)


__all__ = [
    "build_sense_check_content_prompt",
    "build_sense_check_structure_prompt",
]
