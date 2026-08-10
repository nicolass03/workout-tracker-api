-- Persist human-readable address for frequent places (optional).

ALTER TABLE frequent_places
    ADD COLUMN IF NOT EXISTS address TEXT NOT NULL DEFAULT '';
