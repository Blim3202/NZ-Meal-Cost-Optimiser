"""LLM generation service for custom dishes (web dashboard).

Two sequential calls power ``POST /dishes/generate``:

1. :func:`generate_dish_ingredients` — Mistral (the "medium" alias) turns a
   dish name into validated ingredient rows (``search_term`` / ``quantity`` /
   ``unit`` / optional ``approx_quantity`` + ``approx_unit``) using the same
   INGREDIENT_PROMPT + parse_and_validate pipeline as resolve_ingredients().
2. :func:`generate_ingredient_filters` — Google Gemini flash-lite produces
   include/exclude keyword rules per generated search term (prompt + parsing
   ported from exploration/llm/explore_filter_explorer.py), shaped to match
   the runtime IngredientFilterSet contract so the run filters products with
   the same matches_ingredient_filters() machinery used for curated presets
   from data/dish_filters.json.

Error model:
    GenerationConfigError       missing API key — endpoint maps to HTTP 503
    IngredientGenerationError   LLM failed after retries — HTTP 502
    FilterGenerationError       NON-fatal: generate_custom_dish() catches it,
                                returns empty rules + a warning entry, so a
                                Gemini outage never blocks usable ingredients.

Usage:
    from NZMealOptimiser.llm.generation import generate_custom_dish

    payload = generate_custom_dish("kumara & chorizo hash", base_portions=4)
    # {"dish_name": ..., "base_portions": ..., "source": "llm",
    #  "ingredients": [...], "filters": {...}, "warnings": [...]}
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Callable

from dotenv import load_dotenv

from NZMealOptimiser.llm.llm_client import LLMClient, LLMGenerationError
from NZMealOptimiser.llm.llm_utils import LLMParseError, normalise_unit, parse_and_validate

load_dotenv()

GOOGLE_API_KEY_ENVS = ("GOOGLE_API_KEY", "GEMINI_API_KEY")
GOOGLE_FILTER_MODEL_ENV = "GOOGLE_FILTER_MODEL"
GOOGLE_FILTER_MODEL_DEFAULT = "gemini-3.1-flash-lite"

# Upper bound on generated ingredient rows. Each row becomes one search per
# selected store per company, so an unbounded LLM response could fan out into
# hundreds of supermarket queries.
MAX_INGREDIENTS = 10

# Mirror the curated baseline in data/dish_filters.json ("max 5 words").
MAX_EXCLUDES = 5


class GenerationError(Exception):
    """Base class for custom-dish generation failures."""


class GenerationConfigError(GenerationError):
    """A required API key is missing from the environment (HTTP 503)."""


class IngredientGenerationError(GenerationError):
    """Mistral failed to produce usable ingredients after retries (HTTP 502)."""


class FilterGenerationError(GenerationError):
    """Gemini failed to produce filter rules (soft-failed by the orchestrator)."""


# ─── Ingredient generation (Mistral) ─────────────────────────────────────────

def generate_dish_ingredients(dish_name: str, portions: int = 4) -> tuple[list[dict], list[str]]:
    """Generate validated ingredient rows for *dish_name* via Mistral.

    Returns ``(ingredients, warnings)`` where ingredients follow the curated
    dishes.json schema: ``{quantity, unit, search_term[, approx_quantity,
    approx_unit]}`` — units folded through UNIT_ALIASES, duplicates merged
    (first wins), unusable rows dropped, count capped at MAX_INGREDIENTS.
    Every quality intervention appends a human-readable warning so the UI can
    show exactly what the model's raw output was trimmed to.

    Raises:
        GenerationConfigError: MISTRAL_API_KEY not configured.
        IngredientGenerationError: generation/validation failed after retries,
            or the model produced no usable rows.
    """
    if not os.getenv("MISTRAL_API_KEY"):
        raise GenerationConfigError(
            "MISTRAL_API_KEY is not set — add it to .env to enable ingredient generation"
        )
    try:
        client = LLMClient(model_alias="medium")
        raw = client.generate_ingredients(dish_name, portion=portions)
        parsed = parse_and_validate(raw)
    except LLMGenerationError as exc:
        raise IngredientGenerationError(f"Mistral could not generate ingredients: {exc}") from exc
    except LLMParseError as exc:
        raise IngredientGenerationError(f"Mistral returned an invalid recipe: {exc}") from exc

    ingredients: list[dict] = []
    seen: set[str] = set()
    warnings: list[str] = []
    for ing in parsed.ingredients:
        term = str(ing.get("search_term", "")).strip()
        quantity = ing.get("quantity")
        if not term:
            warnings.append("dropped one ingredient with an empty search term")
            continue
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            warnings.append(f"dropped '{term}' — its quantity must be greater than zero")
            continue
        key = term.lower()
        if key in seen:
            warnings.append(f"merged duplicate search term '{term}'")
            continue
        seen.add(key)
        entry: dict = {
            "quantity": float(quantity),
            "unit": normalise_unit(ing.get("unit", "")),
            "search_term": term,
        }
        approx_quantity = ing.get("approx_quantity")
        approx_unit = ing.get("approx_unit")
        if isinstance(approx_quantity, (int, float)) and approx_quantity > 0 and approx_unit:
            entry["approx_quantity"] = float(approx_quantity)
            entry["approx_unit"] = normalise_unit(approx_unit)
        ingredients.append(entry)
        if len(ingredients) >= MAX_INGREDIENTS:
            dropped = len(parsed.ingredients) - len(ingredients)
            if dropped > 0:
                warnings.append(f"capped the recipe at {MAX_INGREDIENTS} ingredients ({dropped} dropped)")
            break

    if not ingredients:
        raise IngredientGenerationError(
            f"Mistral returned no usable ingredients for '{dish_name}'"
        )
    return ingredients, warnings


# ─── Filter-rule generation (Gemini) ─────────────────────────────────────────

FILTER_PROMPT_TEMPLATE = """\
You are a search-intent filter labeller for a New Zealand supermarket price comparator.
A recipe needs the ingredients listed below. For each search_term (the exact query sent
to the supermarket product search API), produce keyword filters that separate CORRECT
products from the WRONG products such searches commonly return.

