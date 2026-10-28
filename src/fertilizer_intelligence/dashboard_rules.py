"""The dashboard rule pack — versioned data for the
ask-in-plain-language assembler (R8, roadmap F21-DR1).

Everything the assembler may do traces to a rule stated
here: the governed panel vocabulary and the scope each panel
kind binds, the defaults a question may fall back to when it
names no season, the role default dashboards stated as data,
and the wording a gap panel uses to name the data it would
need. The pack is data with a version, not scattered
constants: a spec names the pack version it was parsed
under, and the verifiers re-perform the parse and the
assembly from the same pack, so a rule change is a new pack
version and old artefacts stay reproducible under theirs.

The disciplines the pack states once, for every dashboard:

- **Panels are governed, never improvised.** A question
  becomes a dashboard spec: a selection of panels from the
  stated vocabulary, each bound to one stated artefact query
  (engine + scope + as-of). There is no panel kind outside
  the vocabulary, and no scope key outside the kind's stated
  set — a proposal (from the grammar or from a model
  profile) that does not fit is refused, and the refusal is
  recorded on the spec and rendered as a gap.
- **Unanswerable parts are gaps, not silence or invention.**
  A question part that maps to no artefact family becomes a
  gap panel naming what data would be needed. A gap panel
  carries no figures — ever. What the system cannot compute,
  it says it cannot compute.
- **Scope is inherited, defaults are stated.** A follow-up
  clause ("and what's our share?") inherits the district,
  product, season and crop year of the clauses before it.
  When no clause names a season or crop year, the pack's
  stated defaults apply (the latest tracked crop year, the
  kharif season) and the defaulting is recorded in the
  parse provenance — never silent.
- **Every figure carries its lineage.** A rendered figure
  names the artefact it came from, that artefact's as-of,
  and its badges (partial, stale, review state). A figure
  without lineage is a defect the eval gate counts.
- **Scenarios render only when named (R9).** A dashboard
  of record carries no hypothetical figures. A scenario
  panel exists only when the question names a stored fork,
  and every figure on it is badged as a scenario — an
  unbadged scenario figure is a defect the verifier names.
- **Role defaults are specs, not code.** The dashboards a
  regional head, a national planner and leadership open by
  default are stated below as panel lists and are built
  through the same spec machinery as an asked question —
  there is no per-role rendering branch.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- the governed panel vocabulary -------------------------------------
# kind -> the scope keys the kind binds (all required unless
# listed in OPTIONAL_SCOPE), and the engine that answers it.

PANEL_KINDS = (
    "demand_estimate",
    "season_outlook",
    "price_watch",
    "watch_board",
    "supply_position",
    "supply_gap",
    "policy_events",
    "market_share",
    "share_movement",
    "field_signals",
    "scenario",
    "gap",
)

PANEL_SCOPE = {
    "demand_estimate": ("district_id", "product", "crop_year", "season"),
    "season_outlook": ("crop_year", "season"),
    "price_watch": ("series_kind", "item"),
    "watch_board": (),
    "supply_position": ("product", "month"),
    "supply_gap": ("product", "crop_year", "season"),
    "policy_events": (),
    "market_share": ("district_id", "product", "crop_year", "season"),
    "share_movement": ("district_id", "product", "season"),
    "field_signals": ("district_id", "product", "crop_year", "season"),
    "scenario": ("fork_id",),
    "gap": ("subject", "needed_data"),
}

OPTIONAL_SCOPE = {
    "policy_events": ("product",),
}

PANEL_ENGINE = {
    "demand_estimate": "demand engine (R2)",
    "season_outlook": "demand engine outlook (R2)",
    "price_watch": "price watch (R3)",
    "watch_board": "price watch board (R3)",
    "supply_position": "supply tracker (R4)",
    "supply_gap": "supply tracker (R4)",
    "policy_events": "policy registry (R5)",
    "market_share": "share engine (R6)",
    "share_movement": "share engine (R6)",
    "field_signals": "field-signal assessment (R7)",
    "scenario": "scenario forks (R9)",
    "gap": "none — no governed engine answers this part",
}

# -- stated defaults -----------------------------------------------------
# When a question names no crop year anywhere, the parse
# falls back to the latest tracked crop year; when it names
# no season anywhere, to kharif. Both defaults are recorded
# in the spec's parse provenance.

DEFAULT_SEASON = "kharif"

# -- gap wording ---------------------------------------------------------
# The stated first sentence of a gap's needed-data statement
# per cause; the parser appends the specifics it found
# (unknown district, crop named instead of a product, the
# missing scope entity).

GAP_NO_FAMILY = (
    "no governed artefact family answers this part of the question — "
    "it would need a new computed view over data the system does not hold"
)
GAP_MONSOON_FAMILY = (
    "a standalone monsoon outlook is not a computed view in this "
    "system — monsoon deviation is held as a demand driver per "
    "tracked district-season and enters the demand estimate, but no "
    "monsoon forecast artefact exists to render"
)
GAP_MISSING_SCOPE = (
    "this panel needs {missing} — the question does not name it and "
    "no earlier part of the question supplies it"
)
GAP_UNKNOWN_DISTRICT = (
    "district coverage: {name} is not one of the tracked districts "
    "({tracked}) — a district record and its area, monsoon, soil and "
    "consumption facts would be needed before any figure could be "
    "computed for it"
)
GAP_CROP_NOT_PRODUCT = (
    "{crop} is a crop, not a tracked product — demand is estimated "
    "per product ({products}); a crop-level view would need the "
    "application-rate table extended to state a crop aggregate"
)
GAP_REFUSED_PROPOSAL = (
    "the proposed panel was refused: {reason} — no governed panel "
    "was substituted and no figure was invented for this part"
)
GAP_SCENARIO_UNNAMED = (
    "a scenario renders on a dashboard only when the question names "
    "a stored fork — hypothetical figures are never carried unnamed "
    "on a dashboard of record. Stored scenarios: {names}. Naming one "
    "(by its name or its SCN id) renders it, badged as a scenario on "
    "every figure"
)

# -- role default dashboards, stated as data -----------------------------
# role -> (stated question label, [(panel kind, scope), ...]).
# The scope token "current" for crop_year resolves to the
# latest tracked crop year when the default spec is built.

ROLE_DEFAULTS = {
    "regional_head": (
        "Regional head — default dashboard",
        [
            ("watch_board", {}),
            ("supply_gap", {"product": "DAP", "crop_year": "current",
                            "season": "kharif"}),
            ("supply_gap", {"product": "UREA", "crop_year": "current",
                            "season": "kharif"}),
            ("supply_gap", {"product": "MOP", "crop_year": "current",
                            "season": "kharif"}),
            ("market_share", {"district_id": "DST-LUD", "product": "DAP",
                              "crop_year": "current", "season": "kharif"}),
        ],
    ),
    "national_planner": (
        "National planner — default dashboard",
        [
            ("season_outlook", {"crop_year": "current", "season": "kharif"}),
            ("supply_gap", {"product": "DAP", "crop_year": "current",
                            "season": "kharif"}),
            ("supply_gap", {"product": "NPK_10_26_26",
                            "crop_year": "current", "season": "kharif"}),
            ("policy_events", {}),
            ("watch_board", {}),
        ],
    ),
    "leadership": (
        "Leadership — default dashboard",
        [
            ("season_outlook", {"crop_year": "current", "season": "kharif"}),
            ("season_outlook", {"crop_year": "current", "season": "rabi"}),
            ("watch_board", {}),
            ("share_movement", {"district_id": "DST-LUD", "product": "DAP",
                                "season": "kharif"}),
        ],
    ),
}

ROLES = tuple(ROLE_DEFAULTS)
