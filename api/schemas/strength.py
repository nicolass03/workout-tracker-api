import json
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

_MAX_STATE_BYTES = 2_000_000
_MAX_WORKOUT_BYTES = 500_000
_SCHEMA_VERSION = 1


class StrengthStateEnvelope(BaseModel):
    schema_version: int = Field(alias="schemaVersion")
    client_updated_at: datetime = Field(alias="clientUpdatedAt")
    state: dict[str, Any]

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def validate_state(self) -> "StrengthStateEnvelope":
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError(f"schemaVersion must be {_SCHEMA_VERSION}")
        encoded = json.dumps(self.state, separators=(",", ":"), default=str).encode("utf-8")
        if len(encoded) > _MAX_STATE_BYTES:
            raise ValueError("state payload is too large")
        return self


class StrengthStateResponse(StrengthStateEnvelope):
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}


class StrengthRoutinePayload(BaseModel):
    id: UUID
    name: str
    symbol_name: str = Field(default="dumbbell", alias="symbolName")
    progression: str = "linear"
    exercises: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class StrengthRoutineResponse(StrengthRoutinePayload):
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}


class StrengthWeekAssignmentPayload(BaseModel):
    routine_id: UUID | None = Field(default=None, alias="routineId")

    model_config = {"populate_by_name": True}


class StrengthWeekAssignmentResponse(StrengthWeekAssignmentPayload):
    weekday: int
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}


class StrengthWorkoutPayload(BaseModel):
    id: UUID
    workout_date: date = Field(alias="date")
    name: str = Field(min_length=1, max_length=120)
    started_at: datetime = Field(alias="startedAt")
    ended_at: datetime = Field(alias="endedAt")
    entries: list[dict[str, Any]] = Field(min_length=1, max_length=100)

    model_config = {"populate_by_name": True}

    @field_validator("name")
    @classmethod
    def require_nonempty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @model_validator(mode="after")
    def validate_workout(self) -> "StrengthWorkoutPayload":
        if self.ended_at < self.started_at:
            raise ValueError("endedAt must be on or after startedAt")
        encoded = json.dumps(self.entries, separators=(",", ":"), default=str).encode("utf-8")
        if len(encoded) > _MAX_WORKOUT_BYTES:
            raise ValueError("workout entries payload is too large")
        return self


class StrengthWorkoutResponse(StrengthWorkoutPayload):
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}


class StrengthWorkoutPage(BaseModel):
    items: list[StrengthWorkoutResponse]
    next_offset: int | None = Field(alias="nextOffset")

    model_config = {"populate_by_name": True}
