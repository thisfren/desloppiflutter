"""Cache primitives for tree-sitter import resolution."""

from __future__ import annotations

import logging

_go_modules: dict[str, str] = {}


def reset_import_cache() -> None:
    """Reset cached resolver state used by import helpers."""
    _go_modules.clear()


def _read_go_module_path(
    go_mod_path: str,
    *,
    logger: logging.Logger | None = None,
) -> str:
    """Read module path from go.mod with caching."""
    if logger is None:
        logger = logging.getLogger(__name__)
    if go_mod_path in _go_modules:
        return _go_modules[go_mod_path]

    module_path = ""
    try:
        with open(go_mod_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("module "):
                    module_path = line.split(None, 1)[1].strip()
                    break
    except OSError as exc:
        logger.debug("Failed to read go.mod at %s: %s", go_mod_path, exc)

    _go_modules[go_mod_path] = module_path
    return module_path


__all__ = ["_read_go_module_path", "reset_import_cache"]
