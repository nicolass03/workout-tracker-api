from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import CurrentUser, get_current_user
from api.database import get_db
from api.models import StrengthRoutine, StrengthState, StrengthWeekAssignment
from api.schemas.strength import (
    StrengthRoutinePayload,
    StrengthRoutineResponse,
    StrengthStateEnvelope,
    StrengthStateResponse,
    StrengthWeekAssignmentPayload,
    StrengthWeekAssignmentResponse,
)

router = APIRouter(prefix="/strength", tags=["strength"])


def _response(row: StrengthState) -> StrengthStateResponse:
    return StrengthStateResponse(
        schemaVersion=1,
        clientUpdatedAt=row.client_updated_at,
        state=row.state,
        updatedAt=row.updated_at,
    )


def _routine_response(row: StrengthRoutine) -> StrengthRoutineResponse:
    return StrengthRoutineResponse(
        id=row.id,
        name=row.name,
        symbolName=row.symbol_name,
        progression=row.progression,
        exercises=row.exercises if isinstance(row.exercises, list) else [],
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


def _assignment_response(row: StrengthWeekAssignment) -> StrengthWeekAssignmentResponse:
    return StrengthWeekAssignmentResponse(
        weekday=row.weekday,
        routineId=row.routine_id,
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


@router.get("/routines", response_model=list[StrengthRoutineResponse])
async def list_strength_routines(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StrengthRoutineResponse]:
    user_id = UUID(user.id)
    result = await db.execute(
        select(StrengthRoutine)
        .where(StrengthRoutine.user_id == user_id)
        .order_by(StrengthRoutine.created_at.asc())
    )
    return [_routine_response(row) for row in result.scalars().all()]


@router.put("/routines/{routine_id}", response_model=StrengthRoutineResponse)
async def put_strength_routine(
    routine_id: UUID,
    body: StrengthRoutinePayload,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrengthRoutineResponse:
    if body.id != routine_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Routine id must match the route id",
        )

    user_id = UUID(user.id)
    result = await db.execute(
        select(StrengthRoutine).where(
            StrengthRoutine.id == routine_id,
            StrengthRoutine.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if row is None:
        row = StrengthRoutine(
            id=routine_id,
            user_id=user_id,
            name=body.name,
            symbol_name=body.symbol_name,
            progression=body.progression,
            exercises=body.exercises,
            updated_at=now,
        )
        db.add(row)
    else:
        row.name = body.name
        row.symbol_name = body.symbol_name
        row.progression = body.progression
        row.exercises = body.exercises
        row.updated_at = now

    await db.commit()
    await db.refresh(row)
    return _routine_response(row)


@router.delete("/routines/{routine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strength_routine(
    routine_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    user_id = UUID(user.id)
    result = await db.execute(
        select(StrengthRoutine).where(
            StrengthRoutine.id == routine_id,
            StrengthRoutine.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")

    assignments = await db.execute(
        select(StrengthWeekAssignment).where(
            StrengthWeekAssignment.user_id == user_id,
            StrengthWeekAssignment.routine_id == routine_id,
        )
    )
    for assignment in assignments.scalars().all():
        assignment.routine_id = None
        assignment.updated_at = datetime.now(timezone.utc)

    await db.delete(row)
    await db.commit()


@router.get("/week", response_model=list[StrengthWeekAssignmentResponse])
async def list_strength_week_assignments(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StrengthWeekAssignmentResponse]:
    user_id = UUID(user.id)
    result = await db.execute(
        select(StrengthWeekAssignment)
        .where(StrengthWeekAssignment.user_id == user_id)
        .order_by(StrengthWeekAssignment.weekday.asc())
    )
    return [_assignment_response(row) for row in result.scalars().all()]


@router.put("/week/{weekday}", response_model=StrengthWeekAssignmentResponse)
async def put_strength_week_assignment(
    weekday: int,
    body: StrengthWeekAssignmentPayload,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrengthWeekAssignmentResponse:
    if weekday < 0 or weekday > 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="weekday must be between 0 and 6",
        )

    user_id = UUID(user.id)
    routine_id = body.routine_id
    if routine_id is not None:
        routine_result = await db.execute(
            select(StrengthRoutine.id).where(
                StrengthRoutine.id == routine_id,
                StrengthRoutine.user_id == user_id,
            )
        )
        if routine_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")

    result = await db.execute(
        select(StrengthWeekAssignment).where(
            StrengthWeekAssignment.user_id == user_id,
            StrengthWeekAssignment.weekday == weekday,
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = StrengthWeekAssignment(
            user_id=user_id,
            weekday=weekday,
            routine_id=routine_id,
            updated_at=now,
        )
        db.add(row)
    else:
        row.routine_id = routine_id
        row.updated_at = now

    await db.commit()
    await db.refresh(row)
    return _assignment_response(row)
