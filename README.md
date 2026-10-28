<p align="center">
  <img src="https://trida.ai/logos-rounded/trida-rounded.png" alt="Trida AI" width="96">
</p>

# Blueprint — Fertilizer & Agrochemical Market Intelligence Agent

A working prototype of the market-intelligence system a farm-input
company's business teams actually need: one governed view of demand,
prices, imports, policy and competitor movement across districts,
products and seasons — built for **Kaveri Agro Inputs**, a fictional
Indian fertilizer and agrochemical manufacturer, and built for
non-technical users. Product managers, regional sales heads and
strategy teams ask questions and read dashboards; they never touch a
query.

The design centre is that **every number is computed in code from
stored data with provenance**. The agent layer drafts words,
assembles dashboards and runs scenarios — it never originates a
figure, never renders an estimate without its driver contributions,
and never presents a stale figure as current.

> **Work in progress** — this blueprint is built and passing its automated test and eval gates, but it has not yet finished hands-on local testing, and its companion blog post is not yet published. Expect changes. This notice comes off when both are done.

## The laws (enforced in code)

1. **Every number is computed in code from stored data** — demand
   estimates, shares, gaps, movements. The model drafts words; it
   never originates a figure.
2. **Estimates show their drivers.** A demand or outlook number
   without its contribution breakdown cannot be rendered.
3. **Provenance per figure.** Every competitor, policy and field
   figure carries source + date; stale figures are labelled stale by
   a stated freshness rule, never silently presented as current.
4. **Scenarios are pinned forks.** Assumptions are named levers with
   bounds; a scenario never overwrites the base view.
5. **Field signals stay attributed.** A field report is an artefact
   with a named reporter; aggregation shows its inputs; a single
   unverified report cannot move an estimate beyond a stated cap.
6. **Nothing here advises a farmer.** This is a B2B market-intelligence
   tool for the input company's own teams — no agronomy advice
   surface exists.

## What Round 1 builds

- **The dataset generator** — a deterministic, seeded generator
  builds two crop years across 12 districts × 2 seasons (kharif /
  rabi): cropped area by crop, crop mix, monsoon deviation, soil
  nutrient status, monthly product and feedstock price series,
  import arrivals, domestic production vs plan, competitor series,
  policy events and structured field reports. It plants **one price
  spike** (DAP, September 2025) and **one import delay** (a DAP
  shipment two months late) and records every planted fact in a
  **manifest** — the grading truth every later round is measured
  against.
- **Consumption that is provable, not invented** — historical
  consumption per district × season × product is *derived* from
  stored inputs alone (area × stated application rates, adjusted by
  soil status and monsoon deviation, by rules stated in code). The
  eval gate re-derives every one of the 288 consumption figures from
  the store and compares.
- **The market data store** — one store port (SQLite locally,
  Postgres 16 via `DATABASE_URL`), numbered migrations, and
  **insert-only** writes: there is no update or delete verb, so a
  corrected figure is a new fact under a new date and history is
  never rewritten. Every fact row carries `source` and `as_of`.
- **The model port** — offline deterministic by default; the
  `anthropic`, `bedrock` and `nim` profiles are real adapters that
  **fail closed**: selected without their key/endpoint, they refuse
  at wiring time. Nothing silently falls back.
- **The API** — FastAPI reads for districts, demand inputs, prices,
  imports, supply, competitors, policy events, field reports and the
  manifest, plus `/health` and `/readiness`, structured JSON logs
  with request ids throughout.
- **The eval gate v1** — data-integrity counters against the
  manifest: planted spike/delay exactness, provenance completeness,
  district × season coverage, consumption re-derivation, and the
  insert-only guarantee. All zero-tolerance.

## What Round 2 adds

- **The demand-estimation engine** — for any district × product ×
  season, a `DemandEstimate` artefact computed in code from stored
  facts only: base demand from cropped area × the stored crop-mix
  application rates (every crop recorded, including the ones
  excluded for want of a rate), then the versioned rule pack's
  factor adjustments in a stated order — **soil nutrient status**,
  **monsoon deviation**, **price elasticity** against the product's
  own season-window price series, and **carry-in stock** from
  trailing production-vs-plan where supply facts exist. Every
  adjustment is a contribution line carrying its input values and
  the fact ids they came from, and the total is exactly
  base + the line deltas.
