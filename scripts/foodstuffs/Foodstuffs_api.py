"""
Foodstuffs Unified API Module
==============================
Unified API client supporting two backends for both Pak'nSave (PNS) and New World (MNW):
- EDGE API (default): Two-pass pipeline — relevance via Algolia products-index, then per-store pricing via paginated/products
- MOBILE API (fallback): Single-pass search via Foodstuffs mobile endpoint

Both backends use the same store data and dish ingredients. Both brands can be queried from the same file.
"""
import requests
import cloudscraper
import json
import time
import math
import os
import csv
import pandas as pd
from pathlib import Path
from typing import Optional, Literal

BRANDS = {
    "paknsave": {
        "web_base": "https://www.paknsave.co.nz",
        "edge_base": "https://api-prod.paknsave.co.nz/v1/edge",
    },
    "newworld": {
        "web_base": "https://www.newworld.co.nz",
        "edge_base": "https://api-prod.newworld.co.nz/v1/edge",
    },
}

WEB_BASES = {
    "paknsave": "https://www.paknsave.co.nz",
    "newworld": "https://www.newworld.co.nz",
}
EDGE_BASES = {
    "paknsave": "https://api-prod.paknsave.co.nz/v1/edge",
    "newworld": "https://api-prod.newworld.co.nz/v1/edge",
}
MOBILE_BASE = "https://api-prod.prod.fsniwaikato.kiwi/prod"

MOBILE_BANNERS = {
    "paknsave": "PNS",
    "newworld": "MNW",
}
MOBILE_USER_AGENTS = {
    "paknsave": "PAKnSAVEApp/4.32.0",
    "newworld": "NewWorldApp/4.32.0",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "data"))

STORES_CSV = {
    "paknsave": os.path.join(DATA_DIR, "paknsave_stores.csv"),
    "newworld": os.path.join(DATA_DIR, "newworld_stores.csv"),
}
STORES_JSON = {
    "paknsave": os.path.join(DATA_DIR, "paknsave_stores.json"),
    "newworld": os.path.join(DATA_DIR, "newworld_stores.json"),
}

OUTPUT_CSV = {
    "paknsave": os.path.join(DATA_DIR, "paknsave_latest_results.csv"),
    "newworld": os.path.join(DATA_DIR, "newworld_latest_results.csv"),
}

OUTPUT_MOBILE_CSV = {
    "paknsave": os.path.join(DATA_DIR, "paknsave_mobile_latest_results.csv"),
    "newworld": os.path.join(DATA_DIR, "newworld_mobile_latest_results.csv"),
}

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


def load_stores(brand: str = "paknsave") -> list[dict]:
    csv_path = STORES_CSV[brand]
    stores = []
    if not Path(csv_path).exists():
        return stores
    with open(csv_path, newline="", encoding="utf-8") as f:
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
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def geocode(address: str) -> tuple[Optional[float], Optional[float]]:
    time.sleep(1.1)
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
    user_lat: float, user_lon: float, brand: str = "paknsave", radius_km: float = 5.0
) -> list[dict]:
    stores = load_stores(brand)
    nearby = []
    web_base = WEB_BASES[brand]
    for s in stores:
        try:
            d = haversine(user_lat, user_lon, s["latitude"], s["longitude"])
            if d <= radius_km:
                nearby.append({**s, "distance_km": round(d, 2), "brand": brand, "web_base": web_base})
        except (KeyError, ValueError):
            continue
    nearby.sort(key=lambda x: x["distance_km"])
    return nearby


def get_ingredients(dish_name: str) -> list[str]:
    return DISH_INGREDIENTS.get(dish_name.lower().strip(), [dish_name])


# ─── EDGE API (Two-Pass) ────────────────────────────────────────────

