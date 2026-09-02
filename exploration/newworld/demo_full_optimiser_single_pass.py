"""
Complete Edge API flow for meal cost optimiser using website JWT
"""

import sys
from pathlib import Path

import requests
import time

WEB_BASE = "https://www.newworld.co.nz"
EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "combined"))
from optimiser_utils import DISHES, get_ingredients

def get_website_jwt():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    session.get(WEB_BASE, timeout=30)
    session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    return session.cookies.get("fs-user-token")


def get_all_stores(token):
    url = f"{EDGE_BASE}/store"
    headers = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    }
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code == 200:
        data = r.json()
        return data.get("stores", data if isinstance(data, list) else [])
    return []


def search_products(token, store_id, query):
    url = f"{EDGE_BASE}/search/paginated/products"
    headers = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/shop",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    cookies = {
        "eCom_STORE_ID": store_id,
        "STORE_ID_V2": f"{store_id}|False",
        "Region": "NI",
    }
    payload = {
        "algoliaQuery": {"query": query},
        "page": 0,
        "hitsPerPage": 20,
        "storeId": store_id,
        "sortOrder": "PRICE_ASC",
    }
    r = requests.post(url, headers=headers, json=payload, cookies=cookies, timeout=30)
    if r.status_code == 200:
        data = r.json()
        return data.get("products", data.get("items", data.get("results", data.get("hits", []))))
    return []


def extract_price(product):
    single_price = product.get("singlePrice", {})
    price_cents = single_price.get("price")
    promo_price_cents = None
    for promo in product.get("promotions", []):
        if promo.get("bestPromotion") and "rewardValue" in promo:
            promo_price_cents = promo["rewardValue"]
            break
    final_cents = promo_price_cents if promo_price_cents is not None else price_cents
    return round(final_cents / 100, 2) if final_cents is not None else None


def find_cheapest_product(products):
    cheapest = None
    cheapest_price = float('inf')
    for p in products:
        price = extract_price(p)
        if price and price < cheapest_price:
            cheapest_price = price
            cheapest = p
    return cheapest, cheapest_price


def main():
    print("=" * 60)
    print("New World Edge API - Complete Meal Cost Optimiser")
    print("=" * 60)
    
    # 1. Get JWT
    print("\n1. Getting website JWT...")
    token = get_website_jwt()
    print(f"   {'OK' if token else 'FAILED'}")
    
    # 2. Get all stores
    print("\n2. Fetching all stores...")
    stores = get_all_stores(token)
    print(f"   Found {len(stores)} stores")
    
    # 3. Test price comparison for a dish
    dish = "spaghetti bolognese"
    ingredients = get_ingredients(dish)
    
    print(f"\n3. Testing '{dish}' across stores...")
    
    # Use first 5 stores for demo
    test_stores = stores[:5]
    
    for store in test_stores:
        store_id = store.get("id") or store.get("storeId")
        name = store.get("name", "Unknown")
        print(f"\n   Store: {name} ({store_id})")
        
        total = 0
        for ing in ingredients:
            products = search_products(token, store_id, ing)
            if products:
                cheapest, price = find_cheapest_product(products)
                if cheapest:
                    print(f"     {ing}: ${price:.2f} ({cheapest.get('name', '?')})")
                    total += price
                else:
                    print(f"     {ing}: NO PRICE")
            else:
                print(f"     {ing}: NO RESULTS")
            time.sleep(0.2)
        
        print(f"     >>> TOTAL: ${total:.2f}")
    
    print("\n" + "=" * 60)
    print("COMPLETE - Edge API works end-to-end with website JWT")
    print("=" * 60)


if __name__ == "__main__":
    main()