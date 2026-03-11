"""Recovery tests for saved plan metadata when scan state is missing."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import desloppify.app.commands.plan.queue_render as queue_render_mod
import desloppify.app.commands.plan.triage.workflow as workflow_mod
from desloppify.app.commands.helpers.runtime import CommandRuntime


def test_cmd_plan_queue_recovers_saved_plan_state(monkeypatch, capsys) -> None:
    """Queue rendering should continue from saved plan metadata without a scan file."""
    captured_states: list[dict] = []
    plan = {
        "queue_order": ["review::src/foo.ts::abcd1234"],
        "clusters": {
            "cluster-a": {
                "issue_ids": [],
                "action_steps": [
                    {"title": "Fix", "issue_refs": ["review::src/foo.ts::abcd1234"]},
                ],
                "description": "Recovered cluster",
                "auto": False,
            }
        },
        "epic_triage_meta": {"triage_stages": {"observe": {"report": "done"}}},
        "skipped": {},
    }

    monkeypatch.setattr(
        queue_render_mod,
        "command_runtime",
        lambda _args: CommandRuntime(config={}, state={"issues": {}, "last_scan": None}, state_path=None),
    )
    monkeypatch.setattr(queue_render_mod, "load_plan", lambda: plan)
    monkeypatch.setattr(queue_render_mod, "print_triage_guardrail_info", lambda **_kw: None)

    def _fake_build_execution_queue(state, *, options=None):
        del options
        captured_states.append(state)
        return {"items": [], "total": 0, "grouped": {}, "new_ids": set()}

    monkeypatch.setattr(queue_render_mod, "build_execution_queue", _fake_build_execution_queue)

    args = argparse.Namespace(top=30, cluster=None, include_skipped=False, sort="priority")
    queue_render_mod.cmd_plan_queue(args)

    out = capsys.readouterr().out
    assert "rendering queue from saved plan metadata only" in out
    assert captured_states
    assert "review::src/foo.ts::abcd1234" in captured_states[0]["issues"]


def test_run_triage_workflow_recovers_runtime_state(monkeypatch, capsys) -> None:
    """Triage workflow should inject recovered runtime state for downstream handlers."""
    plan = {
        "queue_order": ["review::src/foo.ts::abcd1234"],
        "clusters": {
            "cluster-a": {
                "issue_ids": [],
                "action_steps": [
                    {"title": "Fix", "issue_refs": ["review::src/foo.ts::abcd1234"]},
                ],
                "description": "Recovered cluster",
                "auto": False,
            }
        },
        "epic_triage_meta": {"triage_stages": {"observe": {"report": "done"}}},
    }
    calls: list[dict] = []
    scan_gate_calls: list[dict] = []

    services = SimpleNamespace(
        command_runtime=lambda _args: CommandRuntime(
            config={},
            state={"issues": {}, "last_scan": None},
            state_path=None,
        ),
        load_plan=lambda: plan,
    )

    monkeypatch.setattr(
        workflow_mod._display_mod,
        "cmd_triage_dashboard",
        lambda args, services=None: calls.append(services.command_runtime(args).state),
    )

    workflow_mod.run_triage_workflow(
        argparse.Namespace(
            stage_prompt=None,
            run_stages=False,
            start=False,
            confirm=None,
            complete=False,
            confirm_existing=False,
            stage=None,
            dry_run=False,
        ),
        services=services,
        require_completed_scan_fn=lambda state: scan_gate_calls.append(state) or False,
    )

    out = capsys.readouterr().out
    assert "continuing triage from saved plan metadata only" in out
    assert not scan_gate_calls
    assert calls
    assert "review::src/foo.ts::abcd1234" in calls[0]["issues"]
