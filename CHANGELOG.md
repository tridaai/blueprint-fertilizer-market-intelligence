# Changelog — Fertilizer & Agrochemical Market Intelligence Agent

The full release history, one entry per round. Everything below
shipped under the same discipline: every number computed in code
from stored data, every artefact insert-only and re-performable,
and the eval gate's zero-tolerance counters green on both the
SQLite and Postgres profiles before the round closed.

## R1 — Spine, dataset, market data store

Config, JSON logging with request ids, the numbered migration
runner and migration 0001 in both dialects, the insert-only
market data store with provenance mandatory at the row level,
the fail-closed model port, and the seeded dataset generator:
two crop years across 12 districts × 2 seasons, with one planted
price spike (DAP, September 2025) and one planted import delay
recorded in a manifest — the grading truth every later round is
measured against. Consumption is derived from stored inputs
alone, and the eval gate re-derives all 288 figures.

## R2 — Demand-estimation engine

Estimates computed from area × stored application rates under a
versioned rule pack, with the four stated factor rules recorded
as contribution lines on the artefact itself; partial estimates
name their missing drivers. Season outlooks as sum-of-parts
rollups, a figure-verified outlook narrative, supersession by
fact fingerprint, and re-performance verification (migration
0002).

## R3 — Price & feedstock watch

Computed movement artefacts per series-month and a versioned
alert rule pack (class thresholds, spike + event window,
sustained move). Alerts exist only as firings of the pack on
stored movements and carry their triggering movements; alert
state is the fold of named acknowledgement/closure acts, never
a stored field (migration 0003).

## R4 — Import & supply-gap tracker

Monthly supply positions as re-performable chains — each month's
opening is the prior month's closing by recorded link — with
production plan-vs-actual, arrivals on actual dates and
consumption by the stated seasonal spread. Season gaps banded
by the versioned gap pack over two stated readings; projected
positions carry pinned assumption sets, and a slipped shipment
is excluded and named, never silently re-dated (migration
0004).

## R5 — Policy & subsidy event registry

Recorded policy facts promoted to artefacts under the versioned
policy pack: class vocabulary, stated effects with engine
linkages, windows derived by the pack's rule. Impact notes are
computed by a single scope query over the demand, price and
supply artefacts; hypothetical proposals are held apart (no
note, no board marker) and become real only by supersession.
Policy markers ride the watch board as their own count, never
inside the alert counts (migration 0005).

## R6 — Competitor & market-share intelligence

Tracked competitor points promoted to provenance-carrying
observation artefacts — a point without source or date is
refused. Shares computed by region structure over the district's
recorded market with Kaveri as the named residual and both
denominator readings labelled; stale months badged, excluded
from the headline and the exclusion named; all-stale reads
`not_current`, unobserved reads `no_observations` (migration
0006).

## R7 — Field signals & mobile intake

Structured intake validated at the port (missing attribution
fields named, never defaulted), an offline outbox with
exactly-once sync and conflicts kept both and linked, and a
verification queue of insert-only reviewer acts. The weighting
assessment applies kind effect × freshness decay × review state
against the head estimate, with an unreviewed report clamped to
the pack's 1.5-percentage-point unverified cap, graded exact
(migration 0007).

## R8 — Ask-in-plain-language dashboard assembler

Questions parsed into governed dashboard specs under the
versioned dashboard pack (deterministic grammar offline; hosted
proposals validated against the schema, refusals recorded and
rendered as gaps). Unanswerable parts render as gap panels that
name the data they would need and carry no figures. Assemblies
render only from artefacts with per-figure lineage, and the
whole dashboard is verified before serving — one mismatched
figure refuses it entire (migration 0008).

## R9 — Scenario forks & planning options

The versioned scenario pack: a bounded lever catalogue and the
no-numeric-transmission rule for policy levers. Forks run the
base artefact's own engine over a substituted fact view — the
recorded facts are never written — with exact per-line
reconciliation; planning-options comparisons are re-performed
under an independent verifier; adoption is a named planner's
insert-only act (migration 0009).

## R10 — Weekly brief, report packs & publication gate

A brief assembled for a stated week from artefacts only, stored
only after the figure verifier re-performs every figure and the
narrative passes the shared figure check; one wrong figure
refuses the brief wholesale and the refusal is its own artefact.
Export packs carry a provenance appendix and a checksum
manifest. Publication is an insert-only act binding the exact
artefact version by fingerprint, and the acts form the decision
log (migration 0010).

## R11 — Production data plane

The connector framework and source registry: pluggable ingest
for price feeds, production plans, import schedules, policy
notices and competitor observations, each source registered
with cadence, owner and freshness rule. Replay is idempotent;
a row without source/as_of is refused at the port; malformed or
contradictory facts quarantine with named reasons and engines
never consume a held row; corrections are new facts in a chain;
season-close actuals land as a distinct fact class that can
never overwrite an estimate (migration 0011). The Postgres
profile and production smoke join the standing gates.

## R12 — Season-close estimate scoring

