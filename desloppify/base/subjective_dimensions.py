"""Shared subjective-dimension metadata used by scoring and review layers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache

from desloppify.base.subjective_dimensions_constants import (
    DISPLAY_NAMES,
)
from desloppify.base.subjective_dimensions_constants import (
    LEGACY_DISPLAY_NAMES as _LEGACY_DISPLAY_NAMES,
)
from desloppify.base.subjective_dimensions_constants import (
    LEGACY_RESET_ON_SCAN_DIMENSIONS as _LEGACY_RESET_ON_SCAN_DIMENSIONS,
)
from desloppify.base.subjective_dimensions_constants import (
    LEGACY_WEIGHT_BY_DIMENSION as _LEGACY_WEIGHT_BY_DIMENSION,
)
from desloppify.base.subjective_dimensions_constants import (
    normalize_dimension_name as _normalize_dimension_name,
)
from desloppify.base.subjective_dimensions_constants import (
    normalize_lang_name as _normalize_lang_name,
)
from desloppify.base.subjective_dimensions_constants import (
    title_display_name as _title_display_name,
)
from desloppify.base.subjective_dimensions_merge import (
    merge_dimension_meta as _merge_dimension_meta,
)
from desloppify.base.subjective_dimensions_providers import (
    PROVIDER_STATE as _PROVIDER_STATE,
)
from desloppify.base.subjective_dimensions_providers import (
    available_languages as _available_languages,
)
from desloppify.base.subjective_dimensions_providers import (
    default_available_languages as _default_available_languages,
)
from desloppify.base.subjective_dimensions_providers import (
    default_load_dimensions_payload as _default_load_dimensions_payload,
)
from desloppify.base.subjective_dimensions_providers import (
    default_load_dimensions_payload_for_lang as _default_load_dimensions_payload_for_lang,
)
from desloppify.base.subjective_dimensions_providers import (
    load_dimensions_payload as _load_dimensions_payload,
)
from desloppify.base.subjective_dimensions_providers import (
    load_dimensions_payload_for_lang as _load_dimensions_payload_for_lang,
)
from desloppify.base.text_utils import is_numeric

logger = logging.getLogger(__name__)


def _clear_subjective_dimension_caches() -> None:
    load_subjective_dimension_metadata.cache_clear()
    load_subjective_dimension_metadata_for_lang.cache_clear()


def configure_subjective_dimension_providers(
    *,
    available_languages_provider: Callable[[], list[str]] | None = None,
    load_dimensions_payload_provider: Callable[
        [], tuple[list[str], dict[str, dict[str, object]], str]
    ]
    | None = None,
    load_dimensions_payload_for_lang_provider: Callable[
        [str], tuple[list[str], dict[str, dict[str, object]], str]
    ]
    | None = None,
) -> None:
    """Configure metadata providers for subjective-dimension lookups."""
    state = _PROVIDER_STATE

    changed = False
    if (
        available_languages_provider is not None
        and available_languages_provider is not state.available_languages_provider
    ):
        state.available_languages_provider = available_languages_provider
        changed = True
    if (
        load_dimensions_payload_provider is not None
        and load_dimensions_payload_provider
        is not state.load_dimensions_payload_provider
    ):
        state.load_dimensions_payload_provider = load_dimensions_payload_provider
        changed = True
    if (
        load_dimensions_payload_for_lang_provider is not None
        and load_dimensions_payload_for_lang_provider
        is not state.load_dimensions_payload_for_lang_provider
    ):
        state.load_dimensions_payload_for_lang_provider = (
            load_dimensions_payload_for_lang_provider
        )
        changed = True

    if changed:
        _clear_subjective_dimension_caches()


def reset_subjective_dimension_providers() -> None:
    """Reset metadata providers to built-in defaults."""
    configure_subjective_dimension_providers(
        available_languages_provider=_default_available_languages,
        load_dimensions_payload_provider=_default_load_dimensions_payload,
        load_dimensions_payload_for_lang_provider=_default_load_dimensions_payload_for_lang,
    )


def _normalize_dimension_list(values: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            continue
        dim = _normalize_dimension_name(raw)
        if not dim or dim in normalized:
            continue
        normalized.append(dim)
    return tuple(normalized)


def default_dimension_keys() -> tuple[str, ...]:
    """Return canonical default subjective dimension keys."""
    try:
        dims, _, _ = _load_dimensions_payload()
    except (ImportError, ValueError, RuntimeError) as exc:
        logger.debug("Failed to load default subjective dimensions: %s", exc)
        return tuple(_LEGACY_DISPLAY_NAMES.keys())
    return _normalize_dimension_list(dims)


def default_dimension_keys_for_lang(lang_name: str | None) -> tuple[str, ...]:
    """Return default subjective dimension keys for a specific language."""
    normalized = _normalize_lang_name(lang_name)
    if normalized is None:
        return default_dimension_keys()
    try:
        dims, _, _ = _load_dimensions_payload_for_lang(normalized)
    except (ImportError, ValueError, RuntimeError) as exc:
        logger.debug(
            "Failed to load subjective dimensions for lang %s: %s",
            normalized,
            exc,
        )
        return default_dimension_keys()
    return _normalize_dimension_list(dims)


def _build_subjective_dimension_metadata(
    *,
    lang_name: str | None,
) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}

    try:
        shared_defaults, shared_prompts, _ = _load_dimensions_payload()
    except (ImportError, ValueError, RuntimeError) as exc:
        logger.debug("Failed to load shared subjective dimension payload: %s", exc)
        shared_defaults, shared_prompts = [], {}
    _merge_dimension_meta(out, dimensions=shared_defaults, prompts=shared_prompts)

    langs = (
        [lang_name]
        if isinstance(lang_name, str) and lang_name.strip()
        else _available_languages()
    )
    for name in langs:
        try:
            lang_defaults, lang_prompts, _ = _load_dimensions_payload_for_lang(name)
            _merge_dimension_meta(
                out,
                dimensions=lang_defaults,
                prompts=lang_prompts,
                override_existing=bool(lang_name),
            )
        except (ValueError, RuntimeError) as exc:
            logger.debug("Failed to load dimensions for lang %s: %s", name, exc)
            continue

    for dim, payload in out.items():
        payload.setdefault(
            "display_name",
            _LEGACY_DISPLAY_NAMES.get(dim, _title_display_name(dim)),
        )
        payload.setdefault("weight", _LEGACY_WEIGHT_BY_DIMENSION.get(dim, 1.0))
        payload.setdefault("enabled_by_default", False)
        if dim in _LEGACY_DISPLAY_NAMES:
            payload.setdefault("reset_on_scan", dim in _LEGACY_RESET_ON_SCAN_DIMENSIONS)
        else:
            payload.setdefault("reset_on_scan", True)

    # Preserve legacy dimensions even if a payload temporarily drops one.
    for dim, display in _LEGACY_DISPLAY_NAMES.items():
        payload = out.setdefault(dim, {})
        payload.setdefault("display_name", display)
        payload.setdefault("weight", _LEGACY_WEIGHT_BY_DIMENSION.get(dim, 1.0))
        payload.setdefault("enabled_by_default", True)
        payload.setdefault("reset_on_scan", dim in _LEGACY_RESET_ON_SCAN_DIMENSIONS)

    return out


@lru_cache(maxsize=1)
def load_subjective_dimension_metadata() -> dict[str, dict[str, object]]:
    """Return merged metadata across all known dimensions/languages."""
    return _build_subjective_dimension_metadata(lang_name=None)


@lru_cache(maxsize=16)
def load_subjective_dimension_metadata_for_lang(
    lang_name: str | None,
) -> dict[str, dict[str, object]]:
    """Return merged metadata for one language (with language overrides)."""
    normalized = _normalize_lang_name(lang_name)
    return _build_subjective_dimension_metadata(lang_name=normalized)


def _metadata_registry(lang_name: str | None) -> dict[str, dict[str, object]]:
    normalized = _normalize_lang_name(lang_name)
    if normalized is None:
        return load_subjective_dimension_metadata()
    return load_subjective_dimension_metadata_for_lang(normalized)


def get_dimension_metadata(
    dimension_name: str, *, lang_name: str | None = None
) -> dict[str, object]:
    """Return metadata for one dimension key (with sane defaults)."""
    dim = _normalize_dimension_name(dimension_name)
    all_meta = _metadata_registry(lang_name)
    payload = dict(all_meta.get(dim, {}))

    payload.setdefault("display_name", _title_display_name(dim))
    payload.setdefault("weight", 1.0)
    payload.setdefault("enabled_by_default", False)
    payload.setdefault("reset_on_scan", True)
    return payload


def dimension_display_name(dimension_name: str, *, lang_name: str | None = None) -> str:
    meta = get_dimension_metadata(dimension_name, lang_name=lang_name)
    return str(meta.get("display_name", _title_display_name(dimension_name)))


def dimension_weight(dimension_name: str, *, lang_name: str | None = None) -> float:
    meta = get_dimension_metadata(dimension_name, lang_name=lang_name)
    raw = meta.get("weight", 1.0)
    if is_numeric(raw):
        return max(0.0, float(raw))
    return 1.0


def default_display_names_map(*, lang_name: str | None = None) -> dict[str, str]:
    """Display-name map for default subjective dimensions."""
    out: dict[str, str] = {}
    for dim, payload in _metadata_registry(lang_name).items():
        if not bool(payload.get("enabled_by_default", False)):
            continue
        out[dim] = str(payload.get("display_name", _title_display_name(dim)))
    return out


def resettable_default_dimensions(*, lang_name: str | None = None) -> tuple[str, ...]:
    """Default subjective dimensions that should be reset by scan reset."""
    out = []
    for dim, payload in _metadata_registry(lang_name).items():
        if not bool(payload.get("enabled_by_default", False)):
            continue
        if not bool(payload.get("reset_on_scan", True)):
            continue
        out.append(dim)
    return tuple(sorted(set(out)))


__all__ = [
    "DISPLAY_NAMES",
    "configure_subjective_dimension_providers",
    "default_dimension_keys",
    "default_dimension_keys_for_lang",
    "default_display_names_map",
    "dimension_display_name",
    "dimension_weight",
    "get_dimension_metadata",
    "load_subjective_dimension_metadata",
    "load_subjective_dimension_metadata_for_lang",
    "reset_subjective_dimension_providers",
    "resettable_default_dimensions",
]
