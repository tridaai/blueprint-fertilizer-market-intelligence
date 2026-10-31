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

## What Round 5 adds

- **The policy & subsidy event registry** — the recorded
  policy events become first-class `RegisteredPolicyEvent`
  artefacts under a versioned policy pack: a class from the
  pack vocabulary (subsidy rate change, price control, import
  duty change, export restriction, production incentive,
  environmental rule), an effective window in whole months
  derived from the event's date by the pack's stated rule
  (the window opens at the event's month and closes at the
  end of the season it lands in), product/district scope as
  recorded — an empty district list means market-wide, never
  silently narrowed — and provenance (source label + the date
  the event was recorded). The recorded kinds map onto the
  registry classes in exactly one place, the pack.
- **Stated effects as structured data** — each event carries
  its expected effect as data, never commentary: a direction
  (up / down / none — `none` is a positive statement, e.g. a
  price held), the driver it touches (demand rate, price, or
  supply), the mechanism in the words recorded at
  registration, and the pack's linkage naming the engine
  surface the effect would move — a subsidy revision names
  the demand pack's price-elasticity parameter; an import
  duty names the supply tracker's import-arrivals line at
  its landed-cost aspect. The linkage tells a reader where to
  look; no engine consumes an effect as an input, so a policy
  statement never moves a number by itself.
- **Impact notes, computed by query** — per current registry
  event, a `PolicyImpactNote` names exactly which stored
  artefacts fall inside the event's window and scope: the
  head demand estimates per district × season cell, the
  price series points (product and feedstock alike — the
  planted export restriction names phosphoric acid alongside
  DAP), and the head supply positions. The September 2025
  export restriction's note names 24 demand cells, six price
  points across two series, and the three DAP positions of
  its window. An event whose scope matches nothing stored —
  a rule announced for a season beyond the tracked data —
  earns a note with status `no_observed_scope` and empty
  lists: the absence is stated, not hidden.
- **Hypotheticals stay hypothetical** — a proposed policy is
  registered with the hypothetical flag: listed separately
  with its stated effect only, refused an impact note, and
  never marking the watch board. Registrations are
  insert-only, so the flag cannot be flipped on a stored
  artefact; when a proposal becomes real, the desk registers
  it again under the same event id and the new registration
  supersedes the proposal by link, which stays byte-identical.
- **Watch-board policy markers** — when a real event's window
  is open at the board's reference month (the latest tracked
  price month), the board surfaces it on the rows of the
  series it scopes to, as a typed policy marker with its own
  count — alongside the price alerts, never counted as one.
  At the current reference month only the rabi subsidy
  revision's window is open, marking the DAP and NPK rows.
- **Surfaces** — migration 0005 (registry events, impact
  notes), `POST /policy-registry/register-facts`,
  `POST /policy-registry/events`, registration reads with
  verify endpoints and impact-note compute/read/verify on
  the API, and `policy-register` / `policy-events` /
  `policy-event` / `policy` / `policy-impact` with their
  verify commands on the CLI. The eval gate grows the
  round-5 counters: registration mismatches, impact-scope
  mismatches, hypothetical leaks, supersession failures,
  board marker mismatches.

## What Round 6 adds

