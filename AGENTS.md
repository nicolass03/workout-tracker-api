# Agent Notes

## Project constraints

- Use **SQLAlchemy 2.x async** with **asyncpg** for all database access.
- `DATABASE_URL` must be set via environment (`.env` locally). Never commit real credentials.
- Supabase transaction pooler (`:6543`) requires `statement_cache_size=0` and `prepared_statement_cache_size=0` with asyncpg; this is handled in `api/database.py`.
- For long-running servers, prefer Supabase session pooler or direct connection (`:5432`).
- Apply SQL migrations under `migrations/` manually (Supabase SQL editor or `psql`). Start with `001_daily_activity.sql`.

## Auth

- Auth happens on the **client** (Supabase SDK with **publishable** key `sb_publishable_...`, not legacy `anon`). The API does **not** use supabase-py.
- Protect routes with `Depends(get_current_user)` from `api.auth`.
- Clients must send `Authorization: Bearer <access_token>` (user JWT). Do not put publishable/secret keys in `Authorization` — they are not JWTs.
- Token verification is local via PyJWT:
  - Asymmetric (ES256/RS256): JWKS from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`
  - Legacy HS256: `SUPABASE_JWT_SECRET`
- Required env: `SUPABASE_URL`. Optional: `SUPABASE_JWT_SECRET` for HS256 projects.

## Daily activity

- Table `daily_activity`: one row per `(user_id, day)` with steps, active_energy_kcal, distance_meters, and `trail` JSONB `[{lat, lon, t}]`.
- `PUT /activity/days/{day}` — idempotent upsert for the authenticated user.
- `GET /activity/days/{day}` — fetch one day (404 if missing).
- iOS syncs **completed** days only (local SwiftData → API), typically overnight + on foreground.

## Dependency management

- `uv` is not installed on this machine; use `venv` + `pip` with `requirements.txt`.
- Pinned versions live in both `pyproject.toml` and `requirements.txt`.

## App entrypoint

- `api.main:app` — run with `fastapi dev api.main:app` or `uvicorn api.main:app --reload`.
