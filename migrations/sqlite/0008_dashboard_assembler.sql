-- 0008: the ask-in-plain-language dashboard assembler (R8).

CREATE TABLE dashboard_specs (
    spec_id     TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    question    TEXT NOT NULL,
    asked_by    TEXT NOT NULL,
    role        TEXT,
    name        TEXT,
    saved_by    TEXT,
    as_of       TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE TABLE dashboard_assemblies (
    assembly_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    spec_id     TEXT NOT NULL,
    supersedes  TEXT,
    assembled_on TEXT NOT NULL,
    payload     TEXT NOT NULL
);
