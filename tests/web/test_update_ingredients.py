"""Tests for POST /optimise/{job_id}/update_ingredients — the post-run partial
refresh behind the dashboard's "Update ingredient prices" button: server-side
diffing of builder edits against a completed run's cached ingredients,
re-querying ONLY added/renamed terms across the cached stores, dropping
removed terms, purely rescaling quantity-only edits (zero network), preserving
user filter rules, and advancing job.result + pipeline_cache.

No supermarket network calls — _fetch_ingredient/_make_authenticated_api are
monkeypatched.
"""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from NZMealOptimiser.web import main as web_main
from NZMealOptimiser.web.main import (
    CustomDish,
    CustomIngredient,
    DishRequest,
    JobState,
    _diff_run_ingredients,
)

# Cached run: Store A sells 500 g packs; recipe needs 250 g beef mince
# ($10 pack -> $5.00 used) and 100 g onion ($4 pack -> $0.80 used).
TERMS = ["beef mince", "onion"]
STORE_KEY = ("PaknSave", "sid-a", "Store A")


def _pack_row(term, sku, price, title):
    """A priced 500 g pack row pre-scaling (used_price computed by enrichment)."""
    return {
        "company": "PaknSave", "store": "Store A", "store_id": "sid-a",
        "sku": sku, "search_ingredient": term, "returned_ingredient": title,
        "brand": "Test Brand", "price": price,
        "quantity": 500, "measurement_unit": "g",
    }


def _completed_job(monkeypatch):
    job = JobState(DishRequest(dish="test dish", address="Somewhere, NZ", portions=4))
    job.status = "complete"
    job.pipeline_cache = {
        "rows": [
            _pack_row("beef mince", "s1", 10.0, "Budget Beef Mince 500g"),
            _pack_row("onion", "s2", 4.0, "Brown Onion 1kg"),
        ],
        "search_terms": list(TERMS),
        "ing_lookup": {
            "beef mince": {"search_term": "beef mince", "quantity": 250, "unit": "g"},
            "onion": {"search_term": "onion", "quantity": 100, "unit": "g"},
        },
        "outcomes": {
            (*STORE_KEY, "beef mince"): {"status": "ok", "products": 1, "detail": ""},
            (*STORE_KEY, "onion"): {"status": "ok", "products": 1, "detail": ""},
        },
        "store_geo": {("PaknSave", "Store A"): {"lat": -36.0, "lon": 174.0, "distance_km": 1.0}},
        "companies": ["PaknSave"],
        "dish_name": "test dish",
        "source": "custom",
        "origin": {"lat": -36.0, "lon": 174.0, "source": "geocoded"},
        "regions": {("PaknSave", "sid-a"): "NI"},
        "stores": [STORE_KEY],
    }
    job.result = None
    monkeypatch.setitem(web_main.JOBS, job.id, job)
    return job


@pytest.fixture()
def client():
    return TestClient(web_main.app)


def _install_fake_fetch(monkeypatch, calls):
    async def fake_fetch_ingredient(company, api, store_id, store_name, ingredient, region="", exclude_non_food=True):
        calls.append((company, store_id, store_name, ingredient, region))
        return [_pack_row(ingredient, f"new-{ingredient}", 10.0, f"Fresh {ingredient} 500g")]
    monkeypatch.setattr(web_main, "_fetch_ingredient", fake_fetch_ingredient)
    monkeypatch.setattr(web_main, "_make_authenticated_api", lambda cls: object())


def _dish(*ingredients, portions=4):
    return CustomDish(
        dish_name="test dish",
        base_portions=portions,
        ingredients=[CustomIngredient(**ing) for ing in ingredients],
    )


# ── Diff helper ───────────────────────────────────────────────────────────────

