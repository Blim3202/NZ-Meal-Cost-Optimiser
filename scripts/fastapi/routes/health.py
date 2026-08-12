"""Health + liveness route."""
from fastapi import APIRouter
from core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "supabase_enabled": settings.supabase_enabled,
        "worker_mode": "supabase" if settings.supabase_enabled else "local_fallback",
    }
