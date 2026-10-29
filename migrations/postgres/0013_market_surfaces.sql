-- 0013: the market surfaces (R13) — district maps and
-- their refusals, morning boards and their refusals,
-- and the gap action queue with its acts.

CREATE TABLE market_maps (
    map_id        VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    crop_year     VARCHAR NOT NULL,
    season        VARCHAR NOT NULL,
    as_of         VARCHAR NOT NULL,
    built_by      VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE map_refusals (
    refusal_id    VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    crop_year     VARCHAR NOT NULL,
    season        VARCHAR NOT NULL,
    as_of         VARCHAR NOT NULL,
    built_by      VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE morning_boards (
    board_id      VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    role          VARCHAR NOT NULL,
    crop_year     VARCHAR NOT NULL,
    season        VARCHAR NOT NULL,
    as_of         VARCHAR NOT NULL,
    built_by      VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE board_refusals (
    refusal_id    VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    role          VARCHAR NOT NULL,
    crop_year     VARCHAR NOT NULL,
    season        VARCHAR NOT NULL,
    as_of         VARCHAR NOT NULL,
    built_by      VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE queue_items (
    item_id       VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    gap_id        VARCHAR NOT NULL,
    product       VARCHAR NOT NULL,
    crop_year     VARCHAR NOT NULL,
    season        VARCHAR NOT NULL,
    band          VARCHAR NOT NULL,
    struck_on     VARCHAR NOT NULL,
    due_date      VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE queue_acts (
    act_id        VARCHAR PRIMARY KEY,
    item_id       VARCHAR NOT NULL,
    act           VARCHAR NOT NULL,
    actor         VARCHAR NOT NULL,
    as_of         VARCHAR NOT NULL,
    reason        VARCHAR,
    owner         VARCHAR,
    fork_id       VARCHAR,
    note          VARCHAR
);