Demand estimates scored against season-close actuals per
district × product: error, bias, and driver-attribution error
naming which contribution line was most wrong — re-performed
from the estimate and actual artefacts, with the most-wrong-line
attribution graded against a hand-computed fixture. Unmatched
rows are reported, never dropped (migration 0012).

## R13 — Console, market map & action queue

The district demand/gap map: every coloured cell equals its
artefact value, partial districts badged rather than coloured
confidently, monsoon and field-signal layers with confirmed and
pending signals in separate labelled classes. The market
morning board: one opening view per role, lanes derived at the
board's date and ranked by the owning packs, never by recency.
The shortage & gap action queue: one owned work item per
non-comfortable gap, closed only by a named act speaking the
pack's reason vocabulary (migration 0013).

## R14 — Regional rollups & season readiness

District → region → national rollups that are sums of the
member artefacts, identity holding to the tonne at every level;
a partial member makes every level above it partial with the
district named. The season readiness plan scores each region
complete or incomplete from artefacts — outlook published,
supply cover, open risks, field coverage — never self-declared
(migration 0014).

## R15 — Roles, approvals & collaboration

The versioned access pack: named principals with region and
product remits; a scoped read outside the remit returns absence
(existence hiding), and every guard decision — allowed, hidden
or refused — lands in a content-addressed audit log the
verifier re-decides, exports reconciling one-to-one with export
artefacts. Annotations pin to artefacts by hash and flag —
never move — when the target is superseded; follow-ups are
folds of acts; the publication review queue binds the reviewed
fingerprint so the publishing act must strike with the same one
(migration 0015).

## R16 — Alert subscriptions & escalation

Per-user subscriptions by product, district and severity across
price alerts, gap bands and policy markers — policy markers
never inflate price-alert counts. Deliveries and escalations
are derivations over the alert artefacts, subscription versions
and alert acts, re-performed on every read: there is no stored
delivery for a tamper to invent. Scheduled digests freeze a
subscription's alert/gap set at generation time (migration
0016).

## R17 — Field-report injection screening & reporter integrity

Field text is screened by the versioned integrity pack before
any model structuring; planted instruction-shaped reports never
reach a model prompt. Screening state is the fold of verdict
and release acts. Reporter-integrity boards compute volume
spikes, duplicate clusters and conflicts per reporter —
computed and shown to reviewers, never auto-punished (migration
0017).

## R18 — Cost, freshness & reliability monitoring

The run ledger records every model call the service's drafting
paths make: purpose from the monitoring pack, token counts,
cost priced in integer nano-USD at stated reference rates, and
SHA-256 hashes of prompt and reply — never their text; an
unrated profile's cost is null, never zero-filled. Monitoring
boards fold per-source freshness (fresh / stale / never loaded,
named on every board) and per-reporter reliability from
recorded acts and facts alone (migration 0018).

## R19 — Integration & admin configuration

Signed webhook deliveries: one insert-only delivery per trigger,
the payload the artefact read the system's own surfaces serve,
signed HMAC-SHA256; dispatch idempotent; a disable act silences
what follows it and rewrites nothing already earned. Scoped API
tokens: only the SHA-256 is stored, every presented read is
judged and the judgement recorded either way. Exchange ports
with stated contracts: one violation quarantines the batch
whole. Administered configuration: the threshold packs became
effective-dated registers — engines resolve the version in
force at the artefact's own date, verifiers resolve by the name
the artefact carries, so a change is never retroactive. Master
data (application rates, season calendar, districts, products,
crops) as versioned registers, rates engine-wired (migration
0019).

## R20 — Release hardening: version 1.0.0

No new features. The version is set to 1.0.0 in the package
metadata, `__version__` and the lockfile. The docs were swept
against the shipped tree: the architecture note's claim that a
LangGraph workflow orchestrates the brief pipeline is corrected
(the service performs those steps as stored-artefact
transitions; no LangGraph graph ships), the README's stack
section no longer promises DuckDB rollups (rollups are computed
by the in-repo engines) or a future dashboard layer (shipped in
R8), and the data-model heading now runs to migration 0019.
The migration set itself was reviewed as a set: 19 files per
dialect with identical names, numbering gapless 0001–0019, the
runner's split discipline verified (semicolons occur only
inside full-line comments, which the runner strips before
splitting; no trailing comments; no semicolons inside string
literals), and both dialect sets apply cleanly, in order, with
a re-run applying nothing. The full gate set was frozen green
on the release tree: per-file chunked pytest on both profiles,
the eval gate, all four standing checks, the demo and the
production smoke — figures in `docs/release-1.0.0.md`.

**1.0.0** is the state of the tree at this entry: twenty rounds,
274 tests on each profile with parity gap 0, the eval gate
passing with 102 zero-tolerance counters, and the honest limits
stated in the README's Honest status and the release notes —
no live model call has been made, no webhook leaves the
artefact, no LangGraph graph or vector retrieval ships, and the
Docker build is reviewed statically, never run.
