"""Phase 2: queued optimizer worker.

Consumes `Job` objects from a `JobQueue` on a single background daemon thread
and runs the existing per-brand optimizer pipelines *unmodified*:

* Foodstuffs (Pak'nSave / New World) -> `optimizer_utils.foodstuffs_optimizer_edge`
  (or `_mobile`) — reuses the full two-pass Edge pipeline.
* Woolworths -> `optimizer_utils.woolworths_optimizer` — reuses the per-store
  `create_session()`/`set_store_context()`/`search_products()` flow.

Write isolation: a per-job `append_rows` seam is swapped onto the
`ResultWriter` (in the `optimizer_utils` namespace)
and restored in `finally`, so the worker never edits source files and the
existing CLI/notebook scripts keep writing to CSV untouched.

Concurrency safety (all satisfied by the SINGLE worker thread):
* Fresh API client/session per job and (for Woolworths) per store.
* Nominatim geocode() sleeps 1.1s — serialised automatically.
* LLM rate limits — serialised automatically (LLM jobs reuse this queue).
"""
from __future__ import annotations

import logging
import threading
import traceback
from datetime import date, datetime
from typing import Optional

import pandas as pd

import core.paths  # noqa: F401  (bootstrap sys.path)
import optimizer_utils
import woolworths_api
from core.config import settings
from optimizer_utils import (
    CSV_COLUMNS,
    _compute_pk_hash,
    _resolve_dish,
    analyze_results,
    foodstuffs_optimizer_edge,
    foodstuffs_optimizer_mobile,
    woolworths_optimizer,
)
from paknsave_api import PaknSaveEdgeAPI, find_nearby_stores as ps_find_nearby
from newworld_api import NewWorldEdgeAPI, find_nearby_stores as nw_find_nearby
from services.supabase_client import get_supabase
from workers.store_registry import StoreRegistry
from workers.job_queue import JobQueue, JobStore, JobStatus
from workers.result_writer import LocalTempResultWriter, create_writer

log = logging.getLogger("fastapi.worker")

# Per-brand dispatch config. Edge is the canonical Foodstuffs backend (two-pass);
# mobile is retained as a selectable backend (single-pass fallback).
BRANDS = {
    "PaknSave": {
        "target": "foodstuffs",
        "backend": "edge",
        "api_class": PaknSaveEdgeAPI,
        "find_nearby": ps_find_nearby,
        "company_id": "PaknSave",
        "company_name": "Pak'nSave",
    },
    "NewWorld": {
        "target": "foodstuffs",
        "backend": "edge",
        "api_class": NewWorldEdgeAPI,
        "find_nearby": nw_find_nearby,
        "company_id": "NewWorld",
        "company_name": "New World",
    },
    "Woolworths": {
        "target": "woolworths",
        "company_id": "Woolworths",
        "company_name": "Woolworths",
    },
}


