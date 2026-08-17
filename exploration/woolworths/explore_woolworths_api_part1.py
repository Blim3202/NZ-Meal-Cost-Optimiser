import requests, sys, time, re

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://www.woolworths.co.nz"
API  = f"{BASE}/api/v1"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-NZ,en;q=0.9",
    "x-requested-with": "XMLHttpRequest", # Standard placeholder, any non-blank string seems to work
})
session.get(BASE, timeout=10)


# ---------------------------------------------------------------------------
# 1) Full catalogue via target=browse (no filter) — verify sort + price range
# ---------------------------------------------------------------------------
print("=" * 70)
print("1) target=browse — ascending price sort, max size")
print("=" * 70)

for sort in [None, "PriceAsc", "PriceDesc", "CUPAsc"]:
    params = {"target": "browse", "size": 3}
    if sort:
        params["sort"] = sort
    r = session.get(f"{API}/products", params=params, timeout=10)
    data = r.json()
    items = data.get("products", {}).get("items", [])
    total = data.get("products", {}).get("totalItems")
    label = sort or "relevance"
    print(f"\n  sort={label}  HTTP {r.status_code}  items={len(items)}  total={total}")
    for p in items:
        pr = p.get("price", {})
        print(f"    sku={p.get('sku')}  {p.get('name','')[:50]}  "
              f"sale=${pr.get('salePrice')}  orig=${pr.get('originalPrice')}  "
              f"cup=${pr.get('purchasingUnitPrice','')}  club={pr.get('isClubPrice')}")

# ---------------------------------------------------------------------------
# 2) DasFilter decoding — what does the semicolon format actually control?
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("2) dasFilter — decoding the semicolon format")
print("=" * 70)

# From shell: Meat&Poultry dept key=Department value=2, Beef aisle key=Aisle value=88
# GitHub format: "Department;;meat-poultry;false"
# Let's test with full path from shell's navigation items
# shelfResponses[0] in Meat is Steak (id=541), let's try by shelf id directly

facet_chain_tests = [
    ("Department;;meat-poultry;false",                                         "dept slug only"),
    ("Department;;meat-poultry;false;Aisle;;88;false",                         "dept + Beef aisle numeric"),
    ("Department;;meat-poultry;false;Aisle;;Beef;false",                       "dept + Beef aisle named"),
    ("Department;;meat-poultry;false;Aisle;;88;false;Shelf;;541;false",       "dept + aisle + shelf id"),
    ("2;;1;false",                                                              "raw: only dept numeric"),
    ("2;;1;false;2;;88;false",                                                  "raw: dept+aisle numeric chain"),
    ("Department;;meat-poultry;false;88;;Beef;false",                          "mixed key:value recode"),
]

for df, label in facet_chain_tests:
    r = session.get(f"{API}/products",
                    params={"target": "browse", "dasFilter": df, "size": 3}, timeout=10)
    data = r.json()
    items = data.get("products", {}).get("items", [])
    total = data.get("products", {}).get("totalItems")
    facets = data.get("dasFacets", [])
    print(f"\n  [{label}]  {df}")
    print(f"    HTTP {r.status_code}  total={total}  items={len(items)}")
    print(f"    facets returned: {[{'k':f.get('key'),'v':f.get('value'),'n':f.get('name'),'c':f.get('productCount')} for f in facets[:5]]}")
    for p in items[:1]:
        pr = p.get("price", {})
        print(f"    -> {p.get('name','')[:55]}  sku={p.get('sku')}  ${pr.get('salePrice')}")
    time.sleep(0.3)

# ---------------------------------------------------------------------------
# 3) shell context.fulfilment — default store + all keys
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("3) shell context.fulfilment — store identity")
print("=" * 70)
r = session.get(f"{API}/shell", timeout=10)
data = r.json()
fulf = data.get("context", {}).get("fulfilment", {})
print(f"  fulfilmentStoreId:    {fulf.get('fulfilmentStoreId')}")
print(f"  pickupAddressId:      {fulf.get('pickupAddressId')}")
print(f"  areaId:               {fulf.get('areaId')}")
print(f"  suburbId:             {fulf.get('suburbId')}")
print(f"  method:               {fulf.get('method')}")          # Courier | Pickup
print(f"  address:              {fulf.get('address')}")
print(f"  isDefaultDeliveryAddress: {fulf.get('isDefaultDeliveryAddress')}")
print(f"  isAddressInDeliveryZone:  {fulf.get('isAddressInDeliveryZone')}")

