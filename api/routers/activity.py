from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import CurrentUser, get_current_user
from api.database import get_db
from api.models import DailyActivity
from api.schemas.activity import (
    DailyActivityResponse,
    DailyActivityUpsert,
    TrailPoint,
)

router = APIRouter(prefix="/activity", tags=["activity"])

_MAX_RANGE_DAYS = 62


def _trail_to_json(points: list[TrailPoint]) -> list[dict]:
    payload: list[dict] = []
    for p in points:
        item: dict = {"lat": p.lat, "lon": p.lon, "t": p.t.isoformat(), "seg": p.seg}
        if p.seg_steps is not None:
            item["seg_steps"] = p.seg_steps
        payload.append(item)
    return payload


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


@router.get("/days", response_model=list[DailyActivityResponse])
async def list_daily_activity(
    from_day: date = Query(..., alias="from"),
    to_day: date = Query(..., alias="to"),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[DailyActivityResponse]:
    if from_day > to_day:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'from' must be on or before 'to'",
        )
    if (to_day - from_day).days + 1 > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Range cannot exceed {_MAX_RANGE_DAYS} days",
        )

    user_id = UUID(user.id)
    result = await session.execute(
        select(DailyActivity)
        .where(
            DailyActivity.user_id == user_id,
            DailyActivity.day >= from_day,
            DailyActivity.day <= to_day,
        )
        .order_by(DailyActivity.day.asc())
    )
    rows = result.scalars().all()
    return [_to_response(row) for row in rows]


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
