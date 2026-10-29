-- 0012: season-close estimate scoring (R12). Score runs and
-- score refusals are insert-only artefacts carrying their
-- full record as a payload. A score run grades head demand
-- estimates against season-close actuals and is never an
-- edit of either.

CREATE TABLE estimate_scores (
    score_id      TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    crop_year     TEXT NOT NULL,
    season        TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    scored_by     TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE score_refusals (
    refusal_id    TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    crop_year     TEXT NOT NULL,
    season        TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    scored_by     TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);
