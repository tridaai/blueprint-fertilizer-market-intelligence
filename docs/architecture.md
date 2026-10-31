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

Round 9 adds scenario forks and planning options behind
the same ports: `scenario_rules.py` states the pack once
(the bounded lever catalogue with its bounds and zero
rules, the policy-no-transmission rule, the stated ranking
criteria), and `scenario.py` forks a head estimate or
projection by running that artefact's own engine over a
read-through fact view — the recorded facts are never
written — reconciling the fork line by line against the
base, builds planning-options comparisons whose rows carry
their criterion values and per-figure lineage, and records
adoptions as named insert-only acts (migration 0009).
Forks live only in the scenario tables; the dashboard pack
gains a `scenario` panel kind that resolves only a fork a
question explicitly names, with every figure badged as a
scenario and the dashboard verifier failing an unbadged
one.

Round 10 adds the weekly brief behind the same ports:
`brief_rules.py` states the pack once (the week window,
the season-scope rule, the section order, the pack kinds
and table columns, the appendix and manifest names, the
draft and published badges), and `brief.py` collects a
week's sections from the heads of record, assembles the
brief only after the figure verifier re-performs every
figure from its pinned artefact and the narrative passes
the shared figure check (migration 0010), builds export
packs with a provenance appendix and a checksum manifest,
and records publication as insert-only acts whose chains
form the decision log. The LangGraph workflow (ingest →
estimate → assemble → brief → publish gate) orchestrates
those steps; every state transition is a stored artefact.

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
- **A brief is a verified selection, refused wholesale.** A
  weekly brief's sections are collected from the heads of
  record at its as-of under the brief pack's scope rule, and
  every figure carries its artefact lineage. Before a brief
  is stored, the verifier re-performs every figure from its
  pinned artefact and re-verifies each pinned artefact under
  its own family's verifier, and the drafted summary is
  admitted only if every number in it belongs to the brief's
  figure set. One wrong figure refuses the whole brief: no
  partial brief is stored and no brief is corrected in
  place — the refusal is its own artefact, and a later clean
  assembly for the same week supersedes it by link.
- **Published is an act, never a field.** No artefact table
  carries a published flag. Publication is an insert-only
  act by a named publisher binding the exact artefact
  version by fingerprint; the target must verify under its
  family's verifier at publication time. Acts form one
  supersedes chain per family (a week's briefs, a season's
  outlooks), publication state is the fold of the acts, and
  the decision log re-derives from the acts alone — the
  log's verifier requires each family's chain to be
  unbroken and each act to still bind the artefact it
  published, so a tampered target or a broken chain is
  detectable forever.
- **Exports carry their own proof.** A report pack's files
  are rendered purely from the stored pack artefact, which
  carries a checksum manifest over them and a provenance
  appendix naming the artefact behind every table. A byte
  flipped in an exported file fails its checksum and is
  named; the pack's tables additionally re-perform against
  a fresh collection from the store at the pack's as-of, so
  an export figure that differs from the read is a defect
  the verifier states, not a discrepancy a reader must find.
- **The manifest is the truth.** Anything the generator plants
  (spike, delay, events) is recorded in the manifest at generation
  time. Graders read the manifest, never a hand-copied expectation,
  so the truth cannot drift from the data.
- **A map cell is a composition, never a computation.** The
  district map (R13) computes no figure: each cell binds artefact
  ids — estimate, prior-year estimate, gap, assessment — and its
  readings are stated compositions of theirs under the map pack
  (the worse of the product gap band and the district's signal
  pressure carries the cell). Verification is archival: a stored
  map re-performs against the artefacts it binds, fetched by id,
  so it stays provable after those artefacts are superseded. A
  partial estimate can never render as a confident colour, and
  no-data is a rendering distinct from zero.
- **Evidence classes are never merged.** The map's signal layer
  keeps confirmed field reports and pending (unreviewed or
  queried) reports in separate, labelled classes, folded from
  the review acts at the map's date; rejected reports appear in
  neither and are counted on the cell. A combined count would be
  a different — and false — claim about what the district knows.
