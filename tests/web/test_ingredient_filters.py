"""Tests for the ingredient include/exclude filter feature: the Levenshtein
matcher ported from exploration/llm/validate_dish_filters.py, request-level
filter cleaning/merging, row validity stamping, store-cost gating (strict —
an over-eager filter empties a search rather than being relaxed), and the
post-run POST /optimise/{id}/reapply recalculation endpoint.

No supermarket network calls.
"""
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from NZMealOptimiser.pricing.optimiser_utils import (
    contains_word,
    levenshtein,
    matches_ingredient_filters,
    word_matches,
)
from NZMealOptimiser.web import main as web_main
from NZMealOptimiser.web.main import (
    IngredientFilterSet,
    JobState,
    DishRequest,
    _apply_ingredient_validity,
    _build_store_costs,
    _clean_ingredient_filters,
    _merge_request_filters,
)


# ── Levenshtein matcher ───────────────────────────────────────────────────────

def test_levenshtein_distances():
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3
    assert levenshtein("same", "same") == 0


def test_word_matches_ratio_and_exact():
    assert word_matches("carrots", "carrot") is True  # 1 edit / 7 chars <= .35
    assert word_matches("tomatoes", "tomato") is True
    assert word_matches("beef", "pork") is False
    assert word_matches("mince", "mince") is True


def test_contains_word_singular_plural():
    assert contains_word("Fresh Carrots 1kg", "carrot") is True
    assert contains_word("Diced Tomato Cans", "tomatoes") is True


def test_contains_word_multi_word_needs_all():
    assert contains_word("Butter Chicken Sauce 500g", "butter chicken") is True
    assert contains_word("Chicken Sauce 500g", "butter chicken") is False


def test_contains_word_blank_needle_vacuous():
    assert contains_word("Anything", "") is True
    assert contains_word("Anything", "   ") is True


@pytest.mark.parametrize("returned,includes,excludes,expected", [
    ("Premium Beef Mince 500g", ["mince"], ["pork", "chicken"], True),
    ("NZ Diced Beef 400g", ["mince"], [], False),           # include missing
    ("Pork Mince 500g", ["mince"], ["pork"], False),        # exclude hit
    ("Anything At All", [], ["nope"], True),                # excludes only
    ("Garlic Powder 100g", ["garlic"], ["powder"], False),
    # AND semantics: EVERY include keyword must match the title.
    ("Beef Mince Premium 500g", ["beef", "mince"], [], True),
    ("Beef Mince Premium 500g", ["beef", "lamb"], [], False),   # one include missing
    ("Chicken Thigh 500g", ["chicken", "thigh", "breast"], [], False),
])
def test_matches_ingredient_filters(returned, includes, excludes, expected):
    passed, _ = matches_ingredient_filters(returned, includes, excludes)
    assert passed is expected


def test_matches_ingredient_filters_reason_strings():
    ok, reason = matches_ingredient_filters("Beef Mince", ["mince"], [])
    assert ok and reason == ""
    _, inc_reason = matches_ingredient_filters("Diced Beef", ["mince"], [])
    assert "INCLUDE" in inc_reason and "mince" in inc_reason
    # AND semantics: only the genuinely missing keywords are reported.
    _, multi_reason = matches_ingredient_filters("Beef Mince", ["beef", "lamb"], [])
    assert "INCLUDE" in multi_reason and "lamb" in multi_reason
    _, exc_reason = matches_ingredient_filters("Pork Mince", ["mince"], ["pork"])
    assert "EXCLUDE" in exc_reason


# ── Filter cleaning ───────────────────────────────────────────────────────────

def test_clean_strips_drops_empty_sets():
    raw = {
        "beef mince": IngredientFilterSet(includes=[" mince ", ""], excludes=["pork"]),
        "rice": IngredientFilterSet(),  # empty set -> dropped entirely
        "  ": IngredientFilterSet(includes=["x"]),  # blank term -> dropped
    }
    cleaned = _clean_ingredient_filters(raw)
    assert cleaned == {"beef mince": {"includes": ["mince"], "excludes": ["pork"]}}


def test_clean_accepts_none():
    assert _clean_ingredient_filters(None) == {}


