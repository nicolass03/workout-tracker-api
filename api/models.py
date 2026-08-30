import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class WorkoutSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("ended_at >= started_at", name="ck_sessions_ended_after_start"),
        CheckConstraint("active_duration_seconds >= 0", name="ck_sessions_active_duration_nonneg"),
        CheckConstraint("active_energy_kcal >= 0", name="ck_sessions_energy_nonneg"),
        CheckConstraint("steps IS NULL OR steps >= 0", name="ck_sessions_steps_nonneg"),
        CheckConstraint(
            "distance_meters IS NULL OR distance_meters >= 0",
            name="ck_sessions_distance_nonneg",
        ),
        CheckConstraint(
            "type <> 'walk_run' OR (steps IS NOT NULL AND distance_meters IS NOT NULL)",
            name="ck_sessions_walk_run_fields",
        ),
        CheckConstraint(
            "type NOT IN ('walk_run', 'walk', 'run', 'jogging', 'hiking') "
            "OR (steps IS NOT NULL AND distance_meters IS NOT NULL)",
            name="ck_sessions_move_fields",
        ),
        CheckConstraint(
            "elevation_gain_meters IS NULL OR elevation_gain_meters >= 0",
            name="ck_sessions_elevation_gain_nonneg",
        ),
        CheckConstraint(
            "elevation_loss_meters IS NULL OR elevation_loss_meters >= 0",
            name="ck_sessions_elevation_loss_nonneg",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active_duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    active_energy_kcal: Mapped[float] = mapped_column(Float, nullable=False)
    steps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    distance_meters: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    elevation_gain_meters: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    elevation_loss_meters: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    elevation_samples: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    segments: Mapped[list["SessionSegment"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionSegment.idx",
    )


class SessionSegment(Base):
    __tablename__ = "session_segments"
    __table_args__ = (
        UniqueConstraint("session_id", "idx", name="uq_session_segments_session_idx"),
        CheckConstraint("idx >= 0", name="ck_session_segments_idx_nonneg"),
        CheckConstraint("steps >= 0", name="ck_session_segments_steps_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    points: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped["WorkoutSession"] = relationship(back_populates="segments")


class SessionTraceChunk(Base):
    __tablename__ = "session_trace_chunks"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "kind", "section_index", "chunk_index",
            name="uq_session_trace_chunk",
        ),
        CheckConstraint("section_index >= 0", name="ck_session_trace_chunk_section_nonneg"),
        CheckConstraint("chunk_index >= 0", name="ck_session_trace_chunk_index_nonneg"),
        CheckConstraint("sample_count > 0", name="ck_session_trace_chunk_count_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="location")
    section_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    samples: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SessionRoute(Base):
    __tablename__ = "session_routes"
    __table_args__ = (
        UniqueConstraint("session_id", "revision", name="uq_session_routes_revision"),
        CheckConstraint("revision >= 1", name="ck_session_routes_revision_positive"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_session_routes_confidence"),
        CheckConstraint("distance_meters >= 0", name="ck_session_routes_distance_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    graph_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    distance_meters: Mapped[float] = mapped_column(Float, nullable=False)
    quality: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    sections: Mapped[list] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SavedTrail(Base):
    __tablename__ = "saved_trails"
    __table_args__ = (
        CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 100", name="ck_saved_trails_name"),
        CheckConstraint("source_route_revision >= 1", name="ck_saved_trails_revision"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_saved_trails_confidence"),
        CheckConstraint("distance_meters >= 0", name="ck_saved_trails_distance"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    activity_type: Mapped[str] = mapped_column(String, nullable=False)
    source_route_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    graph_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    distance_meters: Mapped[float] = mapped_column(Float, nullable=False)
    sections: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class FrequentPlace(Base):
    __tablename__ = "frequent_places"
    __table_args__ = (
        CheckConstraint(
            "radius_meters >= 10 AND radius_meters <= 250",
            name="ck_frequent_places_radius",
        ),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_frequent_places_lat"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_frequent_places_lon"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    radius_meters: Mapped[float] = mapped_column(
        Float, nullable=False, default=150.0, server_default="150"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class StrengthRoutine(Base):
    __tablename__ = "strength_routines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    symbol_name: Mapped[str] = mapped_column(String, nullable=False, default="dumbbell")
    progression: Mapped[str] = mapped_column(String, nullable=False, default="linear")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class StrengthExercise(Base):
    __tablename__ = "strength_exercises"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    body_part: Mapped[str] = mapped_column(String, nullable=False, default="")
    equipment: Mapped[str] = mapped_column(String, nullable=False, default="")
    target_muscle: Mapped[str] = mapped_column(String, nullable=False, default="")
    image_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    gif_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_catalog: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class StrengthExerciseInstruction(Base):
    __tablename__ = "strength_exercise_instructions"

    exercise_id: Mapped[str] = mapped_column(ForeignKey("strength_exercises.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    instruction: Mapped[str] = mapped_column(String, nullable=False)


class StrengthExerciseMuscle(Base):
    __tablename__ = "strength_exercise_muscles"

    exercise_id: Mapped[str] = mapped_column(ForeignKey("strength_exercises.id", ondelete="CASCADE"), primary_key=True)
    muscle_key: Mapped[str] = mapped_column(String, primary_key=True)
    load_factor: Mapped[float] = mapped_column(Numeric(4, 2, asdecimal=False), nullable=False)


class StrengthPreference(Base):
    __tablename__ = "strength_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    weight_unit: Mapped[str] = mapped_column(String, nullable=False, default="kg")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class StrengthBodyweight(Base):
    __tablename__ = "strength_bodyweights"
    __table_args__ = (UniqueConstraint("user_id", "measured_on", name="uq_strength_bodyweights_user_day"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    measured_on: Mapped[date] = mapped_column(Date, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Numeric(7, 3, asdecimal=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class StrengthRoutineExercise(Base):
    __tablename__ = "strength_routine_exercises"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    routine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strength_routines.id", ondelete="CASCADE"), nullable=False, index=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("strength_exercises.id", ondelete="RESTRICT"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    target_sets: Mapped[int] = mapped_column(Integer, nullable=False)
    target_reps: Mapped[int] = mapped_column(Integer, nullable=False)
    reps_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reps_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    target_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    target_speed_kmh: Mapped[float] = mapped_column(Numeric(7, 3, asdecimal=False), nullable=False)
    target_weight_kg: Mapped[float] = mapped_column(Numeric(8, 3, asdecimal=False), nullable=False)
    is_bodyweight: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    per_side: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rest_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    superset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    progression: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    increment_kg: Mapped[Optional[float]] = mapped_column(Numeric(8, 3, asdecimal=False), nullable=True)


class StrengthWorkout(Base):
    __tablename__ = "strength_workouts"
    __table_args__ = (
        CheckConstraint("ended_at >= started_at", name="ck_strength_workouts_ended_after_start"),
        CheckConstraint("char_length(btrim(name)) > 0", name="ck_strength_workouts_name_nonempty"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    workout_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    routine_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strength_routines.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class StrengthWorkoutExercise(Base):
    __tablename__ = "strength_workout_exercises"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workout_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strength_workouts.id", ondelete="CASCADE"), nullable=False, index=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("strength_exercises.id", ondelete="RESTRICT"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    is_bodyweight: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    per_side: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class StrengthWorkoutSet(Base):
    __tablename__ = "strength_workout_sets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workout_exercise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strength_workout_exercises.id", ondelete="CASCADE"), nullable=False, index=True)
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[Optional[float]] = mapped_column(Numeric(8, 3, asdecimal=False), nullable=True)
    reps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    speed_kmh: Mapped[Optional[float]] = mapped_column(Numeric(7, 3, asdecimal=False), nullable=True)


class StrengthWeekAssignment(Base):
    __tablename__ = "strength_week_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "weekday", name="uq_strength_week_assignments_user_weekday"),
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_strength_week_assignments_weekday"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    routine_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strength_routines.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DailyActivity(Base):
    __tablename__ = "daily_activity"
    __table_args__ = (
        UniqueConstraint("user_id", "day", name="uq_daily_activity_user_day"),
        CheckConstraint("steps >= 0", name="ck_daily_activity_steps_nonneg"),
        CheckConstraint("active_energy_kcal >= 0", name="ck_daily_activity_energy_nonneg"),
        CheckConstraint("distance_meters >= 0", name="ck_daily_activity_distance_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Indexed via uq_daily_activity_user_day (user_id, day); no standalone user_id index.
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    active_energy_kcal: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    distance_meters: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    trail: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
