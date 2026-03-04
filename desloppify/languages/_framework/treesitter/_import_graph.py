"""Shared import graph construction utilities for tree-sitter backends."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._cache import _PARSE_CACHE
from ._extractors import _get_parser, _make_query, _run_query, _unwrap_node

if TYPE_CHECKING:
    from desloppify.languages._framework.treesitter import TreeSitterLangSpec


def ts_build_dep_graph(
    path: Path,
    spec: TreeSitterLangSpec,
    file_list: list[str],
) -> dict[str, dict[str, Any]]:
    """Build a dependency graph by parsing imports with tree-sitter.

    Returns the same shape as Python/TS dep graphs:
    {file: {"imports": set[str], "importers": set[str], "import_count": int, "importer_count": int}}
    """
    if not spec.import_query or not spec.resolve_import:
        return {}

    parser, language = _get_parser(spec.grammar)
    query = _make_query(language, spec.import_query)

    scan_path = str(path.resolve())
    file_set = set(file_list)
    graph: dict[str, dict[str, Any]] = {}

    # Initialize all files in the graph.
    for f in file_list:
        graph[f] = {"imports": set(), "importers": set()}

    for filepath in file_list:
        cached = _PARSE_CACHE.get_or_parse(filepath, parser, spec.grammar)
        if cached is None:
            continue
        _source, tree = cached
        matches = _run_query(query, tree.root_node)

        for _pattern_idx, captures in matches:
            path_node = _unwrap_node(captures.get("path"))
            if not path_node:
                continue

            raw_text = path_node.text
            import_text = (
                raw_text.decode("utf-8", errors="replace")
                if isinstance(raw_text, bytes)
                else str(raw_text)
            )

            # Strip surrounding quotes if present.
            import_text = import_text.strip("\"'`")

            resolved = spec.resolve_import(import_text, filepath, scan_path)
            if resolved is None:
                continue

            # Normalize to absolute path.
            if not os.path.isabs(resolved):
                resolved = os.path.normpath(os.path.join(scan_path, resolved))

            # Only track edges within the scanned file set.
            if resolved not in file_set:
                continue

            graph[filepath]["imports"].add(resolved)
            if resolved in graph:
                graph[resolved]["importers"].add(filepath)

    # Finalize: add counts.
    for data in graph.values():
        data["import_count"] = len(data["imports"])
        data["importer_count"] = len(data["importers"])

    return graph


def make_ts_dep_builder(spec: TreeSitterLangSpec, file_finder):
    """Create a dep graph builder bound to a TreeSitterLangSpec + file finder.

    Returns a callable with signature (path: Path) -> dict,
    matching the contract expected by LangConfig.build_dep_graph.
    """

    def build(path: Path) -> dict[str, dict[str, Any]]:
        file_list = file_finder(path)
        return ts_build_dep_graph(path, spec, file_list)

    return build


__all__ = ["make_ts_dep_builder", "ts_build_dep_graph"]