def test_clean_rejects_overlong_keyword():
    raw = {"onion": IngredientFilterSet(excludes=["x" * 41])}
    with pytest.raises(HTTPException) as exc:
        _clean_ingredient_filters(raw)
    assert exc.value.status_code == 400
    # Exactly at the cap is fine.
    ok = _clean_ingredient_filters({"onion": IngredientFilterSet(excludes=["x" * 40])})
    assert ok["onion"]["excludes"] == ["x" * 40]


def test_clean_caps_keyword_count():
    words = [f"w{i}" for i in range(12)]
    cleaned = _clean_ingredient_filters({"onion": IngredientFilterSet(excludes=words)})
    assert len(cleaned["onion"]["excludes"]) == web_main.MAX_FILTER_KEYWORDS


# ── Merging onto resolved ingredients ────────────────────────────────────────

def test_merge_case_insensitive_reports_unmatched():
    lookup = {
        "beef mince": {"search_term": "beef mince"},
        "Rice": {"search_term": "Rice"},
    }
    matched, unmatched = _merge_request_filters(lookup, {
        "BEEF MINCE": {"includes": ["mince"], "excludes": []},
        "rice": {"includes": [], "excludes": ["flour"]},
        "ghost term": {"includes": ["boo"], "excludes": []},
    })
    assert matched == 2
    assert unmatched == ["ghost term"]
    assert lookup["beef mince"]["includes"] == ["mince"]
    assert lookup["Rice"]["excludes"] == ["flour"]


# ── Validity stamping ────────────────────────────────────────────────────────

def _row(term, title, price=None):
    return {"search_ingredient": term, "returned_ingredient": title, "used_price": price}


def test_apply_validity_flags_rows():
    rows = [
        _row("beef mince", "Premium Beef Mince 500g"),
        _row("beef mince", "Pork Mince 500g"),
        _row("onion", "Brown Onion 1kg"),  # no filters -> always valid
    ]
    lookup = {
        "beef mince": {"includes": ["mince"], "excludes": ["pork"]},
        "onion": {},
    }
    rejected = _apply_ingredient_validity(rows, lookup)
    assert rejected == 1
    assert rows[0]["valid_ingredient"] is True
    assert rows[1]["valid_ingredient"] is False
    assert "EXCLUDE" in rows[1]["filter_reason"]
    assert rows[2]["valid_ingredient"] is True and rows[2]["filter_reason"] == ""


# ── Store-cost gating ────────────────────────────────────────────────────────

TERMS = ["beef mince", "onion"]


def _store_row(company, store, term, sku, used_price, title="Product", valid=True):
    row = _row(term, title, used_price)
    row.update({
        "company": company, "store": store, "sku": sku,
        "units_match": True, "status": "ok",
        "purchase_quantity": 1, "purchase_price": used_price,
        "valid_ingredient": valid,
        "brand": "Test Brand", "price": used_price,
        "quantity": 500, "measurement_unit": "g",
    })
    return row


def _outcomes(overrides=None):
    base = {
        ("PaknSave", "sid-a", "Store A", t): {"status": "ok", "products": 2, "detail": ""}
        for t in TERMS
    }
    if overrides:
        base.update(overrides)
    return base


GEO = {("PaknSave", "Store A"): {"lat": -36.0, "lon": 174.0, "distance_km": 1.0}}


def test_filtered_out_products_do_not_win():
    """A cheaper but filter-invalid product must lose to a pricier valid one."""
    rows = [
        _store_row("PaknSave", "Store A", "beef mince", "sku-cheap", 5.00, "Pork Mince 500g", valid=False),
        _store_row("PaknSave", "Store A", "beef mince", "sku-ok", 8.00, "Beef Mince Premium"),
        _store_row("PaknSave", "Store A", "onion", "sku-onion", 2.00, "Brown Onion"),
    ]
    costs = _build_store_costs(TERMS, {}, rows, _outcomes(), GEO)
    beef = next(b for b in costs[0]["best_per_ingredient"] if b["search_ingredient"] == "beef mince")
    assert beef["used_price"] == 8.00
    assert costs[0]["total_used_cost"] == 10.00


def test_all_filtered_becomes_filtered_out_issue_with_placeholder():
    rows = [_store_row("PaknSave", "Store A", "beef mince", "sku-1", 5.00, "Pork Mince", valid=False)]
    costs = _build_store_costs(["beef mince"], {}, rows, _outcomes(), GEO)
    store = costs[0]
    assert store["complete"] is False and store["total_used_cost"] == 0.0
    issue = next(i for i in store["issues"] if i["search_ingredient"] == "beef mince")
    assert issue["status"] == "filtered_out"
    assert "rejected by ingredient filters" in issue["detail"]
    blank = store["best_per_ingredient"][0]
    assert blank["status"] == "not_found" and blank["price"] == ""


