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

Round 4 adds the supply tracker behind the same ports:
`supply_rules.py` states the pack once (the position identity,
the consumption spread, the initial-stock derivation, programme
accounting, the gap bands, the projection basis), and
`supply.py` computes positions, gaps and projections from the
stored facts — production and arrival facts from 0001, demand
from the R2 outlooks — storing each as an artefact (migration
0004) with its own re-performance verifier.

Round 5 adds the policy registry behind the same ports:
`policy_rules.py` states the pack once (the class vocabulary
with each class's driver and engine linkage, the recorded-kind
mapping, the planted directions, the window derivation), and
`policy.py` registers the recorded policy facts as artefacts
and computes impact notes by a single scope query over the
demand, price and supply artefacts (migration 0005), each with
its own re-performance verifier. The service ensures the
outlooks and position chains a note can name before the query
runs, and lays the registry's current, real, open-window
events onto the watch board as typed markers.

Round 6 adds competitor & share intelligence behind the same
ports: `share_rules.py` states the pack once (the freshness
window per source class, the season attribution, the
structure construction, the reading bases and statuses), and
`share.py` promotes the tracked competitor points to
observation artefacts and computes market shares and share
movements from the stored observations plus the R2/R4
volumes (migration 0006), each with its own re-performance
verifier. The service ensures the observation pass and the
season outlook before a share is computed, and the stale
read is compute-or-return like the share read itself.

Round 7 adds field signals & mobile intake behind the same
ports: `field_rules.py` states the pack once (the intake
contract, the kind normalization and effects, the freshness
decay and expiry, the unverified cap, the review acts and
their reason vocabularies), and `field.py` lands structured
submissions exactly once per (submission id, payload) —
conflicts kept both, linked — folds reviewer acts into a
derived review state, and computes the weighting assessment
against the head R2 estimate (migration 0007), each artefact
with its own re-performance verifier. The planted R1 field
reports enter through the same landing machinery by
promotion, so one lifecycle covers every field signal; the
service ensures the cell's estimate before an assessment is
computed, and the assessment read is compute-or-return like
the other engines' reads.

Round 8 adds the plain-language dashboard assembler behind
the same ports (AgentSQL-shaped: natural language → governed
artefact selection → static page): `dashboard_rules.py`
states the pack once (the panel vocabulary and the scope
each kind binds, the stated defaults, the gap wording, the
role default dashboards as data), and `dashboard.py` parses
a question into a dashboard spec (migration 0008) — the
offline profile's deterministic grammar, or a hosted
profile's proposals validated against the governed schema
with refusals recorded and rendered as gaps — then
assembles the spec into a static page rendered only from
artefacts, verifying every figure against its pinned
artefact before the assembly is stored. Figure extraction
is one code path shared by assembly and verification, so
what is served is exactly what is re-performed.

Later rounds add, behind the same ports: scenario forks and
the weekly brief with its figure verifier. The LangGraph
workflow (ingest → estimate → assemble → brief → publish
gate) orchestrates those steps; every state transition is a
stored artefact.

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
- **Positions are chains, not snapshots.** A month's opening is
  the prior month's closing by recorded link (the first month's
  opening is a stated derivation over stored consumption), so
  the chain re-performs end to end and a tampered month is
  detectable from its own lines and from its neighbours. Every
  component is a line over named facts; a component with no
  facts is a computed zero or a `not_applicable` line with its
  reason — never a silent fill.
- **A gap names both of its readings.** The season band is the
  more severe of the programme-cover reading and the level
  reading, and the artefact records which one bound it, with
  due / credited / slipped programme tonnage on its face — a
  delayed vessel moves the band even when the stock level is
  deep in surplus, and the recovery is a new artefact, not an
  edit.
- **Projections carry their assumptions as data.** The
  assumption set is pinned on the artefact (basis position,
  plan facts, scheduled and slipped shipments), a slipped
  shipment is excluded and named — never silently re-dated —
  and a superseding projection stores the named difference
  against its predecessor; the verifier re-derives that
  difference and requires it to match.
