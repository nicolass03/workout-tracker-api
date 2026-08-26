-- Relational strength model. Catalogue rows are seeded by 011 before 012 backfills user data.

CREATE TABLE IF NOT EXISTS strength_exercises (
    id TEXT PRIMARY KEY,
    owner_user_id UUID NULL,
    name TEXT NOT NULL,
    body_part TEXT NOT NULL DEFAULT '',
    equipment TEXT NOT NULL DEFAULT '',
    target_muscle TEXT NOT NULL DEFAULT '',
    image_key TEXT NULL,
    gif_key TEXT NULL,
    is_catalog BOOLEAN NOT NULL DEFAULT FALSE,
    archived_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_strength_exercises_name_nonempty CHECK (char_length(btrim(name)) > 0),
    CONSTRAINT ck_strength_exercises_catalog_owner CHECK (
        (is_catalog AND owner_user_id IS NULL) OR (NOT is_catalog AND owner_user_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_strength_exercises_catalog_name
    ON strength_exercises (is_catalog, archived_at, name);
CREATE INDEX IF NOT EXISTS ix_strength_exercises_owner_name
    ON strength_exercises (owner_user_id, archived_at, name);

CREATE TABLE IF NOT EXISTS strength_exercise_instructions (
    exercise_id TEXT NOT NULL REFERENCES strength_exercises(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    instruction TEXT NOT NULL,
    PRIMARY KEY (exercise_id, position),
    CONSTRAINT ck_strength_exercise_instructions_position CHECK (position >= 0),
    CONSTRAINT ck_strength_exercise_instructions_nonempty CHECK (char_length(btrim(instruction)) > 0)
);

CREATE TABLE IF NOT EXISTS strength_exercise_muscles (
    exercise_id TEXT NOT NULL REFERENCES strength_exercises(id) ON DELETE CASCADE,
    muscle_key TEXT NOT NULL,
    load_factor NUMERIC(4, 2) NOT NULL,
    PRIMARY KEY (exercise_id, muscle_key),
    CONSTRAINT ck_strength_exercise_muscles_factor CHECK (load_factor > 0 AND load_factor <= 1)
);

CREATE TABLE IF NOT EXISTS strength_preferences (
    user_id UUID PRIMARY KEY,
    weight_unit TEXT NOT NULL DEFAULT 'kg',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_strength_preferences_unit CHECK (weight_unit IN ('kg', 'lb'))
);

CREATE TABLE IF NOT EXISTS strength_bodyweights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    measured_on DATE NOT NULL,
    weight_kg NUMERIC(7, 3) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_strength_bodyweights_user_day UNIQUE (user_id, measured_on),
    CONSTRAINT ck_strength_bodyweights_positive CHECK (weight_kg > 0)
);

CREATE INDEX IF NOT EXISTS ix_strength_bodyweights_user_day
    ON strength_bodyweights (user_id, measured_on DESC);

CREATE TABLE IF NOT EXISTS strength_routine_exercises (
    id UUID PRIMARY KEY,
    routine_id UUID NOT NULL REFERENCES strength_routines(id) ON DELETE CASCADE,
    exercise_id TEXT NOT NULL REFERENCES strength_exercises(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    mode TEXT NOT NULL DEFAULT 'reps',
    target_sets INTEGER NOT NULL DEFAULT 3,
    target_reps INTEGER NOT NULL DEFAULT 10,
    reps_min INTEGER NULL,
    reps_max INTEGER NULL,
    target_seconds INTEGER NOT NULL DEFAULT 45,
    target_minutes INTEGER NOT NULL DEFAULT 20,
    target_speed_kmh NUMERIC(7, 3) NOT NULL DEFAULT 8,
    target_weight_kg NUMERIC(8, 3) NOT NULL DEFAULT 0,
    is_bodyweight BOOLEAN NULL,
    per_side BOOLEAN NOT NULL DEFAULT FALSE,
    superset_id TEXT NULL,
    progression TEXT NULL,
    increment_kg NUMERIC(8, 3) NULL,
    CONSTRAINT uq_strength_routine_exercises_position UNIQUE (routine_id, position),
    CONSTRAINT ck_strength_routine_exercises_position CHECK (position >= 0),
    CONSTRAINT ck_strength_routine_exercises_mode CHECK (mode IN ('reps', 'time', 'cardio')),
    CONSTRAINT ck_strength_routine_exercises_counts CHECK (
        target_sets > 0 AND target_reps >= 0 AND target_seconds >= 0 AND target_minutes >= 0
    ),
    CONSTRAINT ck_strength_routine_exercises_numeric CHECK (
        target_speed_kmh >= 0 AND target_weight_kg >= 0 AND (increment_kg IS NULL OR increment_kg >= 0)
    )
);

CREATE INDEX IF NOT EXISTS ix_strength_routine_exercises_exercise
    ON strength_routine_exercises (exercise_id);

ALTER TABLE strength_workouts
    ADD COLUMN IF NOT EXISTS routine_id UUID NULL REFERENCES strength_routines(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS strength_workout_exercises (
    id UUID PRIMARY KEY,
    workout_id UUID NOT NULL REFERENCES strength_workouts(id) ON DELETE CASCADE,
    exercise_id TEXT NOT NULL REFERENCES strength_exercises(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    mode TEXT NOT NULL,
    is_bodyweight BOOLEAN NULL,
    per_side BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_strength_workout_exercises_position UNIQUE (workout_id, position),
    CONSTRAINT ck_strength_workout_exercises_position CHECK (position >= 0),
    CONSTRAINT ck_strength_workout_exercises_mode CHECK (mode IN ('reps', 'time', 'cardio'))
);

CREATE INDEX IF NOT EXISTS ix_strength_workout_exercises_exercise_workout
    ON strength_workout_exercises (exercise_id, workout_id);

CREATE TABLE IF NOT EXISTS strength_workout_sets (
    id UUID PRIMARY KEY,
    workout_exercise_id UUID NOT NULL REFERENCES strength_workout_exercises(id) ON DELETE CASCADE,
    set_number INTEGER NOT NULL,
    weight_kg NUMERIC(8, 3) NULL,
    reps INTEGER NULL,
    duration_seconds INTEGER NULL,
    speed_kmh NUMERIC(7, 3) NULL,
    CONSTRAINT uq_strength_workout_sets_number UNIQUE (workout_exercise_id, set_number),
    CONSTRAINT ck_strength_workout_sets_number CHECK (set_number > 0),
    CONSTRAINT ck_strength_workout_sets_values CHECK (
        (weight_kg IS NULL OR weight_kg >= 0) AND
        (reps IS NULL OR reps >= 0) AND
        (duration_seconds IS NULL OR duration_seconds >= 0) AND
        (speed_kmh IS NULL OR speed_kmh >= 0)
    )
);

CREATE INDEX IF NOT EXISTS ix_strength_workout_sets_exercise_number
    ON strength_workout_sets (workout_exercise_id, set_number);

DROP TRIGGER IF EXISTS trg_strength_exercises_set_updated_at ON strength_exercises;
CREATE TRIGGER trg_strength_exercises_set_updated_at BEFORE UPDATE ON strength_exercises FOR EACH ROW EXECUTE PROCEDURE public.set_updated_at();
DROP TRIGGER IF EXISTS trg_strength_preferences_set_updated_at ON strength_preferences;
CREATE TRIGGER trg_strength_preferences_set_updated_at BEFORE UPDATE ON strength_preferences FOR EACH ROW EXECUTE PROCEDURE public.set_updated_at();
DROP TRIGGER IF EXISTS trg_strength_bodyweights_set_updated_at ON strength_bodyweights;
CREATE TRIGGER trg_strength_bodyweights_set_updated_at BEFORE UPDATE ON strength_bodyweights FOR EACH ROW EXECUTE PROCEDURE public.set_updated_at();
