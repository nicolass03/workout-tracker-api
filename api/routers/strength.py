from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import CurrentUser, get_current_user
from api.database import get_db
from api.models import StrengthState
from api.schemas.strength import StrengthStateEnvelope, StrengthStateResponse

router = APIRouter(prefix="/strength", tags=["strength"])


def _response(row: StrengthState) -> StrengthStateResponse:
    return StrengthStateResponse(
        schemaVersion=1,
        clientUpdatedAt=row.client_updated_at,
        state=row.state,
        updatedAt=row.updated_at,
    )


@router.get("/state", response_model=StrengthStateResponse | None)
async def get_strength_state(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrengthStateResponse | None:
    result = await db.execute(
        select(StrengthState).where(StrengthState.user_id == UUID(user.id))
    )
    row = result.scalar_one_or_none()
    return _response(row) if row else None


@router.put("/state", response_model=StrengthStateResponse)
async def put_strength_state(
    body: StrengthStateEnvelope,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrengthStateResponse:
    user_id = UUID(user.id)
    result = await db.execute(select(StrengthState).where(StrengthState.user_id == user_id))
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if row is None:
        row = StrengthState(
            user_id=user_id,
            state=body.state,
            client_updated_at=body.client_updated_at,
            updated_at=now,
        )
        db.add(row)
    elif body.client_updated_at >= row.client_updated_at:
        row.state = body.state
        row.client_updated_at = body.client_updated_at
        row.updated_at = now

    await db.commit()
    await db.refresh(row)
    return _response(row)
