"""Tests for the /test app-shell support endpoints: system-info, tech-docs
serving, danger-zone hard ceilings and the dishes.json delete/source-tag
round trip.

No supermarket network calls — DATA_DIR / TECH_DOCS_DIR are monkeypatched
onto tmp paths where file contents matter.
"""
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from NZMealOptimiser.web import main as web_main
from NZMealOptimiser.web.main import (
    CustomIngredient,
    HARD_LIMITS,
    SaveDishRequest,
    _enforce_hard_limits,
)


@pytest.fixture()
def client():
    return TestClient(web_main.app)


@pytest.fixture()
def docs_dir(tmp_path, monkeypatch):
    docs = tmp_path / "technical"
    docs.mkdir()
    (docs / "FastAPI.md").write_text("# FastAPI\nhello", encoding="utf-8")
    monkeypatch.setattr(web_main, "TECH_DOCS_DIR", docs)
    return docs


# ── GET /system-info ──────────────────────────────────────────────────────────

def test_system_info_reports_workers_and_limits(client):
    data = client.get("/system-info").json()
    assert data["max_workers"] >= 1
    assert data["configured_workers"] == int(web_main.settings.WEB_MAX_WORKERS)
    assert data["hard_limits"] == {
        "max_distance_km": 50.0,
        "max_stores_per_company": 20,
    }


def test_thread_pool_matches_effective_workers():
    assert web_main._THREAD_POOL._max_workers == web_main.EFFECTIVE_MAX_WORKERS


# ── GET /tech-docs ────────────────────────────────────────────────────────────

def test_tech_docs_lists_all_manuals(client):
    docs = client.get("/tech-docs").json()
    names = {d["name"] for d in docs}
    assert {"FastAPI.md", "PaknSave_API.md", "Woolworths_API.md"} <= names
    assert all(set(d) == {"name", "title"} for d in docs)


def test_tech_doc_file_serves_markdown(client, docs_dir):
    response = client.get("/tech-docs/FastAPI.md")
    assert response.status_code == 200
    assert "markdown" in response.headers["content-type"]
    assert response.text.startswith("# FastAPI")


def test_tech_doc_rejects_unknown_names(client):
    assert client.get("/tech-docs/not-a-doc.md").status_code == 404
    # Path traversal attempts fall outside the whitelist too.
    assert client.get("/tech-docs/..%2Fmain.py").status_code in (404, 400)


# ── Danger-zone hard ceilings ────────────────────────────────────────────────

@pytest.mark.parametrize("distance,stores", [(51, 3), (-1, 3), (5, 21), (5, 0)])
def test_enforce_hard_limits_rejects(distance, stores):
    with pytest.raises(HTTPException) as exc:
        _enforce_hard_limits(distance, stores)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("distance,stores", [(50, 20), (0.5, 1), (5, 3)])
def test_enforce_hard_limits_accepts_edge_values(distance, stores):
    _enforce_hard_limits(distance, stores)  # no raise


def test_job_submission_rejects_over_ceiling(client):
    payload = {
        "dish": "spaghetti bolognese",
        "address": "Auckland CBD",
        "distance_km": 51,
        "companies": ["Woolworths"],
    }
    response = client.post("/optimise/jobs", json=payload)
    assert response.status_code == 400
    assert "distance_km" in response.json()["detail"]


def test_nearby_preview_caps_at_hard_limit(client):
    params = {"lat": -36.85, "lon": 174.76, "distance_km": 60}
    response = client.get("/stores/nearby", params=params)
    assert response.status_code == 400


# ── dishes.json: source tag + DELETE ─────────────────────────────────────────

def test_save_tags_user_source_and_delete_round_trip(tmp_path, monkeypatch, client):
    monkeypatch.setattr(web_main, "DATA_DIR", tmp_path)
    seed = {"beef curry": {"dish_name": "Beef Curry", "portion": 4, "ingredients": []}}
    (tmp_path / "dishes.json").write_text(json.dumps(seed), encoding="utf-8")

    save = client.post("/dishes/save", json=SaveDishRequest(
        dish_name="Kumara Hash",
        base_portions=2,
        ingredients=[CustomIngredient(search_term="kumara", quantity=300, unit="g")],
    ).model_dump())
    assert save.status_code == 200
    stored = json.loads((tmp_path / "dishes.json").read_text(encoding="utf-8"))
    assert stored["kumara hash"]["source"] == "user"
    assert "source" not in seed["beef curry"] or seed["beef curry"].get("source") != "user"

    deleted = client.delete("/dishes/kumara hash")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True, "key": "kumara hash", "was_user": True, "dishes_count": 1}
    assert "kumara hash" not in json.loads((tmp_path / "dishes.json").read_text(encoding="utf-8"))


def test_delete_curated_dish_flags_was_user_false(tmp_path, monkeypatch, client):
    monkeypatch.setattr(web_main, "DATA_DIR", tmp_path)
    seed = {"lasagna": {"dish_name": "Lasagna", "portion": 4, "ingredients": []}}
    (tmp_path / "dishes.json").write_text(json.dumps(seed), encoding="utf-8")

    deleted = client.delete("/dishes/lasagna")
    assert deleted.status_code == 200
    assert deleted.json()["was_user"] is False
    assert deleted.json()["dishes_count"] == 0


def test_delete_unknown_dish_404(tmp_path, monkeypatch, client):
    monkeypatch.setattr(web_main, "DATA_DIR", tmp_path)
    (tmp_path / "dishes.json").write_text("{}", encoding="utf-8")
    assert client.delete("/dishes/nope").status_code == 404


def test_save_persists_notes_top_level_key(tmp_path, monkeypatch, client):
    """POST /dishes/save with a notes field persists it as a top-level
    key on the entry (trimmed to <=100 chars); omitting notes leaves
    the key absent. See main.py:849-851."""
    monkeypatch.setattr(web_main, "DATA_DIR", tmp_path)
    (tmp_path / "dishes.json").write_text("{}", encoding="utf-8")

    save = client.post("/dishes/save", json=SaveDishRequest(
        dish_name="Kumara Hash",
        base_portions=4,
        ingredients=[CustomIngredient(search_term="kumara", quantity=300, unit="g")],
        notes="  from bbcgoodfood.com ",
    ).model_dump())
    assert save.status_code == 200
    stored = json.loads((tmp_path / "dishes.json").read_text(encoding="utf-8"))
    assert stored["kumara hash"]["notes"] == "from bbcgoodfood.com"

    save2 = client.post("/dishes/save", json=SaveDishRequest(
        dish_name="No Notes Dish",
        base_portions=2,
        ingredients=[CustomIngredient(search_term="rice", quantity=500, unit="g")],
    ).model_dump())
    assert save2.status_code == 200
    stored = json.loads((tmp_path / "dishes.json").read_text(encoding="utf-8"))
    assert "notes" not in stored["no notes dish"]

    long_notes = "x" * 200
    save3 = client.post("/dishes/save", json=SaveDishRequest(
        dish_name="Truncated Notes",
        base_portions=2,
        ingredients=[CustomIngredient(search_term="rice", quantity=500, unit="g")],
        notes=long_notes,
    ).model_dump())
    assert save3.status_code == 200
    stored = json.loads((tmp_path / "dishes.json").read_text(encoding="utf-8"))
    assert len(stored["truncated notes"]["notes"]) == 100
