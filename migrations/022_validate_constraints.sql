-- Validate the NOT VALID checks and foreign keys added by 014. VALIDATE CONSTRAINT takes a
-- SHARE UPDATE EXCLUSIVE lock, so reads and writes continue. Apart from the clamp below, a
-- historic row that violates a check fails this migration with the constraint's name.

-- Sessions synced before 014 could store up to a second more active time than their
-- whole-second timestamps span (the app sends ISO-8601 seconds; active time is fractional).
-- Active time can't exceed elapsed time, so clamp it the way the app now does before upload.
UPDATE sessions
SET active_duration_seconds = EXTRACT(EPOCH FROM ended_at - started_at)
WHERE active_duration_seconds > EXTRACT(EPOCH FROM ended_at - started_at);

DO $$
DECLARE
    pending record;
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        -- Rows whose user was deleted before 014 added these keys (children cascade),
        -- cleaned up the same way 002/003/006 did. Routines first: they reference exercises.
        DELETE FROM strength_routines r
        WHERE NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id = r.user_id);
        DELETE FROM strength_week_assignments a
        WHERE NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id = a.user_id);
        DELETE FROM strength_preferences p
        WHERE NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id = p.user_id);
        DELETE FROM strength_bodyweights b
        WHERE NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id = b.user_id);
        DELETE FROM strength_exercises e
        WHERE e.owner_user_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM auth.users u WHERE u.id = e.owner_user_id);
    END IF;

    FOR pending IN
        SELECT conrelid::regclass AS table_name, conname
        FROM pg_constraint
        WHERE NOT convalidated AND connamespace = 'public'::regnamespace
    LOOP
        EXECUTE format('ALTER TABLE %s VALIDATE CONSTRAINT %I', pending.table_name, pending.conname);
    END LOOP;
END $$;
