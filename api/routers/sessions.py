from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.auth import CurrentUser, get_current_user
from api.database import get_db
from api.models import SessionSegment, WorkoutSession
from api.schemas.sessions import (
    SegmentPoint,
    SessionSegmentResponse,
    WalkRunSessionCreate,
    WalkRunSessionResponse,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])

_MAX_RANGE_DAYS = 62
# Pad UTC day bounds so local-calendar days near midnight are not missed; clients
# still group/filter by their own Calendar day.
_TZ_PAD = timedelta(hours=14)


def _points_to_json(points: list[SegmentPoint]) -> list[dict]:
    return [{"lat": p.lat, "lon": p.lon, "t": p.t.isoformat()} for p in points]


def _points_from_json(raw: list | None) -> list[SegmentPoint]:
    if not raw:
        return []
    return [SegmentPoint.model_validate(item) for item in raw]


def _to_response(row: WorkoutSession) -> WalkRunSessionResponse:
    if row.type != "walk_run":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported session type: {row.type}",
        )
    if row.steps is None or row.distance_meters is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="walk_run session missing steps/distance",
        )
    segments = [
        SessionSegmentResponse(
            id=seg.id,
            idx=seg.idx,
            started_at=seg.started_at,
            ended_at=seg.ended_at,
            steps=seg.steps,
            points=_points_from_json(seg.points if isinstance(seg.points, list) else []),
        )
        for seg in sorted(row.segments, key=lambda s: s.idx)
    ]
    return WalkRunSessionResponse(
        id=row.id,
        user_id=row.user_id,
        type="walk_run",
        started_at=row.started_at,
        ended_at=row.ended_at,
        active_duration_seconds=row.active_duration_seconds,
        active_energy_kcal=row.active_energy_kcal,
        steps=row.steps,
        distance_meters=row.distance_meters,
        segments=segments,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc) - _TZ_PAD
    end = datetime.combine(day, time.max, tzinfo=timezone.utc) + _TZ_PAD
    return start, end


@router.post("", response_model=WalkRunSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: WalkRunSessionCreate,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WalkRunSessionResponse:
    user_id = UUID(user.id)
    session_id = body.id or uuid4()

    if body.id is not None:
        existing = await db.execute(
            select(WorkoutSession)
            .where(WorkoutSession.id == session_id)
            .options(selectinload(WorkoutSession.segments))
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            if row.user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Session with this id already exists",
                )
            return _to_response(row)

    row = WorkoutSession(
        id=session_id,
        user_id=user_id,
        type=body.type,
        started_at=body.started_at,
        ended_at=body.ended_at,
        active_duration_seconds=body.active_duration_seconds,
        active_energy_kcal=body.active_energy_kcal,
        steps=body.steps,
        distance_meters=body.distance_meters,
    )
    for seg in body.segments:
        row.segments.append(
            SessionSegment(
                id=seg.id or uuid4(),
                idx=seg.idx,
                started_at=seg.started_at,
                ended_at=seg.ended_at,
                steps=seg.steps,
                points=_points_to_json(seg.points),
            )
        )
    db.add(row)
    await db.commit()

    result = await db.execute(
        select(WorkoutSession)
        .where(WorkoutSession.id == session_id)
        .options(selectinload(WorkoutSession.segments))
    )
    saved = result.scalar_one()
    return _to_response(saved)


@router.get("", response_model=list[WalkRunSessionResponse])
async def list_sessions(
    from_day: date = Query(..., alias="from"),
    to_day: date = Query(..., alias="to"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WalkRunSessionResponse]:
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
    range_start, _ = _day_bounds_utc(from_day)
    _, range_end = _day_bounds_utc(to_day)

    result = await db.execute(
        select(WorkoutSession)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.started_at >= range_start,
            WorkoutSession.started_at <= range_end,
        )
        .options(selectinload(WorkoutSession.segments))
        .order_by(WorkoutSession.started_at.asc())
    )
    return [_to_response(row) for row in result.scalars().unique().all()]


@router.get("/{session_id}", response_model=WalkRunSessionResponse)
async def get_session(
    session_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WalkRunSessionResponse:
    user_id = UUID(user.id)
    result = await db.execute(
        select(WorkoutSession)
        .where(WorkoutSession.id == session_id, WorkoutSession.user_id == user_id)
        .options(selectinload(WorkoutSession.segments))
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return _to_response(row)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    user_id = UUID(user.id)
    result = await db.execute(
        select(WorkoutSession).where(
            WorkoutSession.id == session_id, WorkoutSession.user_id == user_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    await db.delete(row)
    await db.commit()
