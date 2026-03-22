"""Firebase antipattern detector for Dart/Flutter projects."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

from desloppify.base.discovery.file_paths import rel
from desloppify.engine.policy.zones import FileZoneMap, Zone

# ── Patterns ─────────────────────────────────────────────────────

# Direct Firestore/RTDB access outside a repository/service class
_DIRECT_ACCESS_RE = re.compile(
    r"FirebaseFirestore\.instance|FirebaseDatabase\.instance|"
    r"FirebaseAuth\.instance|FirebaseStorage\.instance",
)

# Hardcoded collection/document names
_HARDCODED_COLLECTION_RE = re.compile(
    r"""\.collection\(\s*['"]([a-zA-Z0-9_/-]+)['"]\s*\)"""
)

# Missing error handling on Firebase calls
_UNHANDLED_FIREBASE_RE = re.compile(
    r"(?:await\s+)?(?:FirebaseFirestore|FirebaseDatabase|FirebaseAuth|FirebaseStorage)"
    r"\.instance\b",
)

# Firestore rules bypass — using .get() without security context awareness
_RAW_GET_RE = re.compile(
    r"\.doc\([^)]*\)\.get\(\)|\.collection\([^)]*\)\.get\(\)",
)


def detect_firebase_patterns(
    files: list[str],
    zone_map: FileZoneMap | None,
) -> tuple[list[dict], int]:
    """Scan Dart files for Firebase antipatterns.

    Returns (entries, files_scanned).
    """
    entries: list[dict] = []
    scanned = 0

    for filepath in files:
        if zone_map is not None:
            zone = zone_map.get(filepath)
            if zone in (Zone.TEST, Zone.CONFIG, Zone.GENERATED, Zone.VENDOR):
                continue

        if not filepath.endswith(".dart"):
            continue

        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError as exc:
            logger.debug("Failed to read %s: %s", filepath, exc)
            continue

        scanned += 1
        lines = content.splitlines()
        rpath = rel(filepath)

        # Check if file is a repository/service class (skip direct access check)
        is_repository = bool(
            re.search(r"class\s+\w*(?:Repository|Service|DataSource)\b", content)
        )

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("///"):
                continue

            # 1. Direct Firebase access outside repository/service
            if not is_repository and _DIRECT_ACCESS_RE.search(line):
                entries.append({
                    "file": filepath,
                    "name": f"firebase_direct_access::{rpath}::{i}",
                    "tier": 3,
                    "confidence": "medium",
                    "line": i,
                    "summary": (
                        f"Direct Firebase access at line {i} — "
                        "wrap in a repository or service class"
                    ),
                    "detail": {
                        "kind": "firebase_direct_access",
                        "content": stripped[:200],
                        "remediation": (
                            "Move Firebase calls behind a repository or service "
                            "abstraction to improve testability and separation of concerns."
                        ),
                    },
                })

            # 2. Hardcoded collection names
            match = _HARDCODED_COLLECTION_RE.search(line)
            if match:
                collection = match.group(1)
                entries.append({
                    "file": filepath,
                    "name": f"firebase_hardcoded_collection::{rpath}::{i}",
                    "tier": 3,
                    "confidence": "low",
                    "line": i,
                    "summary": (
                        f"Hardcoded collection name '{collection}' at line {i} — "
                        "extract to a constant"
                    ),
                    "detail": {
                        "kind": "firebase_hardcoded_collection",
                        "collection": collection,
                        "content": stripped[:200],
                        "remediation": (
                            "Define collection and document paths as named constants "
                            "to avoid typos and make refactoring easier."
                        ),
                    },
                })

        # 3. File-level: Firebase calls without try/catch
        _check_unhandled_errors(filepath, rpath, content, lines, entries)

    return entries, scanned


def _check_unhandled_errors(
    filepath: str,
    rpath: str,
    content: str,
    lines: list[str],
    entries: list[dict],
) -> None:
    """Flag Firebase calls that are not wrapped in try/catch."""
    in_try_block = False
    brace_depth = 0
    try_depth = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        if stripped.startswith("try") and "{" in stripped:
            in_try_block = True
            try_depth = brace_depth

        brace_depth += line.count("{") - line.count("}")

        if in_try_block and brace_depth <= try_depth:
            in_try_block = False

        if not in_try_block and _UNHANDLED_FIREBASE_RE.search(line):
            if "await" in line:
                entries.append({
                    "file": filepath,
                    "name": f"firebase_unhandled_error::{rpath}::{i}",
                    "tier": 3,
                    "confidence": "low",
                    "line": i,
                    "summary": (
                        f"Firebase call at line {i} may lack error handling — "
                        "wrap in try/catch"
                    ),
                    "detail": {
                        "kind": "firebase_unhandled_error",
                        "content": stripped[:200],
                        "remediation": (
                            "Wrap Firebase operations in try/catch to handle "
                            "network errors, permission denials, and quota limits."
                        ),
                    },
                })
