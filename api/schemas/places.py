from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

_MAX_PLACES_PER_USER = 20
_MIN_RADIUS = 100.0
_MAX_RADIUS = 400.0
_DEFAULT_RADIUS = 150.0


class FrequentPlaceCreate(BaseModel):
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: float = Field(
        default=_DEFAULT_RADIUS, ge=_MIN_RADIUS, le=_MAX_RADIUS
    )


class FrequentPlaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: float = Field(ge=_MIN_RADIUS, le=_MAX_RADIUS)


class FrequentPlaceResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    latitude: float
    longitude: float
    radius_meters: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
