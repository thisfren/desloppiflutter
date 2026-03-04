"""Fixer registry assembly for TypeScript."""

from __future__ import annotations

from desloppify.languages._framework.base.types import FixerConfig
from desloppify.languages.typescript import fixers as ts_fixers_mod
from desloppify.languages.typescript.detectors import logs as logs_detector_mod
from desloppify.languages.typescript.detectors import smells as smells_detector_mod
from desloppify.languages.typescript.detectors import unused as unused_detector_mod


def _det_unused(cat):
    """Create a detector function for a specific unused category."""

    def f(path):
        return unused_detector_mod.detect_unused(path, category=cat)[0]

    return f


def _det_logs(path):
    """Detect tagged debug logs."""
    return logs_detector_mod.detect_logs(path)[0]


def _det_smell(smell_id):
    """Create a detector function for a specific smell ID."""

    def f(path):
        return next(
            (
                e.get("matches", [])
                for e in smells_detector_mod.detect_smells(path)[0]
                if e["id"] == smell_id
            ),
            [],
        )

    return f


def _fix_vars(entries, *, dry_run=False):
    """Fix unused vars, returning FixResult."""
    return ts_fixers_mod.fix_unused_vars(entries, dry_run=dry_run)


def _fix_logs(entries, *, dry_run=False):
    """Fix debug logs, normalizing result keys."""
    result = ts_fixers_mod.fix_debug_logs(entries, dry_run=dry_run)
    for r in result.entries:
        r["removed"] = r.get("tags", r.get("removed", []))
    return result


def get_ts_fixers() -> dict[str, FixerConfig]:
    """Build the TypeScript fixer registry (lazy-loaded)."""
    removed, would_remove = "Removed", "Would remove"
    return {
        "unused-imports": FixerConfig(
            "unused imports",
            _det_unused("imports"),
            ts_fixers_mod.fix_unused_imports,
            "unused",
            removed,
            would_remove,
        ),
        "debug-logs": FixerConfig(
            "tagged debug logs",
            _det_logs,
            _fix_logs,
            "logs",
            removed,
            would_remove,
        ),
        "unused-vars": FixerConfig(
            "unused vars",
            _det_unused("vars"),
            _fix_vars,
            "unused",
            removed,
            would_remove,
        ),
        "unused-params": FixerConfig(
            "unused params",
            _det_unused("vars"),
            ts_fixers_mod.fix_unused_params,
            "unused",
            "Prefixed",
            "Would prefix",
        ),
        "dead-useeffect": FixerConfig(
            "dead useEffect calls",
            _det_smell("dead_useeffect"),
            ts_fixers_mod.fix_dead_useeffect,
            "smells",
            removed,
            would_remove,
        ),
        "empty-if-chain": FixerConfig(
            "empty if/else chains",
            _det_smell("empty_if_chain"),
            ts_fixers_mod.fix_empty_if_chain,
            "smells",
            removed,
            would_remove,
        ),
    }


__all__ = ["get_ts_fixers"]
