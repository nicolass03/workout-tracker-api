# Agent Notes

## Project constraints

- Use **SQLAlchemy 2.x async** with **asyncpg** for all database access.
- `DATABASE_URL` must be set via environment (`.env` locally). Never commit real credentials.
- Supabase transaction pooler (`:6543`) requires `statement_cache_size=0` and `prepared_statement_cache_size=0` with asyncpg; this is handled in `api/database.py`.
- For long-running servers, prefer Supabase session pooler or direct connection (`:5432`).
- Apply SQL migrations under `migrations/` via `python scripts/migrate.py` (tracks applied files in `schema_migrations`). Prefer idempotent SQL (`IF NOT EXISTS`). Railway start runs migrate then uvicorn.

## Auth

- Auth happens on the **client** (Supabase SDK with **publishable** key `sb_publishable_...`, not legacy `anon`). The API does **not** use supabase-py.
- Protect routes with `Depends(get_current_user)` from `api.auth`.
- Clients must send `Authorization: Bearer <access_token>` (user JWT). Do not put publishable/secret keys in `Authorization` — they are not JWTs.
- Token verification is local via PyJWT:
  - Asymmetric (ES256/RS256): JWKS from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`
  - Legacy HS256: `SUPABASE_JWT_SECRET`
- Required env: `SUPABASE_URL`. Optional: `SUPABASE_JWT_SECRET` for HS256 projects.

## Daily activity

- Table `daily_activity`: one row per `(user_id, day)` with steps, active_energy_kcal, distance_meters, and `trail` JSONB.
- Trail point shape: `{lat, lon, t, seg?, seg_steps?}`. `seg` groups walk segments; `seg_steps` is set on the first point of each segment. Legacy flat `[{lat,lon,t}]` still accepted (treated as one segment).
- `PUT /activity/days/{day}` — idempotent upsert for the authenticated user.
- `GET /activity/days/{day}` — fetch one day including trail (404 if missing).
- `GET /activity/days?from=&to=` — list summaries for inclusive range (no trail); max 62 days; `from` must be ≤ `to`.
- iOS syncs **completed** days only (local SwiftData → API), typically overnight + on foreground.
- iOS Steps tab reads past days via GET single-day when local trail/KPIs are missing.

## Dependency management

- `uv` is not installed on this machine; use `venv` + `pip` with `requirements.txt`.
- Pinned versions live in both `pyproject.toml` and `requirements.txt`.

## App entrypoint

- `api.main:app` — run with `fastapi dev api.main:app` or `uvicorn api.main:app --reload`.

## Railway

- Deploy config is `railway.json` (Railpack + `python scripts/migrate.py && uvicorn` on `$PORT`, healthcheck `/health`).
- Python pin: `.python-version` → `3.12` (matches `requires-python` in `pyproject.toml`).
- Required service variables: `DATABASE_URL`, `SUPABASE_URL`. Optional: `SUPABASE_JWT_SECRET` (legacy HS256).
- Prefer Supabase session pooler or direct (`:5432`) for the long-running Railway process; transaction pooler (`:6543`) still works (prepared-statement cache disabled).
- After deploy: generate a public domain, set iOS `API_BASE_URL` to that origin (no trailing slash).
- Deploy from this repo root: `railway up` (or link a GitHub repo in the dashboard).

## Migrations

- Files: `migrations/*.sql` (lexicographic order, e.g. `001_…`, `002_…`).
- Runner: `python scripts/migrate.py` (needs `DATABASE_URL` / `.env`).
- Bookkeeping table: `schema_migrations (filename, applied_at)`.
- Deploy applies pending migrations automatically before the API starts.
- Keep migrations idempotent when possible so a DB that was migrated manually still works.
