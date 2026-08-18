"""
Explore Algolia index endpoints - detailed response inspection
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

def test_index_detailed(session, token, index_name, query="milk", store_id="60928d93-06fa-4d8f-92a6-8c359e7e846d"):
    """Test index and dump full response"""
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
    print(f"\n{'='*60}")
    print(f"INDEX: {index_name}")
    print(f"STATUS: {r.status_code}")
    
    if r.status_code == 200:
        data = r.json()
        print(f"TOP-LEVEL KEYS: {list(data.keys())}")
        
        products = data.get("products", data.get("hits", []))
        print(f"PRODUCTS COUNT: {len(products)}")
        
        if products:
            print(f"FIRST PRODUCT KEYS: {list(products[0].keys())}")
            p = products[0]
            print(f"  name: {p.get('name')}")
            print(f"  displayName: {p.get('displayName')}")
            print(f"  productId: {p.get('productId')}")
            sp = p.get('singlePrice', {})
            print(f"  singlePrice: {sp}")
            promo = p.get('promotions', [])
            print(f"  promotions: {promo[:1] if promo else 'none'}")
            
            # Print all products briefly
            for i, p in enumerate(products[:5]):
                sp = p.get('singlePrice', {})
                price = sp.get('price', '?')
                name = p.get('name', '?')
                print(f"  [{i}] {name}: ${price/100 if isinstance(price, int) else price}")
    else:
        print(f"  Error: {r.text[:500]}")

def main():
    session, token = get_website_session()
    store_id = "60928d93-06fa-4d8f-92a6-8c359e7e846d"
    
    working_indices = [
        "products-index-popularity-asc",
        "products-index-popularity-desc",
        "products-index",
    ]
    
    for idx in working_indices:
        test_index_detailed(session, token, idx, "milk", store_id)

if __name__ == "__main__":
    main()