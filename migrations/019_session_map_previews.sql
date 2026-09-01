-- Compact, precomputed geometry used by Move range maps. Full-fidelity points
-- remain in session_segments/session_trace_chunks/session_routes.

CREATE TABLE IF NOT EXISTS session_map_previews (
    session_id UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    source_revision INTEGER,
    preview_sections JSONB NOT NULL DEFAULT '[]',
    map_sections JSONB NOT NULL DEFAULT '[]',
    detail_sections JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_session_map_previews_revision CHECK (
        source_revision IS NULL OR source_revision >= 1
    ),
    CONSTRAINT ck_session_map_previews_shapes CHECK (
        jsonb_typeof(preview_sections) = 'array'
        AND jsonb_typeof(map_sections) = 'array'
        AND jsonb_typeof(detail_sections) = 'array'
    )
);

CREATE INDEX IF NOT EXISTS ix_session_map_previews_user
    ON session_map_previews(user_id, updated_at DESC);

DROP TRIGGER IF EXISTS trg_session_map_previews_set_updated_at ON session_map_previews;
CREATE TRIGGER trg_session_map_previews_set_updated_at
    BEFORE UPDATE ON session_map_previews
    FOR EACH ROW EXECUTE PROCEDURE public.set_updated_at();

DROP TRIGGER IF EXISTS trg_session_map_previews_validate_owner ON session_map_previews;
CREATE TRIGGER trg_session_map_previews_validate_owner
    BEFORE INSERT OR UPDATE OF session_id, user_id ON session_map_previews
    FOR EACH ROW EXECUTE PROCEDURE public.validate_session_trail_owner();

ALTER TABLE session_map_previews ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        DROP POLICY IF EXISTS user_owns_row ON session_map_previews;
        CREATE POLICY user_owns_row ON session_map_previews
            FOR ALL TO authenticated
            USING ((select auth.uid()) = user_id)
            WITH CHECK ((select auth.uid()) = user_id);
    END IF;
END $$;
