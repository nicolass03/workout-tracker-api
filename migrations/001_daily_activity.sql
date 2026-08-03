CREATE TABLE IF NOT EXISTS daily_activity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    day DATE NOT NULL,
    steps INTEGER NOT NULL DEFAULT 0,
    active_energy_kcal DOUBLE PRECISION NOT NULL DEFAULT 0,
    distance_meters DOUBLE PRECISION NOT NULL DEFAULT 0,
    trail JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_daily_activity_user_day UNIQUE (user_id, day)
);

CREATE INDEX IF NOT EXISTS ix_daily_activity_user_id ON daily_activity (user_id);
