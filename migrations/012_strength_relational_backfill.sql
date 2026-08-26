-- Move all existing strength state into the normalized tables seeded by 011.
-- Historic values were stored in the user's configured unit; persist kg from this point forward.

INSERT INTO strength_preferences (user_id, weight_unit)
SELECT user_id, CASE WHEN state ->> 'unit' = 'lb' THEN 'lb' ELSE 'kg' END
FROM strength_state
ON CONFLICT (user_id) DO UPDATE SET weight_unit = EXCLUDED.weight_unit;

INSERT INTO strength_bodyweights (user_id, measured_on, weight_kg)
SELECT
    source.user_id,
    (entry ->> 'date')::date,
    CASE WHEN source.state ->> 'unit' = 'lb'
        THEN (entry ->> 'weight')::numeric * 0.45359237
        ELSE (entry ->> 'weight')::numeric
    END
FROM strength_state AS source
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(source.state -> 'bodyweight') = 'array' THEN source.state -> 'bodyweight' ELSE '[]'::jsonb END
) AS entry
WHERE entry ? 'date' AND entry ? 'weight' AND (entry ->> 'weight')::numeric > 0
ON CONFLICT (user_id, measured_on) DO UPDATE SET weight_kg = EXCLUDED.weight_kg;

INSERT INTO strength_exercises (id, owner_user_id, name, body_part, equipment, target_muscle, is_catalog)
SELECT
    entry ->> 'id',
    source.user_id,
    COALESCE(NULLIF(btrim(entry ->> 'name'), ''), 'Custom exercise'),
    COALESCE(entry ->> 'bodyPart', ''),
    COALESCE(entry ->> 'equipment', ''),
    COALESCE(entry ->> 'target', ''),
    FALSE
FROM strength_state AS source
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(source.state -> 'customExercises') = 'array' THEN source.state -> 'customExercises' ELSE '[]'::jsonb END
) AS entry
WHERE NULLIF(entry ->> 'id', '') IS NOT NULL
ON CONFLICT (id) DO NOTHING;

-- Preserve any historic references that are not in the OpenGym catalogue or custom state.
WITH referenced_exercises AS (
    SELECT r.user_id, item ->> 'exerciseId' AS exercise_id
    FROM strength_routines AS r
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(r.exercises, '[]'::jsonb)) AS item
    UNION
    SELECT w.user_id, entry ->> 'exerciseId' AS exercise_id
    FROM strength_workouts AS w
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(w.entries, '[]'::jsonb)) AS entry
)
INSERT INTO strength_exercises (id, owner_user_id, name, is_catalog, archived_at)
SELECT DISTINCT exercise_id, user_id, 'Archived exercise', FALSE, now()
FROM referenced_exercises
WHERE NULLIF(exercise_id, '') IS NOT NULL
ON CONFLICT (id) DO NOTHING;

INSERT INTO strength_routine_exercises (
    id, routine_id, exercise_id, position, mode, target_sets, target_reps, reps_min, reps_max,
    target_seconds, target_minutes, target_speed_kmh, target_weight_kg, is_bodyweight, per_side,
    superset_id, progression, increment_kg
)
SELECT
    (item ->> 'id')::uuid,
    routine.id,
    item ->> 'exerciseId',
    ordinal - 1,
    COALESCE(item ->> 'mode', 'reps'),
    COALESCE((item ->> 'sets')::integer, 3),
    COALESCE((item ->> 'reps')::integer, 10),
    NULLIF(item ->> 'repsMin', '')::integer,
    NULLIF(item ->> 'repsMax', '')::integer,
    COALESCE((item ->> 'seconds')::integer, 45),
    COALESCE((item ->> 'minutes')::integer, 20),
    COALESCE((item ->> 'speedKmh')::numeric, 8),
    CASE WHEN state.state ->> 'unit' = 'lb'
        THEN COALESCE((item ->> 'weight')::numeric, 0) * 0.45359237
        ELSE COALESCE((item ->> 'weight')::numeric, 0)
    END,
    NULLIF(item ->> 'bodyweight', '')::boolean,
    COALESCE((item ->> 'perSide')::boolean, FALSE),
    NULLIF(item ->> 'supersetId', ''),
    NULLIF(item ->> 'progression', ''),
    CASE WHEN NULLIF(item ->> 'increment', '') IS NULL THEN NULL
        WHEN state.state ->> 'unit' = 'lb' THEN (item ->> 'increment')::numeric * 0.45359237
        ELSE (item ->> 'increment')::numeric
    END
FROM strength_routines AS routine
LEFT JOIN strength_state AS state ON state.user_id = routine.user_id
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(routine.exercises, '[]'::jsonb)) WITH ORDINALITY AS items(item, ordinal)
WHERE item ? 'id' AND item ? 'exerciseId'
ON CONFLICT (id) DO NOTHING;

INSERT INTO strength_workout_exercises (
    id, workout_id, exercise_id, position, mode, is_bodyweight, per_side
)
SELECT
    (entry ->> 'id')::uuid,
    workout.id,
    entry ->> 'exerciseId',
    ordinal - 1,
    COALESCE(entry -> 'target' ->> 'mode', 'reps'),
    NULLIF(entry -> 'target' ->> 'bodyweight', '')::boolean,
    COALESCE((entry -> 'target' ->> 'perSide')::boolean, FALSE)
FROM strength_workouts AS workout
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(workout.entries, '[]'::jsonb)) WITH ORDINALITY AS entries(entry, ordinal)
WHERE entry ? 'id' AND entry ? 'exerciseId'
ON CONFLICT (id) DO NOTHING;

INSERT INTO strength_workout_sets (
    id, workout_exercise_id, set_number, weight_kg, reps, duration_seconds, speed_kmh
)
SELECT
    (set_item ->> 'id')::uuid,
    (entry ->> 'id')::uuid,
    set_ordinal,
    CASE WHEN state.state ->> 'unit' = 'lb'
        THEN COALESCE((set_item ->> 'weight')::numeric, 0) * 0.45359237
        ELSE COALESCE((set_item ->> 'weight')::numeric, 0)
    END,
    CASE WHEN entry -> 'target' ->> 'mode' = 'reps' THEN COALESCE((set_item ->> 'reps')::integer, 0) ELSE NULL END,
    CASE
        WHEN entry -> 'target' ->> 'mode' = 'time' THEN COALESCE((set_item ->> 'seconds')::integer, 0)
        WHEN entry -> 'target' ->> 'mode' = 'cardio' THEN COALESCE((set_item ->> 'minutes')::integer, 0) * 60
        ELSE NULL
    END,
    CASE WHEN entry -> 'target' ->> 'mode' = 'cardio' THEN COALESCE((set_item ->> 'speedKmh')::numeric, 0) ELSE NULL END
FROM strength_workouts AS workout
LEFT JOIN strength_state AS state ON state.user_id = workout.user_id
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(workout.entries, '[]'::jsonb)) AS entry
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(entry -> 'sets', '[]'::jsonb)) WITH ORDINALITY AS sets(set_item, set_ordinal)
WHERE entry ? 'id' AND set_item ? 'id'
ON CONFLICT (id) DO NOTHING;

ALTER TABLE strength_routines DROP COLUMN exercises;
ALTER TABLE strength_workouts DROP COLUMN entries;
DROP TABLE strength_state;
