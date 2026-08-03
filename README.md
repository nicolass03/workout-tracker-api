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

Apply SQL migrations against Supabase Postgres (SQL editor or `psql`):

```bash
# migrations/001_daily_activity.sql
```

## Endpoints

- `GET /health` — app status
- `GET /health/db` — Supabase Postgres connectivity (`SELECT 1`)
- `GET /auth/me` — current user from Bearer token (requires auth)
- `PUT /activity/days/{day}` — upsert daily trail + KPI snapshot (`YYYY-MM-DD`, requires auth)
- `GET /activity/days/{day}` — fetch one day’s activity (requires auth)

## Connection notes

- Use the **session pooler** or **direct** connection (`:5432`) for a long-running API server.
- Transaction pooler (`:6543`) is also supported; prepared statement caching is disabled automatically.

## Railway

Config lives in `railway.json` (Railpack, uvicorn on `$PORT`, `/health` check).

```bash
railway login
railway init   # or link an existing project
railway variable set DATABASE_URL=... SUPABASE_URL=...
# optional: SUPABASE_JWT_SECRET=...
railway up
railway domain  # public HTTPS URL → set iOS API_BASE_URL
```
