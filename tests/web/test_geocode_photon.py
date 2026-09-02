"""Tests for the /geocode/autocomplete + /geocode/reverse endpoints.

The two new endpoints power the dashboard's Photon-backed address
autocomplete and the new map-click pick-to-resolve flow. We mock the
upstream providers (Photon + Nominatim reverse) so the tests stay
fully offline.

Regression covers:
- LRU cache hits/misses, cache-key shape, NZ bbox guard
- Provider routing (photon vs nominatim vs auto)
- Error path: Photon returns 0 features -> 502; Nominatim failure -> 502
- Empty results: Photon returns no features, autocomplete returns [] (not 404)
"""
import pytest
from fastapi.testclient import TestClient

from NZMealOptimiser.web import main as web_main


@pytest.fixture()
def client():
    return TestClient(web_main.app)


def _reset_caches():
    """Each test resets module-level caches so LRU state can't leak."""
    web_main._AUTOCOMPLETE_CACHE.clear()
    web_main._PHOTON_REVERSE_CACHE.clear()
    web_main._REVERSE_CACHE.clear()


# ── /geocode/autocomplete ────────────────────────────────────────────────────


def test_autocomplete_rejects_short_queries(client):
    _reset_caches()
    response = client.get("/geocode/autocomplete", params={"q": "a"})
    assert response.status_code == 400
    assert "at least 2" in response.json()["detail"]


