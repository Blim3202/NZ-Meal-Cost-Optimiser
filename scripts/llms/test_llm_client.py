"""
Phase 1 Smoke Test — Mistral API Connectivity & Ingredient Generation

Verifies:
  1. MISTRAL_API_KEY is set in .env
  2. Mistral client can list available models
  3. Chat completion with ingredient-generation prompt returns valid JSON

Usage:
    python -m scripts.llms.test_llm_client
    python -m scripts.llms.test_llm_client --dish "chicken katsu" --portions "2 servings"
    python -m scripts.llms.test_llm_client --model small
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from mistralai.client import Mistral

load_dotenv()

API_KEY = os.getenv("MISTRAL_API_KEY", "")

MODEL_ALIASES = {
    "small": os.getenv("MISTRAL_MODEL_SMALL", "ministral-3b-2512"),
    "medium": os.getenv("MISTRAL_MODEL_MEDIUM", "mistral-medium-latest"),
    "large": os.getenv("MISTRAL_MODEL_LARGE", "mistral-large-2512"),
}

RATE_LIMITS = {
    "small": float(os.getenv("MISTRAL_RATE_LIMIT_SMALL", "10")),
    "medium": float(os.getenv("MISTRAL_RATE_LIMIT_MEDIUM", "0.5")),
    "large": float(os.getenv("MISTRAL_RATE_LIMIT_LARGE", "0.067")),
}


def get_rate_limit_sleep(model_alias: str) -> float:
    """Return seconds to sleep before an API call based on model rate limit."""
    rps = RATE_LIMITS.get(model_alias, 0.5)
    return 1.0 / rps if rps > 0 else 0.0

PROMPT = """You are a recipe ingredient generator. Given a classic or user stylised dish and portion size,
return a JSON object with ingredients and quantities.

Dish: {dish}
Portions: {portions}

Return a JSON object with this shape:
{{
  "dish_name": "...",
  "portion": "...",
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
- Quantities and units reflect portion size at typical NZ supermarket pack sizes.
- OMIT small or condiment ingredients like "water", "oil", "salt", "pepper" UNLESS the dish is centred around them (e.g. "deep fried chicken" keeps oil for frying, "pepper crab" keeps pepper).
- Do not include notes or extra fields.
"""


def check_api_key():
    if not API_KEY:
        print("ERROR: MISTRAL_API_KEY is not set in .env")
        print("  Create a .env file in the project root with:")
        print("    MISTRAL_API_KEY=sk-your-key-here")
        sys.exit(1)
    print(f" [*] API key found ({API_KEY[:8]}...)")


def list_models(client):
    print("\n [*] Listing available models...")
    res = client.models.list()
    models = [m.id for m in res.data]
    print(f"    Found {len(models)} models")
    for m in models[:10]:
        print(f"      - {m}")
    if len(models) > 10:
        print(f"      ... and {len(models) - 10} more")
    return models


def generate_ingredients(client, model, dish, portions, model_alias="medium"):
    print(f"\n [*] Generating ingredients for '{dish}' ({portions})...")
    print(f"    Model: {model}")

    sleep_time = get_rate_limit_sleep(model_alias)
    if sleep_time > 0:
        time.sleep(sleep_time)

    prompt = PROMPT.format(
        dish=dish,
        portions=portions,
    )

    res = client.chat.complete(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )

    content = res.choices[0].message.content
    print("\n--- RAW RESPONSE ---")
    print(content)
    print("--- END RAW RESPONSE ---\n")

    try:
        data = json.loads(content)
        print(" [*] JSON parsed successfully")
        print(json.dumps(data, indent=2))
        return data
    except json.JSONDecodeError as e:
        print(f" ERROR: Failed to parse JSON: {e}")
        print("  The model may have included markdown or extra text.")
        print("  Try a different model or adjust the prompt.")
        return None


def main():
    parser = argparse.ArgumentParser(description="Phase 1: Mistral API smoke test")
    parser.add_argument("--dish", default="spaghetti bolognese", help="Dish name")
    parser.add_argument("--portions", default="4 servings", help="Portion description")
    parser.add_argument("--model", default="medium", choices=["small", "medium", "large"], help="Model size alias")
    parser.add_argument("--skip-models", action="store_true", help="Skip model listing (faster)")
    args = parser.parse_args()

    check_api_key()

    model_id = MODEL_ALIASES[args.model]
    print(f" [*] Using model: {model_id}")

    client = Mistral(api_key=API_KEY)

    if not args.skip_models:
        list_models(client)

    result = generate_ingredients(client, model_id, args.dish, args.portions, args.model)

    if result is None:
        print("\n[!] Smoke test FAILED — JSON parsing error")
        sys.exit(1)

    required_fields = ["dish_name", "portion", "ingredients"]
    missing = [f for f in required_fields if f not in result]
    if missing:
        print(f"\n[!] Smoke test FAILED — missing fields: {missing}")
        sys.exit(1)

    if not isinstance(result["ingredients"], list) or len(result["ingredients"]) == 0:
        print("\n[!] Smoke test FAILED — ingredients is empty or not a list")
        sys.exit(1)

    for i, ing in enumerate(result["ingredients"], 1):
        qty = ing.get("quantity", "<missing>")
        unit = ing.get("unit", "<missing>")
        term = ing.get("search_term", "<missing>")
        print(f"    {i:2d}. {qty} {unit:6s}  [{term}]")

    print(f"\n [+] Smoke test PASSED — {len(result['ingredients'])} ingredients generated")


if __name__ == "__main__":
    main()