- **A policy effect is stated data, never an engine input.**
  A registry event's effect (direction, driver, mechanism,
  linkage) is recorded on the artefact and echoed by its
  impact note, but no computation consumes it: the linkage
  names the engine surface a reader should inspect, it does
  not move a number. A registration whose driver disagrees
  with its class's stated driver is refused at the desk.
- **Impact is a scope query, not a narrative.** An impact
  note is the output of one stated query over stored
  artefacts (estimate heads, price points, position heads
  inside the window and scope), and the verifier re-runs the
  same query and requires the same member sets. An empty
  result is a stated status (`no_observed_scope`), never an
  omitted note.
- **Hypotheticals are separated by construction.** A
  proposed policy is a registration with the flag set: the
  note computation refuses it, the board marker pass skips
  it, and the listings filter on it. Because registrations
  are insert-only, the only path from proposal to real event
  is a superseding registration — the proposal artefact
  remains on record, byte-identical.
- **Markers are not alerts.** A watch-board policy marker is
  a registry reference laid on a series row; it has its own
  count field and no path into the alert counts, the band,
  or any alert state — the eval gate grades the separation.
- **Share is structure, not tonnage.** Tracked competitor
  volumes are whole-region figures; district consumption is
  district-level. The share engine never allocates raw region
  tonnage into a district: it takes each competitor's
  structure share of the region's observed market (tracked
  volumes plus Kaveri's home-market anchor, the region's R2
  demand total spread over the window) and distributes the
  district's recorded market by it. Kaveri's line is the
  residual, and the artefact states that any untracked
  seller sits inside it. The two denominator readings —
  of the observed market, of total demand — are computed
  and labelled separately, never blended.
- **Freshness decides what is current.** An observation's
  age at the read date is judged against the pack's window
  for its source class; a class with no stated window is
  never fresh. Stale months are badged on the artefact,
  excluded from the headline, and the exclusion is named
  with its count. When every month is stale the share reads
  `not_current` and carries no headline — the full-season
  figures remain inspectable under their own basis label,
  but nothing presents a stale number as the current share.
- **Field signals are attributed, exactly-once, and never
  overwritten.** A field report exists only as an artefact
  landed from a submission that named its reporter,
  district, product and observation date — the port refuses
  anything less, naming the missing fields. Landing is
  keyed by (submission id, payload hash): re-sends are
  duplicates, and a changed payload under a known id lands
  alongside the original, linked — the store has no path by
  which one report replaces another. Review state is the
  fold of insert-only reviewer acts (the reports table has
  no state column), and rejection is terminal in the fold.
- **Field weight is review state times freshness, capped
  while unverified.** The assessment is the field signals'
  only path into a number: each report contributes its
  kind's stated effect, decayed by the pack's half-life,
  confirmed reports at full decayed weight, unreviewed
  reports clamped per-report to the pack's unverified cap,
  queried and rejected reports at zero, expired reports
  named at zero. The estimate an assessment adjusts is read
  and referenced, never mutated — the base and adjusted
  totals ride side by side on the assessment, and every
  contribution line names its reporter and review state, so
  the adjustment re-performs from the stored reports, acts
  and pack alone.
- **A dashboard is a verified selection of artefacts.** A
  dashboard spec names governed panels, each bound to one
  stated artefact query; an assembly renders only from
  artefacts, and every figure on it traces to an artefact id
  and that artefact's as-of. A question part with no artefact
  family is a gap panel: it states the data it would need
  and carries no figures. Before an assembly is stored,
  every figure is re-performed against its pinned artefact —
  one mismatch refuses the whole dashboard, so no partial or
  unverified page is ever served. A figure whose source
  superseded since the question was asked renders from the
  current head with the supersession noted, and re-assembly
  states the diff against the previous assembly. Rendering
  is a pure function of the stored content, so a stored page
  that was altered after assembly fails verification
  byte-for-byte.
