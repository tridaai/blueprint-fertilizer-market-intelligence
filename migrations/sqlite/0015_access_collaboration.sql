-- 0015: the collaboration layer (R15) — the access log
-- that audits scoped reads and exports, annotations and
-- follow-up tasks pinned to artefacts, and the
-- publication review queue with its refusals.

CREATE TABLE access_entries (
    entry_id      TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    principal     TEXT NOT NULL,
    role          TEXT NOT NULL,
    surface       TEXT NOT NULL,
    decision      TEXT NOT NULL,
    at            TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE annotations (
    annotation_id TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    target_kind   TEXT NOT NULL,
    target_id     TEXT NOT NULL,
    author        TEXT NOT NULL,
    at            TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE followup_tasks (
    task_id       TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    target_kind   TEXT NOT NULL,
    target_id     TEXT NOT NULL,
    assignee      TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    at            TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE followup_acts (
    act_id        TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    task_id       TEXT NOT NULL,
    act           TEXT NOT NULL,
    actor         TEXT NOT NULL,
    at            TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE review_queues (
    queue_id      TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    struck_by     TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE review_refusals (
    refusal_id    TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    struck_by     TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);
