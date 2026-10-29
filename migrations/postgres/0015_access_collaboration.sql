-- 0015: the collaboration layer (R15) — the access log
-- that audits scoped reads and exports, annotations and
-- follow-up tasks pinned to artefacts, and the
-- publication review queue with its refusals.

CREATE TABLE access_entries (
    entry_id      VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    principal     VARCHAR NOT NULL,
    role          VARCHAR NOT NULL,
    surface       VARCHAR NOT NULL,
    decision      VARCHAR NOT NULL,
    at            VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE annotations (
    annotation_id VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    target_kind   VARCHAR NOT NULL,
    target_id     VARCHAR NOT NULL,
    author        VARCHAR NOT NULL,
    at            VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE followup_tasks (
    task_id       VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    target_kind   VARCHAR NOT NULL,
    target_id     VARCHAR NOT NULL,
    assignee      VARCHAR NOT NULL,
    created_by    VARCHAR NOT NULL,
    at            VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE followup_acts (
    act_id        VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    task_id       VARCHAR NOT NULL,
    act           VARCHAR NOT NULL,
    actor         VARCHAR NOT NULL,
    at            VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE review_queues (
    queue_id      VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    as_of         VARCHAR NOT NULL,
    struck_by     VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);

CREATE TABLE review_refusals (
    refusal_id    VARCHAR PRIMARY KEY,
    fingerprint   VARCHAR NOT NULL,
    as_of         VARCHAR NOT NULL,
    struck_by     VARCHAR NOT NULL,
    rules_version VARCHAR NOT NULL,
    payload       VARCHAR NOT NULL
);
