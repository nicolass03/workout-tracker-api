-- Widen/narrow frequent_places radius to 10–250 m (was 100–400).

ALTER TABLE frequent_places DROP CONSTRAINT IF EXISTS ck_frequent_places_radius;

-- Clamp any out-of-range rows before re-adding the check.
UPDATE frequent_places
SET radius_meters = 10
WHERE radius_meters < 10;

UPDATE frequent_places
SET radius_meters = 250
WHERE radius_meters > 250;

ALTER TABLE frequent_places
    ADD CONSTRAINT ck_frequent_places_radius
    CHECK (radius_meters >= 10 AND radius_meters <= 250);