Respond with ONE JSON object and nothing else:
{{"filters": [
    {{"search_term": "<verbatim copy of a search term>",
      "includes": "<one word>",
      "excludes": ["<word>", "<word>"]}}
]}}

Rules:
- Return exactly one filter object per search_term, echoing "search_term" verbatim.
- "includes": ONE singular word — the core noun identifying the ingredient itself as it
  appears on NZ supermarket shelf labels. Fuzzy matching handles plurals and minor typos,
  so the singular form is safest ("carrot" matches both Carrots and Carrot). Pick the
  single most distinctive noun; never use brand names, pack sizes, or the dish name.
- "excludes": up to {max_excludes} single words which, if present in a product title,
  mark it as WRONG for this search_term. Consider which of these common false-positive
  categories actually apply:
  * processed/derived forms of the ingredient: powder, flakes, seasoning, sachet, extract
  * prepared foods built on the ingredient: soup, pie, cake, dip, chips, crackers, sauce
  * flavoured snacks and meal kits that merely mention the ingredient
  Only add an exclude when products containing that word would genuinely be unsuitable.
  Do not pad with speculative words, and never exclude a legitimate form of the ingredient.

Search terms:
{search_terms_json}
"""


def _chat_with_retry(send: Callable[[], str], is_rate_limit: Callable[[Exception], bool],
                     max_retries: int = 3) -> str:
    """Call *send()* retrying on rate limits with linear backoff."""
    for attempt in range(1, max_retries + 1):
        try:
            return send()
        except Exception as e:  # noqa: BLE001 — re-raised unless rate-limited
            if is_rate_limit(e) and attempt < max_retries:
                time.sleep(20 * attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def _loads_json(content: str):
    """Parse model output tolerating markdown code fences."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    return json.loads(cleaned)


def call_gemini(prompt: str) -> str:
    """Send one chat completion to Google Gemini via its OpenAI-compatible API.

    Module-level so tests can monkeypatch it; kept in sync with the proven
    invocation in exploration/llm/explore_filter_explorer.py.
    """
    from openai import OpenAI

    api_key = os.getenv(GOOGLE_API_KEY_ENVS[0]) or os.getenv(GOOGLE_API_KEY_ENVS[1])
    if not api_key:
        raise GenerationConfigError(
            "Neither GOOGLE_API_KEY nor GEMINI_API_KEY is set — "
            "add one to .env to enable filter-rule generation"
        )
    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    def send():
        resp = client.chat.completions.create(
            model=os.getenv(GOOGLE_FILTER_MODEL_ENV, GOOGLE_FILTER_MODEL_DEFAULT),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=4096,
        )
        return resp.choices[0].message.content

    def is_rate_limit(e: Exception) -> bool:
        return type(e).__name__ == "RateLimitError"

    return _chat_with_retry(send, is_rate_limit)


