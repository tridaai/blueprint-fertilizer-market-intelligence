"""The supply rule pack — versioned data for the import &
supply-gap tracker (R4).

Every number the supply engine produces traces to a rule stated
here: how a season's consumption spreads over its months, where
the first tracked month's opening stock comes from, how a
shipment counts toward the season it was scheduled for, and the
bands the supply gap is read in. The pack is data with a version,
not scattered constants: a position, gap and projection artefact
each name the pack version they were computed under, and the
verifiers re-perform them from the same pack, so a rule change
is a new pack version and old artefacts stay reproducible under
theirs.

The dataset's scales, stated plainly: the supply facts are
industry production (hundreds of thousands of tonnes a month)
while the tracked demand is the twelve-district market the rest
of the blueprint computes. Two consequences follow, and the pack
deals with both openly rather than by rescaling anything:

- The **level** of a season's supply against tracked demand is
  structurally enormous for the produced fertilizers. The gap
  artefact still reports it — in tonnes and as a percentage of
  demand — because it is the true figure; but a band read off
  that level alone would say "comfortable" in every week of the
  planted import delay, which is exactly the week a market desk
  needs flagged.
- The season's operational risk sits in its **import
  programme**: the shipments scheduled for the season, which is
  also the leg this blueprint's policy and field data keep
  pointing at (an export restriction in a DAP-origin country, a
  slipped vessel, dealer-level stock-outs in the same window).
  So the gap's band is the more severe of two stated readings —
  the programme-cover reading and the level reading. For an
  import-only product whose tracked consumption outruns its
  arrivals, the level reading is the one that bites, and it says
  so on the artefact.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- the position identity ------------------------------------------------
# For one product and one month:
#
#     closing = opening + production (actual) + import arrivals
#               - consumption
#
# Every component is a recorded line on the position artefact,
# pinned to the facts it came from, and the identity is
# re-performable end to end. A component the data cannot supply
# is never silently zero-filled: it is either a computed zero
# over an empty set (a month with no arrivals; a month no
# season's application window covers) with its empty inputs on
# the line, or a `not_applicable` line carrying its reason (an
# import-only product has no domestic production line to state).

# -- consumption, spread to months -----------------------------------------
# Consumption facts are per district x season. The position needs
# them per month, so the pack states the spread: a season's
# consumption is spread evenly over the season's six application
# months (the same window the demand pack reads prices over),
# each month carrying round(total / 6, 3), and the final month
# carrying the rounding residual — so the six months sum back to
# the season total exactly, never to a rounding of it. A month no
# season window covers carries no consumption: the facts record
# none there.

# -- the first month's opening stock ---------------------------------------
# A position chain has to start somewhere. The pack's stated
# derivation for the first tracked month: opening stock = the
# product's average monthly consumption over the first tracked
# crop year (that crop year's stored consumption total / 12) —
# one month of cover at the tracked market's own rate, derived
# from stored facts by a stated rule, re-performable like
# everything else. Every later month's opening is the prior
# month's closing, so the whole chain hangs off this one stated
# derivation and nothing else.
INITIAL_STOCK_MONTHS_OF_COVER = 12  # the divisor: a crop year's months

# -- import programme accounting (the gap) ----------------------------------
# A shipment belongs to the programme of the season its
# EXPECTED month falls in. Programme tests are struck at month
# granularity — the facts are monthly, so knowledge is too:
#
# - a shipment is DUE once its expected month has been reached
#   (expected_month <= the gap's as_of month);
# - a due shipment is CREDITED to its season once it has landed
#   (arrived_month <= as_of month) — credited to the season it
#   was scheduled for, whenever it lands;
# - a due shipment that has not landed is SLIPPED tonnage, named
#   in tonnes on the gap artefact.
#
# Production and consumption enter the gap as the season's
# recorded actuals from the position chain; the as_of governs
# the programme test, which is where the delay lives.

# -- gap bands ----------------------------------------------------------------
# Programme cover = credited / due, as a percentage, read when at
# least one shipment is due. A season's vessels mostly land:
# cover under 95% means part of the programme is missing, and
# under 75% the season is running on a fraction of what was
# scheduled.
PROGRAMME_COVER_COMFORTABLE_PCT = 95.0
PROGRAMME_COVER_TIGHT_PCT = 75.0

# Level gap = (available - demand) / demand, as a percentage:
# available below demand is a shortage outright; within ten
# percent under demand the season has no slack.
LEVEL_GAP_COMFORTABLE_PCT = 0.0
LEVEL_GAP_TIGHT_PCT = -10.0

BAND_RANK = {"comfortable": 0, "tight": 1, "short": 2}


def programme_band(cover_pct: float) -> str:
    if cover_pct >= PROGRAMME_COVER_COMFORTABLE_PCT:
        return "comfortable"
    if cover_pct >= PROGRAMME_COVER_TIGHT_PCT:
        return "tight"
    return "short"


def level_band(gap_pct_of_demand: float) -> str:
    if gap_pct_of_demand >= LEVEL_GAP_COMFORTABLE_PCT:
        return "comfortable"
    if gap_pct_of_demand >= LEVEL_GAP_TIGHT_PCT:
        return "tight"
    return "short"


def worse_band(band_a: str, band_b: str) -> str:
    """The more severe of two readings — the gap's band is the
    worse of its programme and level readings, so neither a
    slipped programme nor a level shortage can hide behind the
    other."""
    return band_a if BAND_RANK[band_a] >= BAND_RANK[band_b] else band_b


# -- projections --------------------------------------------------------------
# A projection is struck at the end of its basis month (the last
# month the actual position covers) and runs to the target
# season's final month. Its stated basis:
#
# - production enters at PLAN (the supply facts' planned
#   tonnes); a horizon month with no plan on record is beyond
#   the plan horizon — named on the artefact, excluded from the
#   projected chain, never extrapolated;
# - imports enter at their EXPECTED month, for shipments not
#   yet landed by the basis month. A shipment whose expected
#   month has passed without landing is SLIPPED: it is excluded
#   from the horizon and named on the artefact, never silently
#   re-dated to a guessed arrival;
# - consumption enters by the same monthly spread as the
#   position, from the recorded consumption facts.
#
# Arrival knowledge is month-granular, matching the facts: a
# shipment counts as landed once its arrived month is inside
# the basis — its tonnes are then already in the basis stock,
# because the position chain is physical.
