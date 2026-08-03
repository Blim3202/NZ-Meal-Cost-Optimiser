"""
Pak'nSave NZ Product Search Demo — MOBILE API (Single-Pass)
============================================================
Example script demonstrating single-pass product search via the Pak'nSave Mobile API.
Searches for a given ingredient at Pak'nSave Highland Park and prints the top 10 results
with pricing details.

What it does:
    1. Authenticates via guest token (mobile/user/login/guest, banner=PNS)
    2. Runs a single-pass search via /mobile/ecomm-products/PNS/{storeId}/search?q={query}
    3. Prints top 10 results with pricing, unit info, and availability
    4. Dumps raw JSON for the first product

Store info:
    Name:       PAK'nSAVE Highland Park
    Store ID:   2a1b331a-fc4a-496a-b072-e97cc8f70cae

Usage:
    python scripts/paknsave/paknsave_search_demo_mobile.py [ingredient]
    python scripts/paknsave/paknsave_search_demo_mobile.py "beef mince"

Reference: PaknSave_API.md section 5.2 (Mobile API ecomm-products search)
"""

import argparse
import json
import cloudscraper
import sys

MOBILE_BASE = "https://api-prod.prod.fsniwaikato.kiwi/prod"

STORE_NAME = "PAK'nSAVE Highland Park"
STORE_ID = "2a1b331a-fc4a-496a-b072-e97cc8f70cae"
BANNER = "PNS"
USER_AGENT = "PAKnSAVEApp/4.32.0"


def authenticate(scraper):
    """Get guest token via the mobile API login/guest endpoint."""
    r = scraper.post(
        f"{MOBILE_BASE}/mobile/user/login/guest",
        json={"banner": BANNER},
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
    )
    r.raise_for_status()
    data = r.json()
    token = data["access_token"]
    print(f"  Guest token: {token[:40]}...")
    print(f"  Expires in:  {data.get('expires_in', 'unknown')}s")
    return token


def auth_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }


def search_products(scraper, token, store_id, query):
    """Single-pass product search via mobile API.

    POST /mobile/ecomm-products/PNS/{storeId}/search?q={query}
    Response may be a bare list or wrapped in a 'products' key.
    """
    r = scraper.post(
        f"{MOBILE_BASE}/mobile/ecomm-products/{BANNER}/{store_id}/search",
        params={"q": query},
        headers=auth_headers(token),
        json=[],
    )
    if r.status_code != 200:
        print(f"ERROR: Search returned HTTP {r.status_code}")
        print(r.text[:500])
        sys.exit(1)

    data = r.json()
    # Mobile API may return a list directly or wrapped under "products"
    if isinstance(data, list):
        return data, None
    raw_hits = data
    products = data.get("products", [])
    total_hits = data.get("totalHits")
    return products, total_hits


def extract_price(product):
    """Price in dollars (API returns cents)."""
    price_cents = product.get("price")
    return price_cents / 100.0 if price_cents and price_cents > 0 else None


def main():
    parser = argparse.ArgumentParser(
        description="Pak'nSave Mobile API product search demo (single-pass).",
        epilog="Example: python paknsave_search_demo_mobile.py 'beef mince'",
    )
    parser.add_argument(
        "ingredient",
        nargs="?",
        default="gravy dog food",
        help="Ingredient to search for (default: 'gravy dog food')",
    )
    args = parser.parse_args()
    query = args.ingredient

    print(f"=== Pak'nSave Product Search Demo (MOBILE API) ===")
    print(f"Store: {STORE_NAME} ({STORE_ID})")
    print(f"Banner: {BANNER}")
    print()

    # Authenticate
    scraper = cloudscraper.create_scraper()
    print("Step 1: Authenticating (guest token)...")
    token = authenticate(scraper)
    print()

    # Single-pass search
    print(f"Step 2: Searching for '{query}' (single-pass, per-store pricing)")
    products, total_hits = search_products(scraper, token, STORE_ID, query)
    print(f"  Products returned: {len(products)}")
    if total_hits is not None:
        print(f"  Total hits (API):  {total_hits}")
    print()

    # Print results
    print(f"Top 10 results for '{query}' at {STORE_NAME}:")
    print("=" * 80)
    for i, prod in enumerate(products[:10], 1):
        name = prod.get("name", "")
        brand = prod.get("brand", "")
        units = prod.get("units", "")
        unit_price = prod.get("unitPrice", "")
        price = extract_price(prod)
        categories = prod.get("categories", [])
        available_in_store = prod.get("availableInStore")
        available_online = prod.get("availableOnline")
        sale_type = prod.get("saleType", "")

        price_str = f"${price:.2f}" if price is not None else "N/A"

        print(f"{i:>2}. {name}")
        if brand:
            print(f"    Brand: {brand}")
        print(f"    Units: {units}  |  Unit Price: {unit_price}  |  Price: {price_str}")
        print(f"    Categories: {', '.join(categories) if categories else '(none)'}")
        print(f"    Available: store={available_in_store}, online={available_online}  |  Sale type: {sale_type}")
        print()

    # Dump full JSON for first product to show raw API output
    if products:
        print("=" * 80)
        print("RAW JSON for first product:")
        print(json.dumps(products[1], indent=2))


if __name__ == "__main__":
    main()