def parse_filters(parsed, search_terms: list[str]) -> tuple[dict, list[str]]:
    """Normalise model output to ``{term: {"includes": [word], "excludes": [...]}}``.

    Accepts a bare array or a dict wrapping one. Unknown search terms are
    reported as warnings (never invented); excludes are lowercased and capped
    at MAX_EXCLUDES. ``includes`` becomes a single-element LIST to match the
    runtime IngredientFilterSet contract (empty list when the model omitted it).
    """
    if isinstance(parsed, dict):
        entries = next((v for v in parsed.values() if isinstance(v, list)), None)
    elif isinstance(parsed, list):
        entries = parsed
    else:
        entries = None
    if entries is None:
        raise FilterGenerationError("no filter list found in Gemini response")

    terms_lower = {t.lower(): t for t in search_terms}
    filters: dict[str, dict] = {}
    warnings: list[str] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_term = str(entry.get("search_term", "")).strip()
        term = terms_lower.get(raw_term.lower())
        if term is None:
            warnings.append(f"ignored unknown search_term '{raw_term}'")
            continue
        inc = entry.get("includes", "")
        if isinstance(inc, list):
            inc = " ".join(str(w) for w in inc)
        inc = str(inc).strip().lower()
        exc = entry.get("excludes", [])
        if isinstance(exc, str):
            exc = [exc]
        exc = [str(w).strip().lower() for w in exc if str(w).strip()]
        if len(exc) > MAX_EXCLUDES:
            warnings.append(f"'{term}': trimmed excludes from {len(exc)} to {MAX_EXCLUDES}")
            exc = exc[:MAX_EXCLUDES]
        filters[term] = {"includes": [inc] if inc else [], "excludes": exc}

    missing = [t for t in search_terms if t not in filters]
    if missing:
        warnings.append(f"no filter generated for: {', '.join(missing)}")
    return filters, warnings


def generate_ingredient_filters(search_terms: list[str]) -> tuple[dict, list[str]]:
    """Generate include/exclude keyword rules for *search_terms* via Gemini.

    Raises:
        GenerationConfigError: no Google/Gemini API key configured.
        FilterGenerationError: the response could not be parsed after retries.
    """
    if not search_terms:
        return {}, []
    prompt = FILTER_PROMPT_TEMPLATE.format(
        max_excludes=MAX_EXCLUDES,
        search_terms_json=json.dumps(search_terms, ensure_ascii=False),
    )
    try:
        content = call_gemini(prompt)
        parsed = _loads_json(content)
    except GenerationConfigError:
        raise
    except Exception as exc:  # noqa: BLE001 — normalised into FilterGenerationError
        raise FilterGenerationError(f"Gemini filter generation failed: {exc}") from exc
    return parse_filters(parsed, search_terms)


# ─── Orchestrator ─────────────────────────────────────────────────────────────

def generate_custom_dish(dish_name: str, base_portions: int = 4) -> dict:
    """Full custom-dish draft: ingredients (Mistral) then rules (Gemini).

    Filter generation is best-effort: a Gemini failure yields empty rules plus
    a warning instead of discarding perfectly good ingredients. Response shape
    matches POST /dishes/generate.
    """
    ingredients, warnings = generate_dish_ingredients(dish_name, base_portions)
    terms = [ing["search_term"] for ing in ingredients]
    try:
        filters, filter_warnings = generate_ingredient_filters(terms)
        warnings.extend(filter_warnings)
    except GenerationError as exc:
        filters = {}
        warnings.append(f"filter rules unavailable: {exc}")
    return {
        "dish_name": dish_name,
        "base_portions": max(1, min(int(base_portions) or 4, 24)),
        "source": "llm",
        "ingredients": ingredients,
        "filters": filters,
        "warnings": warnings,
    }
