"""Tree-sitter specs for compiled language families."""

from __future__ import annotations

from ..imports.resolvers_backend import resolve_dart_import
from ..types import TreeSitterLangSpec

DART_SPEC = TreeSitterLangSpec(
    grammar="dart",
    function_query="""
        (function_signature
            name: (identifier) @name) @func
        (method_signature
            (function_signature
                name: (identifier) @name)) @func
    """,
    comment_node_types=frozenset({"comment", "documentation_comment"}),
    import_query="""
        (import_or_export
            (library_import
                (import_specification
                    (configurable_uri
                        (uri
                            (string_literal) @path))))) @import
    """,
    resolve_import=resolve_dart_import,
    class_query="""
        (class_definition
            name: (identifier) @name
            body: (class_body) @body) @class
    """,
    log_patterns=(
        r"^\s*(?:print\(|debugPrint|log\.)",
    ),
)

__all__ = [
    "DART_SPEC",
]
