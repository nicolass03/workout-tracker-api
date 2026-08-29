from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_TRAIL_POINTS = 4000
_MAX_ELEVATION_SAMPLES = 4000
MoveSessionType = Literal["walk_run", "walk", "run", "jogging", "hiking"]


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
    vertical_accuracy: float | None = Field(default=None, ge=0)
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


class ElevationSample(APIModel):
    t: AwareDatetime
    altitude_meters: float
    segment_index: int = Field(default=0, ge=0)


class ElevationSampleResponse(APIModel):
    t: datetime
    altitude_meters: float
    segment_index: int = 0


class MoveSessionCreate(APIModel):
    id: UUID | None = None
    type: MoveSessionType
    started_at: AwareDatetime
    ended_at: AwareDatetime
    active_duration_seconds: float = Field(ge=0)
    active_energy_kcal: float = Field(ge=0)
    steps: int = Field(ge=0)
    distance_meters: float = Field(ge=0)
    segments: list[SessionSegmentIn] = Field(default_factory=list)
    elevation_gain_meters: float | None = Field(default=None, ge=0)
    elevation_loss_meters: float | None = Field(default=None, ge=0)
    elevation_samples: list[ElevationSample] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_times_and_points(self) -> "MoveSessionCreate":
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must be on or after started_at")
        if self.active_duration_seconds > (self.ended_at - self.started_at).total_seconds():
            raise ValueError("active_duration_seconds cannot exceed the session duration")
        total_points = sum(len(s.points) for s in self.segments)
        if total_points > _MAX_TRAIL_POINTS:
            raise ValueError(f"Total trail points cannot exceed {_MAX_TRAIL_POINTS}")
        if len(self.elevation_samples) > _MAX_ELEVATION_SAMPLES:
            raise ValueError(
                f"Elevation samples cannot exceed {_MAX_ELEVATION_SAMPLES}"
            )
        if self.type != "hiking" and (
            self.elevation_gain_meters is not None
            or self.elevation_loss_meters is not None
            or self.elevation_samples
        ):
            raise ValueError("Elevation data is supported for hiking sessions only")
        if any(
            sample.t < self.started_at or sample.t > self.ended_at
            for sample in self.elevation_samples
        ):
            raise ValueError("elevation sample timestamps must fall within the session")
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


class MoveSessionResponse(APIModel):
    id: UUID
    user_id: UUID
    type: MoveSessionType
    started_at: datetime
    ended_at: datetime
    active_duration_seconds: float
    active_energy_kcal: float
    steps: int
    distance_meters: float
    segments: list[SessionSegmentResponse]
    elevation_gain_meters: float | None = None
    elevation_loss_meters: float | None = None
    elevation_samples: list[ElevationSampleResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("steps", "distance_meters", mode="before")
    @classmethod
    def require_move_metrics(cls, value: object) -> object:
        if value is None:
            raise ValueError("move sessions require steps and distance_meters")
        return value


# Names retained for imports in older callers.
WalkRunSessionCreate = MoveSessionCreate
WalkRunSessionResponse = MoveSessionResponse
