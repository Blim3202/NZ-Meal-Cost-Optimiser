import json
import requests
import sys
from pathlib import Path

WEB_BASE = "https://www.newworld.co.nz"
EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"

STORE_NAME = "New World Albany"
STORE_ID = "773ad0a0-024e-46c5-a94b-df1cf86d25cc"


DATA_DIR = Path(__file__).resolve().parent / "data"
OUTPUT_CSV = DATA_DIR / "newworld_hits.json"


# Non-food category1 blacklist (shared with newworld_api.py)
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


def authenticate(session):
    """Get website JWT (fs-user-token) via the public website flow."""
    session.get(WEB_BASE, timeout=30)
    r = session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    r.raise_for_status()
    token = session.cookies.get("fs-user-token")
    if not token:
        print("ERROR: Failed to obtain fs-user-token cookie")
        sys.exit(1)
    return token


def auth_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0",
    }


def store_cookies(store_id, region="NI"):
    return {
        "eCom_STORE_ID": store_id,
        "STORE_ID_V2": f"{store_id}|False",
        "Region": region,
    }


def pass1_relevance_search(token, store_id, query, max_hits=20):
    """Pass 1: Relevance search via products-index. Returns productIDs."""
    headers = auth_headers(token)
    cookies = store_cookies(store_id)
    payload = {
        "algoliaQuery": {"query": query},
        "page": 0,
        "hitsPerPage": max_hits,
        "storeId": store_id,
    }
    r = requests.post(
        f"{EDGE_BASE}/search/products/query/index/products-index",
        headers=headers,
        json=payload,
        cookies=cookies,
        timeout=30,
    )
    r.raise_for_status()
    hits = r.json().get("hits", [])
    
    product_ids = []
    raw_hits = []
    for h in hits:
        hr = h.get("_highlightResult", {})
        matched = any(
            isinstance(v, dict) and v.get("matchedWords")
            for v in hr.values()
        )
        cat1 = h.get("category1", [])
        if matched and not any(c in NON_FOOD_CATEGORIES for c in cat1):
            product_ids.append(h["productID"])
            raw_hits.append(h)
    return raw_hits

def main():
    print(f"=== New World Product Search Demo ===")
    print(f"Store: {STORE_NAME} ({STORE_ID})")
    print()

    # Authenticate
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    print("Step 1: Authenticating...")
    token = authenticate(session)
    print(f"  JWT: {token[:40]}...")
    print()

    # Pass 1: Relevance search
    query = "beef mince"
    print(f"Step 2: Pass 1 — Relevance search for '{query}'")
    raw_hits = pass1_relevance_search(token, STORE_ID, query, max_hits=20)

    with open(OUTPUT_CSV, "w", encoding="utf-8") as f:
        json.dump(raw_hits, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(raw_hits)} hits to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()