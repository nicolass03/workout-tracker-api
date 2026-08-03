from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import CurrentUser, get_current_user
from api.database import get_db
from api.models import DailyActivity
from api.schemas.activity import DailyActivityResponse, DailyActivityUpsert, TrailPoint

router = APIRouter(prefix="/activity", tags=["activity"])


def _trail_to_json(points: list[TrailPoint]) -> list[dict]:
    return [
        {"lat": p.lat, "lon": p.lon, "t": p.t.isoformat()}
        for p in points
    ]


def _trail_from_json(raw: list | None) -> list[TrailPoint]:
    if not raw:
        return []
    return [TrailPoint.model_validate(item) for item in raw]


def _to_response(row: DailyActivity) -> DailyActivityResponse:
    return DailyActivityResponse(
        id=row.id,
        user_id=row.user_id,
        day=row.day,
        steps=row.steps,
        active_energy_kcal=row.active_energy_kcal,
        distance_meters=row.distance_meters,
        trail=_trail_from_json(row.trail if isinstance(row.trail, list) else []),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.put("/days/{day}", response_model=DailyActivityResponse)
async def upsert_daily_activity(
    day: date,
    body: DailyActivityUpsert,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> DailyActivityResponse:
    user_id = UUID(user.id)
    result = await session.execute(
        select(DailyActivity).where(
            DailyActivity.user_id == user_id,
            DailyActivity.day == day,
        )
    )
    row = result.scalar_one_or_none()
    trail_json = _trail_to_json(body.trail)

    if row is None:
        row = DailyActivity(
            user_id=user_id,
            day=day,
            steps=body.steps,
            active_energy_kcal=body.active_energy_kcal,
            distance_meters=body.distance_meters,
            trail=trail_json,
        )
        session.add(row)
    else:
        row.steps = body.steps
        row.active_energy_kcal = body.active_energy_kcal
        row.distance_meters = body.distance_meters
        row.trail = trail_json

    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.get("/days/{day}", response_model=DailyActivityResponse)
async def get_daily_activity(
    day: date,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> DailyActivityResponse:
    user_id = UUID(user.id)
    result = await session.execute(
        select(DailyActivity).where(
            DailyActivity.user_id == user_id,
            DailyActivity.day == day,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No activity for this day",
        )
    return _to_response(row)
