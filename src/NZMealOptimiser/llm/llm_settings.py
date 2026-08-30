"""LLM settings store.

Persists the user's choice of ingredient-generation and filter-generation
models in ``data/llm_settings.json`` (parallel to ``dishes.json`` and
``dish_filters.json``). Reads are tolerant of missing or malformed files —
both fall back to the built-in defaults so a fresh deploy behaves exactly
as before.

Atomic temp+replace writes match the pattern used by ``main._write_dishes_file``
so a crash mid-write cannot corrupt the file.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from NZMealOptimiser import DATA_DIR
from .llm_client import (
    GOOGLE_FILTER_MODEL_DEFAULT,
    LLMConfigError,
    PROVIDER_GOOGLE,
    PROVIDER_MISTRAL,
    PROVIDERS,
)

SETTINGS_PATH = DATA_DIR / "llm_settings.json"

DEFAULT_INGREDIENT_MODEL = {"provider": PROVIDER_MISTRAL, "model_id": "mistral-medium-3-5"}
DEFAULT_FILTER_MODEL = {"provider": PROVIDER_GOOGLE, "model_id": GOOGLE_FILTER_MODEL_DEFAULT}


def _default_settings() -> dict:
    return {
        "ingredient_model": dict(DEFAULT_INGREDIENT_MODEL),
        "filter_model": dict(DEFAULT_FILTER_MODEL),
    }


def _coerce_model(value: Any, fallback: dict) -> dict:
    """Coerce an arbitrary value into a valid model spec.

    Anything malformed (missing keys, unknown provider, non-string model_id)
    falls back to the supplied default. We never raise here — settings reads
    must not break generation, and the Settings page can detect defaults and
    show "using defaults" in the UI.
    """
    if not isinstance(value, dict):
        return dict(fallback)
    provider = value.get("provider")
    model_id = value.get("model_id")
    if not isinstance(provider, str) or provider not in PROVIDERS:
        return dict(fallback)
    if not isinstance(model_id, str) or not model_id.strip():
        return dict(fallback)
    return {"provider": provider, "model_id": model_id.strip()}


def load_llm_settings() -> dict:
    """Return the persisted LLM settings, falling back to defaults.

    Returns a fresh dict on every call so callers cannot mutate the on-disk
    value by accident.
    """
    defaults = _default_settings()
    if not SETTINGS_PATH.exists():
        return defaults
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    return {
        "ingredient_model": _coerce_model(data.get("ingredient_model"), DEFAULT_INGREDIENT_MODEL),
        "filter_model": _coerce_model(data.get("filter_model"), DEFAULT_FILTER_MODEL),
    }


def _validate_model(value: Any, *, field: str) -> dict:
    """Validate a model spec for a PUT write. Raises LLMConfigError on bad input."""
    if not isinstance(value, dict):
        raise LLMConfigError(f"{field} must be an object with provider+model_id")
    provider = value.get("provider")
    model_id = value.get("model_id")
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise LLMConfigError(
            f"{field}.provider must be one of {list(PROVIDERS)}, got {provider!r}"
        )
    if not isinstance(model_id, str) or not model_id.strip():
        raise LLMConfigError(f"{field}.model_id must be a non-empty string")
    return {"provider": provider, "model_id": model_id.strip()}


def save_llm_settings(payload: dict) -> dict:
    """Validate and persist the settings. Returns the canonical saved value.

    Raises:
        LLMConfigError: on invalid input.
        OSError: on filesystem failures (propagated from the atomic write).
    """
    if not isinstance(payload, dict):
        raise LLMConfigError("settings payload must be an object")
    ingredient = _validate_model(payload.get("ingredient_model"), field="ingredient_model")
    filter_model = _validate_model(payload.get("filter_model"), field="filter_model")
    canonical = {"ingredient_model": ingredient, "filter_model": filter_model}

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(canonical, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, SETTINGS_PATH)
    except OSError:
        # Clean up the temp file so it doesn't leak into the data dir.
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    return canonical


def get_active_models() -> dict:
    """Convenience wrapper used by the FastAPI handlers and generation.py."""
    return load_llm_settings()


__all__ = [
    "SETTINGS_PATH",
    "DEFAULT_INGREDIENT_MODEL",
    "DEFAULT_FILTER_MODEL",
    "load_llm_settings",
    "save_llm_settings",
    "get_active_models",
]
