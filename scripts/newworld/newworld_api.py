"""
New World API Module
====================
Unified API client supporting two backends:
- EDGE API (default): Two-pass pipeline — relevance via Algolia products-index, then per-store pricing via paginated/products
- MOBILE API (fallback): Single-pass search via Foodstuffs mobile endpoint

Both backends use the same store data (from newworld_setup.py output) and dish ingredients.
"""

import requests
import cloudscraper
import sys
from pathlib import Path
from typing import Optional, Literal, cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "combined"))
from optimizer_utils import haversine, geocode

# ─── Constants ──────────────────────────────────────────────────────────────
WEB_BASE = "https://www.newworld.co.nz"
EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"
MOBILE_BASE = "https://api-prod.prod.fsniwaikato.kiwi/prod"

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STORES_CSV = DATA_DIR / "newworld_stores.csv"
STORES_JSON = DATA_DIR / "newworld_stores.json"

# Non-food category1 blacklist — values to exclude from ingredient search results.
# Sourced from observed_category1_newworld.json (all 116 unique category1 values).
NON_FOOD_CATEGORIES = {
    # Pet / Animal
    "Dog",
    "Cat",
    "Pet Health & Accessories",
    "Birds, Fish & Small Animals",
    # Baby / Toddler
    "Baby & Toddler Food",
    "Baby & Toddler Toiletries",
    "Baby Formula",
    "Baby Wipes",
    "Nappies & Changing",
    "Nursing & Feeding",
    # Household / Cleaning
    "Cleaning & Accessories",
    "Dishwashing",
    "Bathroom & Toilet Cleaners",
    "Kitchen Cleaners",
    "Laundry",
    "Food Wrap, Storage & Bags",
    "Pest & Insect Control",
    "Homewares",
    # Health / Personal Care
    "Bath, Shower & Soap",
    "Dental & Oral Care",
    "Deodorant & Body Sprays",
    "Hair Care",
    "Make Up & Nail Care",
    "Medical & First Aid",
    "Period & Continence Care",
    "Shaving & Hair Removal",
    "Skin Care & Sun Care",
    "Tissues & Cotton Wool",
    "Toilet Paper, Tissues & Paper Towels",
    "Vitamins & Supplements",
    # Other non-food
    "Stationery & Entertainment",
    "Clothing & Accessories",
    "Garage & Outdoor",
    "Batteries & Electrical",
    # # Alcoholic drinks (beverages, not cooking ingredients) Note: Allowed for now
    # "Red Wine",
    # "White Wine",
    # "Rose Wine",
    # "Champagne & Sparkling Wine",
    # "Cask Wine",
    # "Moscato & Sweet Wine",
    # "Craft Beer",
    # "Beer",
    # "Cider",
    # "Seltzers & Other Alcoholic Drinks",
    # "Lower Alcohol Drinks",
    # # Non-food ready-to-drink beverages
    # "Sports & Energy Drinks",
    # "Soft Drinks & Mixers",
    # "Alcohol Free Drinks",
}

# Dish ingredients (21 dishes) — matches NewWorld_prototype.py and woolworths_optimizer.py
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
    """Load store list from CSV/JSON produced by newworld_setup.py."""
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