- **The manifest is the truth.** Anything the generator plants
  (spike, delay, events) is recorded in the manifest at generation
  time. Graders read the manifest, never a hand-copied expectation,
  so the truth cannot drift from the data.
- **Fail-closed model profiles.** Profile resolution happens at
  wiring; unknown names and unconfigured hosted profiles raise.
  There is no code path that substitutes one profile for another.

## Data model (migrations 0001–0008)

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

Supply tables (0004): `supply_positions` (one row per
product-month: the five position figures as columns, the rule
pack version, the fact fingerprint, a `supersedes` link and the
full artefact as a JSON payload), `supply_position_lines` (the
five component lines per position: status, tonnes, fact ids and
recorded inputs as JSON), `supply_gaps` (one row per
product-season computation: demand, available, gap and
percentage as columns, band and band basis, the demand outlook
id, a `supersedes` link and the payload), and
`supply_projections` (one row per projection: basis month,
status, opening/closing, a `supersedes` link and the payload,
which carries the projected months and the pinned assumption
set). All four are insert-only, like every artefact table here.

Registry tables (0005): `policy_registry_events` (one row per
registration: the event id and its recorded-fact link, the
class, window months, scope lists and the hypothetical flag as
columns; the stated effect, detail and provenance in the JSON
payload, with a `supersedes` link and the fact fingerprint),
and `policy_impact_notes` (one row per note: the registry id
it belongs to, its status and member counts as columns, the
member artefact ids and cells in the payload, a `supersedes`
link). Both are insert-only; the current registration of an
event is the head of its supersedes chain, never a flagged
row.

Share tables (0006): `competitor_observations` (one row per
tracked point promoted: competitor, region, product, month
and its attributed season as columns; district coverage,
volume, price and the provenance pair in the payload),
`market_shares` (one row per district × product × season ×
read date: status, the read date and the share-pack version
as columns; the month detail, both readings, the allocation
statement and the provenance panel in the payload, with a
`supersedes` link), and `share_movements` (one row per
district × product × season: the two crop years and the
read date as columns; the per-seller rows, the biggest
mover with its observation provenance, and the two share
ids in the payload). All three are insert-only.

Field tables (0007): `field_signal_reports` (one row per
landed submission: the submission id and payload hash, the
reporter, district, product, signal type and normalized
kind, the observation date and its attributed season, the
source label and landing date, and a `conflicts_with` link
as columns; the submitted form fields and the submission
exactly as received in the payload — deliberately no review
state column, state being the fold of the acts),
`field_review_acts` (one row per act: the report it acts
on, the act, the named reviewer, the reason from the act's
vocabulary, an optional note and the act date), and
`field_signal_assessments` (one row per district × product
× season × read date: the head estimate it adjusts, the
base and adjusted totals and the adjustment as columns; the
per-report contribution lines, the named exclusions and the
capped list in the payload, with a `supersedes` link). All
three are insert-only.

Dashboard tables (0008): `dashboard_specs` (one row per
asked question: the question text, the named asker, the
optional role and save-name, the as-of and the dashboard
pack version as columns; the parsed panels with their
artefact bindings and the full parse provenance — rules
used, defaults applied, proposals refused and why — in the
payload), and `dashboard_assemblies` (one row per assembly
of a spec: the assembly date and a `supersedes` link to the
previous assembly as columns; the resolved panels with
their figures, rows and supersession notes, the computed
diff against the previous assembly, and the rendered HTML
page in the payload). Both are insert-only; a spec's
current dashboard is the head of its assemblies' supersedes
chain.

## Deployment

Multi-stage Dockerfile, non-root runtime user, port 8000. Compose
brings up the agent, Postgres 16 (pgvector image, ahead of the
retrieval rounds) and SeaweedFS as the S3-compatible object store
under the service name `minio`. Configuration is environment-only;
see `.env.example`.
