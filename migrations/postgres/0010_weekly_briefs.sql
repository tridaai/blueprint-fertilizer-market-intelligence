-- 0010: weekly briefs, brief refusals, report packs, publication acts (R10).

CREATE TABLE weekly_briefs (
    brief_id      TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    week_start    TEXT NOT NULL,
    week_ending   TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    assembled_by  TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE brief_refusals (
    refusal_id    TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    week_start    TEXT NOT NULL,
    week_ending   TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    assembled_by  TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE export_packs (
    pack_id       TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    pack_kind     TEXT NOT NULL,
    pack_key      TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    exported_by   TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload       TEXT NOT NULL
);

CREATE TABLE publication_acts (
    act_id        TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    artefact_kind TEXT NOT NULL,
    artefact_id   TEXT NOT NULL,
    family_key    TEXT NOT NULL,
    published_by  TEXT NOT NULL,
    published_at  TEXT NOT NULL,
    supersedes    TEXT,
    payload       TEXT NOT NULL
);
