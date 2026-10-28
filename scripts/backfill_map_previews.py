#!/usr/bin/env python3
"""Build map previews for sessions created before 019_session_map_previews.sql.

New sessions and canonical-route uploads write their own preview, so this only has to
run once per database (before deploying an API without the lazy read-path backfill).
Idempotent: sessions that already have a preview are skipped.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.config import get_settings
from api.database import create_engine
from api.models import SessionMapPreview, WorkoutSession
from api.session_maps import segment_sections, upsert_map_preview

BATCH_SIZE = 50


async def backfill() -> int:
    engine = create_engine(get_settings())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            missing = (
                await db.scalars(
                    select(WorkoutSession.id).where(
                        ~exists().where(SessionMapPreview.session_id == WorkoutSession.id)
                    )
                )
            ).all()
            for start in range(0, len(missing), BATCH_SIZE):
                rows = await db.scalars(
                    select(WorkoutSession)
                    .where(WorkoutSession.id.in_(missing[start : start + BATCH_SIZE]))
                    .options(selectinload(WorkoutSession.segments))
                )
                for row in rows:
                    await upsert_map_preview(db, row, segment_sections(row.segments))
                await db.commit()
                # Release the batch's trail JSON before loading the next one.
                db.expunge_all()
                print(f"  {min(start + BATCH_SIZE, len(missing))}/{len(missing)}", flush=True)
    finally:
        await engine.dispose()
    return len(missing)


def main() -> None:
    try:
        count = asyncio.run(backfill())
    except Exception as exc:  # noqa: BLE001 — surface a clear failure
        print(f"Backfill failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Done. Built {count} map preview(s).")


if __name__ == "__main__":
    main()
