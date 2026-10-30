"""The monitoring rule pack — versioned data for the
per-run cost ledger, the source freshness board and
the reliability lines (R18, roadmap F21-AM2).

Three questions a desk head asks about the system
itself, none of which the market artefacts answer:
what did the model cost, is the data current, and
whose inputs can be trusted how far. This pack
states, as data with a version, how each is measured
— so a rate change or a definition change is a new
pack version, never a silent code edit, and every
board the layer strikes names the version it was
struck under.

- **Every model run is a record.** The model port has
  always returned its token counts; until this round
  nothing kept them. Now every call the service makes
  through its own port is recorded at the call as an
  insert-only run record: the purpose it served, the
  profile and model that answered, the tokens in and
  out, and the cost the pack's rates price them at.
  A call that fails raises through the port and
  records nothing — a failed call is not a run.
  Calls a caller makes through a port of their own
  (an eval harness, a test double) are that caller's
  records to keep; the ledger covers the service's
  own drafting paths, and says so.
- **Cost is exact integer arithmetic.** Rates are
  stated per profile in nano-USD per token (one
  nano-USD is a billionth of a dollar), so a run's
  cost is tokens times rate with no rounding
  anywhere: totals reconcile to the run records to
  the nano. The hosted profiles' rates are the
  pack's stated reference figures for reconciliation
  arithmetic — what a provider actually bills is the
  provider's invoice, never this ledger's claim.
  The offline profile reports zero tokens and is
  priced at zero: a deterministic local composer
  costs nothing and the ledger says exactly that.
- **Freshness judges fact currency per source.**
  For each registered source, the board states the
  newest fact date the source has landed by the
  board date and its age against the registry's
  freshness window: inside the window is `fresh`,
  past it is `stale`, and a source that has landed
  nothing is `never_loaded` — named as such, never
  read as zero or as current.
- **Reliability derives only from recorded acts
  and facts.** A source's line folds its batch
  reports: rows received, landed, duplicated,
  quarantined and refused, the quarantine share,
  and the corrections later recorded against its
  fact class. A reporter's line folds their landed
  reports, the review acts' outcomes (the one fold
  the field layer states), and their screening
  record. A rate with no decided cases behind it
  is stated as unmeasured, never as a number.
  Nothing in this layer moves a weight, a state or
  a standing — like the integrity board, it is
  evidence for a human, not a consequence.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- run purposes ---------------------------------------------------------------
# The drafting paths the service hands its own port
# to, named at the handoff. A run record carries
# exactly one of these; anything else is outside the
# pack's vocabulary and the verifier names it.
PURPOSE_OUTLOOK_NARRATIVE = "outlook_narrative"
PURPOSE_WEEKLY_BRIEF = "weekly_brief"
PURPOSE_DASHBOARD_PARSE = "dashboard_parse"
PURPOSE_SCENARIO_PARSE = "scenario_parse"
PURPOSES = (PURPOSE_OUTLOOK_NARRATIVE, PURPOSE_WEEKLY_BRIEF,
            PURPOSE_DASHBOARD_PARSE, PURPOSE_SCENARIO_PARSE)

# -- cost rates -------------------------------------------------------------------
# Nano-USD per token, per profile, as (input, output).
# Integers by design: cost arithmetic never rounds,
# so a board's totals are sums, not estimates. The
# hosted figures are reference rates stated by this
# pack for reconciliation — see the module docstring.
COST_RATES_NANO_PER_TOKEN = {
    "offline": (0, 0),
    "anthropic": (3000, 15000),
    "bedrock": (3000, 15000),
    "nim": (500, 1500),
}


def cost_nano_usd(profile: str, input_tokens: int,
                  output_tokens: int) -> int | None:
    """The pack's price of one run, or None when the
    profile carries no stated rate — an unrated
    profile's cost is unmeasured, never zero-filled."""
    rates = COST_RATES_NANO_PER_TOKEN.get(profile)
    if rates is None:
        return None
    return input_tokens * rates[0] + output_tokens * rates[1]


# -- freshness ---------------------------------------------------------------------
# The states a source's freshness line can carry,
# judged at the board date from the newest fact the
# source has landed and the registry's window.
STATE_FRESH = "fresh"
STATE_STALE = "stale"
STATE_NEVER_LOADED = "never_loaded"
FRESHNESS_STATES = (STATE_FRESH, STATE_STALE,
                    STATE_NEVER_LOADED)

# The note a reporter's line carries when no review
# act has decided any of their reports: the rate is
# unmeasured, and the line says so instead of
# printing one.
NO_DECIDED_NOTE = "no_decided_reports"
