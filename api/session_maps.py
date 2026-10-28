from __future__ import annotations

from datetime import datetime, timezone
from math import hypot
from typing import Any, Iterable
from uuid import UUID

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import SessionMapPreview, WorkoutSession

_RESOLUTION_LIMITS = {"preview": 50, "map": 300, "detail": 1_000}


def _perpendicular_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    if start == end:
        return hypot(point[0] - start[0], point[1] - start[1])
    dx, dy = end[0] - start[0], end[1] - start[1]
    numerator = abs(dy * point[0] - dx * point[1] + end[0] * start[1] - end[1] * start[0])
    return numerator / hypot(dx, dy)


def _rdp(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points
    kept = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        start_index, end_index = pending.pop()
        distance, split = 0.0, 0
        for index in range(start_index + 1, end_index):
            candidate = _perpendicular_distance(
                points[index], points[start_index], points[end_index]
            )
            if candidate > distance:
                distance, split = candidate, index
        if distance > tolerance:
            kept.add(split)
            pending.append((start_index, split))
            pending.append((split, end_index))
    return [points[index] for index in sorted(kept)]


def _limit(points: list[tuple[float, float]], maximum: int) -> list[tuple[float, float]]:
    if len(points) <= maximum:
        return points
    if maximum <= 2:
        return [points[0], points[-1]]
    stride = (len(points) - 1) / (maximum - 1)
    return [points[round(index * stride)] for index in range(maximum)]


def _simplify_sections(sections: list[dict[str, Any]], maximum: int) -> list[dict[str, Any]]:
    usable = [section for section in sections if len(section.get("coordinates", [])) >= 2]
    total = sum(len(section["coordinates"]) for section in usable)
    if total <= maximum:
        return usable

    # Every kept section needs both endpoints. When that alone overflows the cap,
    # keep the longest sections (in order); the dropped ones are sub-pixel here.
    if 2 * len(usable) > maximum:
        longest = sorted(
            range(len(usable)), key=lambda index: len(usable[index]["coordinates"]), reverse=True
        )[: maximum // 2]
        usable = [usable[index] for index in sorted(longest)]
        total = sum(len(section["coordinates"]) for section in usable)
    # Spread what is left after the endpoints in proportion to each section's
    # interior points; flooring keeps the total within `maximum`.
    spare_budget = maximum - 2 * len(usable)
    spare_points = total - 2 * len(usable)

    result: list[dict[str, Any]] = []
    for section in usable:
        raw = [tuple(coordinate) for coordinate in section["coordinates"]]
        allocation = 2 + (spare_budget * (len(raw) - 2) // spare_points if spare_points else 0)
        # Roughly 1.1 m at the equator; RDP removes collinear points before the
        # deterministic cap and preserves corners much better than stride-only sampling.
        simplified = _limit(_rdp(raw, tolerance=0.00001), allocation)
        result.append({**section, "coordinates": [list(point) for point in simplified]})
    return result


def segment_sections(segments: Iterable[Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for segment in sorted(segments, key=lambda item: item.idx):
        coordinates = [
            [float(point["lat"]), float(point["lon"])]
            for point in (segment.points if isinstance(segment.points, list) else [])
            if isinstance(point, dict)
            and point.get("display", True) is not False
            and point.get("lat") is not None
            and point.get("lon") is not None
        ]
        if len(coordinates) >= 2:
            sections.append(
                {
                    "id": str(segment.id),
                    "idx": segment.idx,
                    "started_at": segment.started_at.isoformat(),
                    "ended_at": segment.ended_at.isoformat() if segment.ended_at else None,
                    "steps": segment.steps,
                    "coordinates": coordinates,
                }
            )
    return sections


def canonical_sections(
    raw_sections: list[dict[str, Any]], session: WorkoutSession
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for index, section in enumerate(raw_sections):
        coordinates = [
            [float(point["latitude"]), float(point["longitude"])]
            for point in section.get("coordinates", [])
            if point.get("latitude") is not None and point.get("longitude") is not None
        ]
        if len(coordinates) >= 2:
            sections.append(
                {
                    "id": str(section.get("id") or UUID(int=index + 1)),
                    "idx": index,
                    "started_at": session.started_at.isoformat(),
                    "ended_at": session.ended_at.isoformat(),
                    "steps": 0,
                    "coordinates": coordinates,
                }
            )
    return sections


def make_preview(
    session: WorkoutSession,
    sections: list[dict[str, Any]],
    *,
    source_revision: int | None = None,
) -> SessionMapPreview:
    # Build progressively so a very high-fidelity canonical route is simplified
    # only once; smaller variants operate on the already bounded detail model.
    detail_sections = _simplify_sections(sections, _RESOLUTION_LIMITS["detail"])
    map_sections = _simplify_sections(detail_sections, _RESOLUTION_LIMITS["map"])
    preview_sections = _simplify_sections(map_sections, _RESOLUTION_LIMITS["preview"])
    return SessionMapPreview(
        session_id=session.id,
        user_id=session.user_id,
        source_revision=source_revision,
        preview_sections=preview_sections,
        map_sections=map_sections,
        detail_sections=detail_sections,
    )


async def upsert_map_preview(
    db: AsyncSession,
    session: WorkoutSession,
    sections: list[dict[str, Any]],
    *,
    source_revision: int | None = None,
) -> None:
    # Simplifying a long canonical route is pure-Python CPU work; keep it off the event loop.
    preview = await run_in_threadpool(
        make_preview, session, sections, source_revision=source_revision
    )
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
    await db.execute(statement.on_conflict_do_update(**update_arguments))


def sections_for_resolution(preview: SessionMapPreview, resolution: str) -> list:
    return {
        "preview": preview.preview_sections,
        "map": preview.map_sections,
        "detail": preview.detail_sections,
    }[resolution]
