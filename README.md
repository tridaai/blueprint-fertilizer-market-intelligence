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
- **The dataset is generated for this blueprint** — built in-repo by
  the seeded generator described above, because no openly licensed
  Indian district-level fertilizer dataset carries the provenance
  this design needs. Kaveri Agro Inputs is fictional; any
  resemblance of figures to a real company's is coincidence of
  construction, not data.
- **Not built yet (on the round map):** the demand-estimation
  engine (R2), price/feedstock alerts (R3), the supply-gap tracker
  (R4), the policy registry views (R5), competitor/share views
  (R6), field-signal weighting (R7), the plain-language dashboard
  assembler (R8), scenario forks (R9), the weekly brief (R10), the
  Postgres production smoke (R11) and the console (R13).
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
  migrations.py      numbered migration runner
  store.py           the insert-only store port (SQLite / Postgres)
  modelport.py       offline default; hosted profiles fail closed
  service.py         dataset loading + read wiring
  api.py             FastAPI surface
  demo.py            the planted-truth walk
migrations/          0001 in sqlite + postgres dialects
scripts/             demo + local harness wrappers
evals/               the eval gate
docs/                architecture.md
```

Apache 2.0. A Trida AI blueprint — patterns are the point; the
fictional company's data is ours, generated for this repo.
