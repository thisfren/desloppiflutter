"""Score/value accessor helpers for state schema payloads."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from desloppify.engine._state.schema import StateModel


def json_default(obj: Any) -> Any:
    """JSON serializer fallback for known non-JSON-native state values."""
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, Path):
        return str(obj).replace("\\", "/")
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON serializable: {obj!r}"
    )


def get_overall_score(state: StateModel) -> float | None:
    value = state.get("overall_score")
    return float(value) if isinstance(value, int | float) else None


def get_objective_score(state: StateModel) -> float | None:
    value = state.get("objective_score")
    return float(value) if isinstance(value, int | float) else None


def get_strict_score(state: StateModel) -> float | None:
    value = state.get("strict_score")
    return float(value) if isinstance(value, int | float) else None


def get_verified_strict_score(state: StateModel) -> float | None:
    value = state.get("verified_strict_score")
    return float(value) if isinstance(value, int | float) else None


__all__ = [
    "get_objective_score",
    "get_overall_score",
    "get_strict_score",
    "get_verified_strict_score",
    "json_default",
]
