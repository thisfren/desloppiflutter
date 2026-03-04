"""Parallel execution and progress-callback helpers for review batches."""

from __future__ import annotations

import json
from pathlib import Path

from desloppify.base.discovery.file_paths import safe_write_text

from ._runner_parallel_execution import (
    _complete_parallel_future,
    _drain_parallel_completions,
    _execute_parallel,
    _execute_serial,
    _heartbeat,
    _queue_parallel_tasks,
    _resolve_parallel_runtime,
    _run_parallel_task,
)
from ._runner_parallel_progress import (
    _RUNNER_CALLBACK_EXCEPTIONS,
    _RUNNER_TASK_EXCEPTIONS,
    _coerce_batch_execution_options,
    _emit_progress,
    _progress_contract,
    _record_execution_error,
    _record_progress_error,
)
from ._runner_parallel_types import (
    BatchExecutionOptions,
    BatchProgressEvent,
    BatchResult,
    BatchTask,
)
from .runner_process import _extract_payload_from_log


def execute_batches(
    *,
    tasks: dict[int, BatchTask],
    options: BatchExecutionOptions | None = None,
    progress_fn=None,
    error_log_fn=None,
) -> list[int]:
    """Run indexed tasks and return failed index list.

    Each value in *tasks* is a zero-arg callable returning an int exit code.
    All domain knowledge (files, prompts, etc.) is pre-bound by the caller.
    """
    resolved_options = _coerce_batch_execution_options(options)
    contract_cache: dict[int, str] = {}
    indexes = sorted(tasks)
    if resolved_options.run_parallel:
        return _execute_parallel(
            tasks=tasks,
            indexes=indexes,
            progress_fn=progress_fn,
            error_log_fn=error_log_fn,
            max_parallel_workers=resolved_options.max_parallel_workers,
            heartbeat_seconds=resolved_options.heartbeat_seconds,
            clock_fn=resolved_options.clock_fn,
            contract_cache=contract_cache,
        )
    return _execute_serial(
        tasks=tasks,
        indexes=indexes,
        progress_fn=progress_fn,
        error_log_fn=error_log_fn,
        clock_fn=resolved_options.clock_fn,
        contract_cache=contract_cache,
    )


def collect_batch_results(
    *,
    selected_indexes: list[int],
    failures: list[int],
    output_files: dict[int, Path],
    allowed_dims: set[str],
    extract_payload_fn,
    normalize_result_fn,
) -> tuple[list[BatchResult], list[int]]:
    """Parse and normalize batch outputs, preserving prior failures."""
    batch_results: list[BatchResult] = []
    failure_set = set(failures)
    for idx in selected_indexes:
        had_execution_failure = idx in failure_set
        raw_path = output_files[idx]
        payload = None
        parsed_from_log = False
        if raw_path.exists():
            try:
                payload = extract_payload_fn(raw_path.read_text())
            except OSError:
                payload = None
        if payload is None:
            payload = _extract_payload_from_log(idx, raw_path, extract_payload_fn)
            parsed_from_log = payload is not None
        if payload is None:
            failure_set.add(idx)
            continue
        if parsed_from_log:
            try:
                safe_write_text(raw_path, json.dumps(payload, indent=2) + "\n")
            except OSError:
                pass
        try:
            assessments, issues, dimension_notes, quality = normalize_result_fn(
                payload,
                allowed_dims,
            )
        except ValueError:
            failure_set.add(idx)
            continue
        if had_execution_failure:
            failure_set.discard(idx)
        batch_results.append(
            BatchResult(
                batch_index=idx + 1,
                assessments=assessments,
                dimension_notes=dimension_notes,
                issues=issues,
                quality=quality,
            )
        )
    return batch_results, sorted(failure_set)


__all__ = [
    "BatchResult",
    "BatchExecutionOptions",
    "BatchProgressEvent",
    "collect_batch_results",
    "execute_batches",
]
