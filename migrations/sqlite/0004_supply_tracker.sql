-- Round 4: the import & supply-gap tracker. A supply position is
-- one product-month's stock statement (opening + production
-- actual + import arrivals - consumption = closing), its
-- component lines stored alongside so the identity is
-- re-performable line by line. A supply gap states one
-- product-season against the R2 outlook: demand, the supply
-- position available to the season, and the import programme
-- test at the gap's as-of month, banded by the supply rule
-- pack. A supply projection runs an actual position forward to
-- a season's end on a pinned assumption set; assumption changes
-- against the superseded projection are stored on the new
-- artefact itself.
--
-- Like every artefact table here these are append-only: rows
-- are inserted, never updated, and a changed computation is a
-- new row whose `supersedes` points at the version it replaces.
-- There is deliberately no status column — position, programme
-- and projection state all live in the payloads and the
-- supersedes links, never in a mutable field.

CREATE TABLE IF NOT EXISTS supply_positions (
    position_id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    month TEXT NOT NULL,
    opening_tonnes REAL NOT NULL,
    production_planned_tonnes REAL,
    production_actual_tonnes REAL,
    imports_tonnes REAL NOT NULL,
    consumption_tonnes REAL NOT NULL,
    closing_tonnes REAL NOT NULL,
    rules_version TEXT NOT NULL,
    fact_fingerprint TEXT NOT NULL,
    as_of TEXT NOT NULL,
    supersedes TEXT,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS supply_position_lines (
    position_id TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    component TEXT NOT NULL,
    status TEXT NOT NULL,
    tonnes REAL NOT NULL,
    fact_ids TEXT NOT NULL,
    inputs TEXT NOT NULL,
    PRIMARY KEY (position_id, line_no)
);

CREATE TABLE IF NOT EXISTS supply_gaps (
    gap_id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    crop_year TEXT NOT NULL,
    season TEXT NOT NULL,
    as_of TEXT NOT NULL,
    as_of_month TEXT NOT NULL,
    demand_tonnes REAL NOT NULL,
    demand_outlook_id TEXT NOT NULL,
    available_tonnes REAL NOT NULL,
    gap_tonnes REAL NOT NULL,
    gap_pct_of_demand REAL NOT NULL,
    band TEXT NOT NULL,
    band_basis TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    fact_fingerprint TEXT NOT NULL,
    supersedes TEXT,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS supply_projections (
    projection_id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    crop_year TEXT NOT NULL,
    season TEXT NOT NULL,
    basis_month TEXT NOT NULL,
    as_of TEXT NOT NULL,
    status TEXT NOT NULL,
    opening_tonnes REAL NOT NULL,
    closing_tonnes REAL NOT NULL,
    rules_version TEXT NOT NULL,
    fact_fingerprint TEXT NOT NULL,
    supersedes TEXT,
    payload TEXT NOT NULL
);
