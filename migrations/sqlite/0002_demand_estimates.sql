-- Demand engine artefacts, round 2. Estimates, outlooks and
-- narratives are insert-only like the facts: a recomputation over
-- changed facts is a new artefact whose supersedes column names
-- the artefact it replaces; the replaced one stays readable.
CREATE TABLE demand_estimates (
    estimate_id TEXT PRIMARY KEY,
    district_id TEXT NOT NULL,
    product TEXT NOT NULL,
    crop_year TEXT NOT NULL,
    season TEXT NOT NULL,
    status TEXT NOT NULL,
    base_tonnes REAL NOT NULL,
    total_tonnes REAL NOT NULL,
    missing_drivers TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    rate_table_version TEXT NOT NULL,
    fact_fingerprint TEXT NOT NULL,
    as_of TEXT NOT NULL,
    supersedes TEXT
);
CREATE TABLE demand_contributions (
    estimate_id TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    driver TEXT NOT NULL,
    status TEXT NOT NULL,
    factor REAL,
    delta_tonnes REAL NOT NULL,
    value_after_tonnes REAL NOT NULL,
    inputs TEXT NOT NULL,
    PRIMARY KEY (estimate_id, line_no)
);
CREATE TABLE season_outlooks (
    outlook_id TEXT PRIMARY KEY,
    crop_year TEXT NOT NULL,
    season TEXT NOT NULL,
    status TEXT NOT NULL,
    estimate_count INTEGER NOT NULL,
    partial_count INTEGER NOT NULL,
    total_tonnes REAL NOT NULL,
    product_rollups TEXT NOT NULL,
    estimate_ids TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    fact_fingerprint TEXT NOT NULL,
    as_of TEXT NOT NULL,
    supersedes TEXT
);
CREATE TABLE outlook_narratives (
    narrative_id TEXT PRIMARY KEY,
    outlook_id TEXT NOT NULL,
    text TEXT NOT NULL,
    model_profile TEXT NOT NULL,
    model_name TEXT NOT NULL,
    figures TEXT NOT NULL,
    as_of TEXT NOT NULL
);
