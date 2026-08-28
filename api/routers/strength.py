from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Float, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import CurrentUser, get_current_user
from api.config import get_settings
from api.database import get_db
from api.models import (
    StrengthExercise,
    StrengthExerciseInstruction,
    StrengthExerciseMuscle,
    StrengthPreference,
    StrengthRoutine,
    StrengthRoutineExercise,
    StrengthWeekAssignment,
    StrengthWorkout,
    StrengthWorkoutExercise,
    StrengthWorkoutSet,
)
from api.schemas.strength import (
    ExercisePage,
    ExerciseResponse,
    RoutineExercisePayload,
    StrengthAnalyticsOverview,
    StrengthBootstrapResponse,
    StrengthHeatmapDay,
    StrengthMuscleLoad,
    StrengthOneRmExercise,
    StrengthOneRmPoint,
    StrengthRecord,
    StrengthRoutinePayload,
    StrengthRoutineResponse,
    StrengthWeekAssignmentPayload,
    StrengthWeekAssignmentResponse,
    StrengthWorkoutPage,
    StrengthWorkoutPayload,
    StrengthWorkoutResponse,
    StrengthWorkoutSummary,
    WorkoutEntryPayload,
    WorkoutSetPayload,
)

router = APIRouter(prefix="/strength", tags=["strength"])

_LB_PER_KG = 2.2046226218
_ONE_RM_REP_CAP = 12


def _to_kg(value: float, unit: str) -> float:
    return value / _LB_PER_KG if unit == "lb" else value


