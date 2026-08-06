"""
LLM Utilities
=============
Shared parsing, validation, and scaling utilities for the LLM-integrated
dish pipeline.

Consolidates two responsibilities:
  1. Ingredient parsing — validate/normalize LLM-generated dish JSON into
     typed dataclasses (ParsedDish, ParsedIngredient) and resolve ingredient
     lists via resolution order: curated dishes.json → LLM generation → fallback.
  2. Quantity scaling — parse optimizer CSV rows and compute scaling ratios
     between LLM-generated ingredient quantities and supermarket pack sizes.

Usage:
    from scripts.llms.llm_utils import (
        ParsedDish, parse_and_validate, LLMParseError,
        resolve_ingredients, parse_optimizer_columns,
    )

    dish = parse_and_validate(raw_llm_response)   # raises LLMParseError on hard failures
    dish_dict, source = resolve_ingredients("spaghetti bolognese", portions=4)
    scaled = parse_optimizer_columns(csv_row_enriched_with_llm_data)
"""

import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.llms.llm_client import LLMClient, LLMGenerationError

load_dotenv()

DATA_DIR = _PROJECT_ROOT / "data"
DISHES_JSON = DATA_DIR / "dishes.json"
DISHES_FILE = DATA_DIR / "dishes.json"

# ──────────────────────────────────────────────────────────────────────────────
# Ingredient Parsing & Validation (from ingredient_parser.py)
# ──────────────────────────────────────────────────────────────────────────────


class LLMParseError(Exception):
    """Raised when LLM output fails structural validation."""
    pass


@dataclass
class ParsedIngredient:
    """A single ingredient with quantity, unit, and supermarket search term."""
    quantity: float
    unit: str
    search_term: str

    def to_dict(self) -> dict:
        return {
            "quantity": self.quantity,
            "unit": self.unit,
            "search_term": self.search_term,
        }


@dataclass
class ParsedDish:
    """Validated dish data from the LLM."""
    dish_name: str
    portion: int
    ingredients: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dish_name": self.dish_name,
            "portion": self.portion,
            "ingredients": self.ingredients,
        }


