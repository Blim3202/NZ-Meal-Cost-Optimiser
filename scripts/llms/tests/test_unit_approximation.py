"""Quick sanity checks for the volume↔weight approximation logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from scripts.llms.llm_utils import parse_optimizer_columns


def test_volume_vs_weight_is_approximate():
    r = parse_optimizer_columns({
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
    r = parse_optimizer_columns({
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
    r = parse_optimizer_columns({
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
    r = parse_optimizer_columns({
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
    r = parse_optimizer_columns({
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


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
