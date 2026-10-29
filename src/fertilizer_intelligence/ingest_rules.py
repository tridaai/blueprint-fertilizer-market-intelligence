"""The ingest pack: the versioned rules the production data
plane runs under (R11, roadmap F21-DI1 + F21-DI2 + F21-DI4).

Like every pack in this system, the rules are data stated
here, in one place:

- the **source registry**: every admissible external feed,
  the fact class it may deliver, the provenance string its
  rows must carry, its cadence, its owner, and its freshness
  rule — a batch naming an unregistered source is refused
  before a single row is read;
- the **fact-class contracts**: per class, the natural key a
  row is identified by, the fields a row must carry, and the
  model the row is validated into — a row without ``source``
  or ``as_of`` is refused at the port, before it can reach
  the store (the models make provenance mandatory and the
  tables make it NOT NULL, so the refusal is schema-level,
  not a courtesy check);
- the **quarantine reasons**: the named reasons a row that
  arrives with provenance can still be held out of the fact
  tables — a held row is recorded with its reason and its
  raw payload, and no engine ever reads it;
- the **actuals kinds**: season-close actuals land as their
  own fact class under their own kinds, through the same
  connector path, and never touch an estimate.
"""

from __future__ import annotations

from .generator import FEEDSTOCKS, PRODUCTS

RULES_VERSION = "2026.10.1"

# -- fact classes -----------------------------------------------------------
# The classes a connector may deliver. Each maps to one fact
# table (actuals to their own), one pydantic model, one
# natural key and one duplicate-comparison basis.

PRICE_POINTS = "price_points"
SUPPLY_FACTS = "supply_facts"
IMPORT_ARRIVALS = "import_arrivals"
POLICY_EVENTS = "policy_events"
COMPETITOR_POINTS = "competitor_points"
SEASON_ACTUALS = "season_actuals"

FACT_CLASSES = [
    PRICE_POINTS,
    SUPPLY_FACTS,
    IMPORT_ARRIVALS,
    POLICY_EVENTS,
    COMPETITOR_POINTS,
    SEASON_ACTUALS,
]

# Fields every row of the class must carry, in the order the
# natural key is built from them. Provenance (source, as_of)
# is required on every class and is checked before this list:
# a row missing it is refused, not quarantined.
CLASS_FIELDS = {
    PRICE_POINTS: ["series_kind", "item", "month", "price", "unit"],
    SUPPLY_FACTS: ["product", "month", "planned_tonnes", "actual_tonnes"],
    IMPORT_ARRIVALS: [
        "shipment_id", "product", "expected_month", "arrived_month",
        "quantity_tonnes", "origin",
    ],
    POLICY_EVENTS: [
        "event_id", "date", "kind", "title", "detail",
        "expected_impact", "impacted_products",
    ],
    COMPETITOR_POINTS: [
        "competitor", "region", "product", "month", "volume_tonnes",
        "price",
    ],
    SEASON_ACTUALS: [
        "district_id", "crop_year", "season", "product", "actual_kind",
        "quantity_tonnes",
    ],
}

NATURAL_KEYS = {
    PRICE_POINTS: ["series_kind", "item", "month"],
    SUPPLY_FACTS: ["product", "month"],
    IMPORT_ARRIVALS: ["shipment_id"],
    POLICY_EVENTS: ["event_id"],
    COMPETITOR_POINTS: ["competitor", "region", "product", "month"],
    SEASON_ACTUALS: [
        "district_id", "crop_year", "season", "product", "actual_kind",
    ],
}

# The store read that returns the class's stored rows, and
# the insert that lands a validated batch of them.
CLASS_STORE_READ = {
    PRICE_POINTS: "price_points",
    SUPPLY_FACTS: "supply_facts",
    IMPORT_ARRIVALS: "import_arrivals",
    POLICY_EVENTS: "policy_events",
    COMPETITOR_POINTS: "competitor_points",
    SEASON_ACTUALS: "season_actuals",
}

# -- vocabularies ------------------------------------------------------------

KNOWN_PRODUCTS = list(PRODUCTS)
PRICE_ITEMS = list(PRODUCTS) + list(FEEDSTOCKS)
SERIES_KINDS = ["product", "feedstock"]
POLICY_KINDS = [
    "subsidy_change", "mrp_notification", "import_policy", "state_scheme",
]
ACTUAL_KINDS = ["consumption", "dispatch"]

