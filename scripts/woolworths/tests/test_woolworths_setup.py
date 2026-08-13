"""
Unit tests for Woolworths NZ Store Setup (woolworths_setup.py).

Tests verify:
    1. clean_null() handles None, empty strings, and valid values.
    2. fetch_store_data() builds data/woolworths_store_data.json and
       data/woolworths_stores.csv DIRECTLY from the CDX site-location API
       response, keyed on extra1 (fulfilmentStoreId). The legacy choices
       CSV is not consulted.
    3. The cleaned=True filter drops stores without coordinates; cleaned=False
       keeps all.
    4. fetch_store_data() handles edge cases (missing coords, invalid coord
       formats, blank coords, null extra1, excluded stores).
    5. The fixture JSON and the stores_fixture.csv are consistent with the
       canonical fetch_store_data() output.

All data is loaded from the fixture directory produced by
generate_fixtures.py — no live network calls during tests.

Fixture data (5 stores in store_data_example.json, the Nelson/South Island
region, ALL with valid coordinates):

    store_data_example.json (CDX site data, 5 sites):
        extra1=9290  -> Nelson Junction Woolworths   lat=-41.2977069 lon=173.241518
        extra1=9527  -> Nelson Woolworths            lat=-41.2727    lon=173.2773
        extra1=9246  -> Trafalgar Park Woolworths    lat=-41.2702    lon=173.2815
        extra1=9168  -> Stoke Woolworths             lat=-41.3117    lon=173.2338
        extra1=9040  -> Richmond Woolworths          lat=-41.3342    lon=173.2018

Since all 5 have coordinates, cleaned=True returns 5 rows (cleaned=False too),
keyed on extra1.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

# Make the woolworths scripts directory and combined helpers importable.
SCRIPT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(SCRIPT_DIR))  # scripts/woolworths
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "combined"))  # shared utils

FIXTURE_DIR = SCRIPT_DIR / "fixture"

# Patch targets for woolworths_setup module
FIX_STORE_DATA_JSON = FIXTURE_DIR / "store_data_example.json"
FIX_STORES_CSV = FIXTURE_DIR / "stores_fixture.csv"   # canonical fetch_store_data output (5 rows, extra1)


class TestCleanNull:
    """Tests for woolworths_setup.clean_null()."""

    @pytest.mark.parametrize("input_val,expected", [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("Hello", "Hello"),
        (123, "123"),
        (0, "0"),
        (True, "True"),
    ])
    def test_clean_null(self, input_val, expected):
        """clean_null() must return empty string for None/empty/whitespace,
        and stringified value for everything else."""
        from woolworths_setup import clean_null
        assert clean_null(input_val) == expected


class TestFetchStoreData:
    """Tests for woolworths_setup.fetch_store_data() using the CDX fixture JSON.

    fetch_store_data() now reads data/woolworths_store_data.json (CDX) directly
    and emits a 5-column store file keyed on extra1. Tests patch
    woolworths_setup.JSON_DATA with store_data_example.json (5 sites, all
    with coordinates) and CSV_STORES with a temp CSV to avoid polluting fixtures.
    """

    # extra1 values present in the fixture (all 5 have coords)
    EXPECTED_IDS = {"9290", "9527", "9246", "9168", "9040"}
    # coords keyed on extra1
    EXPECTED_COORDS = {
        "9290": (-41.2977069, 173.241518),
        "9527": (-41.2727, 173.2773),
        "9246": (-41.2702, 173.2815),
        "9168": (-41.3117, 173.2338),
        "9040": (-41.3342, 173.2018),
    }

    def _run_fetch(self, cleaned, json_path=None, temp_csv=None):
        """Run fetch_store_data against the CDX JSON fixture.

        Patches woolworths_setup.JSON_DATA with the fixture JSON and
        CSV_STORES with a temp CSV, then mocks requests.get to avoid live
        network calls.

        Args:
            cleaned: bool — whether to drop stores without coordinates.
            json_path: optional Path for the input JSON.
            temp_csv: optional Path for the output CSV.

        Returns the list of store dicts.
        """
        if json_path is None:
            json_path = FIX_STORE_DATA_JSON
        if temp_csv is None:
            temp_csv = FIXTURE_DIR / "_fetch_test_output.csv"

        # Load fixture JSON to use as mock response
        with open(json_path, "r", encoding="utf-8") as f:
            fixture_data = json.load(f)

        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture_data
        mock_resp.raise_for_status.return_value = None

        with patch("woolworths_setup.JSON_DATA", json_path), \
             patch("woolworths_setup.CSV_STORES", temp_csv), \
             patch("woolworths_setup.requests.get", return_value=mock_resp):
            from woolworths_setup import fetch_store_data
            stores = fetch_store_data(cleaned=cleaned)

        if temp_csv.exists():
            temp_csv.unlink()
        return stores

    def test_cleaned_store_list_keeps_all_with_coords(self):
        """cleaned=True with the fixture (all 5 stores have coords) keeps all 5."""
        stores = self._run_fetch(cleaned=True)
        assert len(stores) == 5

    def test_unpadded_store_list_keeps_all(self):
        """cleaned=False keeps all 5 stores."""
        stores = self._run_fetch(cleaned=False)
        assert len(stores) == 5

    def test_store_list_has_expected_columns(self):
        """The returned store dicts must have id, name, address, latitude, longitude."""
        stores = self._run_fetch(cleaned=False)
        expected_keys = {"id", "name", "address", "latitude", "longitude"}
        assert set(stores[0].keys()) == expected_keys

    def test_store_list_keys_on_extra1(self):
        """The 'id' field must be the extra1 values (not extra2)."""
        stores = self._run_fetch(cleaned=False)
        actual_ids = {s["id"] for s in stores}
        assert actual_ids == self.EXPECTED_IDS

    def test_store_list_preserves_store_names(self):
        """The store list must contain the real store names from the fixture."""
        stores = self._run_fetch(cleaned=False)
        names = {s["name"] for s in stores}
        assert "Nelson Junction Woolworths" in names
        assert "Nelson Woolworths" in names
        assert "Trafalgar Park Woolworths" in names

    def test_store_list_joined_coordinates_correct(self):
        """The lat/lon for extra1=9290 must match the CDX data."""
        stores = self._run_fetch(cleaned=False)
        store = next(s for s in stores if s["id"] == "9290")
        assert abs(float(store["latitude"]) - (-41.2977069)) < 0.0001
        assert abs(float(store["longitude"]) - 173.241518) < 0.0001

    def test_store_list_preserves_all_coords(self):
        """All 5 fixture stores must have correct coordinates."""
        stores = self._run_fetch(cleaned=False)
        for store_id, (lat, lon) in self.EXPECTED_COORDS.items():
            store = next(s for s in stores if s["id"] == store_id)
            assert abs(float(store["latitude"]) - lat) < 0.0001, \
                f"Lat mismatch for store {store_id}"
            assert abs(float(store["longitude"]) - lon) < 0.0001, \
                f"Lon mismatch for store {store_id}"

    def test_store_list_writes_csv(self):
        """fetch_store_data() must write the CSV file with the correct rows."""
        temp_csv = FIXTURE_DIR / "_fetch_test_csv.csv"
        try:
            stores = self._run_fetch(cleaned=True, temp_csv=temp_csv)
            # Re-run with CSV patching to verify write
            with open(FIX_STORE_DATA_JSON, "r", encoding="utf-8") as f:
                fixture_data = json.load(f)
            mock_resp = MagicMock()
            mock_resp.json.return_value = fixture_data
            mock_resp.raise_for_status.return_value = None
            with patch("woolworths_setup.JSON_DATA", FIX_STORE_DATA_JSON), \
                 patch("woolworths_setup.CSV_STORES", temp_csv), \
                 patch("woolworths_setup.requests.get", return_value=mock_resp):
                from woolworths_setup import fetch_store_data
                fetch_store_data(cleaned=True)

            df = pd.read_csv(temp_csv)
            assert len(df) == 5
            assert set(df["id"].astype(str)) == self.EXPECTED_IDS
            assert list(df.columns) == ["id", "name", "address", "latitude", "longitude"]
        finally:
            if temp_csv.exists():
                temp_csv.unlink()

    def test_fetch_matches_canonical_csv(self):
        """fetch_store_data() output must match the stores_fixture.csv fixture.

        stores_fixture.csv is the canonical 5-column (id=extra1) store file
        emitted by the current fetch_store_data() implementation.
        """
        stores = self._run_fetch(cleaned=True)
        fixture_df = pd.read_csv(FIX_STORES_CSV)
        # Same id set
        assert {s["id"] for s in stores} == set(fixture_df["id"].astype(str))
        # Spot-check one store's coords against the canonical CSV
        store = next(s for s in stores if s["id"] == "9290")
        fix = fixture_df[fixture_df["id"].astype(str) == "9290"].iloc[0]
        assert abs(float(store["latitude"]) - float(fix["latitude"])) < 0.0001
        assert abs(float(store["longitude"]) - float(fix["longitude"])) < 0.0001


class TestCleaningLogic:
    """Tests for the cleaned=True coordinate-filtering logic.

    fetch_store_data() now reads the CDX JSON directly and skips any site
    missing extra1 or with non-numeric/empty lat/lon when cleaned=True.
    We build temp JSON fixtures with blanked/invalid coords to verify.
    """

    def _write_temp_json(self, raw_json_path, modifier):
        """Write a temp CDX JSON with modifier(sites) applied; return its Path."""
        with open(raw_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        modifier(data)
        temp_json = FIXTURE_DIR / "_temp_store_data.json"
        with open(temp_json, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return temp_json

    def test_cleaned_drops_missing_coords(self):
        """cleaned=True must drop stores with null latitude/longitude.

        Blank out one store's lat/lon in the JSON, then verify cleaned=True
        drops it while cleaned=False keeps it (as empty strings).
        """
        target_extra1 = "9527"  # Nelson Woolworths

        def blank_coords(data):
            for detail in data.get("siteDetail", []):
                site = detail.get("site", {})
                if str(site.get("extra1")) == target_extra1:
                    site["latitude"] = None
                    site["longitude"] = None

        temp_json = self._write_temp_json(FIX_STORE_DATA_JSON, blank_coords)
        temp_csv = FIXTURE_DIR / "_temp_cleaned_dropped.csv"
        try:
            # Mock requests to return the temp JSON
            with open(temp_json, "r", encoding="utf-8") as f:
                fixture_data = json.load(f)
            mock_resp = MagicMock()
            mock_resp.json.return_value = fixture_data
            mock_resp.raise_for_status.return_value = None

            with patch("woolworths_setup.JSON_DATA", temp_json), \
                 patch("woolworths_setup.CSV_STORES", temp_csv), \
                 patch("woolworths_setup.requests.get", return_value=mock_resp):
                from woolworths_setup import fetch_store_data
                # cleaned=False keeps all (blank coords allowed)
                stores_full = fetch_store_data(cleaned=False)
                assert len(stores_full) == 5

                # cleaned=True drops the one with blank coords
                stores_clean = fetch_store_data(cleaned=True)
                assert len(stores_clean) == 4
                assert target_extra1 not in {s["id"] for s in stores_clean}
        finally:
            for p in [temp_json, temp_csv]:
                if p.exists():
                    p.unlink()

    def test_cleaned_drops_invalid_string_coords(self):
        """cleaned=True must drop stores with non-numeric latitude/longitude.

        Some exports may contain string values like 'N/A' in coordinate fields.
        """
        target_extra1 = "9246"  # Trafalgar Park Woolworths

        def invalidate_coords(data):
            for detail in data.get("siteDetail", []):
                site = detail.get("site", {})
                if str(site.get("extra1")) == target_extra1:
                    site["latitude"] = "N/A"
                    site["longitude"] = "null"

        temp_json = self._write_temp_json(FIX_STORE_DATA_JSON, invalidate_coords)
        temp_csv = FIXTURE_DIR / "_temp_cleaned_invalid.csv"
        try:
            with open(temp_json, "r", encoding="utf-8") as f:
                fixture_data = json.load(f)
            mock_resp = MagicMock()
            mock_resp.json.return_value = fixture_data
            mock_resp.raise_for_status.return_value = None

            with patch("woolworths_setup.JSON_DATA", temp_json), \
                 patch("woolworths_setup.CSV_STORES", temp_csv), \
                 patch("woolworths_setup.requests.get", return_value=mock_resp):
                from woolworths_setup import fetch_store_data
                # cleaned=False keeps all (invalid coords not filtered at parse time)
                stores_full = fetch_store_data(cleaned=False)
                assert len(stores_full) == 5

                stores_clean = fetch_store_data(cleaned=True)
                assert len(stores_clean) == 4
                assert target_extra1 not in {s["id"] for s in stores_clean}
        finally:
            for p in [temp_json, temp_csv]:
                if p.exists():
                    p.unlink()

    def test_cleaned_drops_empty_string_coords(self):
        """cleaned=True must also drop stores with empty string coordinates."""
        target_extra1 = "9527"

        def empty_coords(data):
            for detail in data.get("siteDetail", []):
                site = detail.get("site", {})
                if str(site.get("extra1")) == target_extra1:
                    site["latitude"] = ""
                    site["longitude"] = ""

        temp_json = self._write_temp_json(FIX_STORE_DATA_JSON, empty_coords)
        temp_csv = FIXTURE_DIR / "_temp_cleaned_empty.csv"
        try:
            with open(temp_json, "r", encoding="utf-8") as f:
                fixture_data = json.load(f)
            mock_resp = MagicMock()
            mock_resp.json.return_value = fixture_data
            mock_resp.raise_for_status.return_value = None

            with patch("woolworths_setup.JSON_DATA", temp_json), \
                 patch("woolworths_setup.CSV_STORES", temp_csv), \
                 patch("woolworths_setup.requests.get", return_value=mock_resp):
                from woolworths_setup import fetch_store_data
                stores_clean = fetch_store_data(cleaned=True)
                assert len(stores_clean) == 4
                assert target_extra1 not in {s["id"] for s in stores_clean}
        finally:
            for p in [temp_json, temp_csv]:
                if p.exists():
                    p.unlink()

    def test_site_without_extra1_skipped(self):
        """Sites missing extra1 must be skipped entirely (no id to key on)."""
        def strip_extra1(data):
            for detail in data.get("siteDetail", []):
                site = detail.get("site", {})
                if str(site.get("extra1")) == "9040":
                    site.pop("extra1", None)

        temp_json = self._write_temp_json(FIX_STORE_DATA_JSON, strip_extra1)
        temp_csv = FIXTURE_DIR / "_temp_no_extra1.csv"
        try:
            with open(temp_json, "r", encoding="utf-8") as f:
                fixture_data = json.load(f)
            mock_resp = MagicMock()
            mock_resp.json.return_value = fixture_data
            mock_resp.raise_for_status.return_value = None

            with patch("woolworths_setup.JSON_DATA", temp_json), \
                 patch("woolworths_setup.CSV_STORES", temp_csv), \
                 patch("woolworths_setup.requests.get", return_value=mock_resp):
                from woolworths_setup import fetch_store_data
                stores = fetch_store_data(cleaned=False)
                assert "9040" not in {s["id"] for s in stores}
                assert len(stores) == 4
        finally:
            for p in [temp_json, temp_csv]:
                if p.exists():
                    p.unlink()

    def test_site_with_null_extra1_skipped(self):
        """Sites whose extra1 is the literal string 'null' must be skipped.

        CDX emits 'null' as a string for missing values; these must not become
        store_ids (they would produce an invalid cw-lrkswrdjp cookie).
        """
        def nullify_extra1(data):
            count = 0
            for detail in data.get("siteDetail", []):
                site = detail.get("site", {})
                if str(site.get("extra1")) == "9290" and count < 1:
                    site["extra1"] = "null"
                    count += 1
            assert count == 1, "expected to null one store"

        temp_json = self._write_temp_json(FIX_STORE_DATA_JSON, nullify_extra1)
        temp_csv = FIXTURE_DIR / "_temp_null_extra1.csv"
        try:
            with open(temp_json, "r", encoding="utf-8") as f:
                fixture_data = json.load(f)
            mock_resp = MagicMock()
            mock_resp.json.return_value = fixture_data
            mock_resp.raise_for_status.return_value = None

            with patch("woolworths_setup.JSON_DATA", temp_json), \
                 patch("woolworths_setup.CSV_STORES", temp_csv), \
                 patch("woolworths_setup.requests.get", return_value=mock_resp):
                from woolworths_setup import fetch_store_data
                stores = fetch_store_data(cleaned=False)
                assert "null" not in {s["id"] for s in stores}
                assert "9290" not in {s["id"] for s in stores}
                assert len(stores) == 4
        finally:
            for p in [temp_json, temp_csv]:
                if p.exists():
                    p.unlink()


class TestExcludedStores:
    """Tests for the EXCLUDED_STORE_IDS filter (shut-down stores)."""

    def test_excluded_stores_constant_exists(self):
        """EXCLUDED_STORE_IDS must contain shutdown stores 9285 and 9035."""
        from woolworths_setup import EXCLUDED_STORE_IDS
        assert "9285" in EXCLUDED_STORE_IDS
        assert "9035" in EXCLUDED_STORE_IDS

    def test_shut_down_store_filtered(self):
        """fetch_store_data() must skip stores in EXCLUDED_STORE_IDS."""
        def add_excluded_store(data):
            sites = data.get("siteDetail", [])
            if sites:
                site = sites[0].get("site", {})
                site["extra1"] = "9285"
                site["name"] = "Te Atatu Woolworths"

        temp_json = FIXTURE_DIR / "_temp_excluded_store.json"
        try:
            with open(FIX_STORE_DATA_JSON, "r", encoding="utf-8") as f:
                fixture_data = json.load(f)
            add_excluded_store(fixture_data)
            with open(temp_json, "w", encoding="utf-8") as f:
                json.dump(fixture_data, f)

            mock_resp = MagicMock()
            mock_resp.json.return_value = fixture_data
            mock_resp.raise_for_status.return_value = None

            temp_csv = FIXTURE_DIR / "_temp_excluded_output.csv"
            with patch("woolworths_setup.JSON_DATA", temp_json), \
                 patch("woolworths_setup.CSV_STORES", temp_csv), \
                 patch("woolworths_setup.requests.get", return_value=mock_resp):
                from woolworths_setup import fetch_store_data
                stores = fetch_store_data(cleaned=False)
                assert "9285" not in {s["id"] for s in stores}
                assert len(stores) == 4  # 5 original minus 1 excluded
        finally:
            for p in [temp_json, temp_csv]:
                if p.exists():
                    p.unlink()
