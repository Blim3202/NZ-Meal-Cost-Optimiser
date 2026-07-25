"""
Pak'nSave API Module
====================
Unified API client supporting two backends:
- EDGE API (default): Two-pass pipeline — relevance via Algolia products-index, then per-store pricing via paginated/products
- MOBILE API (fallback): Single-pass search via Foodstuffs mobile endpoint

Both backends use the same store data (from paknsave_setup.py output) and dish ingredients.
"""

import requests
import cloudscraper
import json
import time
import math
from pathlib import Path
from typing import Optional, Literal

# ─── Constants ──────────────────────────────────────────────────────────────
WEB_BASE = "https://www.paknsave.co.nz"
EDGE_BASE = "https://api-prod.paknsave.co.nz/v1/edge"
MOBILE_BASE = "https://api-prod.prod.fsniwaikato.kiwi/prod"

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STORES_CSV = DATA_DIR / "paknsave_stores.csv"
STORES_JSON = DATA_DIR / "paknsave_stores.json"

# Dish ingredients (21 dishes) — matches PaknSave_prototype.py and woolworths_optimizer.py
DISH_INGREDIENTS = {
    "spaghetti bolognese": ["beef mince", "spaghetti pasta", "canned tomatoes", "onion", "carrot", "garlic", "mixed herbs"],
    "chicken stir fry": ["chicken breast", "stir fry vegetables", "soy sauce", "rice noodles"],
    "beef stir fry": ["beef strips", "stir fry vegetables", "soy sauce", "rice noodles"],
    "roast lamb": ["lamb roast", "potato", "carrot", "broccoli", "stock"],
    "chicken curry": ["chicken thigh", "curry paste", "coconut milk", "rice", "onion"],
    "beef curry": ["diced beef", "curry paste", "coconut milk", "rice", "onion"],
    "fish and chips": ["fish fillet", "potato", "oil"],
    "nachos": ["beef mince", "tortilla chips", "cheese", "beans", "sour cream"],
    "pumpkin soup": ["pumpkin", "onion", "cream", "stock", "bread"],
    "tacos": ["beef mince", "taco shells", "lettuce", "tomato", "cheese", "sour cream"],
    "lamb chops": ["lamb chops", "potato", "mint sauce", "mixed vegetables"],
    "butter chicken": ["chicken thigh", "butter chicken sauce", "rice", "cream"],
    "lasagne": ["beef mince", "lasagne sheets", "cheese", "canned tomatoes", "milk", "butter", "flour"],
    "shepherd's pie": ["beef mince", "potato", "carrot", "peas", "stock"],
    "pizza": ["pizza base", "pizza sauce", "cheese", "pepperoni"],
    "vegie stir fry": ["stir fry vegetables", "tofu", "soy sauce", "rice noodles", "garlic"],
    "frittata": ["eggs", "potato", "onion", "cheese", "milk"],
    "pancakes": ["flour", "eggs", "milk", "sugar", "butter"],
    "chicken soup": ["chicken breast", "carrot", "onion", "celery", "stock", "pasta"],
    "tomato pasta": ["pasta", "canned tomatoes", "garlic", "olive oil", "mixed herbs", "cheese"],
    "chicken katsu": ["chicken breast", "flour", "eggs", "bread", "rice", "katsu sauce"],
}

# ─── Utilities ──────────────────────────────────────────────────────────────

def load_stores() -> list[dict]:
    """Load store list from CSV/JSON produced by paknsave_setup.py."""
    import csv
    stores = []
    if STORES_CSV.exists():
        with open(STORES_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    row["latitude"] = float(row["latitude"])
                    row["longitude"] = float(row["longitude"])
                    stores.append(row)
                except (ValueError, KeyError):
                    continue
    return stores


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def geocode(address: str) -> tuple[Optional[float], Optional[float]]:
    """Geocode a NZ address via Nominatim (rate-limited: 1 req/sec)."""
    time.sleep(1.1)  # respect Nominatim rate limit
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            headers={"User-Agent": "NZMealCostOptimizer/1.0"},
            params={"q": address, "format": "json", "limit": 1},
            timeout=15,
        )
        if r.status_code == 200 and r.json():
            loc = r.json()[0]
            return float(loc["lat"]), float(loc["lon"])
    except Exception:
        pass
    return None, None