def test_unflagged_rows_keep_legacy_behaviour():
    """Rows without a valid_ingredient flag (older runs) are never filtered."""
    legacy = _store_row("PaknSave", "Store A", "beef mince", "sku-legacy", 4.00)
    del legacy["valid_ingredient"]
    costs = _build_store_costs(["beef mince"], {}, [legacy], _outcomes({
        ("PaknSave", "sid-a", "Store A", "beef mince"): {"status": "ok", "products": 1, "detail": ""},
    }), GEO)
    assert costs[0]["best_per_ingredient"][0]["used_price"] == 4.00


# ── Reapply endpoint ──────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    return TestClient(web_main.app)


def _register_completed_job(monkeypatch):
    job = JobState(DishRequest(dish="test dish", address="Somewhere, NZ"))
    job.status = "complete"
    rows = [
        _store_row("PaknSave", "Store A", "beef mince", "s1", 5.00, "Budget Beef Mince 500g"),
        _store_row("PaknSave", "Store A", "beef mince", "s2", 6.50, "Pork Mince 500g"),
        _store_row("PaknSave", "Store A", "onion", "s3", 2.00, "Brown Onion 1kg"),
    ]
    for r in rows:
        r["valid_ingredient"] = True
        r["filter_reason"] = ""
    job.pipeline_cache = {
        "rows": rows,
        "search_terms": TERMS,
        "ing_lookup": {t: {"search_term": t} for t in TERMS},
        "outcomes": _outcomes(),
        "store_geo": GEO,
        "companies": ["PaknSave"],
        "dish_name": "test dish",
        "source": "curated",
        "origin": {"lat": -36.0, "lon": 174.0, "source": "geocoded"},
    }
    job.result = None
    monkeypatch.setitem(web_main.JOBS, job.id, job)
    return job


def test_reapply_recomputes_costs_and_updates_job(client, monkeypatch):
    job = _register_completed_job(monkeypatch)

    response = client.post(f"/optimise/{job.id}/reapply", json={
        "ingredient_filters": {"beef mince": {"includes": ["mince"], "excludes": ["pork"]}},
    })
    assert response.status_code == 200
    data = response.json()
    pork = [r for r in data["rows"] if r["sku"] == "s2"][0]
    assert pork["valid_ingredient"] is False
    beef = next(b for b in data["store_costs"][0]["best_per_ingredient"]
                if b["search_ingredient"] == "beef mince")
    assert beef["used_price"] == 5.00
    # job.result replaced so later snapshots agree with the reapplied view.
    assert job.result is not None and job.result.rows[1]["valid_ingredient"] is False
    # Cached first-run state untouched — reapplying again stays deterministic.
    assert job.pipeline_cache["rows"][1]["valid_ingredient"] is True


def test_reapply_clearing_filters_restores_validity(client, monkeypatch):
    job = _register_completed_job(monkeypatch)
    client.post(f"/optimise/{job.id}/reapply", json={
        "ingredient_filters": {"beef mince": {"includes": ["nonexistent"], "excludes": []}},
    })
    assert all(r["valid_ingredient"] is False for r in job.result.rows if r["search_ingredient"] == "beef mince")
    response = client.post(f"/optimise/{job.id}/reapply", json={"ingredient_filters": {}})
    assert response.status_code == 200
    assert all(r["valid_ingredient"] is True for r in job.result.rows)


def test_reapply_rejects_unknown_or_incomplete_jobs(client, monkeypatch):
    job = _register_completed_job(monkeypatch)
    assert client.post("/optimise/nope/reapply", json={"ingredient_filters": {}}).status_code == 404

    queued = JobState(DishRequest(dish="x", address="y"))
    monkeypatch.setitem(web_main.JOBS, queued.id, queued)
    assert client.post(f"/optimise/{queued.id}/reapply", json={"ingredient_filters": {}}).status_code == 409

    job.pipeline_cache = None
    response = client.post(f"/optimise/{job.id}/reapply", json={"ingredient_filters": {}})
    assert response.status_code == 409
    assert "no cached products" in response.json()["detail"]


