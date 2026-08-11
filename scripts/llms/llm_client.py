"""
LLM Client — Mistral API Wrapper
================================
Single-responsibility wrapper around the Mistral API for ingredient generation.

Reads model aliases, IDs, and rate limits from environment variables (via .env).
Enforces rate limiting via time.sleep before each API call.
Retries up to 2x on JSON parse failure; raises LLMGenerationError on 3rd failure.

Usage:
    from scripts.llms.llm_client import LLMClient, LLMGenerationError

    client = LLMClient(model_alias="medium")
    result = client.generate_ingredients("spaghetti bolognese", portions=4)
"""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from mistralai.client import Mistral
from mistralai.client.errors import SDKError as MistralError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

load_dotenv()

API_KEY_ENV = "MISTRAL_API_KEY"
MODEL_ENV_PREFIX = "MISTRAL_MODEL_"
RATE_LIMIT_ENV_PREFIX = "MISTRAL_RATE_LIMIT_"

DEFAULT_MODELS = {
    "small": "ministral-3b-2512",
    "medium": "mistral-medium-latest",
    "large": "mistral-large-2512",
}

DEFAULT_RATE_LIMITS = {
    "small": 10.0,
    "medium": 0.5,
    "large": 0.067,
}

INGREDIENT_PROMPT = """You are a recipe ingredient generator. Given a classic or user stylised dish and portion count,
return a JSON object with ingredients and quantities.

Dish: {dish}
Portions: {portions}

Return a JSON object with this shape:
{{
  "dish_name": "...",
  "portion": 4,
  "ingredients": [
    {{
      "quantity": 500,
      "unit": "g",
      "search_term": "beef mince"
    }}
  ]
}}

Rules:
- Each ingredient must have exactly ONE search_term (a single string, not a list).
- "search_term" is the term to query supermarket APIs (use the most common NZ supermarket name).
- "portion" must be an integer (number of servings), not a string.
- "quantity" must be a number (int or float).
- "unit" must be a string (e.g. "g", "ml", "tbsp", "cloves", "unit").
- For ingredients with non-standard units (e.g. "1 medium onion", "1 can", "1 head of broccoli", "2 medium carrots", "1 bunch"), also include "approx_quantity" (in g or ml) and "approx_unit" ("g" or "ml"). Omit these fields for ingredients with standard weight/volume units (g, kg, mg, ml, l, cl, cup, tbsp, tsp, cloves, etc.).
- OMIT small or condiment ingredients like "water", "oil", "salt", "pepper" UNLESS the dish is centred around them (e.g. "deep fried chicken" keeps oil for frying, "pepper crab" keeps pepper).
- Do not include notes or extra fields.
"""


class LLMGenerationError(Exception):
    """Raised when the LLM fails to produce parseable JSON after retries."""
    pass


class LLMClient:
    """Mistral API client for ingredient generation with rate limiting and retries."""

    def __init__(self, model_alias: str = "medium"):
        self.model_alias = model_alias.lower()
        if self.model_alias not in DEFAULT_MODELS:
            raise ValueError(
                f"Unknown model_alias '{model_alias}'. "
                f"Valid: {list(DEFAULT_MODELS.keys())}"
            )

        api_key = os.getenv(API_KEY_ENV, "")
        if not api_key:
            raise ValueError(
                f"{API_KEY_ENV} is not set. Create a .env file with your Mistral API key."
            )

        model_env_var = f"{MODEL_ENV_PREFIX}{self.model_alias.upper()}"
        rate_limit_env_var = f"{RATE_LIMIT_ENV_PREFIX}{self.model_alias.upper()}"

        self.model_id = os.getenv(model_env_var, DEFAULT_MODELS[self.model_alias])
        rps = float(os.getenv(rate_limit_env_var, DEFAULT_RATE_LIMITS[self.model_alias]))
        self.rate_limit_sleep = 1.0 / rps if rps > 0 else 0.0

        self.client = Mistral(api_key=api_key)

    def _sleep_for_rate_limit(self):
        """Sleep before an API call to respect the model's rate limit."""
        if self.rate_limit_sleep > 0:
            time.sleep(self.rate_limit_sleep)

    def generate_ingredients(self, dish_name: str, portion: int = 4) -> dict:
        """Call Mistral to generate ingredient list for a dish.

        Args:
            dish_name: name of the dish (e.g. "spaghetti bolognese")
            portion: number of servings (int, default 4)

        Returns:
            Parsed JSON dict with keys: dish_name, portion, ingredients

        Raises:
            LLMGenerationError: after 3 failed JSON parses
            MistrallError: on API-level failures
        """
        prompt = INGREDIENT_PROMPT.format(dish=dish_name, portions=portion)
        max_retries = 3

        for attempt in range(max_retries):
            self._sleep_for_rate_limit()

            try:
                response = self.client.chat.complete(
                    model=self.model_id,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                )
            except MistralError as e:
                if attempt < max_retries - 1:
                    time.sleep(1.0)
                    continue
                raise

            content = response.choices[0].message.content

            try:
                data = json.loads(content)
                if isinstance(data, dict) and "ingredients" in data:
                    return data
            except (json.JSONDecodeError, TypeError):
                if attempt < max_retries - 1:
                    continue

        raise LLMGenerationError(
            f"Failed to get valid JSON from LLM after {max_retries} attempts "
            f"using model '{self.model_id}' for dish '{dish_name}'."
        )