def _from_kg(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    return value * _LB_PER_KG if unit == "lb" else value


def _round(value: float) -> float:
    return round(value, 3)


def _estimate_one_rm(weight_kg: float, reps: int) -> float | None:
    if weight_kg <= 0 or reps < 1 or reps > _ONE_RM_REP_CAP:
        return None
    return round(weight_kg if reps == 1 else weight_kg * (1 + reps / 30), 1)


def _media_url(key: str | None) -> str | None:
    if not key:
        return None
    return f"{get_settings().resolved_media_base_url}/{key.lstrip('/')}"


async def _preference(
    db: AsyncSession, user_id: UUID, *, create: bool = False
) -> StrengthPreference:
    result = await db.execute(select(StrengthPreference).where(StrengthPreference.user_id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        row = StrengthPreference(user_id=user_id, weight_unit="kg")
        if create:
            db.add(row)
            await db.flush()
    return row


async def _exercise_maps(
    db: AsyncSession, exercise_ids: list[str]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    if not exercise_ids:
        return {}, {}
    instruction_result = await db.execute(
        select(StrengthExerciseInstruction)
        .where(StrengthExerciseInstruction.exercise_id.in_(exercise_ids))
        .order_by(StrengthExerciseInstruction.exercise_id, StrengthExerciseInstruction.position)
    )
    muscle_result = await db.execute(
        select(StrengthExerciseMuscle)
        .where(StrengthExerciseMuscle.exercise_id.in_(exercise_ids))
        .order_by(StrengthExerciseMuscle.exercise_id, StrengthExerciseMuscle.load_factor.desc())
    )
    instructions: dict[str, list[str]] = defaultdict(list)
    muscles: dict[str, list[str]] = defaultdict(list)
    for row in instruction_result.scalars().all():
        instructions[row.exercise_id].append(row.instruction)
    for row in muscle_result.scalars().all():
        muscles[row.exercise_id].append(row.muscle_key)
    return instructions, muscles


def _exercise_response(
    row: StrengthExercise,
    instructions: list[str] | None = None,
    muscles: list[str] | None = None,
) -> ExerciseResponse:
    primary = row.target_muscle or (muscles[0] if muscles else None)
    return ExerciseResponse(
        id=row.id,
        n=row.name,
        bp=row.body_part,
        eq=row.equipment,
        tg=row.target_muscle,
        mg=primary,
        sm=muscles or [],
        st=instructions or [],
        img=_media_url(row.image_key),
        gif=_media_url(row.gif_key),
    )


async def _require_exercises(
    db: AsyncSession, user_id: UUID, exercise_ids: set[str]
) -> None:
    if not exercise_ids:
        return
    result = await db.execute(
        select(StrengthExercise.id).where(
            StrengthExercise.id.in_(exercise_ids),
            StrengthExercise.archived_at.is_(None),
            or_(StrengthExercise.is_catalog.is_(True), StrengthExercise.owner_user_id == user_id),
        )
    )
    found = set(result.scalars().all())
    if found != exercise_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="One or more exercises are unavailable",
        )


def _routine_item_response(row: StrengthRoutineExercise, unit: str) -> RoutineExercisePayload:
    return RoutineExercisePayload(
        id=row.id,
        exerciseId=row.exercise_id,
        mode=row.mode,
        sets=row.target_sets,
        reps=row.target_reps,
        repsMin=row.reps_min,
        repsMax=row.reps_max,
        seconds=row.target_seconds,
        minutes=row.target_minutes,
        speedKmh=float(row.target_speed_kmh),
        weight=_round(_from_kg(float(row.target_weight_kg), unit) or 0),
        bodyweight=row.is_bodyweight,
        perSide=row.per_side,
        restSeconds=row.rest_seconds,
        supersetId=row.superset_id,
        progression=row.progression,
        increment=_round(_from_kg(float(row.increment_kg), unit)) if row.increment_kg is not None else None,
    )


async def _routine_responses(
    db: AsyncSession, routines: list[StrengthRoutine], unit: str
) -> list[StrengthRoutineResponse]:
    routine_ids = [routine.id for routine in routines]
    items_by_routine: dict[UUID, list[StrengthRoutineExercise]] = defaultdict(list)
    if routine_ids:
        result = await db.execute(
            select(StrengthRoutineExercise)
            .where(StrengthRoutineExercise.routine_id.in_(routine_ids))
            .order_by(StrengthRoutineExercise.routine_id, StrengthRoutineExercise.position)
        )
        for item in result.scalars().all():
            items_by_routine[item.routine_id].append(item)
    return [
        StrengthRoutineResponse(
            id=routine.id,
            name=routine.name,
            symbolName=routine.symbol_name,
            progression=routine.progression,
            exercises=[_routine_item_response(item, unit) for item in items_by_routine[routine.id]],
            createdAt=routine.created_at,
            updatedAt=routine.updated_at,
        )
        for routine in routines
    ]


def _assignment_response(row: StrengthWeekAssignment) -> StrengthWeekAssignmentResponse:
    return StrengthWeekAssignmentResponse(
        weekday=row.weekday,
        routineId=row.routine_id,
        updatedAt=row.updated_at,
    )


async def _workout_response(
    db: AsyncSession, row: StrengthWorkout, unit: str
) -> StrengthWorkoutResponse:
    item_result = await db.execute(
        select(StrengthWorkoutExercise)
        .where(StrengthWorkoutExercise.workout_id == row.id)
        .order_by(StrengthWorkoutExercise.position)
    )
    items = item_result.scalars().all()
    item_ids = [item.id for item in items]
    sets_by_item: dict[UUID, list[StrengthWorkoutSet]] = defaultdict(list)
    if item_ids:
        set_result = await db.execute(
            select(StrengthWorkoutSet)
            .where(StrengthWorkoutSet.workout_exercise_id.in_(item_ids))
            .order_by(StrengthWorkoutSet.workout_exercise_id, StrengthWorkoutSet.set_number)
        )
        for workout_set in set_result.scalars().all():
            sets_by_item[workout_set.workout_exercise_id].append(workout_set)

    entries: list[WorkoutEntryPayload] = []
    for item in items:
        saved_sets = sets_by_item[item.id]
        first = saved_sets[0] if saved_sets else None
        target = RoutineExercisePayload(
            id=item.id,
            exerciseId=item.exercise_id,
            mode=item.mode,
            sets=max(len(saved_sets), 1),
            reps=first.reps if first and first.reps is not None else 0,
            seconds=first.duration_seconds if first and item.mode == "time" and first.duration_seconds is not None else 0,
            minutes=(first.duration_seconds or 0) // 60 if first and item.mode == "cardio" else 0,
            speedKmh=float(first.speed_kmh) if first and first.speed_kmh is not None else 0,
            weight=_round(_from_kg(float(first.weight_kg), unit) or 0) if first else 0,
            bodyweight=item.is_bodyweight,
            perSide=item.per_side,
        )
        entries.append(
            WorkoutEntryPayload(
                id=item.id,
                exerciseId=item.exercise_id,
                target=target,
                sets=[
                    WorkoutSetPayload(
                        id=workout_set.id,
                        weight=_round(_from_kg(float(workout_set.weight_kg), unit) or 0),
                        reps=workout_set.reps or 0,
                        seconds=workout_set.duration_seconds if item.mode == "time" else 0,
                        minutes=(workout_set.duration_seconds or 0) // 60 if item.mode == "cardio" else 0,
                        speedKmh=float(workout_set.speed_kmh) if workout_set.speed_kmh is not None else 0,
                        done=True,
                    )
                    for workout_set in saved_sets
                ],
            )
        )
    return StrengthWorkoutResponse(
        id=row.id,
        date=row.workout_date,
        name=row.name,
        startedAt=row.started_at,
        endedAt=row.ended_at,
        routineId=row.routine_id,
        entries=entries,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


@router.get("/bootstrap", response_model=StrengthBootstrapResponse)
async def get_strength_bootstrap(
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> StrengthBootstrapResponse:
    user_id = UUID(user.id)
    preference = await _preference(db, user_id)
    routine_result = await db.execute(
        select(StrengthRoutine)
        .where(StrengthRoutine.user_id == user_id)
        .order_by(StrengthRoutine.created_at.asc())
    )
    week_result = await db.execute(
        select(StrengthWeekAssignment)
        .where(StrengthWeekAssignment.user_id == user_id)
        .order_by(StrengthWeekAssignment.weekday.asc())
    )
    return StrengthBootstrapResponse(
        weightUnit=preference.weight_unit,
        routines=await _routine_responses(db, routine_result.scalars().all(), preference.weight_unit),
        week=[_assignment_response(row) for row in week_result.scalars().all()],
    )


@router.get("/exercises", response_model=ExercisePage)
async def list_exercises(
    query: str = Query(default="", max_length=100),
    body_part: str | None = Query(default=None, alias="bodyPart", max_length=100),
    equipment: str | None = Query(default=None, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExercisePage:
    user_id = UUID(user.id)
    conditions = [
        StrengthExercise.archived_at.is_(None),
        or_(StrengthExercise.is_catalog.is_(True), StrengthExercise.owner_user_id == user_id),
    ]
    query = query.strip()
    body_part = body_part.strip() if body_part else None
    equipment = equipment.strip() if equipment else None
    if query:
        term = f"%{query}%"
        conditions.append(
            or_(
                StrengthExercise.name.ilike(term),
                StrengthExercise.target_muscle.ilike(term),
                StrengthExercise.equipment.ilike(term),
                StrengthExercise.body_part.ilike(term),
            )
        )
    if body_part:
        conditions.append(StrengthExercise.body_part == body_part)
    if equipment:
        conditions.append(StrengthExercise.equipment == equipment)
    result = await db.execute(
        select(StrengthExercise)
        .where(*conditions)
        .order_by(StrengthExercise.is_catalog.asc(), StrengthExercise.name.asc())
        .offset(offset)
        .limit(limit + 1)
    )
    rows = result.scalars().all()
    page_rows = rows[:limit]
    return ExercisePage(
        items=[_exercise_response(row) for row in page_rows],
        nextOffset=offset + len(page_rows) if len(rows) > limit else None,
    )


@router.get("/exercises/{exercise_id}", response_model=ExerciseResponse)
async def get_exercise(
    exercise_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExerciseResponse:
    result = await db.execute(
        select(StrengthExercise).where(
            StrengthExercise.id == exercise_id,
            StrengthExercise.archived_at.is_(None),
            or_(StrengthExercise.is_catalog.is_(True), StrengthExercise.owner_user_id == UUID(user.id)),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found")
    instructions, muscles = await _exercise_maps(db, [row.id])
    return _exercise_response(row, instructions.get(row.id), muscles.get(row.id))


@router.get("/routines", response_model=list[StrengthRoutineResponse])
async def list_strength_routines(
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[StrengthRoutineResponse]:
    user_id = UUID(user.id)
    preference = await _preference(db, user_id)
    result = await db.execute(
        select(StrengthRoutine)
        .where(StrengthRoutine.user_id == user_id)
        .order_by(StrengthRoutine.created_at.asc())
    )
    return await _routine_responses(db, result.scalars().all(), preference.weight_unit)


@router.get("/week", response_model=list[StrengthWeekAssignmentResponse])
async def list_strength_week_assignments(
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[StrengthWeekAssignmentResponse]:
    result = await db.execute(
        select(StrengthWeekAssignment)
        .where(StrengthWeekAssignment.user_id == UUID(user.id))
        .order_by(StrengthWeekAssignment.weekday.asc())
    )
    return [_assignment_response(row) for row in result.scalars().all()]


@router.put("/routines/{routine_id}", response_model=StrengthRoutineResponse)
async def put_strength_routine(
    routine_id: UUID,
    body: StrengthRoutinePayload,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrengthRoutineResponse:
    if body.id != routine_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Routine id must match the route id")
    user_id = UUID(user.id)
    await _require_exercises(db, user_id, {item.exercise_id for item in body.exercises})
    preference = await _preference(db, user_id, create=True)
    result = await db.execute(
        select(StrengthRoutine).where(StrengthRoutine.id == routine_id, StrengthRoutine.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = StrengthRoutine(id=routine_id, user_id=user_id, name=body.name, symbol_name=body.symbol_name, progression=body.progression)
        db.add(row)
    else:
        row.name = body.name
        row.symbol_name = body.symbol_name
        row.progression = body.progression
        old_items = await db.execute(select(StrengthRoutineExercise).where(StrengthRoutineExercise.routine_id == routine_id))
        for old_item in old_items.scalars().all():
            await db.delete(old_item)
    for position, item in enumerate(body.exercises):
        db.add(
            StrengthRoutineExercise(
                id=item.id, routine_id=routine_id, exercise_id=item.exercise_id, position=position,
                mode=item.mode, target_sets=item.sets, target_reps=item.reps, reps_min=item.reps_min,
                reps_max=item.reps_max, target_seconds=item.seconds, target_minutes=item.minutes,
                target_speed_kmh=item.speed_kmh, target_weight_kg=_to_kg(item.weight, preference.weight_unit),
                is_bodyweight=item.bodyweight, per_side=item.per_side, rest_seconds=item.rest_seconds,
                superset_id=item.superset_id,
                progression=item.progression, increment_kg=_to_kg(item.increment, preference.weight_unit) if item.increment is not None else None,
            )
        )
    await db.commit()
    await db.refresh(row)
    return (await _routine_responses(db, [row], preference.weight_unit))[0]


@router.delete("/routines/{routine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strength_routine(
    routine_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    user_id = UUID(user.id)
    result = await db.execute(select(StrengthRoutine).where(StrengthRoutine.id == routine_id, StrengthRoutine.user_id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")
    await db.delete(row)
    await db.commit()


@router.put("/week/{weekday}", response_model=StrengthWeekAssignmentResponse)
async def put_strength_week_assignment(
    weekday: int,
    body: StrengthWeekAssignmentPayload,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrengthWeekAssignmentResponse:
    if weekday < 0 or weekday > 6:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="weekday must be between 0 and 6")
    user_id = UUID(user.id)
    if body.routine_id is not None:
        routine = await db.execute(select(StrengthRoutine.id).where(StrengthRoutine.id == body.routine_id, StrengthRoutine.user_id == user_id))
        if routine.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")
    result = await db.execute(select(StrengthWeekAssignment).where(StrengthWeekAssignment.user_id == user_id, StrengthWeekAssignment.weekday == weekday))
    row = result.scalar_one_or_none()
    if row is None:
        row = StrengthWeekAssignment(user_id=user_id, weekday=weekday, routine_id=body.routine_id)
        db.add(row)
    else:
        row.routine_id = body.routine_id
    await db.commit()
    await db.refresh(row)
    return _assignment_response(row)


@router.post("/workouts", response_model=StrengthWorkoutResponse, status_code=status.HTTP_201_CREATED)
async def create_strength_workout(
    body: StrengthWorkoutPayload,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrengthWorkoutResponse:
    user_id = UUID(user.id)
    existing_result = await db.execute(select(StrengthWorkout).where(StrengthWorkout.id == body.id))
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        if existing.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Strength workout with this id already exists")
        preference = await _preference(db, user_id)
        return await _workout_response(db, existing, preference.weight_unit)
    preference = await _preference(db, user_id, create=True)
    if body.routine_id is not None:
        routine = await db.execute(select(StrengthRoutine.id).where(StrengthRoutine.id == body.routine_id, StrengthRoutine.user_id == user_id))
        if routine.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Routine is unavailable")
    await _require_exercises(db, user_id, {entry.exercise_id for entry in body.entries})
    row = StrengthWorkout(
        id=body.id, user_id=user_id, workout_date=body.workout_date, name=body.name,
        started_at=body.started_at, ended_at=body.ended_at, routine_id=body.routine_id,
    )
    db.add(row)
    for position, entry in enumerate(body.entries):
        completed_sets = [workout_set for workout_set in entry.sets if workout_set.done]
        if not completed_sets:
            continue
        workout_exercise = StrengthWorkoutExercise(
            id=entry.id, workout_id=row.id, exercise_id=entry.exercise_id, position=position,
            mode=entry.target.mode, is_bodyweight=entry.target.bodyweight, per_side=entry.target.per_side,
        )
        db.add(workout_exercise)
        for set_number, workout_set in enumerate(completed_sets, start=1):
            duration = workout_set.seconds if entry.target.mode == "time" else workout_set.minutes * 60 if entry.target.mode == "cardio" else None
            db.add(
                StrengthWorkoutSet(
                    id=workout_set.id, workout_exercise_id=workout_exercise.id, set_number=set_number,
                    weight_kg=_to_kg(workout_set.weight, preference.weight_unit),
                    reps=workout_set.reps if entry.target.mode == "reps" else None,
                    duration_seconds=duration,
                    speed_kmh=workout_set.speed_kmh if entry.target.mode == "cardio" else None,
                )
            )
    await db.commit()
    await db.refresh(row)
    return await _workout_response(db, row, preference.weight_unit)


@router.get("/workouts", response_model=StrengthWorkoutPage)
async def list_strength_workouts(
    offset: int = Query(default=0, ge=0), limit: int = Query(default=25, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> StrengthWorkoutPage:
    user_id = UUID(user.id)
    page = (
        select(StrengthWorkout.id)
        .where(StrengthWorkout.user_id == user_id)
        .order_by(
            StrengthWorkout.workout_date.desc(),
            StrengthWorkout.ended_at.desc(),
            StrengthWorkout.id.desc(),
        )
        .offset(offset)
        .limit(limit + 1)
        .subquery()
    )
    result = await db.execute(
        select(StrengthWorkout, func.count(StrengthWorkoutExercise.id).label("exercise_count"))
        .join(page, page.c.id == StrengthWorkout.id)
        .outerjoin(StrengthWorkoutExercise, StrengthWorkoutExercise.workout_id == StrengthWorkout.id)
        .group_by(StrengthWorkout.id)
        .order_by(
            StrengthWorkout.workout_date.desc(),
            StrengthWorkout.ended_at.desc(),
            StrengthWorkout.id.desc(),
        )
    )
    rows = result.all()
    page_rows = rows[:limit]
    return StrengthWorkoutPage(
        items=[StrengthWorkoutSummary(id=workout.id, date=workout.workout_date, name=workout.name, startedAt=workout.started_at, endedAt=workout.ended_at, exerciseCount=count) for workout, count in page_rows],
        nextOffset=offset + len(page_rows) if len(rows) > limit else None,
    )


@router.get("/workouts/{workout_id}", response_model=StrengthWorkoutResponse)
async def get_strength_workout(
    workout_id: UUID,
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> StrengthWorkoutResponse:
    user_id = UUID(user.id)
    preference = await _preference(db, user_id)
    result = await db.execute(select(StrengthWorkout).where(StrengthWorkout.id == workout_id, StrengthWorkout.user_id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strength workout not found")
    return await _workout_response(db, row, preference.weight_unit)


@router.get("/analytics/overview", response_model=StrengthAnalyticsOverview)
async def strength_analytics_overview(
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> StrengthAnalyticsOverview:
    user_id = UUID(user.id)
    today = date.today()
    start = today - timedelta(days=364)
    month_start = today.replace(day=1)
    duration_minutes = func.greatest(
        0,
        func.round(
            func.extract("epoch", StrengthWorkout.ended_at - StrengthWorkout.started_at) / 60
        ),
    )
    totals_result = await db.execute(
        select(
            func.count().label("total_workouts"),
            func.count()
            .filter(StrengthWorkout.workout_date >= month_start)
            .label("workouts_this_month"),
        ).where(StrengthWorkout.user_id == user_id)
    )
    routine_result = await db.execute(select(func.count()).select_from(StrengthRoutine).where(StrengthRoutine.user_id == user_id))
    daily_result = await db.execute(
        select(
            StrengthWorkout.workout_date,
            func.count().label("workout_count"),
            func.sum(duration_minutes).label("duration_minutes"),
        )
        .where(
            StrengthWorkout.user_id == user_id,
            StrengthWorkout.workout_date >= start,
        )
        .group_by(StrengthWorkout.workout_date)
    )
    percentile_result = await db.execute(
        select(
            func.percentile_cont(0.25).within_group(duration_minutes),
            func.percentile_cont(0.5).within_group(duration_minutes),
            func.percentile_cont(0.75).within_group(duration_minutes),
        ).where(
            StrengthWorkout.user_id == user_id,
            StrengthWorkout.workout_date >= start,
        )
    )
    by_day = {
        workout_date: (int(workout_count), int(duration or 0))
        for workout_date, workout_count, duration in daily_result.all()
    }
    thresholds = [int(value or 0) for value in percentile_result.one()]
    heatmap: list[StrengthHeatmapDay] = []
    for day_offset in range(365):
        day = start + timedelta(days=day_offset)
        workout_count, minutes = by_day.get(day, (0, 0))
        level = 0 if not workout_count else 1 if minutes == 0 else 4 if minutes >= thresholds[2] else 3 if minutes >= thresholds[1] else 2 if minutes >= thresholds[0] else 1
        heatmap.append(StrengthHeatmapDay(day=day, workoutCount=workout_count, durationMinutes=minutes, level=level))
    totals = totals_result.one()
    return StrengthAnalyticsOverview(totalWorkouts=totals.total_workouts, workoutsThisMonth=totals.workouts_this_month, routineCount=routine_result.scalar_one(), heatmap=heatmap)


@router.get("/analytics/muscles", response_model=list[StrengthMuscleLoad])
async def strength_muscle_load(
    days: int = Query(default=7, ge=0, le=3650),
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[StrengthMuscleLoad]:
    conditions = [StrengthWorkout.user_id == UUID(user.id)]
    if days:
        conditions.append(StrengthWorkout.workout_date >= date.today() - timedelta(days=days - 1))
    result = await db.execute(
        select(StrengthExerciseMuscle.muscle_key, func.sum(StrengthExerciseMuscle.load_factor))
        .join(StrengthWorkoutExercise, StrengthWorkoutExercise.exercise_id == StrengthExerciseMuscle.exercise_id)
        .join(StrengthWorkoutSet, StrengthWorkoutSet.workout_exercise_id == StrengthWorkoutExercise.id)
        .join(StrengthWorkout, StrengthWorkout.id == StrengthWorkoutExercise.workout_id)
        .where(*conditions)
        .group_by(StrengthExerciseMuscle.muscle_key)
        .order_by(StrengthExerciseMuscle.muscle_key)
    )
    return [StrengthMuscleLoad(muscle=muscle, load=float(load)) for muscle, load in result.all()]


@router.get("/analytics/records", response_model=list[StrengthRecord])
async def strength_records(
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[StrengthRecord]:
    ranked = (
        select(
            StrengthWorkoutExercise.exercise_id.label("exercise_id"),
            StrengthExercise.name.label("exercise_name"),
            StrengthWorkout.ended_at.label("ended_at"),
            StrengthWorkoutSet.weight_kg.label("weight_kg"),
            StrengthWorkoutSet.reps.label("reps"),
            func.row_number()
            .over(
                partition_by=StrengthWorkoutExercise.exercise_id,
                order_by=(StrengthWorkoutSet.weight_kg.desc(), StrengthWorkout.ended_at.asc()),
            )
            .label("rank"),
        )
        .join(StrengthWorkoutSet, StrengthWorkoutSet.workout_exercise_id == StrengthWorkoutExercise.id)
        .join(StrengthWorkout, StrengthWorkout.id == StrengthWorkoutExercise.workout_id)
        .join(StrengthExercise, StrengthExercise.id == StrengthWorkoutExercise.exercise_id)
        .where(
            StrengthWorkout.user_id == UUID(user.id),
            StrengthWorkoutExercise.mode == "reps",
            StrengthWorkoutSet.weight_kg > 0,
            StrengthWorkoutSet.reps > 0,
        )
        .subquery()
    )
    result = await db.execute(
        select(ranked).where(ranked.c.rank == 1).order_by(ranked.c.weight_kg.desc())
    )
    return [
        StrengthRecord(
            exerciseId=row.exercise_id,
            exerciseName=row.exercise_name,
            weightKg=float(row.weight_kg),
            reps=row.reps,
            date=row.ended_at,
            estimatedOneRmKg=_estimate_one_rm(float(row.weight_kg), row.reps),
        )
        for row in result.all()
    ]


@router.get("/analytics/one-rm", response_model=list[StrengthOneRmExercise])
async def strength_one_rm(
    exercise_id: str | None = Query(default=None, alias="exerciseId"),
    days: int = Query(default=365, ge=1, le=3650),
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[StrengthOneRmExercise]:
    estimate = case(
        (StrengthWorkoutSet.reps == 1, cast(StrengthWorkoutSet.weight_kg, Float)),
        else_=cast(
            StrengthWorkoutSet.weight_kg
            * (1 + cast(StrengthWorkoutSet.reps, Float) / 30),
            Float,
        ),
    )
    conditions = [
        StrengthWorkout.user_id == UUID(user.id),
        StrengthWorkout.workout_date >= date.today() - timedelta(days=days - 1),
        StrengthWorkoutExercise.mode == "reps",
        StrengthWorkoutSet.weight_kg > 0,
        StrengthWorkoutSet.reps.between(1, _ONE_RM_REP_CAP),
    ]
    if exercise_id:
        conditions.append(StrengthWorkoutExercise.exercise_id == exercise_id)
    ranked = (
        select(
            StrengthWorkoutExercise.exercise_id.label("exercise_id"),
            StrengthExercise.name.label("exercise_name"),
            StrengthWorkout.ended_at.label("ended_at"),
            StrengthWorkoutSet.weight_kg.label("weight_kg"),
            StrengthWorkoutSet.reps.label("reps"),
            estimate.label("estimate"),
            func.row_number()
            .over(
                partition_by=(StrengthWorkoutExercise.exercise_id, StrengthWorkout.ended_at),
                order_by=estimate.desc(),
            )
            .label("rank"),
        )
        .join(StrengthWorkoutSet, StrengthWorkoutSet.workout_exercise_id == StrengthWorkoutExercise.id)
        .join(StrengthWorkout, StrengthWorkout.id == StrengthWorkoutExercise.workout_id)
        .join(StrengthExercise, StrengthExercise.id == StrengthWorkoutExercise.exercise_id)
        .where(*conditions)
        .subquery()
    )
    result = await db.execute(
        select(ranked)
        .where(ranked.c.rank == 1)
        .order_by(ranked.c.exercise_name.asc(), ranked.c.ended_at.asc())
    )
    grouped: dict[tuple[str, str], dict[datetime, StrengthOneRmPoint]] = defaultdict(dict)
    for row in result.all():
        grouped[(row.exercise_id, row.exercise_name)][row.ended_at] = StrengthOneRmPoint(
            date=row.ended_at,
            estimateKg=round(float(row.estimate), 1),
            weightKg=float(row.weight_kg),
            reps=row.reps,
        )
    return [
        StrengthOneRmExercise(exerciseId=item_id, exerciseName=name, points=list(points.values()))
        for (item_id, name), points in sorted(grouped.items(), key=lambda item: item[0][1])
    ]