- **Partial means partial, and it says why** — a required input
  that is not in the store (the first crop year has no price
  history and no full carry-in window) yields a partial estimate
  naming the missing drivers. Nothing is substituted — no national
  average, no silent 1.0. A driver that cannot apply at all (MOP
  has no supply facts) is recorded `not_applicable` with its
  reason, which is a different statement from "missing".
- **Re-performable forever** — each estimate carries the
  fingerprint of the exact fact set behind it and is stored
  insert-only: recomputing over unchanged facts returns the same
  artefact, recomputing over changed facts supersedes it by link,
  and a verifier re-performs any estimate from its own recorded
  inputs, so a tampered line or total is detectable even after
  the facts have moved on. The engine's base × soil × monsoon
  reproduces the stored consumption derivation — two independent
  paths to the same figure, graded against each other.
- **The season outlook** — the full 72-cell district × product
  grid as one artefact whose product rollups and total are sums
  of the member estimates, computed from them and verifiable
  against them. There is no second aggregation anywhere.
- **A narrative that cannot invent a figure** — the agent step
  drafts the outlook narrative through the model port; a figure
  verifier checks every number in the draft against the
  artefacts' figure set before the narrative may be stored, and
  a wrong figure refuses the draft wholesale.
- **Surfaces** — migration 0002 (estimates, contributions,
  outlooks, narratives), estimate/outlook/narrative reads and
  acts on the API, and a CLI (`scripts/cli.py`) with the same
  surface. The eval gate grows the round-2 counters:
  re-performance, total identity, consumption drift, rollup
  identity, partial naming, narrative figures, tamper detection.

## What Round 3 adds

- **Movements, computed in code** — for every product and
  feedstock price series, a `PriceMovement` artefact per month:
  the month-on-month change and the change against the trailing
  baseline (the mean of the up-to-six preceding months), pinned
  to the exact price facts consumed and to the alert rule pack
  version. A month with too little history states no baseline
  rather than a thin one.
- **A versioned alert rule pack** — thresholds per series class
  (product / feedstock) for the `watch` and `alert` bands of the
  month-on-month and baseline rules, a **spike rule** (a single
  month moving 20% or more), and a **sustained-move rule** (three
  consecutive same-direction months adding up to a stated drift).
  The spike is treated as an event: after it fires, the spike
  rule stays quiet for that series through the pack's two-month
  event window — the unwind is the same event, and it still fires
  the ordinary movement rules on its own figures.
- **Alerts are recorded acts of the engine** — an alert exists
  only because a rule fired on a movement, and it carries the
  triggering movement ids and the computed figures on its face;
  the verifier re-performs every alert from the stored movements,
  so an alert without its movement, or with a tampered band or
  figure, is detectable. Firing is idempotent: re-running the
  pass over unchanged prices stores and fires nothing new.
- **Alert state is a fold of acts, never a field** — an alert is
  open until a named person acknowledges it (with a note), and
  closed when a named person closes it with a stated reason from
  the pack's vocabulary. The alerts table has no state column;
  state is derived from the insert-only act records, and the
  state machine (no acknowledging an acknowledged alert, no
  acting on a closed one) is enforced when an act is recorded.
- **Watch views** — a per-series read (latest movement, open
  alerts, the band those open alerts put the series in) and a
  watch board ranking every series by band, computed from the
  artefacts. Against the planted data the board is exact: DAP
  sits at the alert band on the September 2025 spike, the
  drifting series sit at watch, and the quiet series — natural
  gas, phosphoric acid, sulphur, chlorpyrifos — fire nothing.
- **Surfaces** — migration 0003 (movements, alerts, alert acts),
  `POST /watch/run`, movement and alert reads with verify
  endpoints, acknowledge/close acts, and `/watch` board reads on
  the API, with the same surface on the CLI. The eval gate grows
  the round-3 counters: missed planted alerts, false alerts,
  duplicate alerts, state edits outside acts, alerts without
  movements.

## What Round 4 adds