- **Competitor observations as first-class artefacts** — the
  720 tracked competitor points (three fictional tracked
  sellers × five regions × urea and DAP × 24 months) are
  promoted by an idempotent pass into stored
  `CompetitorObservation` artefacts: competitor, region with
  its district list, product, month, the season the month
  belongs to under the same unique-attribution rule the packs
  share (a month that opens a season belongs to it — November
  is rabi's), volume and price, and provenance on the face of
  the artefact. Provenance is constitutive: a point without
  its source label or its observation date is refused at the
  build and can never be stored bare.
- **Share computed by structure, never by raw tonnage** —
  tracked competitor volumes are whole-region figures while
  recorded consumption is district-level, and the two scales
  differ by an order of magnitude, so a share is built the
  way the market is actually observed: per month, the
  region's observed market is the tracked competitors'
  volumes plus Kaveri's home-market anchor (the region's R2
  demand total, spread over the season window by the supply
  pack's spread rule); each competitor's structure share of
  that observed market distributes the district's recorded
  market for the month, and Kaveri's line is the residual —
  the artefact states this basis on its face, including that
  any untracked seller sits inside the residual. Every share
  carries both denominator readings, labelled and never
  blended: share of the observed market and share of total
  demand (the district's R2 estimate total).
- **Staleness is a discipline, not a footnote** — the
  versioned share pack states the freshness window per
  source class (field tracking: 200 days; a source class
  with no stated window is never fresh). At any read date,
  months whose observations have aged past the window are
  badged `stale` on the artefact and excluded from the
  headline share, and the exclusion is named on the artefact
  itself — "headline excludes 9 stale observations" on the
  Ludhiana DAP kharif share read at 2026-03-31 — while the
  full-season reading rides alongside under its own basis
  label, `full_season_including_stale`. A cell whose every
  month is stale reads status `not_current` with no headline
  at all; a product with no tracked observations reads
  `no_observations`. A stale-exclusion read serves exactly
  the named excluded set.
- **Share movements with provenance** — per district ×
  product × season, a `ShareMovement` compares the two crop
  years' full-season readings (each struck at its own season
  close, so the comparison is like-for-like), names the
  biggest mover by share change, and carries that mover's
  observation ids in both years on the artefact.
- **Surfaces** — migration 0006 (competitor observations,
  market shares, share movements),
  `POST /competitor-observations/build`, observation
  list/read/verify, `POST /shares`, share read/verify/stale
  and share-movement compute/read/verify on the API, and
  `observations-build` / `observations` / `observation` /
  `share` / `verify-share` / `share-stale` /
  `share-movement` / `verify-share-movement` on the CLI.
  The eval gate grows the round-6 counters: share arithmetic
  mismatches, provenance refusals missing, stale-exclusion
  mismatches, not-current mismatches, movement
  re-performance failures, share tamper undetected.

## What Round 7 adds

- **Field reports become artefacts with a lifecycle** — the
  twelve planted field reports and every report from the
  mobile intake land as `FieldSignalReport` artefacts
  through one landing machinery. The intake is a structured,
  low-bandwidth form (reporter, district, product, signal
  type, quantity/price observed, photo reference as a
  string) validated at the port: a submission missing its
  reporter, district or observation date is refused with
  the missing fields named — attribution is never defaulted
  (Law 5).
- **Offline outbox, exactly-once sync** — a submission
  carries a client-generated id from the device's outbox.
  The same id with the same payload lands exactly once,
  however often a dropped connection re-sends it (a partial
  sync followed by a full re-send is the graded walk). The
  same id with a *different* payload is a conflict: both
  artefacts are kept, linked, and read as conflicted —
  never a silent overwrite.
- **The verification queue** — every report lands
  `unreviewed`. Named reviewers record insert-only acts
  (confirm / query / reject, each with a reason from the
  act's stated vocabulary in the versioned field pack);
  the review state is the fold of the acts and is stored
  nowhere. Rejection is terminal — a corrected observation
  arrives as a new report, not a revived one.
- **Weighting with the Law 5 cap, graded to the digit** —
  the field-signal assessment is the first consumer a field
  signal can move: per district × product × season it folds
  the cell's reports into an adjustment against the head R2
  demand estimate (which is read, never mutated). Each
  report contributes its kind's stated effect from the pack
  (demand surge +6.0, stock-out +5.0, …), decayed by a
  stated 30-day half-life and weighted by review state:
  confirmed at full decayed weight, **an unreviewed report
  clamped to the pack's unverified cap of 1.5 percentage
  points**, queried and rejected at zero, expired (past
  180 days) named at zero. The graded case: a fresh
  unreviewed surge whose uncapped weight is 5.345394%
  applies as exactly 1.5% against Ludhiana's DAP estimate —
  and as its full 5.345394% once a named reviewer confirms
  it. Every contribution is a line naming its reporter and
  review state; reports not yet observable at the read date
  are named in an excluded list, never silently dropped.
- **Surfaces** — migration 0007 (field signal reports,
  review acts, assessments), `POST /field-signals/sync`,
  planted promotion, report list/read/verify, the review
  queue, the review act endpoint, and assessment
  compute/read/verify on the API, with `field-sync` /
  `field-promote` / `field-reports` / `field-report` /
  `field-review` / `field-queue` / `field-assessment` /
  verify commands on the CLI, and the airplane-mode walk in
  the demo. The eval gate grows the round-7 counters:
  duplicate syncs landed, uncapped unverified influence,
  unattributed artefacts, silent overwrites, zero-influence
  violations, influence re-performance failures.

## What Round 8 adds

- **Ask in plain language** — a business question ("How is
  DAP looking in Ludhiana this kharif, what's our share, and
  what's the monsoon outlook for groundnut in Anantapur?")
  parses into a **dashboard spec**: a governed selection of
  panels from the dashboard pack's vocabulary, each panel
  bound to a stated artefact query (engine + scope + as-of)
  over the R2–R7 artefact families. The default profile is
  a deterministic grammar in code, stated as grammar;
  follow-up clauses inherit scope from the clauses before
  them, and when no clause names a season or crop year the
  pack's stated defaults apply and the defaulting is
  recorded in the parse provenance.
- **Gaps, never inventions** — a question part that maps to
  no artefact family becomes a named **gap panel** stating
  what data would be needed (an untracked district, a crop
  named where demand is estimated per product, a monsoon
  outlook the system holds only as a demand driver). A gap
  panel carries no figures — ever. Hosted profiles are held
  to the same law: the model port proposes panels as
  structured output, each proposal is validated against the
  governed schema, and a proposal that does not fit is
  refused — the refusal recorded on the spec and rendered
  as a gap panel, never silently dropped. An unparseable
  reply refuses the question outright.
- **The spec is an artefact** — insert-only and
  content-addressed, carrying the original question, the
  named asker (attribution is required, never defaulted),
  the panels with their artefact bindings resolved at ask
  time, and the parse provenance. Specs save under a name
  and re-run against fresh data.
- **Assembly renders only from artefacts** — a static
  dashboard page (single HTML file, the portfolio console
  conventions) whose every figure carries its lineage:
  artefact id, source as-of, and badges — the R6 staleness
  discipline (stale share figures are badged stale, never
  presented as current) and the R7 review states on
  field-signal figures. A figure whose source artefact
  superseded between spec and assembly renders from the
  **current head**, with the supersession noted on the
  panel; re-assembly computes a **diff** against the
  previous assembly — changed figures and superseded
  bindings, stated on the artefact and on the page.
- **Verification before serving** — before an assembly is
  stored, every figure is re-performed against its pinned
  artefact (the R2 figure-verifier discipline at dashboard
  scale): one mismatch refuses the **whole** dashboard with
  the panel and figure named — no partial render is stored.
  A stored assembly re-verifies the same way, plus a
  byte-exact re-render of its page.
- **Role defaults are data** — the dashboards a regional
  head, a national planner and leadership open by default
  are stated panel lists in the dashboard pack, built
  through the same spec machinery as an asked question —
  no per-role code branches. An unknown role is refused.
- **Surfaces** — migration 0008 (dashboard specs,
  assemblies), `POST /dashboards/ask`, spec list/read/
  verify, assemble, assembly read/verify/HTML, and the
  per-role default endpoint on the API, with `ask` /
  `dashboards` / `dashboard-spec` / `assemble` /
  `dashboard` / `verify-dashboard` / `role-dashboard`
  commands on the CLI, and the mixed-question walk in the
  demo. The eval gate grows the round-8 counters: figures
  without lineage, invented figures on gap panels,
  dashboards served with a mismatched figure, unrecorded
  parse refusals.

## What Round 9 adds

- **Scenario forks** — a scenario is a *pinned fork* of a
  head estimate or projection, moved by named levers from
  a **bounded, versioned lever catalogue** (the scenario
  pack): a monsoon deviation shift (±30 points), a price
  level shift (±50%) or elasticity override ([−1, 0]) on
  demand forks; an import arrival slip/advance by whole
  months (±6, future arrivals only — a fork re-times what
  has not landed, it never rewrites the basis stock) and a
  production shortfall (0–50% of plan) on supply forks.
  Out-of-bounds values, wrong-kind levers and unknown
  levers are refused with the bound or the catalogue
  named. A lever aimed at a driver the base carries as
  missing is recorded on the fork as not applied, with the
  reason — never silently absorbed.
- **The same engines, never a parallel calculator** — a
  fork runs the base artefact's own engine over a
  substituted fact view (the recorded facts are never
  written); an elasticity override rides the price line's
  own recorded inputs, base value alongside, so the fork
  re-performs under the R2 verifier discipline. The fork
  carries a **reconciliation**: per driver line (or per
  horizon month), base delta, fork delta and the
  lever-attributed difference — knock-on movements are
  shown and attributed to no lever — summing *exactly* to
  the fork-minus-base total. Graded: a two-month slip of
  the October DAP vessel reproduces the planted delay's
  import path exactly (0 / 0 / 55,000 t).
- **Plain-language intake** — scenario requests arrive as
  text through the model port, with R8's discipline: a
  deterministic grammar offline (defaults recorded, never
  silent), governed JSON proposals on hosted profiles.
  Parts that cannot be mapped become **named gaps** on the
  fork artefact — never dropped, never improvised. A
  policy event asked as a lever is a named gap by the
  pack's stated rule: no pack states a numeric
  transmission from a policy event into the engines, so
  none is invented.
- **Planning options** — a comparison artefact holding a
  base and its forks side by side: totals, the season gap
  reading struck by the R4 gap machinery over each
  option's own arrival view, and share-relevant figures
  where the engines provide them — every figure carrying
  lineage to its fork or base artefact. Options rank
  **only** by the pack's stated criteria (carried on each
  row, deterministically tie-broken), and the comparison
  re-performs exactly under an independent verifier. An
  option is **adopted** only by a named planner's act:
  insert-only, superseding by link, editing no artefact —
  it records which fork the plan follows.
- **Hypothetical discipline** — forks live only in the
  scenario tables. They never enter head estimates, the
  watch board, policy impact notes or dashboards of
  record: a dashboard renders a fork only when the
  question explicitly names the scenario, and then every
  figure is badged `scenario: <name>` — the dashboard
  verifier fails an unbadged scenario figure. Graded: the
  planted record's head figures are byte-identical before
  and after any fork work.
- **Surfaces** — migration 0009 (scenario forks, planning
  options, adoptions), `POST /scenarios` +
  `/scenarios/ask`, fork list/read/verify, `POST
  /planning-options`, options read/verify, adopt +
  current-adoption + adoption verify on the API, with
  `scenario` / `scenario-ask` / `scenarios` /
  `verify-scenario` / `planning-options` / `options` /
  `verify-options` / `adopt` / `adoption` /
  `verify-adoption` commands on the CLI, a `scenario`
  panel kind in the dashboard pack, and the two-fork
  comparison walk in the demo. The eval gate grows the
  round-9 counters: fork identity/delta mismatch, base
  mutated by fork, hypothetical leak, unbadged scenario
  figures served, adoption without a named act.

## What Round 10 adds

- **The weekly brief** — one artefact per stated week,
  assembled from the system's artefacts only: the **demand
  outlook position** for the brief's season scope (the
  season containing the week's month under the brief
  pack's attribution; months in neither window belong to
  the latest closed season, stated as such), the
  **price-watch alerts fired** in the week, the **supply
  gaps open or changed**, the **policy events** effective
  in the week's month, **competitor & share movement**
  across the district × tracked-product grid with R6
  staleness badges intact, and the **adopted planning
  state** where R9 adoptions are in force. Every figure
  carries its lineage — artefact id and that artefact's
  as-of — and the drafted summary is figure-checked
  against the brief's own figure set, exactly as the R2
  outlook narrative is checked against its estimates.
- **Wholesale refusal** — before a brief is stored, an
  independent verifier re-performs every figure from its
  pinned artefact and re-verifies each pinned artefact
  under its own family's verifier. One wrong figure
  refuses the brief wholesale: no partial brief, no
  corrected-in-place brief. The refusal is itself an
  artefact recording the problems; a later clean assembly
  for the same week supersedes it by link. The demo's
  showpiece is a draft corrupted at the intermediate step
  — refused, recorded, then superseded.
- **Report packs** — exportable packs per product and per
  region (CSV tables plus a provenance appendix and a
  checksum manifest), generated from artefacts at a stated
  as-of. The manifest check names a tampered export file —
  flip a byte in an exported figure and that file fails by
  name — and the pack's figures additionally re-perform
  against a fresh read of the store, so an export never
  drifts from the artefacts it quotes.
- **The publication gate & decision log** — nothing
  renders as published without a **named publication act**:
  publisher, timestamp, and the exact artefact version
  bound by its fingerprint. Publication is insert-only; a
  new published version supersedes by link, never edits.
  The families are the week's briefs and the season's
  outlooks; the target must verify under its family's
  verifier at publication time, so an artefact the
  verifier rejects cannot be published at all. The
  **decision log** — who published what, when, superseding
  which version — re-derives gaplessly from the acts
  alone, and its verifier fails a forked, cyclic or
  orphaned chain or an act whose target no longer matches
  its bound hash. Drafts and published artefacts are
  distinct on every surface: the API carries the
  publication state on the brief, and the rendered page
  badges "Published" only with an act behind it — an
  unpublished brief carries the draft mark, never the
  published one.

## What Round 11 adds

- **The connector framework + source registry** — facts now
  enter from real feeds through one port, under the
  versioned ingest pack. The registry states every
  admissible source — the international price feed, plant
  production returns, port import manifests, gazette
  policy notices, dealer competitor returns, state
  dispatch returns — with the fact class it may deliver,
  the provenance string its rows must carry, its cadence,
  its owner and its freshness rule. A batch naming an
  unregistered source is refused before a single row is
  read. **A row without `source` or `as_of` is refused at
  the port** — recorded on the batch report, never stored:
  provenance is mandatory in the models and NOT NULL in
  the schema, so the refusal is structural. Every batch
  report reconciles exactly (received = inserted +
  duplicates + quarantined + refused) and re-performs
  against the store under its verifier.
- **Idempotent replay** — replaying the same batch returns
  the stored report and lands nothing; the same rows in a
  later batch count as duplicates, row by row. A different
  row under a taken natural key is never an overwrite: it
  quarantines as a conflict.
- **Quarantine & corrections** — a provenanced row that is
  malformed or contradictory (a district that does not
  exist, a negative tonnage, an untracked product, a
  stale or future `as_of`, another feed's provenance) is
  held in quarantine with its named reason and raw
  payload; it never reaches a fact table, so no engine can
  consume it. **Corrections are new facts**: a correction
  carries the full corrected row and names what it
  corrects — a stored fact, a quarantined record, or the
  head of the key's correction chain. The stored fact is
  never rewritten; the effective row is the fold of the
  chain, and the chain verifier re-performs the fold,
  recomputes every link's fingerprint, and catches
  tampering.
- **Season-close actuals** — realized consumption and
  dispatch import through the same connector path as a
  **distinct fact class** (`season_actuals`): actuals
  never overwrite an estimate and never land in another
  class's table. The actuals report joins them to struck
  estimates by natural key and **reports unmatched rows by
  name — it never drops them** — so a later round can
  score estimates against what actually happened.
- **The Postgres profile, at full parity** — the whole
  test suite now runs against Postgres 16 as well as the
  SQLite default (each test in its own schema, so the
  pass counts compare directly): **the parity gap is 0**.
  `make smoke` runs the production smoke — migrations on a
  fresh schema, dataset load, health/readiness, and a
  connector batch with an idempotent replay — against
  `DATABASE_URL`.

## What Round 12 adds

- **Season-close estimate scoring** — once a season has
  closed, its head demand estimates are graded against
  the actuals under the versioned scoring pack
  (`scoring_rules`, 2026.10.1). Each cell — district ×
  product × season, per actual kind — carries the signed
  error in tonnes, the percentage error against the
  actual, and the estimate's status as struck (a partial
  estimate is graded as a partial). Nothing is
  re-estimated: scores read the stored estimate artefact
  and the stored actual row, and the run names the
  connector batches that delivered the actuals it grades.
- **Driver-attribution error** — the pack's stated method
  attributes the total signed error across the estimate's
  own contribution lines in proportion to each line's
  signed share of the estimate total, so the attributed
  errors sum back to the total error and the most-wrong
  line can be named: this is how the desk learns *which
  part* of the engine to trust season over season. The
  attribution matches a hand-computed fixture exactly,
  in tests and in the eval gate. A zero-total estimate is
  recorded `not_attributable` rather than divided by
  zero; a zero actual carries no percentage error and is
  named `zero_actual`.
- **Re-performance and refusal** — every score run is an
  insert-only artefact, re-performed by a second route
  that re-derives the line deltas from the recorded
  value-after chain instead of their stated deltas. One
  mismatch refuses the run wholesale (a refusal artefact
  is recorded; no score is stored), and a tampered stored
  run is caught by the same verifier. Unmatched cells are
  named in **both** directions — actuals with no struck
  estimate (the R11 report's discipline) and head
  estimates with no actual on record.
- **Eval depth** — the gate now grades the full
  firing/recovery paths of the planted instruments, not
  just their prints: the DAP spike alert's lifecycle is
  folded from its acts alone, invalid transitions are
  refused and record nothing, and a second alert walks
  open → acknowledged → closed under grading; the
  planted delay's supply-gap path is re-performed across
  all six programme months (short while the vessel is
  slipped, comfortable from the month it lands, cover
  exact) with the stored gap chain walked as one
  unbroken line.

## What Round 13 adds

- **The district demand/gap map** (roadmap F21-GS1) —
  a schematic tile grid of the twelve tracked districts,
  one artefact per season, composed from artefact heads
  under the versioned map pack (`map_rules`, 2026.10.1)
  with product switchers across all six products. A
  cell's demand outlook reads the district's own head
  estimate against its prior-year counterpart — estimate
  against estimate, both named on the cell. Its gap band
  is the more severe of two stated readings: the
  product's season gap band (one reading for the whole
  tracked market) and the district's own field-signal
  pressure from its R7 assessment, with the composition
  stated on the cell. A partial estimate renders hatched
  and badged with its missing drivers — never a
  confident colour; a district with no estimate renders
  as no-data, a different claim from zero; a product
  with no supply side (the agrochemicals) contributes no
  product reading and the cell says which readings it
  does carry. Every cell is re-performed against the
  artefacts it binds before a map is stored — one
  mismatched cell refuses the whole map, with the
  refusal recorded — and a stored map stays verifiable
  archivally after the record moves on.
- **Monsoon & field-signal layers** (F21-GS2) —
  switchable layers over the same tiles. The monsoon
  layer re-performs from the monsoon facts, deviation
  and band per district. The signal layer lists a
  cell's field reports in two classes that are never
  merged: confirmed (a named reviewer's confirm is the
  latest word) rendered solid, and pending — unreviewed
  or queried — in its own labelled class, with rejected
  reports counted on the cell and shown in neither
  class. The layer is read as of the map's date: a
  report that landed later is not on an earlier map.
- **The market morning board** (F21-OW1) — one opening
  view per role (regional head, national planner,
  leadership), its lanes stated in the board pack
  (`board_rules`, 2026.10.1): open alerts, districts
  trending short, stale figures, pending brief
  approvals. Rows re-derive from artefacts — an alert
  is in the open lane exactly while its fold of acts at
  the board's date says open; a short-district row is a
  map cell; a stale row names the share artefact whose
  own readings carry stale observations; a pending
  brief is one no publication act names. Ranking is the
  owning packs' — alert band and rule order, gap
  severity, stale weight, brief severity (the worst
  thing a brief carries) — never recency. A candidate
  board is re-derived lane for lane before storage; one
  wrong row refuses the whole board.
- **The shortage & gap action queue** (F21-OW2) —
  every tight or short gap head becomes a work item,
  struck with the queue pack's named default owner for
  its product (`queue_rules`, 2026.10.1) and a due date
  from its band's stated term (seven days short,
  fourteen tight; overdue is derived at the read date,
  never a stored flag). Membership is derived, never
  curated: exactly one item per non-comfortable gap
  head, following the head when a successor gap clears
  it. Item state, current owner and the mitigation
  scenario slot are folds of named, insert-only acts —
  assign, start, link scenario (a stored R9 fork, by
  reference only), close — and a close is valid only
  with a reason from the pack's stated vocabulary
  (supply secured, scenario adopted, demand revised,
  gap cleared, risk accepted). `make mapcheck`
  re-performs every figure the three surfaces show, on
  a throwaway store, and their pages are static and
  read-only: no form, no POST, no control verb.

