"""Tests for POST /dishes/generate — the LLM custom-dish draft endpoint.

generate_custom_dish is monkeypatched so no LLM is contacted; these tests
cover request validation, base-portion clamping, and error-status mapping.
"""
import asyncio

import pytest
from fastapi import HTTPException

from NZMealOptimiser.llm.generation import GenerationConfigError, GenerationError
from NZMealOptimiser.web import main as web_main
from NZMealOptimiser.web.main import GenerateDishRequest


def _payload():
    return {
        "dish_name": "kumara hash",
        "base_portions": 4,
        "source": "llm",
        "ingredients": [{"quantity": 600.0, "unit": "g", "search_term": "kumara"}],
        "filters": {"kumara": {"includes": ["kumara"], "excludes": ["chips"]}},
        "warnings": [],
    }


def test_generate_happy_path(monkeypatch):
    calls = []

    def fake_generate(name, base):
        calls.append((name, base))
        return _payload()

    monkeypatch.setattr(web_main, "generate_custom_dish", fake_generate)
    out = asyncio.run(web_main.generate_dish(
        GenerateDishRequest(dish_name="  Kumara Hash  ", base_portions=4)))

    assert calls == [("Kumara Hash", 4)]  # stripped name, clamped portions
    assert out["source"] == "llm"
    assert out["ingredients"][0]["search_term"] == "kumara"
    assert out["filters"]["kumara"]["includes"] == ["kumara"]
    assert out["warnings"] == []


def test_generate_clamps_base_portions(monkeypatch):
    seen = []
    monkeypatch.setattr(web_main, "generate_custom_dish", lambda name, base: seen.append((name, base)) or _payload())
    asyncio.run(web_main.generate_dish(GenerateDishRequest(dish_name="x", base_portions=999)))
    assert seen == [("x", 24)]
    seen.clear()
    asyncio.run(web_main.generate_dish(GenerateDishRequest(dish_name="x", base_portions=0)))
    assert seen == [("x", 4)]


@pytest.mark.parametrize("name", ["", "   "])
def test_generate_requires_name(name):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(web_main.generate_dish(GenerateDishRequest(dish_name=name)))
    assert exc.value.status_code == 400


def test_missing_api_key_maps_to_503(monkeypatch):
    def no_key(name, base):
        raise GenerationConfigError("MISTRAL_API_KEY is not set")
    monkeypatch.setattr(web_main, "generate_custom_dish", no_key)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(web_main.generate_dish(GenerateDishRequest(dish_name="x")))
    assert exc.value.status_code == 503
    assert "MISTRAL_API_KEY" in exc.value.detail


def test_generation_failure_maps_to_502(monkeypatch):
    def broken(name, base):
        raise GenerationError("Mistral could not generate ingredients: no json")
    monkeypatch.setattr(web_main, "generate_custom_dish", broken)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(web_main.generate_dish(GenerateDishRequest(dish_name="x")))
    assert exc.value.status_code == 502
