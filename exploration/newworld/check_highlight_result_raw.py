"""
Compare _highlightResult across all three Algolia indices for 'milk'.
Dumps the full first hit from each index to see exactly what differs.
"""

import requests
import json

WEB_BASE = "https://www.newworld.co.nz"
EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"
STORE_ID = "60928d93-06fa-4d8f-92a6-8c359e7e846d"

INDICES = [
    "products-index",
    "products-index-popularity-asc",
    "products-index-popularity-desc",
]


def get_jwt():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    session.get(WEB_BASE, timeout=30)
    session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    return session.cookies.get("fs-user-token")


def search_index(token, index_name, query="milk", hits_per_page=1):
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
        "eCom_STORE_ID": STORE_ID,
        "STORE_ID_V2": f"{STORE_ID}|False",
        "Region": "NI",
    }
    payload = {
        "algoliaQuery": {"query": query},
        "page": 0,
        "hitsPerPage": hits_per_page,
        "storeId": STORE_ID,
    }
    r = requests.post(url, headers=headers, json=payload, cookies=cookies, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    token = get_jwt()
    if not token:
        print("ERROR: no JWT")
        return

    for index in INDICES:
        print(f"\n{'='*70}")
        print(f"INDEX: {index}")
        print(f"{'='*70}")
        data = search_index(token, index)

        # print(data)

        hits = data.get("hits", [])
        print(f"Total hits returned: {data.get('nbHits', '?')}")
        if not hits:
            print("  (no hits)")
            continue

        hit = hits[0]
        print(f"\nFirst hit keys: {sorted(hit.keys())}")
        print(f"\nBasic fields:")
        print(f"  productID:     {hit.get('productID')}")
        print(f"  DisplayName:   {hit.get('DisplayName')}")
        print(f"  brand:         {hit.get('brand')}")
        print(f"  averagePrice:  {hit.get('averagePrice')}")
        print(f"  popularity:    {hit.get('popularity')}")
        print(f"  category0:     {hit.get('category0')}")
        print(f"  category1:     {hit.get('category1')}")
        print(f"  category2:     {hit.get('category2')}")

        hl = hit.get("_highlightResult")
        print(f"\n_highlightResult exists: {hl is not None}")
        if hl:
            print(f"_highlightResult keys: {sorted(hl.keys())}")
            for field, info in sorted(hl.items()):
                if isinstance(info, dict):
                    matched = info.get("matchedWords", [])
                    value = info.get("value", "")[:80]
                    print(f"  {field}: matchedWords={matched} value=\"{value}\"")
                else:
                    print(f"  {field}: {type(info).__name__} = {str(info)[:80]}")
        else:
            print("  _highlightResult is None or missing")


if __name__ == "__main__":
    main()
