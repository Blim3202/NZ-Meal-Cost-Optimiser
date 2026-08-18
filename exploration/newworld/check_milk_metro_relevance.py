import requests

WEB_BASE = "https://www.newworld.co.nz"
EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"
STORE_ID = "60928d93-06fa-4d8f-92a6-8c359e7e846d"

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0", "Origin": WEB_BASE, "Referer": WEB_BASE + "/"})
session.get(WEB_BASE, timeout=30)
session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
token = session.cookies.get("fs-user-token")

headers = {
    "Authorization": f"Bearer {token}",
    "access_token": token,
    "Content-Type": "application/json",
    "Origin": WEB_BASE,
    "Referer": f"{WEB_BASE}/shop",
    "User-Agent": "Mozilla/5.0",
}
cookies = {
    "eCom_STORE_ID": STORE_ID,
    "STORE_ID_V2": f"{STORE_ID}|False",
    "Region": "NI",
}

print("=" * 70)
print("FOCUSED TEST: milk at Metro Auckland (products-index = relevance sorted)")
print("=" * 70)

# PASS 1: Relevance search
print("\n[PASS 1] Algolia Relevance Search - products-index")
url1 = f"{EDGE_BASE}/search/products/query/index/products-index"
payload1 = {"algoliaQuery": {"query": "milk"}, "page": 0, "hitsPerPage": 15, "storeId": STORE_ID}
r1 = requests.post(url1, headers=headers, json=payload1, cookies=cookies, timeout=30)
data1 = r1.json()
hits = data1.get("hits", [])

print(f"Total hits: {len(hits)} (sorted by RELEVANCE - Algolia default)") # Perfect for our use case
print("Top 10 by relevance:")
for i, h in enumerate(hits[:10]):
    pid = h.get("productID")
    dname = h.get("DisplayName")
    brand = h.get("brand")
    avg = h.get("averagePrice")
    hr = h.get("_highlightResult", {})
    matched = []
    for field, info in hr.items():
        if isinstance(info, dict) and info.get("matchedWords"):
            matched.append(field)
    print(f"  {i+1:2}. {pid} - {dname} ({brand}) - Avg: ${avg} - Matched: {matched}")

# PASS 2: Get per-store pricing
print("\n[PASS 2] Per-Store Pricing for top 10 relevant products")
top_ids = [h.get("productID") for h in hits[:10]]
filter_str = " OR ".join([f"productID:{pid}" for pid in top_ids])

url2 = f"{EDGE_BASE}/search/paginated/products"
payload2 = {
    "algoliaQuery": {"query": "milk", "filters": filter_str},
    "page": 0, "hitsPerPage": 20, "storeId": STORE_ID, "sortOrder": "PRICE_ASC"
}
r2 = requests.post(url2, headers=headers, json=payload2, cookies=cookies, timeout=30)
data2 = r2.json()
products = data2.get("products", [])

print(f"Products with pricing at this store: {len(products)}")
print("Sorted by PRICE_ASC at Metro Auckland:")
print(f"  {'#':>2} {'Product':<35} {'Size':<10} {'Price':>8} {'Promo':>8}")
print("  " + "-" * 70)
for i, p in enumerate(products):
    name = (p.get("name") or "")[:34]
    size = (p.get("displayName") or "")[:9]
    sp = p.get("singlePrice", {})
    price = sp.get("price")
    promo = p.get("promotions", [])
    promo_val = promo[0].get("rewardValue") if promo else None
    price_str = f"${price/100:.2f}" if price else "N/A"
    promo_str = f"${promo_val/100:.2f}" if promo_val else ""
    print(f"  {i+1:>2} {name:<35} {size:<10} {price_str:>8} {promo_str:>8}")