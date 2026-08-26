-- Completed strength sessions are immutable history, not part of the mutable plan state.

CREATE TABLE IF NOT EXISTS strength_workouts (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    workout_date DATE NOT NULL,
    name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    entries JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_strength_workouts_ended_after_start CHECK (ended_at >= started_at),
    CONSTRAINT ck_strength_workouts_name_nonempty CHECK (char_length(btrim(name)) > 0),
    CONSTRAINT ck_strength_workouts_entries_array CHECK (jsonb_typeof(entries) = 'array')
);

CREATE INDEX IF NOT EXISTS ix_strength_workouts_user_date_ended
    ON strength_workouts (user_id, workout_date, ended_at, id);

DROP TRIGGER IF EXISTS trg_strength_workouts_set_updated_at ON strength_workouts;
CREATE TRIGGER trg_strength_workouts_set_updated_at
    BEFORE UPDATE ON strength_workouts
    FOR EACH ROW
    EXECUTE PROCEDURE public.set_updated_at();

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_strength_workouts_user'
          AND conrelid = 'public.strength_workouts'::regclass
    ) THEN
        ALTER TABLE strength_workouts
            ADD CONSTRAINT fk_strength_workouts_user
            FOREIGN KEY (user_id) REFERENCES auth.users (id) ON DELETE CASCADE;
    END IF;
END $$;

-- Existing native clients stored the same GymWorkout JSON under strength_state.state.workouts.
-- The app only emits valid UUIDs, local yyyy-MM-dd dates, and ISO-8601 timestamps.
INSERT INTO strength_workouts (
    id,
    user_id,
    workout_date,
    name,
    started_at,
    ended_at,
    entries
)
SELECT
    (workout ->> 'id')::uuid,
    state.user_id,
    (workout ->> 'date')::date,
    workout ->> 'name',
    (workout ->> 'startedAt')::timestamptz,
    (workout ->> 'endedAt')::timestamptz,
    COALESCE(workout -> 'entries', '[]'::jsonb)
FROM strength_state AS state
CROSS JOIN LATERAL jsonb_array_elements(
    CASE
        WHEN jsonb_typeof(state.state -> 'workouts') = 'array' THEN state.state -> 'workouts'
        ELSE '[]'::jsonb
    END
) AS workout
WHERE workout ->> 'id' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
  AND workout ->> 'date' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
  AND btrim(COALESCE(workout ->> 'name', '')) <> ''
  AND workout ? 'startedAt'
  AND workout ? 'endedAt'
  AND jsonb_typeof(COALESCE(workout -> 'entries', '[]'::jsonb)) = 'array'
ON CONFLICT (id) DO NOTHING;

UPDATE strength_state
SET state = state - 'workouts'
WHERE state ? 'workouts';