class NewWorldEdgeAPI:
    """
    New World Edge API client using website JWT authentication.
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
    def pass1_relevance_search_hits(
        self,
        store_id: str,
        query: str,
        max_hits: int = 20,
        region: str = "NI",
    ) -> list[dict]:
        """
        Search products-index for relevance matches.
        Returns full hit objects (with productID, category1, _highlightResult, etc.).
        Filters out non-food category1 values via NON_FOOD_CATEGORIES.
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

        filtered = []
        for h in hits:
            hr = h.get("_highlightResult", {})
            matched = any(
                isinstance(v, dict) and v.get("matchedWords")
                for v in hr.values()
            )
            cat1 = h.get("category1", [])
            if matched and not any(c in NON_FOOD_CATEGORIES for c in cat1):
                filtered.append(h)
        return filtered

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
        Filters out non-food category1 values via NON_FOOD_CATEGORIES.
        """
        hits = self.pass1_relevance_search_hits(store_id, query, max_hits, region)
        return [h["productID"] for h in hits]

    # ── PASS 2: Per-Store Pricing ───────────────────────────────────
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

    # ── Combined Two-Pass Search ────────────────────────────────────
    def search_ingredient(
        self,
        store_id: str,
        ingredient: str,
        max_relevance: int = 20,
        region: str = "NI",
    ) -> tuple[list[dict], list[dict]]:
        """Full two-pass search for one ingredient at one store.

        Returns:
            (products, pass1_hits) where:
            - products: list of product dicts from Pass 2 (with pricing)
            - pass1_hits: list of Pass 1 hit dicts (with category1, _highlightResult)
        """
        pass1_hits = self.pass1_relevance_search_hits(store_id, ingredient, max_relevance, region)
        product_ids = [h["productID"] for h in pass1_hits]
        products = self.pass2_per_store_pricing(store_id, ingredient, product_ids, region=region)
        return products, pass1_hits

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

class NewWorldMobileAPI:
    """
    New World Mobile API client (legacy, fallback).
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
            json={"banner": "MNW"},
            headers={"User-Agent": "NewWorldApp/4.32.0", "Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]

    def _auth_headers(self) -> dict:
        self._ensure_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "access_token": self._token,
            "User-Agent": "NewWorldApp/4.32.0",
            "Content-Type": "application/json",
        }

    def _is_food_product(self, product: dict) -> bool:
        """
        Check if a product is a food item (not pet/baby/household etc.).

        Mirrors edge Pass 1 filtering against the category1 (sub_department) value.
        In the mobile response, categories[0] = category1 (sub_department) and
        categories[1] = category2 (subsub_department). Non-food markers such as
        "Dog"/"Cat" appear at categories[0], so only the first entry is checked.
        """
        categories = product.get("categories", []) or []
        cat1 = categories[0] if categories else ""
        if not cat1:
            return True  # no category1 to check — treat as food
        return cat1 not in NON_FOOD_CATEGORIES

    def search_products(
        self,
        store_id: str,
        query: str,
        hits_per_page: int = 20,
        food_only: bool = True,
    ) -> Optional[list[dict]]:
        """Search products at a store via mobile API. Returns raw product list.

        Limits results with hitsPerPage (default 20) to control response size.
        When food_only=True (default), excludes non-food products by category1/`categories`.
        """
        self._ensure_token()
        r = self.scraper.post(
            f"{MOBILE_BASE}/mobile/ecomm-products/MNW/{store_id}/search?q={query}&hitsPerPage={hits_per_page}",
            headers=self._auth_headers(),
            json=[],
        )
        if r.status_code == 200:
            data = r.json()
            # Mobile API returns a wrapped dict (not a bare list)
            products = data.get("products", []) if isinstance(data, dict) else data
            if food_only:
                products = [p for p in products if self._is_food_product(p)]
            return products
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

class NewWorldAPI:
    """
    Unified New World API client.
    Defaults to Edge API (two-pass). Falls back to Mobile API if requested.
    """

    def __init__(self, backend: Literal["edge", "mobile"] = "edge"):
        self.backend = backend
        self.client: NewWorldEdgeAPI | NewWorldMobileAPI

        if backend == "edge":
            self.client = NewWorldEdgeAPI()
        else:
            self.client = NewWorldMobileAPI()

    def search_ingredient(self, store_id: str, ingredient: str, **kwargs) -> tuple[list[dict], list[dict]]:
        """Search for an ingredient at a store.

        Returns:
            (products, pass1_hits) for edge backend.
            ([], products) for mobile backend (no Pass 1 metadata).
        """
        if isinstance(self.client, NewWorldEdgeAPI):
            return self.client.search_ingredient(store_id, ingredient, **kwargs)

        results = self.client.search_products(store_id, ingredient)
        return [], results or []

    def get_stores(self) -> list[dict]:
        """Get store list (format varies by backend)."""
        if isinstance(self.client, NewWorldEdgeAPI):
            return self.client.get_stores()

        stores = self.client.get_stores()
        return list(cast(dict, stores).values())

    @staticmethod
    def extract_unit_price(product: dict, backend: str) -> str:
        if backend == "edge":
            unit_price = NewWorldEdgeAPI.extract_unit_price(product)
        else:
            unit_price = NewWorldMobileAPI.extract_unit_price(product)

        return unit_price or ""

    @staticmethod
    def get_product_name(product: dict, backend: str) -> str:
        if backend == "edge":
            name = NewWorldEdgeAPI.get_product_name(product)
        else:
            name = NewWorldMobileAPI.get_product_name(product)

        return name or ""

    @staticmethod
    def get_product_size(product: dict, backend: str) -> str:
        if backend == "edge":
            size = NewWorldEdgeAPI.get_product_size(product)
        else:
            size = NewWorldMobileAPI.get_product_size(product)

        return size or ""


# ─── Convenience Functions ──────────────────────────────────────────

def create_api(backend: Literal["edge", "mobile"] = "edge") -> NewWorldAPI:
    """Factory function to create API client with specified backend."""
    return NewWorldAPI(backend=backend)