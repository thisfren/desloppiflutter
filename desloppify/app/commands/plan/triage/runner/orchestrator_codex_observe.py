"""Observe-stage parallel codex execution helpers."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from desloppify.app.commands.review._runner_parallel_types import BatchExecutionOptions, BatchProgressEvent
from desloppify.app.commands.review.runner_parallel import execute_batches
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.output.terminal import colorize

from ..helpers import group_issues_into_observe_batches
from .codex_runner import _output_file_has_text, run_triage_stage
from .stage_prompts import build_observe_batch_prompt


def _merge_observe_outputs(
    batch_outputs: list[tuple[list[str], Path]],
) -> str:
    """Concatenate batch outputs with dimension headers into single observe report."""
    parts: list[str] = []
    for dims, output_file in batch_outputs:
        header = f"## Dimensions: {', '.join(dims)}"
        content = ""
        if output_file.exists():
            try:
                content = output_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                content = "(batch output missing)"
        if not content:
            content = "(batch produced no output)"
        parts.append(f"{header}\n\n{content}")
    return "\n\n---\n\n".join(parts)


def run_observe(
    *,
    si,
    repo_root: Path,
    prompts_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    timeout_seconds: int,
    dry_run: bool = False,
    append_run_log=None,
) -> tuple[bool, str]:
    """Run observe stage via codex subprocess batches."""
    _log = append_run_log or (lambda _msg: None)

    batches = group_issues_into_observe_batches(si)
    total = len(batches)
    print(colorize(f"\n  Observe: splitting into {total} parallel batches.", "bold"))
    _log(f"observe-parallel batches={total}")

    tasks: dict[int, object] = {}
    batch_meta: list[tuple[list[str], Path]] = []

    for i, (dims, issues_subset) in enumerate(batches):
        prompt = build_observe_batch_prompt(
            batch_index=i + 1,
            total_batches=total,
            dimension_group=dims,
            issues_subset=issues_subset,
            repo_root=repo_root,
        )
        prompt_file = prompts_dir / f"observe_batch_{i}.md"
        safe_write_text(prompt_file, prompt)

        output_file = output_dir / f"observe_batch_{i}.raw.txt"
        log_file = logs_dir / f"observe_batch_{i}.log"
        batch_meta.append((dims, output_file))

        if not dry_run:
            tasks[i] = partial(
                run_triage_stage,
                prompt=prompt,
                repo_root=repo_root,
                output_file=output_file,
                log_file=log_file,
                timeout_seconds=timeout_seconds,
                validate_output_fn=_output_file_has_text,
            )

        dim_list = ", ".join(dims)
        print(colorize(f"    Batch {i + 1}: {len(issues_subset)} issues ({dim_list})", "dim"))
        _log(f"observe-batch batch={i + 1} issues={len(issues_subset)} dims={dim_list}")

    if dry_run:
        print(colorize("  [dry-run] Would execute parallel observe batches.", "dim"))
        return True, ""

    def _progress(event: BatchProgressEvent) -> None:
        idx = event.batch_index
        if event.event == "start":
            print(colorize(f"    Observe batch {idx + 1}/{total} started", "dim"))
            _log(f"observe-batch-start batch={idx + 1}")
        elif event.event == "done":
            elapsed = event.details.get("elapsed_seconds", 0) if event.details else 0
            status = "done" if event.code == 0 else f"failed ({event.code})"
            tone = "dim" if event.code == 0 else "yellow"
            print(colorize(f"    Observe batch {idx + 1}/{total} {status} in {int(elapsed)}s", tone))
            _log(f"observe-batch-done batch={idx + 1} code={event.code} elapsed={int(elapsed)}s")
        elif event.event == "heartbeat":
            details = event.details or {}
            active = details.get("active_batches", [])
            elapsed_map = details.get("elapsed_seconds", {})
            if active:
                parts = [f"#{i + 1}:{int(elapsed_map.get(i, 0))}s" for i in active[:6]]
                print(colorize(f"    Observe heartbeat: {len(active)}/{total} active ({', '.join(parts)})", "dim"))

    def _error_log(batch_index: int, exc: Exception) -> None:
        _log(f"observe-batch-error batch={batch_index + 1} error={exc}")

    failures = execute_batches(
        tasks=tasks,
        options=BatchExecutionOptions(run_parallel=True, heartbeat_seconds=15.0),
        progress_fn=_progress,
        error_log_fn=_error_log,
    )

    if failures:
        print(colorize(f"  Observe: {len(failures)} batch(es) failed: {failures}", "red"))
        for idx in failures:
            log_file = logs_dir / f"observe_batch_{idx}.log"
            print(colorize(f"    Check log: {log_file}", "dim"))
        _log(f"observe-parallel-failed failures={failures}")
        return False, ""

    merged = _merge_observe_outputs(batch_meta)
    print(colorize(f"  Observe: merged {total} batch outputs ({len(merged)} chars).", "green"))
    _log(f"observe-parallel-done merged_chars={len(merged)}")
    return True, merged


__all__ = ["run_observe"]
