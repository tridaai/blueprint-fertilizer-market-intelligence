-- 0018: the monitoring layer (R18) — one record
-- per model run the service's own port completes,
-- priced by the monitoring pack, and the monitoring
-- boards struck from the record. Board sections and
-- reliability lines are derived at strike time from
-- the stored artefacts, so no state column lives
-- anywhere here.

CREATE TABLE model_runs (
    run_id        TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    purpose       TEXT NOT NULL,
    profile       TEXT NOT NULL,
    model         TEXT NOT NULL,
    at            TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE monitoring_boards (
    board_id      TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);