class OptimizerWorker:
    """Drains a `JobQueue` on a single daemon thread and runs optimizer jobs.

    Single-consumer by design: this is what makes the concurrency hazards
    (cookie isolation, geocode rate-limit, LLM rate-limit) safe without any
    extra locking.
    """

    def __init__(self, job_queue: JobQueue, store_registry: StoreRegistry, supabase=None) -> None:
        self.queue = job_queue
        self.store_registry = store_registry
        self.supabase = supabase
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, name="optimizer-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self.queue.shutdown()
        if self._thread:
            self._thread.join(timeout=timeout)

    def run(self) -> None:
        log.info("OptimizerWorker started (queue draining).")
        while not self._stop.is_set():
            try:
                job = self.queue.dequeue(timeout=1.0)
            except Exception:
                continue
            if job is None:
                break  # shutdown sentinel
            try:
                result = self.process_job(job)
                log.info("Job %s done; rows=%s cheapest=%s",
                         job.job_id, result.get("rows"), result.get("cheapest_store"))
            except Exception as e:
                log.error("Unhandled worker error on job %s: %s", getattr(job, "job_id", "?"), e)

    # ------------------------------------------------------------------ #
    # public, testable unit of work (no threading)
    # ------------------------------------------------------------------ #
    def process_job(self, job) -> dict:
        """Run one job end-to-end: query (Phase 1) -> optimize (Phase 2).

        Owns the job-status lifecycle (queued->running->done/failed) so it is
        testable in isolation; the daemon `run()` loop simply calls it.
        """
        params = job.params or {}
        brand = params.get("brand")
        if brand not in BRANDS:
            raise ValueError(f"Unsupported brand: {brand!r}. Choose from {list(BRANDS)}")
        dish = params.get("dish")
        dish_name, ingredients = _resolve_dish(dish)
        dry_run = bool(params.get("dry_run"))

        self.queue.store.set_status(job.job_id, JobStatus.RUNNING)
        writer = create_writer(self.supabase, self.store_registry, session_id=job.job_id)
        try:
            written, skipped = self._run_query(job, writer, dish, dry_run)
            self.queue.store.set_status(
                job.job_id, JobStatus.RUNNING,
                result_ref=f"wrote {written} rows ({skipped} dup skipped) via {writer.kind}",
            )
            summary = self._phase2_optimize(writer, dish, dish_name, ingredients, brand)
            self.queue.store.set_status(
                job.job_id, JobStatus.DONE,
                result_ref=_safe_json(summary),
            )
            return summary
        except Exception:
            self.queue.store.set_status(
                job.job_id, JobStatus.FAILED,
                error_message=traceback.format_exc(limit=3),
            )
            raise
        finally:
            if isinstance(writer, LocalTempResultWriter):
                writer.cleanup()

    # ------------------------------------------------------------------ #
    # Phase 1: query the retailer API (reuses existing pipelines)
    # ------------------------------------------------------------------ #
    def _run_query(self, job, writer, dish, dry_run) -> tuple[int, int]:
        if dry_run:
            rows = self._synthetic_rows(job)
            return writer.write_rows(rows)

        params = job.params
        address = params.get("address", "")
        distance = float(params.get("distance_km", 5.0))
        brand = params["brand"]
        cfg = BRANDS[brand]

        # --- per-job append_rows seam (restored in finally) ---
        orig_ou = optimizer_utils.append_rows

        def _patched(rows, results_file=None):
            return writer.write_rows(rows)

        optimizer_utils.append_rows = _patched
        try:
            if cfg["target"] == "woolworths":
                ok = woolworths_optimizer(
                    woolworths_api,
                    cfg["company_id"], cfg["company_name"],
                    address, dish, True, max_dist_km=distance,
                )
            else:
                backend = cfg.get("backend", "edge")
                fn = foodstuffs_optimizer_mobile if backend == "mobile" else foodstuffs_optimizer_edge
                ok = fn(
                    cfg["api_class"], cfg["find_nearby"], cfg["company_id"], cfg["company_name"],
                    address, dish, True, max_dist_km=distance,
                )
            if not ok:
                raise RuntimeError("optimizer returned no data for this address/dish")
            today_rows = len(writer.fetch_today(company=brand))
            return today_rows, 0
        finally:
            optimizer_utils.append_rows = orig_ou

    # ------------------------------------------------------------------ #
    # Phase 2: build the comparison summary from today's rows
    # ------------------------------------------------------------------ #
    def _phase2_optimize(self, writer, dish, dish_name, ingredients, brand) -> dict:
        rows = writer.fetch_today(company=brand)
        today_str = date.today().isoformat()
        rows = [r for r in rows if (r.get("date_created") or today_str) == today_str]
        df = pd.DataFrame(rows, columns=CSV_COLUMNS)
        summary_out = {"rows": len(df), "dish": dish_name, "brand": brand, "date": today_str}

        if df.empty or not ingredients:
            summary_out["note"] = "no priced rows found for this dish/company today"
            return summary_out

        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        df = df[df["price"].notna()]
        if df.empty:
            summary_out["note"] = "no priced rows after numeric coercion"
            return summary_out

        summary_df, table_df = analyze_results(df, ingredients, dish, company=brand)

        def _money(v) -> float:
            try:
                return float(str(v).replace("$", "").replace(",", "").strip())
            except (TypeError, ValueError):
                return 0.0

        summary_records = []
        for _, r in summary_df.reset_index().iterrows():
            summary_records.append({"store": r.get("store"), "total_cost": _money(r.get("total_cost"))})
        summary_records.sort(key=lambda r: r["total_cost"])
        summary_out["summary"] = summary_records
        if summary_records:
            c = summary_records[0]
            summary_out["cheapest_store"] = c["store"]
            summary_out["cheapest_total"] = c["total_cost"]

        best_rows = []
        for _, r in table_df.reset_index().iterrows():
            best_store = r.get("Best Store")
            if best_store and best_store not in ("(mix)", "-", None):
                best_rows.append({
                    "ingredient": r.get("Ingredient"),
                    "best_store": best_store,
                    "best_price": r.get("Best Price"),
                })
        summary_out["best_per_ingredient"] = best_rows
        return summary_out

    # ------------------------------------------------------------------ #
    # test affordance: synthetic rows so plumbing is exercisable offline
    # ------------------------------------------------------------------ #
    def _synthetic_rows(self, job) -> list[dict]:
        brand = job.params["brand"]
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        dish_name, ingredients = _resolve_dish(job.params["dish"])
        stores = ["Synthetic Metro", "Synthetic Local"]
        base_prices = [3.49, 4.12]
        rows = []
        for idx, ing in enumerate(ingredients):
            for s_idx, store in enumerate(stores):
                row = {
                    "company": brand,
                    "store": store,
                    "store_id": f"synth-{brand}-{store}",
                    "search_ingredient": ing,
                    "returned_ingredient": f"{ing} (synthetic)",
                    "price": round(base_prices[s_idx] + idx * 0.05, 2),
                    "quantity": 1,
                    "measurement_unit": "kg",
                    "per_unit_quantity": "kg",
                    "per_unit_price": base_prices[s_idx],
                    "is_sale": s_idx == 0,
                    "sku": f"synth-{ing}-{s_idx}",
                    "department": "produce",
                    "sub_department": "veg",
                    "datetime_created": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "date_created": date_str,
                    "pk_hash": _compute_pk_hash(f"synth-{brand}-{store}", f"synth-{ing}-{s_idx}", date_str),
                    "is_valid": None,
                }
                rows.append(row)
        return rows


def _safe_json(obj) -> Optional[str]:
    try:
        return _json_dumps(obj)
    except Exception:
        return str(obj)


def _json_dumps(obj) -> str:
    import json
    return json.dumps(obj, default=str, ensure_ascii=False)


def get_supabase_safe():
    if settings.supabase_enabled:
        try:
            return get_supabase()
        except Exception as e:
            log.warning("Supabase enabled but client failed: %s — falling back to local mode.", e)
    return None


def build_worker() -> OptimizerWorker:
    supabase = get_supabase_safe()
    store_registry = StoreRegistry(supabase)
    store_registry.load()
    job_store = JobStore(supabase) if supabase else JobStore(None)
    job_queue = JobQueue(job_store)
    job_queue.start()
    return OptimizerWorker(job_queue, store_registry, supabase)


__all__ = ["OptimizerWorker", "build_worker", "BRANDS", "get_supabase_safe", "JobQueue"]
