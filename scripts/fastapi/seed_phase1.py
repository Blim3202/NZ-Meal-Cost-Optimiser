import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services.supabase_client import get_supabase


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def create_schema(supabase):
    """Check if stores table exists. If not, print SQL for manual execution."""
    try:
        from postgrest.exceptions import APIError
        r = supabase.from_("stores").select("store_id").limit(0).execute()
        print(f"stores table ready (accessible).")
    except APIError as e:
        if "PGRST125" in str(e) or "PGRST205" in str(e) or "Invalid path" in str(e):
            print("=== stores table does not exist ===")
            print("Run the following SQL in your Supabase project SQL Editor:")
            print("--- COPY FROM HERE ---")
            with open(Path(__file__).parent / "schema_phase1.sql", encoding="utf-8") as f:
                print(f.read())
            print("--- COPY TO HERE ---")
            sys.exit(1)
        else:
            raise
    except Exception:
        print("=== stores table does not exist ===")
        print("Run the following SQL in your Supabase project SQL Editor:")
        print("--- COPY FROM HERE ---")
        with open(Path(__file__).parent / "schema_phase1.sql", encoding="utf-8") as f:
            print(f.read())
        print("--- COPY TO HERE ---")
        sys.exit(1)


def seed_stores(supabase):
    """Migrate store CSVs into 'nzdio.stores' table."""
    rows = []

    # --- New World ---
    nw_csv = DATA_DIR / "newworld_stores.csv"
    if nw_csv.exists():
        with open(nw_csv, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append({
                    "store_id": r["store_id"],
                    "brand": "NewWorld",
                    "name": r["name"],
                    "address": r["address"],
                    "city": r.get("city", ""),
                    "region": r.get("region", ""),
                    "lat": float(r["latitude"]) if r.get("latitude") else None,
                    "lon": float(r["longitude"]) if r.get("longitude") else None,
                    "banner": r.get("banner", "MNW"),
                    "click_and_collect": r["click_and_collect"] == "True",
                    "delivery": r["delivery"] == "True",
                })

    # --- Pak'nSave ---
    ps_csv = DATA_DIR / "paknsave_stores.csv"
    if ps_csv.exists():
        with open(ps_csv, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append({
                    "store_id": r["store_id"],
                    "brand": "PaknSave",
                    "name": r["name"],
                    "address": r["address"],
                    "city": r.get("city", ""),
                    "region": r.get("region", ""),
                    "lat": float(r["latitude"]) if r.get("latitude") else None,
                    "lon": float(r["longitude"]) if r.get("longitude") else None,
                    "banner": r.get("banner", "PNS"),
                    "click_and_collect": r["click_and_collect"] == "True",
                    "delivery": r["delivery"] == "True",
                })

     # --- Woolworths (JSON with extra1 as store_id) ---
    ww_json = DATA_DIR / "woolworths_store_data.json"
    if ww_json.exists():
        with open(ww_json, encoding="utf-8") as f:
            data = json.load(f)
        sites = data.get("siteDetail", [])
        for s in sites:
            site = s.get("site", {})
            extra1 = str(site.get("extra1", ""))
            extra2 = site.get("extra2")
            rows.append({
                "store_id": extra1,            # canonical: fulfilmentStoreId (extra1)
                "pickup_address_id": str(extra2) if extra2 is not None and str(extra2) != "null" else None,
                "brand": "Woolworths",
                "name": site.get("name", ""),
                "address": site.get("addressLine1", ""),
                "city": site.get("suburb", ""),
                "region": site.get("state", ""),
                "lat": float(site["latitude"]) if site.get("latitude") else None,
                "lon": float(site["longitude"]) if site.get("longitude") else None,
                "banner": None,
                "click_and_collect": None,
                "delivery": None,
            })

    if rows:
        # Deduplicate by store_id (keep first occurrence)
        seen = {}
        unique_rows = []
        for r in rows:
            sid = r["store_id"]
            name = r["name"]
            if sid not in seen:
                seen[sid] = True
                unique_rows.append(r)
            else:
                print(f"Duplicate store_id found and skipped: {sid} - ({name})")
        deduped = len(rows) - len(unique_rows)
        if deduped:
            print(f"Removed {deduped} duplicate store entries.")
        resp = supabase.from_("stores").upsert(unique_rows).execute()
        print(f"Seeded {len(unique_rows)} stores (upserted).")
    else:
        print("No store files found.")


def seed_dishes(supabase):
    """Migrate dishes.json into 'dishes' table."""
    dishes_json = DATA_DIR / "dishes.json"
    if not dishes_json.exists():
        print("dishes.json not found.")
        return

    with open(dishes_json, encoding="utf-8") as f:
        dishes = json.load(f)

    rows = []
    for key, val in dishes.items():
        rows.append({
            "dish_name": val["dish_name"],
            "portion": int(val.get("portion", 4)),
            "ingredients": json.dumps(val["ingredients"]),
            "added_at": None,  # let DB default
        })
    # Use upsert to avoid duplicates on re-run
    resp = supabase.from_("dishes").upsert(rows).execute()
    print(f"Seeded {len(rows)} dishes.")


if __name__ == "__main__":
    supabase = get_supabase()
    print("=== Phase 1: Supabase Seed ===")
    create_schema(supabase)
    seed_stores(supabase)
    seed_dishes(supabase)
    print("Done.")
