# Release 1.0.0 — Fertilizer & Agrochemical Market Intelligence Agent

Twenty rounds, frozen green. This is the market-intelligence
system built for **Kaveri Agro Inputs**, a fictional Indian
fertilizer and agrochemical manufacturer: one governed view of
demand, prices, imports, policy and competitor movement across
districts, products and seasons, for business teams who ask
questions and read dashboards and never touch a query.

The design centre, held across all twenty rounds: **every
number is computed in code from stored data with provenance.**
The agent layer drafts words, assembles dashboards and runs
scenarios — it never originates a figure, never renders an
estimate without its driver contributions, and never presents
a stale figure as current. Nothing in the system advises a
farmer; it is a B2B tool for the input company's own teams.

## What a deployer gets

- **A demand engine whose estimates show their work** — base
  from area × stored application rates, four stated factor
  rules recorded as contribution lines on the artefact, partial
  estimates naming their missing drivers, season outlooks as
  sum-of-parts rollups, and season-close scoring that grades
  each estimate against actuals and names its most-wrong
  contribution line.
- **A price & feedstock watch** — computed movements, a
  versioned alert rule pack, alerts that exist only as firings
  and carry their triggering movements, state as the fold of
  named acts, subscriptions and digests whose deliveries are
  derivations, never stored rows.
- **An import & supply-gap tracker** — positions as
  re-performable chains, gaps banded over two stated readings,
  projections with pinned assumption sets, and an action queue
  that owns every non-comfortable gap from birth.
- **A policy & subsidy registry** — stated effects as data,
  impact notes computed by scope query, hypothetical proposals
  held apart until enacted by supersession.
- **Competitor & market-share intelligence** — provenance per
  figure, stale points badged and excluded from the headline
  with the exclusion named.
- **Field signals with attribution discipline** — structured
  intake validated at the port, an offline outbox with
  exactly-once sync, a reviewer verification queue, injection
  screening before any model sees the text, reporter-integrity
  boards, and the 1.5-percentage-point unverified cap graded
  exact.
- **Ask-in-plain-language dashboards** — governed artefact
  selection, per-figure lineage, unanswerable parts rendered
  as named gap panels carrying no figures, the whole dashboard
  verified before serving.
- **Scenario forks** — bounded levers over a substituted fact
  view; the recorded facts are never written; adoption is a
  named act.
- **A weekly brief with a publication gate** — figure-verified
  wholesale (one wrong figure refuses the brief), export packs
  with provenance appendices and checksum manifests, and a
  decision log that re-derives from the publication acts.
- **A production data plane** — a connector registry, replay
  idempotence, quarantine with named reasons, corrections as
  new facts, season-close actuals as a distinct fact class.
- **Access as a pack** — named principals with region/product
  remits, existence hiding on out-of-scope reads, and an audit
  log the verifier re-decides, exports reconciling one-to-one.
- **Monitoring** — a run ledger pricing every model call in
  integer nano-USD at stated reference rates with prompt/reply
  hashes (never text), freshness boards naming never-loaded
  sources, reliability folded only from recorded acts/facts.
