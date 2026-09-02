"""Tests for the store-cost placeholder rows: ingredients with nothing usable
at a store (zero results, or products that are all unit-incompatible) must
appear as blank rows (status "not_found") in best_per_ingredient, while
totals, matched counts, and basket ranking stay truthful.

Targets the pure _build_store_costs helper extracted from the pipeline.
"""
from NZMealOptimiser.web.main import _build_store_costs

TERMS = ["beef mince", "eggs", "sauce pack"]

ING_LOOKUP = {
    "beef mince": {"quantity": 500, "unit": "g", "search_term": "beef mince"},
    "eggs": {"quantity": 6, "unit": "each", "search_term": "eggs"},
    "sauce pack": {"quantity": 1, "unit": "pack", "approx_quantity": 250,
                   "approx_unit": "ml", "search_term": "sauce pack"},
}


def _row(company, store, term, sku, used_price=None, units_match=True, status="ok"):
    return {
        "company": company, "store": store, "search_ingredient": term, "sku": sku,
        "returned_ingredient": f"{term} product {sku}", "brand": "Budget",
        "price": 9.0, "quantity": 500, "measurement_unit": "g",
        "ingredient_quantity": ING_LOOKUP[term]["quantity"],
        "ingredient_measurement": ING_LOOKUP[term]["unit"],
        "ingredient_approx_quantity": ING_LOOKUP[term].get("approx_quantity"),
        "ingredient_approx_unit": ING_LOOKUP[term].get("approx_unit"),
        "used_price": used_price, "purchase_quantity": 1, "purchase_price": 9.0,
        "units_match": units_match, "status": status,
    }


def _fixture():
    all_rows = [
        # Store A: beef mince has a valid cheapest product + a dud row.
        _row("PaknSave", "Store A", "beef mince", "A1", used_price=5.0),
        _row("PaknSave", "Store A", "beef mince", "A2", used_price=None),
        # Store A: eggs returned products but every one is unit-incompatible.
        _row("PaknSave", "Store A", "eggs", "A3", used_price=None),
        _row("PaknSave", "Store A", "eggs", "A4", used_price=None),
        # sauce pack @ Store A: no rows at all (no_match outcome below).
    ]
    outcomes = {
        ("PaknSave", "sid-a", "Store A", "beef mince"): {"status": "ok", "products": 2, "detail": ""},
        ("PaknSave", "sid-a", "Store A", "eggs"): {"status": "ok", "products": 2, "detail": ""},
        ("PaknSave", "sid-a", "Store A", "sauce pack"): {"status": "no_match", "products": 0, "detail": "no products returned"},
        ("NewWorld", "sid-b", "Store B", "beef mince"): {"status": "error", "products": 0, "detail": "Timeout"},
        ("NewWorld", "sid-b", "Store B", "eggs"): {"status": "error", "products": 0, "detail": "Timeout"},
        ("NewWorld", "sid-b", "Store B", "sauce pack"): {"status": "error", "products": 0, "detail": "Timeout"},
    }
    store_geo = {("PaknSave", "Store A"): {"lat": -36.9, "lon": 174.8, "distance_km": 1.2}}
    return _build_store_costs(TERMS, ING_LOOKUP, all_rows, outcomes, store_geo)


def _by_name(store_costs, name):
    return next(sc for sc in store_costs if sc["store"] == name)


def test_dead_store_still_gets_a_card():
    costs = _fixture()
    assert [sc["store"] for sc in costs] == ["Store B", "Store A"]  # both incomplete: $0.00 first
    dead = _by_name(costs, "Store B")
    assert dead["company"] == "NewWorld"
    assert dead["ingredients_matched"] == 0
    assert dead["complete"] is False
    assert dead["total_used_cost"] == 0.0
    assert [r["search_ingredient"] for r in dead["best_per_ingredient"]] == TERMS
    assert all(r["status"] == "not_found" for r in dead["best_per_ingredient"])
    assert len(dead["issues"]) == 3  # one per failed search


def test_partial_store_placeholder_rows():
    costs = _fixture()
    store = _by_name(costs, "Store A")
    assert store["ingredients_matched"] == 1
    assert store["complete"] is False
    assert store["total_used_cost"] == 5.0  # placeholders add nothing
    assert store["lat"] == -36.9

    rows = {r["search_ingredient"]: r for r in store["best_per_ingredient"]}
    assert [r["search_ingredient"] for r in store["best_per_ingredient"]] == TERMS  # requested order

    # Real pick unchanged.
    beef = rows["beef mince"]
    assert beef["returned_ingredient"] == "beef mince product A1"
    assert beef["used_price"] == 5.0
    assert beef["status"] == "ok"

    # All-incompatible ingredient -> blank row carrying the recipe requirement.
    eggs = rows["eggs"]
    assert eggs["status"] == "not_found"
    assert eggs["used_price"] is None and eggs["purchase_price"] is None
    assert eggs["returned_ingredient"] == "" and eggs["brand"] == "" and eggs["price"] == ""
    assert eggs["quantity"] == "" and eggs["measurement_unit"] == ""
    assert eggs["ingredient_quantity"] == 6 and eggs["ingredient_measurement"] == "each"

    # Zero-result ingredient -> blank row, approx fallback fields preserved.
    sauce = rows["sauce pack"]
    assert sauce["status"] == "not_found"
    assert sauce["ingredient_quantity"] == 1 and sauce["ingredient_measurement"] == "pack"
    assert sauce["ingredient_approx_quantity"] == 250 and sauce["ingredient_approx_unit"] == "ml"


def test_issues_banner_still_explains_why():
    costs = _fixture()
    issues = {(i["search_ingredient"], i["status"]) for i in _by_name(costs, "Store A")["issues"]}
    assert issues == {("eggs", "incompatible_units"), ("sauce pack", "no_match")}


def test_placeholder_shape_matches_real_rows():
    costs = _fixture()
    store = _by_name(costs, "Store A")
    real = next(r for r in store["best_per_ingredient"] if r["search_ingredient"] == "beef mince")
    blank = next(r for r in store["best_per_ingredient"] if r["status"] == "not_found")
    assert set(blank.keys()) == set(real.keys())


def test_complete_store_unchanged_and_wins():
    """A fully matched store still ranks first regardless of cost."""
    rows = [_row("PaknSave", "Full A", t, f"F-{i}", used_price=20.0) for i, t in enumerate(TERMS)]
    rows += [
        _row("NewWorld", "Store A", "beef mince", "A1", used_price=5.0),
        _row("NewWorld", "Store A", "eggs", "A3", used_price=None),
    ]
    outcomes = {("PaknSave", "sid-f", "Full A", t): {"status": "ok", "products": 1, "detail": ""} for t in TERMS}
    outcomes.update({
        ("NewWorld", "sid-a", "Store A", "beef mince"): {"status": "ok", "products": 1, "detail": ""},
        ("NewWorld", "sid-a", "Store A", "eggs"): {"status": "ok", "products": 1, "detail": ""},
        ("NewWorld", "sid-a", "Store A", "sauce pack"): {"status": "no_match", "products": 0, "detail": "no products returned"},
    })
    costs = _build_store_costs(TERMS, ING_LOOKUP, rows, outcomes, {})
    assert len(costs) == 2
    assert costs[0]["store"] == "Full A"
    assert costs[0]["complete"] is True
    assert costs[0]["total_used_cost"] == 60.0
