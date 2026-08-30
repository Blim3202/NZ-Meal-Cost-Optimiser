"""Live model catalog + file cache.

Lists chat-capable models from Mistral (``GET /v1/models``) and Google
(``GET /v1beta/models``) and caches the result in
``data/llm_models_cache.json``. The cache is read on every Settings page
load; the user clicks a "Refresh model list" button to overwrite it
(``POST /llm/models/refresh`` in main.py). This keeps provider quota use
minimal — exactly one fetch per refresh click, never per page load.

Filtering:
  * Mistral: ``capabilities.completion_chat == true`` AND
    ``TYPE != "fine-tuned"`` AND ``archived == false`` AND
    ``deprecation is None`` AND ``billing_model_name == id``
    (drops ``-latest`` aliases, deprecated entries with a replacement
    model, and any other entry whose billing identity differs from its id).
  * Google: ``supportedGenerationMethods`` contains ``"generateContent"``
    (covers every model reachable through the OpenAI-compat chat surface).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from NZMealOptimiser import DATA_DIR
from .llm_client import GOOGLE_API_KEY_ENVS, MISTRAL_API_KEY_ENV, PROVIDER_GOOGLE, PROVIDER_MISTRAL

CACHE_PATH = DATA_DIR / "llm_models_cache.json"
MISTRAL_MODELS_URL = "https://api.mistral.ai/v1/models"
GOOGLE_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
REQUEST_TIMEOUT = 5.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_mistral_models(api_key: Optional[str] = None) -> dict:
    """Fetch + filter Mistral models. Returns ``{available, models, error}``."""
    api_key = api_key or os.getenv(MISTRAL_API_KEY_ENV)
    if not api_key:
        return {"available": False, "error": f"{MISTRAL_API_KEY_ENV} not set", "models": []}
    try:
        resp = requests.get(
            MISTRAL_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {"available": False, "error": f"network error: {exc}", "models": []}
    if resp.status_code != 200:
        snippet = (resp.text or "")[:200]
        return {
            "available": False,
            "error": f"HTTP {resp.status_code}: {snippet}",
            "models": [],
        }
    try:
        payload = resp.json()
    except ValueError as exc:
        return {"available": False, "error": f"invalid JSON: {exc}", "models": []}

    raw_models = payload.get("data", []) if isinstance(payload, dict) else []
    models: list[dict] = []
    for entry in raw_models:
        if not isinstance(entry, dict):
            continue
        caps = entry.get("capabilities") or {}
        if not isinstance(caps, dict) or not caps.get("completion_chat"):
            continue
        if entry.get("type") == "fine-tuned":
            continue
        if entry.get("archived"):
            continue
        if entry.get("deprecation") is not None:
            continue
        billing_name = entry.get("billing_model_name")
        if billing_name is not None and billing_name != entry.get("id"):
            continue
        models.append(
            {
                "id": entry.get("id", ""),
                "display_name": entry.get("id", ""),
                "max_context_length": entry.get("max_context_length"),
                "owned_by": entry.get("owned_by"),
            }
        )
    models.sort(key=lambda m: m["id"])
    return {"available": True, "models": models, "error": None}


def _resolve_google_api_key() -> Optional[str]:
    return os.getenv(GOOGLE_API_KEY_ENVS[0])


def list_google_models(api_key: Optional[str] = None) -> dict:
    """Fetch + filter Google Gemini models. Returns ``{available, models, error}``."""
    api_key = api_key or _resolve_google_api_key()
    if not api_key:
        return {"available": False, "error": f"{GOOGLE_API_KEY_ENVS[0]} not set", "models": []}
    try:
        resp = requests.get(
            GOOGLE_MODELS_URL,
            params={"key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {"available": False, "error": f"network error: {exc}", "models": []}
    if resp.status_code != 200:
        snippet = (resp.text or "")[:200]
        return {
            "available": False,
            "error": f"HTTP {resp.status_code}: {snippet}",
            "models": [],
        }
    try:
        payload = resp.json()
    except ValueError as exc:
        return {"available": False, "error": f"invalid JSON: {exc}", "models": []}

    raw_models = payload.get("models", []) if isinstance(payload, dict) else []
    models: list[dict] = []
    for entry in raw_models:
        if not isinstance(entry, dict):
            continue
        methods = entry.get("supportedGenerationMethods") or []
        if not isinstance(methods, list):
            continue
        required_methods = {"generateContent", "countTokens", "createCachedContent", "batchGenerateContent"}
        if not required_methods.issubset(methods):
            continue
        full_name = entry.get("name", "")
        if not full_name.startswith("models/"):
            continue
        model_id = full_name[len("models/"):]
        if not model_id:
            continue
        models.append(
            {
                "id": model_id,
                "display_name": entry.get("displayName", model_id),
                "input_token_limit": entry.get("inputTokenLimit"),
                "output_token_limit": entry.get("outputTokenLimit"),
                "supported_methods": methods,
            }
        )
    models.sort(key=lambda m: m["id"])
    return {"available": True, "models": models, "error": None}


def fetch_all_providers() -> dict:
    """Call both providers in series. Failures are isolated per provider."""
    return {
        PROVIDER_MISTRAL: list_mistral_models(),
        PROVIDER_GOOGLE: list_google_models(),
    }


def load_models_cache() -> Optional[dict]:
    """Return the cached catalog, or None if missing/malformed.

    A None return is the signal for the UI to show "Not fetched yet" and
    prompt the user to click Refresh.
    """
    if not CACHE_PATH.exists():
        return None
    try:
        with open(CACHE_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    providers = data.get("providers")
    if not isinstance(providers, dict):
        return None
    return data


def save_models_cache(providers: dict) -> dict:
    """Atomically write the catalog cache. Returns the canonical payload."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": _now_iso(),
        "providers": providers,
    }
    tmp = CACHE_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, CACHE_PATH)
    return payload


def ensure_cache_seeded() -> dict:
    """Make sure the cache file exists. If not, fetch and persist it.

    Returns the canonical cache payload (freshly fetched or read from disk).
    Used by the Settings page on first load and on every /llm/models hit
    when the file is missing.
    """
    existing = load_models_cache()
    if existing is not None:
        return existing
    return save_models_cache(fetch_all_providers())


__all__ = [
    "CACHE_PATH",
    "list_mistral_models",
    "list_google_models",
    "fetch_all_providers",
    "load_models_cache",
    "save_models_cache",
    "ensure_cache_seeded",
]
