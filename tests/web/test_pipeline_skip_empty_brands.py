"""Tests for brand skipping in the pipeline's nearby-store phase.

A brand with zero stores in range must NOT enter company_progress (so the
live progress tracker never shows a stuck idle tile), while the requested
companies list stays intact and a console warn explains the skip. When NO
brand has stores, the job fails fast with a clear 400.
"""
import asyncio

import pytest

from NZMealOptimiser.web import main as web_main
from NZMealOptimiser.web.main import DishRequest, JobState


def _store(name, sid, dist):
    return {"name": name, "store_id": sid, "region": "NI", "lat": -36.85,
            "lon": 174.76, "distance_km": dist}


def _row(company, store, term):
    return {
        "company": company, "store": store, "search_ingredient": term,
        "sku": f"{company[:2].lower()}-1", "returned_ingredient": f"{term} product",
        "brand": "Budget", "price": 9.0, "quantity": 500, "measurement_unit": "g",
    }


def _patch_stores(monkeypatch, paknsave, newworld, woolworths):
    """Stub every brand's nearby-store lookup; no network calls."""
    monkeypatch.setitem(web_main.BRANDS["PaknSave"], "find_nearby", lambda *a, **k: paknsave)
    monkeypatch.setitem(web_main.BRANDS["NewWorld"], "find_nearby", lambda *a, **k: newworld)
    monkeypatch.setattr(web_main.woolworths_api, "get_nearby_stores",
                        lambda lat, lon, max_dist_km=5.0: woolworths)


def _patch_pipeline(monkeypatch, terms=("beef mince", "eggs")):
    """Stub ingredient resolution, Edge auth, and the per-search fetch."""
    monkeypatch.setattr(web_main, "resolve_ingredients", lambda name, portions=4: (
        {"dish_name": name, "portion": 4,
         "ingredients": [{"search_term": t, "quantity": 500, "unit": "g"} for t in terms]},
        "curated",
    ))
    monkeypatch.setattr(web_main, "_make_authenticated_api", lambda api_class: None)
    monkeypatch.setattr(
        web_main, "_fetch_ingredient",
        lambda company, api, store_id, store_name, ingredient, region: [
            _row(company, store_name, ingredient),
        ],
    )


def _job(**overrides):
    req = DishRequest(dish="spaghetti bolognese", address="10 High St, Auckland",
                      latitude=-36.85, longitude=174.76, **overrides)
    return JobState(req)


def test_zero_store_brand_is_left_out_of_the_tracker(monkeypatch):
    _patch_stores(monkeypatch,
                  paknsave=[],  # nothing in range for Pak'nSave
                  newworld=[_store("New World City", "nw-1", 2.0)],
                  woolworths=[_store("Woolworths Metro", "ww-1", 3.0)])
    _patch_pipeline(monkeypatch)
    job = _job(companies=["PaknSave", "NewWorld", "Woolworths"])

    asyncio.run(web_main._run_job(job))

    assert job.status == "complete"
    # Pak'nSave never registers -> no tile in the live tracker.
    assert set(job.company_progress) == {"NewWorld", "Woolworths"}
    codes = {c["code"] for c in job.snapshot()["companies"]}
    assert "PNS" not in codes and {"NW", "WW"} <= codes
    # ...but the run still reports which companies were checked.
    assert job.result.companies_checked == ["PaknSave", "NewWorld", "Woolworths"]
    # A console warn explains why the tile is missing.
    warns = [(e["co"], e["text"]) for e in job.events if e["kind"] == "warn"]
    assert any(co == "PNS" and "No stores within" in text for co, text in warns)
    # Tasks exist only for brands with stores.
    assert job.total_tasks == 4  # 2 brands x 1 store x 2 ingredients


def test_all_brands_empty_fails_fast(monkeypatch):
    _patch_stores(monkeypatch, paknsave=[], newworld=[], woolworths=[])
    _patch_pipeline(monkeypatch)
    job = _job()

    asyncio.run(web_main._run_job(job))

    assert job.status == "error"
    assert "No stores found within" in job.error_detail


def test_single_brand_run_with_no_stores_errors_cleanly(monkeypatch):
    """User picks only Pak'nSave; nothing in range -> clear error, no crash."""
    _patch_stores(monkeypatch, paknsave=[], newworld=[], woolworths=[])
    _patch_pipeline(monkeypatch)
    job = _job(companies=["PaknSave"])

    asyncio.run(web_main._run_job(job))

    assert job.status == "error"
    assert job.error_status == 400
    assert "No stores found within" in job.error_detail
