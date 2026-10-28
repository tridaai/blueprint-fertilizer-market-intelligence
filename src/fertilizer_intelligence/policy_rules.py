"""The policy rule pack — versioned data for the policy &
subsidy event registry (R5).

The registry holds policy events as first-class artefacts, and
every part of a registration traces to a statement here: the
event-class vocabulary, the driver each class touches, the
engine surface that driver would move, how the dataset's
recorded event kinds map onto the registry's classes, how an
event's effective window is derived from its date, and when the
watch board carries a policy marker. The pack is data with a
version, not scattered constants: a registry artefact names the
pack version it was registered under, and the verifiers
re-perform registrations from the same pack, so a vocabulary
change is a new pack version and old artefacts stay
reproducible under theirs.

Three disciplines the pack states once, for every event:

- **The stated effect is data, never commentary.** Each event
  carries its expected effect as a structured statement —
  direction, driver, the mechanism in the words recorded at
  registration, and the linkage below naming the engine surface
  the effect would move. Nothing downstream may restate an
  effect the registry does not hold, and no engine consumes an
  effect as an input: the linkage names what a human should
  look at, it does not move a number by itself.
- **Scope is products and districts, as recorded.** An event
  names the products it touches (a feedstock series item is a
  valid scope entry — an origin restriction names phosphoric
  acid alongside DAP in the planted record). An empty district
  list means the event was recorded market-wide; the registry
  never narrows a scope the record did not narrow.
- **A hypothetical is a different kind of record, not a flag
  that can drift.** A proposed policy is registered with
  `hypothetical` set; it is listed separately, it never earns
  an impact note and never marks the watch board. Registrations
  are insert-only, so the flag cannot be flipped on a stored
  artefact — a proposal that becomes real is a new registration
  superseding the hypothetical by link.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- the class vocabulary -------------------------------------------------
# Each class states the driver it touches and the engine surface
# that driver would move — the linkage an impact note echoes and
# a reader follows. A registration whose stated driver disagrees
# with its class's driver here is refused: the class is the
# claim about what kind of lever the policy is.
#
# The drivers are the blueprint's three: demand_rate (the
# application rates the demand engine reads), price (the retail
# and realisation prices the demand elasticity and the price
# watch read), supply (the arrivals and production the supply
# tracker states).
EVENT_CLASSES = {
    "subsidy_rate_change": {
        "driver": "price",
        "linkage": {
            "engine": "demand",
            "parameter": "price_elasticity",
        },
        "statement": "a subsidy revision moves the retail price "
                     "realisation the demand pack's price-elasticity "
                     "driver reads",
    },
    "price_control": {
        "driver": "price",
        "linkage": {
            "engine": "price_watch",
            "target": "product_price_series",
        },
        "statement": "a price notification pins the product price "
                     "series the price watch reads",
    },
    "import_duty_change": {
        "driver": "supply",
        "linkage": {
            "engine": "supply",
            "line": "import_arrivals",
            "aspect": "landed_cost",
        },
        "statement": "a duty change moves the landed cost of the "
                     "import arrivals the supply tracker states",
    },
    "export_restriction": {
        "driver": "supply",
        "linkage": {
            "engine": "supply",
            "line": "import_arrivals",
        },
        "statement": "an origin restriction moves the import "
                     "arrivals themselves — tonnage and timing",
    },
    "production_incentive": {
        "driver": "demand_rate",
        "linkage": {
            "engine": "demand",
            "parameter": "application_rates",
        },
        "statement": "an incentive on purchases or production "
                     "moves the application rates in the demand "
                     "pack's stored rate table",
    },
    "environmental_rule": {
        "driver": "demand_rate",
        "linkage": {
            "engine": "demand",
            "parameter": "application_rates",
        },
        "statement": "a use or application rule moves the "
                     "application rates in the demand pack's "
                     "stored rate table",
    },
}

DRIVERS = ("demand_rate", "price", "supply")

# The direction of the stated effect, read on the class's
# driver: up / down / none. `none` is a positive statement —
# the recorded effect names no directional move (a price held,
# a rate adjusted without a stated direction) — never a missing
# value.
DIRECTIONS = ("up", "down", "none")

# -- the recorded facts' kinds ---------------------------------------------
# The dataset (R1) records policy facts under its own kind
# vocabulary. Registration maps each recorded kind onto exactly
# one registry class, here, so the same fact can never be
# registered two ways.
CLASS_BY_FACT_KIND = {
    "subsidy_change": "subsidy_rate_change",
    "mrp_notification": "price_control",
    "import_policy": "export_restriction",
    "state_scheme": "production_incentive",
}

# The planted events' stated directions, read off each fact's
# recorded expected-impact text at registration time:
# - POL-2024-001: rates revised upward, realisation improves
#   on P&K grades -> up
# - POL-2024-002: MRP retained, no price movement expected
#   -> none
# - POL-2025-001: district demand expected to firm -> up
# - POL-2025-002: the package's stated effect is that the DAP
#   price does NOT rise (held capped) -> none
# - POL-2025-003: arrivals expected to slip (the price spike in
#   the same text is downstream of the supply move) -> down
# - POL-2026-001: a nutrient rate adjusted; the recorded text
#   states a small realisation change without a direction
#   -> none
PLANTED_DIRECTIONS = {
    "POL-2024-001": "up",
    "POL-2024-002": "none",
    "POL-2025-001": "up",
    "POL-2025-002": "none",
    "POL-2025-003": "down",
    "POL-2026-001": "none",
}

# -- the effective window ---------------------------------------------------
# A recorded event carries a date, not a window; the registry
# derives the window in whole months by this stated rule: the
# window opens at the event's month and closes at the end of
# the season price window (the demand pack's six-month calendar)
# that contains the event's month — an event speaks to the
# season it lands in. A month that opens a season (November
# opens rabi while closing kharif) belongs to the season
# opening there. A month before every tracked season (April
# 2024, when a kharif revision is announced) closes at the end
# of the next season window to open. A registrar registering a
# new event at the desk states its window explicitly instead.


def class_driver(event_class: str) -> str:
    return EVENT_CLASSES[event_class]["driver"]


def class_linkage(event_class: str) -> dict:
    return dict(EVENT_CLASSES[event_class]["linkage"])


# -- watch-board markers ------------------------------------------------------
# When a real (non-hypothetical, current-head) event's window is
# open, the watch board surfaces it on the rows of the series it
# scopes to — a policy marker, typed separately from price
# alerts and never counted as one. "Open" is read against the
# board's reference month, stated here: the latest month any
# tracked price series holds, i.e. the desk's current month.