def test_diff_classifies_add_remove_and_qty_changes():
    cache = {
        "search_terms": ["beef mince", "onion"],
        "ing_lookup": {
            "beef mince": {"quantity": 250, "unit": "g", "includes": ["mince"]},
            "onion": {"quantity": 100, "unit": "g"},
        },
    }
    new_lookup = {
        "beef mince": {"search_term": "beef mince", "quantity": 500, "unit": "g"},
        "carrot": {"search_term": "carrot", "quantity": 1, "unit": "bag"},
    }
    diff = _diff_run_ingredients(cache, new_lookup)
    assert diff["added"] == ["carrot"]
    assert diff["removed"] == ["onion"]
    assert diff["kept"] == ["beef mince"]
    assert diff["qty_changed"] == ["beef mince"]


def test_diff_qty_only_edit_detected_without_term_change():
    cache = {
        "search_terms": ["beef mince"],
        "ing_lookup": {"beef mince": {"quantity": 250, "unit": "g"}},
    }
    new_lookup = {"beef mince": {"search_term": "beef mince", "quantity": 375, "unit": "g"}}
    diff = _diff_run_ingredients(cache, new_lookup)
    assert diff["added"] == [] and diff["removed"] == []
    assert diff["kept"] == ["beef mince"] and diff["qty_changed"] == ["beef mince"]


def test_diff_no_changes_returns_empty_lists():
    """An identical builder payload diffs to all-empty lists (no-op path)."""
    cache = {
        "search_terms": ["beef mince", "onion"],
        "ing_lookup": {
            "beef mince": {"quantity": 250, "unit": "g"},
            "onion": {"quantity": 100, "unit": "g"},
        },
    }
    new_lookup = {
        "beef mince": {"search_term": "beef mince", "quantity": 250, "unit": "g"},
        "onion": {"search_term": "onion", "quantity": 100, "unit": "g"},
    }
    diff = _diff_run_ingredients(cache, new_lookup)
    assert diff["added"] == []
    assert diff["removed"] == []
    assert diff["kept"] == ["beef mince", "onion"]
    assert diff["qty_changed"] == []


# ── Endpoint behaviour ────────────────────────────────────────────────────────

def test_added_term_is_queried_per_cached_store(client, monkeypatch):
    job = _completed_job(monkeypatch)
    calls = []
    _install_fake_fetch(monkeypatch, calls)

    response = client.post(f"/optimise/{job.id}/update_ingredients", json={
        "custom_dish": _dish(
            {"search_term": "beef mince", "quantity": 250, "unit": "g"},
            {"search_term": "onion", "quantity": 100, "unit": "g"},
            {"search_term": "chicken thigh", "quantity": 300, "unit": "g"},
        ).model_dump(),
        "ingredient_filters": {},
    })
    assert response.status_code == 200
    data = response.json()

    # ONLY the new term was re-queried, against the original run's store.
    assert calls == [("PaknSave", "sid-a", "Store A", "chicken thigh", "NI")]

    terms = {r["search_ingredient"] for r in data["rows"]}
    assert terms == {"beef mince", "onion", "chicken thigh"}
    # Winner math: $5.00 + $0.80 + ($10 pack @ 300/500 = $6.00).
    assert data["store_costs"][0]["total_used_cost"] == 11.80
    assert data["store_costs"][0]["ingredients_total"] == 3

    # Cache advanced so previews/reapplies/further updates see fresh state.
    assert job.pipeline_cache["search_terms"] == ["beef mince", "onion", "chicken thigh"]
    assert ("PaknSave", "sid-a", "Store A", "chicken thigh") in job.pipeline_cache["outcomes"]
    assert job.result is not None and len(job.result.rows) == len(data["rows"])


def test_removed_term_dropped_with_no_network_calls(client, monkeypatch):
    job = _completed_job(monkeypatch)
    calls = []
    _install_fake_fetch(monkeypatch, calls)

    response = client.post(f"/optimise/{job.id}/update_ingredients", json={
        "custom_dish": _dish({"search_term": "beef mince", "quantity": 250, "unit": "g"}).model_dump(),
    })
    assert response.status_code == 200
    data = response.json()

    assert calls == []  # removals never hit the APIs
    assert {r["search_ingredient"] for r in data["rows"]} == {"beef mince"}
    assert job.pipeline_cache["search_terms"] == ["beef mince"]
    assert all(key[3] != "onion" for key in job.pipeline_cache["outcomes"])
    assert data["store_costs"][0]["ingredients_total"] == 1