def _coerce_to_int(value: Any, field_name: str) -> int:
    """Coerce a value to int. Rejects strings."""
    if isinstance(value, bool):
        raise LLMParseError(f"{field_name} must be an integer, got boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value == int(value):
            return int(value)
        raise LLMParseError(f"{field_name} must be a whole number, got {value}")
    raise LLMParseError(f"{field_name} must be an integer, got {type(value).__name__}: {value!r}")


def _coerce_to_float(value: Any, field_name: str) -> float:
    """Coerce a value to float. Accepts ints and floats, rejects strings."""
    if isinstance(value, bool):
        raise LLMParseError(f"{field_name} must be a number, got boolean")
    if isinstance(value, (int, float)):
        return float(value)
    raise LLMParseError(f"{field_name} must be a number, got {type(value).__name__}: {value!r}")


def parse_and_validate(raw_json: dict) -> ParsedDish:
    """Validate and normalize raw LLM JSON output into a ParsedDish.

    Hard failures (raise LLMParseError):
        - Missing or non-str dish_name
        - Missing or non-int portion (strings rejected)
        - Missing or empty ingredients list
        - Missing quantity/unit/search_term on any ingredient

    Warnings (printed, non-fatal):
        - Missing quantity or unit on an ingredient (will be set to None/empty)
        - Empty search_term (will be set to empty string)

    Args:
        raw_json: dict from LLMClient.generate_ingredients

    Returns:
        ParsedDish with normalized types

    Raises:
        LLMParseError: on structural validation failures
    """
    if not isinstance(raw_json, dict):
        raise LLMParseError(f"Expected dict, got {type(raw_json).__name__}")

    # --- dish_name ---
    dish_name = raw_json.get("dish_name")
    if not dish_name or not isinstance(dish_name, str):
        raise LLMParseError(f"Missing or invalid 'dish_name' (must be non-empty string)")

    # --- portion ---
    portion_raw = raw_json.get("portion")
    portion = _coerce_to_int(portion_raw, "portion")

    # --- ingredients ---
    ingredients_raw = raw_json.get("ingredients")
    if not ingredients_raw or not isinstance(ingredients_raw, list):
        raise LLMParseError("'ingredients' must be a non-empty list")

    normalized_ingredients: list[dict] = []
    for i, ing in enumerate(ingredients_raw, 1):
        if not isinstance(ing, dict):
            raise LLMParseError(f"Ingredient #{i} must be a dict, got {type(ing).__name__}")

        normalized: dict = {
            "quantity": None,
            "unit": "",
            "search_term": "",
        }

        # quantity
        qty_raw = ing.get("quantity")
        if qty_raw is None:
            raise LLMParseError(f"Ingredient #{i} ('{ing.get('search_term', '?')}'): missing 'quantity'")
        normalized["quantity"] = _coerce_to_float(qty_raw, "quantity")

        # unit
        unit_raw = ing.get("unit")
        if unit_raw is None:
            raise LLMParseError(f"Ingredient #{i} ('{ing.get('search_term', '?')}'): missing 'unit'")
        if not isinstance(unit_raw, str):
            raise LLMParseError(f"Ingredient #{i}: 'unit' must be a string")
        normalized["unit"] = unit_raw.strip()

        # search_term
        term_raw = ing.get("search_term")
        if term_raw is None:
            raise LLMParseError(f"Ingredient #{i}: missing 'search_term'")
        if not isinstance(term_raw, str):
            raise LLMParseError(f"Ingredient #{i}: 'search_term' must be a string")
        normalized["search_term"] = term_raw.strip()
        if not normalized["search_term"]:
            print(f"  [WARN] Ingredient #{i}: empty search_term")

        normalized_ingredients.append(normalized)

    return ParsedDish(
        dish_name=dish_name.strip(),
        portion=portion,
        ingredients=normalized_ingredients,
    )


def resolve_ingredients(dish: str, portions: int = 4, regenerate: bool = False,
                         model_alias: str = "medium") -> tuple[dict, str]:
    """Resolve ingredient list for a dish via resolution order:

    1. dishes.json structured records  ← if dish_key exists and not regenerate → use full ingredient dicts
    2. LLM dish builder  ← generate fresh, no caching
    3. Fallback [dish_name]  ← legacy single-search-term behavior

    Args:
        dish: dish name string
        portions: number of servings (int, default 4)
        regenerate: if True, skip curated set and go straight to LLM
        model_alias: model alias for LLM generation ("small"/"medium"/"large")

    Returns:
        (dish_dict, source) where:
        - dish_dict: {"dish_name": str, "portion": int, "ingredients": list}
          ingredients are list of dicts with quantity/unit/search_term.
        - source: "curated", "LLM", or "fallback"
    """
    dish_key = dish.lower().strip()

    # --- 1. Curated set from dishes.json (structured schema) ---
    if not regenerate and DISHES_JSON.exists():
        try:
            with open(DISHES_JSON, "r", encoding="utf-8") as f:
                curated = json.load(f)
            if dish_key in curated:
                entry = curated[dish_key]
                dish_name = entry.get("dish_name", dish)
                portion = entry.get("portion", portions)
                try:
                    portion = int(portion)
                except (TypeError, ValueError):
                    portion = portions
                ingredients = entry.get("ingredients", [])
                if not ingredients:
                    # Legacy schema fallback: reconstruct from search_terms
                    search_terms = entry.get("search_terms", [])
                    ingredients = [{"quantity": None, "unit": "", "search_term": t} for t in search_terms]
                return (
                    {"dish_name": dish_name, "portion": portion, "ingredients": ingredients},
                    "curated",
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # --- 2. LLM generation ---
    try:
        client = LLMClient(model_alias=model_alias)
        raw = client.generate_ingredients(dish, portion=portions)
        parsed = parse_and_validate(raw)
        return (
            {"dish_name": parsed.dish_name, "portion": parsed.portion,
             "ingredients": parsed.ingredients},
            "LLM",
        )
    except (LLMGenerationError, LLMParseError) as e:
        print(f"  [WARN] LLM generation failed for '{dish}': {e}")
        print("  [WARN] Falling back to single-search-term behavior")

    # --- 4. Last-resort fallback: use dish name itself as search term ---
    return (
        {"dish_name": dish, "portion": portions, "ingredients": [dish_key]},
        "fallback",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Quantity Scaling (from quantity_scaling_parser.py)
# ──────────────────────────────────────────────────────────────────────────────

# Unit conversion factors to grams (weight) and milliliters (volume)
_WEIGHT_UNITS_TO_G = {
    "g": 1.0,
    "kg": 1000.0,
    "mg": 0.001,
    "oz": 28.3495,
    "lb": 453.592,
}

_VOLUME_UNITS_TO_ML = {
    "ml": 1.0,
    "l": 1000.0,
    "cl": 10.0,
    "cup": 240.0,
}


def _to_common_quantity(qty: float, unit: str) -> tuple[float, str]:
    """Convert a quantity to a common base unit (g for weight, ml for volume, or original).

    Returns (converted_qty, base_unit) where base_unit is 'g', 'ml', or the
    original unit if no conversion applies.
    """
    if unit is None:
        return qty, ""

    unit_lower = unit.lower().strip()

    if unit_lower in _WEIGHT_UNITS_TO_G:
        return qty * _WEIGHT_UNITS_TO_G[unit_lower], "g"

    if unit_lower in _VOLUME_UNITS_TO_ML:
        return qty * _VOLUME_UNITS_TO_ML[unit_lower], "ml"

    return qty, unit_lower


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float, handling strings, None, and empty values."""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    return default


def parse_optimizer_columns(row: dict) -> dict:
    """Parse an optimizer CSV row enriched with LLM ingredient data and compute scaling.

    The input row should contain:
        - CSV fields: search_ingredient, returned_ingredient, quantity (pack size),
          measurement_unit (pack unit), price (total pack price in dollars),
          per_unit_price (comparative price per unit, optional)
        - LLM-enriched fields: ingredient_quantity, ingredient_measurement (the recipe amount needed)

    Args:
        row: dict with CSV columns + ingredient_quantity + ingredient_measurement

    Returns:
        {
            "search_ingredient": str,
            "returned_ingredient": str,
            "ingredient_quantity": number,          # LLM-generated quantity
            "ingredient_measurement": str,          # LLM-generated unit
            "per_unit_price": float,                # total pack price (from CSV 'price' column)
            "pack_quantity": number,                # quantity from the supermarket API result
            "pack_unit": str,                       # measurement_unit from the supermarket API result
            "scaling_ratio": float,                 # LLM quantity / pack quantity (unit-normalized)
            "used_price": float,                    # proportional cost for the amount the user needs
            "purchase_quantity": int,               # number of packs to buy (ceil if ratio > 1)
            "purchase_price": float,                # total cost for the number of packs purchased
        }

    Rules:
        - If scaling_ratio <= 1: used_price = pack_price * scaling_ratio
          purchase_quantity = 1 (still buy 1 pack), purchase_price = pack_price
        - If scaling_ratio > 1: purchase_quantity = ceil(scaling_ratio)
          purchase_price = pack_price * purchase_quantity
          used_price = pack_price * scaling_ratio (proportional cost for what was actually used)
    """
    # --- Extract CSV fields ---
    search_ingredient = row.get("search_ingredient", "")
    returned_ingredient = row.get("returned_ingredient", "")

    # Pack data from CSV
    pack_quantity = _safe_float(row.get("quantity", 0))
    pack_unit = row.get("measurement_unit", "")

    # Price: prefer 'price' (total pack price), fall back to 'per_unit_price'
    pack_price = _safe_float(row.get("price", row.get("per_unit_price", 0)))
    per_unit_price = _safe_float(row.get("per_unit_price", 0))

    # --- Extract LLM-enriched fields ---
    # If ingredient_quantity/ingredient_measurement not present, fall back to pack values (backward compat)
    ingredient_quantity = _safe_float(row.get("ingredient_quantity", row.get("quantity", 0)))
    ingredient_measurement = row.get("ingredient_measurement", row.get("measurement_unit", ""))

    # --- Compute scaling ratio with unit normalization ---
    # Convert both quantities to a common base to handle unit mismatches
    # (e.g., LLM says 1000g, pack says 1kg → ratio = 1.0)
    req_qty_base, req_base_unit = _to_common_quantity(ingredient_quantity, ingredient_measurement)
    pack_qty_base, pack_base_unit = _to_common_quantity(pack_quantity, pack_unit)

    if pack_qty_base > 0 and (pack_base_unit == req_base_unit or req_base_unit == ""):
        scaling_ratio = req_qty_base / pack_qty_base
    else:
        # Units don't match or can't convert — use raw values
        scaling_ratio = req_qty_base / pack_qty_base if pack_qty_base > 0 else 0.0

    # --- Compute purchase decisions ---
    if scaling_ratio <= 1:
        used_price = pack_price * scaling_ratio
        purchase_quantity = 1
        purchase_price = pack_price
    else:
        purchase_quantity = math.ceil(scaling_ratio)
        purchase_price = pack_price * purchase_quantity
        used_price = pack_price * scaling_ratio

    return {
        "search_ingredient": search_ingredient,
        "returned_ingredient": returned_ingredient,
        "ingredient_quantity": ingredient_quantity,          # LLM-generated
        "ingredient_measurement": ingredient_measurement,       # LLM-generated
        "per_unit_price": per_unit_price,   # comparative price from supermarket (may be 0)
        "pack_quantity": pack_quantity,     # from CSV
        "pack_unit": pack_unit,             # from CSV
        "scaling_ratio": round(scaling_ratio, 4),
        "used_price": round(used_price, 2),
        "purchase_quantity": purchase_quantity,
        "purchase_price": round(purchase_price, 2),
    }
