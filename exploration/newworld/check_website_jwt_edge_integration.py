"""
Test if website JWT works for Edge API store listing
"""

import requests

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
    return token, session


def test_edge_store_listing(token):
    """Test Edge store listing with website JWT"""
    url = f"{EDGE_BASE}/store"
    headers = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    }
    r = requests.get(url, headers=headers, timeout=30)
    print(f"Edge store listing: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        stores = data.get("stores", data if isinstance(data, list) else [])
        print(f"  Found {len(stores)} stores")
        if stores:
            print(f"  Sample: {stores[0]}")
        return stores
    else:
        print(f"  Error: {r.text[:300]}")
    return []


def test_edge_product_search(token, store_id):
    """Test Edge product search with website JWT"""
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
        "algoliaQuery": {"query": "milk"},
        "page": 0,
        "hitsPerPage": 20,
        "storeId": store_id,
        "sortOrder": "PRICE_ASC",
    }
    r = requests.post(url, headers=headers, json=payload, cookies=cookies, timeout=30)
    print(f"Edge product search: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        products = data.get("products", data.get("items", data.get("results", data.get("hits", []))))
        print(f"  Found {len(products)} products")
        for p in products[:3]:
            name = p.get("name", "?")
            price = p.get("singlePrice", {}).get("price", "?")
            promo = p.get("promotions", [{}])[0].get("rewardValue", None)
            print(f"    {name}: ${price/100:.2f}" + (f" (promo ${promo/100:.2f})" if promo else ""))
        return products
    else:
        print(f"  Error: {r.text[:300]}")
    return []


def main():
    print("=" * 60)
    print("Testing Website JWT with Edge API")
    print("=" * 60)
    
    print("\n1. Getting website JWT...")
    token, session = get_website_jwt()
    print(f"   Token: {'YES' if token else 'NO'} ({token[:50] if token else 'N/A'}...)")
    
    print("\n2. Testing Edge store listing with website JWT...")
    stores = test_edge_store_listing(token)
    
    if stores:
        store_id = stores[0].get("storeId", stores[0].get("id"))
        print(f"\n3. Testing product search with store {store_id}...")
        test_edge_product_search(token, store_id)


if __name__ == "__main__":
    main()