# ── Filter preview endpoint ───────────────────────────────────────────────────

def test_filter_preview_counts_and_product_flags(client, monkeypatch):
    job = _register_completed_job(monkeypatch)

    response = client.post(f"/optimise/{job.id}/filter_preview", json={
        "ingredient_filters": {"beef mince": {"includes": ["mince"], "excludes": ["pork"]}},
    })
    assert response.status_code == 200
    data = response.json()
    assert data["terms"]["beef mince"] == {"total": 2, "matched": 1}
    assert data["terms"]["onion"] == {"total": 1, "matched": 1}
    assert data["unmatched_terms"] == []

    by_sku = {p["sku"]: p for p in data["products"]}
    assert by_sku["s1"]["valid"] is True and by_sku["s1"]["reason"] == ""
    assert by_sku["s2"]["valid"] is False
    assert "EXCLUDE" in by_sku["s2"]["reason"]
    # Product display fields ride along for the tuner's card 3.
    assert by_sku["s2"]["brand"] == "Test Brand"
    assert by_sku["s2"]["returned_ingredient"] == "Pork Mince 500g"
    assert by_sku["s2"]["price"] == 6.50
    assert by_sku["s2"]["quantity"] == 500 and by_sku["s2"]["measurement_unit"] == "g"
    assert by_sku["s2"]["search_ingredient"] == "beef mince"


def test_filter_preview_does_not_mutate_job(client, monkeypatch):
    job = _register_completed_job(monkeypatch)
    payload = {"ingredient_filters": {
        "beef mince": {"includes": ["nonexistent"], "excludes": []}}}

    first = client.post(f"/optimise/{job.id}/filter_preview", json=payload)
    assert first.status_code == 200
    assert all(p["valid"] is False for p in first.json()["products"]
               if p["search_ingredient"] == "beef mince")

    # Nothing stuck: cached rows keep their original flags, result untouched,
    # and a second identical preview is deterministic.
    assert all(r["valid_ingredient"] is True for r in job.pipeline_cache["rows"])
    assert job.result is None
    second = client.post(f"/optimise/{job.id}/filter_preview", json=payload)
    assert second.json() == first.json()


def test_filter_preview_reports_unmatched_terms(client, monkeypatch):
    job = _register_completed_job(monkeypatch)
    data = client.post(f"/optimise/{job.id}/filter_preview", json={
        "ingredient_filters": {"ghost term": {"includes": ["x"], "excludes": []}},
    }).json()
    assert data["unmatched_terms"] == ["ghost term"]
    assert all(p["valid"] is True for p in data["products"])


def test_filter_preview_rejects_unknown_or_incomplete_jobs(client, monkeypatch):
    job = _register_completed_job(monkeypatch)
    body = {"ingredient_filters": {}}
    assert client.post("/optimise/nope/filter_preview", json=body).status_code == 404

    queued = JobState(DishRequest(dish="x", address="y"))
    monkeypatch.setitem(web_main.JOBS, queued.id, queued)
    assert client.post(f"/optimise/{queued.id}/filter_preview", json=body).status_code == 409

    job.pipeline_cache = None
    response = client.post(f"/optimise/{job.id}/filter_preview", json=body)
    assert response.status_code == 409
    assert "no cached products" in response.json()["detail"]


# ── GET /dish_filters ─────────────────────────────────────────────────────────

def test_dish_filters_endpoint_serves_curated_file(client, tmp_path, monkeypatch):
    seed = {"_comment": "meta", "spaghetti bolognese": {
        "beef mince": {"includes": ["mince"], "excludes": ["pork"]}}}
    (tmp_path / "dish_filters.json").write_text(json.dumps(seed), encoding="utf-8")
    monkeypatch.setattr(web_main, "DATA_DIR", tmp_path)
    data = client.get("/dish_filters").json()
    assert data["_comment"] == "meta"
    assert data["spaghetti bolognese"]["beef mince"]["includes"] == ["mince"]


def test_request_model_accepts_ingredient_filters():
    req = DishRequest(dish="d", address="a", ingredient_filters={
        "beef mince": IngredientFilterSet(includes=["mince"], excludes=["pork"])})
    cleaned = _clean_ingredient_filters(req.ingredient_filters)
    assert cleaned["beef mince"]["excludes"] == ["pork"]
