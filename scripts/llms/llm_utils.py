"""
LLM Utilities
=============
Shared parsing, validation, and scaling utilities for the LLM-integrated
dish pipeline.

Consolidates two responsibilities:
  1. Ingredient parsing — validate/normalize LLM-generated dish JSON into
     typed dataclasses (ParsedDish, ParsedIngredient) and resolve ingredient
     lists via resolution order: curated dishes.json → LLM generation → fallback.
  2. Quantity scaling — parse optimiser CSV rows and compute scaling ratios
     between LLM-generated ingredient quantities and supermarket pack sizes.

Usage:
    from scripts.llms.llm_utils import (
        ParsedDish, parse_and_validate, LLMParseError,
        resolve_ingredients, parse_optimiser_columns,
    )

    dish = parse_and_validate(raw_llm_response)   # raises LLMParseError on hard failures
    dish_dict, source = resolve_ingredients("spaghetti bolognese", portions=4)
    scaled = parse_optimiser_columns(csv_row_enriched_with_llm_data)
"""

import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

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
# Ingredient Parsing & Validation
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
    approx_quantity: Optional[float] = None
    approx_unit: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "quantity": self.quantity,
            "unit": self.unit,
            "search_term": self.search_term,
        }
        if self.approx_quantity is not None:
            d["approx_quantity"] = self.approx_quantity
        if self.approx_unit is not None:
            d["approx_unit"] = self.approx_unit
        return d


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
            "approx_quantity": None,
            "approx_unit": None,
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

        # approx_quantity (optional)
        approx_qty_raw = ing.get("approx_quantity")
        if approx_qty_raw is not None:
            normalized["approx_quantity"] = _coerce_to_float(approx_qty_raw, "approx_quantity")

        # approx_unit (optional)
        approx_unit_raw = ing.get("approx_unit")
        if approx_unit_raw is not None:
            if not isinstance(approx_unit_raw, str):
                print(f"  [WARN] Ingredient #{i}: 'approx_unit' must be a string, ignoring")
            else:
                normalized["approx_unit"] = approx_unit_raw.strip()

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
    3. Fallback [dish_name]  ← legacy single-search-term behaviour

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
        # Strip None approx fields so output matches curated format (keys only when present)
        cleaned = []
        for ing in parsed.ingredients:
            c = {k: v for k, v in ing.items() if v is not None or k in ("quantity", "unit", "search_term")}
            cleaned.append(c)
        return (
            {"dish_name": parsed.dish_name, "portion": parsed.portion,
             "ingredients": cleaned},
            "LLM",
        )
    except (LLMGenerationError, LLMParseError) as e:
        print(f"  [WARN] LLM generation failed for '{dish}': {e}")
        print("  [WARN] Falling back to single-search-term behaviour")

    # --- 4. Last-resort fallback: use dish name itself as search term ---
    return (
        {"dish_name": dish, "portion": portions, "ingredients": [dish_key]},
        "fallback",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Quantity Scaling
# ──────────────────────────────────────────────────────────────────────────────

# Unit conversion factors to grams (weight) and milliliters (volume)
# Cooking units (tbsp, tsp, cloves) use approximate conversions.
_WEIGHT_UNITS_TO_G = {
    "g": 1.0,
    "kg": 1000.0,
    "mg": 0.001,
    "oz": 28.3495,
    "lb": 453.592,
    "clove": 5.0,        # approximate: 1 garlic clove ≈ 5g
    "cloves": 5.0,
}

_VOLUME_UNITS_TO_ML = {
    "ml": 1.0,
    "l": 1000.0,
    "cl": 10.0,
    "cup": 240.0,
    "cups": 240.0,
    "tbsp": 15.0,        # US tablespoon ≈ 15ml
    "tsp": 5.0,          # teaspoon ≈ 5ml
}

_COUNT_UNITS = {"ea", "unit", "pk", "pack", "bunch", "each"}


def _parse_compound_unit(unit: str) -> tuple[float, str]:
    """Parse a compound unit like "x 375ml" or "x 25g".

    These units appear in CSV rows where `quantity` is the case/sachet count
    (e.g. 10) and `measurement_unit` is "x 375ml" (meaning 10 × 375ml bottles).

    Returns (multiplier, base_unit) where:
        - multiplier is the per-item quantity (e.g. 375 for "x 375ml")
        - base_unit is the unit after "x" (e.g. "ml", "g")
    Returns (1.0, unit_lower) if the unit does not match the "x UNIT" pattern.
    """
    if unit is None:
        return 1.0, ""
    unit_lower = unit.lower().strip()

    if unit_lower.startswith("x "):
        match = re.match(r"^x\s+(\d+(?:\.\d+)?)\s*([a-zA-Z]+)$", unit_lower)
        if match:
            return float(match.group(1)), match.group(2)

    return 1.0, unit_lower


def _to_common_quantity(qty: float, unit: str) -> tuple[float, str]:
    """Convert a quantity to a common base unit (g for weight, ml for volume, or original).

    Handles compound units like "x 375ml" by expanding the multiplier:
        e.g. qty=10, unit="x 375ml" → (3750.0, "ml")

    Count units ("ea", "unit", "pk", "pack", "bunch") are grouped as "count"
    so they can be compared against each other.

    Returns (converted_qty, base_unit) where base_unit is 'g', 'ml', 'count',
    or the original unit if no conversion applies.
    """
    if unit is None:
        return qty, ""

    unit_lower = unit.lower().strip()

    # Handle compound units like "x 375ml"
    multiplier, base_unit = _parse_compound_unit(unit_lower)
    if multiplier != 1.0:
        qty *= multiplier
        unit_lower = base_unit

    if unit_lower in _WEIGHT_UNITS_TO_G:
        return qty * _WEIGHT_UNITS_TO_G[unit_lower], "g"

    if unit_lower in _VOLUME_UNITS_TO_ML:
        return qty * _VOLUME_UNITS_TO_ML[unit_lower], "ml"

    if unit_lower in _COUNT_UNITS:
        return qty, "count"

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


def parse_optimiser_columns(row: dict) -> dict:
    """Parse an optimiser CSV row enriched with LLM ingredient data and compute scaling.

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
        "ingredient_approx_quantity": number | None,  # LLM approx quantity (optional, for non-standard units)
        "ingredient_approx_unit": str | None,   # LLM approx unit (optional)
        "per_unit_price": float,                # comparative price per unit, may be 0
        "pack_quantity": number,                # quantity from the supermarket API result
        "pack_unit": str,                       # measurement_unit from the supermarket API result
        "scaling_ratio": float or None,         # LLM quantity / pack quantity (unit-normalized). None if genuinely incompatible
        "used_price": float or None,            # proportional cost for the amount the user needs. None if incompatible
        "purchase_quantity": int,               # number of packs to buy (ceil if ratio > 1)
        "purchase_price": float or None,        # total cost for the number of packs purchased. None if incompatible
        "status": str,                          # "ok", "approximate", or "incompatible_units"
        "unit_approximate": bool,               # True if 1ml≈1g approximation applied (volume vs weight cross-category)
        "units_match": bool,                    # True if recipe and pack units are in the same base category (no approximation needed)
    }

    Rules:
        - If scaling_ratio <= 1: used_price = pack_price * scaling_ratio
          purchase_quantity = 1 (still buy 1 pack), purchase_price = pack_price
        - If scaling_ratio > 1: purchase_quantity = ceil(scaling_ratio)
          purchase_price = pack_price * purchase_quantity
          used_price = pack_price * scaling_ratio (proportional cost for what was actually used)
        - If units are incompatible across categories (weight vs volume, e.g. g vs ml): applies 1ml ≈ 1g approximation,
          scaling_ratio computed, unit_approximate=True, status="approximate"
        - If units are genuinely incompatible (e.g. count vs weight: 1 unit vs 500g):
          falls back to ingredient_approx_quantity/ingredient_approx_unit if available
          (e.g. "1 medium onion" ≈ 150g vs a 500g pack). If the approx unit is in a
          compatible category with the pack unit, scaling_ratio is computed with
          unit_approximate=True (or True if cross-category 1ml≈1g was applied),
          status="approximate".
          If no approx fallback is available, or the approx unit is also incompatible,
          scaling_ratio, used_price, and purchase_price are set to None,
          status = "incompatible_units".
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

    # Optional approx fields for non-standard units ("1 medium onion", "1 can", etc.)
    ingredient_approx_quantity = _safe_float(row.get("ingredient_approx_quantity", 0)) if row.get("ingredient_approx_quantity") else None
    ingredient_approx_unit = row.get("ingredient_approx_unit", "") if row.get("ingredient_approx_unit") else None

    # --- Compute scaling ratio with unit normalisation ---
    # Convert both quantities to a common base to handle unit mismatches
    # (e.g., LLM says 1000g, pack says 1kg → ratio = 1.0)
    req_qty_base, req_base_unit = _to_common_quantity(ingredient_quantity, ingredient_measurement)
    pack_qty_base, pack_base_unit = _to_common_quantity(pack_quantity, pack_unit)

    # Cross-category: weight (g) vs volume (ml).
    # Apply 1ml ≈ 1g approximation so proportional costs can still be computed.
    # The approximation is flagged so callers can indicate it in output.
    cross_category = (
        (pack_base_unit == "g" and req_base_unit == "ml")
        or (pack_base_unit == "ml" and req_base_unit == "g")
    )
    unit_approximate = False
    used_approx_fallback = False

    if req_base_unit == "" or pack_base_unit == "":
        # One or both sides have no recognizable unit — fall back to raw ratio
        scaling_ratio = req_qty_base / pack_qty_base if pack_qty_base > 0 else 0.0
    elif pack_base_unit == req_base_unit:
        # Units match (both g, both ml, both count, etc.) — normal ratio
        scaling_ratio = req_qty_base / pack_qty_base if pack_qty_base > 0 else 0.0
    elif cross_category:
        # Weight vs volume — apply 1ml ≈ 1g approximation
        scaling_ratio = req_qty_base / pack_qty_base if pack_qty_base > 0 else 0.0
        unit_approximate = True
    else:
        # Units are incompatible (e.g. count vs weight: 1 unit vs 500g)
        # Try falling back to approx_quantity/approx_unit if the LLM provided them.
        if ingredient_approx_quantity and ingredient_approx_unit:
            approx_qty_base, approx_base_unit = _to_common_quantity(
                ingredient_approx_quantity, ingredient_approx_unit
            )
            if (pack_base_unit == approx_base_unit
                or (pack_base_unit == "g" and approx_base_unit == "ml")
                or (pack_base_unit == "ml" and approx_base_unit == "g")):
                # Approx values are in a compatible category (or cross-category) with the pack
                scaling_ratio = approx_qty_base / pack_qty_base if pack_qty_base > 0 else 0.0
                used_approx_fallback = True
                if pack_base_unit != approx_base_unit:
                    unit_approximate = True  # 1ml ≈ 1g cross-category approximation
            else:
                scaling_ratio = None
        else:
            # Genuinely incompatible — no approx fallback available
            scaling_ratio = None

    # --- Compute purchase decisions ---
    if scaling_ratio is None:
        # Incompatible units — product can't be used
        used_price = None
        purchase_quantity = 0
        purchase_price = None
        status = "incompatible_units"
    elif scaling_ratio <= 1:
        used_price = pack_price * scaling_ratio
        purchase_quantity = 1
        purchase_price = pack_price
        status = "approximate" if (unit_approximate or used_approx_fallback) else "ok"
    else:
        purchase_quantity = math.ceil(scaling_ratio)
        purchase_price = pack_price * purchase_quantity
        used_price = pack_price * scaling_ratio
        status = "approximate" if (unit_approximate or used_approx_fallback) else "ok"

    return {
        "search_ingredient": search_ingredient,
        "returned_ingredient": returned_ingredient,
        "ingredient_quantity": ingredient_quantity,          # LLM-generated
        "ingredient_measurement": ingredient_measurement,       # LLM-generated
        "ingredient_approx_quantity": ingredient_approx_quantity,  # LLM approx (optional)
        "ingredient_approx_unit": ingredient_approx_unit,       # LLM approx (optional)
        "per_unit_price": per_unit_price,   # comparative price from supermarket (may be 0)
        "pack_quantity": pack_quantity,     # from CSV
        "pack_unit": pack_unit,             # from CSV
        "scaling_ratio": None if scaling_ratio is None else round(scaling_ratio, 4),
        "used_price": None if used_price is None else round(used_price, 2),
        "purchase_quantity": purchase_quantity,
        "purchase_price": None if purchase_price is None else round(purchase_price, 2),
        "status": status,
        "unit_approximate": unit_approximate,
        "units_match": (not unit_approximate and not used_approx_fallback),
    }
