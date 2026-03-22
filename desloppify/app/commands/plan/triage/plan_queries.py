"""Plan-level query helpers shared across triage subpackages.

Extracted from stages.helpers to avoid reciprocal imports between
the ``stages`` and ``validation`` subpackages.
"""

from __future__ import annotations

from desloppify.base.enums import Status
from desloppify.engine.plan_constants import is_synthetic_id
from desloppify.state_io import is_review_work_item

from .review_coverage import (
    active_triage_issue_ids,
    cluster_issue_ids,
    live_active_triage_issue_ids,
    manual_clusters_with_issues,
)


def active_triage_issue_scope(
    plan: dict,
    state: dict | None = None,
) -> set[str] | None:
    frozen = active_triage_issue_ids(plan, state)
    if not frozen:
        return None
    if state is None:
        return frozen
    return live_active_triage_issue_ids(plan, state)


def scoped_manual_clusters_with_issues(
    plan: dict,
    state: dict | None = None,
) -> list[str]:
    scope = active_triage_issue_scope(plan, state)
    clusters = plan.get("clusters", {})
    names = manual_clusters_with_issues(plan)
    if scope is None:
        return names
    return [
        name
        for name in names
        if set(cluster_issue_ids(clusters.get(name, {}))) & scope
    ]


def triage_scoped_plan(
    plan: dict,
    state: dict | None = None,
) -> dict:
    scope = active_triage_issue_scope(plan, state)
    if scope is None:
        return plan
    allowed = set(scoped_manual_clusters_with_issues(plan, state))
    return {
        **plan,
        "clusters": {
            name: cluster
            for name, cluster in plan.get("clusters", {}).items()
            if name in allowed
        },
    }


def unenriched_clusters(
    plan: dict,
    state: dict | None = None,
) -> list[tuple[str, list[str]]]:
    gaps: list[tuple[str, list[str]]] = []
    clusters = plan.get("clusters", {})
    for name in scoped_manual_clusters_with_issues(plan, state):
        cluster = clusters.get(name, {})
        issue_ids = cluster_issue_ids(cluster)
        missing: list[str] = []
        if not cluster.get("description"):
            missing.append("description")
        steps = cluster.get("action_steps") or []
        issue_count = len(issue_ids)
        if not steps:
            missing.append("action_steps")
        elif issue_count < 5 and len(steps) < issue_count:
            missing.append(
                f"action_steps (have {len(steps)}, need >= {issue_count} for small cluster)"
            )
        if missing:
            gaps.append((name, missing))
    return gaps


def unclustered_review_issues(plan: dict, state: dict | None = None) -> list[str]:
    clusters = plan.get("clusters", {})
    clustered_ids: set[str] = set()
    for cluster in clusters.values():
        if not cluster.get("auto"):
            clustered_ids.update(cluster_issue_ids(cluster))
    skipped_ids = {
        fid for fid in (plan.get("skipped", {}) or {}).keys() if isinstance(fid, str)
    }

    if state is not None:
        review_ids = [
            fid for fid, finding in (state.get("work_items") or state.get("issues", {})).items()
            if finding.get("status") == Status.OPEN
            and is_review_work_item(finding)
        ]
        frozen_ids = (plan.get("epic_triage_meta", {}) or {}).get("active_triage_issue_ids")
        if isinstance(frozen_ids, list) and frozen_ids:
            frozen_id_set = live_active_triage_issue_ids(plan, state)
            review_ids = [fid for fid in review_ids if fid in frozen_id_set]
    else:
        review_ids = [
            fid for fid in plan.get("queue_order", [])
            if not is_synthetic_id(fid)
            and (fid.startswith("review::") or fid.startswith("concerns::"))
        ]

    return [
        fid for fid in review_ids
        if fid not in clustered_ids and fid not in skipped_ids
    ]
