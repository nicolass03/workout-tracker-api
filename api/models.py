import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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
