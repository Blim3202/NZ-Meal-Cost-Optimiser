"""Tests for the /test dish-builder backend: unit normalisation, custom-dish
validation, portions scaling, and the dishes.json save/upsert round-trip.

These exercise pure helpers in NZMealOptimiser.web.main — no supermarket
network calls. The save test monkeypatches the module-level DATA_DIR onto a
tmp path so data/dishes.json is never touched.
"""
import asyncio
import json

import pytest
from fastapi import HTTPException

from NZMealOptimiser.llm.llm_utils import normalise_unit, parse_optimiser_columns
from NZMealOptimiser.web import main as web_main
from NZMealOptimiser.web.main import (
    CustomDish,
    CustomIngredient,
    _clean_custom_ingredients,
    _scale_ingredients_to_portions,
    _validate_custom_dish,
)


# ── Unit normalisation ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("pk", "pack"),
    ("PK", "pack"),
    ("ea", "each"),
    ("cups", "cup"),
    ("cloves", "clove"),
    ("grams", "g"),
    ("KG", "kg"),
    ("fillets", "fillet"),
    ("base", "base"),
    ("egg", "each"),
    ("eggs", "each"),
])
def test_normalise_unit_aliases(raw, expected):
    assert normalise_unit(raw) == expected


def test_normalise_unit_one_way():
    """egg folds into each, but each never expands back to egg."""
    assert normalise_unit("each") == "each"
    assert normalise_unit("6 eggs") == "6 eggs"  # only bare units are aliases


def test_eggs_scale_against_count_pack():
    """6 recipe eggs vs a 10-egg pack sold as "ea" -> 0.6 ratio, exact match."""
    row = {
        "search_ingredient": "eggs",
        "quantity": 10,
        "measurement_unit": "ea",
        "price": 5.0,
        "ingredient_quantity": 6,
        "ingredient_measurement": "eggs",
    }
    scaled = parse_optimiser_columns(row)
    assert scaled["status"] == "ok"
    assert scaled["units_match"] is True
    assert scaled["scaling_ratio"] == 0.6
    assert scaled["used_price"] == 3.0
    assert scaled["purchase_quantity"] == 1
    assert scaled["purchase_price"] == 5.0


def test_stalk_recipe_vs_count_pack_is_incompatible():
    """Recipe "2 stalk" (approx 80 g) vs a "1 ea" pack -> unusable product.

    Regression guard: incompatible rows used to report units_match=True
    because the flag only tracked "was an approximation applied", which was
    vacuously true when scaling failed outright — the All Results UI then
    showed a green tick for a product whose used cost could not be computed.
    """
    row = {
        "search_ingredient": "celery",
        "quantity": 1,
        "measurement_unit": "ea",
        "price": 3.99,
        "ingredient_quantity": 2,
        "ingredient_measurement": "stalk",
        "ingredient_approx_quantity": 80,
        "ingredient_approx_unit": "g",
    }
    scaled = parse_optimiser_columns(row)
    assert scaled["status"] == "incompatible_units"
    assert scaled["units_match"] is False
    assert scaled["used_price"] is None
    assert scaled["purchase_price"] is None
    assert scaled["purchase_quantity"] == 0


def test_normalise_unit_passthrough_and_garbage():
    assert normalise_unit("handful") == "handful"
    assert normalise_unit("  g ") == "g"
    assert normalise_unit("") == ""
    assert normalise_unit(None) == ""


# ── Custom ingredient cleaning ────────────────────────────────────────────────

def test_clean_strips_and_normalises():
    rows = [
        CustomIngredient(search_term=" beef mince ", quantity=500, unit="g"),
        CustomIngredient(search_term="beans", quantity=1, unit="can",
                         approx_quantity=400, approx_unit=" grams"),
    ]
    cleaned = _clean_custom_ingredients(rows)
    assert cleaned[0] == {"quantity": 500.0, "unit": "g", "search_term": "beef mince"}
    assert cleaned[1]["search_term"] == "beans"
    assert cleaned[1]["approx_unit"] == "g"


def test_clean_rejects_blank_term():
    with pytest.raises(HTTPException) as exc:
        _clean_custom_ingredients([CustomIngredient(search_term="   ", quantity=1)])
    assert exc.value.status_code == 400


def test_clean_folds_egg_into_each():
    cleaned = _clean_custom_ingredients([CustomIngredient(search_term="eggs", quantity=6, unit="egg")])
    assert cleaned[0]["unit"] == "each"


