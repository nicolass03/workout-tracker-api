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

## Daily activity (legacy)

- Table `daily_activity`: one row per `(user_id, day)` with steps, active_energy_kcal, distance_meters, and `trail` JSONB.
- **Deprecated for new iOS writes** — workout trails/metrics now live in `sessions` + `session_segments`. Keep `/activity/days*` for older data until a follow-up migration drops the table/column.
- Trail point shape (legacy): `{lat, lon, t, seg?, seg_steps?}`.
- Constraints (migration `002_…`): CHECK non-negative KPIs; `updated_at` BEFORE UPDATE trigger; `user_id` FK → `auth.users(id) ON DELETE CASCADE` when `auth.users` exists.
- Apply `001_daily_activity.sql` then `002_daily_activity_hardening.sql` on Supabase.
- Apply `003_frequent_places.sql` for Frequent Places sync.
- Apply `004_frequent_places_radius.sql` to set radius CHECK to 10–250 m.
- Apply `005_frequent_places_address.sql` for optional `address` text on places.
- Apply **`006_sessions.sql`** for workout sessions + segments (required for current iOS).

## Sessions (current)

- Hybrid model: **day KPIs are HealthKit on iOS** (includes non-workout steps). API `sessions` store registered workouts only.
- Table `sessions` (STI): `type` discriminator (`walk_run`), base fields `started_at`, `ended_at`, `active_duration_seconds`, `active_energy_kcal`; walk_run also requires `steps`, `distance_meters`.
- Table `session_segments`: one row per GPS segment; `session_id` FK **ON DELETE CASCADE**; `idx` order; `points` JSONB `[{lat,lon,t}]`. Reconstruct trail with `ORDER BY idx`.
- Total points across segments capped at **4000** (API validation on create).
- Endpoints:
  - `POST /sessions` — create session + segments in one transaction (client may supply `id`; idempotent if same user owns id)
  - `GET /sessions/{id}`
  - `GET /sessions?from=&to=` — inclusive calendar days on `started_at` with **±14h UTC pad** so local midnights are not missed; clients still group by local `Calendar` day; max 62 days
  - `DELETE /sessions/{id}` — cascades segments
- ORM class is `WorkoutSession` (table name `sessions`) to avoid clashing with SQLAlchemy `Session`.
- No automatic backfill from historical `daily_activity.trail`.
- Apply **`019_session_map_previews.sql`** for the compact `/sessions/map` read model.
  The first read lazily materializes previews for existing sessions; new sessions and
  canonical-route writes keep 50/300/1000-point preview variants current.
- Optional `REDIS_URL` enables fail-open, per-user cache-aside storage for serialized
  Move map ranges. PostgreSQL remains authoritative; session/route mutations invalidate
  cached generations. Keep Redis private and configure an allkeys LRU/LFU eviction policy.
- `POST /sessions?compact=true` avoids echoing raw point metadata back to clients.
  `POST /sessions/{id}/trace-chunks/batch` stores up to 32 chunks in one transaction.
- iOS discards orphan local sessions with `syncStatus == recording` on launch (app-kill leftovers).

## Frequent places

- Table `frequent_places`: id, user_id, name, latitude, longitude, radius_meters (10–250, default 150), timestamps.
- Max **20** places per user (enforced on `POST /places`; matches iOS `CLMonitor` condition cap).
- `GET /places` — list for authenticated user.
- `POST /places` — create (optional client-supplied `id` UUID so iOS geofence ids stay stable).
- `PUT /places/{id}` / `DELETE /places/{id}` — own rows only.
- `updated_at` trigger reuses `set_updated_at()`; optional `auth.users` FK via same `DO $$` guard as 002.
- iOS: Frequent Places are synced for future use; they do **not** currently gate GPS trail recording (manual sessions only).

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
