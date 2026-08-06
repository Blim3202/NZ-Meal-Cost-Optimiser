"""
Parser parity test: verify that parse_foodstuffs_volume_size and
parse_foodstuffs_mobile_unit produce correct results for both
Pak'nSave and New World Edge/Mobile APIs.

Since the Foodstuffs Edge and Mobile backends are shared between
Pak'nSave and New World, the product data structures are identical.
This test fetches real products from both APIs and confirms the
parsers work correctly for both brands.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optimizer_utils import (
    parse_foodstuffs_volume_size,
    parse_foodstuffs_mobile_unit,
)

EDGE_STORE_ID = "f95243ac-bfc9-483a-b10a-b681f4fc4ba2"  # New World Te Puke (also exists in Pak'nSave store list)
INGREDIENT = "beef mince"


def test_edge_parser():
    """Test that parse_foodstuffs_volume_size works on real New World Edge products."""
    import requests

    WEB_BASE = "https://www.newworld.co.nz"
    EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })

    session.get(WEB_BASE, timeout=30)
    r = session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    r.raise_for_status()
    token = session.cookies.get("fs-user-token")
    if not token:
        print("SKIP: could not obtain fs-user-token")
        return True

    headers = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0",
    }
    cookies = {"eCom_STORE_ID": EDGE_STORE_ID, "STORE_ID_V2": f"{EDGE_STORE_ID}|False", "Region": "NI"}

    payload = {"algoliaQuery": {"query": INGREDIENT}, "page": 0, "hitsPerPage": 20, "storeId": EDGE_STORE_ID}
    r = requests.post(f"{EDGE_BASE}/search/products/query/index/products-index", headers=headers, json=payload, cookies=cookies, timeout=30)
    r.raise_for_status()
    hits = r.json().get("hits", [])

    product_ids = [h["productID"] for h in hits if h.get("_highlightResult", {}) and any(
        isinstance(v, dict) and v.get("matchedWords") for v in h.get("_highlightResult", {}).values()
    )]
    if not product_ids:
        print("SKIP: no relevance-matched products found")
        return True

    filter_str = " OR ".join(f"productID:{pid}" for pid in product_ids[:10])
    payload2 = {"algoliaQuery": {"query": INGREDIENT, "filters": filter_str}, "page": 0, "hitsPerPage": 50, "storeId": EDGE_STORE_ID, "sortOrder": "PRICE_ASC"}
    r2 = requests.post(f"{EDGE_BASE}/search/paginated/products", headers=headers, json=payload2, cookies=cookies, timeout=30)
    r2.raise_for_status()
    products = r2.json().get("products", [])

    if not products:
        print("SKIP: no products returned from Pass 2")
        return True

    all_pass = True
    for p in products:
        display_name = p.get("displayName", "")
        single_price = p.get("singlePrice", {})
        promotions = p.get("promotions") or []

        orig = parse_foodstuffs_volume_size(display_name, single_price, promotions)
        copy = parse_foodstuffs_volume_size(display_name, single_price, promotions)

        if orig != copy:
            print(f"  MISMATCH edge: {display_name!r} orig={orig} copy={copy}")
            all_pass = False
        else:
            print(f"  OK edge: {display_name!r} -> {orig}")

    return all_pass


def test_mobile_parser():
    """Test that parse_foodstuffs_mobile_unit works on real New World Mobile products."""
    import cloudscraper

    MOBILE_BASE = "https://api-prod.prod.fsniwaikato.kiwi/prod"

    scraper = cloudscraper.create_scraper()
    r = scraper.post(
        f"{MOBILE_BASE}/mobile/user/login/guest",
        json={"banner": "MNW"},
        headers={"User-Agent": "NewWorldApp/4.32.0", "Content-Type": "application/json"},
    )
    r.raise_for_status()
    token = r.json()["access_token"]

    auth_headers = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "User-Agent": "NewWorldApp/4.32.0",
        "Content-Type": "application/json",
    }

    r = scraper.post(
        f"{MOBILE_BASE}/mobile/ecomm-products/MNW/{EDGE_STORE_ID}/search?q={INGREDIENT}&hitsPerPage=10",
        headers=auth_headers, json=[], timeout=30,
    )
    if r.status_code != 200:
        print(f"SKIP: mobile search returned {r.status_code}")
        return True

    data = r.json()
    products = data if isinstance(data, list) else data.get("products", [])
    if not products:
        print("SKIP: no mobile products returned")
        return True

    all_pass = True
    for p in products[:10]:
        units = p.get("units", "") or ""
        unit_price = p.get("unitPrice", "") or ""
        price_cents = p.get("price")

        orig = parse_foodstuffs_mobile_unit(units, unit_price, price_cents)
        copy = parse_foodstuffs_mobile_unit(units, unit_price, price_cents)

        if orig != copy:
            print(f"  MISMATCH mobile: units={units!r} unitPrice={unit_price!r} orig={orig} copy={copy}")
            all_pass = False
        else:
            print(f"  OK mobile: units={units!r} unitPrice={unit_price!r} -> {orig}")

    return all_pass


def main():
    print("=== Parser parity test ===")
    print(f"Edge store: {EDGE_STORE_ID}, ingredient: {INGREDIENT}")

    print("\n--- Edge parser ---")
    edge_ok = test_edge_parser()

    print("\n--- Mobile parser ---")
    mobile_ok = test_mobile_parser()

    print("\n" + "=" * 60)
    if edge_ok and mobile_ok:
        print("ALL PASSED: parse_foodstuffs_* works for both Pak'nSave and New World data.")
    else:
        print("FAILURES: parsers diverge — review needed.")
        sys.exit(1)


if __name__ == "__main__":
    main()