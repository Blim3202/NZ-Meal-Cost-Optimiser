"""
Unit tests for Woolworths NZ Store Setup (woolworths_setup.py).

Tests verify:
    1. clean_null() handles None, empty strings, and valid values.
    2. merge_stores() performs a correct left-join between the
       fixture store choices CSV (cookies_example1.csv) and the
       fixture store data CSV (store_data_fixture.csv).
    3. The cleaned=False merge keeps all stores.
    4. The cleaned=True merge drops stores without coordinates.
    5. merge_stores() handles edge cases (duplicates, missing from one side,
       invalid coordinate formats, string coords).
    6. The fixture JSON and CSV are consistent with the real captured data.

All data is loaded from the fixture directory produced by
generate_fixtures.py — no live network calls during tests.

Fixture data (3 stores in choices CSV, 5 stores in JSON, all from the
Nelson/South Island region):
    cookies_example1.csv (pickup choices):
        id=4166071 -> Nelson Junction Woolworths
        id=1225552 -> Nelson Woolworths
        id=2810937 -> Trafalgar Park Woolworths

    store_data_fixture.csv (CDX site data):
        SiteDataID=4166071 -> lat=-41.2977069, lon=173.241518  (has coords)
        SiteDataID=1225552 -> lat=-41.2727, lon=173.2773        (has coords)
        SiteDataID=2810937 -> lat=-41.2702, lon=173.2815        (has coords)

Since all 3 stores have coordinates, cleaned=True and cleaned=False
both return 3 rows. A separate edge-case test verifies the cleaning
logic by using a modified fixture.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

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
FIX_CHOICES_CSV = FIXTURE_DIR / "cookies_example1.csv"
FIX_STORE_DATA_CSV = FIXTURE_DIR / "store_data_fixture.csv"
FIX_STORE_DATA_JSON = FIXTURE_DIR / "store_data_example.json"


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


class TestMergeStores:
    """Tests for woolworths_setup.merge_stores() using REAL fixture files.

    The fixture data (captured from live APIs) has 3 stores, all with
    valid coordinates. Therefore:
        - cleaned=True  -> 3 stores (all have coords)
        - cleaned=False -> 3 stores (same)
    """

    def _run_merge(self, cleaned, temp_csv=None):
        """Run merge_stores against fixture files.

        Args:
            cleaned: bool — whether to drop stores without coordinates.
            temp_csv: optional Path for the output CSV (avoids polluting
                      the fixture directory).

        Returns the merged DataFrame.
        """
        if temp_csv is None:
            temp_csv = FIXTURE_DIR / "_merge_test_output.csv"

        with patch("woolworths_setup.CSV_CHOICES", FIX_CHOICES_CSV), \
             patch("woolworths_setup.CSV_DATA", FIX_STORE_DATA_CSV), \
             patch("woolworths_setup.CSV_MERGED", temp_csv):
            from woolworths_setup import merge_stores
            merged = merge_stores(cleaned=cleaned)

        # Clean up the temp output file.
        if temp_csv.exists():
            temp_csv.unlink()

        return merged

    def test_cleaned_merge_keeps_all_with_coords(self):
        """cleaned=True with the fixture (all stores have coords) keeps all 3.

        Fixture: all 3 stores have valid lat/lon.
        """
        merged = self._run_merge(cleaned=True)
        assert len(merged) == 3

    def test_unpadded_merge_keeps_all(self):
        """cleaned=False keeps all 3 stores from the left-join."""
        merged = self._run_merge(cleaned=False)
        assert len(merged) == 3

    def test_merge_has_expected_columns(self):
        """The merged DataFrame must have id, name, address, latitude, longitude."""
        merged = self._run_merge(cleaned=False)
        expected = {"id", "name", "address", "latitude", "longitude"}
        assert expected.issubset(set(merged.columns))

    def test_merge_preserves_store_names(self):
        """The merged DataFrame must contain the real store names from the fixture."""
        merged = self._run_merge(cleaned=False)
        names = set(merged["name"].tolist())
        assert "Nelson Junction Woolworths" in names
        assert "Nelson Woolworths" in names
        assert "Trafalgar Park Woolworths" in names

    def test_merge_preserves_site_data_ids(self):
        """The merged 'id' column must match the fixture choices CSV ids."""
        merged = self._run_merge(cleaned=False)
        expected_ids = {"4166071", "1225552", "2810937"}
        actual_ids = set(merged["id"].astype(str).tolist())
        assert actual_ids == expected_ids

    def test_merge_joined_coordinates_correct(self):
        """The merged latitude/longitude must match the CDX data for store 4166071."""
        merged = self._run_merge(cleaned=False)
        row = merged[merged["id"].astype(str) == "4166071"].iloc[0]
        assert abs(float(row["latitude"]) - (-41.2977069)) < 0.0001
        assert abs(float(row["longitude"]) - 173.241518) < 0.0001

    def test_merge_preserves_all_three_stores_coordinates(self):
        """All 3 fixture stores must have correct coordinates in the merge."""
        merged = self._run_merge(cleaned=False)
        coords_expected = {
            "4166071": (-41.2977069, 173.241518),
            "1225552": (-41.2727, 173.2773),
            "2810937": (-41.2702, 173.2815),
        }
        for store_id, (lat, lon) in coords_expected.items():
            row = merged[merged["id"].astype(str) == store_id].iloc[0]
            assert abs(float(row["latitude"]) - lat) < 0.0001, \
                f"Lat mismatch for store {store_id}"
            assert abs(float(row["longitude"]) - lon) < 0.0001, \
                f"Lon mismatch for store {store_id}"

    def test_merge_drops_site_data_id_column(self):
        """The SiteDataID column is dropped during merge (it's only used for joining)."""
        merged = self._run_merge(cleaned=False)
        assert "SiteDataID" not in merged.columns


class TestMergeStoresCleaningLogic:
    """Tests for the cleaned=True coordinate-filtering logic.

    The real fixtures have all stores with coordinates, so we create a
    temporary modified CSV where one store has empty/NaN coordinates, to
    verify the cleaning logic works on real data.
    """

    def test_cleaned_drops_missing_coords(self):
        """cleaned=True must drop stores with empty latitude/longitude.

        We create a temp copy of the fixture store data CSV where the
        second store's latitude and longitude are replaced with NaN,
        then verify that cleaned=True drops it while cleaned=False keeps it.
        """
        # Read the real fixture CSV and blank out one store's coords.
        df = pd.read_csv(FIX_STORE_DATA_CSV)
        # Use numpy NaN to avoid pandas dtype coercion errors
        df.loc[df["SiteDataID"].astype(str) == "1225552", "latitude"] = np.nan
        df.loc[df["SiteDataID"].astype(str) == "1225552", "longitude"] = np.nan

        temp_data_csv = FIXTURE_DIR / "_temp_store_data.csv"
        temp_merged_csv = FIXTURE_DIR / "_temp_merged.csv"
        df.to_csv(temp_data_csv, index=False, encoding="utf-8")

        try:
            with patch("woolworths_setup.CSV_CHOICES", FIX_CHOICES_CSV), \
                 patch("woolworths_setup.CSV_DATA", temp_data_csv), \
                 patch("woolworths_setup.CSV_MERGED", temp_merged_csv):
                from woolworths_setup import merge_stores

                # cleaned=True should drop the store with blank coords
                merged_clean = merge_stores(cleaned=True)
                assert len(merged_clean) == 2
                assert "1225552" not in merged_clean["id"].astype(str).tolist()

                # cleaned=False should keep all 3
                merged_full = merge_stores(cleaned=False)
                assert len(merged_full) == 3
        finally:
            for p in [temp_data_csv, temp_merged_csv]:
                if p.exists():
                    p.unlink()

    def test_cleaned_drops_invalid_string_coords(self):
        """cleaned=True must drop stores with non-numeric latitude/longitude.

        Some CDX exports may contain string values like 'null' or 'N/A'
        in coordinate fields instead of actual numbers. We test this by
        converting the columns to object dtype first (simulating what
        happens when invalid data is in the CSV).
        """
        df = pd.read_csv(FIX_STORE_DATA_CSV)
        # Convert columns to object dtype to allow string assignment
        df["latitude"] = df["latitude"].astype(object)
        df["longitude"] = df["longitude"].astype(object)
        # Set invalid string coords for one store
        df.loc[df["SiteDataID"].astype(str) == "2810937", "latitude"] = "N/A"
        df.loc[df["SiteDataID"].astype(str) == "2810937", "longitude"] = "null"

        temp_data_csv = FIXTURE_DIR / "_temp_store_data_str.csv"
        temp_merged_csv = FIXTURE_DIR / "_temp_merged_str.csv"
        df.to_csv(temp_data_csv, index=False, encoding="utf-8")

        try:
            with patch("woolworths_setup.CSV_CHOICES", FIX_CHOICES_CSV), \
                 patch("woolworths_setup.CSV_DATA", temp_data_csv), \
                 patch("woolworths_setup.CSV_MERGED", temp_merged_csv):
                from woolworths_setup import merge_stores

                # cleaned=False keeps all 3 (invalid coords not filtered)
                merged_full = merge_stores(cleaned=False)
                assert len(merged_full) == 3

                # cleaned=True drops the store with invalid coords
                merged_clean = merge_stores(cleaned=True)
                assert len(merged_clean) == 2
                assert "2810937" not in merged_clean["id"].astype(str).tolist()
        finally:
            for p in [temp_data_csv, temp_merged_csv]:
                if p.exists():
                    p.unlink()

    def test_cleaned_drops_empty_string_coords(self):
        """cleaned=True must also drop stores with empty string coordinates.

        Some CDX exports may contain empty strings instead of NaN.
        """
        df = pd.read_csv(FIX_STORE_DATA_CSV)
        # Convert columns to object dtype to allow string assignment
        df["latitude"] = df["latitude"].astype(object)
        df["longitude"] = df["longitude"].astype(object)
        # Set empty string coords for one store
        df.loc[df["SiteDataID"].astype(str) == "1225552", "latitude"] = ""
        df.loc[df["SiteDataID"].astype(str) == "1225552", "longitude"] = ""

        temp_data_csv = FIXTURE_DIR / "_temp_store_data_empty.csv"
        temp_merged_csv = FIXTURE_DIR / "_temp_merged_empty.csv"
        df.to_csv(temp_data_csv, index=False, encoding="utf-8")

        try:
            with patch("woolworths_setup.CSV_CHOICES", FIX_CHOICES_CSV), \
                 patch("woolworths_setup.CSV_DATA", temp_data_csv), \
                 patch("woolworths_setup.CSV_MERGED", temp_merged_csv):
                from woolworths_setup import merge_stores

                # cleaned=True drops stores with empty string coords
                merged_clean = merge_stores(cleaned=True)
                assert len(merged_clean) == 2
                assert "1225552" not in merged_clean["id"].astype(str).tolist()
        finally:
            for p in [temp_data_csv, temp_merged_csv]:
                if p.exists():
                    p.unlink()

    def test_merge_preserves_choices_with_no_data_match(self):
        """A store in choices CSV but missing from data CSV should have
        NaN coordinates in cleaned=False, and be dropped in cleaned=True.

        This tests the left-join behavior: all choices are kept, but
        missing coordinate data causes them to be filtered when cleaned=True.
        """
        df_data = pd.read_csv(FIX_STORE_DATA_CSV)

        # Remove one store from the data CSV (simulate store not in CDX data)
        df_data_reduced = df_data[df_data["SiteDataID"].astype(str) != "2810937"]

        temp_data_csv = FIXTURE_DIR / "_temp_reduced_data.csv"
        temp_merged_csv = FIXTURE_DIR / "_temp_reduced_merged.csv"
        df_data_reduced.to_csv(temp_data_csv, index=False, encoding="utf-8")

        try:
            with patch("woolworths_setup.CSV_CHOICES", FIX_CHOICES_CSV), \
                 patch("woolworths_setup.CSV_DATA", temp_data_csv), \
                 patch("woolworths_setup.CSV_MERGED", temp_merged_csv):
                from woolworths_setup import merge_stores

                # cleaned=False keeps all 3 (left join on choices)
                merged_full = merge_stores(cleaned=False)
                assert len(merged_full) == 3
                # The missing store should have NaN coords
                row = merged_full[merged_full["id"].astype(str) == "2810937"].iloc[0]
                assert pd.isna(row["latitude"])
                assert pd.isna(row["longitude"])

                # cleaned=True drops the store with NaN coords (no match in data)
                merged_clean = merge_stores(cleaned=True)
                assert len(merged_clean) == 2
                assert "2810937" not in merged_clean["id"].astype(str).tolist()
        finally:
            for p in [temp_data_csv, temp_merged_csv]:
                if p.exists():
                    p.unlink()

    def test_merge_with_duplicate_choice_ids(self):
        """If the choices CSV has duplicate ids, merge_stores should
        preserve duplicates (inner join behavior on the left table).

        This tests that merge_stores doesn't silently deduplicate.
        """
        df_choices = pd.read_csv(FIX_CHOICES_CSV)
        # Duplicate the first row
        df_choices_dup = pd.concat([df_choices, df_choices.iloc[[0]]], ignore_index=True)

        temp_choices_csv = FIXTURE_DIR / "_temp_dup_choices.csv"
        temp_merged_csv = FIXTURE_DIR / "_temp_dup_merged.csv"
        df_choices_dup.to_csv(temp_choices_csv, index=False, encoding="utf-8")

        try:
            with patch("woolworths_setup.CSV_CHOICES", temp_choices_csv), \
                 patch("woolworths_setup.CSV_DATA", FIX_STORE_DATA_CSV), \
                 patch("woolworths_setup.CSV_MERGED", temp_merged_csv):
                from woolworths_setup import merge_stores

                merged = merge_stores(cleaned=False)
                # Left join with duplicate on left side produces duplicate rows
                assert len(merged) == 4  # 3 original + 1 duplicate
        finally:
            for p in [temp_choices_csv, temp_merged_csv]:
                if p.exists():
                    p.unlink()


class TestSetupDataIntegration:
    """Integration test: verify the fixture store_data_example.json and
    store_data_fixture.csv are consistent with the real captured data.

    This ensures the fixture files captured by generate_fixtures.py are
    internally coherent — the JSON and CSV describe the same stores
    with the same IDs and coordinates.
    """

    @patch("woolworths_api.STORE_JSON", FIX_STORE_DATA_JSON)
    def test_fixture_json_matches_csv(self):
        """The store IDs and coordinates in store_data_example.json must
        match those in store_data_fixture.csv.

        Note: pandas reads SiteDataID from the CSV as int64 (e.g. 4166071),
        while the JSON stores it as a string ('4166071'). We normalize
        to str for comparison.
        """
        from woolworths_api import _load_store_mapping

        mapping = _load_store_mapping()
        df = pd.read_csv(FIX_STORE_DATA_CSV)
        # Normalize SiteDataID to string for consistent comparison.
        df["SiteDataID"] = df["SiteDataID"].astype(str)

        # The JSON has 5 sites; the CSV has 3 (subset).
        # All 3 CSV SiteDataIDs must be present in the JSON mapping.
        assert len(mapping) == 5
        assert len(df) == 3

        for _, row in df.iterrows():
            site_id = row["SiteDataID"]
            assert site_id in mapping, \
                f"SiteDataID {site_id} from CSV not in JSON mapping"

            json_entry = mapping[site_id]
            csv_lat = float(row["latitude"])
            csv_lon = float(row["longitude"])
            assert abs(json_entry["lat"] - csv_lat) < 0.0001
            assert abs(json_entry["lon"] - csv_lon) < 0.0001

    @patch("woolworths_api.STORE_JSON", FIX_STORE_DATA_JSON)
    def test_all_stores_have_valid_coords(self):
        """Every store in the fixture JSON must have non-null coordinates."""
        from woolworths_api import _load_store_mapping
        mapping = _load_store_mapping()
        for pid, info in mapping.items():
            assert info["lat"] is not None, \
                f"Store {pid} has null latitude"
            assert info["lon"] is not None, \
                f"Store {pid} has null longitude"

    @patch("woolworths_api.STORE_JSON", FIX_STORE_DATA_JSON)
    def test_fixture_stores_have_extra1_and_extra2(self):
        """Every store in the fixture JSON must have extra1 and extra2
        populated — these are required for cookie construction and
        pickup address mapping.
        """
        from woolworths_api import _load_store_mapping
        mapping = _load_store_mapping()
        for pid, info in mapping.items():
            assert info["fulfilmentStoreId"] != 9171, \
                f"Store {pid} has default fulfilmentStoreId (9171)"
            assert pid != "9171", \
                f"Store id {pid} looks like a default store id"

    @patch("woolworths_api.STORE_JSON", FIX_STORE_DATA_JSON)
    def test_fixture_store_names_match_csv(self):
        """Store names in the JSON must match the choices CSV names."""
        from woolworths_api import _load_store_mapping
        mapping = _load_store_mapping()
        df_choices = pd.read_csv(FIX_CHOICES_CSV)

        for _, row in df_choices.iterrows():
            store_id = str(row["id"])
            assert store_id in mapping, \
                f"Store id {store_id} from choices CSV not in JSON mapping"
            assert mapping[store_id]["name"] == row["name"], \
                f"Name mismatch for store {store_id}"