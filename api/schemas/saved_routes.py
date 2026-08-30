from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from api.schemas.sessions import APIModel, CanonicalTrailSection, MoveSessionType


class SavedRouteCreate(APIModel):
    source_session_id: UUID
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized


class SavedRouteSummary(APIModel):
    id: UUID
    source_session_id: UUID | None
    name: str
    activity_type: MoveSessionType
    distance_meters: float
    confidence: float
    graph_version: str | None
    created_at: datetime
    updated_at: datetime


class SavedRouteResponse(SavedRouteSummary):
    source_route_revision: int
    algorithm_version: str
    status: Literal["gpsOnly", "partiallyMatched", "matched"]
    sections: list[CanonicalTrailSection]
