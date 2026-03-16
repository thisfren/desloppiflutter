"""Internal spec aggregation for tree-sitter language specs.

Canonical public imports should come from ``treesitter.__init__``.
This module remains a compatibility layer for internal aggregation.
"""

from __future__ import annotations

from .compiled import DART_SPEC
from .scripting import TYPESCRIPT_SPEC

TREESITTER_SPECS = {
    "dart": DART_SPEC,
    "typescript": TYPESCRIPT_SPEC,
}

__all__ = [
    "DART_SPEC",
    "TREESITTER_SPECS",
    "TYPESCRIPT_SPEC",
]