class FoodstuffsEdgeAPI:
    """
    Foodstuffs Edge API client using website JWT authentication.
    Works for both Pak'nSave (PNS) and New World (MNW).
    Two-pass pipeline:
      PASS 1: POST /v1/edge/search/products/query/index/products-index (relevance + _highlightResult)
      PASS 2: POST /v1/edge/search/paginated/products (per-store pricing with filters + PRICE_ASC)
    """

    def __init__(self, brand: str = "paknsave"):
        self.brand = brand
        self.web_base = WEB_BASES[brand]
        self.edge_base = EDGE_BASES[brand]
        self.token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": self.web_base,
            "Referer": self.web_base + "/",
        })

    def authenticate(self) -> str:
        self.session.get(self.web_base, timeout=30)
        r = self.session.post(
            f"{self.web_base}/api/user/get-current-user",
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
            "Origin": self.web_base,
            "Referer": f"{self.web_base}/shop",
            "User-Agent": "Mozilla/5.0",
        }

    def _store_cookies(self, store_id: str, region: str = "NI") -> dict:
        return {
            "eCom_STORE_ID": store_id,
            "STORE_ID_V2": f"{store_id}|False",
            "Region": region,
        }

    def get_stores(self) -> list[dict]:
        headers = self._auth_headers()
        r = requests.get(f"{self.edge_base}/store", headers=headers, timeout=30)
        r.raise_for_status()
        return r.json().get("stores", [])

    def pass1_relevance_search(
        self,
        store_id: str,
        query: str,
        max_hits: int = 20,
        region: str = "NI",
    ) -> list[str]:
        headers = self._auth_headers()
        cookies = self._store_cookies(store_id, region)
        payload = {
            "algoliaQuery": {"query": query},
            "page": 0,
            "hitsPerPage": max_hits,
            "storeId": store_id,
        }
        r = requests.post(
            f"{self.edge_base}/search/products/query/index/products-index",
            headers=headers,
            json=payload,
            cookies=cookies,
            timeout=30,
        )
        r.raise_for_status()
        hits = r.json().get("hits", [])

        pet_categories = {"Dog", "Cat"}
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

    def pass2_per_store_pricing(
        self,
        store_id: str,
        query: str,
        product_ids: list[str],
        hits_per_page: int = 50,
        region: str = "NI",
    ) -> list[dict]:
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
            f"{self.edge_base}/search/paginated/products",
            headers=headers,
            json=payload,
            cookies=cookies,
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("products", [])

    def search_ingredient(
        self,
        store_id: str,
        ingredient: str,
        max_relevance: int = 20,
        region: str = "NI",
    ) -> list[dict]:
        product_ids = self.pass1_relevance_search(store_id, ingredient, max_relevance, region)
        return self.pass2_per_store_pricing(store_id, ingredient, product_ids, region=region)

    @staticmethod
    def extract_price(product: dict) -> Optional[float]:
        sp = product.get("singlePrice", {})
        price_cents = sp.get("price")
        promo = product.get("promotions", [])
        promo_val = promo[0].get("rewardValue") if promo else None
        final_cents = promo_val if promo_val is not None else price_cents
        return final_cents / 100.0 if final_cents else None

    @staticmethod
    def extract_unit_price(product: dict) -> Optional[str]:
        sp = product.get("singlePrice", {})
        return sp.get("unitPrice") or sp.get("pricePerUnit") or ""

    @staticmethod
    def get_product_name(product: dict) -> str:
        return product.get("name") or product.get("displayName") or ""

    @staticmethod
    def get_product_size(product: dict) -> str:
        return product.get("displayName") or product.get("size") or ""


# ─── MOBILE API (Single-Pass, Legacy Fallback) ─────────────────────

