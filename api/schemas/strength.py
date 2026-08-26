import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

_MAX_STATE_BYTES = 2_000_000
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
