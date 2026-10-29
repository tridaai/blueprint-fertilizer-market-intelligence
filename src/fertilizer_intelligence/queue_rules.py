"""The gap action-queue rule pack — versioned data for
the shortage & gap action queue (R13, roadmap F21-OW2).

A gap that nobody owns is just a chart. This pack states
the queue's terms as data: who owns a gap by default,
how long each band gets before it is overdue, the acts
that move an item, and the vocabulary a closing act must
speak. The pack is data with a version: an item names
the pack version it was struck under, closing reasons
are validated against the version the queue runs, and a
vocabulary change is a new pack version, never a code
edit.

- **Membership is derived, never curated.** The queue
  holds exactly one item per non-comfortable supply-gap
  head — every tight or short gap, and nothing else. An
  item exists because a gap artefact says the season is
  short of cover, not because someone raised a ticket.
- **Ownership is stated, then assignable.** Every item
  is struck with the pack's default owner for its
  product — a named desk lead, on the item from its
  first moment, so no gap is ever ownerless. A named
  assign act can move it; the fold of acts, not the
  struck default, is the current owner.
- **Due states are derived from the band.** A short gap
  gets days, a tight gap gets a fortnight, counted from
  the date the item was struck. Overdue is a computation
  against a read date, never a stored flag someone can
  forget to set.
- **Closing is a named act with a stated reason.** The
  vocabulary below is the whole set: supply secured, a
  mitigation scenario adopted, the demand picture
  revised, the successor gap artefact reading
  comfortable, or the risk accepted in the open. A
  free-text shrug closes nothing.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- default owners, by product -------------------------------------------------
# The desk lead who owns a product's gaps until an assign
# act says otherwise. Stated as data so a personnel change
# is a pack change, not a code change.
DEFAULT_OWNERS = {
    "UREA": "R. Menon — nitrogen desk",
    "DAP": "S. Iyer — phosphates desk",
    "NPK_10_26_26": "S. Iyer — phosphates desk",
    "MOP": "K. Bhatt — potash desk",
    "GLYPHOSATE": "L. D'Souza — crop protection desk",
    "CHLORPYRIFOS": "L. D'Souza — crop protection desk",
}
DEFAULT_OWNER_FALLBACK = "Duty manager — supply desk"

# -- due terms, by band ------------------------------------------------------------
DUE_DAYS = {"short": 7, "tight": 14}

# -- acts -----------------------------------------------------------------------------
ACT_ASSIGN = "assign"
ACT_START = "start"
ACT_LINK_SCENARIO = "link_scenario"
ACT_CLOSE = "close"
ACTS = (ACT_ASSIGN, ACT_START, ACT_LINK_SCENARIO, ACT_CLOSE)

# Item states, derived from the fold of acts: open until
# a start, in progress until a close, closed for good.
STATE_OPEN = "open"
STATE_IN_PROGRESS = "in_progress"
STATE_CLOSED = "closed"

# Due states, derived at a read date: an item inside its
# term is within term, on its due date it is due, past it
# overdue — and a closed item reads closed whatever the
# calendar says.
DUE_WITHIN_TERM = "within_term"
DUE_TODAY = "due_today"
DUE_OVERDUE = "overdue"
DUE_CLOSED = "closed"

# -- the closing vocabulary ---------------------------------------------------------
CLOSE_REASONS = {
    "supply_secured": "supply has been secured against the gap",
    "scenario_adopted": "a mitigation scenario was adopted as the plan of record",
    "demand_revised": "a revised demand artefact removed the gap",
    "gap_cleared": "the gap artefact's successor reads comfortable",
    "risk_accepted": "the desk accepts the gap risk for this season, in the open",
}
