"""Optimizer job lifecycle routes.

POST /jobs/optimize  -> enqueue a (brand, dish, address) optimization job
GET  /jobs/{job_id}  -> poll status / result
GET  /jobs/         -> list recent jobs (memory or Supabase)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from workers.job_queue import JobQueue, JobStore, JobType
from models.jobs import CreateJobRequest, JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_job_queue(request: Request) -> JobQueue:
    return request.app.state.job_queue


def _normalize_brand(brand: str) -> str:
    m = {"paknsave": "PaknSave", "pakn-save": "PaknSave", "pak n save": "PaknSave",
         "newworld": "NewWorld", "new world": "NewWorld",
         "woolworths": "Woolworths", "countdown": "Woolworths"}
    return m.get(brand.strip().lower(), brand)


@router.post("/optimize", response_model=JobResponse)
def enqueue_optimize(req: CreateJobRequest, request: Request):
    brand = _normalize_brand(req.brand)
    if brand not in ("PaknSave", "NewWorld", "Woolworths"):
        raise HTTPException(status_code=400, detail=f"Unsupported brand: {req.brand}")
    if not req.dry_run and not req.address:
        raise HTTPException(status_code=400, detail="address is required unless dry_run=true")

    params = {
        "brand": brand,
        "dish": req.dish,
        "address": req.address,
        "distance_km": req.distance_km,
        "backend": req.backend,
        "dry_run": req.dry_run,
    }
    job_queue: JobQueue = get_job_queue(request)
    job = job_queue.enqueue(JobType.OPTIMIZE, params)
    return JobResponse(**job.to_dict())


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, request: Request):
    job = get_job_queue(request).store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return JobResponse(**job.to_dict())


@router.get("/", response_model=list[JobResponse])
def list_jobs(request: Request, status: str | None = None):
    jobs = get_job_queue(request).store.list(status)
    return [JobResponse(**j.to_dict()) for j in jobs]