def find_nearby_stores(
    user_lat: float, user_lon: float, radius_km: float = 5.0
) -> list[dict]:
    """Return stores within radius_km, sorted by distance."""
    stores = load_stores()
    nearby = []
    for s in stores:
        try:
            d = haversine(user_lat, user_lon, s["latitude"], s["longitude"])
            if d <= radius_km:
                nearby.append({**s, "distance_km": round(d, 2)})
        except (KeyError, ValueError):
            continue
    nearby.sort(key=lambda x: x["distance_km"])
    return nearby


def get_ingredients(dish_name: str) -> list[str]:
    """Get ingredient list for a dish (case-insensitive)."""
    return DISH_INGREDIENTS.get(dish_name.lower().strip(), [dish_name])


# ─── EDGE API (Two-Pass) ────────────────────────────────────────────────────

class PaknSaveEdgeAPI:
    """
    Pak'nSave Edge API client using website JWT authentication.
    Two-pass pipeline:
      PASS 1: POST /v1/edge/search/products/query/index/products-index (relevance + _highlightResult)
      PASS 2: POST /v1/edge/search/paginated/products (per-store pricing with filters + PRICE_ASC)
    """

    def __init__(self):
        self.token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": WEB_BASE,
            "Referer": WEB_BASE + "/",
        })

    # ── Authentication ──────────────────────────────────────────────────────
    def authenticate(self) -> str:
        """Get website JWT (fs-user-token) via the public website flow."""
        self.session.get(WEB_BASE, timeout=30)
        r = self.session.post(
            f"{WEB_BASE}/api/user/get-current-user",
            json={},
            timeout=30,
        )
        r.raise_for_status()
        self.token = self.session.cookies.get("fs-user-token")
        if not self.token:
            raise RuntimeError("Failed to obtain fs-user-token cookie")
        return self.token

    def _auth_headers(self) -> dict:
        if not self.token:
            self.authenticate()
        return {
            "Authorization": f"Bearer {self.token}",
            "access_token": self.token,
            "Content-Type": "application/json",
            "Origin": WEB_BASE,
            "Referer": f"{WEB_BASE}/shop",
            "User-Agent": "Mozilla/5.0",
        }

    def _store_cookies(self, store_id: str, region: str = "NI") -> dict:
        return {
            "eCom_STORE_ID": store_id,
            "STORE_ID_V2": f"{store_id}|False",
            "Region": region,
        }

    # ── Store Listing ───────────────────────────────────────────────────────
    def get_stores(self) -> list[dict]:
        """Fetch all stores from Edge API (requires auth)."""
        headers = self._auth_headers()
        r = requests.get(f"{EDGE_BASE}/store", headers=headers, timeout=30)
        r.raise_for_status()
        return r.json().get("stores", [])

    # ── PASS 1: Relevance Search ────────────────────────────────────────────
    def pass1_relevance_search(
        self,
        store_id: str,
        query: str,
        max_hits: int = 20,
        region: str = "NI",
    ) -> list[str]:
        """
        Search products-index for relevance matches.
        Returns productIDs where _highlightResult has non-empty matchedWords.
        Filters out pet food (category1: Dog, Cat, Pet).
        """
        headers = self._auth_headers()
        cookies = self._store_cookies(store_id, region)
        payload = {
            "algoliaQuery": {"query": query},
            "page": 0,
            "hitsPerPage": max_hits,
            "storeId": store_id,
        }
        r = requests.post(
            f"{EDGE_BASE}/search/products/query/index/products-index",
            headers=headers,
            json=payload,
            cookies=cookies,
            timeout=30,
        )
        r.raise_for_status()
        hits = r.json().get("hits", [])

        pet_categories = {"Dog", "Cat", "Pet"}
        product_ids = []
        for h in hits:
            hr = h.get("_highlightResult", {})
            matched = any(
                isinstance(v, dict) and v.get("matchedWords")
                for v in hr.values()
            )
            cat1 = h.get("category1", [])
            if matched and not any(c in pet_categories for c in cat1):
                product_ids.append(h["productID"])
        return product_ids

    # ── PASS 2: Per-Store Pricing ───────────────────────────────────────────
    def pass2_per_store_pricing(
        self,
        store_id: str,
        query: str,
        product_ids: list[str],
        hits_per_page: int = 50,
        region: str = "NI",
    ) -> list[dict]:
        """
        Get per-store pricing for specific productIDs.
        Uses Algolia filter syntax: productID:xxx OR productID:yyy
        Sorts by PRICE_ASC (cheapest first at this store).
        Returns list of product dicts with singlePrice.price (cents) and promotions.
        """
        if not product_ids:
            return []

        headers = self._auth_headers()
        cookies = self._store_cookies(store_id, region)
        filter_str = " OR ".join(f"productID:{pid}" for pid in product_ids)
        payload = {
            "algoliaQuery": {"query": query, "filters": filter_str},
            "page": 0,
            "hitsPerPage": hits_per_page,
            "storeId": store_id,
            "sortOrder": "PRICE_ASC",
        }
        r = requests.post(
            f"{EDGE_BASE}/search/paginated/products",
            headers=headers,
            json=payload,
            cookies=cookies,
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("products", [])

    # ── Combined Two-Pass Search ────────────────────────────────────────────
    def search_ingredient(
        self,
        store_id: str,
        ingredient: str,
        max_relevance: int = 20,
        region: str = "NI",
    ) -> list[dict]:
        """Full two-pass search for one ingredient at one store."""
        product_ids = self.pass1_relevance_search(store_id, ingredient, max_relevance, region)
        return self.pass2_per_store_pricing(store_id, ingredient, product_ids, region=region)

    # ── Price Extraction ────────────────────────────────────────────────────
    @staticmethod
    def extract_price(product: dict) -> Optional[float]:
        """Extract final price in dollars (promo if available, else regular)."""
        sp = product.get("singlePrice", {})
        price_cents = sp.get("price")
        promo = product.get("promotions", [])
        promo_val = promo[0].get("rewardValue") if promo else None
        final_cents = promo_val if promo_val is not None else price_cents
        return final_cents / 100.0 if final_cents else None

    @staticmethod
    def extract_unit_price(product: dict) -> Optional[str]:
        """Extract unit price string (e.g., '$10.00/kg')."""
        sp = product.get("singlePrice", {})
        return sp.get("unitPrice") or sp.get("pricePerUnit") or ""

    @staticmethod
    def get_product_name(product: dict) -> str:
        return product.get("name") or product.get("displayName") or ""

    @staticmethod
    def get_product_size(product: dict) -> str:
        return product.get("displayName") or product.get("size") or ""


# ─── MOBILE API (Single-Pass, Legacy Fallback) ──────────────────────────────

class PaknSaveMobileAPI:
    """
    Pak'nSave Mobile API client (legacy, fallback).
    Uses Foodstuffs mobile endpoint with guest token auth.
    Single search per ingredient per store; no relevance visibility.
    """

    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self._token: Optional[str] = None

    def _ensure_token(self):
        if self._token:
            return
        r = self.scraper.post(
            f"{MOBILE_BASE}/mobile/user/login/guest",
            json={"banner": "PNS"},
            headers={"User-Agent": "PAKnSAVEApp/4.32.0", "Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]

    def _auth_headers(self) -> dict:
        self._ensure_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "access_token": self._token,
            "User-Agent": "PAKnSAVEApp/4.32.0",
            "Content-Type": "application/json",
        }

    def search_products(self, store_id: str, query: str) -> Optional[list[dict]]:
        """Search products at a store via mobile API. Returns raw product list."""
        self._ensure_token()
        r = self.scraper.post(
            f"{MOBILE_BASE}/mobile/ecomm-products/PNS/{store_id}/search?q={query}",
            headers=self._auth_headers(),
            json=[],
        )
        if r.status_code == 200:
            data = r.json()
            # Mobile API returns list directly, not wrapped in "products" key
            return data if isinstance(data, list) else data.get("products", [])
        return None

    def get_stores(self) -> dict:
        """Fetch store list from mobile API. Returns {store_id: store_dict}."""
        self._ensure_token()
        r = self.scraper.get(f"{MOBILE_BASE}/mobile/store/physical", headers=self._auth_headers())
        if r.status_code == 200:
            return {s["id"]: s for s in r.json()["stores"]}
        return {}

    @staticmethod
    def extract_price(product: dict) -> Optional[float]:
        """Price in dollars (from cents)."""
        price_cents = product.get("price")
        return price_cents / 100.0 if price_cents and price_cents > 0 else None

    @staticmethod
    def extract_unit_price(product: dict) -> str:
        return product.get("units", "") or ""

    @staticmethod
    def get_product_name(product: dict) -> str:
        return product.get("name", "")

    @staticmethod
    def get_product_size(product: dict) -> str:
        return product.get("size", "") or product.get("packageSize", "")


# ─── Unified Interface ──────────────────────────────────────────────────────

class PaknSaveAPI:
    """
    Unified Pak'nSave API client.
    Defaults to Edge API (two-pass). Falls back to Mobile API if requested.
    """

    def __init__(self, backend: Literal["edge", "mobile"] = "edge"):
        self.backend = backend
        if backend == "edge":
            self.client = PaknSaveEdgeAPI()
        else:
            self.client = PaknSaveMobileAPI()

    def search_ingredient(self, store_id: str, ingredient: str, **kwargs) -> list[dict]:
        """Search for an ingredient at a store. Returns list of product dicts."""
        if self.backend == "edge":
            return self.client.search_ingredient(store_id, ingredient, **kwargs)
        else:
            results = self.client.search_products(store_id, ingredient)
            return results or []

    def get_stores(self) -> list[dict]:
        """Get store list (format varies by backend)."""
        if self.backend == "edge":
            return self.client.get_stores()
        else:
            return list(self.client.get_stores().values())

    @staticmethod
    def extract_price(product: dict, backend: str) -> Optional[float]:
        if backend == "edge":
            return PaknSaveEdgeAPI.extract_price(product)
        else:
            return PaknSaveMobileAPI.extract_price(product)

    @staticmethod
    def extract_unit_price(product: dict, backend: str) -> str:
        if backend == "edge":
            return PaknSaveEdgeAPI.extract_unit_price(product)
        else:
            return PaknSaveMobileAPI.extract_unit_price(product)

    @staticmethod
    def get_product_name(product: dict, backend: str) -> str:
        if backend == "edge":
            return PaknSaveEdgeAPI.get_product_name(product)
        else:
            return PaknSaveMobileAPI.get_product_name(product)

    @staticmethod
    def get_product_size(product: dict, backend: str) -> str:
        if backend == "edge":
            return PaknSaveEdgeAPI.get_product_size(product)
        else:
            return PaknSaveMobileAPI.get_product_size(product)


# ─── Convenience Functions ──────────────────────────────────────────────────

def create_api(backend: Literal["edge", "mobile"] = "edge") -> PaknSaveAPI:
    """Factory function to create API client with specified backend."""
    return PaknSaveAPI(backend=backend)