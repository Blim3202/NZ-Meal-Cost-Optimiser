"""FastAPI entrypoint for the NZ Meal Cost Optimizer.

Run:
    .venv\\Scripts\\python scripts/fastapi/main.py
or:
    .venv\\Scripts\\uvicorn main:app --app-dir scripts/fastapi --port 8000

Lifespan starts the single-background OptimizerWorker thread (queue.Queue +
daemon thread, no Redis). When SUPABASE_* env vars are present the worker uses
Supabase; otherwise it runs in local-only fallback (temp CSV + in-memory
job store) so a fresh checkout with no DB can still submit + resolve jobs.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

import core.paths  # noqa: F401  (bootstrap sys.path for legacy modules)
from core.config import settings
from routes import health, jobs
from workers.optimizer_worker import OptimizerWorker, build_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fastapi.main")

TMP_DIR = Path(__file__).resolve().parent / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Booting OptimizerWorker (supabase_enabled=%s).", settings.supabase_enabled)
    worker: OptimizerWorker = build_worker()
    worker.start()
    # expose to routes via app.state
    app.state.worker = worker
    app.state.job_queue = worker.queue
    app.state.store_registry = worker.store_registry
    app.state.supabase = worker.supabase
    log.info("FastAPI ready. Worker thread alive=%s.", worker._thread.is_alive())
    yield
    log.info("Shutting down OptimizerWorker.")
    worker.stop()


app = FastAPI(
    title="NZ Meal Cost Optimizer",
    description="Queued, single-worker API over Pak'nSave / New World / Woolworths ingredient prices.",
    lifespan=lifespan,
)
app.include_router(health.router)
app.include_router(jobs.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
