CREATE TABLE IF NOT EXISTS strength_routines (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    name TEXT NOT NULL,
    symbol_name TEXT NOT NULL DEFAULT 'dumbbell',
    progression TEXT NOT NULL DEFAULT 'linear',
    exercises JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_strength_routines_user_id
    ON strength_routines (user_id);

CREATE TABLE IF NOT EXISTS strength_week_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    weekday INTEGER NOT NULL,
    routine_id UUID NULL REFERENCES strength_routines(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_strength_week_assignments_user_weekday UNIQUE (user_id, weekday),
    CONSTRAINT ck_strength_week_assignments_weekday CHECK (weekday >= 0 AND weekday <= 6)
);

CREATE INDEX IF NOT EXISTS ix_strength_week_assignments_user_id
    ON strength_week_assignments (user_id);