class FoodstuffsMobileAPI:
    """
    Foodstuffs Mobile API client (legacy, fallback).
    Works for both Pak'nSave (PNS) and New World (MNW).
    Uses Foodstuffs mobile endpoint with guest token auth.
    Single search per ingredient per store; no relevance visibility.
    """

    def __init__(self, brand: str = "paknsave"):
        self.brand = brand
        self.banner = MOBILE_BANNERS[brand]
        self.user_agent = MOBILE_USER_AGENTS[brand]
        self.scraper = cloudscraper.create_scraper()
        self._token: Optional[str] = None

    def _ensure_token(self):
        if self._token:
            return
        r = self.scraper.post(
            f"{MOBILE_BASE}/mobile/user/login/guest",
            json={"banner": self.banner},
            headers={"User-Agent": self.user_agent, "Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._auth = {
            "Authorization": f"Bearer {self._token}",
            "access_token": self._token,
            "User-Agent": self.user_agent,
            "Content-Type": "application/json",
        }

    def search_products(self, store_id: str, query: str) -> Optional[list[dict]]:
        self._ensure_token()
        r = self.scraper.post(
            f"{MOBILE_BASE}/mobile/ecomm-products/{self.banner}/{store_id}/search?q={query}",
            headers=self._auth,
            json=[],
        )
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else data.get("products", [])
        return None

    def get_stores(self) -> dict:
        self._ensure_token()
        r = self.scraper.get(f"{MOBILE_BASE}/mobile/store/physical", headers=self._auth)
        if r.status_code == 200:
            return {s["id"]: s for s in r.json()["stores"] if s.get("banner") == self.banner}
        return {}

    @staticmethod
    def extract_price(product: dict) -> Optional[float]:
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


# ─── Unified Interface ───────────────────────────────────────────────

class FoodstuffsAPI:
    """
    Unified Foodstuffs API client (Edge by default, Mobile fallback).
    Works for both Pak'nSave (PNS) and New World (MNW).

    Args:
        brand: "paknsave" or "newworld"
        backend: "edge" (default, two-pass) or "mobile" (single-pass fallback)
    """

    def __init__(self, brand: str = "paknsave", backend: Literal["edge", "mobile"] = "edge"):
        self.brand = brand
        self.backend = backend
        if backend == "edge":
            self.client = FoodstuffsEdgeAPI(brand=brand)
        else:
            self.client = FoodstuffsMobileAPI(brand=brand)

    def search_ingredient(self, store_id: str, ingredient: str, **kwargs) -> list[dict]:
        if self.backend == "edge":
            return self.client.search_ingredient(store_id, ingredient, **kwargs)
        else:
            results = self.client.search_products(store_id, ingredient)
            return results or []

    def get_stores(self) -> list[dict]:
        if self.backend == "edge":
            return self.client.get_stores()
        else:
            return list(self.client.get_stores().values())

    @staticmethod
    def extract_price(product: dict, backend: str) -> Optional[float]:
        if backend == "edge":
            return FoodstuffsEdgeAPI.extract_price(product)
        else:
            return FoodstuffsMobileAPI.extract_price(product)

    @staticmethod
    def extract_unit_price(product: dict, backend: str = "edge") -> str:
        if backend == "edge":
            return FoodstuffsEdgeAPI.extract_unit_price(product)
        else:
            return FoodstuffsMobileAPI.extract_unit_price(product)

    @staticmethod
    def get_product_name(product: dict, backend: str = "edge") -> str:
        if backend == "edge":
            return FoodstuffsEdgeAPI.get_product_name(product)
        else:
            return FoodstuffsMobileAPI.get_product_name(product)

    def save_results(self, df: pd.DataFrame, brand: str = "paknsave", mobile: bool = False) -> str:
        output = OUTPUT_MOBILE_CSV[brand] if mobile else OUTPUT_CSV[brand]
        df.to_csv(output, index=False, encoding="utf-8")
        print(f"\n[OK] Full results saved to {output}")
        return output


def create_api(brand: str = "paknsave", backend: Literal["edge", "mobile"] = "edge") -> FoodstuffsAPI:
    return FoodstuffsAPI(brand=brand, backend=backend)