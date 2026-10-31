-- 0019: the admin & integration layer (R19) — pack
-- configuration versions and master-data versions
-- struck as stored, effective-dated artefacts,
-- webhook subscriptions and their signed
-- deliveries, scoped API tokens and the decision
-- entry every token read leaves, and the exchange
-- batches and feeds of the ERP/CRM-shaped ports.
-- Every table here is insert-only, like the rest
-- of the store: state is a fold of artefacts and
-- acts, never a column somebody edits.

CREATE TABLE pack_config_versions (
    version_id    TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    family        TEXT NOT NULL,
    version_label TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    editor        TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE master_data_versions (
    version_id    TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    register      TEXT NOT NULL,
    version_label TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    editor        TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE webhook_subscriptions (
    subscription_id TEXT PRIMARY KEY,
    fingerprint     TEXT NOT NULL,
    integration     TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    payload         TEXT NOT NULL
);

CREATE TABLE webhook_controls (
    control_id      TEXT PRIMARY KEY,
    fingerprint     TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    act             TEXT NOT NULL,
    actor           TEXT NOT NULL,
    as_of           TEXT NOT NULL,
    payload         TEXT NOT NULL
);

CREATE TABLE webhook_deliveries (
    delivery_id     TEXT PRIMARY KEY,
    fingerprint     TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    event_kind      TEXT NOT NULL,
    trigger_id      TEXT NOT NULL,
    payload         TEXT NOT NULL
);

CREATE TABLE api_tokens (
    token_id    TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    integration TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE TABLE api_token_acts (
    act_id      TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    token_id    TEXT NOT NULL,
    act         TEXT NOT NULL,
    actor       TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE TABLE token_decisions (
    decision_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    token_id    TEXT,
    kind        TEXT NOT NULL,
    target      TEXT NOT NULL,
    decision    TEXT NOT NULL,
    at          TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE TABLE exchange_batches (
    batch_id   TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    port       TEXT NOT NULL,
    outcome    TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE TABLE exchange_feeds (
    feed_id    TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    port       TEXT NOT NULL,
    as_of      TEXT NOT NULL,
    payload    TEXT NOT NULL
);
