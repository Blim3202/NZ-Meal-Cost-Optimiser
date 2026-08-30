"""Tests for the provider-parameter constructor on LLMClient.

Covers the new explicit (provider, model_id) form and the legacy model_alias
shim, plus a check that the retry/JSON-parse loop is honoured by both
providers.
"""
from unittest.mock import MagicMock, patch

import pytest

from NZMealOptimiser.llm.llm_client import (
    LLMClient,
    LLMConfigError,
    LLMGenerationError,
    PROVIDER_GOOGLE,
    PROVIDER_MISTRAL,
)


# ── Provider validation ──────────────────────────────────────────────────────

def test_unknown_provider_raises_config_error(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    with pytest.raises(LLMConfigError, match="Unknown provider"):
        LLMClient(provider="openai", model_id="gpt-4o")


def test_missing_both_provider_and_alias_raises_config_error(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    with pytest.raises(LLMConfigError, match="requires either model_alias"):
        LLMClient()


def test_missing_mistral_key_raises_config_error(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(LLMConfigError, match="MISTRAL_API_KEY"):
        LLMClient(provider="mistral", model_id="mistral-medium-latest")


def test_missing_google_key_raises_config_error(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(LLMConfigError, match="GOOGLE_API_KEY"):
        LLMClient(provider="google", model_id="gemini-2.5-pro")


# ── Mistral path ─────────────────────────────────────────────────────────────

def test_mistral_provider_calls_mistral_sdk(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    fake_mistral = MagicMock()
    fake_mistral.chat.complete.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"dish_name": "x", "portion": 2, "ingredients": []}'))],
    )
    with patch("NZMealOptimiser.llm.llm_client.Mistral", return_value=fake_mistral):
        client = LLMClient(provider="mistral", model_id="mistral-medium-latest")
        out = client.generate_ingredients("x", portion=2)

    assert out["dish_name"] == "x"
    assert out["portion"] == 2
    assert out["ingredients"] == []
    assert fake_mistral.chat.complete.call_args.kwargs["model"] == "mistral-medium-latest"
    assert fake_mistral.chat.complete.call_args.kwargs["response_format"] == {"type": "json_object"}


def test_legacy_model_alias_still_works(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    fake_mistral = MagicMock()
    fake_mistral.chat.complete.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"ingredients": []}'))],
    )
    with patch("NZMealOptimiser.llm.llm_client.Mistral", return_value=fake_mistral):
        client = LLMClient(model_alias="medium")
    assert client.provider == "mistral"
    assert client.model_id == "mistral-medium-latest"


def test_legacy_unknown_alias_raises(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    with pytest.raises(LLMConfigError, match="Unknown model_alias"):
        LLMClient(model_alias="ultra")


# ── Google path ──────────────────────────────────────────────────────────────

def test_google_provider_calls_openai_compat(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    fake_openai = MagicMock()
    fake_openai.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"ingredients": []}'))],
    )
    with patch("NZMealOptimiser.llm.llm_client.OpenAI", return_value=fake_openai):
        client = LLMClient(provider="google", model_id="gemini-2.5-pro")
        out = client.generate_ingredients("x")

    assert out == {"ingredients": []}
    call = fake_openai.chat.completions.create.call_args.kwargs
    assert call["model"] == "gemini-2.5-pro"
    assert call["response_format"] == {"type": "json_object"}


def test_google_provider_passes_temperature_and_max_tokens(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    fake_openai = MagicMock()
    fake_openai.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"ingredients": []}'))],
    )
    with patch("NZMealOptimiser.llm.llm_client.OpenAI", return_value=fake_openai):
        client = LLMClient(provider="google", model_id="gemini-2.5-pro", temperature=0.1, max_tokens=4096)
        client.generate_ingredients("x")

    call = fake_openai.chat.completions.create.call_args.kwargs
    assert call["temperature"] == 0.1
    assert call["max_tokens"] == 4096


# ── Retry loop ───────────────────────────────────────────────────────────────

def test_retry_on_json_parse_failure_then_succeeds(monkeypatch):
    """The 3-attempt loop should keep calling the model until JSON parses."""
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    fake_mistral = MagicMock()
    fake_mistral.chat.complete.side_effect = [
        MagicMock(choices=[MagicMock(message=MagicMock(content="not json"))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content="not json either"))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content='{"ingredients": []}'))]),
    ]
    with patch("NZMealOptimiser.llm.llm_client.Mistral", return_value=fake_mistral), \
         patch("NZMealOptimiser.llm.llm_client.time.sleep"):
        client = LLMClient(provider="mistral", model_id="mistral-medium-latest")
        out = client.generate_ingredients("x")

    assert out == {"ingredients": []}
    assert fake_mistral.chat.complete.call_count == 3


def test_retry_exhausts_and_raises(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    fake_mistral = MagicMock()
    fake_mistral.chat.complete.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="never json"))],
    )
    with patch("NZMealOptimiser.llm.llm_client.Mistral", return_value=fake_mistral), \
         patch("NZMealOptimiser.llm.llm_client.time.sleep"):
        client = LLMClient(provider="mistral", model_id="mistral-medium-latest")
        with pytest.raises(LLMGenerationError, match="Failed to get valid JSON"):
            client.generate_ingredients("x")
    assert fake_mistral.chat.complete.call_count == 3
