"""
Pak'nSave Edge API Two-Pass Optimizer - Proof of Concept

Two-pass pipeline:
  PASS 1: Algolia relevance search (products-index) with _highlightResult.matchedWords
          + category filtering to exclude pet food (Dog, Cat, Pet)
  PASS 2: Per-store pricing via paginated/products with Algolia filters
          Sorted by PRICE_ASC at each store

Queries top 20 most relevant products per ingredient per store.
"""

import requests
import time
import math
import pandas as pd
import os
import sys

WEB_BASE = "https://www.paknsave.co.nz"
EDGE_BASE = "https://api-prod.paknsave.co.nz/v1/edge"

DISH_INGREDIENTS = {
    "spaghetti bolognese": [
        "beef mince", "spaghetti pasta", "canned tomatoes",
        "onion", "carrot", "garlic", "mixed herbs"
    ],
    "butter chicken": [
        "chicken breast", "butter chicken sauce", "rice", "cream", "onion"
    ],
    "fish and chips": [
        "fish fillets", "potatoes", "flour", "oil"
    ],
    "chicken stir fry": [
        "chicken breast", "stir fry vegetables", "soy sauce", "rice noodles"
    ],
}


class PaknSaveEdgeAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": WEB_BASE,
            "Referer": WEB_BASE + "/",
        })
        self._token = None
        self._headers = None

    def _get_token(self):
        if self._token:
            return self._token
        self.session.get(WEB_BASE, timeout=30)
        self.session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
        self._token = self.session.cookies.get("fs-user-token")
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "access_token": self._token,
            "Content-Type": "application/json",
            "Origin": WEB_BASE,
            "Referer": f"{WEB_BASE}/shop",
            "User-Agent": "Mozilla/5.0",
        }
        return self._token

    def get_stores(self):
        self._get_token()
        r = requests.get(f"{EDGE_BASE}/store", headers=self._headers, timeout=30)
        r.raise_for_status()
        return r.json().get("stores", [])

    def haversine(self, lat1, lon1, lat2, lon2):
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        return R * 2 * math.asin(math.sqrt(a))

    def find_nearby(self, user_lat, user_lon, radius_km=5):
        stores = self.get_stores()
        for s in stores:
            s["distance_km"] = self.haversine(user_lat, user_lon, s["latitude"], s["longitude"])
        nearby = [s for s in stores if s["distance_km"] <= radius_km]
        nearby.sort(key=lambda x: x["distance_km"])
        return nearby

    def two_pass_search(self, store_id, query, max_relevance=20):
        """
        PASS 1: Algolia relevance search (products-index)
        Returns hits with _highlightResult.matchedWords for explicit relevance matching.
        Filters out pet food categories (Dog, Cat, Pet).

        PASS 2: Per-store pricing via paginated/products with Algolia filters
        Uses productID filter from Pass 1, sorted by PRICE_ASC.
        """
        cookies = {
            "eCom_STORE_ID": store_id,
            "STORE_ID_V2": f"{store_id}|False",
            "Region": "NI",
        }

        # PASS 1: Relevance
        payload1 = {
            "algoliaQuery": {"query": query},
            "page": 0,
            "hitsPerPage": max_relevance,
            "storeId": store_id,
        }
        r1 = requests.post(
            f"{EDGE_BASE}/search/products/query/index/products-index",
            headers=self._headers, json=payload1, cookies=cookies, timeout=30
        )
        if r1.status_code != 200:
            return []
        hits = r1.json().get("hits", [])

        # Filter: must have matchedWords AND not be pet food
        pet_categories = {"Dog", "Cat", "Pet"}
        product_ids = []
        for h in hits:
            hr = h.get("_highlightResult", {})
            matched = [f for f, v in hr.items()
                       if isinstance(v, dict) and v.get("matchedWords")]
            cat1 = h.get("category1", [])
            if matched and not any(c in pet_categories for c in cat1):
                product_ids.append(h["productID"])

        if not product_ids:
            return []

        # PASS 2: Per-store pricing with filters
        filter_str = " OR ".join([f"productID:{pid}" for pid in product_ids])
        payload2 = {
            "algoliaQuery": {"query": query, "filters": filter_str},
            "page": 0,
            "hitsPerPage": 50,
            "storeId": store_id,
            "sortOrder": "PRICE_ASC",
        }
        r2 = requests.post(
            f"{EDGE_BASE}/search/paginated/products",
            headers=self._headers, json=payload2, cookies=cookies, timeout=30
        )
        if r2.status_code != 200:
            return []
        return r2.json().get("products", [])

    def find_cheapest(self, products):
        cheapest = None
        cheapest_price = float("inf")
        for p in products:
            sp = p.get("singlePrice", {})
            price = sp.get("price")
            promo_val = None
            for promo in p.get("promotions", []):
                if promo.get("bestPromotion") and "rewardValue" in promo:
                    promo_val = promo["rewardValue"]
                    break
            final = promo_val if promo_val is not None else price
            if final is not None and final < cheapest_price:
                cheapest_price = final
                cheapest = p
        if cheapest:
            return cheapest, cheapest_price / 100
        return None, None

    def optimize_dish(self, address, dish_name, radius_km=5):
        # Geocode address
        geo = requests.get(
            "https://nominatim.openstreetmap.org/search",
            headers={"User-Agent": "NZMealCostOptimizer/1.0"},
            params={"q": address, "format": "json", "limit": 1},
            timeout=30
        )
        if geo.status_code != 200 or not geo.json():
            raise ValueError("Could not geocode address")
        loc = geo.json()[0]
        user_lat, user_lon = float(loc["lat"]), float(loc["lon"])

        ingredients = DISH_INGREDIENTS.get(dish_name.lower(), [dish_name])
        nearby = self.find_nearby(user_lat, user_lon, radius_km)

        print(f"\n{'='*60}")
        print(f"Pak'nSave Edge API Two-Pass Optimizer")
        print(f"Dish: {dish_name} | Address: {address} | Radius: {radius_km}km")
        print(f"Nearby stores: {len(nearby)}")
        print(f"{'='*60}")

        results = []
        for store in nearby:
            store_id = store["id"]
            store_name = store["name"]
            print(f"\n--- {store_name} ({store['distance_km']:.1f} km) ---")

            total = 0.0
            items = []
            for ing in ingredients:
                products = self.two_pass_search(store_id, ing, max_relevance=20)
                if products:
                    cheapest, price = self.find_cheapest(products)
                    if cheapest:
                        name = cheapest.get("name", "")
                        size = cheapest.get("displayName", "")
                        print(f"  {ing:25s} ${price:.2f}  ({name} {size})")
                        total += price
                        items.append((ing, price, name, size))
                    else:
                        print(f"  {ing:25s} NO PRICE")
                else:
                    print(f"  {ing:25s} NOT FOUND")
                time.sleep(0.15)

            print(f"  {'TOTAL':25s} ${total:.2f}")
            results.append({
                "store_id": store_id,
                "store_name": store_name,
                "distance_km": store["distance_km"],
                "total": total,
                "items": items,
            })

        results.sort(key=lambda x: x["total"])
        print(f"\n{'='*60}")
        print("CHEAPEST STORES:")
        for i, r in enumerate(results):
            print(f"  {i+1}. {r['store_name']} (${r['total']:.2f}, {r['distance_km']:.1f} km)")
        print(f"{'='*60}")

        return results


def main():
    address = sys.argv[1] if len(sys.argv) > 1 else "123 Queen Street, Auckland CBD, 1010"
    dish = sys.argv[2] if len(sys.argv) > 2 else "spaghetti bolognese"

    api = PaknSaveEdgeAPI()
    api.optimize_dish(address, dish)


if __name__ == "__main__":
    main()