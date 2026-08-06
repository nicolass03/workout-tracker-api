# Agent Notes

## Project constraints

- Use **SQLAlchemy 2.x async** with **asyncpg** for all database access.
- `DATABASE_URL` must be set via environment (`.env` locally). Never commit real credentials.
- Supabase transaction pooler (`:6543`) requires `statement_cache_size=0` and `prepared_statement_cache_size=0` with asyncpg; this is handled in `api/database.py`.
- For long-running servers, prefer Supabase **session pooler** (`*.pooler.supabase.com:5432`). Avoid direct `db.<ref>.supabase.co` unless the runtime has working IPv6.
- **IPv6 / errno 8 (local):** direct host `db.<ref>.supabase.co` is often **AAAA-only**. On machines without working IPv6, `python scripts/migrate.py` fails with `[Errno 8] nodename nor servname provided, or not known`. Use the **pooler** URL, or run SQL in the Supabase SQL editor.
- **IPv6 / errno 101 (Railway):** Railway → direct `db.<ref>.supabase.co` fails at runtime with `OSError: [Errno 101] Network is unreachable` (asyncpg connect). Symptom: `PUT /activity/days/{day}` → 500, nothing written to `daily_activity`. **Fix:** set Railway `DATABASE_URL` to the Supabase pooler URI (session `:5432` preferred; transaction `:6543` OK with statement caches disabled).
- Apply SQL migrations under `migrations/` manually (Supabase SQL editor, `psql`, or `python scripts/migrate.py`). Do not auto-run migrations on Railway deploy.

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
- Day KPIs (HealthKit) and `seg_steps` (CMPedometer) are **intentionally independent** — do not require Σ seg_steps == steps.
- Constraints (migration `002_…`): CHECK non-negative KPIs; `updated_at` BEFORE UPDATE trigger; `user_id` FK → `auth.users(id) ON DELETE CASCADE` when `auth.users` exists; no standalone `user_id` index (`UNIQUE (user_id, day)` covers it).
- PUT trail array capped at **4000** points (matches iOS downsample max).
- `PUT /activity/days/{day}` — idempotent upsert for the authenticated user.
- `GET /activity/days/{day}` — fetch one day including trail (404 if missing).
- `GET /activity/days?from=&to=` — list full day payloads including trail for inclusive range; max 62 days; `from` must be ≤ `to`. Same response shape as single-day GET.
- iOS syncs **completed** days only (local SwiftData → API), typically overnight + on foreground.
- iOS Steps tab: Daily uses GET single-day when local trail/KPIs are missing; Weekly/Monthly use range GET once, then merge with local today / unsynced days.
- Apply `001_daily_activity.sql` then `002_daily_activity_hardening.sql` on Supabase (002 deletes orphan `daily_activity` rows with no matching `auth.users` before adding the FK).

## Dependency management

- `uv` is not installed on this machine; use `venv` + `pip` with `requirements.txt`.
- Pinned versions live in both `pyproject.toml` and `requirements.txt`.

## App entrypoint

- `api.main:app` — run with `fastapi dev api.main:app` or `uvicorn api.main:app --reload`.

## Railway

- Deploy config is `railway.json` (Railpack + uvicorn on `$PORT`, healthcheck `/health`, timeout 300s). Migrations are **not** run on deploy.
- Python pin: `.python-version` → `3.12` (matches `requires-python` in `pyproject.toml`).
- Required service variables: `DATABASE_URL`, `SUPABASE_URL`. Optional: `SUPABASE_JWT_SECRET` (legacy HS256).
- **Railway `DATABASE_URL` must use the pooler** (`*.pooler.supabase.com`), not direct `db.*.supabase.co` (see errno 101 above). Session `:5432` preferred; transaction `:6543` works (prepared-statement cache disabled).
- After deploy: generate a public domain, set iOS `API_BASE_URL` to that origin (no trailing slash).
- Deploy from this repo root: `railway up` (or link a GitHub repo in the dashboard).

## Migrations

- Files: `migrations/*.sql` (lexicographic order, e.g. `001_…`, `002_…`).
- Apply manually: Supabase SQL editor, `psql`, or optionally `python scripts/migrate.py` (tracks `schema_migrations`).
- `scripts/migrate.py` needs the project venv (`source .venv/bin/activate` then `python scripts/migrate.py`) — imports SQLAlchemy/asyncpg via `api.*`. Or paste SQL in Supabase editor (no venv).
- Prefer idempotent SQL (`IF NOT EXISTS`).
- Railway does **not** auto-apply migrations on deploy.
- `migrate.py` statement splitter must respect `$tag$…$tag$` bodies (functions/`DO` blocks); naive `;` split breaks `002_…`.
