"""The notify rule pack — versioned data for alert
subscriptions, deliveries, escalation and digests
(R16, roadmap F21-AL1 + F21-AL2).

The desk's alerts were struck by the engines and read
by whoever opened the board. This pack states the
terms on which an alert reaches a named person, as
data with a version:

- **Three notice classes, kept apart.** A notice is
  derived from one alert artefact: a price alert (R3),
  a non-comfortable supply-gap head (R4, the R13
  queue's membership), or a current policy registry
  head (R5). Policy notices are their own class and
  are never counted as price alerts — the R5 discipline
  (markers are not alerts) carries through delivery
  and digest counts exactly.
- **Severity is per class, on the owning pack's
  scale.** Price notices rank by the alert pack's
  bands (watch below alert); gap notices by the
  supply pack's bands (tight below short); a policy
  notice is a marker, rank 1, the only severity its
  class has. A subscription's floor is stated per
  class in that class's own labels.
- **Geography is stated or national.** Price and gap
  series are national: their notices carry no region.
  A policy notice carries the regions of the districts
  its event names; an event naming no districts is
  market-wide and its notice is national. A
  subscription's region filter matches only a notice
  whose stated geography touches the filter — a
  national notice does not match a region filter,
  because the desk cannot honestly say which region a
  national move belongs to.
- **Remit is a second, harder line.** A subscription
  states what its subscriber wants; the access pack's
  register states what they may receive. A delivery
  exists only where the two agree: strategy receives
  the whole book; a product reader receives notices
  whose product sits in their remit (a feedstock
  notice sits in no product remit); a regional reader
  receives only notices whose stated geography touches
  their regions — a national notice cannot be placed
  in a regional remit, exactly as the access pack
  judges an unplaceable read as outside it; a viewer
  receives nothing.
- **Escalation is a clock, not a job.** Only price
  alerts acknowledge, so only they escalate: an
  alert-band (critical) price alert still open past
  the pack's windows climbs a ladder — first the
  product owner the register names for its item (the
  strategy principal when no product reader owns the
  item), then the strategy principal. The state is
  derived from the alert's acts and the read date,
  every time, by re-performance.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- notice classes ------------------------------------
CLASS_PRICE = "price"
CLASS_GAP = "gap"
CLASS_POLICY = "policy"
CLASSES = (CLASS_PRICE, CLASS_GAP, CLASS_POLICY)

# -- severity scales, per class, in the owning packs'
# labels. A floor names a label; a notice delivers
# when its rank is at least the floor's rank. --------
SEVERITY = {
    CLASS_PRICE: {"watch": 1, "alert": 2},
    CLASS_GAP: {"tight": 1, "short": 2},
    CLASS_POLICY: {"marker": 1},
}

# -- escalation (price alerts at the alert band) -------
# Days an alert may sit unacknowledged before each
# ladder level engages. Level 0 is within window.
ESCALATION_WINDOWS = {1: 3, 2: 7}
ESCALATION_BAND = "alert"

# Ladder slots, resolved from the access register at
# derivation time: the product owner for the alert's
# item, then the strategy principal. A slot that
# resolves to nobody is named as unstaffed, never
# silently dropped.
LADDER_PRODUCT_OWNER = "product_owner"
LADDER_STRATEGY = "strategy"
LADDER = (LADDER_PRODUCT_OWNER, LADDER_STRATEGY)
