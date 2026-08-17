"""
Test Edge API product search WITHOUT relying on mobile API token.
Explore alternative authentication paths:
1. Website session (get-current-user endpoint returns JWT in cookie)
2. Direct Edge API token validation
3. Anonymous/unauthenticated access
"""

import json
import requests
import time

EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"
WEB_BASE = "https://www.newworld.co.nz"

TEST_STORE = "60928d93-06fa-4d8f-92a6-8c359e7e846d"  # New World Metro Auckland


def get_token_from_website():
    """Get JWT from website session via get-current-user endpoint"""
    url = f"{WEB_BASE}/api/user/get-current-user"
    
    # Start a session to get cookies
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    
    # First, visit homepage to get initial cookies
    r = session.get(WEB_BASE, timeout=30)
    print(f"Homepage: {r.status_code}, Cookies: {len(session.cookies)}")
    
    # Call get-current-user (returns user info + sets fs-user-token cookie)
    r = session.post(url, json={}, timeout=30)
    print(f"Get current user: {r.status_code}")
    
    # Extract token from cookies
    token = None
    for cookie in session.cookies:
        if cookie.name == "fs-user-token":
            token = cookie.value
            break
    
    if not token:
        # Try parsing response
        try:
            data = r.json()
            token = data.get("token") or data.get("accessToken")
        except:
            pass
    
    return session, token


