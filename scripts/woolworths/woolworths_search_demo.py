"""
Woolworths NZ Product Search Demo
==================================
Example script demonstrating per-store product search via the Woolworths API.
Searches for products at a single hardcoded store (Greville Road) and prints
the top 10 results with pricing details.

What it does:
    1. Creates a fresh session and seeds cookies via GET /
    2. Injects the cw-lrkswrdjp cookie for Greville Road (pickupAddressId 3105636)
    3. Validates store context via /api/v1/shell
    4. Searches GET /api/v1/products?target=search&search=<query>&size=10
    5. Filters out ad/promo items (no SKU) and prints results
    6. Dumps raw JSON for the first product

Store info (from data/woolworths_store_data.json):
    Name:               Woolworths Greville Road
    pickupAddressId:    3105636
    fulfilmentStoreId:  9171 (extra1)

Usage:
    python woolworths_search_demo.py

Reference: Woolworths_API.md sections 3, 4, 5.2, 8
"""

import json
import requests
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
BASE_URL = "https://www.woolworths.co.nz/api/v1"
SITE_URL = "https://www.woolworths.co.nz/"

HEADERS = {
    "x-requested-with": "??",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OnionWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-NZ,en;q=0.9",
    "Referer": "https://www.woolworths.co.nz/",
}

STORE_NAME = "Woolworths Greville Road"
PICKUP_ADDRESS_ID = "3105636"
FULFILMENT_STORE_ID = 9171  # extra1 from woolworths_store_data.json


def load_store_mapping():
    """Load fulfilmentStoreId mapping from woolworths_store_data.json."""
    store_data_path = DATA_DIR / "woolworths_store_data.json"
    with open(store_data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    mapping = {}
    for detail in data.get("siteDetail", []):
        site = detail.get("site", {})
        extra1 = site.get("extra1")
        extra2 = site.get("extra2")
        name = site.get("name", "")
        if extra1 and extra2 and str(extra1) != "null" and str(extra2) != "null":
            mapping[str(extra2)] = {
                "fulfilmentStoreId": int(extra1),
                "name": name,
            }
    return mapping


def create_session():
    """Create a requests.Session with Woolworths headers and seed cookies."""
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get(SITE_URL, timeout=15)
    return session


def set_store_context(session, pickup_address_id):
    """Set per-store pricing by injecting the cw-lrkswrdjp cookie."""
    mapping = load_store_mapping()
    store = mapping.get(str(pickup_address_id))
    if not store:
        print(f"ERROR: Store {pickup_address_id} not in mapping")
        sys.exit(1)

    fsid = store["fulfilmentStoreId"]
    cookie_val = f"dm-Pickup,f-{fsid},s-38"
    session.cookies.set("cw-lrkswrdjp", cookie_val, domain="www.woolworths.co.nz", path="/")

    # Validate via shell
    resp = session.get(f"{BASE_URL}/shell", timeout=15)
    shell = resp.json()
    fulf = shell.get("context", {}).get("fulfilment", {})
    actual_fsid = fulf.get("fulfilmentStoreId")
    print(f"Store context set: {store['name']}")
    print(f"  fulfilmentStoreId: {actual_fsid}")
    print(f"  method: {fulf.get('method')}")
    if actual_fsid == 9171 and fsid != 9171:
        print("WARNING: Cookie may not have taken effect (showing default store)")
    return fulf


def search_products(session, query, size=10):
    """Search for products with the current store context.

    Fetches extra to account for ad/promo items that lack SKU/price.
    """
    resp = session.get(
        f"{BASE_URL}/products",
        params={"target": "search", "search": query, "size": size + 5},
        timeout=15,
    )
    data = resp.json()
    all_items = data.get("products", {}).get("items", [])
    total = data.get("products", {}).get("totalItems", 0)
    # Filter out ads/promos (no sku = not a real product)
    items = [i for i in all_items if i.get("sku")]
    return items[:size], total


def main():
    print(f"=== Woolworths Onion Search ===")
    print(f"Store: {STORE_NAME} (pickupAddressId={PICKUP_ADDRESS_ID})")
    print()

    # Create session and set store context
    session = create_session()
    set_store_context(session, PICKUP_ADDRESS_ID)
    print()

    # Search for Onion
    query = "Onion"
    print(f"Searching for: '{query}' (top 10 results)")
    print("=" * 80)

    items, total = search_products(session, query, size=10)
    print(f"Total results: {total}")
    print()

    for i, item in enumerate(items, 1):
        price_info = item.get("price", {})
        sale_price = price_info.get("salePrice")
        original_price = price_info.get("originalPrice")
        is_special = price_info.get("isSpecial", False)
        brand = item.get("brand", "")
        name = item.get("name", "")
        sku = item.get("sku", "")
        unit = item.get("unit", "")

        price_str = f"${sale_price:.2f}" if sale_price is not None else "N/A"
        if is_special:
            price_str += " SPECIAL"
        if original_price and sale_price and original_price != sale_price:
            price_str += f" (was ${original_price:.2f})"

        print(f"{i:>2}. {name}")
        print(f"    Brand: {brand}  |  SKU: {sku}  |  Unit: {unit}")
        print(f"    Price: {price_str}")
        print()

    # Dump full JSON for first product to show raw API output
    print("=" * 80)
    print("RAW JSON for first product:")
    print(json.dumps(items[0], indent=2))


if __name__ == "__main__":
    main()
