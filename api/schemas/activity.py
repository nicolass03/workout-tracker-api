from datetime import date, datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# Matches iOS ActivitySyncService downsample maxPoints.
_MAX_TRAIL_POINTS = 4000


class APIModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class TrailPoint(APIModel):
    lat: float
    lon: float
    t: AwareDatetime
    seg: int = Field(default=0, ge=0)
    seg_steps: int | None = Field(default=None, ge=0)


class DailyActivityUpsert(APIModel):
    steps: int = Field(ge=0)
    active_energy_kcal: float = Field(ge=0)
    distance_meters: float = Field(ge=0)
    trail: list[TrailPoint] = Field(default_factory=list, max_length=_MAX_TRAIL_POINTS)


class DailyActivityResponse(APIModel):
    id: UUID
    user_id: UUID
    day: date
    steps: int
    active_energy_kcal: float
    distance_meters: float
    trail: list[TrailPoint]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, allow_inf_nan=False)
