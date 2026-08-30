"""Tests for NZMealOptimiser.llm.llm_models — live catalog + file cache.

Validates Mistral + Google filtering rules, the cache read/write round-trip,
and that each provider's call site is isolated (a Mistral failure must not
poison the Google result).
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from NZMealOptimiser import DATA_DIR
from NZMealOptimiser.llm import llm_models
from NZMealOptimiser.llm.llm_client import MISTRAL_API_KEY_ENV


@pytest.fixture
def isolated_cache_path(tmp_path: Path, monkeypatch):
    target = tmp_path / "llm_models_cache.json"
    monkeypatch.setattr(llm_models, "CACHE_PATH", target)
    return target


# ── Mistral list ──────────────────────────────────────────────────────────────

def test_list_mistral_models_filters_to_chat_capable():
    payload = {
        "data": [
            {"id": "mistral-medium-latest",
             "capabilities": {"completion_chat": True}, "type": "base", "archived": False,
             "max_context_length": 32768},
            {"id": "mistral-embed",
             "capabilities": {"completion_chat": False}, "type": "base", "archived": False,
             "max_context_length": 8192},
            {"id": "ft:my-fine-tune",
             "capabilities": {"completion_chat": True}, "type": "fine-tuned", "archived": False,
             "max_context_length": 4096},
            {"id": "mistral-old",
             "capabilities": {"completion_chat": True}, "type": "base", "archived": True,
             "max_context_length": 4096},
        ]
    }
    fake_response = type("Resp", (), {"status_code": 200, "json": staticmethod(lambda: payload), "text": ""})()
    with patch.object(requests, "get", return_value=fake_response):
        result = llm_models.list_mistral_models("key")

    assert result["available"] is True
    assert result["error"] is None
    ids = [m["id"] for m in result["models"]]
    assert ids == ["mistral-medium-latest"]
    assert result["models"][0]["max_context_length"] == 32768


def test_list_mistral_models_missing_key_returns_error(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    result = llm_models.list_mistral_models()
    assert result["available"] is False
    assert "MISTRAL_API_KEY" in result["error"]
    assert result["models"] == []


def test_list_mistral_models_http_error_returns_error():
    fake_response = type("Resp", (), {"status_code": 401, "text": "unauthorized"})()
    with patch.object(requests, "get", return_value=fake_response):
        result = llm_models.list_mistral_models("key")
    assert result["available"] is False
    assert "HTTP 401" in result["error"]


# ── Google list ───────────────────────────────────────────────────────────────

def test_list_google_models_filters_to_generate_content():
    payload = {
        "models": [
            {"name": "models/gemini-2.5-pro",
             "supportedGenerationMethods": ["generateContent", "countTokens"],
             "inputTokenLimit": 1000000, "outputTokenLimit": 65536,
             "displayName": "Gemini 2.5 Pro"},
            {"name": "models/embedding-001",
             "supportedGenerationMethods": ["embedContent"],
             "inputTokenLimit": 2048, "outputTokenLimit": 0,
             "displayName": "Embedding"},
            {"name": "gemini-flash",
             "supportedGenerationMethods": ["generateContent"],
             "inputTokenLimit": 1000000, "outputTokenLimit": 8192,
             "displayName": "Flash"},
            {"name": "models/gemini-2.5-flash",
             "supportedGenerationMethods": ["generateContent"],
             "inputTokenLimit": 1000000, "outputTokenLimit": 8192,
             "displayName": "Gemini 2.5 Flash"},
        ]
    }
    fake_response = type("Resp", (), {"status_code": 200, "json": staticmethod(lambda: payload), "text": ""})()
    with patch.object(requests, "get", return_value=fake_response):
        result = llm_models.list_google_models("key")

    assert result["available"] is True
    ids = [m["id"] for m in result["models"]]
    # embedding filtered (no generateContent), unprefixed "gemini-flash" filtered,
    # gemini-2.5-pro + gemini-2.5-flash kept
    assert ids == ["gemini-2.5-flash", "gemini-2.5-pro"]
    assert result["models"][0]["display_name"] == "Gemini 2.5 Flash"


def test_list_google_models_network_error_returns_error():
    def boom(*args, **kwargs):
        raise requests.ConnectionError("dns fail")
    with patch.object(requests, "get", side_effect=boom):
        result = llm_models.list_google_models("key")
    assert result["available"] is False
    assert "network error" in result["error"]


# ── Cache ─────────────────────────────────────────────────────────────────────

def test_load_models_cache_returns_none_when_missing(isolated_cache_path):
    assert llm_models.load_models_cache() is None


def test_save_and_load_round_trip(isolated_cache_path):
    providers = {
        "mistral": {"available": True, "models": [{"id": "m", "display_name": "m"}], "error": None},
        "google": {"available": True, "models": [{"id": "g", "display_name": "g"}], "error": None},
    }
    saved = llm_models.save_models_cache(providers)
    assert saved["providers"] == providers
    assert "fetched_at" in saved

    loaded = llm_models.load_models_cache()
    assert loaded == saved


def test_load_recovers_from_malformed_cache(isolated_cache_path):
    isolated_cache_path.write_text("not json", encoding="utf-8")
    assert llm_models.load_models_cache() is None


def test_ensure_cache_seeded_writes_when_missing(isolated_cache_path):
    providers = {
        "mistral": {"available": True, "models": [], "error": None},
        "google": {"available": False, "models": [], "error": "no key"},
    }
    with patch.object(llm_models, "fetch_all_providers", return_value=providers):
        payload = llm_models.ensure_cache_seeded()
    assert payload["providers"] == providers
    assert isolated_cache_path.exists()


def test_ensure_cache_seeded_returns_existing_without_calling_fetch(isolated_cache_path):
    existing = {
        "fetched_at": "2026-01-01T00:00:00Z",
        "providers": {"mistral": {"available": True, "models": [], "error": None},
                      "google": {"available": True, "models": [], "error": None}},
    }
    isolated_cache_path.write_text(json.dumps(existing), encoding="utf-8")
    with patch.object(llm_models, "fetch_all_providers") as fetch:
        loaded = llm_models.ensure_cache_seeded()
    assert loaded == existing
    fetch.assert_not_called()


def test_fetch_all_providers_isolates_failures(monkeypatch):
    """Mistral raising must not prevent Google from being queried."""
    monkeypatch.setenv(MISTRAL_API_KEY_ENV, "k")
    with patch.object(llm_models, "list_mistral_models", side_effect=RuntimeError("mistral down")), \
         patch.object(llm_models, "list_google_models", return_value={"available": True, "models": [{"id": "g"}], "error": None}) as google_mock:
        result = llm_models.fetch_all_providers()
    assert google_mock.called, "Google must still be queried when Mistral raises"
    assert result["google"]["available"] is True
    assert result["google"]["models"] == [{"id": "g"}]
