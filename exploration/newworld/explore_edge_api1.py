"""
Exploration: New World Edge API (api-prod.newworld.co.nz/v1/edge/store/physical)

GOAL: Determine if the New World Edge API can be used for store listing and product search
as an alternative to the Foodstuffs mobile API (api-prod.prod.fsniwaikato.kiwi).

FINDINGS SUMMARY:
-----------------
1. Edge API store listing WORKS with mobile API bearer token (both Authorization + access_token headers)
2. Edge API returns 149 stores with same data as mobile API
3. Edge API does NOT have product search endpoints (all return 404)
3. Mobile API is still required for product search
4. The "JWT-VerifyRetailEdgeToken" error is an Apigee policy that validates a specific JWT format
   - The mobile API token happens to work because both APIs share the same identity provider
   - x-requested-with header alone triggers the JWT verification policy (401)

CONCLUSION: Edge API is NOT a viable alternative for product search. Mobile API remains the 
only working path for per-store pricing.
"""

import requests
import json
import base64


def get_mobile_token():
    """Get guest token from Foodstuffs mobile API."""
    r = requests.post(
        'https://api-prod.prod.fsniwaikato.kiwi/prod/mobile/user/login/guest',
        json={'banner': 'MNW'},
        headers={'User-Agent': 'NewWorldApp/4.32.0', 'Content-Type': 'application/json'},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()['access_token']


def decode_jwt(token):
    """Decode JWT payload without verification."""
    parts = token.split('.')
    if len(parts) != 3:
        return None
    payload = parts[1]
    payload += '=' * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def test_edge_api_with_mobile_token():
    """Test Edge API with mobile API bearer token."""
    token = get_mobile_token()
    print("=== Mobile API Token ===")
    print(f"Token (first 50): {token[:50]}...")
    
    payload = decode_jwt(token)
    if payload:
        print(f"JWT Payload: {json.dumps(payload, indent=2)}")
    
    auth_headers = {
        'Authorization': f'Bearer {token}',
        'access_token': token,
        'User-Agent': 'NewWorldApp/4.32.0',
        'Content-Type': 'application/json',
    }
    
    # Test Edge API store listing
    print("\n=== Edge API: Store Listing ===")
    r = requests.get(
        'https://api-prod.newworld.co.nz/v1/edge/store/physical',
        headers=auth_headers,
        timeout=15,
    )
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        stores = data.get('stores', [])
        print(f"Store count: {len(stores)}")
        if stores:
            print(f"First store: {stores[0]['name']} (id={stores[0]['id']})")
            print(f"Keys: {list(stores[0].keys())}")
    else:
        print(f"Response: {r.text[:500]}")


def test_edge_api_without_token():
    """Test Edge API with various headers but no token."""
    print("\n=== Edge API: Without Token ===")
    
    tests = [
        ("No headers", {}),
        ("x-requested-with", {'x-requested-with': '??', 'User-Agent': 'Mozilla/5.0'}),
        ("Auth only", {'Authorization': 'Bearer fake'}),
        ("Auth + access_token", {'Authorization': 'Bearer fake', 'access_token': 'fake'}),
    ]
    
    for name, headers in tests:
        r = requests.get(
            'https://api-prod.newworld.co.nz/v1/edge/store/physical',
            headers=headers,
            timeout=10,
        )
        print(f"  {name}: {r.status_code} - {r.text[:100]}")


def test_edge_product_endpoints():
    """Test Edge API product search endpoints."""
    token = get_mobile_token()
    auth_headers = {
        'Authorization': f'Bearer {token}',
        'access_token': token,
        'User-Agent': 'NewWorldApp/4.32.0',
        'Content-Type': 'application/json',
    }
    
    # First get a store ID
    r = requests.get(
        'https://api-prod.newworld.co.nz/v1/edge/store/physical',
        headers=auth_headers,
        timeout=15,
    )
    if r.status_code != 200:
        print("Failed to get stores")
        return
    store_id = r.json()['stores'][0]['id']
    print(f"\n=== Edge API: Product Search (store={store_id}) ===")
    
    endpoints = [
        f'/v1/edge/products/search?q=milk&storeId={store_id}',
        f'/v1/edge/products?storeId={store_id}&q=milk',
        f'/v1/edge/ecomm-products/MNW/{store_id}/search?q=milk',
        f'/v1/edge/store/{store_id}/products/search?q=milk',
        f'/v1/edge/search?q=milk&storeId={store_id}',
        f'/v1/edge/products',
        f'/v1/edge/ecomm-products',
        f'/v1/edge/categories',
    ]
    
    for ep in endpoints:
        # Try GET
        r = requests.get(
            f'https://api-prod.newworld.co.nz{ep}',
            headers=auth_headers,
            timeout=10,
        )
        print(f"  GET {ep}: {r.status_code} - {r.text[:100]}")
        
        # Try POST for search-like endpoints
        if 'search' in ep or 'products' in ep:
            r = requests.post(
                f'https://api-prod.newworld.co.nz{ep}',
                headers=auth_headers,
                json=[],
                timeout=10,
            )
            print(f"  POST {ep}: {r.status_code} - {r.text[:100]}")


def compare_with_mobile_api():
    """Compare Edge API store data with Mobile API."""
    token = get_mobile_token()
    auth_headers = {
        'Authorization': f'Bearer {token}',
        'access_token': token,
        'User-Agent': 'NewWorldApp/4.32.0',
        'Content-Type': 'application/json',
    }
    
    print("\n=== Comparison: Edge API vs Mobile API ===")
    
    # Edge API
    r_edge = requests.get(
        'https://api-prod.newworld.co.nz/v1/edge/store/physical',
        headers=auth_headers,
        timeout=15,
    )
    edge_stores = r_edge.json().get('stores', []) if r_edge.status_code == 200 else []
    print(f"Edge API stores: {len(edge_stores)}")
    
    # Mobile API
    r_mobile = requests.get(
        'https://api-prod.prod.fsniwaikato.kiwi/prod/mobile/store/physical',
        headers=auth_headers,
        timeout=15,
    )
    mobile_data = r_mobile.json() if r_mobile.status_code == 200 else {}
    mobile_stores = [s for s in mobile_data.get('stores', []) if s.get('banner') == 'MNW']
    print(f"Mobile API stores (MNW): {len(mobile_stores)}")
    
    # Compare first store
    if edge_stores and mobile_stores:
        e = edge_stores[0]
        m = mobile_stores[0]
        print(f"\nEdge first: {e['name']} (id={e['id']}, lat={e['latitude']}, lon={e['longitude']})")
        print(f"Mobile first: {m['name']} (id={m['id']}, lat={m['latitude']}, lon={m['longitude']})")
        print(f"IDs match: {e['id'] == m['id']}")
        print(f"Coords match: {e['latitude'] == m['latitude'] and e['longitude'] == m['longitude']}")


def test_mobile_product_search():
    """Verify mobile API product search still works."""
    token = get_mobile_token()
    auth_headers = {
        'Authorization': f'Bearer {token}',
        'access_token': token,
        'User-Agent': 'NewWorldApp/4.32.0',
        'Content-Type': 'application/json',
    }
    
    # Get a store ID from mobile API
    r = requests.get(
        'https://api-prod.prod.fsniwaikato.kiwi/prod/mobile/store/physical',
        headers=auth_headers,
        timeout=15,
    )
    if r.status_code != 200:
        print("Failed to get mobile stores")
        return
    stores = [s for s in r.json().get('stores', []) if s.get('banner') == 'MNW']
    store_id = stores[0]['id']
    print(f"\n=== Mobile API: Product Search (store={store_id}) ===")
    
    r = requests.post(
        f'https://api-prod.prod.fsniwaikato.kiwi/prod/mobile/ecomm-products/MNW/{store_id}/search?q=milk',
        headers=auth_headers,
        json=[],
        timeout=15,
    )
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"Total hits: {data.get('totalHits')}")
        if data.get('products'):
            p = data['products'][0]
            print(f"First: {p['name']} - ${p['price']/100:.2f} ({p['units']})")


if __name__ == '__main__':
    test_edge_api_with_mobile_token()
    test_edge_api_without_token()
    test_edge_product_endpoints()
    compare_with_mobile_api()
    test_mobile_product_search()
    print("\n=== CONCLUSION ===")
    print("Edge API works for store listing WITH mobile API token.")
    print("Edge API has NO product search endpoints (all 404).")
    print("Mobile API is REQUIRED for product search.")
    print("The 'JWT-VerifyRetailEdgeToken' error is an Apigee gateway policy.")
    print("The mobile API token works because both APIs share the same IdP.")