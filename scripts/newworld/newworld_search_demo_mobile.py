"""
New World NZ Product Search Demo — MOBILE API (Single-Pass)
=================================================================
Example script demonstrating single-pass product search via the New World
Mobile API. Searches for a given ingredient at New World Albany and prints
the top 10 results with pricing details.

What it does:
    1. Authenticates via guest token (mobile/user/login/guest, banner=MNW)
    2. Runs a single-pass search via /mobile/ecomm-products/MNW/{storeId}/search
    3. Prints top 10 results with pricing, unit info, and category1
    4. Dumps raw JSON for the first product

Store info:
    Name:       New World Albany
    Store ID:   773ad0a0-024e-46c5-a94b-df1cf86d25cc

Usage:
    python scripts/newworld/newworld_search_demo_mobile.py [ingredient]
    python scripts/newworld/newworld_search_demo_mobile.py "milk"

Reference: NewWorld_API.md section 5 (Mobile API ecomm-products search)
"""

import argparse
import json
import sys

import cloudscraper

MOBILE_BASE = "https://api-prod.prod.fsniwaikato.kiwi/prod"

STORE_NAME = "New World Botany"
STORE_ID = "c387ac97-5e0a-43ed-9c93-f1edccda298d"
BANNER = "MNW"
USER_AGENT = "NewWorldApp/4.32.0"

NON_FOOD_CATEGORIES = {
    "Dog", "Cat", "Pet Health & Accessories", "Birds, Fish & Small Animals",
    "Baby & Toddler Food", "Baby & Toddler Toiletries", "Baby Formula",
    "Baby Wipes", "Nappies & Changing", "Nursing & Feeding",
    "Cleaning & Accessories", "Dishwashing", "Bathroom & Toilet Cleaners",
    "Kitchen Cleaners", "Laundry", "Food Wrap, Storage & Bags",
    "Pest & Insect Control", "Homewares",
    "Bath, Shower & Soap", "Dental & Oral Care", "Deodorant & Body Sprays",
    "Hair Care", "Make Up & Nail Care", "Medical & First Aid",
    "Period & Continence Care", "Shaving & Hair Removal", "Skin Care & Sun Care",
    "Tissues & Cotton Wool", "Toilet Paper, Tissues & Paper Towels",
    "Vitamins & Supplements",
    "Stationery & Entertainment", "Clothing & Accessories",
    "Garage & Outdoor", "Batteries & Electrical",
}


def authenticate(scraper):
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


def search_products(scraper, token, store_id, query, hits_per_page=20):
    r = scraper.post(
        f"{MOBILE_BASE}/mobile/ecomm-products/{BANNER}/{store_id}/search",
        params={"q": query, "hitsPerPage": hits_per_page},
        headers=auth_headers(token),
        json=[],
    )
    if r.status_code != 200:
        print(f"ERROR: Search returned HTTP {r.status_code}")
        print(r.text[:500])
        sys.exit(1)

    data = r.json()
    if isinstance(data, list):
        return data
    products = data.get("products", [])
    return products


def is_food_product(product):
    categories = product.get("categories", []) or []
    cat1 = categories[0] if categories else ""
    if not cat1:
        return True
    return cat1 not in NON_FOOD_CATEGORIES


def extract_price(product):
    price_cents = product.get("price")
    return price_cents / 100.0 if price_cents and price_cents > 0 else None


def main():
    parser = argparse.ArgumentParser(
        description="New World Mobile API product search demo (single-pass).",
        epilog="Example: python newworld_search_demo_mobile.py 'milk'",
    )
    parser.add_argument(
        "ingredient",
        nargs="?",
        default="milk",
        help="Ingredient to search for (default: 'milk')",
    )
    args = parser.parse_args()
    query = args.ingredient

    print(f"=== New World Product Search Demo (MOBILE API) ===")
    print(f"Store: {STORE_NAME} ({STORE_ID})")
    print(f"Banner: {BANNER}")
    print()

    scraper = cloudscraper.create_scraper()
    print("Step 1: Authenticating (guest token)...")
    token = authenticate(scraper)
    print()

    print(f"Step 2: Searching for '{query}' (single-pass, per-store pricing)")
    products = search_products(scraper, token, STORE_ID, query, hits_per_page=20)
    print(f"  Products returned: {len(products)}")
    print()

    food_products = [p for p in products if is_food_product(p)]
    print(f"  Food products: {len(food_products)}")
    print()

    print(f"Top 10 results for '{query}' at {STORE_NAME}:")
    print("=" * 80)
    for i, prod in enumerate(food_products[:10], 1):
        name = prod.get("name", "")
        brand = prod.get("brand", "")
        units = prod.get("units", "")
        unit_price = prod.get("unitPrice", "")
        price = extract_price(prod)
        categories = prod.get("categories", [])
        available_in_store = prod.get("availableInStore")
        available_online = prod.get("availableInOnline")
        sale_type = prod.get("saleType", "")

        price_str = f"${price:.2f}" if price is not None else "N/A"

        print(f"{i:>2}. {name}")
        if brand:
            print(f"    Brand: {brand}")
        print(f"    Units: {units}  |  Unit Price: {unit_price}  |  Price: {price_str}")
        print(f"    Categories: {', '.join(categories) if categories else '(none)'}")
        print(f"    Available: store={available_in_store}, online={available_online}  |  Sale type: {sale_type}")
        print()

    if products:
        print("=" * 80)
        print("RAW JSON for first product:")
        print(json.dumps(products[1], indent=2))


if __name__ == "__main__":
    main()