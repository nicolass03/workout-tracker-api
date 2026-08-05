from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

# Matches iOS ActivitySyncService downsample maxPoints.
_MAX_TRAIL_POINTS = 4000


class TrailPoint(BaseModel):
    lat: float
    lon: float
    t: datetime
    seg: int = Field(default=0, ge=0)
    seg_steps: int | None = Field(default=None, ge=0)


class DailyActivityUpsert(BaseModel):
    steps: int = Field(ge=0)
    active_energy_kcal: float = Field(ge=0)
    distance_meters: float = Field(ge=0)
    trail: list[TrailPoint] = Field(default_factory=list, max_length=_MAX_TRAIL_POINTS)


class DailyActivitySummary(BaseModel):
    day: date
    steps: int
    active_energy_kcal: float
    distance_meters: float

    model_config = {"from_attributes": True}


class DailyActivityResponse(BaseModel):
    id: UUID
    user_id: UUID
    day: date
    steps: int
    active_energy_kcal: float
    distance_meters: float
    trail: list[TrailPoint]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
