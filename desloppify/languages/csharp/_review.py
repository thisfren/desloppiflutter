"""Review configuration exports for C#."""

from __future__ import annotations

from desloppify.languages.csharp.review import (
    HOLISTIC_REVIEW_DIMENSIONS as CSHARP_HOLISTIC_REVIEW_DIMENSIONS,
)
from desloppify.languages.csharp.review import LOW_VALUE_PATTERN as CSHARP_LOW_VALUE_PATTERN
from desloppify.languages.csharp.review import (
    MIGRATION_MIXED_EXTENSIONS as CSHARP_MIGRATION_MIXED_EXTENSIONS,
)
from desloppify.languages.csharp.review import (
    MIGRATION_PATTERN_PAIRS as CSHARP_MIGRATION_PATTERN_PAIRS,
)
from desloppify.languages.csharp.review import REVIEW_GUIDANCE as CSHARP_REVIEW_GUIDANCE
from desloppify.languages.csharp.review import api_surface as csharp_review_api_surface
from desloppify.languages.csharp.review import (
    module_patterns as csharp_review_module_patterns,
)

__all__ = [
    "CSHARP_HOLISTIC_REVIEW_DIMENSIONS",
    "CSHARP_LOW_VALUE_PATTERN",
    "CSHARP_MIGRATION_MIXED_EXTENSIONS",
    "CSHARP_MIGRATION_PATTERN_PAIRS",
    "CSHARP_REVIEW_GUIDANCE",
    "csharp_review_api_surface",
    "csharp_review_module_patterns",
]
