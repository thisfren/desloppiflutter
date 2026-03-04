"""Review configuration exports for TypeScript."""

from __future__ import annotations

from desloppify.languages.typescript.review import (
    HOLISTIC_REVIEW_DIMENSIONS as TS_HOLISTIC_REVIEW_DIMENSIONS,
)
from desloppify.languages.typescript.review import LOW_VALUE_PATTERN as TS_LOW_VALUE_PATTERN
from desloppify.languages.typescript.review import (
    MIGRATION_MIXED_EXTENSIONS as TS_MIGRATION_MIXED_EXTENSIONS,
)
from desloppify.languages.typescript.review import (
    MIGRATION_PATTERN_PAIRS as TS_MIGRATION_PATTERN_PAIRS,
)
from desloppify.languages.typescript.review import REVIEW_GUIDANCE as TS_REVIEW_GUIDANCE
from desloppify.languages.typescript.review import api_surface as ts_review_api_surface
from desloppify.languages.typescript.review import (
    module_patterns as ts_review_module_patterns,
)

__all__ = [
    "TS_HOLISTIC_REVIEW_DIMENSIONS",
    "TS_LOW_VALUE_PATTERN",
    "TS_MIGRATION_MIXED_EXTENSIONS",
    "TS_MIGRATION_PATTERN_PAIRS",
    "TS_REVIEW_GUIDANCE",
    "ts_review_api_surface",
    "ts_review_module_patterns",
]
