-- Synced strength-training plan/history document for the native Gym MVP.
-- Walk/run GPS workouts remain in sessions + session_segments.

CREATE TABLE IF NOT EXISTS strength_state (
    user_id UUID PRIMARY KEY,
    state JSONB NOT NULL DEFAULT '{}',
    client_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_strength_state_set_updated_at ON strength_state;
CREATE TRIGGER trg_strength_state_set_updated_at
    BEFORE UPDATE ON strength_state
    FOR EACH ROW
    EXECUTE PROCEDURE public.set_updated_at();

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        DELETE FROM strength_state s
        WHERE NOT EXISTS (
            SELECT 1 FROM auth.users u WHERE u.id = s.user_id
        );

        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'fk_strength_state_user'
              AND conrelid = 'public.strength_state'::regclass
        ) THEN
            ALTER TABLE strength_state
                ADD CONSTRAINT fk_strength_state_user
                FOREIGN KEY (user_id) REFERENCES auth.users (id) ON DELETE CASCADE;
        END IF;
    END IF;
END $$;