def test_quantity_only_edit_rescales_without_network(client, monkeypatch):
    job = _completed_job(monkeypatch)
    calls = []
    _install_fake_fetch(monkeypatch, calls)

    response = client.post(f"/optimise/{job.id}/update_ingredients", json={
        "custom_dish": _dish(
            {"search_term": "beef mince", "quantity": 750, "unit": "g"},  # needs 1.5 packs
            {"search_term": "onion", "quantity": 100, "unit": "g"},
        ).model_dump(),
    })
    assert response.status_code == 200
    data = response.json()

    assert calls == []  # pure rescale — zero supermarket queries
    store = data["store_costs"][0]
    beef = next(b for b in store["best_per_ingredient"] if b["search_ingredient"] == "beef mince")
    assert beef["used_price"] == 15.00  # 750/500 * $10
    assert beef["purchase_quantity"] == 2
    assert store["total_used_cost"] == 15.80


def test_rename_requeries_new_term_and_carries_filters(client, monkeypatch):
    job = _completed_job(monkeypatch)
    calls = []
    _install_fake_fetch(monkeypatch, calls)

    response = client.post(f"/optimise/{job.id}/update_ingredients", json={
        "custom_dish": _dish(
            {"search_term": "beef mince", "quantity": 250, "unit": "g"},
            {"search_term": "shallot", "quantity": 100, "unit": "g"},  # renamed from onion
        ).model_dump(),
        "ingredient_filters": {"shallot": {"includes": ["shallot"], "excludes": []}},
    })
    assert response.status_code == 200
    data = response.json()

    assert calls == [("PaknSave", "sid-a", "Store A", "shallot", "NI")]
    terms = {r["search_ingredient"] for r in data["rows"]}
    assert terms == {"beef mince", "shallot"}  # onion rows gone
    # The client's rules were merged onto the NEW term — nothing regenerated.
    lookup = job.pipeline_cache["ing_lookup"]
    assert lookup["shallot"]["includes"] == ["shallot"]
    assert "onion" not in lookup


def test_unknown_filter_terms_reported_not_fatal(client, monkeypatch):
    job = _completed_job(monkeypatch)
    _install_fake_fetch(monkeypatch, [])

    response = client.post(f"/optimise/{job.id}/update_ingredients", json={
        "custom_dish": _dish(
            {"search_term": "beef mince", "quantity": 250, "unit": "g"},
            {"search_term": "onion", "quantity": 100, "unit": "g"},
        ).model_dump(),
        "ingredient_filters": {"ghost term": {"includes": ["x"], "excludes": []}},
    })
    assert response.status_code == 200
    notes = [e["text"] for e in job.events if "unknown filter terms" in e["text"]]
    assert any("ghost term" in text for text in notes)


def test_endpoint_guards(client, monkeypatch):
    job = _completed_job(monkeypatch)
    body = {"custom_dish": _dish({"search_term": "beef mince", "quantity": 250, "unit": "g"}).model_dump()}

    assert client.post("/optimise/nope/update_ingredients", json=body).status_code == 404

    queued = JobState(DishRequest(dish="x", address="y"))
    monkeypatch.setitem(web_main.JOBS, queued.id, queued)
    assert client.post(f"/optimise/{queued.id}/update_ingredients", json=body).status_code == 409

    job.pipeline_cache = None
    assert client.post(f"/optimise/{job.id}/update_ingredients", json=body).status_code == 409
    assert "no cached products" in client.post(
        f"/optimise/{job.id}/update_ingredients", json=body
    ).json()["detail"]


def test_blank_recipe_rejected(client, monkeypatch):
    job = _completed_job(monkeypatch)
    _install_fake_fetch(monkeypatch, [])
    response = client.post(f"/optimise/{job.id}/update_ingredients", json={
        "custom_dish": _dish().model_dump(),
    })
    assert response.status_code == 400
