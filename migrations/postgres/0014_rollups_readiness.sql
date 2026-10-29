-- 0014: the territory layer (R14) — regional rollups
-- and their refusals, season readiness plans and their
-- refusals.

CREATE TABLE regional_rollups (
    rollup_id     VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    crop_year     VARCHAR NOT NULL,
    season        VARCHAR NOT NULL,
    as_of         VARCHAR NOT NULL,
    built_by      VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE rollup_refusals (
    refusal_id    VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    crop_year     VARCHAR NOT NULL,
    season        VARCHAR NOT NULL,
    as_of         VARCHAR NOT NULL,
    built_by      VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE season_readiness (
    readiness_id  VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    region        VARCHAR NOT NULL,
    crop_year     VARCHAR NOT NULL,
    season        VARCHAR NOT NULL,
    as_of         VARCHAR NOT NULL,
    struck_by     VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE readiness_refusals (
    refusal_id    VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    region        VARCHAR NOT NULL,
    crop_year     VARCHAR NOT NULL,
    season        VARCHAR NOT NULL,
    as_of         VARCHAR NOT NULL,
    struck_by     VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);
