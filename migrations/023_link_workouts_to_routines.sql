-- Workouts saved before the app sent routineId carry no link to the routine they were
-- started from. Link each to the routine it was named after, when exactly one routine
-- of that user still has that name. Only the link is set: the workout keeps its own
-- name and sets, so history and analytics read exactly as before.
UPDATE strength_workouts AS w
SET routine_id = r.id
FROM (
    SELECT user_id, name, (array_agg(id))[1] AS id
    FROM strength_routines
    GROUP BY user_id, name
    HAVING count(*) = 1
) AS r
WHERE w.routine_id IS NULL
  AND w.user_id = r.user_id
  AND w.name = r.name;
