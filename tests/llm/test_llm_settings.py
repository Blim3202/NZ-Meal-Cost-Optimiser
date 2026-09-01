"""Tests for NZMealOptimiser.llm.llm_settings — the LLM model settings store.

Validates the read/write/validate pipeline for ``data/llm_settings.json``.
Settings must tolerate a missing or malformed file (fresh deploys fall back to
built-in defaults) and must reject obviously invalid input on PUT.
"""
import json
from pathlib import Path

import pytest

from NZMealOptimiser import DATA_DIR
from NZMealOptimiser.llm import llm_settings
from NZMealOptimiser.llm.llm_client import LLMConfigError


@pytest.fixture
def isolated_settings_path(tmp_path: Path, monkeypatch):
    """Point the settings store at a temp file and restore DATA_DIR on teardown.

    llm_settings resolves SETTINGS_PATH at import time, so we monkeypatch
    the module attribute directly rather than touching DATA_DIR.
    """
    target = tmp_path / "llm_settings.json"
    monkeypatch.setattr(llm_settings, "SETTINGS_PATH", target)
    return target


def test_load_returns_defaults_when_file_missing(isolated_settings_path):
    assert not isolated_settings_path.exists()
    loaded = llm_settings.load_llm_settings()
    assert loaded == {
        "ingredient_model": dict(llm_settings.DEFAULT_INGREDIENT_MODEL),
        "filter_model": dict(llm_settings.DEFAULT_FILTER_MODEL),
        "exclude_non_food": True,
    }


def test_save_writes_canonical_payload(isolated_settings_path):
    payload = {
        "ingredient_model": {"provider": "google", "model_id": "gemini-2.5-pro"},
        "filter_model": {"provider": "mistral", "model_id": "mistral-small-latest"},
        "exclude_non_food": True,
    }
    saved = llm_settings.save_llm_settings(payload)
    assert saved == payload
    on_disk = json.loads(isolated_settings_path.read_text(encoding="utf-8"))
    assert on_disk == payload


def test_save_rejects_unknown_provider(isolated_settings_path):
    bad = {
        "ingredient_model": {"provider": "openai", "model_id": "gpt-4o"},
        "filter_model": dict(llm_settings.DEFAULT_FILTER_MODEL),
    }
    with pytest.raises(LLMConfigError, match="ingredient_model.provider"):
        llm_settings.save_llm_settings(bad)
    assert not isolated_settings_path.exists()


def test_save_rejects_blank_model_id(isolated_settings_path):
    bad = {
        "ingredient_model": dict(llm_settings.DEFAULT_INGREDIENT_MODEL),
        "filter_model": {"provider": "google", "model_id": "   "},
    }
    with pytest.raises(LLMConfigError, match="filter_model.model_id"):
        llm_settings.save_llm_settings(bad)


def test_save_rejects_non_dict_payload(isolated_settings_path):
    with pytest.raises(LLMConfigError):
        llm_settings.save_llm_settings(["not", "a", "dict"])


def test_load_recovers_from_malformed_file(isolated_settings_path):
    isolated_settings_path.write_text("{not valid json", encoding="utf-8")
    loaded = llm_settings.load_llm_settings()
    assert loaded["ingredient_model"] == dict(llm_settings.DEFAULT_INGREDIENT_MODEL)
    assert loaded["filter_model"] == dict(llm_settings.DEFAULT_FILTER_MODEL)


def test_load_recovers_from_partial_file(isolated_settings_path):
    isolated_settings_path.write_text(json.dumps({"ingredient_model": {"provider": "google", "model_id": "x"}}), encoding="utf-8")
    loaded = llm_settings.load_llm_settings()
    # ingredient_model kept, filter_model reset to default
    assert loaded["ingredient_model"] == {"provider": "google", "model_id": "x"}
    assert loaded["filter_model"] == dict(llm_settings.DEFAULT_FILTER_MODEL)


def test_load_coerces_unknown_provider_to_default(isolated_settings_path):
    isolated_settings_path.write_text(
        json.dumps({"ingredient_model": {"provider": "openai", "model_id": "gpt-4o"},
                    "filter_model": {"provider": "google", "model_id": "  "}}),
        encoding="utf-8",
    )
    loaded = llm_settings.load_llm_settings()
    assert loaded["ingredient_model"] == dict(llm_settings.DEFAULT_INGREDIENT_MODEL)
    assert loaded["filter_model"] == dict(llm_settings.DEFAULT_FILTER_MODEL)


def test_save_is_atomic(isolated_settings_path):
    """A successful save should leave no .tmp file behind."""
    llm_settings.save_llm_settings({
        "ingredient_model": dict(llm_settings.DEFAULT_INGREDIENT_MODEL),
        "filter_model": dict(llm_settings.DEFAULT_FILTER_MODEL),
    })
    assert isolated_settings_path.exists()
    assert not isolated_settings_path.with_suffix(".json.tmp").exists()


def test_save_recovers_from_replace_failure(monkeypatch, isolated_settings_path):
    """If os.replace fails mid-save, the .tmp file is cleaned up and the
    pre-existing settings file is left untouched. This is the recovery
    path that justifies the temp+replace pattern in save_llm_settings."""
    import os as os_mod

    payload = {
        "ingredient_model": dict(llm_settings.DEFAULT_INGREDIENT_MODEL),
        "filter_model": dict(llm_settings.DEFAULT_FILTER_MODEL),
    }
    llm_settings.save_llm_settings(payload)
    pre_existing = isolated_settings_path.read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os_mod, "replace", boom)
    with pytest.raises(OSError):
        llm_settings.save_llm_settings({
            "ingredient_model": {"provider": "google", "model_id": "x"},
            "filter_model": dict(llm_settings.DEFAULT_FILTER_MODEL),
        })
    # pre-existing file untouched
    assert isolated_settings_path.read_text(encoding="utf-8") == pre_existing
    # no .tmp file leaked
    assert not isolated_settings_path.with_suffix(".json.tmp").exists()


def test_get_active_models_matches_load(isolated_settings_path):
    assert llm_settings.get_active_models() == llm_settings.load_llm_settings()
