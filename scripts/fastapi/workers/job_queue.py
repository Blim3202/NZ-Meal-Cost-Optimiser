"""Phase 2: thread-safe job queue + status store.

Design: a single `queue.Queue` fed by many FastAPI request threads (producers)
and drained by a SINGLE `OptimizerWorker` thread (consumer). queue.Queue is
thread-safe, so enqueues never collide. A single consumer trivially serialises
every concurrency hazard (Nominatim 1 req/s, LLM rate limits, cookie/session
isolation) — see AGENTS.md / HANDOVER.md §Challenges.

Job status is mirrored to the Supabase `jobs` table when configured, and also
held in-memory so `GET /jobs/{id}` works in local-only fallback mode.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

import core.paths  # noqa: F401  (ensures sys.path bootstrap ran)


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class JobType:
    OPTIMIZE = "optimize"
    GENERATE_DISH = "generate_dish"
    FILTER_INGREDIENTS = "filter_ingredients"
    VALIDATE_RESULTS = "validate_results"
    SCALE_QUANTITY = "scale_quantity"


@dataclass
class Job:
    job_id: str
    type: str
    params: dict
    status: str = JobStatus.QUEUED
    result_ref: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)


_SHUTDOWN = object()


class JobQueue:
    """Thread-safe work queue. Producers enqueue; the worker dequeues."""

    def __init__(self, job_store) -> None:
        self._q: "queue.Queue[object]" = None  # set in start() to avoid import-order issues
        self._q_lock = threading.Lock()
        self.store = job_store
        self._size = 0
        self._size_lock = threading.Lock()

    def start(self) -> None:
        import queue as _q
        with self._q_lock:
            if self._q is None:
                self._q = _q.Queue()

    def enqueue(self, type_: str, params: dict) -> Job:
        job = self.store.create(type_, params)
        assert self._q is not None, "JobQueue.start() must be called first"
        self._q.put(job)
        with self._size_lock:
            self._size += 1
        return job

    def dequeue(self, timeout: Optional[float] = None) -> Optional[Job]:
        assert self._q is not None, "JobQueue.start() must be called first"
        item = self._q.get(timeout=timeout)
        if item is _SHUTDOWN:
            return None
        with self._size_lock:
            if self._size > 0:
                self._size -= 1
        return item

    def size(self) -> int:
        return self._size

    def shutdown(self) -> None:
        assert self._q is not None
        self._q.put(_SHUTDOWN)


class JobStore:
    """Persist job status to Supabase `jobs` table when configured, else in-memory.

    In-memory mode is the local-only fallback (no .env / no Supabase keys):
    status lives for the lifetime of the app process, which matches the
    "store results while the session persists" requirement.
    """

    def __init__(self, supabase_client=None) -> None:
        self._supabase = supabase_client
        self._memory: dict[str, Job] = {}
        self._lock = threading.Lock()

    def _use_db(self) -> bool:
        return self._supabase is not None

    def create(self, type_: str, params: dict) -> Job:
        job = Job(job_id=str(uuid.uuid4()), type=type_, params=params)
        if self._use_db():
            try:
                self._supabase.from_("jobs").insert({
                    "job_id": job.job_id,
                    "type": job.type,
                    "status": job.status,
                    "params": job.params,
                    "created_at": job.created_at,
                    "updated_at": job.updated_at,
                }).execute()
            except Exception:
                pass  # fall through to in-memory so enqueue never fails
        with self._lock:
            self._memory[job.job_id] = job
        return job

    def set_status(self, job_id: str, status: str, result_ref: Optional[str] = None,
                   error_message: Optional[str] = None) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        updates: dict = {"status": status, "updated_at": now}
        if result_ref is not None:
            updates["result_ref"] = result_ref
        if error_message is not None:
            updates["error_message"] = error_message
        if self._use_db():
            try:
                self._supabase.from_("jobs").update(updates).eq("job_id", job_id).execute()
            except Exception:
                pass
        with self._lock:
            job = self._memory.get(job_id)
            if job is not None:
                job.status = status
                job.updated_at = now
                if result_ref is not None:
                    job.result_ref = result_ref
                if error_message is not None:
                    job.error_message = error_message

    def get(self, job_id: str) -> Optional[Job]:
        if self._use_db():
            try:
                row = self._supabase.from_("jobs").select("*").eq("job_id", job_id).single().execute().data
                if row:
                    return Job(
                        job_id=row["job_id"],
                        type=row.get("type", "") or "",
                        params=row.get("params") or {},
                        status=row.get("status", JobStatus.QUEUED),
                        result_ref=row.get("result_ref"),
                        error_message=row.get("error_message"),
                        created_at=row.get("created_at"),
                        updated_at=row.get("updated_at"),
                    )
            except Exception:
                pass
        with self._lock:
            return self._memory.get(job_id)

    def list(self, status: Optional[str] = None) -> list:
        if self._use_db():
            try:
                q = self._supabase.from_("jobs").select("*")
                if status:
                    q = q.eq("status", status)
                rows = q.execute().data or []
                out = []
                for r in rows:
                    out.append(Job(
                        job_id=r["job_id"],
                        type=r.get("type", "") or "",
                        params=r.get("params") or {},
                        status=r.get("status", JobStatus.QUEUED),
                        result_ref=r.get("result_ref"),
                        error_message=r.get("error_message"),
                        created_at=r.get("created_at"),
                        updated_at=r.get("updated_at"),
                    ))
                return out
            except Exception:
                pass
        with self._lock:
            jobs = list(self._memory.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        return jobs
