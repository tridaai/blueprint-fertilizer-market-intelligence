-- Round 7: field signals & mobile intake. Field reports stop
-- being read-only facts and become first-class artefacts with
-- a lifecycle: a structured submission from the mobile intake
-- (or the promotion of a planted R1 field report) lands as a
-- FieldSignalReport under the field-signal pack, exactly once
-- per (submission id, payload) however often the outbox
-- re-sends it; a conflicting payload under the same submission
-- id lands alongside, linked, never overwriting. Reviewer
-- acts are insert-only and the review state is their fold —
-- there is deliberately no state column on the report.
-- Assessments are the weighting consumer: per district x
-- product x season they fold the cell's reports (review state
-- times freshness decay, the unverified cap applied per
-- report) into an adjustment against the head R2 demand
-- estimate, every contribution a named, attributed line.
--
-- Like every artefact table here these are append-only: rows
-- are inserted, never updated, and a recomputation over
-- changed inputs is a new row whose `supersedes` points at the
-- version it replaces.

CREATE TABLE IF NOT EXISTS field_signal_reports (
    report_id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    reporter TEXT NOT NULL,
    district_id TEXT NOT NULL,
    product TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    signal_kind TEXT NOT NULL,
    observed_on TEXT NOT NULL,
    crop_year TEXT,
    season TEXT,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    conflicts_with TEXT,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS field_review_acts (
    act_id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    act TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    note TEXT,
    as_of TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS field_signal_assessments (
    assessment_id TEXT PRIMARY KEY,
    district_id TEXT NOT NULL,
    product TEXT NOT NULL,
    crop_year TEXT NOT NULL,
    season TEXT NOT NULL,
    as_of TEXT NOT NULL,
    estimate_id TEXT NOT NULL,
    base_tonnes DOUBLE PRECISION NOT NULL,
    adjustment_pct DOUBLE PRECISION NOT NULL,
    adjusted_tonnes DOUBLE PRECISION NOT NULL,
    rules_version TEXT NOT NULL,
    fact_fingerprint TEXT NOT NULL,
    supersedes TEXT,
    payload TEXT NOT NULL
);
