import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
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


class StrengthState(Base):
    __tablename__ = "strength_state"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    client_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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
    exercises: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class StrengthWorkout(Base):
    __tablename__ = "strength_workouts"
    __table_args__ = (
        CheckConstraint("ended_at >= started_at", name="ck_strength_workouts_ended_after_start"),
        CheckConstraint("char_length(btrim(name)) > 0", name="ck_strength_workouts_name_nonempty"),
        CheckConstraint("jsonb_typeof(entries) = 'array'", name="ck_strength_workouts_entries_array"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    workout_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entries: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


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