# ---------------------------------------------------------------------------
# 4) pickup-addresses — full store structure, look for ANY bridge keys
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("4) pickup-addresses — full store record structure (first 5 stores)")
print("=" * 70)
r = session.get(f"{API}/addresses/pickup-addresses", timeout=10)
areas = r.json().get("storeAreas", [])
seen = 0
for area in areas:
    for s in area.get("storeAddresses", []):
        if seen >= 5:
            break
        print(f"\n  id={s.get('id')}  name={s.get('name','')[:45]}")
        print(f"  address={s.get('address','')[:80]}")
        print(f"  ALL KEYS: {list(s.keys())}")
        extra = {k: v for k, v in s.items() if k not in ("id", "name", "address")}
        if extra:
            for k, v in extra.items():
                print(f"  {k}: {repr(v)[:200]}")
        else:
            print("  (no extra keys)")
        seen += 1

# Also list the first 20 IDs to see if 9171 appears
all_ids = []
for area in areas:
    for s in area.get("storeAddresses", []):
        all_ids.append(s["id"])
print(f"\n  First 20 store IDs in pickup-addresses: {all_ids[:20]}")
print(f"  fulfilmentStoreId 9171 in pickup list: {9171 in all_ids}")

# ---------------------------------------------------------------------------
# 5) Price comparison across fulfilmentStoreId values — does store param change price?
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("5) Price comparison — fulfilmentStoreId param effect")
print("=" * 70)

r_base = session.get(f"{API}/products",
                     params={"target": "search", "search": "milk", "size": 10}, timeout=10)
base_items = r_base.json().get("products", {}).get("items", [])
base_map = {}
for p in base_items:
    sku = p.get("sku")
    if sku:
        base_map[sku] = {
            "salePrice": p.get("price", {}).get("salePrice"),
            "name": p.get("name", ""),
        }

print(f"  baseline items with sku: {len(base_map)}")
for sku, info in list(base_map.items())[:3]:
    print(f"    sku={sku}  {info['name']}  ${info['salePrice']}")

# Pick two distinct known store IDs for comparison
store_a = 9171                          # default delivery
store_b = all_ids[0] if all_ids else 1225718  # first pickup store

for label, sid in [("base (no param)", None), ("fulfilmentStoreId=9171", store_a), ("fulfilmentStoreId="+str(store_b), store_b)]:
    params = {"target": "search", "search": "milk", "size": 10}
    if sid:
        params["fulfilmentStoreId"] = sid
    r = session.get(f"{API}/products", params=params, timeout=10)
    items = r.json().get("products", {}).get("items", [])
    changed = []
    for p in items:
        sku = p.get("sku")
        if sku not in base_map:
            continue
        new_price = p.get("price", {}).get("salePrice")
        old_price = base_map[sku]["salePrice"]
        if new_price != old_price:
            changed.append(f"    sku={sku}  {base_map[sku]['name'][:40]}  ${old_price} -> ${new_price}")
    print(f"\n  {label}:")
    if changed:
        print("  PRICE CHANGES:")
        for c in changed:
            print(c)
    else:
        print("  (no changes — prices are identical to baseline)")
    time.sleep(0.3)

# ---------------------------------------------------------------------------
# 6) POST endpoints — try to set / change store id
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("6) POST attempts — inject fulfilment store context")
print("=" * 70)

post_eps = [
    "addresses/set-store",
    "addresses/change-store",
    "addresses/set-pickup-store",
    "addresses/selected-store",
    "store/context",
    "store/current",
    "store/set",
    "fulfilment/store",
    "fulfilment/selected-store",
]
for ep in post_eps:
    url = f"{API}/{ep}"
    for payload in [
        {"fulfilmentStoreId": store_b},
        {"pickupAddressId":   store_b},
        {"storeId":           store_b},
    ]:
        try:
            r = session.post(url, json=payload, timeout=10)
            print(f"[POST {ep}] payload={payload}  {r.status_code}  {len(r.content)}B  "
                  f"{r.text[:120].replace(chr(10),' ')}")
        except Exception as e:
            print(f"[POST {ep}] EXCEPTION: {e}")
        time.sleep(0.15)

# ---------------------------------------------------------------------------
# 7) Are fulfilmentStoreId values visible anywhere else in the shell response?
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("7) Full shell response — search for all numeric store-like IDs")
print("=" * 70)
r = session.get(f"{API}/shell", timeout=10)
text = r.text

unique_ids = sorted(set(int(x) for x in all_ids))
print(f"  Unique numeric IDs in shell response ({len(unique_ids)}):")
for uid in unique_ids[:30]:
    # find surrounding context
    idx = text.find(f'"id":{uid}')
    ctx = text[max(0,idx-40):idx+60].replace('\n',' ')
    print(f"  id={uid}  context: ...{ctx}...")

print("\nDone.")
