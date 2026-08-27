ALTER TABLE strength_routine_exercises
    ADD COLUMN IF NOT EXISTS rest_seconds INTEGER NULL;

ALTER TABLE strength_routine_exercises
    DROP CONSTRAINT IF EXISTS ck_strength_routine_exercises_rest_seconds;

ALTER TABLE strength_routine_exercises
    ADD CONSTRAINT ck_strength_routine_exercises_rest_seconds
    CHECK (rest_seconds IS NULL OR rest_seconds BETWEEN 5 AND 3600);
