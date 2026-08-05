-- Harden daily_activity: CHECKs, updated_at trigger, auth.users FK, drop redundant index.
-- UNIQUE (user_id, day) already covers lookups by user_id.

-- Non-negative KPI guards (Pydantic already enforces on write).
ALTER TABLE daily_activity DROP CONSTRAINT IF EXISTS ck_daily_activity_steps_nonneg;
ALTER TABLE daily_activity
    ADD CONSTRAINT ck_daily_activity_steps_nonneg CHECK (steps >= 0);

ALTER TABLE daily_activity DROP CONSTRAINT IF EXISTS ck_daily_activity_energy_nonneg;
ALTER TABLE daily_activity
    ADD CONSTRAINT ck_daily_activity_energy_nonneg CHECK (active_energy_kcal >= 0);

ALTER TABLE daily_activity DROP CONSTRAINT IF EXISTS ck_daily_activity_distance_nonneg;
ALTER TABLE daily_activity
    ADD CONSTRAINT ck_daily_activity_distance_nonneg CHECK (distance_meters >= 0);

-- Keep updated_at current on every UPDATE (ORM onupdate alone misses raw SQL).
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_daily_activity_set_updated_at ON daily_activity;
CREATE TRIGGER trg_daily_activity_set_updated_at
    BEFORE UPDATE ON daily_activity
    FOR EACH ROW
    EXECUTE PROCEDURE public.set_updated_at();

-- Covered by uq_daily_activity_user_day (user_id, day).
DROP INDEX IF EXISTS ix_daily_activity_user_id;

-- Soft-link → real FK when running on Supabase (auth.users present).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        -- Drop orphan rows that would block the FK (no matching auth user).
        DELETE FROM daily_activity da
        WHERE NOT EXISTS (
            SELECT 1 FROM auth.users u WHERE u.id = da.user_id
        );

        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'fk_daily_activity_user'
              AND conrelid = 'public.daily_activity'::regclass
        ) THEN
            ALTER TABLE daily_activity
                ADD CONSTRAINT fk_daily_activity_user
                FOREIGN KEY (user_id) REFERENCES auth.users (id) ON DELETE CASCADE;
        END IF;
    END IF;
END $$;
