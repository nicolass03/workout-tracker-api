-- Distinct move-session types plus hiking elevation data.
-- Keep `walk_run` valid so clients can continue to read historical sessions.

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS elevation_gain_meters DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS elevation_loss_meters DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS elevation_samples JSONB NOT NULL DEFAULT '[]';

DO $$
BEGIN
    ALTER TABLE sessions DROP CONSTRAINT IF EXISTS ck_sessions_type;
    ALTER TABLE sessions
        ADD CONSTRAINT ck_sessions_type
        CHECK (type IN ('walk_run', 'walk', 'run', 'jogging', 'hiking'));

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_sessions_elevation_gain_nonneg'
          AND conrelid = 'public.sessions'::regclass
    ) THEN
        ALTER TABLE sessions
            ADD CONSTRAINT ck_sessions_elevation_gain_nonneg
            CHECK (elevation_gain_meters IS NULL OR elevation_gain_meters >= 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_sessions_move_fields'
          AND conrelid = 'public.sessions'::regclass
    ) THEN
        ALTER TABLE sessions
            ADD CONSTRAINT ck_sessions_move_fields
            CHECK (
                type NOT IN ('walk_run', 'walk', 'run', 'jogging', 'hiking')
                OR (steps IS NOT NULL AND distance_meters IS NOT NULL)
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_sessions_elevation_loss_nonneg'
          AND conrelid = 'public.sessions'::regclass
    ) THEN
        ALTER TABLE sessions
            ADD CONSTRAINT ck_sessions_elevation_loss_nonneg
            CHECK (elevation_loss_meters IS NULL OR elevation_loss_meters >= 0);
    END IF;
END $$;
