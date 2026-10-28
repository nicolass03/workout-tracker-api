# Agent Notes

## Project constraints

- Use **SQLAlchemy 2.x async** with **asyncpg** for all database access.
- `DATABASE_URL` must be set via environment (`.env` locally). Never commit real credentials.
- Supabase transaction pooler (`:6543`) requires `statement_cache_size=0` and `prepared_statement_cache_size=0` with asyncpg; this is handled in `api/database.py`.
- For long-running servers, prefer Supabase **session pooler** (`*.pooler.supabase.com:5432`). Avoid direct `db.<ref>.supabase.co` unless the runtime has working IPv6.
- **IPv6 / errno 8 (local):** direct host `db.<ref>.supabase.co` is often **AAAA-only**. On machines without working IPv6, `python scripts/migrate.py` fails with `[Errno 8] nodename nor servname provided, or not known`. Use the **pooler** URL, or run SQL in the Supabase SQL editor.
- **IPv6 / errno 101 (Railway):** Railway → direct `db.<ref>.supabase.co` fails at runtime with `OSError: [Errno 101] Network is unreachable` (asyncpg connect). Symptom: every database-backed route (e.g. `POST /sessions`) → 500. **Fix:** set Railway `DATABASE_URL` to the Supabase pooler URI (session `:5432` preferred; transaction `:6543` OK with statement caches disabled).
- Apply SQL migrations under `migrations/` manually (Supabase SQL editor, `psql`, or `python scripts/migrate.py`). Do not auto-run migrations on Railway deploy.

## Auth

- Auth happens on the **client** (Supabase SDK with **publishable** key `sb_publishable_...`, not legacy `anon`). The API does **not** use supabase-py.
- Protect routes with `Depends(get_current_user)` from `api.auth`.
- Clients must send `Authorization: Bearer <access_token>` (user JWT). Do not put publishable/secret keys in `Authorization` — they are not JWTs.
- Token verification is local via PyJWT:
  - Asymmetric (ES256/RS256): JWKS from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`
  - Legacy HS256: `SUPABASE_JWT_SECRET`
- Required env: `SUPABASE_URL`. Optional: `SUPABASE_JWT_SECRET` for HS256 projects.
- An unknown `kid` refetches the JWKS at most once a minute (`_ThrottledJWKClient`); PyJWT would otherwise make an outbound request per forged token.
- `DELETE /auth/me` deletes the account: strength workouts/routines first (they RESTRICT-reference the user's custom exercises), then `DELETE FROM auth.users` on the API's own connection; every other user-owned row cascades. Needs DELETE on `auth.users` for the API's role (`select has_table_privilege('auth.users', 'DELETE')`). Sign in with Apple token revocation is not implemented (needs the Apple `.p8` key server-side).

## Errors and limits

- Unique/foreign-key violations (`23505`/`23503`) return 409: duplicate client ids, a create race, or a parent deleted mid-request. Retrying an idempotent create after a 409 replays it.
- Unhandled exceptions are logged on `workout_tracker.errors` with the request id, and the 500 carries `X-Request-ID`.
- Request bodies are capped at 16 MiB (`BodySizeLimitMiddleware`); FastAPI buffers and parses the body before auth runs.

## Daily activity (legacy)

- Table `daily_activity`: one row per `(user_id, day)` with steps, active_energy_kcal, distance_meters, and `trail` JSONB.
- **Legacy data only** — workout trails/metrics live in `sessions` + `session_segments`. The `/activity/*` endpoints and ORM model are removed (the app had stopped calling them); the table and its rows stay until a deliberate drop.
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
  - `GET /sessions?from=&to=` — inclusive calendar days on `started_at` with **±14h UTC pad** so local midnights are not missed; clients still group by local `Calendar` day; max 62 days. `includePoints=false` omits the trail and the elevation/speed series
  - `DELETE /sessions/{id}` — one Core `DELETE`; foreign keys cascade segments, chunks, routes and previews
- ORM class is `WorkoutSession` (table name `sessions`) to avoid clashing with SQLAlchemy `Session`.
- No automatic backfill from historical `daily_activity.trail`.
- Apply **`019_session_map_previews.sql`** for the compact `/sessions/map` read model, then
  run `python scripts/backfill_map_previews.py` once (idempotent) for sessions created
  before it: reads no longer materialize previews, and `/sessions/history` `has_trail`
  comes from them. New sessions and canonical-route writes keep the 50/300/1000-point
  variants current (hard caps; simplification runs in a worker thread).
- Trail data roles: `session_segments.points` = synced fixes (metrics/detail);
  `session_routes` = display geometry (iOS always writes revision 1);
  `session_map_previews` = derived cache; `session_trace_chunks` = raw archive (only the
  upload manifest is read back; `kind=location` only); `saved_routes.sections` = user
  snapshot that survives session deletion.
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

## Strength

- Weights are stored in kg (`NUMERIC(…, 3)`); `strength_preferences.weight_unit` only controls conversion, and lb output is rounded to 0.01 so stored kg round-trips cleanly. `PUT /strength/preferences` switches the unit.
- `DELETE /strength/workouts/{id}` cascades the workout's exercises and sets.
- Analytics take an optional `today` (the client's local date): `workout_date` is the client's calendar day, so the server's UTC date must not anchor the windows. Heatmap levels are quartiles of daily totals.
- `strength_bodyweights` only holds rows migrated from the old strength state; no API or ORM model.

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
- `021_schema_migrations_rls.sql` enables RLS on `migrate.py`'s bookkeeping table, which the Data API otherwise exposes to `anon`.
- `022_validate_constraints.sql` validates 014's `NOT VALID` checks/foreign keys after deleting orphan rows; a historic row that violates a check fails it, naming the constraint.

## Tests

- `python -m unittest discover -s tests` runs everything; `tests/test_api.py` is skipped unless `TEST_DATABASE_URL` points at a migrated **throwaway** Postgres (it writes data — never Supabase):

```bash
docker run -d --name wt-api-test-pg -e POSTGRES_PASSWORD=postgres -p 55432:5432 postgres:17-alpine
until docker exec wt-api-test-pg pg_isready -U postgres -q; do sleep 1; done
docker exec -i wt-api-test-pg psql -U postgres < tests/supabase_stub.sql
DATABASE_URL=postgresql://postgres:postgres@localhost:55432/postgres python scripts/migrate.py
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/postgres python -m unittest discover -s tests
```