## What Round 14 adds

- **Regional rollups** (roadmap F21-DR3) — one
  insert-only artefact per season under the versioned
  rollup pack (`rollup_rules`, 2026.10.1) that
  decomposes the head outlook's own total: for every
  product, the member estimates the outlook names are
  grouped district → region → national, and every
  figure is a sum of member artefacts — nothing is
  re-estimated and nothing is re-derived from raw
  facts. A district whose member estimate is partial
  is named on the rollup's face and makes its region,
  its product and the rollup itself partial; a district
  with no member artefact is named as missing and
  contributes nothing — it is never silently zero, so
  a region can read 0 t only with every one of its
  districts named missing beside the figure. The
  product's gap position rides by reference: the head
  gap's own figures under its own id, with the demand
  basis stated — whether the gap was struck from this
  rollup's outlook, in which case the verifier
  cross-checks its demand against the rollup's
  national total, or from an earlier one. When a
  member is superseded the old rollup stays and a new
  one supersedes it by link; the verifier re-performs
  the identity by a second route (the store's estimate
  rows grouped directly) and refuses the rollup
  wholesale on one mismatched tonne, count or name.
- **Territory packs** (F21-DR3) — a third export-pack
  kind on the R10 machinery: one region's pack whose
  three tables (region and national rollup rows, the
  region's district member lines, the gap positions)
  are rendered from the rollup artefact for the season
  in scope at the pack's date, so every figure in the
  pack is exactly the rollup's figure. The CSVs carry
  the usual provenance appendix (every row's source
  artefact named) and SHA-256 manifest — a flipped
  byte in a written file is named by the pack
  directory verifier.
- **The season readiness plan** (roadmap F21-PO3) —
  a pre-season checklist artefact per region under
  the versioned readiness pack (`readiness_rules`,
  2026.10.1), its four lines scored from artefacts,
  never self-declared: the demand outlook published
  (the head outlook counts only behind its R10
  publication act, folded at the plan's date), supply
  cover by product (every product with a supply side
  has a head gap struck and none reads short — the
  short product is named with its figures), open risks
  (alerts standing open at the date by their act fold,
  plus short gaps whose R13 queue item still has no
  assign act — the struck default owner is named),
  and field coverage (every district in the region
  carries a field report for the season whose review
  state at the date is confirmed). The plan names
  exactly which lines block it; a region cannot read
  ready over an unpublished outlook, an unowned short
  gap, or any other incomplete line. Lines re-derive
  on read by a second route, and a stored plan
  verifies against the record it was struck from —
  acts recorded on a later date move the next plan,
  never rewrite this one.

## What Round 15 adds

- **Regional role scopes** (roadmap F21-AS1) —
  who may read what is a versioned pack
  (`access_rules`, 2026.10.1): named principals hold
  a strategy remit (everything), a product remit, a
  regional remit (one region), or a viewer remit
  (published material only) — and any name the pack
  does not register reads as a viewer, so an
  unregistered name is refused rather than waved
  through. Through the scoped surfaces a regional
  reader enumerates only their own region's
  districts, and a competitor observation outside
  the reader's remit reads exactly as if it did not
  exist — absence, never a refusal that proves the
  record is there. Competitor reads are judged per
  artefact, region and product remits alike.
- **The export audit log** (F21-AS1) — every
  guard decision is itself an insert-only,
  content-addressed artefact: the principal, the
  surface, the target, the artefact's own region
  and product context, the remit the pack judged,
  the decision and the pack version. Exports are
  always allowed — any named person may export —
  and always logged, so what left the building is
  a fact on record; the graded invariant is that
  the log's export entries reconcile one-to-one
  with the export packs in the store, and an
  independent verifier re-decides every logged
  entry from the pack as it stands, so a doctored
  decision is named.
- **Annotations and assigned follow-ups**
  (roadmap F21-CA2) — a note can be pinned to a
  demand estimate, a supply gap or a price alert:
  an insert-only artefact whose pin is a hash of
  the target exactly as stored, so a view of the
  note says plainly whether the target still
  matches its pin and whether the family has since
  moved on — the flag is folded from the family's
  own supersession links, never stored. Follow-ups
  are tasks struck once against a target, with
  their state a fold of attributed acts (assign,
  complete, close with a stated reason): an act
  against a finished task is refused outright, so
  a closed item cannot be quietly revived, and the
  verifier re-performs every pin and fold.
- **The publication review queue** (roadmap
  F21-OW4) — one insert-only artefact per review
  date listing everything awaiting publication with
  exactly what a reviewer needs to say yes: for an
  outlook, its totals and the cell-by-cell diff
  against the family's published head (changed,
  added and removed cells with their tonnes), for
  a brief, its figure diff by section and label —
  or the plain basis "first publication" when
  nothing has been published yet. Each item binds
  the artefact's fingerprint as reviewed, so the
  publication act that follows strikes with that
  same fingerprint — published equals reviewed,
  byte for byte. A pending artefact that fails its
  own verifier refuses the whole queue and the
  refusal is itself recorded; membership and diffs
  re-derive by a second route from the raw acts.
  The R10 publication gate is re-graded by this
  queue (roadmap F21-CA1): briefs and outlooks
  alike enter it only while their folded state is
  draft, and leave it only through the act.

## What Round 16 adds

- **Alert subscriptions** (roadmap F21-AL1) —
  a named reader of the R15 register holds a
  standing instruction as an insert-only artefact:
  notice classes (price alerts, supply-gap heads,
  policy registry heads), product and region
  filters, and a severity floor per class in that
  class's own labels. A change is a new version
  superseding the old by link, never an edit. The
  strike itself is judged by the access pack —
  only the subscriber or the strategy desk may
  strike, the reach must sit inside the
  subscriber's remit, viewers and unregistered
  names hold no subscriptions — and the decision,
  allowed or refused, is an access-log entry like
  every other guarded act since Round 15.
- **Deliveries, derived never authored** — at any
  read date the deliveries are recomputed from the
  notices as they stand, the subscription version
  in force on the day each notice was struck, and
  the subscriber's remit: the filter states what a
  reader wants, the remit states what they may
  receive, and a delivery needs both (a feedstock
  notice sits in no product remit; a national
  notice cannot be placed in a regional one). A
  delivery is evidence an alert reached a
  subscriber — it changes no alert's state — and a
  notice nobody reaches is counted per class as
  undelivered-by-design. Policy notices are their
  own class throughout: never counted as price
  alerts, in delivery sets, undelivered counts and
  digests alike. Alert reads themselves now pass
  the guard too, with Round 15's existence hiding.
- **Escalation as a clock in code** — an
  alert-band price alert still open three days
  past its strike climbs to the product owner the
  register names for its item (the strategy
  principal for an item nobody owns); at seven
  days the strategy desk joins the ladder. The
  state is derived from the alert's acts folded at
  the read date on every read — there is no
  background job to trust — and an acknowledgement
  stops the clock from its own date. An escalation
  names follow-up tasks pinned to the alert by
  reference; it never writes one, and it composes
  with the Round 13 queue the same way: a gap
  notice carries its queue item's id, by reference
  only.
- **Scheduled digests** (roadmap F21-AL2) — a
  digest artefact freezes one subscription
  version's delivery set, its per-class counts and
  its escalations at a generation date, so what a
  reader was told can be re-performed later
  exactly; regenerating at a later date is a new
  artefact superseding the old by link. The same
  content renders as JSON through the API and CLI
  and as plain low-bandwidth text lines. The whole
  layer — subscriptions, deliveries, escalations,
  digests — is re-performed by an independent
  verifier, and a subscription written straight
  into the store with no judging entry is named
  as unreconciled.

## What Round 17 adds

- **Field-text screening** (roadmap F21-AS2) —
  field notes are the one place unvetted prose
  enters this system, so every landed report is
  screened at the door against a versioned
  integrity pack: rules addressed to text that
  speaks to a model or a system (instruction
  overrides, role markers, directive headers,
  persona assignments, output control), run over
  the note as written and over any base64 span it
  carries, decoded — an encoded instruction is
  the same instruction. The verdict is its own
  insert-only artefact bound to the report and to
  a hash of the exact text screened. A held note
  is treated as absent everywhere it could
  travel: redacted on the report's views, and a
  named omission in the structuring context a
  model would be handed — while attribution,
  figures and weighting proceed untouched, and
  clean market prose passes byte-identically.
  Screening never edits the report it judges.
- **Release as a second pair of eyes** — held
  text is freed only by a named reviewer's act
  with a reason from the pack's vocabulary; the
  reporter can never release their own text, a
  release against unheld text is refused, and
  the state (clean / held / released) is the
  fold, stored nowhere. The one read that serves
  a note raw is the access-guarded screening
  surface: judged on the report's district and
  product under the R15 pack, existence-hidden
  outside the reader's remit, closed to viewers,
  and logged like every guarded read since R15.
- **Reporter integrity, computed and advisory** —
  an integrity board artefact strikes, per
  reporter, the facts a reviewer needs: landing
  volume against the pack's stated spike bar,
  duplicate-content clusters detected exactly
  (the same observation under different
  submission ids — a re-sent submission is the
  sync layer's duplicate, never a cluster),
  conflict involvement, and review outcomes
  folded from the acts. A signal is a prompt for
  a human to look, never an automatic
  consequence: the board writes nothing back,
  and a field assessment re-performs identically
  whether or not a board exists — that
  independence is graded, not asserted. The
  whole layer re-performs through an independent
  verifier, and `make integritycheck` plants
  direct, role-marked and encoded injections and
  grades the discipline end to end.

## What Round 18 adds

- **A run ledger for every model call**
  (roadmap F21-AM2) — the service's drafting
  steps (outlook narratives, the weekly brief,
  dashboard and scenario parses) record each
  completed call as an insert-only run: the
  purpose from a versioned monitoring pack, the
  profile and model, the token counts the port
  reports, and the price the pack puts on them —
  integer nano-USD against stated reference
  rates, never provider-billed figures. The
  ledger stores hashes of prompt and reply,
  never their text; a call that fails records
  nothing, and a call on a profile the pack
  carries no rate for stands as unrated, never
  zero-priced. Sequence numbers are gapless, so
  a missing run is a visible hole, not a quiet
  absence.
- **Freshness, judged per source** — a
  monitoring board artefact strikes, for every
  source in the ingest registry, the newest fact
  its landed batches actually inserted and that
  fact's age against the registry's own window:
  fresh, stale, or never loaded. A source that
  has never landed a batch is named in that
  state on every board — never absent from the
  list, never read as current.
- **Reliability, folded not asserted** — the
  same board folds per-source reliability from
  the batch reports and the corrections ledger
  (received, inserted, duplicates, quarantined,
  refused, and the quarantine rate), and
  per-reporter reliability from the review acts
  and the screening record. A confirmation rate
  is stated only behind decided cases; a
  reporter with none reads as unmeasured, with
  the reason named — never a flattering zero.
  The board's money reconciles with the ledger
  to the nano, the board reads through the R15
  access guard like every guarded surface, and
  an independent verifier re-performs the whole
  layer — a tampered run or board is named, not
  averaged away. `make monitoringcheck` stands
  the discipline up end to end.

## What Round 19 adds

- **Signed webhook deliveries** (roadmap
  F21-IA1) — an integration subscribes to spike
  alerts, gap-band changes and brief
  publications. Dispatch strikes one insert-only
  delivery per trigger: the payload is the
  artefact read the system's own surfaces serve,
  signed HMAC-SHA256 under the subscription's
  secret. The secret is held to sign and to
  verify — every read of a subscription states
  that a secret is set, never its value. A
  delivery covers a trigger on or after the
  subscription's registration and only while it
  stands active at the trigger's own date, so a
  disable act silences what follows it and
  rewrites nothing already earned; dispatch is
  idempotent, and the verifier re-performs every
  payload and signature and the completeness of
  the set.
- **Scoped API tokens** (roadmap F21-IA1) — a
  token is issued to a named integration with
  stated read scopes (alerts, gaps, briefs); the
  plaintext exists only in the issuer's hands at
  issue, and the store keeps its SHA-256. Every
  presented read is judged — known token, not
  revoked, kind in scope — and the judgement
  lands as a decision entry either way, so a
  refused read is as much on the record as an
  allowed one. Revocation is an act, and a
  revoked token refuses everything from its
  date. The verifier re-judges every entry from
  the token artefact and its acts.
- **Exchange ports with stated contracts**
  (roadmap F21-IA2) — the inbound ports speak an
  external shape (material codes, kilotonnes,
  period strings) and grade each batch against
  the port's contract before anything is
  translated: one violation — an unknown
  material, a negative quantity, a malformed
  period, a missing, extra or mis-sourced field,
  an empty batch — quarantines the batch whole,
  with the violations named on the batch
  artefact and nothing landed anywhere. A
  conforming batch is translated at the border
  and lands through the production data plane
  under the port's own registered feed, where
  row-level fact discipline applies as it does
  to every feed. Outbound feeds are artefacts
  whose rows derive from artefacts alone under
  a recomputed checksum. Shapes only: no vendor
  is named, and nothing here claims to be one.
- **Administered configuration** (roadmap
  F21-AD2) — the threshold packs that used to
  change only by code release (alert bands and
  the spike/sustained rules, supply-gap bands,
  ingest freshness windows, the field-signal
  cap) are now registers of effective-dated
  versions: a complete validated snapshot struck
  by a named editor, never backdated, effective
  dates strictly rising, its diff against the
  version in force before it derived and
  recorded, a change that changes nothing
  refused. Engines resolve the version in force
  at the artefact's own date and name it on the
  artefact; verifiers resolve by the name the
  artefact carries — so a threshold change is
  never retroactive, and an old alert, gap,
  batch, board or assessment re-performs under
  exactly the values it was struck with. The
  movement-shaping windows stay in code, stated
  on the pack's face: they shape artefacts of
  their own, not thresholds.
- **Master data as versions** (roadmap
  F21-AD1) — application rates, the season
  calendar, districts, products and crops are
  registers under the same versioning
  discipline, seeded from the baseline the code
  and the store hold today. The demand engine
  computes under the rate table in force at the
  estimate's date and names it on the estimate;
  the estimate's verifier still re-performs from
  the rates recorded on its own base line, so a
  later table never moves an estimate already
  struck. The remaining registers are versioned
  records of reference, graded against the
  state they describe — stated plainly, they
  are not yet engine-wired. `make
  integrationcheck` stands the whole layer up
  end to end.

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
make mapcheck       # re-perform every figure the map/board/queue show
make integritycheck # plant injections; grade screening + integrity end to end
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
- **Built and gated in R5:** the policy & subsidy event
  registry — the recorded events promoted to artefacts under
  the versioned policy pack (class vocabulary, stated effects
  with engine linkages, windows derived by the pack's rule,
  scope as recorded), impact notes computed by scope query
  over the demand/price/supply artefacts with the
  `no_observed_scope` statement, hypothetical proposals held
  apart (no note, no board marker, real only by supersession),
  and policy markers on the watch board — migration 0005,
  API + CLI surfaces, demo walk, tests and eval counters.
- **Built and gated in R6:** competitor & market-share
  intelligence — the tracked points promoted to
  provenance-carrying observation artefacts (a point without
  source or date refused), market shares computed by region
  structure over the district's recorded market with Kaveri
  as the named residual and both denominator readings
  labelled, the freshness discipline (stale months badged,
  excluded from the headline, the exclusion named; all-stale
  reads `not_current`; unobserved reads `no_observations`),
  and share movements between the crop years with the
  biggest mover's provenance carried — migration 0006,
  API + CLI surfaces, demo walk, tests and eval counters.
- **Built and gated in R7:** field signals & mobile intake —
  structured intake validated at the port (missing
  attribution fields named, never defaulted), exactly-once
  outbox sync with conflicts kept both and linked, the
  planted reports promoted through the same landing
  machinery, the verification queue (insert-only reviewer
  acts, state derived, rejection terminal), and the
  weighting assessment: kind effect × freshness decay ×
  review state against the head R2 estimate, an unreviewed
  report clamped to the pack's 1.5-point unverified cap
  (graded exact: 5.345394% uncapped applies as 1.5%),
  queried/rejected/expired at zero and named — migration
  0007, API + CLI surfaces, demo walk, tests and eval
  counters.
- **Built and gated in R8:** the plain-language dashboard
  assembler — questions parsed into governed dashboard
  specs under the versioned dashboard pack (deterministic
  grammar offline; hosted proposals validated against the
  schema, refusals recorded and rendered as gaps),
  unanswerable parts carried as gap panels naming the data
  they would need and carrying no figures, specs as
  insert-only attributed artefacts, assembly rendered only
  from artefacts with per-figure lineage (artefact id,
  as-of, staleness and review-state badges), supersession
  noted with figures from the current head, re-assembly
  diffs computed and stated, whole-dashboard verification
  before serving (one mismatched figure refuses the whole
  dashboard), and per-role default dashboards stated as
  pack data — migration 0008, API + CLI surfaces, demo
  walk, tests and eval counters.
- **Built and gated in R9:** scenario forks & planning
  options — the versioned scenario pack (bounded lever
  catalogue, stated ranking criteria, the
  no-numeric-transmission rule for policy levers), forks
  computed by the R2/R4 engines over a substituted fact
  view with exact per-line reconciliation, plain-language
  scenario intake with named gaps, planning-options
  comparisons re-performed under an independent verifier,
  adoption as a named planner's insert-only act, and the
  hypothetical discipline (forks in their own tables only;
  dashboards render a fork only when named, badged on
  every figure) — migration 0009, API + CLI surfaces, a
  scenario panel kind in the dashboard pack, demo walk,
  tests and eval counters.
- **Built and gated in R10:** the weekly brief, report
  packs & the publication gate — a brief assembled for a
  stated week from artefacts only (outlook position,
  alerts, gaps, policy events, share movement with staleness
  badges, adopted planning state), every figure carrying
  artefact lineage; an independent verifier that re-performs
  every figure and refuses a wrong brief wholesale, the
  refusal recorded as an artefact; export packs per product
  and region with a provenance appendix and a checksum
  manifest that names a tampered file; and publication as
  insert-only named acts binding the exact artefact version
  by hash, with the decision log re-derived from the acts
  alone and drafts distinguished from published artefacts
  on every surface — migration 0010, API + CLI surfaces,
  demo walk, tests and eval counters.
- **The dataset is generated for this blueprint** — built in-repo by
  the seeded generator described above, because no openly licensed
  Indian district-level fertilizer dataset carries the provenance
  this design needs. Kaveri Agro Inputs is fictional; any
  resemblance of figures to a real company's is coincidence of
  construction, not data.
- **Built and gated in R11:** the production data plane —
  the connector framework and source registry (six feeds
  registered with cadence, owner and freshness rule;
  provenance refused at the port, schema-level), idempotent
  replay at batch and row level, quarantine with exact
  named reasons (engines never consume a held row),
  corrections as linked new facts whose chains re-perform,
  season-close actuals as a distinct fact class with
  unmatched rows reported by name, and the Postgres
  profile at full test parity (gap 0) with the production
  smoke — migration 0011, API + CLI surfaces, demo walk,
  tests and eval counters.
- **Built and gated in R12:** season-close estimate
  scoring — per-cell error and run bias from the stored
  artefacts, driver-attribution error under the versioned
  scoring pack with the most-wrong line named and a
  hand-computed fixture matched exactly, second-route
  re-performance with wholesale refusal, unmatched cells
  named in both directions — plus the spike-lifecycle and
  delay-gap-path eval depth — migration 0012, API + CLI
  surfaces, demo walk, tests and eval counters.
- **Built and gated in R13:** the district demand/gap
  map with monsoon and field-signal layers (cells
  composed from artefact heads under the map pack,
  partial hatched and no-data dashed, confirmed and
  pending signals never merged, archival by-id
  verification with wholesale refusal), the per-role
  morning board (lanes re-derived from artefacts,
  ranked by the owning packs, never by recency), and
  the gap action queue (membership exactly the
  non-comfortable gap heads, pack-named owners, due
  states derived, closes speaking a stated vocabulary,
  scenario links by reference) — migration 0013, API +
  CLI surfaces, a map/board checker script, demo walk,
  tests and five new eval counters.
- **Built and gated in R14:** regional rollups (the
  outlook's total decomposed district → region →
  national as sums of its named member estimates,
  partial and missing districts named on the face, gap
  positions carried by reference with their demand
  basis stated), territory packs on the R10 export
  machinery (every figure exactly the rollup's, the
  manifest naming a tampered file), and the season
  readiness plan (four lines scored from artefacts —
  publication acts, gap heads, alert and queue act
  folds, confirmed field reports — blocking lines
  named, re-derived on read) — migration 0014, API +
  CLI surfaces, demo walk, tests and four new eval
  counters.
- **Not built yet:** the LangGraph agent-orchestration
  layer named in the stack (ingest → estimate →
  assemble → brief → publish gate); the artefact
  engines it would orchestrate are the rounds above.
- **No live model has been called.** Hosted profiles are wired as
  adapters and refuse loudly until configured; the offline profile
  is what tests and evals run.
- **R19's outward surfaces stop at the artefact.** A webhook
  delivery is a struck, signed record of what would be sent —
  no HTTP call is made to any endpoint; the transport belongs
  to the integrator. The exchange ports are stated shapes with
  local doubles behind them: no live ERP or CRM is connected,
  and token reads guard this system's own read surface, not a
  network perimeter. Of the master-data registers, only
  application rates are engine-wired; the season calendar,
  districts, products and crops are versioned records of
  reference, graded against the state they describe. A
  freshness-window change governs new loads — a batch already
  judged keeps its judgement, and the correction machinery
  remains the route for rows it held.
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
  policy_rules.py    the versioned policy pack (classes, linkages, windows)
  policy.py          registry events, impact notes and their verifiers
  share_rules.py     the versioned share pack (freshness, structure, bases)
  share.py           observations, market shares, movements, verifiers
  field_rules.py     the versioned field pack (intake, kinds, decay, cap, acts)
  field.py           signal landing, review fold, weighting assessments
  dashboard_rules.py the versioned dashboard pack (panel vocabulary, defaults, role defaults)
  dashboard.py       question parsing, dashboard specs, assembly, verification, rendering
  scenario_rules.py  the versioned scenario pack (lever catalogue, ranking criteria)
  scenario.py        scenario forks, planning options, adoptions, verifiers
  brief_rules.py     the versioned brief pack (week + scope rules, sections, pack kinds, badges)
  brief.py           weekly brief, figure verifier, report packs, publication acts + decision log
  access_rules.py    the versioned access pack (principal register, remit kinds, decisions)
  access.py          the access guard, scoped reads and the export audit log + verifier
  notes_rules.py     the versioned notes pack (pin kinds, follow-up acts, close reasons)
  notes.py           annotations with pins, follow-up task folds and their verifier
  review_rules.py    the versioned review pack (pending kinds, queue sections)
  review.py          the publication review queue: membership, cell/figure diffs, verifier
  ingest_rules.py    the versioned ingest pack (source registry, class contracts, quarantine reasons)
  ingest.py          connector loads, batch verifier, corrections + chains, actuals report
  notify_rules.py    the versioned notify pack (notice classes, severity floors, escalation windows)
  notify.py          subscriptions, derived deliveries + escalations, digests and their verifier
  integrity_rules.py the versioned integrity pack (screening rules, release vocabulary, spike bar)
  integrity.py       field-text screening, release fold, reporter-integrity boards and their verifier
  monitoring_rules.py the versioned monitoring pack (run pricing, freshness states)
  monitoring.py      the run ledger, monitoring boards and their verifier
  configuration_rules.py the versioned configuration pack (families, value validation, diffs)
  configuration.py   pack configuration versions: resolution by date, strikes, verifier
  master_rules.py    the versioned master-data pack (registers, baseline content, validation)
  master.py          master-data versions, the demand engine's rate resolution, verifier
  integration_rules.py the versioned integration pack (webhook events, token scopes, exchange contracts)
  integration.py     webhook subscriptions/deliveries, scoped tokens, exchange ports and their verifiers
  migrations.py      numbered migration runner
  store.py           the insert-only store port (SQLite / Postgres)
  modelport.py       offline default; hosted profiles fail closed
  service.py         dataset loading + engine/watch/supply/policy/share/field/dashboard/scenario/brief/ingest/notify/integrity/monitoring/configuration/master/integration wiring
  api.py             FastAPI surface
  cli.py             command-line surface (same reads and acts)
  demo.py            the planted-truth walk
migrations/          0001-0019 in sqlite + postgres dialects
scripts/             demo + CLI + local harness + production smoke wrappers
evals/               the eval gate
docs/                architecture.md
```

Apache 2.0. A Trida AI blueprint — patterns are the point; the
fictional company's data is ours, generated for this repo.
