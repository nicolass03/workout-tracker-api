from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_TRAIL_POINTS = 4000


class APIModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class SegmentPoint(APIModel):
    lat: float
    lon: float
    t: AwareDatetime
    accuracy: float | None = Field(default=None, ge=0)
    speed: float | None = None
    course: float | None = Field(default=None, ge=0, le=360)
    altitude: float | None = None
    display: bool | None = None


class SessionSegmentIn(APIModel):
    id: UUID | None = None
    idx: int = Field(ge=0)
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    steps: int = Field(default=0, ge=0)
    points: list[SegmentPoint] = Field(default_factory=list)


class SessionSegmentResponse(APIModel):
    id: UUID
    idx: int
    started_at: datetime
    ended_at: datetime | None
    steps: int
    points: list[SegmentPoint]

    model_config = {"from_attributes": True}


class WalkRunSessionCreate(APIModel):
    id: UUID | None = None
    type: Literal["walk_run"] = "walk_run"
    started_at: AwareDatetime
    ended_at: AwareDatetime
    active_duration_seconds: float = Field(ge=0)
    active_energy_kcal: float = Field(ge=0)
    steps: int = Field(ge=0)
    distance_meters: float = Field(ge=0)
    segments: list[SessionSegmentIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_times_and_points(self) -> "WalkRunSessionCreate":
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must be on or after started_at")
        if self.active_duration_seconds > (self.ended_at - self.started_at).total_seconds():
            raise ValueError("active_duration_seconds cannot exceed the session duration")
        total_points = sum(len(s.points) for s in self.segments)
        if total_points > _MAX_TRAIL_POINTS:
            raise ValueError(f"Total trail points cannot exceed {_MAX_TRAIL_POINTS}")
        idxs = [s.idx for s in self.segments]
        if len(idxs) != len(set(idxs)):
            raise ValueError("segment idx values must be unique within a session")
        for segment in self.segments:
            if segment.ended_at is not None and segment.ended_at < segment.started_at:
                raise ValueError("segment ended_at must be on or after started_at")
            if segment.started_at < self.started_at or (
                segment.ended_at is not None and segment.ended_at > self.ended_at
            ):
                raise ValueError("segment timestamps must fall within the session")
        return self


class WalkRunSessionResponse(APIModel):
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
