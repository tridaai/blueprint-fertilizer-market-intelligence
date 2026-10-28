-- 0009: scenario forks & planning options (R9).

CREATE TABLE scenario_forks (
    fork_id          TEXT PRIMARY KEY,
    fingerprint      TEXT NOT NULL,
    name             TEXT,
    kind             TEXT NOT NULL,
    base_artefact_id TEXT NOT NULL,
    created_by       TEXT NOT NULL,
    as_of            TEXT NOT NULL,
    rules_version    TEXT NOT NULL,
    payload          TEXT NOT NULL
);

CREATE TABLE planning_options (
    options_id       TEXT PRIMARY KEY,
    fingerprint      TEXT NOT NULL,
    name             TEXT,
    kind             TEXT NOT NULL,
    base_artefact_id TEXT NOT NULL,
    created_by       TEXT NOT NULL,
    as_of            TEXT NOT NULL,
    rules_version    TEXT NOT NULL,
    payload          TEXT NOT NULL
);

CREATE TABLE planning_adoptions (
    adoption_id TEXT PRIMARY KEY,
    options_id  TEXT NOT NULL,
    fork_id     TEXT,
    adopted_by  TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    supersedes  TEXT,
    payload     TEXT NOT NULL
);
