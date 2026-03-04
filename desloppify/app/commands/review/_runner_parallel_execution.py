"""Serial/parallel execution loops for review batch tasks."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError

from desloppify.base.output.fallbacks import log_best_effort_failure

from ._runner_parallel_progress import (
    _RUNNER_CALLBACK_EXCEPTIONS,
    _RUNNER_TASK_EXCEPTIONS,
    _emit_progress,
    _record_execution_error,
    _record_progress_error,
)
from ._runner_parallel_types import BatchTask

logger = logging.getLogger(__name__)


def _execute_serial(
    *,
    tasks: dict[int, BatchTask],
    indexes: list[int],
    progress_fn,
    error_log_fn,
    clock_fn,
    contract_cache: dict[int, str],
) -> list[int]:
    """Run tasks one at a time — no threads, no closures."""
    failures: set[int] = set()
    for idx in indexes:
        t0 = float(clock_fn())
        start_error = _emit_progress(
            progress_fn,
            idx,
            "start",
            None,
            details={"max_workers": 1},
            contract_cache=contract_cache,
        )
        if start_error is not None:
            _record_execution_error(
                error_log_fn=error_log_fn,
                failures=failures,
                idx=idx,
                exc=start_error,
            )
        try:
            code = tasks[idx]()
        except _RUNNER_TASK_EXCEPTIONS as exc:
            _record_execution_error(
                error_log_fn=error_log_fn,
                failures=failures,
                idx=idx,
                exc=exc,
            )
            code = 1
        if code != 0:
            failures.add(idx)
        done_error = _emit_progress(
            progress_fn,
            idx,
            "done",
            code,
            details={"elapsed_seconds": int(max(0.0, clock_fn() - t0))},
            contract_cache=contract_cache,
        )
        if done_error is not None:
            _record_execution_error(
                error_log_fn=error_log_fn,
                failures=failures,
                idx=idx,
                exc=done_error,
            )
    return sorted(failures)


def _execute_parallel(
    *,
    tasks: dict[int, BatchTask],
    indexes: list[int],
    progress_fn,
    error_log_fn,
    max_parallel_workers,
    heartbeat_seconds,
    clock_fn,
    contract_cache: dict[int, str],
) -> list[int]:
    """Run tasks in a thread pool with optional heartbeat monitoring."""
    max_workers, heartbeat = _resolve_parallel_runtime(
        indexes=indexes,
        max_parallel_workers=max_parallel_workers,
        heartbeat_seconds=heartbeat_seconds,
    )
    failures: set[int] = set()
    progress_failures: set[int] = set()
    started_at: dict[int, float] = {}
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = _queue_parallel_tasks(
            executor=executor,
            indexes=indexes,
            tasks=tasks,
            progress_fn=progress_fn,
            error_log_fn=error_log_fn,
            contract_cache=contract_cache,
            max_workers=max_workers,
            failures=failures,
            progress_failures=progress_failures,
            started_at=started_at,
            lock=lock,
            clock_fn=clock_fn,
        )
        pending = set(futures.keys())
        _drain_parallel_completions(
            pending=pending,
            futures=futures,
            heartbeat=heartbeat,
            indexes=indexes,
            progress_fn=progress_fn,
            error_log_fn=error_log_fn,
            contract_cache=contract_cache,
            failures=failures,
            progress_failures=progress_failures,
            started_at=started_at,
            lock=lock,
            clock_fn=clock_fn,
        )
    return sorted(failures)


def _resolve_parallel_runtime(
    *,
    indexes: list[int],
    max_parallel_workers,
    heartbeat_seconds,
) -> tuple[int, float | None]:
    requested = (
        int(max_parallel_workers)
        if isinstance(max_parallel_workers, int) and max_parallel_workers > 0
        else 8
    )
    max_workers = max(1, min(len(indexes), requested))
    heartbeat = (
        float(heartbeat_seconds)
        if isinstance(heartbeat_seconds, int | float) and heartbeat_seconds > 0
        else None
    )
    return max_workers, heartbeat


def _run_parallel_task(
    *,
    idx: int,
    tasks: dict[int, BatchTask],
    progress_fn,
    error_log_fn,
    contract_cache: dict[int, str],
    max_workers: int,
    progress_failures: set[int],
    started_at: dict[int, float],
    lock: threading.Lock,
    clock_fn,
) -> int:
    with lock:
        started_at[idx] = float(clock_fn())
    progress_error = _emit_progress(
        progress_fn,
        idx,
        "start",
        None,
        details={"max_workers": max_workers},
        contract_cache=contract_cache,
    )
    if progress_error is not None:
        _record_progress_error(
            idx=idx,
            err=progress_error,
            progress_failures=progress_failures,
            lock=lock,
            error_log_fn=error_log_fn,
        )
    return tasks[idx]()


def _queue_parallel_tasks(
    *,
    executor: ThreadPoolExecutor,
    indexes: list[int],
    tasks: dict[int, BatchTask],
    progress_fn,
    error_log_fn,
    contract_cache: dict[int, str],
    max_workers: int,
    failures: set[int],
    progress_failures: set[int],
    started_at: dict[int, float],
    lock: threading.Lock,
    clock_fn,
) -> dict:
    futures: dict = {}
    for idx in indexes:
        queue_error = _emit_progress(
            progress_fn,
            idx,
            "queued",
            None,
            details={"max_workers": max_workers},
            contract_cache=contract_cache,
        )
        if queue_error is not None:
            _record_progress_error(
                idx=idx,
                err=queue_error,
                progress_failures=progress_failures,
                lock=lock,
                error_log_fn=error_log_fn,
            )
            failures.add(idx)
        futures[
            executor.submit(
                _run_parallel_task,
                idx=idx,
                tasks=tasks,
                progress_fn=progress_fn,
                error_log_fn=error_log_fn,
                contract_cache=contract_cache,
                max_workers=max_workers,
                progress_failures=progress_failures,
                started_at=started_at,
                lock=lock,
                clock_fn=clock_fn,
            )
        ] = idx
    return futures


def _complete_parallel_future(
    *,
    future,
    futures: dict,
    progress_fn,
    error_log_fn,
    contract_cache: dict[int, str],
    failures: set[int],
    progress_failures: set[int],
    started_at: dict[int, float],
    lock: threading.Lock,
    clock_fn,
) -> None:
    idx = futures[future]
    with lock:
        t0 = started_at.get(idx, float(clock_fn()))
    elapsed = int(max(0.0, clock_fn() - t0))
    try:
        code = future.result()
    except _RUNNER_TASK_EXCEPTIONS as exc:
        _record_execution_error(
            error_log_fn=error_log_fn,
            failures=failures,
            idx=idx,
            exc=exc,
        )
        done_error = _emit_progress(
            progress_fn,
            idx,
            "done",
            1,
            details={"elapsed_seconds": elapsed},
            contract_cache=contract_cache,
        )
        if done_error is not None:
            _record_progress_error(
                idx=idx,
                err=done_error,
                progress_failures=progress_failures,
                lock=lock,
                error_log_fn=error_log_fn,
            )
        return

    done_error = _emit_progress(
        progress_fn,
        idx,
        "done",
        code,
        details={"elapsed_seconds": elapsed},
        contract_cache=contract_cache,
    )
    if done_error is not None:
        _record_progress_error(
            idx=idx,
            err=done_error,
            progress_failures=progress_failures,
            lock=lock,
            error_log_fn=error_log_fn,
        )

    with lock:
        had_progress_failure = idx in progress_failures
    if code != 0 or had_progress_failure:
        failures.add(idx)


def _drain_parallel_completions(
    *,
    pending: set,
    futures: dict,
    heartbeat: float | None,
    indexes: list[int],
    progress_fn,
    error_log_fn,
    contract_cache: dict[int, str],
    failures: set[int],
    progress_failures: set[int],
    started_at: dict[int, float],
    lock: threading.Lock,
    clock_fn,
) -> None:
    if heartbeat is None:
        for future in as_completed(pending):
            _complete_parallel_future(
                future=future,
                futures=futures,
                progress_fn=progress_fn,
                error_log_fn=error_log_fn,
                contract_cache=contract_cache,
                failures=failures,
                progress_failures=progress_failures,
                started_at=started_at,
                lock=lock,
                clock_fn=clock_fn,
            )
        return

    while pending:
        try:
            future = next(as_completed(pending, timeout=heartbeat))
        except FuturesTimeoutError:
            _heartbeat(
                pending,
                futures,
                started_at,
                lock,
                indexes,
                progress_fn,
                clock_fn,
                error_log_fn=error_log_fn,
                contract_cache=contract_cache,
            )
            continue
        pending.discard(future)
        _complete_parallel_future(
            future=future,
            futures=futures,
            progress_fn=progress_fn,
            error_log_fn=error_log_fn,
            contract_cache=contract_cache,
            failures=failures,
            progress_failures=progress_failures,
            started_at=started_at,
            lock=lock,
            clock_fn=clock_fn,
        )


def _heartbeat(
    pending,
    futures,
    started_at,
    lock,
    indexes,
    progress_fn,
    clock_fn,
    *,
    error_log_fn=None,
    contract_cache: dict[int, str] | None = None,
):
    """Build and emit a heartbeat with active/queued batch status."""
    with lock:
        active = sorted(futures[f] for f in pending if futures[f] in started_at)
    active_set = set(active)
    queued = sorted(futures[f] for f in pending if futures[f] not in active_set)
    elapsed = {
        idx: int(max(0.0, clock_fn() - started_at.get(idx, clock_fn())))
        for idx in active
    }
    heartbeat_error = _emit_progress(
        progress_fn,
        -1,
        "heartbeat",
        None,
        details={
            "active_batches": active,
            "queued_batches": queued,
            "elapsed_seconds": elapsed,
            "active_count": len(active),
            "queued_count": len(queued),
            "total_count": len(indexes),
        },
        contract_cache=contract_cache,
    )
    if heartbeat_error is not None and callable(error_log_fn):
        try:
            error_log_fn(-1, heartbeat_error)
        except _RUNNER_CALLBACK_EXCEPTIONS as exc:
            log_best_effort_failure(
                logger,
                "record batch heartbeat failure via callback",
                exc,
            )


__all__ = [
    "_complete_parallel_future",
    "_drain_parallel_completions",
    "_execute_parallel",
    "_execute_serial",
    "_heartbeat",
    "_queue_parallel_tasks",
    "_resolve_parallel_runtime",
    "_run_parallel_task",
]
