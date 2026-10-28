-- Price watch artefacts, round 3. Movements and alerts are
-- insert-only like everything else in this store. An alert's
-- state is NOT a column here: it is derived from its acts in
-- alert_acts, so state can only ever change by recording an act.
CREATE TABLE price_movements (
    movement_id TEXT PRIMARY KEY,
    series_kind TEXT NOT NULL,
    item TEXT NOT NULL,
    month TEXT NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    prev_price DOUBLE PRECISION,
    mom_pct DOUBLE PRECISION,
    baseline_mean DOUBLE PRECISION,
    baseline_pct DOUBLE PRECISION,
    baseline_months TEXT NOT NULL,
    fact_ids TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    fact_fingerprint TEXT NOT NULL,
    as_of TEXT NOT NULL
);
CREATE TABLE price_alerts (
    alert_id TEXT PRIMARY KEY,
    series_kind TEXT NOT NULL,
    item TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    band TEXT NOT NULL,
    period_month TEXT NOT NULL,
    movement_ids TEXT NOT NULL,
    figures TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    as_of TEXT NOT NULL
);
CREATE TABLE alert_acts (
    act_id TEXT PRIMARY KEY,
    alert_id TEXT NOT NULL,
    act TEXT NOT NULL,
    actor TEXT NOT NULL,
    note TEXT,
    closing_reason TEXT,
    as_of TEXT NOT NULL
);
