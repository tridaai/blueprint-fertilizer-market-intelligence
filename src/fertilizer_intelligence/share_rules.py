"""The share rule pack — versioned data for competitor &
market-share intelligence (R6).

Every share figure traces to a rule stated here: how a monthly
competitor point is attributed to a season, how the region's
observed structure distributes a district's recorded market
across sellers, where Kaveri's own volume comes from, what
makes an observation stale, and which months a headline share
is computed over. The pack is data with
a version, not scattered constants: a share artefact names the
pack version it was computed under, and the verifiers
re-perform it from the same pack, so a rule change is a new
pack version and old artefacts stay reproducible under theirs.

The disciplines the pack states once, for every share:

- **Attribution is unique.** A competitor point belongs to
  exactly one season: the season whose six-month window (the
  demand pack's calendar) opens at the point's month when a
  season opens there — November opens rabi while closing
  kharif, and belongs to rabi — otherwise the season whose
  window contains the month. A month in no tracked window
  (April/May at the edges of the tracked years) belongs to no
  season and is stated as such on the observation. This is the
  same convention the policy pack states for event windows,
  so a month is never counted in two seasons anywhere in the
  repo.
- **District volumes follow the region's observed
  structure.** The tracked competitor volumes are whole-region
  figures — a single tracked competitor's region season
  volume is several times the tracked districts' entire
  recorded market, because the twelve tracked districts are a
  sample of their regions, not the whole of them. Allocating
  raw region tonnage into a district would fabricate district
  volumes larger than the district's market, so the pack
  states the construction the data supports: per month, the
  region's observed market is the tracked competitors'
  volumes plus Kaveri's home-market anchor — the region's R2
  demand total, spread over the season window by the supply
  pack's rule — and each seller's share of that observed
  market is its region structure share. A district's volume
  for a seller is the district's recorded market for the
  month (its consumption total, spread the same way)
  distributed by those structure shares. The structure is
  computed from stored figures only, and every intermediate
  volume is carried on the artefact, so the construction
  re-performs exactly.
- **Kaveri's volume is the residual.** Within the district's
  recorded market, Kaveri's volume is what remains after the
  tracked competitors' structure-distributed volumes are
  taken out. The residual is named as a residual on the
  artefact — any untracked seller sits inside the residual,
  and the artefact says so.
- **Freshness is per source class.** An observation carries
  its source label; the pack states the freshness window of
  the label's source class in days. An observation older than
  its window at the share's read date is stale. A source label
  whose class has no stated window is never fresh — an
  unstated window is not an infinite one.
- **The headline is the fresh window.** A share is read at a
  stated date (by default the season's close). A month whose
  observations are stale, or whose month-end falls after the
  read date, is excluded from the headline, and the exclusion
  is named on the artefact — "headline excludes N stale
  observations". The full-season reading is carried alongside,
  labelled as including stale figures, and the two readings
  are never blended. A district-season whose every month is
  excluded reads `not_current`: a named state, never a silent
  old number.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# The home seller. Competitor labels come from the tracked
# data; this is the only seller the system speaks for.
KAVERI_SELLER = "Kaveri Agro Inputs"

# -- freshness -------------------------------------------------------------
# Source label -> source class, and the class's freshness
# window in days. Field tracking is a season-scale instrument:
# a tracked figure is trusted for 200 days from its observation
# date. A label with no class stated here has no window, and
# its observations are never fresh (see the module docstring).
SOURCE_CLASS_BY_LABEL = {
    "competitor_field_tracking": "field_tracking",
}
FRESHNESS_WINDOW_DAYS = {
    "field_tracking": 200,
}


def source_class(source_label: str) -> str | None:
    return SOURCE_CLASS_BY_LABEL.get(source_label)


def freshness_window_days(source_label: str) -> int | None:
    """The stated freshness window for a source label, or None
    when the pack states no window for its class — in which
    case the observation can never be fresh."""
    klass = source_class(source_label)
    if klass is None:
        return None
    return FRESHNESS_WINDOW_DAYS.get(klass)


# -- arithmetic --------------------------------------------------------------
# The stated rounding of the share engine, so a verifier
# re-performing the computation lands on the same figures:
# region structure shares to six decimals, volumes to three
# (the store's tonne precision), percentages to four.
STRUCTURE_DECIMALS = 6
VOLUME_DECIMALS = 3
PCT_DECIMALS = 4

# The two denominators every share reading carries, labelled
# and never blended:
# - observed_market: the volumes this reading is computed over
#   (Kaveri residual + tracked competitors) — the market as
#   observed;
# - total_demand: the R2 demand estimate total over the same
#   months (the season total spread by the supply pack's rule,
#   summed over the reading's months) — the market as
#   estimated.
DENOMINATOR_OBSERVED = "observed_market"
DENOMINATOR_DEMAND = "total_demand"

# Reading basis labels, carried on every reading so a figure
# can never be quoted without the basis it was computed on.
BASIS_HEADLINE = "fresh_window"
BASIS_FULL_SEASON = "full_season_including_stale"

# Month states at a read date, stated once:
# - fresh: the month's observations are inside their window;
# - no_observation: no competitor observation is attributed to
#   the month (its tracked points belong to the season opening
#   there, or none were recorded) — the month still counts,
#   with the residual absorbing it, and the state is named;
# - stale: at least one of the month's observations is past
#   its freshness window — the month is excluded from the
#   headline;
# - after_read_date: the month ends after the read date — the
#   month is excluded from every reading at that date.
MONTH_FRESH = "fresh"
MONTH_NO_OBSERVATION = "no_observation"
MONTH_STALE = "stale"
MONTH_AFTER_READ_DATE = "after_read_date"

HEADLINE_MONTH_STATES = (MONTH_FRESH, MONTH_NO_OBSERVATION)

# Share artefact states: current (a headline exists),
# not_current (every month excluded — the named state the
# brief requires instead of a silent old number), and
# no_observations (no competitor observation is attributed to
# the cell at all — competitor share is unknown, stated).
STATUS_CURRENT = "current"
STATUS_NOT_CURRENT = "not_current"
STATUS_NO_OBSERVATIONS = "no_observations"
