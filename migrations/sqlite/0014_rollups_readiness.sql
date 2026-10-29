-- 0014: the territory layer (R14) — regional rollups
-- and their refusals, season readiness plans and their
-- refusals.

CREATE TABLE regional_rollups (
    rollup_id     TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    crop_year     TEXT NOT NULL,
    season        TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    built_by      TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE rollup_refusals (
    refusal_id    TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    crop_year     TEXT NOT NULL,
    season        TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    built_by      TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE season_readiness (
    readiness_id  TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    region        TEXT NOT NULL,
    crop_year     TEXT NOT NULL,
    season        TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    struck_by     TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE readiness_refusals (
    refusal_id    TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    region        TEXT NOT NULL,
    crop_year     TEXT NOT NULL,
    season        TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    struck_by     TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);
