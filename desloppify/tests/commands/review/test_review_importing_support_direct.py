"""Direct tests for review importing support modules."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import desloppify.app.commands.review.importing.cmd as import_cmd_mod
import desloppify.app.commands.review.importing.flags as flags_mod
import desloppify.app.commands.review.importing.plan_sync as plan_sync_mod
import desloppify.app.commands.review.importing.results as results_mod
import desloppify.engine.plan_queue as plan_queue_mod


def test_plan_sync_uses_narrow_plan_facades() -> None:
    src = inspect.getsource(plan_sync_mod)
    assert "from desloppify.engine.plan import" not in src
    assert "desloppify.engine.plan_queue" in src


def test_flags_validation_and_assessment_state_helpers() -> None:
    with pytest.raises(flags_mod.ImportFlagValidationError):
        flags_mod.validate_import_flag_combos(
            attested_external=True,
            allow_partial=False,
            override_enabled=True,
            override_attest="ok",
        )
    with pytest.raises(flags_mod.ImportFlagValidationError):
        flags_mod.validate_import_flag_combos(
            attested_external=False,
            allow_partial=True,
            override_enabled=True,
            override_attest="ok",
        )

    keys = flags_mod.imported_assessment_keys(
        {"assessments": {"Naming Quality": 70, "": 50}}
    )
    assert keys == {"naming_quality"}

    state = {
        "scan_count": 4,
        "subjective_assessments": {"naming_quality": {"source": "holistic"}},
    }
    marked = flags_mod.mark_manual_override_assessments_provisional(
        state,
        assessment_keys={"naming_quality"},
    )
    assert marked == 1
    assert state["subjective_assessments"]["naming_quality"]["provisional_until_scan"] == 5

    cleared = flags_mod.clear_provisional_override_flags(
        state,
        assessment_keys={"naming_quality"},
    )
    assert cleared == 1
    assert state["subjective_assessments"]["naming_quality"]["source"] == "holistic"


def test_sync_plan_after_import_no_living_plan(monkeypatch) -> None:
    monkeypatch.setattr(plan_queue_mod, "has_living_plan", lambda: False)
    plan_sync_mod.sync_plan_after_import(
        state={},
        diff={"new": 1, "reopened": 0},
        assessment_mode="issues_only",
    )


def test_sync_plan_after_import_handles_plan_exceptions(monkeypatch, capsys) -> None:
    monkeypatch.setattr(plan_queue_mod, "has_living_plan", lambda: True)
    monkeypatch.setattr(
        plan_queue_mod,
        "load_plan",
        lambda: (_ for _ in ()).throw(OSError("boom")),
    )
    monkeypatch.setattr(plan_sync_mod, "PLAN_LOAD_EXCEPTIONS", (OSError,))

    plan_sync_mod.sync_plan_after_import(
        state={},
        diff={"new": 1, "reopened": 0},
        assessment_mode="issues_only",
    )
    out = capsys.readouterr().out
    assert "skipped plan sync after review import" in out


def test_sync_plan_after_import_runs_review_sync_for_auto_resolved_deltas(monkeypatch) -> None:
    plan: dict = {"queue_order": []}
    seen = {"import_called": False, "stale_called": False}

    monkeypatch.setattr(plan_queue_mod, "has_living_plan", lambda: True)
    monkeypatch.setattr(plan_queue_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(plan_queue_mod, "save_plan", lambda _plan: None)
    monkeypatch.setattr(plan_queue_mod, "current_unscored_ids", lambda _state: set())
    monkeypatch.setattr(plan_queue_mod, "purge_ids", lambda _plan, _ids: None)
    monkeypatch.setattr(
        plan_queue_mod,
        "compute_subjective_visibility",
        lambda *_a, **_k: SimpleNamespace(has_objective_backlog=False),
    )
    monkeypatch.setattr(plan_queue_mod, "ScoreSnapshot", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_communicate_score_needed",
        lambda _plan, _state, **_kwargs: SimpleNamespace(changes=False),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_import_scores_needed",
        lambda _plan, _state, assessment_mode: SimpleNamespace(changes=False),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_create_plan_needed",
        lambda _plan, _state, policy=None: SimpleNamespace(changes=False),
    )

    def fake_import_sync(_plan, _state, policy=None):
        seen["import_called"] = True
        return None

    def fake_stale_sync(_plan, _state, policy=None):
        seen["stale_called"] = True
        return SimpleNamespace(changes=False, injected=[], pruned=[])

    monkeypatch.setattr(plan_queue_mod, "sync_plan_after_review_import", fake_import_sync)
    monkeypatch.setattr(plan_queue_mod, "sync_stale_dimensions", fake_stale_sync)
    monkeypatch.setattr(plan_queue_mod, "append_log_entry", lambda *_a, **_k: None)

    plan_sync_mod.sync_plan_after_import(
        state={},
        diff={"new": 0, "reopened": 0, "auto_resolved": 2},
        assessment_mode="issues_only",
    )

    assert seen["import_called"] is True
    assert seen["stale_called"] is True


def test_sync_plan_after_import_logs_triage_provenance(monkeypatch) -> None:
    plan: dict = {"queue_order": []}
    entries: list[tuple[str, dict]] = []

    monkeypatch.setattr(plan_queue_mod, "has_living_plan", lambda: True)
    monkeypatch.setattr(plan_queue_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(plan_queue_mod, "save_plan", lambda _plan: None)
    monkeypatch.setattr(plan_queue_mod, "current_unscored_ids", lambda _state: set())
    monkeypatch.setattr(plan_queue_mod, "purge_ids", lambda _plan, _ids: None)
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_stale_dimensions",
        lambda _plan, _state, policy=None: SimpleNamespace(
            changes=False,
            injected=[],
            pruned=[],
        ),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_plan_after_review_import",
        lambda _plan, _state, policy=None: SimpleNamespace(
            new_ids={"review::x"},
            added_to_queue=["review::x"],
            triage_injected=True,
            stale_pruned_from_queue=[],
            triage_injected_ids=["triage::observe", "triage::reflect"],
            triage_deferred=False,
        ),
    )
    monkeypatch.setattr(plan_queue_mod, "ScoreSnapshot", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_communicate_score_needed",
        lambda _plan, _state, **_kwargs: SimpleNamespace(changes=False),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_import_scores_needed",
        lambda _plan, _state, assessment_mode: SimpleNamespace(changes=False),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "compute_subjective_visibility",
        lambda *_a, **_k: SimpleNamespace(has_objective_backlog=False),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_create_plan_needed",
        lambda _plan, _state, policy=None: SimpleNamespace(changes=False),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "append_log_entry",
        lambda _plan, action, **kwargs: entries.append((action, kwargs["detail"])),
    )

    plan_sync_mod.sync_plan_after_import(
        state={},
        diff={"new": 1, "reopened": 0},
        assessment_mode="issues_only",
    )

    assert entries
    action, detail = entries[-1]
    assert action == "review_import_sync"
    assert detail["triage_injected"] is True
    assert detail["triage_injected_ids"] == ["triage::observe", "triage::reflect"]
    assert detail["triage_deferred"] is False
    assert detail["stale_pruned_from_queue"] == []


def test_sync_plan_after_import_keeps_workflow_before_triage(monkeypatch) -> None:
    plan: dict = {
        "queue_order": [],
        "plan_start_scores": {"strict": 70.0, "overall": 70.0, "objective": 80.0, "verified": 80.0},
    }
    entries: list[tuple[str, dict]] = []

    monkeypatch.setattr(plan_queue_mod, "has_living_plan", lambda: True)
    monkeypatch.setattr(plan_queue_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(plan_queue_mod, "save_plan", lambda _plan: None)
    monkeypatch.setattr(plan_queue_mod, "current_unscored_ids", lambda _state: set())
    monkeypatch.setattr(plan_queue_mod, "purge_ids", lambda _plan, _ids: None)
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_stale_dimensions",
        lambda _plan, _state, policy=None: SimpleNamespace(
            changes=False,
            injected=[],
            pruned=[],
        ),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "ScoreSnapshot",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    def fake_communicate(_plan, _state, **_kwargs):
        _plan["queue_order"].append("workflow::communicate-score")
        plan_queue_mod.normalize_queue_workflow_and_triage_prefix(_plan["queue_order"])
        return SimpleNamespace(changes=True)

    def fake_create_plan(_plan, _state, policy=None):
        _plan["queue_order"].append("workflow::create-plan")
        plan_queue_mod.normalize_queue_workflow_and_triage_prefix(_plan["queue_order"])
        return SimpleNamespace(changes=True)

    def fake_review_import(_plan, _state, policy=None):
        _plan["queue_order"].extend(["review::x", "triage::observe"])
        return SimpleNamespace(
            new_ids={"review::x"},
            added_to_queue=["review::x"],
            triage_injected=True,
            stale_pruned_from_queue=[],
            triage_injected_ids=["triage::observe"],
            triage_deferred=False,
        )

    monkeypatch.setattr(plan_queue_mod, "sync_communicate_score_needed", fake_communicate)
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_import_scores_needed",
        lambda _plan, _state, assessment_mode: SimpleNamespace(changes=False),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "compute_subjective_visibility",
        lambda *_a, **_k: SimpleNamespace(has_objective_backlog=False),
    )
    monkeypatch.setattr(plan_queue_mod, "sync_create_plan_needed", fake_create_plan)
    monkeypatch.setattr(plan_queue_mod, "sync_plan_after_review_import", fake_review_import)
    monkeypatch.setattr(
        plan_queue_mod,
        "append_log_entry",
        lambda _plan, action, **kwargs: entries.append((action, kwargs["detail"])),
    )

    plan_sync_mod.sync_plan_after_import(
        state={"issues": {"review::x": {"summary": "new review issue"}}},
        diff={"new": 1, "reopened": 0},
        assessment_mode="trusted_internal",
    )

    assert plan["queue_order"][:2] == [
        "workflow::communicate-score",
        "workflow::create-plan",
    ]
    assert plan["queue_order"].index("workflow::communicate-score") < plan["queue_order"].index("triage::observe")
    assert plan["queue_order"].index("workflow::create-plan") < plan["queue_order"].index("triage::observe")
    action, detail = entries[-1]
    assert action == "review_import_sync"
    assert detail["workflow_injected_ids"] == [
        "workflow::communicate-score",
        "workflow::create-plan",
    ]


def test_sync_plan_after_import_reuses_plan_aware_policy(monkeypatch) -> None:
    plan: dict = {"queue_order": []}
    policy = SimpleNamespace(has_objective_backlog=False)
    seen: dict[str, object] = {}

    monkeypatch.setattr(plan_queue_mod, "has_living_plan", lambda: True)
    monkeypatch.setattr(plan_queue_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(plan_queue_mod, "save_plan", lambda _plan: None)
    monkeypatch.setattr(plan_queue_mod, "current_unscored_ids", lambda _state: set())
    monkeypatch.setattr(plan_queue_mod, "purge_ids", lambda _plan, _ids: None)
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_stale_dimensions",
        lambda _plan, _state, policy=None: SimpleNamespace(
            changes=False,
            injected=[],
            pruned=[],
        ),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "ScoreSnapshot",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_communicate_score_needed",
        lambda _plan, _state, **_kwargs: SimpleNamespace(changes=False),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_import_scores_needed",
        lambda _plan, _state, assessment_mode: SimpleNamespace(changes=False),
    )

    def fake_compute_policy(_state, *, target_strict, plan):
        seen["target_strict"] = target_strict
        seen["plan"] = plan
        return policy

    def fake_create_plan(_plan, _state, *, policy=None):
        seen["create_plan_policy"] = policy
        return SimpleNamespace(changes=False)

    def fake_review_import(_plan, _state, *, policy=None):
        seen["import_policy"] = policy
        return None

    def fake_stale_sync(_plan, _state, *, policy=None):
        seen["stale_policy"] = policy
        return SimpleNamespace(changes=False, injected=[], pruned=[])

    monkeypatch.setattr(plan_queue_mod, "compute_subjective_visibility", fake_compute_policy)
    monkeypatch.setattr(plan_queue_mod, "sync_create_plan_needed", fake_create_plan)
    monkeypatch.setattr(plan_queue_mod, "sync_plan_after_review_import", fake_review_import)
    monkeypatch.setattr(plan_queue_mod, "sync_stale_dimensions", fake_stale_sync)

    plan_sync_mod.sync_plan_after_import(
        state={},
        diff={"new": 1, "reopened": 0},
        assessment_mode="issues_only",
        config={"target_strict_score": 97},
    )

    assert seen["target_strict"] == 97.0
    assert seen["plan"] is plan
    assert seen["create_plan_policy"] is policy
    assert seen["import_policy"] is policy
    assert seen["stale_policy"] is policy


def test_sync_plan_after_import_does_not_purge_subjective_ids(monkeypatch) -> None:
    plan: dict = {"queue_order": ["subjective::naming_quality", "review::existing"]}
    purge_calls: list[list[str]] = []

    monkeypatch.setattr(plan_queue_mod, "has_living_plan", lambda: True)
    monkeypatch.setattr(plan_queue_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(plan_queue_mod, "save_plan", lambda _plan: None)
    monkeypatch.setattr(
        plan_queue_mod,
        "compute_subjective_visibility",
        lambda *_a, **_k: SimpleNamespace(has_objective_backlog=False),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "ScoreSnapshot",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_communicate_score_needed",
        lambda _plan, _state, **_kwargs: SimpleNamespace(changes=False),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_import_scores_needed",
        lambda _plan, _state, assessment_mode: SimpleNamespace(changes=False),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_create_plan_needed",
        lambda _plan, _state, policy=None: SimpleNamespace(changes=False),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_plan_after_review_import",
        lambda _plan, _state, policy=None: SimpleNamespace(
            new_ids={"review::new"},
            added_to_queue=["review::new"],
            triage_injected=False,
            stale_pruned_from_queue=[],
            triage_injected_ids=[],
            triage_deferred=False,
        ),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "sync_stale_dimensions",
        lambda _plan, _state, policy=None: SimpleNamespace(
            changes=False,
            injected=[],
            pruned=[],
        ),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "purge_ids",
        lambda _plan, ids: purge_calls.append(list(ids)),
    )
    monkeypatch.setattr(
        plan_queue_mod,
        "append_log_entry",
        lambda *_a, **_k: None,
    )

    plan_sync_mod.sync_plan_after_import(
        state={"issues": {"review::new": {"summary": "new review issue"}}},
        diff={"new": 1, "reopened": 0},
        assessment_mode="issues_only",
    )

    assert purge_calls == []
    assert "subjective::naming_quality" in plan["queue_order"]


def test_refresh_scorecard_after_import_only_for_trusted_assessments(monkeypatch) -> None:
    calls: list[tuple[object, dict, dict]] = []
    monkeypatch.setattr(
        import_cmd_mod,
        "emit_scorecard_badge",
        lambda args, config, state: (calls.append((args, config, state)), (None, None))[1],
    )

    trusted = SimpleNamespace(assessments_present=True, trusted=True)
    skipped = SimpleNamespace(assessments_present=True, trusted=False)
    scan_state = {
        "last_scan": "2026-03-10T00:00:00+00:00",
        "dimension_scores": {
            "Code quality": {
                "checks": 10,
                "score": 95.0,
                "strict": 95.0,
                "detectors": {"smells": {"potential": 10}},
            },
            "Naming quality": {
                "checks": 10,
                "score": 80.0,
                "strict": 80.0,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"}
                },
            },
        },
    }

    assert import_cmd_mod._refresh_scorecard_after_import(
        state=scan_state,
        config={"badge_path": "scorecard.png"},
        assessment_policy=trusted,
    ) is True
    assert len(calls) == 1

    assert import_cmd_mod._refresh_scorecard_after_import(
        state=scan_state,
        config={"badge_path": "scorecard.png"},
        assessment_policy=skipped,
    ) is False
    assert len(calls) == 1

    assert import_cmd_mod._refresh_scorecard_after_import(
        state={"strict_score": 74.5},
        config={"badge_path": "scorecard.png"},
        assessment_policy=trusted,
    ) is False
    assert len(calls) == 1


def test_refresh_scorecard_after_import_skips_subjective_only_state(monkeypatch) -> None:
    calls: list[tuple[object, dict, dict]] = []
    monkeypatch.setattr(
        import_cmd_mod,
        "emit_scorecard_badge",
        lambda args, config, state: (calls.append((args, config, state)), (None, None))[1],
    )
    trusted = SimpleNamespace(assessments_present=True, trusted=True)
    subjective_only_state = {
        "last_scan": "2026-03-10T00:00:00+00:00",
        "dimension_scores": {
            "Naming quality": {
                "checks": 10,
                "score": 100.0,
                "strict": 100.0,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"}
                },
            }
        },
    }

    assert import_cmd_mod._refresh_scorecard_after_import(
        state=subjective_only_state,
        config={"badge_path": "scorecard.png"},
        assessment_policy=trusted,
    ) is False
    assert calls == []


def test_print_import_results_writes_query_payload(monkeypatch) -> None:
    captured: list[dict] = []
    monkeypatch.setattr(results_mod.narrative_mod, "compute_narrative", lambda *_a, **_k: {"summary": "ok"})
    monkeypatch.setattr(results_mod.import_helpers_mod, "print_skipped_validation_details", lambda *_a, **_k: None)
    monkeypatch.setattr(results_mod.import_helpers_mod, "print_assessments_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(
        results_mod.import_helpers_mod,
        "print_open_review_summary",
        lambda *_a, **_k: "desloppify next",
    )
    monkeypatch.setattr(
        results_mod.import_helpers_mod,
        "print_review_import_scores_and_integrity",
        lambda *_a, **_k: [{"name": "Design coherence", "score": 95.0}],
    )
    monkeypatch.setattr(results_mod, "show_score_with_plan_context", lambda *_a, **_k: None)
    monkeypatch.setattr(results_mod, "write_query", lambda payload: captured.append(payload))

    results_mod.print_import_results(
        state={"issues": {}},
        lang_name="python",
        config={},
        diff={"new": 2, "auto_resolved": 1, "reopened": 0},
        prev=SimpleNamespace(overall=0),
        label="Holistic review",
        provisional_count=0,
        assessment_policy=SimpleNamespace(mode="issues_only", trusted=False, reason="untrusted"),
        scorecard_subjective_at_target_fn=lambda *_a, **_k: [],
    )

    assert captured
    payload = captured[0]
    assert payload["command"] == "review"
    assert payload["action"] == "import"
    assert payload["next_command"] == "desloppify next"
    assert payload["assessment_import"]["mode"] == "issues_only"
