import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DailyActivity(Base):
    __tablename__ = "daily_activity"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_daily_activity_user_day"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
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
