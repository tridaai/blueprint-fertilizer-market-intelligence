-- 0016: the notify layer (R16) — subscription
-- artefacts (a named reader's standing instruction,
-- superseded by link, never edited) and digest
-- artefacts (a subscription's derived deliveries and
-- escalations, frozen at a generation date).
-- Deliveries and escalation states are derived at
-- read from the alerts, the subscriptions and the
-- acts, so they take no table here.

CREATE TABLE subscriptions (
    subscription_id VARCHAR PRIMARY KEY,
    fingerprint     VARCHAR NOT NULL,
    principal       VARCHAR NOT NULL,
    struck_by       VARCHAR NOT NULL,
    at              VARCHAR NOT NULL,
    rules_version   VARCHAR NOT NULL,
    payload         VARCHAR NOT NULL
);

CREATE TABLE digests (
    digest_id       VARCHAR PRIMARY KEY,
    fingerprint     VARCHAR NOT NULL,
    subscription_id VARCHAR NOT NULL,
    principal       VARCHAR NOT NULL,
    as_of           VARCHAR NOT NULL,
    rules_version   VARCHAR NOT NULL,
    payload         VARCHAR NOT NULL
);
