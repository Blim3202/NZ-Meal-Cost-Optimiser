"""Phase 2: store catalogue + store-id normalisation.

Loads the store list from Supabase (`stores` table, incl. `pickup_address_id`)
when configured, or falls back to the on-disk CSV/JSON files in `data/`.

Primary responsibility for the worker: **store-id normalisation**. The
Woolworths pipeline (`optimizer_utils.build_woolworths_row`) writes `store_id =
pickupAddressId` (extra2), but `stores.store_id` = `fulfilmentStoreId` (extra1).
The writer calls `normalize_store_id("Woolworths", raw_id)` to reconcile this
so Supabase `results` rows join to `stores`; Foodstuffs UUIDs pass through.
"""
from __future__ import annotations

import csv
import json
import threading
from pathlib import Path
from typing import Optional

import core.paths  # noqa: F401
from core.paths import DATA_DIR, SCRIPTS_DIR
from optimizer_utils import geocode, haversine


def _csv_lat(row):
    for k in ("lat", "latitude"):
        v = row.get(k)
        if v:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


def _csv_lon(row):
    for k in ("lon", "longitude"):
        v = row.get(k)
        if v:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


class StoreRegistry:
    def __init__(self, supabase=None) -> None:
        self._supabase = supabase
        self._stores: list[dict] = []
        self._pid2fsid: dict[str, str] = {}
        self._lock = threading.Lock()
        self._loaded = False

    def load(self) -> list[dict]:
        if self._loaded:
            return self._stores
        with self._lock:
            if self._loaded:
                return self._stores
            stores: list[dict] | None = None
            if self._supabase:
                try:
                    stores = self._load_from_db()
                except Exception as e:  # noqa: BLE001
                    import logging
                    logging.getLogger("fastapi.worker").warning(
                        "StoreRegistry DB load failed (%s); falling back to CSV/JSON.", e
                    )
                    stores = None
            if not stores:
                stores = self._load_fallback()
            # dedup by store_id (keep first) — mirrors seed_phase1.py so fallback
            # counts match the seeded DB (e.g. 148 NW + 57 PS + 177 WW = 382).
            seen = set()
            stores = [s for s in stores if s["store_id"] not in seen and not seen.add(s["store_id"])]
            self._stores = stores or []
            for s in self._stores:
                pa = s.get("pickup_address_id")
                if s.get("brand") == "Woolworths" and pa:
                    self._pid2fsid[str(pa)] = s["store_id"]
            self._loaded = True
        return self._stores

    def _load_from_db(self) -> list[dict]:
        rows = (
            self._supabase
            .from_("stores")
            .select("store_id,brand,name,address,city,region,lat,lon,banner,pickup_address_id")
            .execute()
            .data
        ) or []
        return rows

    def _load_fallback(self) -> list[dict]:
        stores: list[dict] = []
        for brand, fname, brand_label in (
            ("NewWorld", "newworld_stores.csv", "NewWorld"),
            ("PaknSave", "paknsave_stores.csv", "PaknSave"),
        ):
            path = DATA_DIR / fname
            if not path.exists():
                continue
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    stores.append({
                        "store_id": r["store_id"],
                        "brand": brand_label,
                        "name": r.get("name", ""),
                        "address": r.get("address", ""),
                        "city": r.get("city", ""),
                        "region": r.get("region", ""),
                        "lat": _csv_lat(r),
                        "lon": _csv_lon(r),
                        "banner": r.get("banner"),
                        "pickup_address_id": None,
                    })
        ww = DATA_DIR / "woolworths_store_data.json"
        if ww.exists():
            with open(ww, encoding="utf-8") as f:
                data = json.load(f)
            for detail in data.get("siteDetail", []):
                site = detail.get("site", {})
                e1 = site.get("extra1")
                e2 = site.get("extra2")
                if not e1 or str(e1) == "null":
                    continue
                stores.append({
                    "store_id": str(e1),
                    "brand": "Woolworths",
                    "name": site.get("name", ""),
                    "address": site.get("addressLine1", ""),
                    "city": site.get("suburb", ""),
                    "region": site.get("state", ""),
                    "lat": float(site["latitude"]) if site.get("latitude") not in (None, "null") else None,
                    "lon": float(site["longitude"]) if site.get("longitude") not in (None, "null") else None,
                    "banner": None,
                    "pickup_address_id": str(e2) if e2 not in (None, "null") else None,
                })
        return stores

    def get(self, store_id: str) -> Optional[dict]:
        for s in self.load():
            if s["store_id"] == store_id:
                return s
        return None

    def normalize_store_id(self, brand: str, raw_id: str) -> str:
        """Return the store_id that matches `stores.store_id` for this brand.

        - Foodstuffs: identity (UUID already matches).
        - Woolworths: map pickupAddressId (extra2) -> fulfilmentStoreId (extra1);
          pass through if raw_id is already a known fulfilmentStoreId.
        """
        if not raw_id:
            return raw_id
        if brand == "Woolworths":
            return self._pid2fsid.get(str(raw_id), raw_id)
        return raw_id

    def nearby(self, address: str, brand: Optional[str] = None, radius_km: float = 5.0) -> list[dict]:
        """Geocode `address` and return stores within `radius_km` (sorted by distance).

        NOTE: geocode() uses Nominatim (1 req/s). Keep the FastAPI worker single-
        threaded; if /stores/nearby is ever exposed as a concurrent route, add
        a rate-limiting lock around geocode. (Phase 3 concern; not called by the
        worker core path, which delegates nearby-finding to the brand optimizers.)
        """
        lat, lon = geocode(address)
        if lat is None or lon is None:
            return []
        out = []
        for s in self.load():
            if brand and s.get("brand") != brand:
                continue
            if s["lat"] is None or s["lon"] is None:
                continue
            d = haversine(lat, lon, s["lat"], s["lon"])
            if d <= radius_km:
                s2 = dict(s)
                s2["distance_km"] = round(d, 2)
                out.append(s2)
        out.sort(key=lambda s: s["distance_km"])
        return out

    def store_ids_near(self, address: str, brand: str, radius_km: float = 5.0) -> set:
        return {s["store_id"] for s in self.nearby(address, brand, radius_km)}
