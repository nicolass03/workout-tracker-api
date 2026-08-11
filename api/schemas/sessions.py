from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

_MAX_TRAIL_POINTS = 4000


class SegmentPoint(BaseModel):
    lat: float
    lon: float
    t: datetime


class SessionSegmentIn(BaseModel):
    id: UUID | None = None
    idx: int = Field(ge=0)
    started_at: datetime
    ended_at: datetime | None = None
    steps: int = Field(default=0, ge=0)
    points: list[SegmentPoint] = Field(default_factory=list)


class SessionSegmentResponse(BaseModel):
    id: UUID
    idx: int
    started_at: datetime
    ended_at: datetime | None
    steps: int
    points: list[SegmentPoint]

    model_config = {"from_attributes": True}


class WalkRunSessionCreate(BaseModel):
    id: UUID | None = None
    type: Literal["walk_run"] = "walk_run"
    started_at: datetime
    ended_at: datetime
    active_duration_seconds: float = Field(ge=0)
    active_energy_kcal: float = Field(ge=0)
    steps: int = Field(ge=0)
    distance_meters: float = Field(ge=0)
    segments: list[SessionSegmentIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_times_and_points(self) -> "WalkRunSessionCreate":
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must be on or after started_at")
        total_points = sum(len(s.points) for s in self.segments)
        if total_points > _MAX_TRAIL_POINTS:
            raise ValueError(f"Total trail points cannot exceed {_MAX_TRAIL_POINTS}")
        idxs = [s.idx for s in self.segments]
        if len(idxs) != len(set(idxs)):
            raise ValueError("segment idx values must be unique within a session")
        return self


class WalkRunSessionResponse(BaseModel):
    id: UUID
    user_id: UUID
    type: Literal["walk_run"]
    started_at: datetime
    ended_at: datetime
    active_duration_seconds: float
    active_energy_kcal: float
    steps: int
    distance_meters: float
    segments: list[SessionSegmentResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("steps", "distance_meters", mode="before")
    @classmethod
    def require_walk_run_metrics(cls, value: object) -> object:
        if value is None:
            raise ValueError("walk_run sessions require steps and distance_meters")
        return value