- **Board membership is derived state, ranked by packs.** A
  morning-board lane holds exactly what its derivation produces
  at the board's date (an alert whose acts fold to open, a map
  cell banded tight or short, a brief no publication act names),
  ordered by the owning packs' severity rules, never by recency;
  the verifier re-derives the lanes as ordered lists.
- **Queue membership is the gap record, owned from birth.** The
  action queue holds one item per non-comfortable gap head —
  derived, never curated — struck with a named owner and a due
  date from the band's term. Its state, owner and scenario slot
  are folds of insert-only acts; a close must speak the pack's
  reason vocabulary, and a scenario link names a stored fork by
  reference and copies nothing.
- **A rollup is a decomposition, never a rival figure.** The
  regional rollup (R14) sums exactly the member estimates its
  outlook names, grouped district → region → national; its
  national total is the outlook's own total, re-performed by an
  independent route that groups the store's estimate rows
  directly. A partial member names its district and makes every
  level above it partial; a memberless district is named missing
  and contributes nothing — zero appears only next to the names
  that explain it. Gap positions are carried by reference under
  the head gap's own id and figures, with the demand basis
  stated; the identity re-performance grades a gap's demand
  against the rollup's national total only when the gap was
  struck from this rollup's outlook.
- **Readiness is scored, never declared.** A season readiness
  plan's four lines are derivations over other artefacts at the
  plan's date: the outlook line folds the publication acts (an
  outlook counts only behind its act, and the act must name the
  head outlook), the cover line reads the gap heads, the risks
  line folds alert acts and queue acts, and the coverage line
  folds field-review acts. The verifier re-derives every line by
  a second route over the same record; because folds are by
  date, acts recorded on a later date move the next plan and
  never rewrite a struck one.
- **Access is a pack, and its decisions are artefacts.** Who
  may read what is decided by a versioned register of named
  principals and remits, never by ad-hoc checks at call sites:
  an unregistered name resolves to the narrowest remit. A
  scoped read that falls outside the remit returns absence —
  the record reads exactly as if it did not exist — and every
  decision, allowed, hidden or refused, is written to an
  insert-only audit log whose entries are content-addressed
  and re-decided by the verifier, exports included: the log's
  export entries must reconcile one-to-one with the export
  packs in the store.
- **Collaboration rides the same folds.** An annotation pins
  itself to its target by hash, and whether the target family
  has moved on is folded from the supersession links at read
  time, never stored on the note. A follow-up's state is the
  fold of its acts and a terminal fold refuses further acts.
  The publication review queue is an artefact like any other:
  its membership is the publication fold at its date, its
  diffs are computed against the family's published head, and
  each item binds the fingerprint as reviewed so the act that
  publishes must strike with the same fingerprint — the queue
  refuses wholesale, with the refusal recorded, when a pending
  artefact fails its own verifier.
- **Fail-closed model profiles.** Profile resolution happens at
  wiring; unknown names and unconfigured hosted profiles raise.
  There is no code path that substitutes one profile for another.

## Data model (migrations 0001–0018)

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

Scenario tables (0009): `scenario_forks` (one row per fork:
kind, base artefact, creator, as-of and the scenario pack
version as columns; the applied lever records with their
base values and outcomes, the named gaps, the parse
provenance, the engine result and the line-by-line
reconciliation in the payload), `planning_options` (one
row per comparison: kind, base, creator, as-of and pack
version as columns; the fork ids, the stated criteria and
the ranked rows with per-figure lineage and each option's
gap reading in the payload), and `planning_adoptions` (one
row per adoption act: the options id, the adopted fork —
null for the base view — the named planner, the act date
and a `supersedes` link as columns; the full act in the
payload). All three are insert-only; no head table
references them, and the current adoption for a comparison
is the head of its supersedes chain.

