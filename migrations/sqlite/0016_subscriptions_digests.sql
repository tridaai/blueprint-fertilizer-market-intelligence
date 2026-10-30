-- 0016: the notify layer (R16) — subscription
-- artefacts (a named reader's standing instruction,
-- superseded by link, never edited) and digest
-- artefacts (a subscription's derived deliveries and
-- escalations, frozen at a generation date).
-- Deliveries and escalation states are derived at
-- read from the alerts, the subscriptions and the
-- acts, so they take no table here.

CREATE TABLE subscriptions (
    subscription_id TEXT PRIMARY KEY,
    fingerprint     TEXT NOT NULL,
    principal       TEXT NOT NULL,
    struck_by       TEXT NOT NULL,
    at              TEXT NOT NULL,
    rules_version   TEXT NOT NULL,
    payload         TEXT NOT NULL
);

CREATE TABLE digests (
    digest_id       TEXT PRIMARY KEY,
    fingerprint     TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    principal       TEXT NOT NULL,
    as_of           TEXT NOT NULL,
    rules_version   TEXT NOT NULL,
    payload         TEXT NOT NULL
);
