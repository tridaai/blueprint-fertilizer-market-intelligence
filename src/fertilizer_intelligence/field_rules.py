"""The field-signal rule pack — versioned data for field
reports, their verification and their weighting (R7).

Everything Round 7 does with a field signal traces to a rule
stated here: what the mobile intake form may carry, how a
submitted signal type normalizes to the kind the weighting
reads, what each kind is worth to the demand consumer at full
weight, how freshness decays that weight, the cap Law 5 puts
on a single unverified report, and the acts a reviewer may
record against a report with the reasons each act accepts.
The pack is data with a version, not scattered constants: a
field artefact names the pack version it was landed or
computed under, and the verifiers re-perform the weighting
from the same pack, so a rule change is a new pack version
and old artefacts stay reproducible under theirs.

The disciplines the pack states once, for every field signal:

- **Attribution is constitutive.** A field report is an
  artefact with a named reporter, a district, a product and
  an observation date. The intake refuses a submission
  missing any of them, naming the missing fields — an
  unattributed signal is never defaulted into existence
  (Law 5: field signals stay attributed).
- **Sync is exactly-once.** A submission carries a
  client-generated submission id. The same submission id
  with the same payload lands exactly once, however often
  the outbox re-sends it. The same id with a *different*
  payload is a conflict: both artefacts are kept, linked,
  and the conflict is flagged — never a silent overwrite.
- **Review state is derived, never stored.** A report lands
  `unreviewed`. Reviewer acts (confirm / query / reject, each
  with a reason from the act's stated vocabulary) are
  insert-only artefacts; the state is the fold of the acts.
  A rejection is terminal: it stands whatever later acts are
  attempted (they are refused), and a corrected observation
  must arrive as a new report.
- **Weight is review state times freshness.** A confirmed
  report carries its kind's full stated effect, decayed by
  age. An unreviewed report's contribution is capped at the
  pack's unverified cap — Law 5's "a single unverified
  report cannot move an estimate beyond a stated cap", as a
  number. A queried report carries zero weight until it is
  re-confirmed; a rejected report carries zero forever.
- **Freshness decays, then expires.** Weight decays with a
  stated half-life from the observation date; past the
  pack's maximum age a report's weight is zero and the line
  is named `expired` on the assessment — listed, attributed,
  and weightless, never silently dropped.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- intake ------------------------------------------------------------------
# What the low-bandwidth mobile form may carry (F21-DI3). The
# submission id lives on the sync envelope, not in the form:
# it is generated on the device when the report is queued in
# the outbox, so a re-send of the same queued report carries
# the same id — that is what makes sync exactly-once.
INTAKE_SOURCE = "field_mobile_intake"

SIGNAL_TYPES = (
    "price_observed",
    "stock_observed",
    "demand_signal",
    "competitor_activity",
)

# demand_signal is the one intake type that needs a direction
# before it can normalize to a weighted kind.
DEMAND_DIRECTIONS = ("up", "down", "flat")

REQUIRED_FIELDS = ("reporter", "district_id", "product", "signal_type", "observed_on")

# -- signal kinds and their demand effect -------------------------------------
# The normalized kind the weighting reads. The planted R1
# reports already speak in kinds; intake types normalize into
# the same vocabulary here, in exactly one place.
KIND_BY_INTAKE_TYPE = {
    "price_observed": "price_observed",
    "stock_observed": "stock_out",
    "competitor_activity": "competitor_activity",
}
KIND_BY_DEMAND_DIRECTION = {
    "up": "demand_surge",
    "down": "demand_slump",
    "flat": "demand_flat",
}

# The demand effect of one report of each kind at full weight
# and zero age, as percentage points of the cell's R2 demand
# estimate total — stated, so the weighting re-performs.
# Kinds whose information belongs to another surface (a price
# observation feeds the price watch's world, a competitor
# sighting the share world) carry zero demand effect *on this
# consumer*, and the zero is stated here rather than implied
# by an absence.
EFFECT_PCT = {
    "demand_surge": 6.0,
    "demand_slump": -6.0,
    "stock_out": 5.0,
    "pest_outbreak": 4.0,
    "discounting": -3.0,
    "demand_flat": 0.0,
    "price_observed": 0.0,
    "competitor_activity": 0.0,
}

# -- freshness -----------------------------------------------------------------
# Weight halves every HALF_LIFE_DAYS from the observation
# date; past MAX_AGE_DAYS the weight is zero and the line is
# named expired on the assessment.
HALF_LIFE_DAYS = 30
MAX_AGE_DAYS = 180

# -- the Law 5 cap ---------------------------------------------------------------
# The most one unreviewed report may move a cell's estimate,
# in percentage points of the estimate total — applied to the
# report's decayed contribution, sign preserved.
UNVERIFIED_CAP_PCT = 1.5

# -- review acts -------------------------------------------------------------------
ACT_CONFIRM = "confirm"
ACT_QUERY = "query"
ACT_REJECT = "reject"
ACTS = (ACT_CONFIRM, ACT_QUERY, ACT_REJECT)

# The stated reason vocabulary of each act. An act with a
# reason outside its vocabulary is refused.
ACT_REASONS = {
    ACT_CONFIRM: ("corroborated", "reporter_verified", "consistent_with_records"),
    ACT_QUERY: ("needs_quantity", "needs_photo_evidence", "date_unclear", "conflicting_report"),
    ACT_REJECT: ("duplicate", "not_credible", "wrong_district", "stale_observation"),
}

# Review states, derived from the acts — the fold is stated
# here and implemented in one place (field.derive_review_state):
# any reject act -> rejected (terminal); otherwise the latest
# act decides (confirm -> confirmed, query -> queried); no
# acts -> unreviewed.
STATE_UNREVIEWED = "unreviewed"
STATE_CONFIRMED = "confirmed"
STATE_QUERIED = "queried"
STATE_REJECTED = "rejected"
REVIEW_STATES = (
    STATE_UNREVIEWED,
    STATE_CONFIRMED,
    STATE_QUERIED,
    STATE_REJECTED,
)

# Arithmetic discipline, stated so a verifier re-performing
# the weighting lands on the same figures: decay and
# per-report contributions to six decimals, the cell
# adjustment to four, tonnes to three (the store's precision).
DECAY_DECIMALS = 6
CONTRIBUTION_DECIMALS = 6
PCT_DECIMALS = 4
TONNE_DECIMALS = 3
