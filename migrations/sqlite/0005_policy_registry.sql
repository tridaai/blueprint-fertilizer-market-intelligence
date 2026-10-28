-- Round 5: the policy & subsidy event registry. A registry
-- event is a recorded policy fact promoted to a first-class
-- artefact: its class and stated effect from the policy rule
-- pack, its derived effective window, its product/district
-- scope, its provenance (source + recorded date), and a
-- hypothetical marker for proposed policies. An impact note
-- states, per current registry event, exactly which stored
-- artefacts fall inside the event's window and scope — the
-- demand estimate heads, the price series points and the
-- supply position heads — computed by query, never narrated.
--
-- Like every artefact table here these are append-only: rows
-- are inserted, never updated, and a corrected registration
-- (or a hypothetical that becomes real) is a new row whose
-- `supersedes` points at the version it replaces. There is
-- deliberately no status column — the current registration of
-- an event is the head of its supersedes chain, and a note's
-- status lives in its payload.

CREATE TABLE IF NOT EXISTS policy_registry_events (
    registry_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    fact_event_id TEXT,
    event_class TEXT NOT NULL,
    fact_kind TEXT,
    title TEXT NOT NULL,
    effective_from_month TEXT NOT NULL,
    effective_to_month TEXT NOT NULL,
    products TEXT NOT NULL,
    districts TEXT NOT NULL,
    hypothetical INTEGER NOT NULL,
    source TEXT NOT NULL,
    recorded_on TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    fact_fingerprint TEXT NOT NULL,
    as_of TEXT NOT NULL,
    supersedes TEXT,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_impact_notes (
    note_id TEXT PRIMARY KEY,
    registry_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    status TEXT NOT NULL,
    demand_count INTEGER NOT NULL,
    price_point_count INTEGER NOT NULL,
    position_count INTEGER NOT NULL,
    rules_version TEXT NOT NULL,
    fact_fingerprint TEXT NOT NULL,
    as_of TEXT NOT NULL,
    supersedes TEXT,
    payload TEXT NOT NULL
);
