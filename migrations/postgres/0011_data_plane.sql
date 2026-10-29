-- 0011: the production data plane (R11). Connector load batches,
-- quarantined rows, fact corrections and the season-close actuals
-- fact class. Batches, quarantine records and corrections are
-- insert-only artefacts carrying their full record as a payload.
-- Actuals are facts: a distinct class with provenance at the row
-- level, never an overwrite of any estimate.

CREATE TABLE ingest_batches (
    batch_id      TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    fact_class    TEXT NOT NULL,
    loaded_by     TEXT NOT NULL,
    load_date     TEXT NOT NULL,
    received      INTEGER NOT NULL,
    inserted      INTEGER NOT NULL,
    duplicates    INTEGER NOT NULL,
    quarantined   INTEGER NOT NULL,
    refused       INTEGER NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE quarantine_records (
    quarantine_id TEXT PRIMARY KEY,
    batch_id      TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    fact_class    TEXT NOT NULL,
    reason        TEXT NOT NULL,
    natural_key   TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE fact_corrections (
    correction_id TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    fact_class    TEXT NOT NULL,
    natural_key   TEXT NOT NULL,
    corrects      TEXT,
    corrected_by  TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    supersedes    TEXT,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE season_actuals (
    district_id     TEXT NOT NULL,
    crop_year       TEXT NOT NULL,
    season          TEXT NOT NULL,
    product         TEXT NOT NULL,
    actual_kind     TEXT NOT NULL,
    quantity_tonnes REAL NOT NULL,
    source          TEXT NOT NULL,
    as_of           TEXT NOT NULL,
    PRIMARY KEY (district_id, crop_year, season, product, actual_kind)
);