def test_clean_rejects_duplicates_case_insensitive():
    rows = [
        CustomIngredient(search_term="Rice", quantity=1, unit="cup"),
        CustomIngredient(search_term="rice", quantity=2, unit="cup"),
    ]
    with pytest.raises(HTTPException) as exc:
        _clean_custom_ingredients(rows)
    assert "Duplicate ingredient" in exc.value.detail


# ── Custom dish validation ────────────────────────────────────────────────────

def _dish(name="my hash", base=4, terms=("beef mince",)):
    return CustomDish(
        dish_name=name,
        base_portions=base,
        ingredients=[CustomIngredient(search_term=t, quantity=100, unit="g") for t in terms],
    )


def test_validate_requires_name():
    with pytest.raises(HTTPException):
        _validate_custom_dish(_dish(name="   "))


def test_validate_requires_ingredients():
    with pytest.raises(HTTPException):
        _validate_custom_dish(CustomDish(dish_name="empty", base_portions=4, ingredients=[]))


def test_validate_clamps_base_portions():
    name, base, _ = _validate_custom_dish(_dish(base=999))
    assert (name, base) == ("my hash", 24)
    _, base_lo, _ = _validate_custom_dish(_dish(base=-5))
    assert base_lo == 1
    # 0 is falsy → falls back to the default base of 4.
    _, base_zero, _ = _validate_custom_dish(_dish(base=0))
    assert base_zero == 4


# ── Portions scaling ──────────────────────────────────────────────────────────

def test_scale_noop_when_equal():
    dish = {"dish_name": "x", "portion": 4,
            "ingredients": [{"quantity": 500, "unit": "g", "search_term": "mince"}]}
    out = _scale_ingredients_to_portions(dict(dish), 4)
    assert out["ingredients"][0]["quantity"] == 500


def test_scale_up_and_down_including_approx():
    dish = {"dish_name": "x", "portion": 4, "ingredients": [
        {"quantity": 500, "unit": "g", "search_term": "mince"},
        {"quantity": 1, "unit": "can", "search_term": "tomatoes",
         "approx_quantity": 400, "approx_unit": "g"},
    ]}
    up = _scale_ingredients_to_portions(json.loads(json.dumps(dish)), 6)
    assert up["portion"] == 6
    assert up["ingredients"][0]["quantity"] == 750.0
    assert up["ingredients"][1]["approx_quantity"] == 600.0
    down = _scale_ingredients_to_portions(json.loads(json.dumps(dish)), 2)
    assert down["ingredients"][0]["quantity"] == 250.0


def test_scale_leaves_string_legacy_rows_alone():
    dish = {"dish_name": "x", "portion": 4, "ingredients": ["beef mince"]}
    out = _scale_ingredients_to_portions(dish, 8)
    assert out["ingredients"] == ["beef mince"]
    assert out["_scale_factor"] == 2.0


# ── dishes.json upsert (monkeypatched DATA_DIR) ───────────────────────────────

def test_save_dish_round_trip(tmp_path, monkeypatch):
    seed = {"spaghetti bolognese": {"dish_name": "spaghetti bolognese", "portion": 4,
                                    "ingredients": []}}
    (tmp_path / "dishes.json").write_text(json.dumps(seed), encoding="utf-8")
    monkeypatch.setattr(web_main, "DATA_DIR", tmp_path)

    req = web_main.SaveDishRequest(
        dish_name="My Test Hash",
        base_portions=2,
        ingredients=[CustomIngredient(search_term="kumara", quantity=600, unit="g"),
                     CustomIngredient(search_term="chorizo", quantity=1, unit="pk",
                                      approx_quantity=200, approx_unit="g")],
    )
    first = asyncio.run(web_main.save_dish(req))
    assert first["ok"] is True and first["updated"] is False and first["key"] == "my test hash"

    stored = json.loads((tmp_path / "dishes.json").read_text(encoding="utf-8"))
    entry = stored["my test hash"]
    assert entry["portion"] == 2
    assert entry["ingredients"][0] == {"quantity": 600.0, "unit": "g", "search_term": "kumara"}
    # Alias normalised on save; original curated dish untouched.
    assert entry["ingredients"][1]["unit"] == "pack"
    assert "spaghetti bolognese" in stored

    second = asyncio.run(web_main.save_dish(req))
    assert second["updated"] is True
