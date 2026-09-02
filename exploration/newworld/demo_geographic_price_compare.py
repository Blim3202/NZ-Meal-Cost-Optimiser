"""
Complete Edge API test with website JWT - full price comparison across stores
"""

import requests
import time

EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"
WEB_BASE = "https://www.newworld.co.nz"


def get_website_jwt():
    """Get JWT from website"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    r = session.get(WEB_BASE, timeout=30)
    r = session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    token = session.cookies.get("fs-user-token")
    return token


def get_all_stores(token):
    """Get all stores from Edge API"""
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
    """Search products at a store"""
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
    """Extract price in dollars"""
    single_price = product.get("singlePrice", {})
    price_cents = single_price.get("price")
    
    promo_price_cents = None
    for promo in product.get("promotions", []):
        if promo.get("bestPromotion") and "rewardValue" in promo:
            promo_price_cents = promo["rewardValue"]
            break
    
    final_cents = promo_price_cents if promo_price_cents is not None else price_cents
    if final_cents is not None:
        return round(final_cents / 100, 2)
    return None


def main():
    print("=" * 60)
    print("Complete Edge API Price Comparison")
    print("=" * 60)
    
    # Get JWT
    print("\n1. Getting website JWT...")
    token = get_website_jwt()
    print(f"   Token: {'YES' if token else 'NO'}")
    
    # Get all stores
    print("\n2. Fetching all stores...")
    stores = get_all_stores(token)
    print(f"   Found {len(stores)} stores")
    
    # Select a few stores for testing (geographically diverse)
    test_stores = [
        s for s in stores 
        if s.get("name") in [
            "New World Te Puke",
            "New World Albany", 
            "New World Birkenhead",
            "New World Metro Auckland",
            "New World Wellington City",
            "New World Christchurch Central",
        ]
    ]
    
    # If not found by name, use first 6
    if len(test_stores) < 6:
        test_stores = stores[:6]
    
    print(f"\n3. Testing {len(test_stores)} stores...")
    for store in test_stores:
        store_id = store.get("id") or store.get("storeId")
        name = store.get("name")
        print(f"\n   Store: {name} ({store_id})")
        products = search_products(token, store_id, "standard milk 2L")
        
        if products:
            # Find the standard milk 2L
            for p in products[:5]:
                price = extract_price(p)
                if price:
                    print(f"     {p.get('name', '?')}: ${price}")
                    break
        time.sleep(0.5)
    
    # Test more ingredients for a dish
    print("\n4. Testing dish ingredients (Spaghetti Bolognese)...")
    ingredients = ["beef mince 500g", "pasta 500g", "tomato paste", "onion", "garlic"]
    
    # Use first test store
    store = test_stores[0]
    store_id = store.get("id") or store.get("storeId")
    print(f"   Store: {store.get('name')} ({store_id})")
    
    total = 0
    for ing in ingredients:
        products = search_products(token, store_id, ing)
        if products:
            price = extract_price(products[0])
            if price:
                print(f"     {ing}: ${price}")
                total += price
            else:
                print(f"     {ing}: NO PRICE")
        else:
            print(f"     {ing}: NO RESULTS")
        time.sleep(0.3)
    
    print(f"\n   Estimated total: ${total:.2f}")


if __name__ == "__main__":
    main()