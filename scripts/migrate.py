#!/usr/bin/env python3
"""Apply pending SQL migrations under migrations/ using DATABASE_URL.

Tracks applied files in schema_migrations. Safe to re-run.
Prefer idempotent SQL (IF NOT EXISTS) so already-manual applies are fine.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"

# Ensure repo root is importable when run as `python scripts/migrate.py`.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.config import get_settings
from api.database import create_engine

ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _split_statements(sql: str) -> list[str]:
    """Split a simple SQL file into statements (no procedure bodies)."""
    without_line_comments = re.sub(r"(?m)^\s*--.*$", "", sql)
    parts = [part.strip() for part in without_line_comments.split(";")]
    return [part for part in parts if part]


async def apply_migrations() -> int:
    settings = get_settings()
    engine = create_engine(settings)

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print("No migration files found.")
        await engine.dispose()
        return 0

    applied = 0
    try:
        async with engine.begin() as conn:
            await conn.execute(text(ENSURE_TABLE_SQL))
            result = await conn.execute(text("SELECT filename FROM schema_migrations"))
            already = {row[0] for row in result.fetchall()}

            for path in migration_files:
                name = path.name
                if name in already:
                    print(f"skip  {name}")
                    continue

                sql = path.read_text(encoding="utf-8")
                statements = _split_statements(sql)
                if not statements:
                    print(f"skip  {name} (empty)")
                    continue

                print(f"apply {name}")
                for statement in statements:
                    await conn.execute(text(statement))
                await conn.execute(
                    text("INSERT INTO schema_migrations (filename) VALUES (:filename)"),
                    {"filename": name},
                )
                applied += 1
    finally:
        await engine.dispose()

    print(f"Done. Applied {applied} migration(s).")
    return applied


def main() -> None:
    try:
        asyncio.run(apply_migrations())
    except Exception as exc:  # noqa: BLE001 — surface clear deploy failure
        print(f"Migration failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
