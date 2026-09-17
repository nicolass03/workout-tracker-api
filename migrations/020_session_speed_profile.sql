-- Per-session speed curve derived from the GNSS Doppler speed already captured in
-- session_segments.points. Drives the speed-over-time chart and the speed-shaded trail.
-- Each sample is {"t": seconds from sessions.started_at, "d": cumulative meters,
-- "v": meters per second, "seg": recording section index}.

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS speed_samples JSONB NOT NULL DEFAULT '[]';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_sessions_speed_samples'
          AND conrelid = 'public.sessions'::regclass
    ) THEN
        ALTER TABLE sessions
            ADD CONSTRAINT ck_sessions_speed_samples
            CHECK (jsonb_typeof(speed_samples) = 'array');
    END IF;
END $$;
