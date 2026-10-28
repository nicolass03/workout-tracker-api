from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import CurrentUser, get_current_user
from api.cache import response_cache
from api.database import get_db
from api.models import StrengthRoutine, StrengthWorkout

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict[str, str | None]:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
    }


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete the caller's account; user-owned rows cascade from auth.users."""
    user_id = UUID(user.id)
    # Workouts and routines RESTRICT-reference the user's custom exercises, which the
    # auth.users cascade deletes in trigger-name order; removing them first keeps it deterministic.
    await db.execute(delete(StrengthWorkout).where(StrengthWorkout.user_id == user_id))
    await db.execute(delete(StrengthRoutine).where(StrengthRoutine.user_id == user_id))
    await db.execute(text("DELETE FROM auth.users WHERE id = :id"), {"id": user_id})
    await db.commit()
    await response_cache.invalidate_user(user.id)
