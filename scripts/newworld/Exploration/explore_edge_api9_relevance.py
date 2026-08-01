"""
New World Edge API - Relevance Matching Exploration
====================================================

This script documents the complete exploration process to discover how to get
relevance-matched product search WITH per-store pricing on the New World Edge API.

DISCOVERY TIMELINE:
===================

PHASE 1: Initial Edge API Exploration (explore_edge_api.py - explore_edge_api4.py)
----------------------------------------------------------------------------------
- Tested endpoints: /v1/edge/store/physical, /v1/edge/ecomm-products/v1/edge/store/{id}/categories
- All worked with mobile API guest token (Authorization + access_token headers)
- PROBLEM: Product search endpoints ALL returned 404:
  - /v1/edge/products/search → 404
  - /v1/edge/ecomm-products/{banner}/{store_id}/search → 404
  - /v1/edge/search/products → 404
- CONCLUSION at this stage: Edge API has store listing but NO product search

PHASE 2: Website Network Capture Analysis (explore_edge_api5.py)
-----------------------------------------------------------------
- Fetched store-finder page, search page, homepage __NEXT_DATA__
- Checked API gateway on main domain (/api/mobile/*, /api/v1/*)
- Found website uses JWT auth via POST /api/user/get-current-user → fs-user-token cookie
- Still no product search endpoint visible in page props

PHASE 3: Breakthrough - Algolia Index Endpoints (products-index-popularity-asc.txt)
------------------------------------------------------------------------------------
- Captured network request from browser DevTools on www.newworld.co.nz search
- Found: POST /v1/edge/search/products/query/index/products-index-popularity-asc → 200 OK
- This revealed the pattern: /v1/edge/search/products/query/index/{index_name}
- Index names follow pattern: products-index-{sort_order}

PHASE 4: Testing Algolia Indices (explore_algolia_indices.py, explore_indices_detailed.py)
------------------------------------------------------------------------------------------
- Tested multiple index endpoints:
  - products-index-popularity-asc → 200 (returns hits, HAS _highlightResult, sorted by popularity ASC)
  - products-index-popularity-desc → 200 (returns hits, HAS _highlightResult, sorted by popularity DESC)
  - products-index → 200 (returns hits, HAS _highlightResult, sorted by relevance (Algolia default))
  - products-index-price-asc → 404
  - products-index-price-desc → 404
  - products-index-relevance → 404
  - products-index-name-asc → 404
  - products-index-name-desc → 404
  - products-index-newest → 404
  - products-index-bestselling → 404
  - products-index-trending → 404
  - products → 404
  - products-index → 200 (same as products-index)

KEY FINDING: Only THREE indices exist and return 200:
  1. products-index-popularity-asc (popularity ascending)
  2. products-index-popularity-desc (popularity descending)
  3. products-index (DEFAULT - relevance sorted)

ALL THREE indices return identical _highlightResult structures with matchedWords.
The only difference is the sort order of results. For relevance matching, any index
works — products-index (relevance sort) is preferred since top hits are most relevant.

PHASE 5: Per-Store Pricing Discovery (edge_full_test.py, edge_optimizer_demo.py)
---------------------------------------------------------------------------------
- Found separate endpoint: POST /v1/edge/search/paginated/products
- Requires website JWT (fs-user-token) + store context cookies
- Returns per-store pricing: singlePrice.price (cents) + promotions[].rewardValue
- Sort options: PRICE_ASC, PRICE_DESC (validated via enum)
- RELEVANCE sort NOT available on this endpoint (400 enum mismatch)

PHASE 6: The Two-Pass Solution (THIS SCRIPT)
---------------------------------------------
PASS 1: Query products-index (Algolia) for relevance matching
  - Returns hits with _highlightResult showing matched words
  - Extract productIDs from hits where _highlightResult has matches

PASS 2: Query /search/paginated/products with Algolia filter syntax
  - Filter: 'productID:xxx OR productID:yyy OR productID:zzz'
  - Returns per-store pricing for ONLY those relevant products
  - Sort by PRICE_ASC for cheapest at that store

DIFFERENCE FROM MOBILE API PIPELINE:
====================================
MOBILE API (Old):
  1. Guest login → api-prod.prod.fsniwaikato.kiwi/prod/mobile/user/login/guest (banner=MNW)
  2. Store search → /mobile/store/physical (returns 149 stores with coords)
  3. Product search → /mobile/ecomm-products/MNW/{store_id}/search?q=milk
  4. Returns per-store pricing directly in response
  5. Depends on Foodstuffs mobile API (internal, unstable)

EDGE API (New - Two Pass):
  1. Website session → GET www.newworld.co.nz → POST /api/user/get-current-user → fs-user-token cookie
  2. Store listing → GET /v1/edge/store (148 stores) OR reuse mobile API store list
  3. PASS 1 Relevance → POST /v1/edge/search/products/query/index/products-index?q=milk
     → Returns productIDs with _highlightResult relevance matches
  4. PASS 2 Pricing → POST /v1/edge/search/paginated/products with filters
     → Returns per-store singlePrice + promotions for matched products only
  5. Uses public website JWT (more stable, same IdP as mobile)
  6. No dependency on Foodstuffs mobile API endpoint

"""

