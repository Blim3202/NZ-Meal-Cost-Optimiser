"""Quick sanity checks for the volume↔weight approximation logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from NZMealOptimiser.llm.llm_utils import parse_optimiser_columns


def test_volume_vs_weight_is_approximate():
    r = parse_optimiser_columns({
        "search_ingredient": "baking soda",
        "returned_ingredient": "Baking Soda",
        "quantity": 500,
        "measurement_unit": "g",
        "price": 2.39,
        "per_unit_price": 0.48,
        "ingredient_quantity": 1.0,
        "ingredient_measurement": "tsp",
    })
    assert r["status"] == "approximate"
    assert r["unit_approximate"] is True
    assert r["used_price"] is not None
    assert r["purchase_quantity"] == 1
    assert r["purchase_price"] == 2.39


def test_volume_vs_volume_is_not_approximate():
    r = parse_optimiser_columns({
        "search_ingredient": "vanilla",
        "returned_ingredient": "Vanilla Extract",
        "quantity": 50,
        "measurement_unit": "ml",
        "price": 4.39,
        "per_unit_price": 0.88,
        "ingredient_quantity": 1.0,
        "ingredient_measurement": "tsp",
    })
    assert r["status"] == "ok"
    assert r["unit_approximate"] is False
    assert r["used_price"] is not None


def test_weight_vs_weight_is_not_approximate():
    r = parse_optimiser_columns({
        "search_ingredient": "flour",
        "returned_ingredient": "Plain Flour",
        "quantity": 1500,
        "measurement_unit": "g",
        "price": 1.69,
        "per_unit_price": 0.11,
        "ingredient_quantity": 225.0,
        "ingredient_measurement": "g",
    })
    assert r["status"] == "ok"
    assert r["unit_approximate"] is False


def test_count_vs_weight_is_genuinely_incompatible():
    r = parse_optimiser_columns({
        "search_ingredient": "egg",
        "quantity": 500,
        "measurement_unit": "g",
        "price": 2.99,
        "ingredient_quantity": 1.0,
        "ingredient_measurement": "unit",
    })
    assert r["status"] == "incompatible_units"
    assert r["unit_approximate"] is False
    assert r["used_price"] is None


def test_weight_vs_volume_is_approximate():
    r = parse_optimiser_columns({
        "search_ingredient": "oil",
        "quantity": 500,
        "measurement_unit": "ml",
        "price": 3.50,
        "ingredient_quantity": 30.0,
        "ingredient_measurement": "g",
    })
    assert r["status"] == "approximate"
    assert r["unit_approximate"] is True
    assert r["used_price"] is not None


def test_incompatible_falls_back_to_approx():
    """Recipe says '1 medium onion' (approx 150g) vs pack '500g' — should use approx."""
    r = parse_optimiser_columns({
        "search_ingredient": "onion",
        "returned_ingredient": "Red Onion",
        "quantity": 500,
        "measurement_unit": "g",
        "price": 1.99,
        "per_unit_price": 0.40,
        "ingredient_quantity": 1.0,
        "ingredient_measurement": "medium",
        "ingredient_approx_quantity": 150,
        "ingredient_approx_unit": "g",
    })
    assert r["status"] == "approximate"
    assert r["unit_approximate"] is False  # no 1ml≈1g cross-category; just approx weight
    assert r["scaling_ratio"] is not None
    assert r["scaling_ratio"] == round(150 / 500, 4)  # 0.3
    assert r["used_price"] is not None
    assert r["purchase_quantity"] == 1
    assert r["purchase_price"] == 1.99


def test_incompatible_no_approx_returns_none():
    """No approx fields available — should remain incompatible_units."""
    r = parse_optimiser_columns({
        "search_ingredient": "onion",
        "quantity": 500,
        "measurement_unit": "g",
        "price": 1.99,
        "ingredient_quantity": 1.0,
        "ingredient_measurement": "medium",
    })
    assert r["status"] == "incompatible_units"
    assert r["used_price"] is None
    assert r["purchase_price"] is None


def test_incompatible_approx_cross_category():
    """'1 can' → approx 400ml, pack is 500ml — should be ok (matching ml category)."""
    r = parse_optimiser_columns({
        "search_ingredient": "canned tomatoes",
        "returned_ingredient": "Canned Tomatoes",
        "quantity": 500,
        "measurement_unit": "ml",
        "price": 2.50,
        "per_unit_price": 0.50,
        "ingredient_quantity": 1.0,
        "ingredient_measurement": "can",
        "ingredient_approx_quantity": 400,
        "ingredient_approx_unit": "ml",
    })
    assert r["status"] == "approximate"
    assert r["unit_approximate"] is False
    assert r["scaling_ratio"] == round(400 / 500, 4)  # 0.8
    assert r["used_price"] is not None


def test_incompatible_approx_mixed_category():
    """'1 can coconut milk' → approx 400ml, pack is 400g — cross-category 1ml≈1g."""
    r = parse_optimiser_columns({
        "search_ingredient": "coconut milk",
        "returned_ingredient": "Coconut Milk",
        "quantity": 400,
        "measurement_unit": "g",
        "price": 3.20,
        "per_unit_price": 0.80,
        "ingredient_quantity": 1.0,
        "ingredient_measurement": "can",
        "ingredient_approx_quantity": 400,
        "ingredient_approx_unit": "ml",
    })
    assert r["status"] == "approximate"
    assert r["unit_approximate"] is True  # ml vs g cross-category
    assert r["scaling_ratio"] == round(400 / 400, 4)  # 1.0
    assert r["used_price"] is not None


def test_incompatible_approx_wrong_category():
    """Approx unit is count but pack is weight — still incompatible."""
    r = parse_optimiser_columns({
        "search_ingredient": "onion",
        "quantity": 500,
        "measurement_unit": "g",
        "price": 1.99,
        "ingredient_quantity": 1.0,
        "ingredient_measurement": "medium",
        "ingredient_approx_quantity": 1,
        "ingredient_approx_unit": "unit",
    })
    assert r["status"] == "incompatible_units"
    assert r["used_price"] is None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
