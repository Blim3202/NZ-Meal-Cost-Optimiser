"""Tests for NZMealOptimiser.llm.llm_utils — structural validation and
quantity-scaling helpers.

Covers branches of ``parse_and_validate`` and the ``approx_quantity`` /
``approx_unit`` fallback path in ``parse_optimiser_columns`` (the load-bearing
scaler for the LLM Recipe Builder + /optimise/{id}/reapply).
"""
import pytest

from NZMealOptimiser.llm.llm_utils import (
    LLMParseError,
    parse_and_validate,
    parse_optimiser_columns,
)


# ── parse_and_validate: structural branches ──────────────────────────────────

def test_parse_and_validate_rejects_non_dict_payload():
    with pytest.raises(LLMParseError, match="Expected dict"):
        parse_and_validate(["not", "a", "dict"])


def test_parse_and_validate_rejects_missing_dish_name():
    with pytest.raises(LLMParseError, match="dish_name"):
        parse_and_validate({"portion": 4, "ingredients": [{"quantity": 1, "unit": "g", "search_term": "x"}]})


def test_parse_and_validate_rejects_string_portion():
    with pytest.raises(LLMParseError, match="portion"):
        parse_and_validate({"dish_name": "x", "portion": "4", "ingredients": [{"quantity": 1, "unit": "g", "search_term": "x"}]})


def test_parse_and_validate_rejects_missing_ingredients():
    with pytest.raises(LLMParseError, match="ingredients"):
        parse_and_validate({"dish_name": "x", "portion": 4})


def test_parse_and_validate_rejects_missing_quantity_field():
    with pytest.raises(LLMParseError, match="missing 'quantity'"):
        parse_and_validate({
            "dish_name": "x", "portion": 4,
            "ingredients": [{"unit": "g", "search_term": "x"}],
        })


def test_parse_and_validate_rejects_non_string_unit():
    with pytest.raises(LLMParseError, match="unit"):
        parse_and_validate({
            "dish_name": "x", "portion": 4,
            "ingredients": [{"quantity": 1, "unit": 42, "search_term": "x"}],
        })


# ── parse_optimiser_columns: approx_quantity/approx_unit fallback ───────────

def test_parse_optimiser_columns_count_vs_weight_with_approx_falls_back():
    """Recipe needs 2 stalks of celery; pack is 500g. 'stalk' is not a
    recognised unit so the code falls back to ingredient_approx_quantity
    (=80g per stalk in this case) and computes scaling_ratio = 80/500.
    status='approximate'.

    The scaler uses the approx_quantity directly (80g), not the
    recipe-quantity × approx-quantity (2×80=160g), because the per-stalk
    weight is what we'd actually buy at the supermarket.
    """
    row = {
        "search_ingredient": "celery",
        "returned_ingredient": "Celery",
        "ingredient_quantity": 2,
        "ingredient_measurement": "stalk",
        "ingredient_approx_quantity": 80,
        "ingredient_approx_unit": "g",
        "per_unit_price": 0.6,
        "quantity": 500,
        "measurement_unit": "g",
        "price": 3.0,
    }
    out = parse_optimiser_columns(row)
    assert out["status"] == "approximate"
    assert out["unit_approximate"] is False  # same category (g vs g)
    assert out["scaling_ratio"] == pytest.approx(0.16, abs=0.001)
    assert out["used_price"] == pytest.approx(0.48, abs=0.01)
    assert out["purchase_quantity"] == 1
    assert out["purchase_price"] == pytest.approx(3.0, abs=0.01)


def test_parse_optimiser_columns_count_vs_weight_no_approx_is_incompatible():
    """Same scenario but with no approx fallback: status='incompatible_units'."""
    row = {
        "search_ingredient": "celery",
        "returned_ingredient": "Celery",
        "ingredient_quantity": 2,
        "ingredient_measurement": "stalk",
        "ingredient_approx_quantity": None,
        "ingredient_approx_unit": None,
        "per_unit_price": 0.6,
        "quantity": 500,
        "measurement_unit": "g",
        "price": 3.0,
    }
    out = parse_optimiser_columns(row)
    assert out["status"] == "incompatible_units"
    assert out["scaling_ratio"] is None
    assert out["used_price"] is None
    assert out["purchase_price"] is None
    assert out["purchase_quantity"] == 0
