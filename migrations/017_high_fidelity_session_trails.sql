-- Lossless, resumable trail capture plus versioned canonical routes.
-- Legacy session_segments remains the compatibility/read-summary representation.

CREATE TABLE IF NOT EXISTS session_trace_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    kind TEXT NOT NULL DEFAULT 'location',
    section_index INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    first_at TIMESTAMPTZ NOT NULL,
    last_at TIMESTAMPTZ NOT NULL,
    sample_count INTEGER NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    samples JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_session_trace_chunk UNIQUE (session_id, kind, section_index, chunk_index),
    CONSTRAINT ck_session_trace_chunk_kind CHECK (kind IN ('location', 'motion')),
    CONSTRAINT ck_session_trace_chunk_indexes CHECK (section_index >= 0 AND chunk_index >= 0),
    CONSTRAINT ck_session_trace_chunk_times CHECK (last_at >= first_at),
    CONSTRAINT ck_session_trace_chunk_count CHECK (
        sample_count BETWEEN 1 AND 512
        AND jsonb_typeof(samples) = 'array'
        AND jsonb_array_length(samples) = sample_count
    ),
    CONSTRAINT ck_session_trace_chunk_checksum CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS ix_session_trace_chunks_manifest
    ON session_trace_chunks(session_id, kind, section_index, chunk_index);

CREATE TABLE IF NOT EXISTS session_routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    algorithm_version TEXT NOT NULL,
    graph_version TEXT,
    status TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    distance_meters DOUBLE PRECISION NOT NULL,
    quality JSONB NOT NULL DEFAULT '{}',
    sections JSONB NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_session_routes_revision UNIQUE(session_id, revision),
    CONSTRAINT ck_session_routes_revision CHECK (revision >= 1),
    CONSTRAINT ck_session_routes_status CHECK (
        status IN ('gps_only', 'partially_matched', 'matched')
    ),
    CONSTRAINT ck_session_routes_confidence CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_session_routes_distance CHECK (distance_meters >= 0),
    CONSTRAINT ck_session_routes_sections CHECK (jsonb_typeof(sections) = 'array')
);

CREATE INDEX IF NOT EXISTS ix_session_routes_latest
    ON session_routes(session_id, revision DESC);

DROP TRIGGER IF EXISTS trg_session_trace_chunks_set_updated_at ON session_trace_chunks;
CREATE TRIGGER trg_session_trace_chunks_set_updated_at
    BEFORE UPDATE ON session_trace_chunks
    FOR EACH ROW EXECUTE PROCEDURE public.set_updated_at();

DROP TRIGGER IF EXISTS trg_session_routes_set_updated_at ON session_routes;
CREATE TRIGGER trg_session_routes_set_updated_at
    BEFORE UPDATE ON session_routes
    FOR EACH ROW EXECUTE PROCEDURE public.set_updated_at();

CREATE OR REPLACE FUNCTION public.validate_session_trail_owner()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM sessions
        WHERE sessions.id = NEW.session_id AND sessions.user_id = NEW.user_id
    ) THEN
        RAISE EXCEPTION 'trail owner must own the parent session'
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_session_trace_chunks_validate_owner ON session_trace_chunks;
CREATE TRIGGER trg_session_trace_chunks_validate_owner
    BEFORE INSERT OR UPDATE OF session_id, user_id ON session_trace_chunks
    FOR EACH ROW EXECUTE PROCEDURE public.validate_session_trail_owner();

DROP TRIGGER IF EXISTS trg_session_routes_validate_owner ON session_routes;
CREATE TRIGGER trg_session_routes_validate_owner
    BEFORE INSERT OR UPDATE OF session_id, user_id ON session_routes
    FOR EACH ROW EXECUTE PROCEDURE public.validate_session_trail_owner();

ALTER TABLE session_trace_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_routes ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        DROP POLICY IF EXISTS user_owns_row ON session_trace_chunks;
        CREATE POLICY user_owns_row ON session_trace_chunks
            FOR ALL TO authenticated
            USING ((select auth.uid()) = user_id)
            WITH CHECK ((select auth.uid()) = user_id);

        DROP POLICY IF EXISTS user_owns_row ON session_routes;
        CREATE POLICY user_owns_row ON session_routes
            FOR ALL TO authenticated
            USING ((select auth.uid()) = user_id)
            WITH CHECK ((select auth.uid()) = user_id);
    END IF;
END $$;