def test_autocomplete_proxies_photon_and_shapes_payload(client, monkeypatch):
    _reset_caches()
    captured = {}

    def fake_request(url, params):
        captured["url"] = url
        captured["params"] = params
        return [
            {
                "geometry": {"coordinates": [174.7633, -36.8485]},
                "properties": {
                    "name": "Queen Street",
                    "street": "Queen Street",
                    "housenumber": "21",
                    "city": "Auckland",
                    "country": "New Zealand",
                    "postcode": "1010",
                    "type": "street",
                },
            },
            {
                "geometry": {"coordinates": [174.77, -36.84]},
                "properties": {"name": "Auckland CBD", "country": "New Zealand", "type": "locality"},
            },
        ]

    monkeypatch.setattr(web_main, "_photon_request_json", fake_request)
    response = client.get("/geocode/autocomplete", params={"q": "Queen St"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cached"] is False
    assert body["source"] == "photon"
    assert captured["url"] == "https://photon.komoot.io/api/"
    assert captured["params"]["q"] == "Queen St"
    assert captured["params"]["countrycode"] == "NZ"
    assert len(body["suggestions"]) == 2
    first = body["suggestions"][0]
    assert first["lat"] == pytest.approx(-36.8485)
    assert first["lon"] == pytest.approx(174.7633)
    assert "21" in first["display"] and "Queen Street" in first["display"]
    assert first["type"] == "street"
    assert first["postcode"] == "1010"


def test_autocomplete_returns_empty_list_when_photon_has_no_match(client, monkeypatch):
    _reset_caches()
    monkeypatch.setattr(web_main, "_photon_request_json", lambda *_a, **_k: [])
    response = client.get("/geocode/autocomplete", params={"q": "zzzz no such place"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["suggestions"] == []
    assert body["cached"] is False


def test_autocomplete_uses_lru_cache_for_repeat_queries(client, monkeypatch):
    _reset_caches()
    call_count = {"n": 0}

    def fake_request(url, params):
        call_count["n"] += 1
        return [{"geometry": {"coordinates": [174.7, -36.8]}, "properties": {"name": "X"}}]

    monkeypatch.setattr(web_main, "_photon_request_json", fake_request)
    first = client.get("/geocode/autocomplete", params={"q": "Auckland"})
    second = client.get("/geocode/autocomplete", params={"q": "Auckland"})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert call_count["n"] == 1


def test_autocomplete_clamps_limit_to_max(client, monkeypatch):
    _reset_caches()
    captured = {}

    def fake_request(url, params):
        captured["params"] = params
        return []

    monkeypatch.setattr(web_main, "_photon_request_json", fake_request)
    response = client.get("/geocode/autocomplete", params={"q": "wellington", "limit": 99})
    assert response.status_code == 200
    assert captured["params"]["limit"] == web_main._AUTOCOMPLETE_MAX_LIMIT


# ── /geocode/reverse (Photon) ────────────────────────────────────────────────


def test_reverse_photon_returns_label_and_caches(client, monkeypatch):
    _reset_caches()
    captured = {}

    def fake_request(url, params):
        captured["url"] = url
        captured["params"] = params
        return [
            {
                "geometry": {"coordinates": [174.7633, -36.8485]},
                "properties": {
                    "name": "Auckland",
                    "street": "Queen Street",
                    "housenumber": "21",
                    "city": "Auckland",
                    "country": "New Zealand",
                },
            }
        ]

    monkeypatch.setattr(web_main, "_photon_request_json", fake_request)
    response = client.get("/geocode/reverse", params={"lat": -36.8485, "lon": 174.7633})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "photon"
    assert body["cached"] is False
    assert "21" in body["label"] and "Queen Street" in body["label"]
    assert "Auckland" in body["label"]
    assert captured["url"] == "https://photon.komoot.io/reverse"
    assert captured["params"]["lat"] == pytest.approx(-36.8485)

    second = client.get("/geocode/reverse", params={"lat": -36.8485, "lon": 174.7633})
    assert second.json()["cached"] is True


def test_reverse_photon_returns_502_on_no_features(client, monkeypatch):
    _reset_caches()
    monkeypatch.setattr(web_main, "_photon_request_json", lambda *_a, **_k: [])
    response = client.get("/geocode/reverse", params={"lat": -36.8485, "lon": 174.7633})
    assert response.status_code == 502
    assert "Photon" in response.json()["detail"]


def test_reverse_rejects_coords_outside_nz(client):
    response = client.get("/geocode/reverse", params={"lat": -33.0, "lon": 151.0})
    assert response.status_code == 400
    assert "outside New Zealand" in response.json()["detail"]


def test_reverse_rejects_unknown_provider(client):
    response = client.get("/geocode/reverse", params={"lat": -36.8485, "lon": 174.7633, "provider": "google"})
    assert response.status_code == 400
    assert "photon" in response.json()["detail"]


# ── /geocode/reverse (Nominatim) ─────────────────────────────────────────────


def test_reverse_nominatim_uses_helper_and_caches(client, monkeypatch):
    _reset_caches()
    captured = {}

    def fake_nominatim(lat, lon):
        captured["lat"] = lat
        captured["lon"] = lon
        return ("21 Queen Street, Auckland, New Zealand", -36.8485, 174.7633)

    monkeypatch.setattr(web_main, "_nominatim_reverse", fake_nominatim)
    response = client.get(
        "/geocode/reverse",
        params={"lat": -36.8485, "lon": 174.7633, "provider": "nominatim"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "nominatim"
    assert body["cached"] is False
    assert body["label"] == "21 Queen Street, Auckland, New Zealand"
    assert captured["lat"] == pytest.approx(-36.8485)
    # Cache hit
    response2 = client.get(
        "/geocode/reverse",
        params={"lat": -36.8485, "lon": 174.7633, "provider": "nominatim"},
    )
    assert response2.json()["cached"] is True


def test_reverse_nominatim_returns_502_when_helper_fails(client, monkeypatch):
    _reset_caches()
    monkeypatch.setattr(web_main, "_nominatim_reverse", lambda *_a: None)
    response = client.get(
        "/geocode/reverse",
        params={"lat": -36.8485, "lon": 174.7633, "provider": "nominatim"},
    )
    assert response.status_code == 502
    assert "Nominatim" in response.json()["detail"]


def test_reverse_auto_defaults_to_photon(client, monkeypatch):
    _reset_caches()
    monkeypatch.setattr(
        web_main,
        "_photon_request_json",
        lambda *_a, **_k: [
            {"geometry": {"coordinates": [174.7, -36.8]}, "properties": {"name": "Auckland"}}
        ],
    )
    response = client.get("/geocode/reverse", params={"lat": -36.8, "lon": 174.7, "provider": "auto"})
    assert response.status_code == 200
    assert response.json()["source"] == "photon"


# ── /geocode (existing endpoint) regression: must keep working ──────────────


def test_existing_geocode_still_works(client, monkeypatch):
    """Sanity: the new helpers did not break the existing /geocode
    forward-lookup. The /test tree imports the same module, so a
    regression here would break map → preview → run for every brand.
    """
    monkeypatch.setattr(web_main.optimiser_utils, "geocode", lambda _addr: (-36.84, 174.74))
    web_main._GEOCODE_CACHE.clear()
    response = client.get("/geocode", params={"address": "Auckland CBD"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lat"] == pytest.approx(-36.84)
    assert body["lon"] == pytest.approx(174.74)
    assert body["cached"] is False
