"""Phase 2-3: Pydantic models for the optimizer job surface."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CreateJobRequest(BaseModel):
    brand: str = Field(..., description="PaknSave | NewWorld | Woolworths")
    dish: str = Field(..., description="Dish name (must exist in dishes.json) or a search term")
    address: Optional[str] = Field(default=None, description="NZ address to geocode. Required unless dry_run=True")
    distance_km: float = Field(default=5.0, description="Store search radius in km (default 5)")
    backend: Optional[str] = Field(default="edge", description="Foodstuffs backend: edge (two-pass) or mobile (single-pass). Ignored for Woolworths.")
    dry_run: bool = Field(default=False, description="If true, skip live API and use synthetic rows (offline test affordance)")


class JobResponse(BaseModel):
    job_id: str
    type: str
    status: str
    params: dict
    result_ref: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
