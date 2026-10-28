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

Round 2 adds the demand-estimation engine behind the service:
`demand_rules.py` holds the versioned rule pack (soil factors,
monsoon bands, price elasticities, carry-in bands, calendar
windows — imported by the generator too, so each rule is stated
exactly once), and `demand.py` holds the engine, the
re-performance verifier, the outlook builder and the narrator.
Estimates, outlooks and narratives are stored artefacts
(migration 0002), insert-only like the facts, linked by
supersession when the fact set moves.

Later rounds add, behind the same ports: the alert recorder, the
dashboard assembler (AgentSQL-shaped: natural language → governed
artefact selection → static page), scenario forks, and the
weekly brief with its figure verifier. The LangGraph workflow
(ingest → estimate → assemble → brief → publish gate)
orchestrates those steps; every state transition is a stored
artefact.

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
- **Estimates are re-performable from themselves.** Each estimate
  records its inputs (values + fact ids) on its contribution
  lines, so verification does not depend on the current fact
  set: an estimate stays provable after it is superseded, and a
  tampered line is detectable forever. Missing inputs are named
  on the artefact (`partial` + `missing_drivers`); inapplicable
  drivers are recorded as such — the two are never conflated.
- **Rollups are sums, not estimates.** An outlook's product
  rollups and total are computed from its member estimates and
  graded against them; no code path aggregates independently.
- **Narrative figures are checked, not trusted.** The model port
  drafts words; the figure verifier admits the draft only if
  every figure in it belongs to the artefacts' figure set.
- **Alerts exist only as firings.** An alert is produced by the
  rule pack firing on a stored movement, and it carries the
  triggering movement ids and figures on its face; the verifier
  re-runs the firing function over the stored movements and
  requires the alert to be among its output. There is no insert
  path by which an alert could exist without its movement.
- **Alert state is derived, never stored.** The alerts table has
  no state column. State is the fold of the alert's acts —
  acknowledgement (named actor, note) and closure (named actor,
  reason from the pack's vocabulary) — each an insert-only
  artefact, with the transitions enforced when an act is
  recorded. Recording an act leaves the alert row itself
  byte-identical; the eval gate grades exactly that.
- **The manifest is the truth.** Anything the generator plants
  (spike, delay, events) is recorded in the manifest at generation
  time. Graders read the manifest, never a hand-copied expectation,
  so the truth cannot drift from the data.
- **Fail-closed model profiles.** Profile resolution happens at
  wiring; unknown names and unconfigured hosted profiles raise.
  There is no code path that substitutes one profile for another.

## Data model (migrations 0001–0003)

Fact tables (0001): `districts`, `area_facts`, `monsoon_facts`,
`soil_facts`, `application_rates`, `consumption_facts`,
`price_points`, `import_arrivals`, `supply_facts`,
`competitor_points`, `policy_events`, `field_reports`, and
`generator_manifest` (one row). Primary keys are the natural keys of
each fact, which is what makes a duplicate insert an error rather
than an overwrite. JSON payloads (policy-event product lists, the
manifest) are stored as JSON text in both dialects.

Artefact tables (0002): `demand_estimates` (one row per computed
estimate, with status, base/total, missing drivers, rule-pack
versions, the fact fingerprint and a `supersedes` link),
`demand_contributions` (the five stated lines per estimate, with
factor, delta, running value and the recorded inputs as JSON),
`season_outlooks` (the grid snapshot: member estimate ids, product
rollups and total as JSON + columns), and `outlook_narratives`
(the verified narrative text with the figure set it was checked
against). Artefacts share the facts' insert-only discipline.

Watch tables (0003): `price_movements` (one row per series-month:
the two movement figures, the baseline window and fact ids as
JSON, the rule-pack version and the fact fingerprint),
`price_alerts` (one row per firing: rule, band, period month,
triggering movement ids and figures as JSON — and deliberately
no state column), and `alert_acts` (acknowledgements and
closures: act kind, named actor, note or closing reason).

## Deployment

Multi-stage Dockerfile, non-root runtime user, port 8000. Compose
brings up the agent, Postgres 16 (pgvector image, ahead of the
retrieval rounds) and SeaweedFS as the S3-compatible object store
under the service name `minio`. Configuration is environment-only;
see `.env.example`.
