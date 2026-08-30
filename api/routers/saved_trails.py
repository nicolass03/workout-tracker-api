from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import CurrentUser, get_current_user
from api.database import get_db
from api.models import SavedTrail, SessionRoute, WorkoutSession
from api.schemas.saved_trails import SavedTrailCreate, SavedTrailResponse, SavedTrailSummary

router = APIRouter(prefix="/saved-trails", tags=["saved-trails"])
_MAX_SAVED_TRAILS = 50


def _public_status(value: str) -> str:
    return {
        "gps_only": "gpsOnly",
        "partially_matched": "partiallyMatched",
        "matched": "matched",
    }[value]


def _summary(row: SavedTrail) -> SavedTrailSummary:
    return SavedTrailSummary(
        id=row.id,
        source_session_id=row.source_session_id,
        name=row.name,
        activity_type=row.activity_type,
        distance_meters=row.distance_meters,
        confidence=row.confidence,
        graph_version=row.graph_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _response(row: SavedTrail) -> SavedTrailResponse:
    return SavedTrailResponse(
        **_summary(row).model_dump(),
        source_route_revision=row.source_route_revision,
        algorithm_version=row.algorithm_version,
        status=_public_status(row.status),
        sections=row.sections,
    )


@router.post("", response_model=SavedTrailResponse, status_code=status.HTTP_201_CREATED)
async def save_trail(
    body: SavedTrailCreate,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SavedTrailResponse:
    user_id = UUID(user.id)
    session = await db.scalar(
        select(WorkoutSession).where(
            WorkoutSession.id == body.source_session_id,
            WorkoutSession.user_id == user_id,
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    route = await db.scalar(
        select(SessionRoute)
        .where(SessionRoute.session_id == session.id, SessionRoute.user_id == user_id)
        .order_by(SessionRoute.revision.desc())
        .limit(1)
    )
    if route is None:
        raise HTTPException(status_code=409, detail="Session route is not ready")

    row = await db.scalar(
        select(SavedTrail).where(
            SavedTrail.user_id == user_id,
            SavedTrail.source_session_id == session.id,
        )
    )
    if row is None:
        count = await db.scalar(
            select(func.count()).select_from(SavedTrail).where(SavedTrail.user_id == user_id)
        )
        if (count or 0) >= _MAX_SAVED_TRAILS:
            raise HTTPException(status_code=409, detail="Saved trail limit reached")
        row = SavedTrail(id=uuid4(), user_id=user_id, source_session_id=session.id)
        db.add(row)

    row.name = body.name
    row.activity_type = session.type
    row.source_route_revision = route.revision
    row.algorithm_version = route.algorithm_version
    row.graph_version = route.graph_version
    row.status = route.status
    row.confidence = route.confidence
    row.distance_meters = route.distance_meters
    row.sections = route.sections
    await db.commit()
    await db.refresh(row)
    return _response(row)


@router.get("", response_model=list[SavedTrailSummary])
async def list_saved_trails(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SavedTrailSummary]:
    result = await db.execute(
        select(SavedTrail)
        .where(SavedTrail.user_id == UUID(user.id))
        .order_by(SavedTrail.updated_at.desc())
    )
    return [_summary(row) for row in result.scalars().all()]


@router.get("/{trail_id}", response_model=SavedTrailResponse)
async def get_saved_trail(
    trail_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SavedTrailResponse:
    row = await db.scalar(
        select(SavedTrail).where(
            SavedTrail.id == trail_id,
            SavedTrail.user_id == UUID(user.id),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Saved trail not found")
    return _response(row)


@router.delete("/{trail_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_trail(
    trail_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await db.scalar(
        select(SavedTrail).where(
            SavedTrail.id == trail_id,
            SavedTrail.user_id == UUID(user.id),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Saved trail not found")
    await db.delete(row)
    await db.commit()