Brief tables (0010): `weekly_briefs` (one row per verified
brief: the week start and ending, the as-of, the assembler
and the brief pack version as columns; the season scope,
the sections with their figures and lineage, the verified
narrative and the `supersedes_refusal` link in the payload),
`brief_refusals` (one row per refused assembly: the week,
the as-of, the assembler and the pack version as columns;
the refusal's problems in the payload), `export_packs`
(one row per pack: kind, key, as-of, exporter and pack
version as columns; the tables, the provenance appendix
and the checksum manifest in the payload), and
`publication_acts` (one row per act: the artefact kind and
id, the family key, the named publisher, the publication
date and a `supersedes` link as columns; the bound
artefact fingerprint and the full act in the payload). All
four are insert-only; a brief's publication state is the
fold of the acts that name it, and a family's current
published artefact is its head act's target.

Data-plane tables (0011): `ingest_batches` (one row per
connector load: source, fact class, loader, load date and
the reconciled counts as columns; the inserted keys and
rows, the quarantine summary and the port refusals in the
payload), `quarantine_records` (one row per held row: the
batch, the named reason and the natural-key label as
columns; the detail and the raw row in the payload),
`fact_corrections` (one row per correction: the fact
class, the natural-key label, the `corrects` link, the
named corrector, a `supersedes` chain link and the content
fingerprint as columns; the full corrected row in the
payload), and `season_actuals` (the season-close actuals
fact class: district, crop year, season, product, actual
kind and tonnage with provenance at the row level, keyed
by its natural key). Batches, quarantine records and
corrections are insert-only artefacts; actuals are facts
under the same insert-only discipline as the 0001 tables,
in their own table so an actual can never be mistaken for
— or overwrite — an estimate.

Scoring tables (0012): `estimate_scores` (one row per
season-close score run: crop year, season, the scoring
date, the named scorer and the pack version as columns;
the per-cell errors, driver attributions, summary bias,
the graded actual batches and both unmatched sets in the
payload) and `score_refusals` (one row per refused run,
with its re-performance problems in the payload). Both
are insert-only; a score is a grading of stored
artefacts, never an edit of an estimate or an actual.

Market-surface tables (0013): `market_maps` and
`map_refusals` (one row per district map or its refusal:
crop year, season, strike date, the named builder and
the map pack version as columns; the cells, the monsoon
layer and the rendered page in the payload), `morning_boards`
and `board_refusals` (the same shape per role, with the
lanes and their rows in the payload), and the queue pair
`queue_items` (one row per gap item: the gap it answers,
its product and season, its band, its struck and due
dates as columns; the pack owner and gap figures in the
payload) with `queue_acts` (one row per act — assign,
start, link scenario, close — with the named actor, the
close's stated reason, the assign's owner and the
link's fork id as columns). Maps, boards and items are
insert-only artefacts; queue acts are insert-only and an
item's state exists nowhere as a column — it is the
fold of its acts, exactly like an alert's.

Rollup & readiness tables (0014): `regional_rollups`
and `rollup_refusals` (one row per seasonal rollup or
its refusal: crop year, season, strike date, the named
builder and the rollup pack version as columns; the
product blocks — member lines, region subtotals,
national totals and the by-reference gap lines — in
the payload), and `season_readiness` with
`readiness_refusals` (one row per region's plan: the
region as a column beside crop year, season, strike
date, striker and pack version; the four scored lines
with their figures in the payload). Both artefacts
are insert-only and supersede by link; territory
packs ride the existing `export_packs` table under
the territory pack kind.

Access & collaboration tables (0015): `access_entries`
(one row per guard decision: the principal, surface,
target and the artefact's region as columns; the
decision, remit and pin context in the payload),
`annotations` (the pinned target's kind and id as
columns; the pin hash and the note in the payload),
`followup_tasks` with `followup_acts` (one row per
act — assign, complete, close — with the actor, the
act's date, the assignee and the close's stated
reason as columns), and `review_queues` with
`review_refusals` (one row per queue or its refusal:
the strike date, striker and review pack version as
columns; the membership items with their driver
summaries, diffs and reviewed fingerprints in the
payload). All insert-only; a follow-up's state and a
note's superseded flag exist nowhere as columns —
they are folds, exactly like an alert's.

Notify tables (0016): `subscriptions` (one row per
subscription version: the subscriber, striker, strike
date and notify pack version as columns; the class,
product and region filters and the per-class severity
floors in the payload) and `digests` (one row per
generation: the subscription it freezes, its principal
and generation date as columns; the delivery rows,
per-class counts and escalation rows in the payload).
Deliveries and escalation states take no table — they
are derivations over the alert artefacts, the
subscription versions and the alert acts, re-performed
on every read and every verification, so there is no
stored delivery for a tamper to invent and no stored
escalation for a job to misreport.

Integrity tables (0017): `field_screenings` (one row
per landed field report: the verdict, landing date
and integrity pack version as columns; the matched
rules and the screened text's hash in the payload —
the text itself stays on the report artefact it
judges, and the hash is what binds verdict to text),
`field_screening_acts` (the release acts: actor,
reason and date as columns, content-addressed like
the other act tables) and `reporter_integrity_boards`
(one row per strike: its date and pack version as
columns; the per-reporter rows — window counts,
duplicate clusters, conflicts, review outcomes — in
the payload). Screening state is a fold of verdict
and acts; a board is a snapshot other artefacts
never read, so its contents are re-performed on
verification and nothing downstream can inherit a
signal as a fact.

Monitoring tables (0018): `model_runs` (one row per
completed model call through the service's drafting
port: sequence, purpose, profile, model, date and
monitoring pack version as columns; the token
counts, the pack-priced integer nano-USD cost and
the prompt/reply hashes in the payload — text is
never stored, and an unrated profile's cost is
null, never zero) and `monitoring_boards` (one row
per strike: its date and pack version as columns;
the cost totals and per-profile/per-purpose
breakdowns, the per-source freshness rows and
reliability folds, and the per-reporter reliability
rows in the payload). Freshness and reliability are
folds over batch reports, corrections, review acts
and screenings struck at the board's date; the
board is a snapshot other artefacts never read, and
its money is cross-checked against a direct sum
over the run ledger on verification.

Admin & integration tables (0019):
`pack_config_versions` and `master_data_versions`
(one row per struck version: family or register,
version label, effective date and editor as
columns; the complete values/content snapshot and
its derived diff in the payload) — the registers
behind the resolution discipline the engines now
share: **build resolves by the artefact's own
date, verify resolves by the artefact's named
version**. An engine striking a new artefact
takes the version in force at its date and names
it; a verifier re-performing an old one takes the
values its name carries, so a later version can
never move an artefact already struck, and a
label nothing holds is refused as unknown.
`webhook_subscriptions` (the payload holds the
signing secret; the store's row reader redacts it
on every surface, and one raw accessor exists for
dispatch and verification alone), `webhook_controls`
(disable/enable acts), `webhook_deliveries` (the
artefact read plus its HMAC, content-addressed
over subscription, trigger and payload),
`api_tokens` (the payload carries the token's
SHA-256 — the plaintext is never stored),
`api_token_acts` (revocations) and
`token_decisions` (one row per presented read,
allowed or refused), and `exchange_batches` /
`exchange_feeds` (the external rows and named
violations, or the derived feed rows and their
checksum). The exchange ports keep their own
source registry in the integration pack, beside
their contracts: the ingest registry — and the
monitoring board that folds it, asserting exactly
the six registered sources — is deliberately
untouched, and port loads reach the data plane
through `load_batch`'s entry override. Freshness
is the one family judged at two moments: a load
is judged under the window in force at its load
date (and the batch names that version), a board
under the window in force at its own date — both
resolve through the same register.

## Deployment

Multi-stage Dockerfile, non-root runtime user, port 8000. Compose
brings up the agent, Postgres 16 (pgvector image, ahead of the
retrieval rounds) and SeaweedFS as the S3-compatible object store
under the service name `minio`. Configuration is environment-only;
see `.env.example`.

The Postgres profile is a tested profile, not a hope: the full
test suite runs against Postgres 16 with per-test schema
isolation and must match the SQLite pass count exactly (parity
gap 0), and `scripts/prod_smoke.py` (`make smoke`, needs
`DATABASE_URL`) proves a fresh deployment end to end —
migrations on a clean schema, dataset load with zero provenance
gaps, health/readiness, and a connector batch whose replay
lands nothing twice.