- **Integration & administration** — signed webhook deliveries
  (struck records; the transport is the integrator's), scoped
  API tokens storing only the SHA-256 with every presented
  read judged on the record, exchange ports whose contracts
  quarantine a violating batch whole, effective-dated
  configuration registers that are never retroactive, and
  master data as versioned registers.

## How to run it

```bash
make install        # uv sync (or: make install-pip)
make demo           # generate the dataset, walk the planted truth
make test           # pytest (SQLite profile)
make evals          # the eval gate
make mapcheck       # re-perform every figure the map/board/queue show
make integritycheck # plant injections; grade screening + integrity
make monitoringcheck
make integrationcheck
make serve          # the API on http://localhost:8000
```

Configuration is environment-only (see `.env.example`):
SQLite unless `DATABASE_URL` points at Postgres. `docker
compose up` brings the agent, Postgres 16 and the SeaweedFS
S3 gateway together. The Postgres profile is a tested
profile: the full suite runs against it with per-test schema
isolation, and `make smoke` (needs `DATABASE_URL`) proves a
fresh deployment end to end.

## Freeze figures (release tree)

The full gate set, run on the exact tree this document ships
in, per-file chunked with figures read from the run logs:

- **pytest, SQLite profile: 274 passed, 0 failed** (19 files)
- **pytest, Postgres profile: 274 passed, 0 failed** (19
  files) — **parity gap 0**
- **Eval gate: PASS** — 102 zero-tolerance counters, all at
  zero
- **Standing checks: all PASS** — monitoring, integrity, map
  board, integration (each exit 0)
- **Demo: exit 0**
- **Production smoke: PASS** — the Postgres profile serves end
  to end, all 19 migrations applying cleanly on a fresh schema
- **Local harness: exit 0**

Freeze A ran in two passes: a runtime restart killed the
first session after 15 of 19 SQLite chunks; the completed
chunk logs were kept, the four remaining SQLite chunks and
the whole Postgres leg were re-run in full, and no partial
figure was signed off. The Postgres cluster died once in the
same window and was re-stood before its leg began.

## Migration review (part of this round)

The 19-migration set was reviewed as a set, not file by file:

- 19 files per dialect with **identical names**, numbering
  **gapless 0001–0019**.
- The runner drops full-line comments before splitting on
  `;`; verified across every file: semicolons occur only
  inside full-line comments (four files per dialect), there
  are **no trailing comments**, **no interior semicolons** on
  code lines, and **no semicolons inside string literals**.
- Both dialect sets apply cleanly, in order, through the
  repo's own runner on fresh databases, and a second run
  applies nothing (recorded in `schema_migrations`).

## Honest limits — what 1.0.0 is not

- **No live model has been called.** Hosted profiles
  (Anthropic, Bedrock, NIM) are wired as adapters and refuse
  loudly until configured; tests and evals run the offline
  deterministic profile. A deployment with a real key is the
  remaining live-verification step.
- **No LangGraph graph ships.** The ingest → estimate →
  assemble → brief → publish-gate flow is the service's own
  pipeline of stored artefacts; `langgraph` is a pinned
  dependency the shipped code does not import. The
  architecture note's earlier claim otherwise was a stale
  promise, corrected in this round's docs sweep.
- **No vector retrieval ships.** Compose runs the pgvector
  Postgres image, but no embedding or vector-search surface
  exists; the retrieval-shaped reads are the governed
  artefact selections. numpy and pandas are likewise pinned
  but unused — the engines are pure stated Python, and no
  DuckDB is used anywhere (rollups are computed in code).
- **Outward surfaces stop at the artefact.** A webhook
  delivery is a struck, signed record of what would be sent —
  no HTTP call is made; the transport belongs to the
  integrator. The exchange ports are stated shapes with local
  doubles: no live ERP or CRM is connected, and token reads
  guard this system's own read surface, not a network
  perimeter.
- **Of the master-data registers, only application rates are
  engine-wired.** The season calendar, districts, products
  and crops are versioned records of reference, graded
  against the state they describe.
- **Screening covers the field-report text path** named in
  R17/R18; deliveries and digests remain pull-only
  derivations, by design.
- **The Docker image build was never run** (no daemon in the
  build sandbox); the Dockerfile and compose file follow the
  portfolio's verified pattern and are reviewed statically.
  The S3 store is verified to its port; SeaweedFS is not run
  end to end.
- **The data is generated for this blueprint** — gold by
  construction, with the planted spike and delay recorded in
  the generator manifest that grades the engines.

## What a deployment still has to do

Configure a hosted model profile and run the live
verification; put a transport behind the webhook deliveries;
connect real feeds through the connector registry (each
source admitted with provenance and a freshness rule);
operate the Postgres profile as the system of record; and
complete the hands-on developer testing and companion blog
post that the README's work-in-progress notice waits on —
the notice stays until both are done.
