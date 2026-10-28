"""The scenario rule pack — versioned data for scenario
forks & planning options (R9, roadmap F21-PO4 + F21-PO2).

Everything a scenario may do traces to a rule stated here:
the bounded lever catalogue (which levers exist, which fork
kind each applies to, the bounds a value must sit inside),
the wording a gap uses when a request names something the
engines cannot move, and the stated criteria a planning
comparison ranks by. The pack is data with a version, not
scattered constants: a fork names the pack version it was
built under, and the verifiers re-perform the fork and the
comparison from the same pack, so a catalogue change is a
new pack version and old forks stay reproducible under
theirs.

The disciplines the pack states once, for every scenario:

- **Levers are bounded, never improvised.** A lever value
  outside its stated bound is refused with the bound named.
  A lever that applies to one fork kind is refused on the
  other — there is no silent reinterpretation.
- **Forks run through the engines, never beside them.** A
  fork is the base artefact's engine (the R2 demand engine,
  the R4 projection machinery) re-run over a stated view of
  the facts with the levers applied. There is no second
  calculator for scenario numbers.
- **Hypotheticals stay hypothetical.** A fork is a scenario
  by construction: it lives only in the scenario tables,
  and no head view (estimate, gap, watch board, policy
  impact, dashboard of record) ever reads it. A dashboard
  may render a fork only when the question names the
  scenario, and then every figure is badged as one.
- **Policy events carry no numeric transmission.** The R5
  registry states a policy event's direction and driver as
  data, and its impact note is a scope query — no pack in
  this system states a numeric transmission from a policy
  event into demand or supply. A request to apply or remove
  a policy event as a lever is therefore a named gap, not
  an invented elasticity: the gap states the event's
  recorded effect and what a transmission rule would need.
- **Options rank by stated criteria only.** A planning
  comparison ranks its rows by the criteria below, in
  order, with every criterion value on the row's face. No
  unexplained "best" exists anywhere in the artefact.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- fork kinds -----------------------------------------------------------
# A scenario forks one head artefact of one of these kinds.

KIND_DEMAND = "demand_estimate"
KIND_PROJECTION = "supply_projection"
FORK_KINDS = (KIND_DEMAND, KIND_PROJECTION)

SCOPE_KEYS = {
    KIND_DEMAND: ("district_id", "product", "crop_year", "season"),
    KIND_PROJECTION: ("product", "crop_year", "season"),
}

# -- the lever catalogue ----------------------------------------------------
# lever -> the fork kinds it applies to, the engine driver or
# component it moves, and its stated bound. A value must sit
# inside [min, max] and (unless zero is meaningful) be
# non-zero: a lever that moves nothing is refused, not stored
# as a fork of nothing.

LEVER_CATALOGUE = {
    "monsoon_deviation_shift": {
        "applies_to": (KIND_DEMAND,),
        "driver": "monsoon_deviation",
        "unit": "percentage points of monsoon deviation",
        "min": -30.0,
        "max": 30.0,
        "zero_allowed": False,
        "statement": (
            "shift the district-season's recorded monsoon "
            "deviation by the stated points; the demand "
            "engine's own banding turns the shifted deviation "
            "into the fork's monsoon factor"),
    },
    "price_level_shift_pct": {
        "applies_to": (KIND_DEMAND,),
        "driver": "price_elasticity",
        "unit": "percent on the season-window price level",
        "min": -50.0,
        "max": 50.0,
        "zero_allowed": False,
        "statement": (
            "shift the product's recorded prices inside the "
            "estimate's current season window by the stated "
            "percent; the prior window is untouched, so the "
            "engine's own elasticity rule prices the move"),
    },
    "price_elasticity_override": {
        "applies_to": (KIND_DEMAND,),
        "driver": "price_elasticity",
        "unit": "price elasticity of demand",
        "min": -1.0,
        "max": 0.0,
        "zero_allowed": True,
        "statement": (
            "replace the demand pack's stated elasticity for "
            "the product with the stated value, inside the "
            "engine's price line — the base elasticity is "
            "recorded on the fork's line inputs"),
    },
    "import_arrival_shift_months": {
        "applies_to": (KIND_PROJECTION,),
        "driver": "import_arrivals",
        "unit": "whole months (negative advances, positive slips)",
        "min": -6,
        "max": 6,
        "zero_allowed": False,
        "whole": True,
        "statement": (
            "re-time a shipment scheduled in the base "
            "projection by whole months: the fork's view "
            "expects and lands it in the shifted month. The "
            "shifted arrival must stay after the projection's "
            "basis month — a fork re-times future arrivals, "
            "it does not rewrite the basis stock"),
    },
    "production_shortfall_pct": {
        "applies_to": (KIND_PROJECTION,),
        "driver": "domestic_production",
        "unit": "percent below plan across the projection horizon",
        "min": 0.0,
        "max": 50.0,
        "zero_allowed": False,
        "statement": (
            "scale the planned production the projection "
            "reads by the stated percent shortfall; actuals "
            "and the basis position are facts and never move"),
    },
}

LEVER_NAMES = tuple(LEVER_CATALOGUE)

# The drivers/components a fork's reconciliation attributes
# deltas to, per kind — the demand engine's line drivers and
# the projection's month components.
DEMAND_DRIVERS = (
    "base_area_rates", "soil_nutrient_status", "monsoon_deviation",
    "price_elasticity", "carry_in_stock",
)

# -- gap wording -----------------------------------------------------------
# The stated reason a scenario request becomes a named gap
# instead of a lever. Gaps ride on the fork artefact: the
# request part is named, never dropped, and no value is
# improvised for it.

GAP_POLICY_NO_TRANSMISSION = (
    "policy events carry no numeric transmission into the "
    "demand or supply engines in the current packs — the "
    "registry states an event's direction and driver and its "
    "impact note is a scope query, so applying or removing "
    "{event} as a lever would need a transmission rule stated "
    "in a pack before any figure could move; none is stated, "
    "so no figure moves for this part"
)
GAP_UNMAPPED_SEGMENT = (
    "this part of the request maps to no lever in the "
    "scenario catalogue ({levers}) — it is recorded as a gap "
    "and no value was improvised for it"
)
GAP_REFUSED_LEVER = (
    "the requested lever was refused: {reason} — it is "
    "recorded as a gap and no value was substituted"
)

# -- ranking criteria -------------------------------------------------------
# The stated order a planning comparison ranks by, per fork
# kind: (criterion, direction, what the criterion means).
# Every criterion's value rides on the row; the final
# artefact-id criterion makes the order total and
# deterministic — a tie is broken by identity, never by
# arrival order or a hidden preference.

RANKING_CRITERIA = {
    KIND_DEMAND: (
        ("total_tonnes", "desc",
         "plan against the highest stated demand first"),
        ("complete_first", "asc",
         "a complete estimate ranks before a partial one at "
         "equal tonnage — its drivers all spoke"),
        ("lever_count", "asc",
         "at equal standing, the view that assumes less "
         "ranks first"),
        ("artefact_id", "asc", "deterministic tie-break"),
    ),
    KIND_PROJECTION: (
        ("closing_tonnes", "desc",
         "the season ends with the most stock first"),
        ("min_monthly_closing", "desc",
         "at equal endings, the path that never dips as low "
         "ranks first"),
        ("lever_count", "asc",
         "at equal standing, the view that assumes less "
         "ranks first"),
        ("artefact_id", "asc", "deterministic tie-break"),
    ),
}
