-- Data integrity, scalable search/analytics, and direct Supabase Data API protection.
-- Existing rows are left untouched; NOT VALID constraints apply to new writes now and
-- can be validated after any historic-data remediation.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS ix_strength_workouts_user_ended_at
    ON strength_workouts (user_id, ended_at DESC);

CREATE INDEX IF NOT EXISTS ix_strength_exercises_active_name_trgm
    ON strength_exercises USING gin (name gin_trgm_ops)
    WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_strength_exercises_active_target_trgm
    ON strength_exercises USING gin (target_muscle gin_trgm_ops)
    WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_strength_exercises_active_equipment_trgm
    ON strength_exercises USING gin (equipment gin_trgm_ops)
    WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_strength_exercises_active_body_part_trgm
    ON strength_exercises USING gin (body_part gin_trgm_ops)
    WHERE archived_at IS NULL;

ALTER TABLE sessions DROP CONSTRAINT IF EXISTS ck_sessions_type;
ALTER TABLE sessions
    ADD CONSTRAINT ck_sessions_type CHECK (type = 'walk_run') NOT VALID;
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS ck_sessions_active_duration_elapsed;
ALTER TABLE sessions
    ADD CONSTRAINT ck_sessions_active_duration_elapsed CHECK (
        active_duration_seconds <= EXTRACT(EPOCH FROM ended_at - started_at)
    ) NOT VALID;
ALTER TABLE session_segments DROP CONSTRAINT IF EXISTS ck_session_segments_ended_after_start;
ALTER TABLE session_segments
    ADD CONSTRAINT ck_session_segments_ended_after_start CHECK (
        ended_at IS NULL OR ended_at >= started_at
    ) NOT VALID;

ALTER TABLE strength_routines DROP CONSTRAINT IF EXISTS ck_strength_routines_name_nonempty;
ALTER TABLE strength_routines
    ADD CONSTRAINT ck_strength_routines_name_nonempty
    CHECK (char_length(btrim(name)) > 0) NOT VALID;
ALTER TABLE strength_routines DROP CONSTRAINT IF EXISTS ck_strength_routines_progression;
ALTER TABLE strength_routines
    ADD CONSTRAINT ck_strength_routines_progression
    CHECK (progression IN ('off', 'linear', 'double', 'time')) NOT VALID;

CREATE OR REPLACE FUNCTION public.validate_session_segment_times()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    parent_session sessions%ROWTYPE;
BEGIN
    SELECT * INTO parent_session FROM sessions WHERE id = NEW.session_id;
    IF FOUND AND (
        NEW.started_at < parent_session.started_at
        OR (NEW.ended_at IS NOT NULL AND NEW.ended_at > parent_session.ended_at)
    ) THEN
        RAISE EXCEPTION 'session segment timestamps must fall within the parent session'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_session_segments_validate_times ON session_segments;
CREATE TRIGGER trg_session_segments_validate_times
    BEFORE INSERT OR UPDATE OF session_id, started_at, ended_at ON session_segments
    FOR EACH ROW EXECUTE PROCEDURE public.validate_session_segment_times();

CREATE OR REPLACE FUNCTION public.enforce_frequent_places_limit()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext(NEW.user_id::text));
    IF (SELECT count(*) FROM frequent_places WHERE user_id = NEW.user_id) >= 20 THEN
        RAISE EXCEPTION 'maximum of 20 frequent places allowed'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_frequent_places_limit ON frequent_places;
CREATE TRIGGER trg_frequent_places_limit
    BEFORE INSERT ON frequent_places
    FOR EACH ROW EXECUTE PROCEDURE public.enforce_frequent_places_limit();

DROP TRIGGER IF EXISTS trg_strength_routines_set_updated_at ON strength_routines;
CREATE TRIGGER trg_strength_routines_set_updated_at
    BEFORE UPDATE ON strength_routines
    FOR EACH ROW EXECUTE PROCEDURE public.set_updated_at();
DROP TRIGGER IF EXISTS trg_strength_week_assignments_set_updated_at ON strength_week_assignments;
CREATE TRIGGER trg_strength_week_assignments_set_updated_at
    BEFORE UPDATE ON strength_week_assignments
    FOR EACH ROW EXECUTE PROCEDURE public.set_updated_at();

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_strength_routines_user') THEN
            ALTER TABLE strength_routines
                ADD CONSTRAINT fk_strength_routines_user
                FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE NOT VALID;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_strength_week_assignments_user') THEN
            ALTER TABLE strength_week_assignments
                ADD CONSTRAINT fk_strength_week_assignments_user
                FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE NOT VALID;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_strength_preferences_user') THEN
            ALTER TABLE strength_preferences
                ADD CONSTRAINT fk_strength_preferences_user
                FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE NOT VALID;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_strength_bodyweights_user') THEN
            ALTER TABLE strength_bodyweights
                ADD CONSTRAINT fk_strength_bodyweights_user
                FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE NOT VALID;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_strength_exercises_owner_user') THEN
            ALTER TABLE strength_exercises
                ADD CONSTRAINT fk_strength_exercises_owner_user
                FOREIGN KEY (owner_user_id) REFERENCES auth.users(id) ON DELETE CASCADE NOT VALID;
        END IF;
    END IF;
END $$;

ALTER TABLE daily_activity ENABLE ROW LEVEL SECURITY;
ALTER TABLE frequent_places ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_segments ENABLE ROW LEVEL SECURITY;
ALTER TABLE strength_exercises ENABLE ROW LEVEL SECURITY;
ALTER TABLE strength_exercise_instructions ENABLE ROW LEVEL SECURITY;
ALTER TABLE strength_exercise_muscles ENABLE ROW LEVEL SECURITY;
ALTER TABLE strength_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE strength_bodyweights ENABLE ROW LEVEL SECURITY;
ALTER TABLE strength_routines ENABLE ROW LEVEL SECURITY;
ALTER TABLE strength_routine_exercises ENABLE ROW LEVEL SECURITY;
ALTER TABLE strength_week_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE strength_workouts ENABLE ROW LEVEL SECURITY;
ALTER TABLE strength_workout_exercises ENABLE ROW LEVEL SECURITY;
ALTER TABLE strength_workout_sets ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    policy_table text;
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE tables.table_schema = 'auth' AND tables.table_name = 'users'
    ) THEN
        FOREACH policy_table IN ARRAY ARRAY[
            'daily_activity', 'frequent_places', 'sessions', 'strength_preferences',
            'strength_bodyweights', 'strength_routines', 'strength_week_assignments',
            'strength_workouts'
        ] LOOP
            EXECUTE format('DROP POLICY IF EXISTS user_owns_row ON public.%I', policy_table);
            EXECUTE format(
                'CREATE POLICY user_owns_row ON public.%I FOR ALL TO authenticated '
                || 'USING ((select auth.uid()) = user_id) '
                || 'WITH CHECK ((select auth.uid()) = user_id)',
                policy_table
            );
        END LOOP;

        DROP POLICY IF EXISTS catalog_or_owner_select ON strength_exercises;
        CREATE POLICY catalog_or_owner_select ON strength_exercises
            FOR SELECT TO authenticated
            USING (is_catalog OR owner_user_id = (select auth.uid()));
        DROP POLICY IF EXISTS custom_exercise_owner_write ON strength_exercises;
        CREATE POLICY custom_exercise_owner_write ON strength_exercises
            FOR ALL TO authenticated
            USING (NOT is_catalog AND owner_user_id = (select auth.uid()))
            WITH CHECK (NOT is_catalog AND owner_user_id = (select auth.uid()));
    END IF;
END $$;
