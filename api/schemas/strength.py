from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

WeightUnit = Literal["kg", "lb"]
ExerciseMode = Literal["reps", "time", "cardio"]
Progression = Literal["off", "linear", "double", "time"]


class ExerciseResponse(BaseModel):
    id: str
    name: str = Field(alias="n")
    body_part: str = Field(alias="bp")
    equipment: str = Field(alias="eq")
    target: str = Field(alias="tg")
    main_muscle: str | None = Field(default=None, alias="mg")
    secondary_muscles: list[str] = Field(default_factory=list, alias="sm")
    steps: list[str] = Field(default_factory=list, alias="st")
    image_url: str | None = Field(default=None, alias="img")
    gif_url: str | None = Field(default=None, alias="gif")

    model_config = {"populate_by_name": True}


class ExercisePage(BaseModel):
    items: list[ExerciseResponse]
    next_offset: int | None = Field(alias="nextOffset")

    model_config = {"populate_by_name": True}


class RoutineExercisePayload(BaseModel):
    id: UUID
    exercise_id: str = Field(alias="exerciseId", min_length=1, max_length=100)
    mode: ExerciseMode = "reps"
    sets: int = Field(default=3, ge=1, le=50)
    reps: int = Field(default=10, ge=0, le=1_000)
    reps_min: int | None = Field(default=None, alias="repsMin", ge=0, le=1_000)
    reps_max: int | None = Field(default=None, alias="repsMax", ge=0, le=1_000)
    seconds: int = Field(default=45, ge=0, le=86_400)
    minutes: int = Field(default=20, ge=0, le=1_440)
    speed_kmh: float = Field(default=8, alias="speedKmh", ge=0, le=200)
    weight: float = Field(default=0, ge=0, le=2_000)
    bodyweight: bool | None = None
    per_side: bool = Field(default=False, alias="perSide")
    rest_seconds: int | None = Field(default=None, alias="restSeconds", ge=5, le=3_600)
    superset_id: str | None = Field(default=None, alias="supersetId", max_length=100)
    progression: Progression | None = None
    increment: float | None = Field(default=None, ge=0, le=500)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def validate_rep_range(self) -> "RoutineExercisePayload":
        if self.reps_min is not None and self.reps_max is not None and self.reps_min > self.reps_max:
            raise ValueError("repsMin cannot exceed repsMax")
        return self


class StrengthRoutinePayload(BaseModel):
    id: UUID
    name: str = Field(min_length=1, max_length=120)
    symbol_name: str = Field(default="dumbbell", alias="symbolName", max_length=100)
    progression: Progression = "linear"
    exercises: list[RoutineExercisePayload] = Field(default_factory=list, max_length=100)

    model_config = {"populate_by_name": True}

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value


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


class WorkoutSetPayload(BaseModel):
    id: UUID
    weight: float = Field(default=0, ge=0, le=2_000)
    reps: int = Field(default=0, ge=0, le=1_000)
    seconds: int = Field(default=0, ge=0, le=86_400)
    minutes: int = Field(default=0, ge=0, le=1_440)
    speed_kmh: float = Field(default=0, alias="speedKmh", ge=0, le=200)
    done: bool = True

    model_config = {"populate_by_name": True}


class WorkoutEntryPayload(BaseModel):
    id: UUID
    exercise_id: str = Field(alias="exerciseId", min_length=1, max_length=100)
    target: RoutineExercisePayload
    sets: list[WorkoutSetPayload] = Field(min_length=1, max_length=100)

    model_config = {"populate_by_name": True}


class StrengthWorkoutPayload(BaseModel):
    id: UUID
    workout_date: date = Field(alias="date")
    name: str = Field(min_length=1, max_length=120)
    started_at: datetime = Field(alias="startedAt")
    ended_at: datetime = Field(alias="endedAt")
    routine_id: UUID | None = Field(default=None, alias="routineId")
    entries: list[WorkoutEntryPayload] = Field(min_length=1, max_length=100)

    model_config = {"populate_by_name": True}

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @model_validator(mode="after")
    def validate_workout(self) -> "StrengthWorkoutPayload":
        if self.ended_at < self.started_at:
            raise ValueError("endedAt must be on or after startedAt")
        if not any(workout_set.done for entry in self.entries for workout_set in entry.sets):
            raise ValueError("workout must contain a completed set")
        return self


class StrengthWorkoutResponse(StrengthWorkoutPayload):
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}


class StrengthWorkoutSummary(BaseModel):
    id: UUID
    date: date
    name: str
    started_at: datetime = Field(alias="startedAt")
    ended_at: datetime = Field(alias="endedAt")
    exercise_count: int = Field(alias="exerciseCount")

    model_config = {"populate_by_name": True}


class StrengthWorkoutPage(BaseModel):
    items: list[StrengthWorkoutSummary]
    next_offset: int | None = Field(alias="nextOffset")

    model_config = {"populate_by_name": True}


class StrengthBootstrapResponse(BaseModel):
    weight_unit: WeightUnit = Field(alias="weightUnit")
    routines: list[StrengthRoutineResponse]
    week: list[StrengthWeekAssignmentResponse]

    model_config = {"populate_by_name": True}


class StrengthHeatmapDay(BaseModel):
    day: date
    workout_count: int = Field(alias="workoutCount")
    duration_minutes: int = Field(alias="durationMinutes")
    level: int

    model_config = {"populate_by_name": True}


class StrengthAnalyticsOverview(BaseModel):
    total_workouts: int = Field(alias="totalWorkouts")
    workouts_this_month: int = Field(alias="workoutsThisMonth")
    routine_count: int = Field(alias="routineCount")
    heatmap: list[StrengthHeatmapDay]

    model_config = {"populate_by_name": True}


class StrengthMuscleLoad(BaseModel):
    muscle: str
    load: float


class StrengthRecord(BaseModel):
    exercise_id: str = Field(alias="exerciseId")
    exercise_name: str = Field(alias="exerciseName")
    weight_kg: float = Field(alias="weightKg")
    reps: int
    date: datetime
    estimated_one_rm_kg: float | None = Field(alias="estimatedOneRmKg")

    model_config = {"populate_by_name": True}


class StrengthOneRmPoint(BaseModel):
    date: datetime
    estimate_kg: float = Field(alias="estimateKg")
    weight_kg: float = Field(alias="weightKg")
    reps: int

    model_config = {"populate_by_name": True}


class StrengthOneRmExercise(BaseModel):
    exercise_id: str = Field(alias="exerciseId")
    exercise_name: str = Field(alias="exerciseName")
    points: list[StrengthOneRmPoint]

    model_config = {"populate_by_name": True}
