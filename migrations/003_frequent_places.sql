-- Frequent places: quiet zones used by iOS to gate pocket GPS trail recording.

CREATE TABLE IF NOT EXISTS frequent_places (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    name TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    radius_meters DOUBLE PRECISION NOT NULL DEFAULT 150,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_frequent_places_radius CHECK (radius_meters >= 100 AND radius_meters <= 400),
    CONSTRAINT ck_frequent_places_lat CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT ck_frequent_places_lon CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT ck_frequent_places_name_nonempty CHECK (char_length(btrim(name)) > 0)
);

CREATE INDEX IF NOT EXISTS ix_frequent_places_user_id ON frequent_places (user_id);

-- Reuse set_updated_at() from 002 (CREATE OR REPLACE is safe if 002 already ran).
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_frequent_places_set_updated_at ON frequent_places;
CREATE TRIGGER trg_frequent_places_set_updated_at
    BEFORE UPDATE ON frequent_places
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
        DELETE FROM frequent_places fp
        WHERE NOT EXISTS (
            SELECT 1 FROM auth.users u WHERE u.id = fp.user_id
        );

        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'fk_frequent_places_user'
              AND conrelid = 'public.frequent_places'::regclass
        ) THEN
            ALTER TABLE frequent_places
                ADD CONSTRAINT fk_frequent_places_user
                FOREIGN KEY (user_id) REFERENCES auth.users (id) ON DELETE CASCADE;
        END IF;
    END IF;
END $$;
