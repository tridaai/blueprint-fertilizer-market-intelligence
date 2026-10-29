"""The market-map rule pack — versioned data for the
district demand/gap map (R13, roadmap F21-GS1 + F21-GS2).

Every reading the map states traces to a rule stated here:
how a district's demand outlook is banded from its own
estimates, how the district's gap band is composed, how the
monsoon layer is banded, and how the field-signal layer
keeps confirmed and unconfirmed evidence apart. The pack
is data with a version, not scattered constants: a map
artefact names the pack version it was built under, and
the verifier re-performs it from the same pack, so a rule
change is a new pack version and old maps stay
reproducible under theirs.

The composition rules, stated plainly because the map is
the most persuasive surface in the system and therefore
the one most at risk of overstating what is known:

- **The demand outlook is the district's own.** A cell's
  outlook band reads the district's head demand estimate
  for the switched product and season against the same
  district, product and season in the prior crop year —
  estimate against estimate, both artefacts named on the
  cell. No prior-year estimate means no baseline, and the
  cell says so; an outlook is never invented from a
  national trend.
- **The gap band is a composition of two stated
  readings**, the way the R4 gap itself composes its
  programme and level readings. The product reading is
  the season's R4 gap band for the switched product —
  one reading for the whole tracked market, named as
  such on every cell it touches. The district reading is
  the district's own field-signal pressure: the R7
  assessment's capped, review-weighted adjustment for
  that district and product, banded below. The cell's
  gap band is the more severe of the two, and the cell
  states which readings composed it. A product with no
  supply side (the agrochemicals) contributes no product
  reading; a district with no assessment contributes no
  district reading; a cell with neither states that it
  has no gap evidence — it never borrows a neighbour's.
- **Partial data never wears a confident colour.** A
  cell whose estimate is partial renders hatched and
  badged partial, whatever its bands say. A district
  with no estimate renders as no-data — a distinct
  rendering from a zero figure, because the two claims
  are different claims.
- **Layers keep their evidence classes apart.** The
  monsoon layer re-performs from the monsoon facts. The
  field-signal layer lists confirmed reports (a named
  reviewer's confirm act is the latest word) in the
  confirmed class, and unreviewed or queried reports in
  a separate, labelled pending class. The two classes
  are never merged into one count, and a rejected report
  appears in neither — it is counted on the cell as
  rejected, so its absence is itself stated.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- the tile layout ------------------------------------------------------
# The map is a schematic tile grid, not a geographic
# outline: one tile per tracked district, grouped in
# region rows in the stated order, districts ordered by
# district id within their region. The layout is a pure
# function of the district register, so a rendered map
# re-performs byte for byte.
REGION_ORDER = ("north", "west", "central", "east", "south")

# -- cell data states -------------------------------------------------------
DATA_COMPLETE = "complete"
DATA_PARTIAL = "partial"
DATA_NONE = "no_data"

# -- the demand outlook reading ---------------------------------------------
# Change in the district's estimated demand against the
# prior crop year's same season, in percent. Five percent
# either way is the stated materiality line for a district
# season: inside it the outlook reads steady.
OUTLOOK_GROWING_PCT = 5.0
OUTLOOK_CONTRACTING_PCT = -5.0

OUTLOOK_GROWING = "growing"
OUTLOOK_STEADY = "steady"
OUTLOOK_CONTRACTING = "contracting"
OUTLOOK_NO_BASELINE = "no_baseline"


def outlook_band(change_pct: float | None) -> str:
    if change_pct is None:
        return OUTLOOK_NO_BASELINE
    if change_pct >= OUTLOOK_GROWING_PCT:
        return OUTLOOK_GROWING
    if change_pct <= OUTLOOK_CONTRACTING_PCT:
        return OUTLOOK_CONTRACTING
    return OUTLOOK_STEADY


# -- the district signal-pressure reading ------------------------------------
# The R7 assessment's adjustment for the cell, in percent
# of the estimate total: the capped, review-weighted net
# of the district's own field evidence. A strong positive
# adjustment is the district's reporters saying demand is
# running ahead of the estimate — stock-outs and surges —
# which is exactly local tightness the product-level gap
# cannot see. The bands sit on the field pack's own
# scale: one unreviewed report can move a cell at most
# 1.5 points, so a tight reading needs more than a single
# unverified voice, and a short reading needs confirmed
# weight behind it.
PRESSURE_SHORT_PCT = 4.0
PRESSURE_TIGHT_PCT = 1.5


def pressure_band(adjustment_pct: float | None) -> str | None:
    if adjustment_pct is None:
        return None
    if adjustment_pct >= PRESSURE_SHORT_PCT:
        return "short"
    if adjustment_pct >= PRESSURE_TIGHT_PCT:
        return "tight"
    return "comfortable"


# -- the composed district gap band -------------------------------------------
# basis -> the stated sentence a cell carries about what
# composed its gap band.
GAP_BASIS_PRODUCT_AND_SIGNALS = "product_gap_and_district_signals"
GAP_BASIS_PRODUCT_ONLY = "product_gap_only"
GAP_BASIS_SIGNALS_ONLY = "district_signals_only"
GAP_BASIS_NONE = "no_gap_evidence"

GAP_BASIS_TEXT = {
    GAP_BASIS_PRODUCT_AND_SIGNALS: (
        "the season's product gap band for the tracked market, "
        "composed with this district's own field-signal pressure — "
        "the more severe reading carries the cell"),
    GAP_BASIS_PRODUCT_ONLY: (
        "the season's product gap band for the tracked market; "
        "this district has no field-signal assessment to compose "
        "with it"),
    GAP_BASIS_SIGNALS_ONLY: (
        "this district's own field-signal pressure; the product "
        "has no supply-gap artefact to compose with it"),
    GAP_BASIS_NONE: (
        "no gap evidence: the product has no supply-gap artefact "
        "and this district has no field-signal assessment"),
}

# -- the monsoon layer ---------------------------------------------------------
# Deviation from the long-period average, in percent, per
# district and season, straight from the monsoon facts.
# Ten percent either way is the stated line the demand
# pack's own driver treats as material.
MONSOON_DEFICIT_PCT = -10.0
MONSOON_SURPLUS_PCT = 10.0

MONSOON_DEFICIT = "deficit"
MONSOON_NEAR_NORMAL = "near_normal"
MONSOON_SURPLUS = "surplus"
MONSOON_NO_DATA = "no_data"


def monsoon_band(deviation_pct: float | None) -> str:
    if deviation_pct is None:
        return MONSOON_NO_DATA
    if deviation_pct <= MONSOON_DEFICIT_PCT:
        return MONSOON_DEFICIT
    if deviation_pct >= MONSOON_SURPLUS_PCT:
        return MONSOON_SURPLUS
    return MONSOON_NEAR_NORMAL


# -- the field-signal layer -----------------------------------------------------
# The layer's classes. Confirmed means the report's
# derived review state is confirmed; pending means
# unreviewed or queried — evidence that has arrived but
# has not earned its full weight, rendered in its own
# labelled class and never counted with the confirmed.
LAYER_CONFIRMED = "confirmed"
LAYER_PENDING = "pending"
