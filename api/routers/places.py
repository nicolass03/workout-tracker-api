from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import CurrentUser, get_current_user
from api.database import get_db
from api.models import FrequentPlace
from api.schemas.places import (
    FrequentPlaceCreate,
    FrequentPlaceResponse,
    FrequentPlaceUpdate,
)

router = APIRouter(prefix="/places", tags=["places"])

_MAX_PLACES_PER_USER = 20


def _to_response(row: FrequentPlace) -> FrequentPlaceResponse:
    return FrequentPlaceResponse.model_validate(row)


@router.get("", response_model=list[FrequentPlaceResponse])
async def list_places(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[FrequentPlaceResponse]:
    user_id = UUID(user.id)
    result = await session.execute(
        select(FrequentPlace)
        .where(FrequentPlace.user_id == user_id)
        .order_by(FrequentPlace.created_at.asc())
    )
    return [_to_response(row) for row in result.scalars().all()]


@router.post("", response_model=FrequentPlaceResponse, status_code=status.HTTP_201_CREATED)
async def create_place(
    body: FrequentPlaceCreate,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> FrequentPlaceResponse:
    user_id = UUID(user.id)
    count_result = await session.execute(
        select(func.count()).select_from(FrequentPlace).where(FrequentPlace.user_id == user_id)
    )
    count = int(count_result.scalar_one())
    if count >= _MAX_PLACES_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Maximum of {_MAX_PLACES_PER_USER} frequent places allowed",
        )

    place_id = body.id or uuid4()
    if body.id is not None:
        existing = await session.execute(
            select(FrequentPlace).where(FrequentPlace.id == place_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Place with this id already exists",
            )

    row = FrequentPlace(
        id=place_id,
        user_id=user_id,
        name=body.name.strip(),
        latitude=body.latitude,
        longitude=body.longitude,
        radius_meters=body.radius_meters,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.put("/{place_id}", response_model=FrequentPlaceResponse)
async def update_place(
    place_id: UUID,
    body: FrequentPlaceUpdate,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> FrequentPlaceResponse:
    user_id = UUID(user.id)
    result = await session.execute(
        select(FrequentPlace).where(
            FrequentPlace.id == place_id,
            FrequentPlace.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Place not found",
        )

    row.name = body.name.strip()
    row.latitude = body.latitude
    row.longitude = body.longitude
    row.radius_meters = body.radius_meters
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.delete("/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_place(
    place_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    user_id = UUID(user.id)
    result = await session.execute(
        select(FrequentPlace).where(
            FrequentPlace.id == place_id,
            FrequentPlace.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Place not found",
        )
    await session.delete(row)
    await session.commit()
