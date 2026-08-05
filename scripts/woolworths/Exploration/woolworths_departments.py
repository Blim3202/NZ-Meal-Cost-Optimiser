"""
Woolworths NZ Department & Aisle Explorer
=========================================
Prints the full Woolworths product taxonomy: 14 top-level departments and their
sub-departments (aisles), fetched live from the API.

How it works:
    1. GET /api/v1/shell  - extracts department slugs from mainNavs[1] (Browse)
    2. For each department, GET /api/v1/products?target=browse&dasFilter=Department;;<slug>;false&size=1
       - the response dasFacets[] array contains the aisle-level breakdown

Output format:
    Department Name  (/slug, N products)
      [aisle_id]  Aisle Name                          (N products)

Usage:
    python woolworths_departments.py

Reference: Woolworths_API.md sections 5.1, 5.2, 6.2
"""

import json
import requests

BASE_URL = "https://www.woolworths.co.nz/api/v1"
SITE_URL = "https://www.woolworths.co.nz/"

HEADERS = {
    "x-requested-with": "??",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-NZ,en;q=0.9",
}


def create_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get(SITE_URL, timeout=15)
    return session


def get_departments(session):
    """Get department slugs and names from /shell."""
    resp = session.get(f"{BASE_URL}/shell", timeout=15)
    shell = resp.json()
    # mainNavs[1] = "Browse" block, navigationItems[0].items = department list
    nav_items = shell.get("mainNavs", [])[1].get("navigationItems", [])[0].get("items", [])
    departments = []
    for item in nav_items:
        facets = item.get("dasFacets", [])
        if facets:
            departments.append({
                "slug": item.get("url", "").lstrip("/").split("/")[-1],
                "name": item.get("label", facets[0].get("name", "")),
                "productCount": facets[0].get("productCount", 0),
            })
    return departments


def get_aisles(session, dept_slug):
    """Get aisles for a department via dasFacets on a browse query."""
    resp = session.get(
        f"{BASE_URL}/products",
        params={
            "target": "browse",
            "dasFilter": f"Department;;{dept_slug};false",
            "size": 1,
        },
        timeout=15,
    )
    data = resp.json()
    facets = data.get("dasFacets", [])
    aisles = []
    for f in facets:
        if f.get("key") == "Aisle":
            aisles.append({
                "id": f.get("value"),
                "name": f.get("name"),
                "productCount": f.get("productCount", 0),
            })
    return aisles


def main():
    session = create_session()

    print("Fetching departments from /shell...")
    departments = get_departments(session)
    print(f"Found {len(departments)} departments\n")
    print(f"Department JSON format [1]: {departments[1]}")

    counter = 1 # Added a counter in - structure reflects in search demo
    for dept in departments:
        print(f"{'=' * 60}")
        print(f"  [{counter}] {dept['name']}  (/{dept['slug']}, {dept['productCount']} products)")
        print(f"{'=' * 60}")

        aisles = get_aisles(session, dept["slug"])
        if aisles:
            for aisle in aisles:
                print(f"  [{aisle['id']:>3}]  {aisle['name']:<40}  ({aisle['productCount']} products)")
        else:
            print("  (no aisles)")
        print()
        counter += 1


if __name__ == "__main__":
    main()
