import base64
import binascii
import json
from hashlib import sha256
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID, uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from api.auth import CurrentUser, get_current_user
from api.database import get_db
from api.cache import response_cache
from api.models import (
    SessionMapPreview,
    SessionRoute,
    SessionSegment,
    SessionTraceChunk,
    WorkoutSession,
)
from api.session_maps import (
    canonical_sections,
    make_preview,
    sections_for_resolution,
    segment_sections,
)
from api.schemas.sessions import (
    SegmentPoint,
    ElevationSampleResponse,
    SessionSegmentResponse,
    MoveSessionCreate,
    MoveSessionHistoryItem,
    MoveSessionHistoryPage,
    MoveMapSection,
    MoveMapSessionResponse,
    MoveSessionResponse,
    CanonicalTrailResponse,
    CanonicalTrailUpsert,
    TraceChunkManifestItem,
    TraceChunkBatchUpsert,
    TraceChunkUpsert,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])

_MAX_RANGE_DAYS = 62
# Pad UTC day bounds so local-calendar days near midnight are not missed; clients
# still group/filter by their own Calendar day.
_TZ_PAD = timedelta(hours=14)


def _encode_history_cursor(started_at: datetime, session_id: UUID) -> str:
    payload = json.dumps(
        {"started_at": started_at.isoformat(), "id": str(session_id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_history_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        started_at = datetime.fromisoformat(payload["started_at"])
        session_id = UUID(payload["id"])
        if started_at.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return started_at, session_id
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid history cursor",
        ) from error


async def _require_owned_session(
    db: AsyncSession, session_id: UUID, user_id: UUID
) -> None:
    exists = await db.scalar(
        select(WorkoutSession.id).where(
            WorkoutSession.id == session_id, WorkoutSession.user_id == user_id
        )
    )
    if exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")


def _points_to_json(points: list[SegmentPoint]) -> list[dict]:
    return [
        {
            "lat": p.lat,
            "lon": p.lon,
            "t": p.t.isoformat(),
            "accuracy": p.accuracy,
            "speed": p.speed,
            "course": p.course,
            "altitude": p.altitude,
            "vertical_accuracy": p.vertical_accuracy,
            "display": p.display,
        }
        for p in points
    ]


def _points_from_json(raw: list | None) -> list[SegmentPoint]:
    if not raw:
        return []
    return [SegmentPoint.model_validate(item) for item in raw]


def _downsample_points(points: list[SegmentPoint], maximum: int | None) -> list[SegmentPoint]:
    if maximum is None or len(points) <= maximum:
        return points
    if maximum == 1:
        return [points[0]]
    stride = (len(points) - 1) / (maximum - 1)
    return [points[round(index * stride)] for index in range(maximum)]


def _elevation_samples_from_json(raw: list | None) -> list[ElevationSampleResponse]:
    if not raw:
        return []
    return [ElevationSampleResponse.model_validate(item) for item in raw]


def _to_response(
    row: WorkoutSession, *, include_points: bool = True, point_limit: int | None = None
) -> MoveSessionResponse:
    if row.type not in {"walk_run", "walk", "run", "jogging", "hiking"}:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported session type: {row.type}",
        )
    if row.steps is None or row.distance_meters is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="move session missing steps/distance",
        )
    segments = [
        SessionSegmentResponse(
            id=seg.id,
            idx=seg.idx,
            started_at=seg.started_at,
            ended_at=seg.ended_at,
            steps=seg.steps,
            points=(
                _downsample_points(
                    _points_from_json(seg.points if isinstance(seg.points, list) else []),
                    point_limit,
                )
                if include_points
                else []
            ),
        )
        for seg in sorted(row.segments, key=lambda s: s.idx)
    ]
    return MoveSessionResponse(
        id=row.id,
        user_id=row.user_id,
        type=row.type,
        started_at=row.started_at,
        ended_at=row.ended_at,
        active_duration_seconds=row.active_duration_seconds,
        active_energy_kcal=row.active_energy_kcal,
        steps=row.steps,
        distance_meters=row.distance_meters,
        segments=segments,
        elevation_gain_meters=row.elevation_gain_meters,
        elevation_loss_meters=row.elevation_loss_meters,
        elevation_samples=_elevation_samples_from_json(
            row.elevation_samples if isinstance(row.elevation_samples, list) else []
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc) - _TZ_PAD
    end = datetime.combine(day, time.max, tzinfo=timezone.utc) + _TZ_PAD
    return start, end


async def _upsert_map_preview(
    db: AsyncSession,
    session: WorkoutSession,
    sections: list[dict],
    *,
    source_revision: int | None = None,
) -> None:
    preview = make_preview(session, sections, source_revision=source_revision)
    values = {
        "session_id": preview.session_id,
        "user_id": preview.user_id,
        "source_revision": preview.source_revision,
        "preview_sections": preview.preview_sections,
        "map_sections": preview.map_sections,
        "detail_sections": preview.detail_sections,
    }
    statement = insert(SessionMapPreview).values(**values)
    update_arguments = {
        "index_elements": [SessionMapPreview.session_id],
        "set_": {**values, "updated_at": datetime.now(timezone.utc)},
    }
    if source_revision is not None:
        update_arguments["where"] = or_(
            SessionMapPreview.source_revision.is_(None),
            SessionMapPreview.source_revision <= source_revision,
        )
    statement = statement.on_conflict_do_update(**update_arguments)
    await db.execute(statement)


async def _invalidate_move_cache(user_id: UUID) -> None:
    await response_cache.invalidate_user(str(user_id))


def _to_map_response(
    row: WorkoutSession,
    preview: SessionMapPreview | None,
    resolution: str = "map",
) -> MoveMapSessionResponse:
    return MoveMapSessionResponse(
        id=row.id,
        user_id=row.user_id,
        type=row.type,
        started_at=row.started_at,
        ended_at=row.ended_at,
        active_duration_seconds=row.active_duration_seconds,
        active_energy_kcal=row.active_energy_kcal,
        steps=row.steps,
        distance_meters=row.distance_meters,
        elevation_gain_meters=row.elevation_gain_meters,
        elevation_loss_meters=row.elevation_loss_meters,
        sections=[
            MoveMapSection.model_validate(section)
            for section in sections_for_resolution(preview, resolution)
        ] if preview else [],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _map_session_columns():
    return load_only(
        WorkoutSession.id,
        WorkoutSession.user_id,
        WorkoutSession.type,
        WorkoutSession.started_at,
        WorkoutSession.ended_at,
        WorkoutSession.active_duration_seconds,
        WorkoutSession.active_energy_kcal,
        WorkoutSession.steps,
        WorkoutSession.distance_meters,
        WorkoutSession.elevation_gain_meters,
        WorkoutSession.elevation_loss_meters,
        WorkoutSession.created_at,
        WorkoutSession.updated_at,
    )


@router.post(
    "",
    response_model=MoveSessionResponse | MoveMapSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    body: MoveSessionCreate,
    compact: bool = Query(default=False),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MoveSessionResponse | MoveMapSessionResponse:
    user_id = UUID(user.id)
    session_id = body.id or uuid4()

    if body.id is not None:
        options = (
            selectinload(WorkoutSession.map_preview)
            if compact
            else selectinload(WorkoutSession.segments)
        )
        existing = await db.execute(
            select(WorkoutSession)
            .where(WorkoutSession.id == session_id)
            .options(_map_session_columns(), options)
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            if row.user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Session with this id already exists",
                )
            return _to_map_response(row, row.map_preview) if compact else _to_response(row)

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
        elevation_gain_meters=body.elevation_gain_meters,
        elevation_loss_meters=body.elevation_loss_meters,
        elevation_samples=[sample.model_dump(mode="json") for sample in body.elevation_samples],
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
    await db.flush()
    await _upsert_map_preview(db, row, segment_sections(row.segments))
    await db.commit()
    await _invalidate_move_cache(user_id)

    if compact:
        result = await db.execute(
            select(WorkoutSession)
            .where(WorkoutSession.id == session_id)
            .options(_map_session_columns(), selectinload(WorkoutSession.map_preview))
        )
        saved = result.scalar_one()
        return _to_map_response(saved, saved.map_preview)

    result = await db.execute(
        select(WorkoutSession)
        .where(WorkoutSession.id == session_id)
        .options(selectinload(WorkoutSession.segments))
    )
    saved = result.scalar_one()
    return _to_response(saved)


@router.get("/map", response_model=list[MoveMapSessionResponse])
async def list_session_map(
    request: Request,
    from_day: date = Query(..., alias="from"),
    to_day: date = Query(..., alias="to"),
    resolution: Literal["preview", "map", "detail"] = Query(default="map"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Return a compact, cacheable Move map read model without raw GPS metadata."""
    if from_day > to_day:
        raise HTTPException(status_code=422, detail="'from' must be on or before 'to'")
    if (to_day - from_day).days + 1 > _MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail=f"Range cannot exceed {_MAX_RANGE_DAYS} days")

    user_id = UUID(user.id)
    generation = await response_cache.generation(str(user_id))
    cache_key = (
        f"move:{user_id}:map:v1:{generation}:{from_day}:{to_day}:{resolution}"
        if generation is not None
        else None
    )
    payload = await response_cache.get(cache_key) if cache_key else None

    if payload is None:
        range_start, _ = _day_bounds_utc(from_day)
        _, range_end = _day_bounds_utc(to_day)
        result = await db.execute(
            select(WorkoutSession)
            .where(
                WorkoutSession.user_id == user_id,
                WorkoutSession.started_at >= range_start,
                WorkoutSession.started_at <= range_end,
            )
            .options(_map_session_columns(), selectinload(WorkoutSession.map_preview))
            .order_by(WorkoutSession.started_at.asc())
        )
        rows = result.scalars().unique().all()

        missing_ids = [row.id for row in rows if row.map_preview is None]
        if missing_ids:
            legacy = await db.execute(
                select(WorkoutSession)
                .where(WorkoutSession.id.in_(missing_ids))
                .options(selectinload(WorkoutSession.segments))
            )
            for row in legacy.scalars().unique().all():
                await _upsert_map_preview(db, row, segment_sections(row.segments))
            await db.commit()
            # Refresh only the small preview relationship; legacy point JSON is released.
            refreshed = await db.execute(
                select(WorkoutSession)
                .where(WorkoutSession.id.in_(missing_ids))
                .options(_map_session_columns(), selectinload(WorkoutSession.map_preview))
                .execution_options(populate_existing=True)
            )
            replacements = {row.id: row for row in refreshed.scalars().unique().all()}
            rows = [replacements.get(row.id, row) for row in rows]

        response_models = [_to_map_response(row, row.map_preview, resolution) for row in rows]
        payload = json.dumps(
            [model.model_dump(mode="json") for model in response_models],
            separators=(",", ":"),
        ).encode()
        age = (datetime.now(timezone.utc).date() - to_day).days
        ttl = 45 if age <= 0 else 300 if age <= 7 else 21_600
        if cache_key:
            await response_cache.set(cache_key, payload, ttl)

    etag = f'"{sha256(payload).hexdigest()}"'
    headers = {
        "Cache-Control": "private, max-age=0, must-revalidate",
        "ETag": etag,
        "Vary": "Authorization, Accept-Encoding",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=payload, media_type="application/json", headers=headers)


@router.get("", response_model=list[MoveSessionResponse])
async def list_sessions(
    from_day: date = Query(..., alias="from"),
    to_day: date = Query(..., alias="to"),
    include_points: bool = Query(default=False, alias="includePoints"),
    point_limit: int | None = Query(default=None, alias="pointLimit", ge=1, le=4_000),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MoveSessionResponse]:
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

    segments_option = selectinload(WorkoutSession.segments)
    if not include_points:
        segments_option = segments_option.load_only(
            SessionSegment.id,
            SessionSegment.idx,
            SessionSegment.started_at,
            SessionSegment.ended_at,
            SessionSegment.steps,
        )
    result = await db.execute(
        select(WorkoutSession)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.started_at >= range_start,
            WorkoutSession.started_at <= range_end,
        )
        .options(segments_option)
        .order_by(WorkoutSession.started_at.asc())
    )
    return [
        _to_response(row, include_points=include_points, point_limit=point_limit)
        for row in result.scalars().unique().all()
    ]


@router.get("/history", response_model=MoveSessionHistoryPage)
async def list_session_history(
    limit: int = Query(default=30, ge=1, le=50),
    cursor: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MoveSessionHistoryPage:
    """Return move sessions newest first without sending trail geometry."""
    user_id = UUID(user.id)
    cursor_values = _decode_history_cursor(cursor) if cursor else None
    has_trail = exists(
        select(SessionSegment.id).where(
            SessionSegment.session_id == WorkoutSession.id,
            func.coalesce(func.jsonb_array_length(SessionSegment.points), 0) >= 2,
        )
    ).label("has_trail")
    statement = (
        select(WorkoutSession, has_trail)
        .where(WorkoutSession.user_id == user_id)
        .options(_map_session_columns())
    )
    if cursor_values:
        started_at, session_id = cursor_values
        statement = statement.where(
            or_(
                WorkoutSession.started_at < started_at,
                and_(WorkoutSession.started_at == started_at, WorkoutSession.id < session_id),
            )
        )
    result = await db.execute(
        statement
        .order_by(WorkoutSession.started_at.desc(), WorkoutSession.id.desc())
        .limit(limit + 1)
    )
    rows = result.all()
    page_rows = rows[:limit]
    items = [
        MoveSessionHistoryItem(
            id=row.id,
            type=row.type,
            started_at=row.started_at,
            ended_at=row.ended_at,
            active_duration_seconds=row.active_duration_seconds,
            active_energy_kcal=row.active_energy_kcal,
            steps=row.steps,
            distance_meters=row.distance_meters,
            elevation_gain_meters=row.elevation_gain_meters,
            elevation_loss_meters=row.elevation_loss_meters,
            has_trail=trail_exists,
        )
        for row, trail_exists in page_rows
    ]
    next_cursor = None
    if len(rows) > limit and page_rows:
        last, _ = page_rows[-1]
        next_cursor = _encode_history_cursor(last.started_at, last.id)
    return MoveSessionHistoryPage(items=items, next_cursor=next_cursor)


@router.put(
    "/{session_id}/trace-chunks/{kind}/{section_index}/{chunk_index}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def put_trace_chunk(
    session_id: UUID,
    kind: Literal["location", "motion"],
    section_index: int,
    chunk_index: int,
    body: TraceChunkUpsert,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if section_index < 0 or chunk_index < 0:
        raise HTTPException(status_code=422, detail="chunk indexes must be non-negative")
    if any(sample.session_id != session_id for sample in body.samples):
        raise HTTPException(status_code=422, detail="sample session_id must match the URL")

    user_id = UUID(user.id)
    await _require_owned_session(db, session_id, user_id)
    values = {
        "session_id": session_id,
        "user_id": user_id,
        "kind": kind,
        "section_index": section_index,
        "chunk_index": chunk_index,
        "first_at": body.first_at,
        "last_at": body.last_at,
        "sample_count": len(body.samples),
        "checksum_sha256": body.checksum_sha256,
        "samples": [sample.model_dump(mode="json") for sample in body.samples],
    }
    statement = insert(SessionTraceChunk).values(**values)
    statement = statement.on_conflict_do_update(
        constraint="uq_session_trace_chunk",
        set_={**values, "updated_at": datetime.now(timezone.utc)},
    )
    await db.execute(statement)
    await db.commit()


@router.post(
    "/{session_id}/trace-chunks/batch",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def put_trace_chunk_batch(
    session_id: UUID,
    body: TraceChunkBatchUpsert,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if any(
        sample.session_id != session_id
        for chunk in body.chunks
        for sample in chunk.samples
    ):
        raise HTTPException(status_code=422, detail="sample session_id must match the URL")
    user_id = UUID(user.id)
    await _require_owned_session(db, session_id, user_id)
    now = datetime.now(timezone.utc)
    values_list = []
    for chunk in body.chunks:
        values_list.append({
            "session_id": session_id,
            "user_id": user_id,
            "kind": chunk.kind,
            "section_index": chunk.section_index,
            "chunk_index": chunk.chunk_index,
            "first_at": chunk.first_at,
            "last_at": chunk.last_at,
            "sample_count": len(chunk.samples),
            "checksum_sha256": chunk.checksum_sha256,
            "samples": [sample.model_dump(mode="json") for sample in chunk.samples],
        })
    statement = insert(SessionTraceChunk).values(values_list)
    statement = statement.on_conflict_do_update(
        constraint="uq_session_trace_chunk",
        set_={
            "user_id": statement.excluded.user_id,
            "first_at": statement.excluded.first_at,
            "last_at": statement.excluded.last_at,
            "sample_count": statement.excluded.sample_count,
            "checksum_sha256": statement.excluded.checksum_sha256,
            "samples": statement.excluded.samples,
            "updated_at": now,
        },
    )
    await db.execute(statement)
    await db.commit()


@router.get(
    "/{session_id}/trace-chunks",
    response_model=list[TraceChunkManifestItem],
)
async def get_trace_manifest(
    session_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TraceChunkManifestItem]:
    user_id = UUID(user.id)
    await _require_owned_session(db, session_id, user_id)
    result = await db.execute(
        select(SessionTraceChunk)
        .where(
            SessionTraceChunk.session_id == session_id,
            SessionTraceChunk.user_id == user_id,
        )
        .options(
            load_only(
                SessionTraceChunk.kind,
                SessionTraceChunk.section_index,
                SessionTraceChunk.chunk_index,
                SessionTraceChunk.first_at,
                SessionTraceChunk.last_at,
                SessionTraceChunk.sample_count,
                SessionTraceChunk.checksum_sha256,
            )
        )
        .order_by(
            SessionTraceChunk.kind,
            SessionTraceChunk.section_index,
            SessionTraceChunk.chunk_index,
        )
    )
    return [
        TraceChunkManifestItem(
            kind=row.kind,
            section_index=row.section_index,
            chunk_index=row.chunk_index,
            first_at=row.first_at,
            last_at=row.last_at,
            sample_count=row.sample_count,
            checksum_sha256=row.checksum_sha256,
        )
        for row in result.scalars().all()
    ]


def _route_response(row: SessionRoute) -> CanonicalTrailResponse:
    status_value = {
        "gps_only": "gpsOnly",
        "partially_matched": "partiallyMatched",
        "matched": "matched",
    }[row.status]
    return CanonicalTrailResponse(
        session_id=row.session_id,
        revision=row.revision,
        algorithm_version=row.algorithm_version,
        graph_version=row.graph_version,
        status=status_value,
        confidence=row.confidence,
        distance_meters=row.distance_meters,
        quality=row.quality,
        sections=row.sections,
        processed_at=row.processed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.put(
    "/{session_id}/routes/{revision}",
    response_model=CanonicalTrailResponse,
)
async def put_canonical_route(
    session_id: UUID,
    revision: int,
    body: CanonicalTrailUpsert,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CanonicalTrailResponse:
    if revision < 1:
        raise HTTPException(status_code=422, detail="revision must be positive")
    user_id = UUID(user.id)
    await _require_owned_session(db, session_id, user_id)
    status_value = {
        "gpsOnly": "gps_only",
        "partiallyMatched": "partially_matched",
        "matched": "matched",
    }[body.status]
    values = {
        "session_id": session_id,
        "user_id": user_id,
        "revision": revision,
        "algorithm_version": body.algorithm_version,
        "graph_version": body.graph_version,
        "status": status_value,
        "confidence": body.confidence,
        "distance_meters": body.distance_meters,
        "quality": body.quality,
        "sections": [section.model_dump(mode="json") for section in body.sections],
        "processed_at": body.processed_at,
    }
    statement = insert(SessionRoute).values(**values)
    statement = statement.on_conflict_do_update(
        constraint="uq_session_routes_revision",
        set_={**values, "updated_at": datetime.now(timezone.utc)},
    ).returning(SessionRoute)
    row = (await db.execute(statement)).scalar_one()
    session = (
        await db.execute(
            select(WorkoutSession).where(
                WorkoutSession.id == session_id,
                WorkoutSession.user_id == user_id,
            ).options(_map_session_columns())
        )
    ).scalar_one()
    await _upsert_map_preview(
        db,
        session,
        canonical_sections(
            [section.model_dump(mode="json") for section in body.sections],
            session,
        ),
        source_revision=revision,
    )
    await db.commit()
    await _invalidate_move_cache(user_id)
    return _route_response(row)


@router.get(
    "/{session_id}/routes/latest",
    response_model=CanonicalTrailResponse,
)
async def get_latest_canonical_route(
    session_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CanonicalTrailResponse:
    user_id = UUID(user.id)
    await _require_owned_session(db, session_id, user_id)
    result = await db.execute(
        select(SessionRoute)
        .where(SessionRoute.session_id == session_id, SessionRoute.user_id == user_id)
        .order_by(SessionRoute.revision.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Canonical route not found")
    return _route_response(row)


@router.get("/{session_id}", response_model=MoveSessionResponse)
async def get_session(
    session_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MoveSessionResponse:
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
    await _invalidate_move_cache(user_id)