def test_edge_store_listing(session, token=None):
    """Test Edge store listing endpoint"""
    url = f"{EDGE_BASE}/store"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["access_token"] = token
    
    r = requests.get(url, headers=headers, cookies=session.cookies, timeout=30)
    print(f"\nEdge store listing: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        stores = data.get("stores", data if isinstance(data, list) else [])
        print(f"  Found {len(stores)} stores")
        return stores
    else:
        print(f"  Error: {r.text[:300]}")
    return []


def test_edge_categories(session, token, store_id):
    """Test Edge categories endpoint"""
    url = f"{EDGE_BASE}/store/{store_id}/categories"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["access_token"] = token
    
    cookies = dict(session.cookies)
    cookies["eCom_STORE_ID"] = store_id
    cookies["STORE_ID_V2"] = f"{store_id}|False"
    
    r = requests.get(url, headers=headers, cookies=cookies, timeout=30)
    print(f"\nEdge categories: {r.status_code}")
    if r.status_code == 200:
        cats = r.json()
        print(f"  Found {len(cats)} categories")
    return r.status_code == 200


def test_edge_cookies_only(session, store_id, query="milk"):
    """Test Edge API using ONLY cookies from website session (no Authorization header)"""
    url = f"{EDGE_BASE}/search/paginated/products"
    
    cookies = dict(session.cookies)
    cookies["eCom_STORE_ID"] = store_id
    cookies["STORE_ID_V2"] = f"{store_id}|False"
    cookies["Region"] = "NI"
    
    headers = {
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        # NO Authorization header
    }
    
    # Fixed payload - API expects q, page, hitsPerPage
    payload = {
        "q": query,
        "page": 0,
        "hitsPerPage": 20,
        "storeId": store_id,
    }
    
    print(f"\n  Testing WITHOUT Authorization header...")
    print(f"  Cookies: eCom_STORE_ID, STORE_ID_V2, fs-user-token={bool(session.cookies.get('fs-user-token'))}")
    
    r = requests.post(url, headers=headers, json=payload, cookies=cookies, timeout=30)
    print(f"  Status: {r.status_code}")
    
    if r.status_code == 200:
        data = r.json()
        products = data.get("products", data.get("items", data.get("results", [])))
        print(f"  SUCCESS: {len(products)} products")
        for p in products[:3]:
            name = p.get("name", p.get("displayName", "?"))
            price = p.get("price", p.get("displayPrice", p.get("unitPrice", "?")))
            print(f"    - {name}: {price}")
        return True
    else:
        print(f"  Error: {r.text[:300]}")
        return False
    

def test_edge_with_auth_header(session, token, store_id, query="milk"):
    """Test Edge API with Authorization header + cookies"""
    url = f"{EDGE_BASE}/search/paginated/products"
    
    cookies = dict(session.cookies)
    cookies["eCom_STORE_ID"] = store_id
    cookies["STORE_ID_V2"] = f"{store_id}|False"
    cookies["Region"] = "NI"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    
    # Working payload
    payload = {
        "algoliaQuery": {"query": query},
        "page": 0,
        "hitsPerPage": 20,
        "storeId": store_id,
        "sortOrder": "PRICE_ASC",
    }
    
    print(f"\n  Testing WITH Authorization header...")
    print(f"  Payload: {payload}")
    
    r = requests.post(url, headers=headers, json=payload, cookies=cookies, timeout=30)
    print(f"  Status: {r.status_code}")
    
    if r.status_code == 200:
        data = r.json()
        products = data.get("products", data.get("items", data.get("results", data.get("hits", []))))
        print(f"  SUCCESS: {len(products)} products")
        
        # Extract prices
        priced_products = []
        for p in products[:10]:
            name = p.get("name", p.get("displayName", p.get("title", "?")))
            price = extract_price(p)
            priced_products.append({"name": name, "price": price, "productId": p.get("productId")})
            if price:
                print(f"    - {name}: ${price}")
            else:
                print(f"    - {name}: NO PRICE")
        
        return priced_products
    elif r.status_code == 400:
        print(f"  Error: {r.text[:400]}")
    else:
        print(f"  Error: {r.text[:300]}")
    return None


def extract_price(product):
    """Extract price in dollars from product"""
    # Regular price in cents
    single_price = product.get("singlePrice", {})
    price_cents = single_price.get("price")
    
    # Promotional price
    promo_price_cents = None
    promotions = product.get("promotions", [])
    for promo in promotions:
        if promo.get("bestPromotion") and "rewardValue" in promo:
            promo_price_cents = promo["rewardValue"]
            break
    
    # Return promo price if available, else regular price
    final_cents = promo_price_cents if promo_price_cents is not None else price_cents
    if final_cents is not None:
        return round(final_cents / 100, 2)
    return None


def main():
    print("=" * 60)
    print("Testing Edge API WITHOUT mobile API token")
    print("=" * 60)
    
    # Get website session + token
    print("\n1. Getting website session and JWT...")
    session, token = get_token_from_website()
    
    if not token:
        print("  No token found in cookies. Checking response...")
    
    print(f"  Token: {'FOUND' if token else 'NOT FOUND'} ({token[:50] if token else 'N/A'}...)")
    print(f"  Cookies: {len(session.cookies)} cookies")
    for c in session.cookies:
        if c.name in ("fs-user-token", "eCom_STORE_ID", "STORE_ID_V2", "Region"):
            print(f"    {c.name}: {c.value[:50]}...")
    
    # Test store listing (works without auth per earlier test)
    print("\n2. Testing Edge store listing (no auth)...")
    test_edge_store_listing(session, None)
    
    # Test categories
    print("\n3. Testing Edge categories...")
    test_edge_categories(session, token, TEST_STORE)
    
    # Test product search - cookies only
    print("\n4. Testing product search (cookies only)...")
    test_edge_cookies_only(session, TEST_STORE, "milk")
    
    # Test product search - with auth header if we have token
    if token:
        print("\n5. Testing product search (with auth header)...")
        products = test_edge_with_auth_header(session, token, TEST_STORE, "milk")
        
        if products:
            print("\n  Full product sample:")
            import json
            print(json.dumps(products[0], indent=2)[:2000])
        
        # Test price comparison with REAL store IDs
        print("\n6. Testing price comparison across REAL stores...")
        real_stores = [
            "60928d93-06fa-4d8f-92a6-8c359e7e846d",  # Metro Auckland (from capture)
            "773ad0a0-024e-46c5-a94b-df1cf86d25cc",  # New World Albany
            "63190876-2bd4-4562-ae34-bb5caebab4f9",  # New World Birkenhead
        ]
        for store_id in real_stores:
            print(f"\n  Store: {store_id}")
            products = test_edge_with_auth_header(session, token, store_id, "milk")
            if products:
                prices = [p.get("price", p.get("displayPrice", p.get("unitPrice", p.get("salePrice", p.get("regularPrice", None))))) for p in products[:5]]
                print(f"    Prices: {prices}")
            time.sleep(1)


if __name__ == "__main__":
    main()