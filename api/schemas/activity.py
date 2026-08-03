from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TrailPoint(BaseModel):
    lat: float
    lon: float
    t: datetime


class DailyActivityUpsert(BaseModel):
    steps: int = Field(ge=0)
    active_energy_kcal: float = Field(ge=0)
    distance_meters: float = Field(ge=0)
    trail: list[TrailPoint] = Field(default_factory=list)


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
