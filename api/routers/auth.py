from fastapi import APIRouter, Depends

from api.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict[str, str | None]:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
    }