- **Supply positions, computed in code** — for every product
  with a supply side (the three produced fertilizers plus
  import-only MOP), a `SupplyPosition` artefact per month:
  opening + domestic production + import arrivals −
  consumption = closing. Every component is a recorded line
  pinned to its facts; the production line carries plan
  alongside actual, the import line names the shipments that
  landed that month, and consumption enters by the pack's
  stated spread (a season's recorded consumption spread evenly
  over its six application months, the final month carrying the
  rounding residual). The first tracked month's opening is the
  pack's stated derivation — one month of cover at the first
  tracked crop year's own consumption rate — and every later
  opening is the prior month's closing, so the whole chain is
  re-performable end to end. A product with no production and
  no arrivals (the agrochemicals) has no position, and the
  engine says so rather than zero-filling one; MOP's production
  line reads `not_applicable`, with its reason.
- **The supply-gap view** — per product-season, a `SupplyGap`
  artefact: the R2 outlook's demand rollup against the supply
  available to the season, with the season's import programme
  tested at the gap's as-of month — shipments due, credited
  once landed (to the season they were scheduled for), slipped
  tonnage named. The band (comfortable / tight / short) is the
  more severe of two stated readings in the versioned gap
  pack — programme cover and the level gap — and the artefact
  records which reading bound it. The planted DAP delay reads
  **short** through October and November 2025 (55,000 t slipped,
  programme cover 52.59%) and resolves to comfortable when the
  vessel lands in December; import-only MOP binds on the level
  reading instead.
- **Forward positions** — a `SupplyProjection` runs an actual
  position forward to a season's end on a pinned assumption
  set: production at plan, imports at their expected months,
  consumption by the same spread. Labelled `projected`
  throughout; a horizon month with no plan on record is named
  beyond the plan horizon and left unprojected (status
  `partial`), never extrapolated. If a scheduled import slips —
  its expected month passes with no arrival — the projection
  is recomputed as a new artefact superseding by link, the
  slipped vessel excluded and the change named in its
  assumption changes (`slipped_unlanded`); when it later
  lands, the next projection names that too
  (`landed_after_slip`).
- **Verification throughout** — positions verify from their
  own recorded inputs (identity, production against the supply
  fact, shipments against the arrival facts, consumption cells
  against the spread rule, the opening against its stated
  basis), and the chain head must also match a fresh
  re-performance; gaps and projections verify by full
  re-performance, assumption changes included. Tampering with
  a stored position or one of its lines is detectable.
- **Surfaces** — migration 0004 (positions + component lines,
  gaps, projections), `POST /positions`, `/gaps`,
  `/projections`, position/gap/projection reads with verify
  endpoints on the API, and `positions` / `position` / `gap` /
  `projection` with their verify commands on the CLI. The eval
  gate grows the round-4 counters: position identity
  violations, planted delay dip mismatches, gap band
  mismatches, projection supersession failures, undetected
  position tampering.

## Product lineage

This blueprint follows patterns from the group's own products. It
ships its own original code; the references name the pattern, not a
dependency.