import requests
import json
import time

# ============================================================================
# CONFIGURATION
# ============================================================================

WEB_BASE = "https://www.newworld.co.nz"
EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"

# New World Metro Auckland store (used for all tests)
STORE_ID = "60928d93-06fa-4d8f-92a6-8c359e7e846d"

# ============================================================================
# SESSION HELPERS
# ============================================================================

def get_website_session():
    """
    Establish website session and get JWT token.
    
    DISCOVERY: The website uses a simple JWT flow:
    1. GET https://www.newworld.co.nz (establishes cookies, CSRF)
    2. POST https://www.newworld.co.nz/api/user/get-current-user (empty JSON)
    3. Response sets 'fs-user-token' cookie with JWT
    
    This JWT works for BOTH:
    - Algolia index endpoints (/search/products/query/index/*)
    - Paginated search endpoint (/search/paginated/products)
    
    The mobile API token ALSO works for both endpoints (shared IdP: online-customer).
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    # Step 1: Establish base cookies
    session.get(WEB_BASE, timeout=30)
    # Step 2: Get JWT (anonymous user)
    session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    token = session.cookies.get("fs-user-token")
    return session, token


def get_store_context_cookies(store_id):
    """Store context cookies required for per-store pricing."""
    return {
        "eCom_STORE_ID": store_id,
        "STORE_ID_V2": f"{store_id}|False",
        "Region": "NI",
    }


def get_auth_headers(token):
    """Auth headers for Edge API (Bearer + access_token)."""
    return {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }


# ============================================================================
# PASS 1: ALGOLIA INDEX SEARCH (RELEVANCE MATCHING)
# ============================================================================

def algolia_relevance_search(token, query, store_id, hits_per_page=20):
    """
    Search the DEFAULT Algolia index (products-index) for relevance matches.
    
    WHY products-index?
    - Tested 14+ index names, only 3 returned 200
    - All 3 indices (products-index, popularity-asc, popularity-desc) return
      identical _highlightResult structures with matchedWords
    - products-index is preferred because it sorts by Algolia relevance (default),
      so top hits are most likely to match the query
    
    The _highlightResult field is the KEY to relevance matching:
    - Contains matchedWords array showing which query terms matched which fields
    - Fields with matches: DisplayName, category1, category2, category2AndBrand, etc.
    - Products WITHOUT matches have empty matchedWords arrays
    
    Returns: List of (productID, DisplayName, brand, averagePrice, highlight_matches)
    """
    url = f"{EDGE_BASE}/search/products/query/index/products-index"
    headers = get_auth_headers(token)
    cookies = get_store_context_cookies(store_id)
    
    payload = {
        "algoliaQuery": {"query": query},
        "page": 0,
        "hitsPerPage": hits_per_page,
        "storeId": store_id,
    }
    
    r = requests.post(url, headers=headers, json=payload, cookies=cookies, timeout=30)
    r.raise_for_status()
    data = r.json()
    
    hits = data.get("hits", [])
    results = []
    
    for hit in hits:
        product_id = hit.get("productID")
        display_name = hit.get("DisplayName")
        brand = hit.get("brand")
        avg_price = hit.get("averagePrice")
        
        # Check _highlightResult for relevance matches
        highlight_result = hit.get("_highlightResult", {})
        matched_fields = []
        for field, info in highlight_result.items():
            if isinstance(info, dict) and info.get("matchedWords"):
                matched_fields.append({
                    "field": field,
                    "matched_words": info["matchedWords"],
                    "value": info.get("value", "")[:100]
                })
        
        results.append({
            "product_id": product_id,
            "display_name": display_name,
            "brand": brand,
            "average_price": avg_price,
            "category1": hit.get("category1", []),
            "category2": hit.get("category2", []),
            "matched_fields": matched_fields,
            "has_relevance_match": len(matched_fields) > 0,
            "raw_hit": hit  # Keep for debugging
        })
    
    return results


def algolia_popularity_search(token, query, store_id, hits_per_page=20, asc=True):
    """
    Search popularity-sorted index for comparison.
    
    NOTE: These indices DO have _highlightResult (identical to products-index).
    The only difference from products-index is the sort order (popularity vs relevance).
    They only have averagePrice across all stores, not per-store pricing.
    """
    suffix = "asc" if asc else "desc"
    index_name = f"products-index-popularity-{suffix}"
    url = f"{EDGE_BASE}/search/products/query/index/{index_name}"
    headers = get_auth_headers(token)
    cookies = get_store_context_cookies(store_id)
    
    payload = {
        "algoliaQuery": {"query": query},
        "page": 0,
        "hitsPerPage": hits_per_page,
        "storeId": store_id,
    }
    
    r = requests.post(url, headers=headers, json=payload, cookies=cookies, timeout=30)
    r.raise_for_status()
    data = r.json()
    
    hits = data.get("hits", [])
    results = []
    
    for hit in hits:
        # Check if _highlightResult exists (all 3 indices have it)
        has_highlight = "_highlightResult" in hit and hit["_highlightResult"]
        
        results.append({
            "product_id": hit.get("productID"),
            "display_name": hit.get("DisplayName"),
            "brand": hit.get("brand"),
            "average_price": hit.get("averagePrice"),
            "popularity": hit.get("popularity"),
            "has_highlight_result": has_highlight,
        })
    
    return results


# ============================================================================
# PASS 2: PAGINATED SEARCH (PER-STORE PRICING)
# ============================================================================

def paginated_store_pricing(token, query, store_id, product_ids, sort_order="PRICE_ASC", hits_per_page=50):
    """
    Get per-store pricing for SPECIFIC product IDs using Algolia filter syntax.
    
    KEY DISCOVERY: The paginated endpoint accepts Algolia 'filters' parameter!
    Filter syntax: 'productID:xxx OR productID:yyy OR productID:zzz'
    
    This is the BRIDGE between relevance matching (Pass 1) and per-store pricing (Pass 2).
    
    Returns per-store pricing:
    - singlePrice.price (cents) - regular price at THIS store
    - promotions[].rewardValue (cents) - promo discount at THIS store
    - singlePrice.comparativePrice - unit price (e.g., $/kg)
    
    Sort options (validated enum): PRICE_ASC, PRICE_DESC
    RELEVANCE sort NOT available (returns 400 enum mismatch)
    """
    url = f"{EDGE_BASE}/search/paginated/products"
    headers = get_auth_headers(token)
    cookies = get_store_context_cookies(store_id)
    
    # Build OR filter for all product IDs from Pass 1
    filter_str = " OR ".join([f"productID:{pid}" for pid in product_ids])
    
    payload = {
        "algoliaQuery": {
            "query": query,
            "filters": filter_str
        },
        "page": 0,
        "hitsPerPage": hits_per_page,
        "storeId": store_id,
        "sortOrder": sort_order,
    }
    
    r = requests.post(url, headers=headers, json=payload, cookies=cookies, timeout=30)
    r.raise_for_status()
    data = r.json()
    
    products = data.get("products", [])
    results = []
    
    for p in products:
        pid = p.get("productId")
        name = p.get("name")
        display_name = p.get("displayName")
        single_price = p.get("singlePrice", {})
        price_cents = single_price.get("price")
        comparative = single_price.get("comparativePrice", {})
        promotions = p.get("promotions", [])
        promo_cents = promotions[0].get("rewardValue") if promotions else None
        
        results.append({
            "product_id": pid,
            "name": name,
            "display_name": display_name,
            "price_cents": price_cents,
            "price_dollars": price_cents / 100 if price_cents else None,
            "promo_cents": promo_cents,
            "promo_dollars": promo_cents / 100 if promo_cents else None,
            "unit_price": comparative.get("pricePerUnit"),
            "unit_uom": comparative.get("unitQuantityUom"),
            "sort_position": p.get("algoliaAnalytics", {}).get("searchPosition"),
        })
    
    return results


# ============================================================================
# COMPLETE TWO-PASS PIPELINE
# ============================================================================

def two_pass_search(token, query, store_id, max_relevance_results=10, sort_order="PRICE_ASC"):
    """
    Complete two-pass pipeline: Relevance → Per-Store Pricing
    
    PASS 1: Algolia relevance search (products-index)
    - Get top N products with relevance matches (_highlightResult)
    - Filter to only those with matchedWords
    
    PASS 2: Paginated per-store pricing
    - Query with productID filter for matched products
    - Sort by price at this store
    
    Returns: List of products with BOTH relevance info AND per-store pricing
    """
    print(f"\n{'='*70}")
    print(f"TWO-PASS SEARCH: '{query}' at store {store_id}")
    print(f"{'='*70}")
    
    # PASS 1
    print(f"\n[PASS 1] Algolia Relevance Search (products-index)")
    print(f"  Query: '{query}', Max results: {max_relevance_results}")
    
    relevance_results = algolia_relevance_search(token, query, store_id, max_relevance_results)
    
    # Filter to only products with relevance matches
    matched_products = [r for r in relevance_results if r["has_relevance_match"]]
    product_ids = [r["product_id"] for r in matched_products]
    
    print(f"  Total hits: {len(relevance_results)}")
    print(f"  With relevance matches: {len(matched_products)}")
    print(f"  Product IDs for Pass 2: {product_ids[:5]}{'...' if len(product_ids) > 5 else ''}")
    
    # Show relevance matches
    for r in matched_products[:3]:
        fields = [f"{m['field']}:{m['matched_words']}" for m in r["matched_fields"]]
        print(f"    OK {r['product_id']} - {r['display_name']} ({r['brand']}) - Matches: {', '.join(fields)}")
    
    if not product_ids:
        print("  No relevance matches found!")
        return []
    
    # PASS 2
    print(f"\n[PASS 2] Per-Store Pricing (paginated endpoint, sort={sort_order})")
    print(f"  Filter: {len(product_ids)} product IDs")
    
    pricing_results = paginated_store_pricing(token, query, store_id, product_ids, sort_order)
    
    print(f"  Pricing results: {len(pricing_results)}")
    
    # Merge relevance info with pricing
    relevance_map = {r["product_id"]: r for r in matched_products}
    merged = []
    
    for p in pricing_results:
        pid = p["product_id"]
        rel = relevance_map.get(pid, {})
        merged.append({
            **p,
            "relevance_display_name": rel.get("display_name"),
            "relevance_brand": rel.get("brand"),
            "relevance_category1": rel.get("category1"),
            "relevance_category2": rel.get("category2"),
            "relevance_matches": rel.get("matched_fields"),
            "relevance_avg_price": rel.get("average_price"),
        })
    
    # Sort by price (cheapest first)
    merged.sort(key=lambda x: x["price_dollars"] or 999999)
    
    return merged


# ============================================================================
# COMPARISON: MOBILE API vs EDGE API
# ============================================================================

def print_pipeline_comparison():
    print("\n" + "="*70)
    print("PIPELINE COMPARISON: MOBILE API vs EDGE API (Two-Pass)")
    print("="*70)
    
    print("""
