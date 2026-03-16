"""Tree-sitter specs for scripting/dynamic language families."""

from __future__ import annotations

from ..imports.resolvers_scripts import resolve_js_import
from ..types import TreeSitterLangSpec

TYPESCRIPT_SPEC = TreeSitterLangSpec(
    grammar="tsx",
    function_query="""
        (function_declaration
            name: (identifier) @name
            body: (statement_block) @body) @func
        (method_definition
            name: (property_identifier) @name
            body: (statement_block) @body) @func
        (variable_declarator
            name: (identifier) @name
            value: (arrow_function
                body: (statement_block) @body)) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""
        (import_statement
            source: (string (string_fragment) @path)) @import
    """,
    resolve_import=resolve_js_import,
    class_query="""
        (class_declaration
            name: (type_identifier) @name
            body: (class_body) @body) @class
    """,
    log_patterns=(r"^\s*console\.",),
)