- **The market data layer is the [Farmioc](https://farmioc.com)
  DataStore shape** — demand, prices, imports, policy, competitor
  and field signals held in one ontology with provenance, the way
  Farmioc's agricultural data platform organises India's agri data.
- **The dashboard and ask-in-plain-language layer (later rounds) is
  the [Trida Labs](https://tridalabs.com) TridaPad + AgentSQL
  shape** — natural language → governed query → dashboard, on a
  collaborative analytics surface. The tool ports in this repo are
  MCP-shaped, the same shape TridaPad's MCP server exposes, so the
  agent layer here could sit directly on TridaPad + AgentSQL in a
  production deployment.

## Stack

Python 3.12 · FastAPI · Pydantic · LangGraph (agent workflow in
later rounds: ingest → estimate → assemble → brief → publish gate) ·
PostgreSQL 16 as the system of record with SQLite for the offline
profile · DuckDB for rollups (later rounds) · numpy/pandas under the
stated in-repo estimation engine · model port with offline default
and fail-closed hosted profiles (Anthropic, Bedrock, NIM) ·
S3-compatible object storage (SeaweedFS in compose) · uv with exact
pins and a frozen `constraints.txt` · multi-stage non-root Docker.

## Quickstart

```bash
make install        # uv sync (or: make install-pip)
make demo           # generate the dataset, walk the planted truth
make harness        # exercise the HTTP read surface in-process
make test           # pytest
make evals          # the eval gate
make serve          # the API on http://localhost:8000
```

Configuration is environment-only (see `.env.example`): model
profile first, SQLite unless `DATABASE_URL` points at Postgres.
`docker compose up` brings the agent, Postgres+pgvector and the
SeaweedFS S3 gateway together.

## Honest status

- **Built and gated in R1:** spine (config, JSON logging with
  request ids, migrations, Dockerfile/compose), the dataset
  generator + manifest, the insert-only market data store, the
  model port, the API read surface, demo, harness, tests and the
  eval gate.
- **Built and gated in R2:** the demand-estimation engine (base
  from area × stored rates, four stated factor rules as recorded
  contribution lines, partial estimates naming missing drivers,
  fact-fingerprint supersession, re-performance verification),
  the season outlook with sum-of-parts rollups, and the
  figure-verified outlook narrative — migration 0002, API + CLI
  surfaces, demo walk, tests and eval counters.
- **Built and gated in R3:** the price & feedstock watch —
  computed movement artefacts per series-month, the versioned
  alert rule pack (class thresholds, spike + event window,
  sustained-move), alerts as recorded acts of the engine carrying
  their triggering movements, acknowledgement/closure as named
  acts with state derived (never stored), and the watch views —
  migration 0003, API + CLI surfaces, demo walk, tests and eval
  counters.
- **Built and gated in R4:** the import & supply-gap tracker —
  monthly supply positions as re-performable chains (stated
  initial-stock derivation, production plan-vs-actual, arrivals
  on actual dates, consumption by the stated seasonal spread),
  season supply gaps banded by the versioned gap pack over two
  stated readings (programme cover and level), and projected
  positions with pinned assumption sets and named slip/landing
  changes — migration 0004, API + CLI surfaces, demo walk,
  tests and eval counters.
- **The dataset is generated for this blueprint** — built in-repo by
  the seeded generator described above, because no openly licensed
  Indian district-level fertilizer dataset carries the provenance
  this design needs. Kaveri Agro Inputs is fictional; any
  resemblance of figures to a real company's is coincidence of
  construction, not data.
- **Not built yet (on the round map):** the policy registry
  views (R5), competitor/share views (R6), field-signal
  weighting (R7), the plain-language dashboard assembler (R8),
  scenario forks (R9), the weekly brief (R10), the Postgres
  production smoke (R11) and the console (R13).
- **No live model has been called.** Hosted profiles are wired as
  adapters and refuse loudly until configured; the offline profile
  is what tests and evals run.
- **Docker image build was not run** in the build sandbox (no
  daemon); the Dockerfile and compose file follow the portfolio's
  verified pattern and are reviewed statically.

## Layout

```
src/fertilizer_intelligence/
  config.py          environment-only settings
  logging_config.py  JSON logs with request ids
  models.py          fact models — provenance is mandatory
  generator.py       the seeded dataset generator + manifest
  demand_rules.py    the versioned demand rule pack (factors, windows)
  demand.py          the demand engine, verifiers, outlook narrator
  alert_rules.py     the versioned alert rule pack (bands, spike, sustained)
  movements.py       the movement engine, rule firing, alert verification
  supply_rules.py    the versioned supply pack (identity, spread, gap bands)
  supply.py          positions, gaps, projections and their verifiers
  migrations.py      numbered migration runner
  store.py           the insert-only store port (SQLite / Postgres)
  modelport.py       offline default; hosted profiles fail closed
  service.py         dataset loading + engine/watch/supply wiring
  api.py             FastAPI surface
  cli.py             command-line surface (same reads and acts)
  demo.py            the planted-truth walk
migrations/          0001-0004 in sqlite + postgres dialects
scripts/             demo + CLI + local harness wrappers
evals/               the eval gate
docs/                architecture.md
```

Apache 2.0. A Trida AI blueprint — patterns are the point; the
fictional company's data is ours, generated for this repo.