# -- quarantine reasons -------------------------------------------------------
# The named reasons a provenanced row is held out of the
# fact tables. A batch's quarantine is graded against these
# exactly: every held row carries exactly one reason.

REASON_UNKNOWN_DISTRICT = "unknown_district"
REASON_UNKNOWN_PRODUCT = "unknown_product"
REASON_UNKNOWN_KIND = "unknown_kind"
REASON_NEGATIVE_QUANTITY = "negative_quantity"
REASON_NON_POSITIVE_PRICE = "non_positive_price"
REASON_SOURCE_MISMATCH = "source_mismatch"
REASON_STALE_BEYOND_FRESHNESS = "stale_beyond_freshness"
REASON_FUTURE_AS_OF = "future_as_of"
REASON_MALFORMED_ROW = "malformed_row"
REASON_CONFLICTS_WITH_STORED = "conflicts_with_stored"

QUARANTINE_REASONS = [
    REASON_UNKNOWN_DISTRICT,
    REASON_UNKNOWN_PRODUCT,
    REASON_UNKNOWN_KIND,
    REASON_NEGATIVE_QUANTITY,
    REASON_NON_POSITIVE_PRICE,
    REASON_SOURCE_MISMATCH,
    REASON_STALE_BEYOND_FRESHNESS,
    REASON_FUTURE_AS_OF,
    REASON_MALFORMED_ROW,
    REASON_CONFLICTS_WITH_STORED,
]

# The refusal reason for a row refused at the port. Refusals
# are recorded on the batch report, never in quarantine:
# quarantine is for facts that arrived, refusals never did.
REFUSAL_MISSING_PROVENANCE = "missing_provenance"

# -- the source registry -------------------------------------------------------
# One entry per admissible feed. ``provenance_source`` is
# the exact source string the feed's rows carry — a row
# claiming any other source under this feed's batch is held
# as source_mismatch. ``freshness_days`` bounds the row's
# as_of against the batch's load date: older than the
# window is stale, later than the load date is future.

SOURCES = {
    "intl_price_feed": {
        "fact_class": PRICE_POINTS,
        "provenance_source": "intl_price_feed",
        "cadence": "daily",
        "owner": "market-data desk",
        "freshness_days": 7,
        "description": "International and domestic price prints "
                       "for tracked products and feedstocks",
    },
    "plant_production_returns": {
        "fact_class": SUPPLY_FACTS,
        "provenance_source": "plant_production_returns",
        "cadence": "monthly",
        "owner": "supply desk",
        "freshness_days": 45,
        "description": "Producer returns of planned and actual "
                       "production, per product per month",
    },
    "port_import_manifests": {
        "fact_class": IMPORT_ARRIVALS,
        "provenance_source": "port_import_manifests",
        "cadence": "weekly",
        "owner": "supply desk",
        "freshness_days": 31,
        "description": "Port manifests for tracked import "
                       "shipments, expected against arrived",
    },
    "gazette_policy_notices": {
        "fact_class": POLICY_EVENTS,
        "provenance_source": "gazette_policy_notices",
        "cadence": "event-driven",
        "owner": "policy desk",
        "freshness_days": 92,
        "description": "Gazette and ministry notices: subsidy, "
                       "MRP, import policy, state schemes",
    },
    "dealer_competitor_returns": {
        "fact_class": COMPETITOR_POINTS,
        "provenance_source": "dealer_competitor_returns",
        "cadence": "monthly",
        "owner": "market-data desk",
        "freshness_days": 45,
        "description": "Dealer-network returns of competitor "
                       "volumes and prices by region",
    },
    "state_dispatch_returns": {
        "fact_class": SEASON_ACTUALS,
        "provenance_source": "state_dispatch_returns",
        "cadence": "season-close",
        "owner": "state agriculture departments",
        "freshness_days": 370,
        "description": "Season-close realized consumption and "
                       "dispatch returns, by district",
    },
}


def source_entry(source_id: str) -> dict | None:
    return SOURCES.get(source_id)


def natural_key(fact_class: str, row: dict) -> dict:
    """The row's identity under its class contract: the
    natural-key fields and their values, nothing else."""
    return {field: row.get(field) for field in NATURAL_KEYS[fact_class]}


def key_label(fact_class: str, key: dict) -> str:
    """A stable one-line rendering of a natural key, used
    wherever a row must be named (quarantine records,
    correction links, reports)."""
    fields = NATURAL_KEYS[fact_class]
    return "/".join(str(key.get(field)) for field in fields)
