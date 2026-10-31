"""The integration rule pack — versioned data for
the webhook, token and exchange surfaces (R19,
roadmap F21-IA1 + F21-IA2).

A market-intelligence system earns its keep inside
the company's other systems: a shortage should reach
the ERP before a person reads a dashboard. This pack
states, as data with a version, how this system
speaks outward and what it accepts inward.

- **Webhooks are signed deliveries of artefact
  reads.** An integration subscribes to event
  families — spike alerts, gap-band changes, brief
  publications. A delivery is an insert-only
  artefact whose payload is exactly the read the
  system's own surfaces serve for the triggering
  artefact, signed with HMAC-SHA256 over its
  canonical form under the subscription's secret.
  The secret is held to sign and to verify; no read
  surface ever returns it — a subscription read
  states that a secret is set, never its value.
  A delivery covers a trigger on or after the
  subscription's registration, struck while the
  subscription stands active at the trigger's own
  date — a disable act silences triggers from its
  date, never rewrites ones already earned.
  Dispatch is deterministic and idempotent: the
  same fold over the same artefacts strikes the
  same deliveries and no others.
- **API tokens are scoped, and every read leaves
  an entry.** A token names its integration and
  the read families it may touch — alerts, gaps,
  briefs — and nothing else. The store keeps the
  token's hash, never the token. Every presented
  read, allowed or refused, appends a decision
  entry: who (which token), what kind, what
  target, what was decided and why — and the
  revocation acts on file when the judgement was
  made, bound into the entry, so the verifier
  re-judges from exactly the acts the judgement
  saw and a later revocation never rewrites an
  earlier honest read. An out-of-scope read is
  refused, and the refusal is the logged fact; a
  revoked token refuses everything.
- **Exchange ports are stated contracts.** The
  inbound ports speak the external system's shape
  — its field names, its material codes, its
  kilotonnes — and are conformance-checked as a
  batch before anything is translated: a contract
  violation quarantines the batch whole, with the
  violations named, and nothing lands anywhere.
  A conforming batch is translated at the border
  and lands through the data plane's connector
  path under the port's own registered feed, where
  row-level fact discipline applies as it does to
  every feed. The outbound ports strike feed
  artefacts — rows derived from artefacts alone,
  with a checksum the verifier recomputes — for
  the brief and alert families. Shapes only: no
  vendor is named, and no system here claims to
  be one.
"""

from __future__ import annotations

import hashlib
import hmac
import json

RULES_VERSION = "2026.10.1"

# -- webhook events ---------------------------------------------------------
EVENT_PRICE_ALERT = "price_alert"
EVENT_GAP_BAND = "gap_band"
EVENT_BRIEF_PUBLISHED = "brief_published"
EVENTS = (EVENT_PRICE_ALERT, EVENT_GAP_BAND,
          EVENT_BRIEF_PUBLISHED)

# Webhook control acts: a subscription is active
# unless its latest control act at the trigger's
# date disables it.
ACT_DISABLE = "disable"
ACT_ENABLE = "enable"
CONTROL_ACTS = (ACT_DISABLE, ACT_ENABLE)

# -- token reads --------------------------------------------------------------
KIND_ALERT = "alert"
KIND_GAP = "gap"
KIND_BRIEF = "brief"
READ_KINDS = (KIND_ALERT, KIND_GAP, KIND_BRIEF)

SCOPE_ALERTS = "alerts"
SCOPE_GAPS = "gaps"
SCOPE_BRIEFS = "briefs"
SCOPES = (SCOPE_ALERTS, SCOPE_GAPS, SCOPE_BRIEFS)
KIND_SCOPE = {KIND_ALERT: SCOPE_ALERTS,
              KIND_GAP: SCOPE_GAPS,
              KIND_BRIEF: SCOPE_BRIEFS}

DECISION_ALLOWED = "allowed"
DECISION_REFUSED = "refused"

ACT_REVOKE = "revoke"


def canonical(payload) -> bytes:
    """The one canonical byte form a signature or a
    checksum is ever computed over."""
    return json.dumps(
        payload, sort_keys=True,
        separators=(",", ":")).encode()


def sign(secret: str, payload) -> str:
    """A delivery's signature: HMAC-SHA256 over the
    canonical payload, keyed by the subscription's
    secret."""
    return hmac.new(
        secret.encode(), canonical(payload),
        hashlib.sha256).hexdigest()


