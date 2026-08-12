"""Phase 2: dual-mode result persistence.

`ResultWriter` abstracts where optimizer rows are persisted so the worker can
run in two modes transparently:

* **Supabase mode** (SUPABASE_* env set): rows `INSERT` into `results` with
  `ON CONFLICT (pk_hash) DO NOTHING` semantics (via SELECT-then-INSERT for
  accurate appended/skipped counts). Woolworths `store_id` is normalized to
  `extra1` (fulfilmentStoreId) to match `stores.store_id`.
* **Local-only fallback** (no Supabase keys): rows are kept in a session-scoped
  temp CSV (`scripts/fastapi/tmp/<session>_results.csv`) + an in-memory index,
  so a fresh GitHub checkout with no DB can still query + optimise for the
  lifetime of the process — exactly the "store while session persists" need.

The legacy `append_rows` in `optimizer_utils`/`woolworths_optimizer` is swapped
(per-job, restored in `finally`) to call `writer.write_rows`, so the existing
CLI/notebook pipelines run unmodified and the worker never edits source files.
"""
from __future__ import annotations

import csv
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import Optional

import core.paths  # noqa: F401
from core.paths import FASTAPI_DIR
from optimizer_utils import CSV_COLUMNS

_TMP_DIR = FASTAPI_DIR / "tmp"


def _coerce_row(row: dict) -> dict:
    """Normalize a build_*_row dict for persistence."""
    out = dict(row)
    # empty-string numerics -> null (DB-safe)
    for k in ("price", "per_unit_price", "quantity"):
        v = out.get(k, "")
        if v == "" or v is None:
            out[k] = None
    # ensure is_valid present (blank in CSV → NULL in DB)
    if "is_valid" not in out:
        out["is_valid"] = None
    return out


class ResultWriter(ABC):
    """Abstract result sink + reader used by OptimizerWorker."""

    @abstractmethod
    def write_rows(self, rows, results_file=None) -> tuple[int, int]:
        """Persist rows. Returns (appended, skipped)."""

    @abstractmethod
    def fetch_today(self, company: Optional[str] = None, store_ids: Optional[set] = None,
                    require_valid: bool = False) -> list[dict]:
        """Rows created today, optionally filtered by company / store_ids / validity."""

    @property
    @abstractmethod
    def kind(self) -> str:
        ...


class SupabaseResultWriter(ResultWriter):
    def __init__(self, supabase, store_registry=None) -> None:
        self._supabase = supabase
        self._registry = store_registry
        self._lock = threading.Lock()

    @property
    def kind(self) -> str:
        return "supabase"

    def _normalize(self, row: dict) -> dict:
        company = row.get("company", "")
        if company == "Woolworths" and self._registry is not None:
            row = dict(row)
            row["store_id"] = self._registry.normalize_store_id("Woolworths", row.get("store_id", ""))
        return row

    def write_rows(self, rows, results_file=None) -> tuple[int, int]:
        if not rows:
            return 0, 0
        rows = [_coerce_row(self._normalize(r)) for r in rows]
        hashes = [r["pk_hash"] for r in rows]
        with self._lock:
            existing_resp = self._supabase.from_("results").select("pk_hash").in_("pk_hash", hashes).execute().data
            existing = {r["pk_hash"] for r in (existing_resp or [])}
            to_insert = [r for r in rows if r["pk_hash"] not in existing]
            skipped = len(rows) - len(to_insert)
            if to_insert:
                self._supabase.from_("results").insert(to_insert).execute()
        return len(to_insert), skipped

    def fetch_today(self, company=None, store_ids=None, require_valid=False) -> list[dict]:
        today = date.today().isoformat()
        q = self._supabase.from_("results").select("*").eq("date_created", today)
        if company:
            q = q.eq("company", company)
        resp = q.execute().data or []
        if store_ids:
            resp = [r for r in resp if r.get("store_id") in store_ids]
        if require_valid:
            resp = [r for r in resp if r.get("is_valid") is True]
        return resp


class LocalTempResultWriter(ResultWriter):
    """Fallback writer: session-scoped temp CSV + in-memory index (no DB)."""

    def __init__(self, store_registry=None, session_id: Optional[str] = None) -> None:
        self._registry = store_registry
        self._rows: list[dict] = []
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        self._session_id = session_id or uuid.uuid4().hex[:8]
        _TMP_DIR.mkdir(parents=True, exist_ok=True)
        self.temp_path = _TMP_DIR / f"{self._session_id}_results.csv"
        with self._lock:
            if self.temp_path.exists():
                self.temp_path.unlink()
            self._write_header()

    @property
    def kind(self) -> str:
        return "local_temp"

    def _write_header(self) -> None:
        with open(self.temp_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if self.temp_path.stat().st_size == 0:
                w.writeheader()

    def _normalize(self, row: dict) -> dict:
        company = row.get("company", "")
        if company == "Woolworths" and self._registry is not None:
            row = dict(row)
            row["store_id"] = self._registry.normalize_store_id("Woolworths", row.get("store_id", ""))
        return row

    def write_rows(self, rows, results_file=None) -> tuple[int, int]:
        if not rows:
            return 0, 0
        appended = skipped = 0
        with self._lock:
            for r in rows:
                row = self._normalize(r)
                h = row.get("pk_hash")
                if h in self._seen:
                    skipped += 1
                    continue
                safe = _coerce_row(row)
                self._rows.append(safe)
                self._seen.add(h)
                with open(self.temp_path, "a", newline="", encoding="utf-8") as f:
                    csv.DictWriter(f, fieldnames=CSV_COLUMNS).writerow(
                        {k: safe.get(k, "") for k in CSV_COLUMNS}
                    )
                appended += 1
        return appended, skipped

    def fetch_today(self, company=None, store_ids=None, require_valid=False) -> list[dict]:
        today = date.today().isoformat()
        with self._lock:
            rows = list(self._rows)
        out = [r for r in rows if r.get("date_created") == today]
        if company:
            out = [r for r in out if r.get("company") == company]
        if store_ids:
            out = [r for r in out if r.get("store_id") in store_ids]
        if require_valid:
            out = [r for r in out if r.get("is_valid") is True]
        return out

    def cleanup(self) -> None:
        try:
            if self.temp_path.exists():
                self.temp_path.unlink()
        except OSError:
            pass


def create_writer(supabase=None, store_registry=None, session_id: Optional[str] = None) -> ResultWriter:
    """Pick Supabase writer when configured, else a local-temp writer."""
    if supabase is not None:
        return SupabaseResultWriter(supabase, store_registry)
    return LocalTempResultWriter(store_registry, session_id=session_id)
