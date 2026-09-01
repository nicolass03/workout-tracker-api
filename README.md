# Workout Tracker API

FastAPI backend connected to Supabase PostgreSQL.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set in `.env`:

- `DATABASE_URL` — Supabase Dashboard → Connect
- `SUPABASE_URL` — `https://<project-ref>.supabase.co`
- `SUPABASE_JWT_SECRET` — only if the project still signs with HS256 (legacy JWT secret)
- `REDIS_URL` — optional private Redis connection URL. Move map reads use it as a
  fail-open response cache; PostgreSQL remains the source of truth.

## Run

```bash
fastapi dev api.main:app
```

Or:

```bash
uvicorn api.main:app --reload
```

## Auth

The iOS app signs in with the Supabase client (using the **publishable** key `sb_publishable_...`, not the legacy anon key) and sends the access token:

```http
Authorization: Bearer <supabase_access_token>
```

The API verifies that JWT locally (no supabase-py). Use `Depends(get_current_user)` on protected routes.

- Asymmetric keys (ES256/RS256): verified via JWKS at `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`
- Legacy HS256: verified with `SUPABASE_JWT_SECRET`

Do not put publishable/secret API keys in `Authorization` — they are not JWTs.
## Database

Apply SQL migrations manually against Supabase Postgres (SQL editor, `psql`, or optionally `python scripts/migrate.py`):

```bash
# Apply every numbered migration through 019_session_map_previews.sql
# or: python scripts/migrate.py
```

Railway does not auto-run migrations on deploy.

## Endpoints

- `GET /health` — app status
- `GET /health/db` — Supabase Postgres connectivity (`SELECT 1`)
- `GET /auth/me` — current user from Bearer token (requires auth)
- `PUT /activity/days/{day}` — upsert daily trail + KPI snapshot (`YYYY-MM-DD`, requires auth)
- `GET /activity/days/{day}` — fetch one day’s activity including trail (requires auth)
- `GET /activity/days?from=&to=` — list days in range including trail (max 62 days, requires auth)
- `GET /sessions?from=&to=&includePoints=&pointLimit=` — list workout sessions. Set
  `includePoints=false` for metadata-only views, or use `pointLimit` (1–4000) for a
  downsampled trail.
- `GET /sessions/map?from=&to=&resolution=map` — compact Move map read model backed
  by precomputed 50/300/1000-point geometry variants (`preview`, `map`, `detail`).
  Responses support ETags and optional Redis caching.
- `POST /sessions?compact=true` — create idempotently without echoing full GPS
  metadata in the response.
- `PUT /sessions/{id}/trace-chunks/location/{section}/{chunk}` — idempotent raw-fix
  chunk upload (up to 512 fixes); `GET /sessions/{id}/trace-chunks` returns the
  retry manifest.
- `POST /sessions/{id}/trace-chunks/batch` — upload up to 32 idempotent chunks in
  one database transaction.
- `PUT /sessions/{id}/routes/{revision}` — store a versioned canonical route;
  `GET /sessions/{id}/routes/latest` retrieves it for future offline guidance.
- `POST /saved-routes` — snapshot a session's latest route as a reusable route;
  `GET /saved-routes` lists summaries and `GET/DELETE /saved-routes/{id}` retrieves
  route geometry or removes the saved route.
- `GET /strength/analytics/one-rm?days=365` — bounded 1RM history; `days` accepts
  1–3650.

Apply migrations `014_integrity_performance_and_rls.sql` through
`019_session_map_previews.sql` with the existing migrations.
It enables RLS for the public Data API. The API database role must own the tables or
otherwise have `BYPASSRLS`; verify this in staging before deploying the migration.

## Connection notes

- Use the **session pooler** or **direct** connection (`:5432`) for a long-running API server.
- Transaction pooler (`:6543`) is also supported; prepared statement caching is disabled automatically.

## Railway

Config lives in `railway.json` (Railpack, uvicorn on `$PORT`, `/health` check).

```bash
railway login
railway init   # or link an existing project
railway variable set DATABASE_URL=... SUPABASE_URL=...
# optional: SUPABASE_JWT_SECRET=... REDIS_URL=...
railway up
railway domain  # public HTTPS URL → set iOS API_BASE_URL
```
