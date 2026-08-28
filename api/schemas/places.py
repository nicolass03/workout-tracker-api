from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_MAX_PLACES_PER_USER = 20
_MIN_RADIUS = 10.0
_MAX_RADIUS = 250.0
_DEFAULT_RADIUS = 150.0


class PlacePayload(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    @field_validator("name", check_fields=False)
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @field_validator("address", check_fields=False)
    @classmethod
    def strip_address(cls, value: str) -> str:
        return value.strip()


class FrequentPlaceCreate(PlacePayload):
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=80)
    address: str = Field(default="", max_length=300)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: float = Field(
        default=_DEFAULT_RADIUS, ge=_MIN_RADIUS, le=_MAX_RADIUS
    )


class FrequentPlaceUpdate(PlacePayload):
    name: str = Field(min_length=1, max_length=80)
    address: str = Field(default="", max_length=300)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: float = Field(ge=_MIN_RADIUS, le=_MAX_RADIUS)


class FrequentPlaceResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    address: str = ""
    latitude: float
    longitude: float
    radius_meters: float
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, allow_inf_nan=False)
