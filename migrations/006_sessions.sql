-- First-class workout sessions + GPS segments (trail reconstruct via session_id).
-- Day KPIs remain HealthKit on iOS; daily_activity trail is legacy.

CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    type TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    active_duration_seconds DOUBLE PRECISION NOT NULL,
    active_energy_kcal DOUBLE PRECISION NOT NULL,
    steps INTEGER,
    distance_meters DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sessions_ended_after_start CHECK (ended_at >= started_at),
    CONSTRAINT ck_sessions_active_duration_nonneg CHECK (active_duration_seconds >= 0),
    CONSTRAINT ck_sessions_energy_nonneg CHECK (active_energy_kcal >= 0),
    CONSTRAINT ck_sessions_steps_nonneg CHECK (steps IS NULL OR steps >= 0),
    CONSTRAINT ck_sessions_distance_nonneg CHECK (distance_meters IS NULL OR distance_meters >= 0),
    CONSTRAINT ck_sessions_walk_run_fields CHECK (
        type <> 'walk_run'
        OR (steps IS NOT NULL AND distance_meters IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_sessions_user_started_at
    ON sessions (user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS session_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    steps INTEGER NOT NULL DEFAULT 0,
    points JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_session_segments_session_idx UNIQUE (session_id, idx),
    CONSTRAINT ck_session_segments_idx_nonneg CHECK (idx >= 0),
    CONSTRAINT ck_session_segments_steps_nonneg CHECK (steps >= 0)
);

CREATE INDEX IF NOT EXISTS ix_session_segments_session_idx
    ON session_segments (session_id, idx);

-- Reuse set_updated_at() from 002.
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sessions_set_updated_at ON sessions;
CREATE TRIGGER trg_sessions_set_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW
    EXECUTE PROCEDURE public.set_updated_at();

-- Soft-link → real FK when running on Supabase (auth.users present).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        DELETE FROM sessions s
        WHERE NOT EXISTS (
            SELECT 1 FROM auth.users u WHERE u.id = s.user_id
        );

        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'fk_sessions_user'
              AND conrelid = 'public.sessions'::regclass
        ) THEN
            ALTER TABLE sessions
                ADD CONSTRAINT fk_sessions_user
                FOREIGN KEY (user_id) REFERENCES auth.users (id) ON DELETE CASCADE;
        END IF;
    END IF;
END $$;
