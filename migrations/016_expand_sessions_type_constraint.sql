-- Upgrade databases where 015 left the previous walk_run-only constraint in place.
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS ck_sessions_type;

ALTER TABLE sessions
    ADD CONSTRAINT ck_sessions_type
    CHECK (type IN ('walk_run', 'walk', 'run', 'jogging', 'hiking'));