MOBILE API PIPELINE (Original - Deprecated):
--------------------------------------------
1. POST https://api-prod.prod.fsniwaikato.kiwi/prod/mobile/user/login/guest
   Body: {"banner": "MNW"}
   Headers: User-Agent: NewWorldApp/4.32.0
   -> Returns: access_token (guest, expires ~30 min)

2. GET /mobile/store/physical (with auth headers)
   -> Returns: 149 stores with coordinates, store_ids

3. GET /mobile/ecomm-products/MNW/{store_id}/search?q=milk
   -> Returns: Products with per-store pricing directly
   -> Price in cents, divide by 100

PROBLEMS:
- Internal Foodstuffs mobile API (not public, unstable)
- No relevance sorting (returns first/most-relevant but no _highlightResult)
- Token expires, needs refresh logic
- Different domain, different auth flow

================================================================================

EDGE API TWO-PASS PIPELINE (New - Production Ready):
----------------------------------------------------
1. GET https://www.newworld.co.nz (establish session)
2. POST https://www.newworld.co.nz/api/user/get-current-user (empty JSON)
   -> Returns: fs-user-token cookie (JWT, same IdP: online-customer)

3. GET /v1/edge/store (with JWT) OR reuse mobile API store list
   -> Returns: 148 stores (missing Foodie Mart vs mobile's 149)

4. PASS 1 - RELEVANCE: POST /v1/edge/search/products/query/index/products-index
   Body: {"algoliaQuery": {"query": "milk"}, "page": 0, "hitsPerPage": 20, "storeId": "..."}
   Headers: Authorization: Bearer {jwt}, access_token: {jwt}, Origin: https://www.newworld.co.nz
   Cookies: eCom_STORE_ID, STORE_ID_V2, Region
   -> Returns: hits WITH _highlightResult showing matchedWords
   -> Extract productIDs where matchedWords not empty

5. PASS 2 - PRICING: POST /v1/edge/search/paginated/products
   Body: {
     "algoliaQuery": {"query": "milk", "filters": "productID:xxx OR productID:yyy"},
     "page": 0, "hitsPerPage": 50, "storeId": "...", "sortOrder": "PRICE_ASC"
   }
   Same headers + cookies
   -> Returns: per-store singlePrice.price (cents) + promotions[].rewardValue
   -> Sort: PRICE_ASC or PRICE_DESC (validated)

ADVANTAGES:
- Uses public website JWT (more stable, same identity provider)
- NO dependency on Foodstuffs mobile API endpoint
- Explicit relevance matching via _highlightResult
- Per-store pricing with promotional prices
- Standard REST + Algolia patterns
- Works with website session (no app User-Agent needed)
""")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    print("="*70)
    print("NEW WORLD EDGE API - RELEVANCE MATCHING EXPLORATION")
    print("="*70)
    
    # Get website session + JWT
    print("\n[SETUP] Establishing website session and getting JWT...")
    session, token = get_website_session()
    print(f"  JWT token: {token[:50]}..." if token else "  FAILED - no token")
    
    if not token:
        print("ERROR: Could not get JWT token")
        return
    
    # Print comparison
    print_pipeline_comparison()
    
    # Test queries
    test_queries = ["milk", "beef mince", "bread", "cheese"]
    
    for query in test_queries:
        results = two_pass_search(token, query, STORE_ID, max_relevance_results=15)
        
        print(f"\n  RESULTS for '{query}' (sorted by price at Metro Auckland):")
        print(f"  {'#':>2} {'Product':<35} {'Size':<10} {'Price':>8} {'Promo':>8} {'Relevance Match'}")
        print(f"  {'-'*80}")
        
        for i, r in enumerate(results[:10]):
            name = (r.get("name") or "")[:34]
            size = (r.get("display_name") or "")[:9]
            price = f"${r['price_dollars']:.2f}" if r.get("price_dollars") else "N/A"
            promo = f"${r['promo_dollars']:.2f}" if r.get("promo_dollars") else "—"
            
            # Show top relevance match
            rel_match = "—"
            if r.get("relevance_matches"):
                top_match = r["relevance_matches"][0]
                rel_match = f"{top_match['field']}:{top_match['matched_words']}"
            
            print(f"  {i+1:>2} {name:<35} {size:<10} {price:>8} {promo:>8} {rel_match}")
        
        # Small delay between queries
        time.sleep(0.5)
    
    # Demonstrate the difference: popularity vs relevance
    print("\n" + "="*70)
    print("COMPARISON: Popularity Index vs Relevance Index (for 'milk')")
    print("="*70)
    
    print("\n[Popularity ASC - products-index-popularity-asc]")
    pop_asc = algolia_popularity_search(token, "milk", STORE_ID, hits_per_page=5, asc=True)
    for i, r in enumerate(pop_asc):
        hl = "OK Has _highlightResult" if r["has_highlight_result"] else "NO _highlightResult"
        print(f"  {i+1}. {r['product_id']} - {r['display_name']} ({r['brand']}) - "
              f"Avg: ${r['average_price']} - Pop: {r['popularity']} - {hl}")
    
    print("\n[Popularity DESC - products-index-popularity-desc]")
    pop_desc = algolia_popularity_search(token, "milk", STORE_ID, hits_per_page=5, asc=False)
    for i, r in enumerate(pop_desc):
        hl = "OK Has _highlightResult" if r["has_highlight_result"] else "NO _highlightResult"
        print(f"  {i+1}. {r['product_id']} - {r['display_name']} ({r['brand']}) - "
              f"Avg: ${r['average_price']} - Pop: {r['popularity']} - {hl}")
    
    print("\n[Relevance - products-index (DEFAULT)]")
    rel = algolia_relevance_search(token, "milk", STORE_ID, hits_per_page=5)
    for i, r in enumerate(rel):
        match_info = "NO MATCH"
        if r["has_relevance_match"]:
            fields = [f"{m['field']}" for m in r["matched_fields"]]
            match_info = f"MATCHES: {', '.join(fields)}"
        print(f"  {i+1}. {r['product_id']} - {r['display_name']} ({r['brand']}) - "
              f"Avg: ${r['average_price']} - {match_info}")
    
    print("\n" + "="*70)
    print("KEY INSIGHT: All 3 indices have identical _highlightResult with matchedWords!")
    print("The only difference is sort order. 'products-index' (relevance) is preferred")
    print("for the two-pass pipeline since top hits match the query best.")
    print("="*70)


if __name__ == "__main__":
    main()