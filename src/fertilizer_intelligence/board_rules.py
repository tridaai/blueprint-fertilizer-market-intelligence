"""The morning-board rule pack — versioned data for the
market morning board (R13, roadmap F21-OW1).

The board is the opening view a desk starts its day
with: open alerts, districts trending short, stale
figures, pending brief approvals. Everything about its
composition is stated here as data: which lanes each
role opens, what belongs in a lane, and the order rows
sit in. The pack is data with a version, not scattered
constants: a board artefact names the pack version it
was built under, and the verifier re-performs it from
the same pack.

The ranking discipline, stated once for every lane:
**rows are ranked by the packs that own their subject
matter, never by recency.** Alerts rank by the alert
pack's band order, then by a stated rule order, then by
the size of the move. Short districts rank by the
composed gap band, then by how far under demand the
product gap sits. Stale figures rank by how much stale
evidence they carry. Pending briefs rank by the severity
of what they carry — a brief holding a short gap
outranks one holding only a watch alert — with the week
ending used only as the final tiebreak between briefs
of equal severity. A board that sorted by what happened
most recently would bury the worst problem under the
newest one; this board sorts by the problem.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- lanes ---------------------------------------------------------------------

LANE_OPEN_ALERTS = "open_alerts"
LANE_SHORT_DISTRICTS = "districts_trending_short"
LANE_STALE_FIGURES = "stale_figures"
LANE_PENDING_BRIEFS = "pending_brief_approvals"

LANE_TITLES = {
    LANE_OPEN_ALERTS: "Open price alerts",
    LANE_SHORT_DISTRICTS: "Districts trending short",
    LANE_STALE_FIGURES: "Stale figures",
    LANE_PENDING_BRIEFS: "Brief approvals pending",
}

# -- roles and their opening lanes, stated as data ------------------------------
# A regional head runs districts: every lane. A national
# planner works the same four from the programme side.
# Leadership opens on the exceptions and the decisions
# waiting for sign-off, not the figure hygiene.
ROLE_LANES = {
    "regional_head": (
        LANE_OPEN_ALERTS, LANE_SHORT_DISTRICTS,
        LANE_STALE_FIGURES, LANE_PENDING_BRIEFS,
    ),
    "national_planner": (
        LANE_OPEN_ALERTS, LANE_SHORT_DISTRICTS,
        LANE_STALE_FIGURES, LANE_PENDING_BRIEFS,
    ),
    "leadership": (
        LANE_OPEN_ALERTS, LANE_SHORT_DISTRICTS, LANE_PENDING_BRIEFS,
    ),
}

ROLES = tuple(ROLE_LANES)

# -- alert ranking ----------------------------------------------------------------
# Rule order inside a band: a spike is a single violent
# move and outranks a drift from baseline, which outranks
# an ordinary month-on-month move, which outranks a
# sustained crawl. The band itself ranks by the alert
# pack's BAND_RANK (alert above watch).
RULE_RANK = {"spike": 3, "baseline": 2, "mom": 1, "sustained_move": 0}

# The figure an alert row is ranked and read by, per rule:
# the move that fired it.
RULE_FIGURE = {
    "spike": "mom_pct",
    "mom": "mom_pct",
    "baseline": "baseline_pct",
    "sustained_move": "cumulative_pct",
}

# -- pending-brief severity --------------------------------------------------------
# A pending brief's severity is read off the figures its
# own sections carry, under the brief pack's figure
# vocabulary: a short gap is the heaviest thing a brief
# can hold, then an alert-band price alert, then a tight
# gap, then a watch-band alert. The score is the single
# heaviest class present — briefs are ranked by the worst
# thing in them, not by how much is in them.
BRIEF_SEVERITY = {
    "short_gap": 4,
    "alert_band_alert": 3,
    "tight_gap": 2,
    "watch_band_alert": 1,
    "none": 0,
}
