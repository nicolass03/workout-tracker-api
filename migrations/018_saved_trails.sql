-- User-curated reusable routes. Geometry is snapshotted so deleting the source
-- workout does not remove a trail the user intentionally saved.

CREATE TABLE IF NOT EXISTS saved_trails (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    source_session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    source_route_revision INTEGER NOT NULL,
    algorithm_version TEXT NOT NULL,
    graph_version TEXT,
    status TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    distance_meters DOUBLE PRECISION NOT NULL,
    sections JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_saved_trails_name CHECK (char_length(btrim(name)) BETWEEN 1 AND 100),
    CONSTRAINT ck_saved_trails_activity CHECK (
        activity_type IN ('walk_run', 'walk', 'run', 'jogging', 'hiking')
    ),
    CONSTRAINT ck_saved_trails_revision CHECK (source_route_revision >= 1),
    CONSTRAINT ck_saved_trails_status CHECK (
        status IN ('gps_only', 'partially_matched', 'matched')
    ),
    CONSTRAINT ck_saved_trails_confidence CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_saved_trails_distance CHECK (distance_meters >= 0),
    CONSTRAINT ck_saved_trails_sections CHECK (
        jsonb_typeof(sections) = 'array' AND jsonb_array_length(sections) > 0
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_saved_trails_user_source
    ON saved_trails(user_id, source_session_id)
    WHERE source_session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_saved_trails_user_updated
    ON saved_trails(user_id, updated_at DESC);

DROP TRIGGER IF EXISTS trg_saved_trails_set_updated_at ON saved_trails;
CREATE TRIGGER trg_saved_trails_set_updated_at
    BEFORE UPDATE ON saved_trails
    FOR EACH ROW EXECUTE PROCEDURE public.set_updated_at();

CREATE OR REPLACE FUNCTION public.validate_saved_trail_source_owner()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.source_session_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM sessions
        WHERE sessions.id = NEW.source_session_id
          AND sessions.user_id = NEW.user_id
    ) THEN
        RAISE EXCEPTION 'saved trail owner must own the source session'
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_saved_trails_validate_source_owner ON saved_trails;
CREATE TRIGGER trg_saved_trails_validate_source_owner
    BEFORE INSERT OR UPDATE OF source_session_id, user_id ON saved_trails
    FOR EACH ROW EXECUTE PROCEDURE public.validate_saved_trail_source_owner();

ALTER TABLE saved_trails ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        ALTER TABLE saved_trails
            DROP CONSTRAINT IF EXISTS saved_trails_user_id_fkey;
        ALTER TABLE saved_trails
            ADD CONSTRAINT saved_trails_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

        DROP POLICY IF EXISTS user_owns_row ON saved_trails;
        CREATE POLICY user_owns_row ON saved_trails
            FOR ALL TO authenticated
            USING ((select auth.uid()) = user_id)
            WITH CHECK ((select auth.uid()) = user_id);
    END IF;
END $$;
