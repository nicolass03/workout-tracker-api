from datetime import datetime
from typing import Any, Literal
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


class MoveSessionHistoryItem(APIModel):
    """Compact move-session representation used by the infinite history feed."""

    id: UUID
    type: MoveSessionType
    started_at: datetime
    ended_at: datetime
    active_duration_seconds: float
    active_energy_kcal: float
    steps: int
    distance_meters: float
    elevation_gain_meters: float | None = None
    elevation_loss_meters: float | None = None
    has_trail: bool


class MoveSessionHistoryPage(APIModel):
    items: list[MoveSessionHistoryItem]
    next_cursor: str | None = None


# Names retained for imports in older callers.
WalkRunSessionCreate = MoveSessionCreate
WalkRunSessionResponse = MoveSessionResponse


class RawTrailSample(APIModel):
    session_id: UUID
    section_id: UUID
    sequence: int = Field(ge=0)
    timestamp: AwareDatetime
    received_at: AwareDatetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude: float | None = None
    horizontal_accuracy: float = Field(ge=0)
    vertical_accuracy: float | None = Field(default=None, ge=0)
    speed: float | None = None
    speed_accuracy: float | None = Field(default=None, ge=0)
    course: float | None = Field(default=None, ge=0, le=360)
    course_accuracy: float | None = Field(default=None, ge=0)
    is_stationary: bool
    is_full_accuracy: bool
    is_simulated_by_software: bool
    is_produced_by_accessory: bool
    quality: Literal[
        "usable", "weak", "diagnosticOnly", "invalidTimestamp", "invalidCoordinate"
    ]


class TraceChunkUpsert(APIModel):
    first_at: AwareDatetime
    last_at: AwareDatetime
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    samples: list[RawTrailSample] = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_chunk(self) -> "TraceChunkUpsert":
        if self.last_at < self.first_at:
            raise ValueError("last_at must be on or after first_at")
        if any(sample.timestamp < self.first_at or sample.timestamp > self.last_at for sample in self.samples):
            raise ValueError("sample timestamps must fit inside the chunk bounds")
        sequences = [sample.sequence for sample in self.samples]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("sample sequences must be unique and ascending")
        return self


class TraceChunkManifestItem(APIModel):
    kind: Literal["location", "motion"]
    section_index: int
    chunk_index: int
    first_at: datetime
    last_at: datetime
    sample_count: int
    checksum_sha256: str


class CanonicalTrailCoordinate(APIModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class CanonicalTrailSection(APIModel):
    id: UUID
    source: Literal["filteredGPS", "inertialBridge", "mapMatched"]
    confidence: float = Field(ge=0, le=1)
    coordinates: list[CanonicalTrailCoordinate] = Field(min_length=2)


class CanonicalTrailUpsert(APIModel):
    algorithm_version: str = Field(min_length=1, max_length=100)
    graph_version: str | None = Field(default=None, max_length=200)
    status: Literal["gpsOnly", "partiallyMatched", "matched"]
    confidence: float = Field(ge=0, le=1)
    distance_meters: float = Field(ge=0)
    quality: dict[str, Any] = Field(default_factory=dict)
    sections: list[CanonicalTrailSection]
    processed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_route_size(self) -> "CanonicalTrailUpsert":
        if sum(len(section.coordinates) for section in self.sections) > 100_000:
            raise ValueError("canonical route cannot exceed 100000 coordinates")
        return self


class CanonicalTrailResponse(CanonicalTrailUpsert):
    session_id: UUID
    revision: int
    created_at: datetime
    updated_at: datetime
