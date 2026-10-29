-- 0013: the market surfaces (R13) — district maps and
-- their refusals, morning boards and their refusals,
-- and the gap action queue with its acts.

CREATE TABLE market_maps (
    map_id        TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    crop_year     TEXT NOT NULL,
    season        TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    built_by      TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE map_refusals (
    refusal_id    TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    crop_year     TEXT NOT NULL,
    season        TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    built_by      TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE morning_boards (
    board_id      TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    role          TEXT NOT NULL,
    crop_year     TEXT NOT NULL,
    season        TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    built_by      TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE board_refusals (
    refusal_id    TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    role          TEXT NOT NULL,
    crop_year     TEXT NOT NULL,
    season        TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    built_by      TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE queue_items (
    item_id       TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    gap_id        TEXT NOT NULL,
    product       TEXT NOT NULL,
    crop_year     TEXT NOT NULL,
    season        TEXT NOT NULL,
    band          TEXT NOT NULL,
    struck_on     TEXT NOT NULL,
    due_date      TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE queue_acts (
    act_id        TEXT PRIMARY KEY,
    item_id       TEXT NOT NULL,
    act           TEXT NOT NULL,
    actor         TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    reason        TEXT,
    owner         TEXT,
    fork_id       TEXT,
    note          TEXT
);
