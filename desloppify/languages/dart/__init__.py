"""Dart/Flutter language configuration for Desloppify."""

from __future__ import annotations

from desloppify.base.discovery.paths import get_area
from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.engine.hook_registry import register_lang_hooks
from desloppify.languages import register_lang
from desloppify.languages._framework.base.phase_builders import (
    detector_phase_security,
    detector_phase_signature,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from desloppify.languages._framework.base.types import DetectorPhase, LangConfig
from desloppify.languages._framework.treesitter.phases import all_treesitter_phases
from desloppify.languages.dart import test_coverage as dart_test_coverage_hooks
from desloppify.languages.dart.commands import get_detect_commands
from desloppify.languages.dart.detectors.deps import (
    build_dep_graph as build_dart_dep_graph,
)
from desloppify.languages.dart.extractors import (
    DART_FILE_EXCLUSIONS,
    extract_functions,
    find_dart_files,
)
from desloppify.languages.dart.phases import phase_coupling, phase_structural
from desloppify.languages.dart.review import (
    HOLISTIC_REVIEW_DIMENSIONS,
    LOW_VALUE_PATTERN,
    MIGRATION_MIXED_EXTENSIONS,
    MIGRATION_PATTERN_PAIRS,
    REVIEW_GUIDANCE,
    api_surface,
    module_patterns,
)

DART_ENTRY_PATTERNS = [
    "/main.dart",
    "/bin/",
    "/tool/",
    "/web/",
    "/test/",
    "/integration_test/",
]

DART_ZONE_RULES = [
    ZoneRule(Zone.TEST, ["/test/", "/integration_test/", "_test.dart"]),
    ZoneRule(
        Zone.CONFIG,
        ["/pubspec.yaml", "/analysis_options.yaml", "/l10n.yaml", "/build.yaml"],
    ),
    ZoneRule(
        Zone.GENERATED,
        [".g.dart", ".freezed.dart", ".mocks.dart", "/.dart_tool/", "/build/"],
    ),
] + COMMON_ZONE_RULES


register_lang_hooks("dart", test_coverage=dart_test_coverage_hooks)


@register_lang("dart")
class DartConfig(LangConfig):
    """Dart/Flutter language configuration."""

    def __init__(self):
        super().__init__(
            name="dart",
            extensions=[".dart"],
            exclusions=DART_FILE_EXCLUSIONS,
            default_src="lib",
            build_dep_graph=build_dart_dep_graph,
            entry_patterns=DART_ENTRY_PATTERNS,
            barrel_names={"index.dart"},
            phases=[
                DetectorPhase("Structural analysis", phase_structural),
                DetectorPhase("Coupling + cycles + orphaned", phase_coupling),
                *all_treesitter_phases("dart"),
                detector_phase_signature(),
                detector_phase_test_coverage(),
                detector_phase_security(),
                *shared_subjective_duplicates_tail(),
            ],
            fixers={},
            get_area=get_area,
            detect_commands=get_detect_commands(),
            boundaries=[],
            typecheck_cmd="dart analyze",
            file_finder=find_dart_files,
            large_threshold=500,
            complexity_threshold=16,
            default_scan_profile="full",
            detect_markers=["pubspec.yaml"],
            external_test_dirs=["test", "integration_test"],
            test_file_extensions=[".dart"],
            review_module_patterns_fn=module_patterns,
            review_api_surface_fn=api_surface,
            review_guidance=REVIEW_GUIDANCE,
            review_low_value_pattern=LOW_VALUE_PATTERN,
            holistic_review_dimensions=HOLISTIC_REVIEW_DIMENSIONS,
            migration_pattern_pairs=MIGRATION_PATTERN_PAIRS,
            migration_mixed_extensions=MIGRATION_MIXED_EXTENSIONS,
            extract_functions=extract_functions,
            zone_rules=DART_ZONE_RULES,
        )

__all__ = [
    "get_area",
    "COMMON_ZONE_RULES",
    "Zone",
    "ZoneRule",
    "register_lang_hooks",
    "register_lang",
    "detector_phase_security",
    "detector_phase_signature",
    "detector_phase_test_coverage",
    "shared_subjective_duplicates_tail",
    "DetectorPhase",
    "LangConfig",
    "all_treesitter_phases",
    "dart_test_coverage_hooks",
    "get_detect_commands",
    "build_dart_dep_graph",
    "DART_FILE_EXCLUSIONS",
    "extract_functions",
    "find_dart_files",
    "phase_coupling",
    "phase_structural",
    "HOLISTIC_REVIEW_DIMENSIONS",
    "LOW_VALUE_PATTERN",
    "MIGRATION_MIXED_EXTENSIONS",
    "MIGRATION_PATTERN_PAIRS",
    "REVIEW_GUIDANCE",
    "api_surface",
    "module_patterns",
    "DART_ENTRY_PATTERNS",
    "DART_ZONE_RULES",
    "DartConfig",
]
