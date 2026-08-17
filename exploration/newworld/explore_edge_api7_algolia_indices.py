"""
Explore Algolia index endpoints for different sort orders.
The website uses different indices for different sort options.
"""

import requests
import json

WEB_BASE = "https://www.newworld.co.nz"
EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"

def get_website_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    session.get(WEB_BASE, timeout=30)
    session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    token = session.cookies.get("fs-user-token")
    return session, token

def test_index_endpoint(session, token, index_name, query="milk", store_id="60928d93-06fa-4d8f-92a6-8c359e7e846d"):
    """Test a specific Algolia index endpoint"""
    url = f"{EDGE_BASE}/search/products/query/index/{index_name}"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
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
    }
    
    r = requests.post(url, headers=headers, json=payload, cookies=cookies, timeout=30)
    print(f"\n{index_name}: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        products = data.get("products", data.get("hits", []))
        print(f"  Products: {len(products)}")
        for p in products[:3]:
            name = p.get("name", "?")
            price = p.get("singlePrice", {}).get("price")
            promo = p.get("promotions", [])
            promo_price = promo[0].get("rewardValue") if promo else None
            print(f"    {name}: ${price/100 if price else '?'}{' (promo:' + str(promo_price/100) + ')' if promo_price else ''}")
        return products
    else:
        print(f"  Error: {r.text[:300]}")
    return None

def main():
    session, token = get_website_session()
    store_id = "60928d93-06fa-4d8f-92a6-8c359e7e846d" # New World Metro Auckland
    
    # Known index endpoints from network capture + common patterns
    indices = [
        "products-index-popularity-asc",
        "products-index-popularity-desc",
        "products-index-relevance",
        "products-index-price-asc",
        "products-index-price-desc",
        "products-index-name-asc",
        "products-index-name-desc",
        "products-index-newest",
        "products-index-bestselling",
        "products-index-trending",
        # Generic ones
        "products",
        "products-index",
    ]
    
    print("=" * 60)
    print("Testing Algolia Index Endpoints")
    print("=" * 60)
    
    for idx in indices:
        test_index_endpoint(session, token, idx, "milk", store_id)

if __name__ == "__main__":
    main()