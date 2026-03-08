"""Sense-check parallel codex execution helpers."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from desloppify.app.commands.review._runner_parallel_types import BatchExecutionOptions, BatchProgressEvent
from desloppify.app.commands.review.runner_parallel import execute_batches
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.output.terminal import colorize

from ..helpers import manual_clusters_with_issues
from .codex_runner import _output_file_has_text, run_triage_stage
from .stage_prompts import build_sense_check_content_prompt, build_sense_check_structure_prompt


def run_sense_check(
    *,
    plan: dict,
    repo_root: Path,
    prompts_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    timeout_seconds: int,
    dry_run: bool = False,
    append_run_log=None,
) -> tuple[bool, str]:
    """Run sense-check via parallel codex subprocess batches."""
    _log = append_run_log or (lambda _msg: None)

    clusters = manual_clusters_with_issues(plan)
    total_content = len(clusters)
    total = total_content + 1
    print(colorize(f"\n  Sense-check: {total_content} content batches + 1 structure batch.", "bold"))
    _log(f"sense-check-parallel content_batches={total_content}")

    tasks: dict[int, object] = {}
    batch_meta: list[tuple[str, Path]] = []

    for i, cluster_name in enumerate(clusters):
        prompt = build_sense_check_content_prompt(cluster_name=cluster_name, plan=plan, repo_root=repo_root)
        prompt_file = prompts_dir / f"sense_check_content_{i}.md"
        safe_write_text(prompt_file, prompt)

        output_file = output_dir / f"sense_check_content_{i}.raw.txt"
        log_file = logs_dir / f"sense_check_content_{i}.log"
        batch_meta.append((f"content:{cluster_name}", output_file))

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
        print(colorize(f"    Content batch {i + 1}: {cluster_name}", "dim"))
        _log(f"sense-check-content batch={i + 1} cluster={cluster_name}")

    structure_idx = total_content
    structure_prompt = build_sense_check_structure_prompt(plan=plan, repo_root=repo_root)
    prompt_file = prompts_dir / "sense_check_structure.md"
    safe_write_text(prompt_file, structure_prompt)

    structure_output = output_dir / "sense_check_structure.raw.txt"
    structure_log = logs_dir / "sense_check_structure.log"
    batch_meta.append(("structure", structure_output))

    if not dry_run:
        tasks[structure_idx] = partial(
            run_triage_stage,
            prompt=structure_prompt,
            repo_root=repo_root,
            output_file=structure_output,
            log_file=structure_log,
            timeout_seconds=timeout_seconds,
            validate_output_fn=_output_file_has_text,
        )
    print(colorize("    Structure batch: global dependency check", "dim"))
    _log("sense-check-structure batch=global")

    if dry_run:
        print(colorize("  [dry-run] Would execute parallel sense-check batches.", "dim"))
        return True, ""

    def _progress(event: BatchProgressEvent) -> None:
        idx = event.batch_index
        label = batch_meta[idx][0] if idx < len(batch_meta) else f"batch-{idx}"
        if event.event == "start":
            print(colorize(f"    Sense-check {label} started", "dim"))
            _log(f"sense-check-batch-start {label}")
        elif event.event == "done":
            elapsed = event.details.get("elapsed_seconds", 0) if event.details else 0
            status = "done" if event.code == 0 else f"failed ({event.code})"
            tone = "dim" if event.code == 0 else "yellow"
            print(colorize(f"    Sense-check {label} {status} in {int(elapsed)}s", tone))
            _log(f"sense-check-batch-done {label} code={event.code} elapsed={int(elapsed)}s")

    def _error_log(batch_index: int, exc: Exception) -> None:
        _log(f"sense-check-batch-error batch={batch_index} error={exc}")

    failures = execute_batches(
        tasks=tasks,
        options=BatchExecutionOptions(run_parallel=True, heartbeat_seconds=15.0),
        progress_fn=_progress,
        error_log_fn=_error_log,
    )

    if failures:
        print(colorize(f"  Sense-check: {len(failures)} batch(es) failed: {failures}", "red"))
        _log(f"sense-check-parallel-failed failures={failures}")
        return False, ""

    parts: list[str] = []
    for label, output_file in batch_meta:
        content = ""
        if output_file.exists():
            try:
                content = output_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                content = "(output missing)"
        if not content:
            content = "(no output)"
        parts.append(f"## {label}\n\n{content}")

    merged = "\n\n---\n\n".join(parts)
    print(colorize(f"  Sense-check: merged {total} batch outputs ({len(merged)} chars).", "green"))
    _log(f"sense-check-parallel-done merged_chars={len(merged)}")
    return True, merged


__all__ = ["run_sense_check"]
