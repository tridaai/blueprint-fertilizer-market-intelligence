# Architecture — Fertilizer & Agrochemical Market Intelligence Agent

## Shape

```
                ┌────────────────────────────────────────────┐
  business      │  API (FastAPI) — reads, /health, /readiness │
  users ───────▶│  request ids + JSON logs on every call      │
                └──────────────┬─────────────────────────────┘
                               │
                ┌──────────────▼─────────────────────────────┐
                │  Service — dataset loading, read wiring     │
                └──────┬───────────────────────┬─────────────┘
                       │                       │
        ┌──────────────▼───────────┐  ┌────────▼────────────────┐
        │  Market data store port  │  │  Model port              │
        │  insert-only, provenance │  │  offline default,        │
        │  per row                 │  │  hosted fail-closed      │
        │  SQLite │ Postgres 16    │  └─────────────────────────┘
        └──────────────┬───────────┘
                       │
        ┌──────────────▼───────────┐
        │  Dataset generator       │
        │  seeded, deterministic,  │
        │  plants spike + delay,   │
        │  emits the manifest      │
        └──────────────────────────┘
```

Later rounds add, behind the same ports: the demand-estimation
engine (computed views over the store, driver contributions as
artefacts), the alert recorder, the dashboard assembler
(AgentSQL-shaped: natural language → governed artefact selection →
static page), scenario forks, and the weekly brief with its figure
verifier. The LangGraph workflow (ingest → estimate → assemble →
brief → publish gate) orchestrates those steps; every state
transition is a stored artefact.

## The invariants

- **Provenance is a schema property, not a convention.** The fact
  models refuse a figure without `source` and `as_of`; the store
  has no write path that could drop them.
- **Insert-only.** No update/delete verb exists on the store port.
  Corrections are new facts. The eval gate grades this by attempting
  a second dataset load and requiring refusal.
- **Derived numbers are re-derivable.** Consumption in R1 is the
  template: a stated pure function of stored inputs, graded by
  re-derivation. The R2 demand engine follows the same rule — an
  estimate is a function of stored facts plus a versioned rule set,
  and the eval gate re-performs it.
- **The manifest is the truth.** Anything the generator plants
  (spike, delay, events) is recorded in the manifest at generation
  time. Graders read the manifest, never a hand-copied expectation,
  so the truth cannot drift from the data.
- **Fail-closed model profiles.** Profile resolution happens at
  wiring; unknown names and unconfigured hosted profiles raise.
  There is no code path that substitutes one profile for another.

## Data model (migration 0001)

Fact tables: `districts`, `area_facts`, `monsoon_facts`,
`soil_facts`, `application_rates`, `consumption_facts`,
`price_points`, `import_arrivals`, `supply_facts`,
`competitor_points`, `policy_events`, `field_reports`, and
`generator_manifest` (one row). Primary keys are the natural keys of
each fact, which is what makes a duplicate insert an error rather
than an overwrite. JSON payloads (policy-event product lists, the
manifest) are stored as JSON text in both dialects.

## Deployment

Multi-stage Dockerfile, non-root runtime user, port 8000. Compose
brings up the agent, Postgres 16 (pgvector image, ahead of the
retrieval rounds) and SeaweedFS as the S3-compatible object store
under the service name `minio`. Configuration is environment-only;
see `.env.example`.
