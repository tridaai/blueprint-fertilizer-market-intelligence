-- Round 6: competitor & market-share intelligence. The
-- tracked competitor points (migration 0001 facts) become
-- first-class CompetitorObservation artefacts — provenance
-- (source + observation date) is part of the artefact, and an
-- observation without it cannot be stored. Market shares are
-- computed per district x product x season from the stored
-- observations, the R2 demand estimates and the recorded
-- consumption, under the share rule pack: allocation by
-- demand weight, Kaveri's volume as the named residual, a
-- headline reading over the fresh window only with stale
-- exclusions named, and a full-season reading labelled as
-- including stale figures. Share movements compare the two
-- crop years' full-season readings per district x product.
--
-- Like every artefact table here these are append-only: rows
-- are inserted, never updated, and a recomputation over
-- changed facts is a new row whose `supersedes` points at the
-- version it replaces. There is deliberately no freshness
-- column on the observation — staleness is a property of a
-- read date, computed at share time under the pack.

CREATE TABLE IF NOT EXISTS competitor_observations (
    observation_id TEXT PRIMARY KEY,
    competitor TEXT NOT NULL,
    region TEXT NOT NULL,
    product TEXT NOT NULL,
    month TEXT NOT NULL,
    crop_year TEXT,
    season TEXT,
    volume_tonnes REAL NOT NULL,
    price REAL NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_shares (
    share_id TEXT PRIMARY KEY,
    district_id TEXT NOT NULL,
    product TEXT NOT NULL,
    crop_year TEXT NOT NULL,
    season TEXT NOT NULL,
    as_of TEXT NOT NULL,
    status TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    fact_fingerprint TEXT NOT NULL,
    supersedes TEXT,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS share_movements (
    movement_id TEXT PRIMARY KEY,
    district_id TEXT NOT NULL,
    product TEXT NOT NULL,
    season TEXT NOT NULL,
    from_crop_year TEXT NOT NULL,
    to_crop_year TEXT NOT NULL,
    biggest_mover TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    fact_fingerprint TEXT NOT NULL,
    as_of TEXT NOT NULL,
    supersedes TEXT,
    payload TEXT NOT NULL
);
