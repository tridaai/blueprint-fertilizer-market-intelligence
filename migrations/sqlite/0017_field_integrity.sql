-- 0017: the field-integrity layer (R17) — one
-- screening verdict per landed field report, the
-- release acts that fold a held screening, and the
-- reporter-integrity boards struck from the record.
-- Screening state and board contents are derived at
-- read from these artefacts and the field book, so
-- no state column lives anywhere here.

CREATE TABLE field_screenings (
    screening_id  TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    report_id     TEXT NOT NULL,
    verdict       TEXT NOT NULL,
    at            TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE field_screening_acts (
    act_id       TEXT PRIMARY KEY,
    fingerprint  TEXT NOT NULL,
    screening_id TEXT NOT NULL,
    report_id    TEXT NOT NULL,
    act          TEXT NOT NULL,
    actor        TEXT NOT NULL,
    reason       TEXT NOT NULL,
    as_of        TEXT NOT NULL
);

CREATE TABLE reporter_integrity_boards (
    board_id      TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);