def secret_hash(secret: str) -> str:
    """What the store keeps of a token: its SHA-256.
    The token itself is never stored, anywhere."""
    return hashlib.sha256(secret.encode()).hexdigest()


def checksum(rows) -> str:
    return hashlib.sha256(canonical(rows)).hexdigest()


# -- exchange ports -----------------------------------------------------------
PORT_PRODUCTION_IN = "erp_production_in"
PORT_DISPATCH_IN = "erp_dispatch_in"
PORT_BRIEF_FEED_OUT = "crm_brief_feed"
PORT_ALERT_FEED_OUT = "crm_alert_feed"
INBOUND_PORTS = (PORT_PRODUCTION_IN, PORT_DISPATCH_IN)
OUTBOUND_PORTS = (PORT_BRIEF_FEED_OUT, PORT_ALERT_FEED_OUT)
PORTS = INBOUND_PORTS + OUTBOUND_PORTS

# The material codes the external system speaks,
# mapped to the products this system tracks. A code
# outside the map violates the contract.
MATERIAL_MAP = {
    "ERP-UREA": "UREA",
    "ERP-DAP": "DAP",
    "ERP-NPK102626": "NPK_10_26_26",
    "ERP-MOP": "MOP",
    "ERP-GLYPH": "GLYPHOSATE",
    "ERP-CHLOR": "CHLORPYRIFOS",
}

# The ports' quantities arrive in kilotonnes and
# land in tonnes: the translation states its unit.
QTY_FACTOR_TO_TONNES = 1000.0

# The feeds the inbound ports land through: each
# port's own registered source entry for the data
# plane, in the ingest registry's shape. The
# exchange ports keep their registry here, beside
# their contracts — the ingest registry (and the
# monitoring board that folds it) is unchanged.
PORT_SOURCES = {
    PORT_PRODUCTION_IN: {
        "fact_class": "supply_facts",
        "provenance_source": "erp_production_returns",
        "cadence": "monthly",
        "owner": "supply desk",
        "freshness_days": 45,
        "description": "Production plan and actual "
                       "returns arriving through the "
                       "ERP exchange port",
    },
    PORT_DISPATCH_IN: {
        "fact_class": "season_actuals",
        "provenance_source": "erp_dispatch_returns",
        "cadence": "season-close",
        "owner": "supply desk",
        "freshness_days": 370,
        "description": "Dispatch actuals arriving "
                       "through the ERP exchange port",
    },
}

# The contract each inbound port states, in the
# external shape: the fields a row must carry, the
# fields it may carry, and nothing else. Provenance
# (source, as_of) is part of every contract — a row
# without it violates the contract, as it would be
# refused at the data plane's own port.
PORT_CONTRACTS = {
    PORT_PRODUCTION_IN: {
        "required": ["material_code", "period",
                     "planned_qty_kt", "actual_qty_kt",
                     "source", "as_of"],
        "quantities": ["planned_qty_kt", "actual_qty_kt"],
        "period_fields": ["period"],
    },
    PORT_DISPATCH_IN: {
        "required": ["district_code", "crop_year",
                     "season", "material_code",
                     "dispatched_qty_kt",
                     "source", "as_of"],
        "quantities": ["dispatched_qty_kt"],
        "period_fields": [],
    },
}

# -- contract violations ------------------------------------------------------
V_MISSING_FIELD = "missing_field"
V_UNKNOWN_FIELD = "unknown_field"
V_UNKNOWN_MATERIAL = "unknown_material"
V_NEGATIVE_QUANTITY = "negative_quantity"
V_MALFORMED_PERIOD = "malformed_period"
V_MALFORMED_ROW = "malformed_row"
V_EMPTY_BATCH = "empty_batch"
V_SOURCE_MISMATCH = "source_mismatch"
VIOLATIONS = (V_MISSING_FIELD, V_UNKNOWN_FIELD,
              V_UNKNOWN_MATERIAL, V_NEGATIVE_QUANTITY,
              V_MALFORMED_PERIOD, V_MALFORMED_ROW,
              V_EMPTY_BATCH, V_SOURCE_MISMATCH)

OUTCOME_LANDED = "landed"
OUTCOME_QUARANTINED_WHOLE = "quarantined_whole"
