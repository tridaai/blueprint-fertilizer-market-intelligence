"""Scenario forks & planning options (R9, roadmap
F21-PO4 + F21-PO2).

Rounds 2–7 built the views of record: demand estimates,
supply positions, gaps and projections, shares, field
assessments. This round builds the planning layer over
them — what a planner actually asks the week before a
season: *what if the monsoon comes in weaker, what if the
October vessel slips two months, what if production runs
short of plan?* — and gives the answers the same artefact
discipline as everything else:

- A **scenario fork** is a pinned fork of one head
  artefact (a demand estimate or a supply projection).
  Its levers come from the scenario pack's bounded
  catalogue and are applied by re-running the base
  artefact's OWN engine over a stated view of the facts
  (shifted monsoon deviation, shifted window prices, a
  re-timed arrival, production at a stated shortfall of
  plan) — never a parallel calculator. The fork's
  contribution lines (demand) or month rows (projection)
  reconcile against the base's line by line: the fork
  total minus the base total is exactly the sum of the
  lever-attributed deltas. The base artefact is never
  mutated; forks link to it.
- Scenario requests arrive as **plain language** through
  the model port — the offline deterministic grammar by
  default, the same discipline as the R8 dashboard parse.
  A part that maps to no lever becomes a **named gap** on
  the fork artefact: never silently dropped, never an
  improvised value. A policy event named in a request is
  a gap by the pack's stated rule — no pack states a
  numeric transmission from policy into the engines, so
  no figure moves for it.
- A **planning-options** artefact compares the base
  against one or more of its forks side by side: totals,
  the season gap reading struck by the R4 gap machinery
  over each option's own arrival view, each figure
  carrying its lineage to the artefact it came from.
  Rows rank ONLY by the pack's stated criteria, with the
  criterion values on the row. An option is **adopted**
  only by a named planner's insert-only act; adoption
  supersedes by link and edits nothing — it records
  which fork the plan follows.
- Forks are **hypothetical by construction**. They live
  only in the scenario tables; no head read in this
  system (estimate, gap, watch board, policy impact,
  dashboard of record) ever joins them. A dashboard may
  render a fork only when the question names the
  scenario, and then every figure is badged as one
  (the R8 dashboard layer enforces that).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from . import demand as demand_engine
from . import demand_rules
from . import scenario_rules as pack
from . import supply as supply_engine
from .generator import CROP_YEARS, PRODUCTS

TONNE_TOL = 0.002  # the engines' rounding discipline


class ScenarioRefused(ValueError):
    """A plain-language scenario request that cannot
    produce a fork at all — no resolvable base, or no
    lever that could be applied. Fail-closed: no fork,
    no fallback guess; the reasons ride on the error."""


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def _shift_month(month: str, delta: int) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def slugify(name: str) -> str:
    """The name a scenario is referred by: lowercased,
    runs of non-alphanumerics collapsed to single hyphens.
    Names are how dashboards and planners refer to a
    scenario, so a name identifies exactly one fork."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------


class ScenarioFork(BaseModel):
    fork_id: str
    fingerprint: str
    name: str | None = None
    kind: str  # demand_estimate | supply_projection
    scope: dict[str, Any]
    base_artefact_id: str
    base_total_tonnes: float
    fork_total_tonnes: float
    delta_tonnes: float
    status: str  # the fork result's own status, from its engine
    hypothetical: bool = True
    created_by: str
    as_of: str  # the base artefact's strike date — a fork is pinned to it
    levers: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    parse: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    reconciliation: list[dict[str, Any]] = Field(default_factory=list)
    rules_version: str
    engine_rules_version: str
    fact_fingerprint: str  # the fork result's own engine fingerprint


class PlanningOptions(BaseModel):
    options_id: str
    fingerprint: str
    name: str | None = None
    kind: str
    scope: dict[str, Any]
    base_artefact_id: str
    fork_ids: list[str]
    created_by: str
    as_of: str
    criteria: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    rules_version: str


class PlanningAdoption(BaseModel):
    adoption_id: str
    options_id: str
    fork_id: str | None = None  # None = the base view is adopted
    adopted_by: str
    note: str | None = None
    as_of: str
    supersedes: str | None = None


# ---------------------------------------------------------------------------
# The fork view: the engines' facts, with the levers applied
# ---------------------------------------------------------------------------


class ForkStoreView:
    """A read-through view over the real store carrying
    exactly the lever substitutions — and nothing else.
    The demand engine and the projection machinery run
    over this view unmodified, so a fork is computed by
    the same code as its base; the real store is never
    written, and its facts never move. Substitutions:

    - ``monsoon``: one district-season's deviation,
      shifted by the lever's points;
    - ``price``: one product's price points inside the
      estimate's current season window, shifted by pct;
    - ``imports``: named shipments expected and landed in
      their shifted month;
    - ``production``: one product's planned tonnes,
      scaled by the shortfall.
    """

    def __init__(self, store, *, monsoon=None, price=None,
                 imports=None, production=None):
        self._store = store
        self._monsoon = monsoon
        self._price = price
        self._imports = dict(imports or {})
        self._production = production

    def __getattr__(self, name):
        return getattr(self._store, name)

    def monsoon_facts(self, district_id=None, crop_year=None, season=None):
        rows = self._store.monsoon_facts(district_id, crop_year, season)
        cfg = self._monsoon
        if not cfg:
            return rows
        out = []
        for row in rows:
            row = dict(row)
            if (row["district_id"] == cfg["district_id"]
                    and row["crop_year"] == cfg["crop_year"]
                    and row["season"] == cfg["season"]):
                row["deviation_pct"] = round(
                    row["deviation_pct"] + cfg["shift_points"], 2)
            out.append(row)
        return out

    def price_points(self, series_kind=None, item=None):
        rows = self._store.price_points(series_kind, item)
        cfg = self._price
        if not cfg:
            return rows
        out = []
        for row in rows:
            row = dict(row)
            if (row["series_kind"] == "product"
                    and row["item"] == cfg["product"]
                    and row["month"] in cfg["months"]):
                row["price"] = round(
                    row["price"] * (1.0 + cfg["pct"] / 100.0), 2)
            out.append(row)
        return out

    def import_arrivals(self, product=None):
        rows = self._store.import_arrivals(product)
        if not self._imports:
            return rows
        out = []
        for row in rows:
            row = dict(row)
            shift = self._imports.get(row["shipment_id"])
            if shift:
                row["expected_month"] = _shift_month(
                    row["expected_month"], shift)
                row["arrived_month"] = _shift_month(
                    row["arrived_month"], shift)
            out.append(row)
        return out

    def supply_facts(self, product=None):
        rows = self._store.supply_facts(product)
        cfg = self._production
        if not cfg:
            return rows
        out = []
        for row in rows:
            row = dict(row)
            if row["product"] == cfg["product"]:
                row["planned_tonnes"] = round(
                    row["planned_tonnes"] * (1.0 - cfg["pct"] / 100.0), 3)
            out.append(row)
        return out


def view_from_levers(store, levers: list[dict]):
    """Rebuild the exact view a fork's lever records
    describe, plus the elasticity override if one is among
    them — creation and verification build the view the
    same way, from the artefact alone."""
    monsoon = price = production = None
    imports: dict[str, int] = {}
    elasticity = None
    for record in levers:
        # Every record's parameters enter the view, applied
        # or not: `applied` is an outcome the engines derive
        # (a lever aimed at a missing driver line moved no
        # figure), not an input — building the view from the
        # records alone keeps creation and verification on
        # the same view by construction.
        lever = record["lever"]
        if lever == "monsoon_deviation_shift":
            target = record["target"]
            monsoon = {
                "district_id": target["district_id"],
                "crop_year": target["crop_year"],
                "season": target["season"],
                "shift_points": record["value"],
            }
        elif lever == "price_level_shift_pct":
            target = record["target"]
            price = {
                "product": target["product"],
                "months": list(target["months"]),
                "pct": record["value"],
            }
        elif lever == "import_arrival_shift_months":
            imports[record["target"]["shipment_id"]] = int(record["value"])
        elif lever == "production_shortfall_pct":
            production = {
                "product": record["target"]["product"],
                "pct": record["value"],
            }
        elif lever == "price_elasticity_override":
            elasticity = record["value"]
    view = ForkStoreView(store, monsoon=monsoon, price=price,
                         imports=imports, production=production)
    return view, elasticity


# ---------------------------------------------------------------------------
# Lever resolution: requested levers -> canonical applied records
# ---------------------------------------------------------------------------


def _lever_error(lever: str, reason: str) -> ValueError:
    return ValueError(f"lever {lever!r} refused: {reason}")


def _check_bounds(lever: str, value: Any) -> float:
    spec = pack.LEVER_CATALOGUE[lever]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _lever_error(lever, f"a numeric value is required, got {value!r}")
    value = float(value)
    if spec.get("whole") and value != int(value):
        raise _lever_error(
            lever, f"the value must be whole {spec['unit']} — got {value}")
    if value < spec["min"] or value > spec["max"]:
        raise _lever_error(
            lever,
            f"value {value:g} is outside the catalogue bound "
            f"[{spec['min']:g}, {spec['max']:g}] ({spec['unit']})")
    if value == 0 and not spec["zero_allowed"]:
        raise _lever_error(
            lever, "a value of 0 moves nothing — a lever must move its input")
    return value


def resolve_levers(store, kind: str, scope: dict, base: dict,
                   lever_specs: list[dict],
                   on_error: str = "raise") -> tuple[list[dict], list[dict]]:
    """Validate requested levers against the catalogue and
    the base artefact, and canonicalize them into applied
    lever records carrying their base values and exact
    parameters. With ``on_error="raise"`` the first refusal
    raises naming the bound or mismatch; with ``"collect"``
    (the plain-language path) refusals come back as named
    gaps and the valid levers proceed."""
    records: list[dict] = []
    gaps: list[dict] = []
    seen: set[str] = set()

    def refuse(lever: str, reason: str, subject: str) -> None:
        error = _lever_error(lever, reason)
        if on_error == "raise":
            raise error
        gaps.append({
            "subject": subject,
            "needed": pack.GAP_REFUSED_LEVER.format(reason=str(error)),
            "rule": "scenario:refused_lever",
        })

    for spec_in in lever_specs:
        lever = spec_in.get("lever") if isinstance(spec_in, dict) else None
        subject = str(spec_in)[:96]
        if lever is None:
            refuse("(unnamed)", "a lever entry must name its lever", subject)
            continue
        if lever not in pack.LEVER_CATALOGUE:
            if "policy" in lever:
                reason = (
                    "no pack states a numeric transmission from a "
                    "policy event into the engines — a policy lever "
                    "cannot be applied (see the scenario pack)")
            else:
                reason = (
                    f"the scenario catalogue states: "
                    f"{', '.join(pack.LEVER_NAMES)}")
            refuse(lever, reason, subject)
            continue
        spec = pack.LEVER_CATALOGUE[lever]
        if kind not in spec["applies_to"]:
            refuse(lever,
                   f"it applies to {'/'.join(spec['applies_to'])} forks, "
                   f"not to a {kind} fork", subject)
            continue
        raw_value = spec_in.get("value")
        if lever == "monsoon_deviation_shift" and raw_value is None \
                and spec_in.get("target_deviation") is not None:
            # "A monsoon deviation of -5" names the target,
            # not the shift: the shift is the distance from
            # the recorded fact, derived here where the fact
            # is in reach.
            fact_rows = store.monsoon_facts(
                scope["district_id"], scope["crop_year"], scope["season"])
            if not fact_rows:
                refuse(lever,
                       "no monsoon fact is recorded for this "
                       "district-season — a target deviation "
                       "cannot be turned into a shift", subject)
                continue
            raw_value = round(
                float(spec_in["target_deviation"])
                - fact_rows[0]["deviation_pct"], 2)
        try:
            value = _check_bounds(lever, raw_value)
        except ValueError as exc:
            if on_error == "raise":
                raise
            gaps.append({
                "subject": subject,
                "needed": pack.GAP_REFUSED_LEVER.format(reason=str(exc)),
                "rule": "scenario:refused_lever",
            })
            continue

        if lever == "import_arrival_shift_months":
            months = int(value)
            shipment_ids = []
            if spec_in.get("shipment_id"):
                shipment_ids = [spec_in["shipment_id"]]
            elif spec_in.get("shipment_ids"):
                shipment_ids = list(spec_in["shipment_ids"])
            elif spec_in.get("expected_month_name"):
                month_no = _MONTH_NUMBERS[spec_in["expected_month_name"]]
                shipment_ids = [
                    s["shipment_id"]
                    for s in base["assumption_set"]["scheduled_shipments"]
                    if int(s["expected_month"][5:7]) == month_no
                ]
                if not shipment_ids:
                    refuse(lever,
                           f"no shipment scheduled in the base "
                           f"projection is expected in "
                           f"{spec_in['expected_month_name']}", subject)
                    continue
            else:
                shipment_ids = [
                    s["shipment_id"]
                    for s in base["assumption_set"]["scheduled_shipments"]
                ]
                if not shipment_ids:
                    refuse(lever,
                           "the base projection schedules no shipments "
                           "to re-time", subject)
                    continue
            scheduled = {
                s["shipment_id"]: s
                for s in base["assumption_set"]["scheduled_shipments"]
            }
            arrivals = {a["shipment_id"]: a
                        for a in store.import_arrivals(scope["product"])}
            for shipment_id in shipment_ids:
                key = f"{lever}:{shipment_id}"
                if key in seen:
                    refuse(lever, f"shipment {shipment_id} is re-timed "
                                  "twice in one request", subject)
                    continue
                seen.add(key)
                if shipment_id not in scheduled:
                    refuse(lever,
                           f"shipment {shipment_id} is not scheduled in "
                           f"the base projection (scheduled: "
                           f"{', '.join(sorted(scheduled)) or 'none'}) — "
                           "only a scheduled arrival can be re-timed",
                           subject)
                    continue
                fact = arrivals[shipment_id]
                fork_expected = _shift_month(fact["expected_month"], months)
                fork_arrived = _shift_month(fact["arrived_month"], months)
                if fork_expected <= base["basis_month"] or \
                        fork_arrived <= base["basis_month"]:
                    refuse(lever,
                           f"shifting {shipment_id} by {months:+d} months "
                           f"lands it in {fork_expected} (arrival "
                           f"{fork_arrived}), at or before the "
                           f"projection's basis month "
                           f"{base['basis_month']} — a fork re-times "
                           "future arrivals, it does not rewrite the "
                           "basis stock", subject)
                    continue
                records.append({
                    "lever": lever, "value": months,
                    "driver": spec["driver"],
                    "target": {"shipment_id": shipment_id},
                    "base_value": {
                        "expected_month": fact["expected_month"],
                        "arrived_month": fact["arrived_month"],
                    },
                    "fork_value": {
                        "expected_month": fork_expected,
                        "arrived_month": fork_arrived,
                    },
                    "quantity_tonnes": fact["quantity_tonnes"],
                    "applied": True,
                })
            continue

        if lever in seen:
            refuse(lever, "the lever is stated twice in one request",
                   subject)
            continue
        seen.add(lever)

        if lever == "monsoon_deviation_shift":
            rows = store.monsoon_facts(
                scope["district_id"], scope["crop_year"], scope["season"])
            if not rows:
                refuse(lever,
                       "no monsoon fact is recorded for this "
                       "district-season — there is no deviation for "
                       "the lever to shift", subject)
                continue
            deviation = rows[0]["deviation_pct"]
            records.append({
                "lever": lever, "value": value,
                "driver": spec["driver"],
                "target": {
                    "district_id": scope["district_id"],
                    "crop_year": scope["crop_year"],
                    "season": scope["season"],
                },
                "base_value": deviation,
                "fork_value": round(deviation + value, 2),
                "applied": True,
            })
        elif lever == "price_level_shift_pct":
            months = demand_rules.season_price_window(
                scope["crop_year"], scope["season"])
            points = {p["month"] for p in store.price_points(
                "product", scope["product"])}
            present = [m for m in months if m in points]
            if not present:
                refuse(lever,
                       "no price points are recorded inside the "
                       "season window — there is no price level "
                       "for the lever to shift", subject)
                continue
            records.append({
                "lever": lever, "value": value,
                "driver": spec["driver"],
                "target": {"product": scope["product"],
                           "months": present},
                "applied": True,
            })
        elif lever == "price_elasticity_override":
            records.append({
                "lever": lever, "value": value,
                "driver": spec["driver"],
                "target": {"product": scope["product"]},
                "base_value": demand_rules.PRICE_ELASTICITY[scope["product"]],
                "applied": True,
            })
        elif lever == "production_shortfall_pct":
            records.append({
                "lever": lever, "value": value,
                "driver": spec["driver"],
                "target": {"product": scope["product"]},
                "applied": True,
            })
    if on_error == "collect":
        return records, gaps
    return records


_MONTH_NUMBERS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}


# ---------------------------------------------------------------------------
# Fork computation: the base artefact's engine over the fork view
# ---------------------------------------------------------------------------


def _mark_outcomes(records: list[dict], result_lines: list[dict],
                   kind: str) -> None:
    """State, on each lever record, whether its substitution
    reached an applied engine line — a lever aimed at a
    driver the base estimate carries as missing moved no
    figure, and the fork says so on the lever's face."""
    by_driver = ({line["driver"]: line for line in result_lines}
                 if kind == pack.KIND_DEMAND else {})
    for record in records:
        lever = record["lever"]
        if lever == "monsoon_deviation_shift":
            line = by_driver.get("monsoon_deviation")
            record["applied"] = bool(line and line["status"] == "applied")
            if not record["applied"]:
                record["reason"] = (
                    "the fork's monsoon line is "
                    f"{line['status'] if line else 'absent'} — there "
                    "is no deviation factor for the lever to move")
        elif lever in ("price_level_shift_pct", "price_elasticity_override"):
            line = by_driver.get("price_elasticity")
            record["applied"] = bool(line and line["status"] == "applied")
            if not record["applied"]:
                record["reason"] = (
                    "the fork's price line is "
                    f"{line['status'] if line else 'absent'} — there "
                    "is no price factor for the lever to move")
        elif lever == "production_shortfall_pct":
            record["applied"] = any(
                m["production_planned_tonnes"] is not None
                for m in result_lines)
            if not record["applied"]:
                record["reason"] = (
                    "no month in the projection horizon carries a "
                    "production plan — there is no plan for the "
                    "shortfall to scale")


def compute_demand_fork(store, base: dict, records: list[dict]):
    """Run the R2 demand engine over the fork view for the
    base estimate's cell. Returns (result payload,
    reconciliation, records) — the reconciliation is the
    per-driver statement: base delta, fork delta, and the
    lever-attributed difference, which sums exactly to the
    fork-minus-base total."""
    view, elasticity = view_from_levers(store, records)
    estimate = demand_engine.compute_estimate(
        view, base["district_id"], base["product"], base["crop_year"],
        base["season"], base["as_of"], elasticity_override=elasticity)
    result = estimate.model_dump()
    _mark_outcomes(records, result["contributions"], pack.KIND_DEMAND)
    base_lines = {line["driver"]: line for line in base["contributions"]}
    reconciliation = []
    for line in result["contributions"]:
        base_line = base_lines[line["driver"]]
        attributed = [r["lever"] for r in records
                      if r.get("driver") == line["driver"] and r["applied"]]
        reconciliation.append({
            "driver": line["driver"],
            "status_base": base_line["status"],
            "status_fork": line["status"],
            "base_factor": base_line["factor"],
            "fork_factor": line["factor"],
            "base_delta_tonnes": base_line["delta_tonnes"],
            "fork_delta_tonnes": line["delta_tonnes"],
            "lever_delta_tonnes": round(
                line["delta_tonnes"] - base_line["delta_tonnes"], 3),
            "attributed_levers": attributed,
        })
    return result, reconciliation


def compute_projection_fork(store, base: dict, records: list[dict]):
    """Run the R4 projection machinery over the fork view,
    standing on the REAL position chain (the basis is a
    fact). The reconciliation walks the horizon month by
    month: production delta, imports delta, closing delta
    — each month's closing delta is the previous month's
    plus its own component deltas, exactly."""
    view, _elasticity = view_from_levers(store, records)
    chain = supply_engine.compute_position_chain(
        store, base["product"], base["as_of"])
    projection = supply_engine.compute_projection(
        view, base["product"], base["crop_year"], base["season"],
        base["as_of"], chain)
    result = projection.model_dump()
    _mark_outcomes(records, result["months"], pack.KIND_PROJECTION)
    base_months = {m["month"]: m for m in base["months"]}
    reconciliation = []
    carried: set[str] = set()
    for month in result["months"]:
        base_month = base_months[month["month"]]
        production_delta = None
        if (month["production_planned_tonnes"] is not None
                and base_month["production_planned_tonnes"] is not None):
            production_delta = round(
                month["production_planned_tonnes"]
                - base_month["production_planned_tonnes"], 3)
        imports_delta = round(
            month["imports_scheduled_tonnes"]
            - base_month["imports_scheduled_tonnes"], 3)
        closing_delta = None
        if (month["closing_tonnes"] is not None
                and base_month["closing_tonnes"] is not None):
            closing_delta = round(
                month["closing_tonnes"] - base_month["closing_tonnes"], 3)
        attributed = set()
        if production_delta:
            attributed.update(
                r["lever"] for r in records
                if r["driver"] == "domestic_production" and r["applied"])
        if imports_delta:
            attributed.update(
                r["lever"] for r in records
                if r["driver"] == "import_arrivals" and r["applied"])
        carried |= attributed
        if closing_delta:
            attributed |= carried
        reconciliation.append({
            "month": month["month"],
            "projected": month["projected"],
            "base_production_tonnes": base_month["production_planned_tonnes"],
            "fork_production_tonnes": month["production_planned_tonnes"],
            "production_delta_tonnes": production_delta,
            "base_imports_tonnes": base_month["imports_scheduled_tonnes"],
            "fork_imports_tonnes": month["imports_scheduled_tonnes"],
            "imports_delta_tonnes": imports_delta,
            "base_closing_tonnes": base_month["closing_tonnes"],
            "fork_closing_tonnes": month["closing_tonnes"],
            "closing_delta_tonnes": closing_delta,
            "attributed_levers": sorted(attributed),
        })
    return result, reconciliation


def build_fork(kind: str, scope: dict, base: dict, records: list[dict],
               gaps: list[dict], parse: dict, created_by: str,
               name: str | None, result: dict,
               reconciliation: list[dict]) -> ScenarioFork:
    """Assemble the fork artefact from its computed result.
    Identity is content: kind, scope, base, the applied
    lever records, the gaps and the name."""
    if kind == pack.KIND_DEMAND:
        base_total = base["total_tonnes"]
        engine_version = result["rules_version"]
    else:
        base_total = base["closing_tonnes"]
        engine_version = result["rules_version"]
    fork_total = (result["total_tonnes"] if kind == pack.KIND_DEMAND
                  else result["closing_tonnes"])
    canonical_levers = [
        {k: r[k] for k in ("lever", "value", "target") if k in r}
        for r in records
    ]
    fingerprint = _fingerprint({
        "kind": kind, "scope": scope,
        "base": base["estimate_id"] if kind == pack.KIND_DEMAND
                else base["projection_id"],
        "levers": canonical_levers,
        "gaps": gaps, "name": name,
        "pack": pack.RULES_VERSION,
    })
    return ScenarioFork(
        fork_id=f"SCN-{fingerprint[:10]}", fingerprint=fingerprint,
        name=name, kind=kind, scope=scope,
        base_artefact_id=(base["estimate_id"] if kind == pack.KIND_DEMAND
                          else base["projection_id"]),
        base_total_tonnes=base_total, fork_total_tonnes=fork_total,
        delta_tonnes=round(fork_total - base_total, 3),
        status=result["status"], hypothetical=True,
        created_by=created_by, as_of=base["as_of"],
        levers=records, gaps=gaps, parse=parse, result=result,
        reconciliation=reconciliation,
        rules_version=pack.RULES_VERSION,
        engine_rules_version=engine_version,
        fact_fingerprint=result["fact_fingerprint"],
    )


# ---------------------------------------------------------------------------
# Planning options: the base and its forks, side by side, ranked by pack
# ---------------------------------------------------------------------------


def _fig(label: str, value: Any, unit: str, artefact_id: str) -> dict:
    return {"label": label, "value": value, "unit": unit,
            "artefact_id": artefact_id}


def _rank_rows(kind: str, rows: list[dict]) -> None:
    """Assign ranks by the pack's stated criteria, in
    order. The criteria are data; this is the one place
    they are interpreted, and the verifier re-runs it."""
    criteria = pack.RANKING_CRITERIA[kind]

    def key(row):
        parts = []
        for name, direction, _statement in criteria:
            value = row["criteria"][name]
            if name == "complete_first":
                parts.append(0 if value else 1)
            elif direction == "desc":
                parts.append(-(value if value is not None else -1e18))
            else:
                parts.append(value)
        return tuple(parts)

    for rank, row in enumerate(sorted(rows, key=key), start=1):
        row["rank"] = rank


def _gap_reading(store, kind_scope: dict, view, as_of: str,
                 chain, demand_tonnes: float, outlook_id: str) -> dict:
    """The season gap reading for one option, struck by the
    R4 gap machinery over the option's own arrival view at
    the options' as-of: the base row reads the facts, a
    fork row reads its forked arrivals — the same
    computation, never a second banding rule. The reading
    is a scenario figure: computed for the comparison,
    never stored as a gap of record."""
    gap = supply_engine.compute_gap(
        view, kind_scope["product"], kind_scope["crop_year"],
        kind_scope["season"], as_of, demand_tonnes, outlook_id, chain)
    return {
        "band": gap.band, "band_basis": gap.band_basis,
        "programme_cover_pct": gap.programme_cover_pct,
        "slipped_tonnes": gap.slipped_tonnes,
        "gap_tonnes": gap.gap_tonnes,
        "as_of": as_of,
    }


def compute_options(store, kind: str, scope: dict, base: dict,
                    forks: list[dict], created_by: str, as_of: str,
                    name: str | None) -> PlanningOptions:
    """Assemble the comparison. Every row's figures name
    the artefact they came from (the base artefact, or the
    fork); the ranking is the pack's stated criteria over
    the criterion values carried on each row."""
    rows: list[dict] = []
    if kind == pack.KIND_DEMAND:
        def demand_row(artefact_id: str, result: dict, is_base: bool,
                       lever_count: int) -> dict:
            figures = [
                _fig("Base demand (area × application rates)",
                     result["base_tonnes"], "t", artefact_id),
                _fig("Estimated demand", result["total_tonnes"], "t",
                     artefact_id),
                _fig("Change vs the base view",
                     round(result["total_tonnes"] - base["total_tonnes"], 3),
                     "t", artefact_id),
                _fig("Estimate status", result["status"], "status",
                     artefact_id),
            ]
            return {
                "artefact_id": artefact_id, "is_base": is_base,
                "figures": figures,
                "criteria": {
                    "total_tonnes": result["total_tonnes"],
                    "complete_first": result["status"] == "complete",
                    "lever_count": lever_count,
                    "artefact_id": artefact_id,
                },
                "rank": 0,
            }

        rows.append(demand_row(base["estimate_id"], base, True, 0))
        for fork in forks:
            rows.append(demand_row(
                fork["fork_id"], fork["result"], False,
                len([r for r in fork["levers"] if r["applied"]])))
    else:
        outlook = supply_engine.head_of(
            store.list_outlooks(scope["crop_year"], scope["season"]),
            "outlook_id")
        if outlook is None:
            raise ValueError(
                "no season outlook is stored for "
                f"{scope['crop_year']} {scope['season']} — the "
                "comparison's gap reading needs the outlook's "
                "demand rollup")
        demand_tonnes = outlook["product_rollups"][scope["product"]]
        chain = supply_engine.compute_position_chain(
            store, scope["product"], as_of)

        def projection_row(artefact_id: str, result: dict, view,
                           is_base: bool, lever_count: int) -> dict:
            projected = [m for m in result["months"] if m["projected"]
                         and m["closing_tonnes"] is not None]
            min_closing = (min(m["closing_tonnes"] for m in projected)
                           if projected else None)
            gap = _gap_reading(store, scope, view, as_of, chain,
                               demand_tonnes, outlook["outlook_id"])
            figures = [
                _fig("Opening stock", result["opening_tonnes"], "t",
                     artefact_id),
                _fig("Projected closing stock", result["closing_tonnes"],
                     "t", artefact_id),
                _fig("Change vs the base view",
                     round(result["closing_tonnes"]
                           - base["closing_tonnes"], 3), "t", artefact_id),
                _fig("Lowest monthly closing",
                     min_closing, "t", artefact_id),
                _fig("Scheduled imports over the horizon",
                     round(sum(m["imports_scheduled_tonnes"]
                               for m in result["months"]), 3),
                     "t", artefact_id),
                _fig("Gap band (gap machinery over this view)",
                     gap["band"], "band", artefact_id),
                _fig("Import programme cover", gap["programme_cover_pct"],
                     "%", artefact_id),
                _fig("Slipped tonnage in this view", gap["slipped_tonnes"],
                     "t", artefact_id),
            ]
            return {
                "artefact_id": artefact_id, "is_base": is_base,
                "figures": figures, "gap_reading": gap,
                "criteria": {
                    "closing_tonnes": result["closing_tonnes"],
                    "min_monthly_closing": min_closing,
                    "lever_count": lever_count,
                    "artefact_id": artefact_id,
                },
                "rank": 0,
            }

        rows.append(projection_row(
            base["projection_id"], base, store, True, 0))
        for fork in forks:
            view, _ = view_from_levers(store, fork["levers"])
            rows.append(projection_row(
                fork["fork_id"], fork["result"], view, False,
                len([r for r in fork["levers"] if r["applied"]])))

    _rank_rows(kind, rows)
    base_id = (base["estimate_id"] if kind == pack.KIND_DEMAND
               else base["projection_id"])
    fingerprint = _fingerprint({
        "kind": kind, "base": base_id,
        "forks": [f["fork_id"] for f in forks],
        "as_of": as_of, "name": name, "pack": pack.RULES_VERSION,
    })
    return PlanningOptions(
        options_id=f"OPT-{fingerprint[:10]}", fingerprint=fingerprint,
        name=name, kind=kind, scope=scope, base_artefact_id=base_id,
        fork_ids=[f["fork_id"] for f in forks],
        created_by=created_by, as_of=as_of,
        criteria=[{"criterion": c, "direction": d, "statement": s}
                  for c, d, s in pack.RANKING_CRITERIA[kind]],
        rows=rows, rules_version=pack.RULES_VERSION,
    )


def build_adoption(options: dict, fork_id: str | None, adopted_by: str,
                   note: str | None, as_of: str,
                   supersedes: str | None) -> PlanningAdoption:
    """One adoption act. Adoption records which option the
    plan follows — the base view (fork_id None) or one of
    the comparison's forks — and nothing else: no artefact
    is edited by being adopted."""
    fingerprint = _fingerprint({
        "options": options["options_id"], "fork": fork_id,
        "adopted_by": adopted_by, "as_of": as_of,
        "supersedes": supersedes,
    })
    return PlanningAdoption(
        adoption_id=f"ADOPT-{fingerprint[:10]}",
        options_id=options["options_id"], fork_id=fork_id,
        adopted_by=adopted_by, note=note, as_of=as_of,
        supersedes=supersedes,
    )


def head_adoption(adoptions: list[dict]) -> dict | None:
    """The current adoption in a chain: the act no other
    act supersedes from."""
    superseded = {a["supersedes"] for a in adoptions if a.get("supersedes")}
    heads = [a for a in adoptions if a["adoption_id"] not in superseded]
    return heads[0] if heads else None


# ---------------------------------------------------------------------------
# Verifiers: re-performance from the artefacts alone
# ---------------------------------------------------------------------------


def verify_fork(store, fork: dict) -> list[str]:
    """Re-perform a stored fork: rebuild its view from its
    own lever records, re-run the base artefact's engine,
    and compare the result, the reconciliation and the
    delta identity. The base artefact is fetched by id —
    a fork whose base has moved on still verifies against
    the base it pinned."""
    problems: list[str] = []
    if fork["rules_version"] != pack.RULES_VERSION:
        return [f"fork names unknown scenario pack {fork['rules_version']}"]
    if not fork["hypothetical"]:
        problems.append("the fork does not carry its hypothetical flag")
    records = [dict(r) for r in fork["levers"]]
    if fork["kind"] == pack.KIND_DEMAND:
        base = store.get_estimate(fork["base_artefact_id"])
        if base is None:
            return problems + ["the fork's base estimate is not in the store"]
        base = {**base,
                "contributions": store.estimate_contributions(base["estimate_id"])}
        result, reconciliation = compute_demand_fork(store, base, records)
        lever_sum = round(sum(r["lever_delta_tonnes"]
                              for r in reconciliation), 3)
        if abs(lever_sum - fork["delta_tonnes"]) > TONNE_TOL:
            problems.append(
                f"lever deltas sum to {lever_sum}, not the fork's "
                f"stated delta {fork['delta_tonnes']}")
    else:
        base = store.get_projection(fork["base_artefact_id"])
        if base is None:
            return problems + ["the fork's base projection is not in the store"]
        result, reconciliation = compute_projection_fork(store, base, records)
        previous = 0.0
        for row in reconciliation:
            if row["closing_delta_tonnes"] is None:
                continue
            step = round(previous + (row["production_delta_tonnes"] or 0.0)
                         + row["imports_delta_tonnes"], 3)
            if abs(step - row["closing_delta_tonnes"]) > TONNE_TOL:
                problems.append(
                    f"month {row['month']}: closing delta "
                    f"{row['closing_delta_tonnes']} != the accumulated "
                    f"component deltas {step}")
            previous = row["closing_delta_tonnes"]
        if abs(previous - fork["delta_tonnes"]) > TONNE_TOL:
            problems.append(
                f"the month chain ends at delta {previous}, not the "
                f"fork's stated delta {fork['delta_tonnes']}")
    if json.dumps(result, sort_keys=True) != \
            json.dumps(fork["result"], sort_keys=True):
        problems.append("the fork's result does not re-perform from its "
                        "lever records over the pinned base")
    if json.dumps(reconciliation, sort_keys=True) != \
            json.dumps(fork["reconciliation"], sort_keys=True):
        problems.append("the fork's reconciliation does not re-perform")
    if json.dumps(records, sort_keys=True) != \
            json.dumps(fork["levers"], sort_keys=True):
        problems.append("the fork's lever outcomes do not re-perform")
    return problems


def verify_options(store, options: dict) -> list[str]:
    """Re-perform a stored comparison: the base and every
    fork are fetched by id, the rows and the ranking are
    rebuilt by the same computation, and any difference —
    a moved figure, a swapped rank — is a named problem."""
    problems: list[str] = []
    if options["rules_version"] != pack.RULES_VERSION:
        return [f"options name unknown scenario pack "
                f"{options['rules_version']}"]
    if options["kind"] == pack.KIND_DEMAND:
        base = store.get_estimate(options["base_artefact_id"])
        if base is not None:
            base = {**base, "contributions": store.estimate_contributions(
                base["estimate_id"])}
    else:
        base = store.get_projection(options["base_artefact_id"])
    if base is None:
        return ["the comparison's base artefact is not in the store"]
    forks = []
    for fork_id in options["fork_ids"]:
        fork = store.get_scenario_fork(fork_id)
        if fork is None:
            return problems + [f"fork {fork_id} is not in the store"]
        if fork["base_artefact_id"] != options["base_artefact_id"]:
            problems.append(
                f"fork {fork_id} forks {fork['base_artefact_id']}, not "
                f"the comparison's base {options['base_artefact_id']}")
        forks.append(fork)
    fresh = compute_options(
        store, options["kind"], options["scope"], base, forks,
        options["created_by"], options["as_of"], options["name"])
    if json.dumps(fresh.rows, sort_keys=True) != \
            json.dumps(options["rows"], sort_keys=True):
        stored = {r["artefact_id"]: r for r in options["rows"]}
        rebuilt = {r["artefact_id"]: r for r in fresh.rows}
        for artefact_id in sorted(set(stored) | set(rebuilt)):
            if stored.get(artefact_id) != rebuilt.get(artefact_id):
                problems.append(
                    f"row {artefact_id} does not re-perform — stored "
                    f"{stored.get(artefact_id)} vs rebuilt "
                    f"{rebuilt.get(artefact_id)}")
    if fresh.options_id != options["options_id"]:
        problems.append("the comparison's id does not match its content")
    return problems


def verify_adoption(store, adoption: dict) -> list[str]:
    """An adoption act verifies against its comparison:
    the options exist, the adopted fork is one of its
    rows (or the base), and the supersedes link resolves."""
    problems: list[str] = []
    options = store.get_planning_options(adoption["options_id"])
    if options is None:
        return [f"options {adoption['options_id']} are not in the store"]
    if adoption["fork_id"] is not None \
            and adoption["fork_id"] not in options["fork_ids"]:
        problems.append(
            f"adopted fork {adoption['fork_id']} is not a row of the "
            "comparison")
    if adoption["supersedes"] is not None \
            and store.get_planning_adoption(adoption["supersedes"]) is None:
        problems.append("the superseded adoption is not in the store")
    if not adoption["adopted_by"]:
        problems.append("the adoption names no planner")
    return problems


# ---------------------------------------------------------------------------
# Plain-language intake: a scenario request -> levers + named gaps
# ---------------------------------------------------------------------------

_FILLER = {
    "what", "if", "the", "a", "an", "for", "in", "of", "our", "we",
    "this", "next", "season", "demand", "supply", "estimate",
    "projection", "projected", "show", "me", "happens", "happen",
    "would", "could", "please", "and", "or", "to", "be", "is",
    "with", "by", "on", "at", "from", "than", "then", "into",
    "runs", "run", "comes", "come", "say", "suppose", "assuming",
    "assume", "under", "over",
}

_POLICY_WORDS = ("subsidy", "subsidies", "export restriction",
                 "export ban", "import duty", "duty", "policy",
                 "tax credit")


def _segments(text: str) -> list[str]:
    parts = re.split(r";|,", text)
    out: list[str] = []
    for part in parts:
        out.extend(s.strip() for s in re.split(r"\s+and\s+", part)
                   if s.strip())
    return out


def _policy_gap(store, segment: str) -> dict:
    """A policy part of a request is a named gap by the
    pack's stated rule. When a recorded event matches the
    segment's keywords, the gap names it — its stated
    effect is the only thing the system may say about it."""
    low = segment.lower()
    named = "the named policy change"
    candidates = []
    for row in store.list_policy_registrations():
        candidates.append((row["event_id"], row["title"],
                           row["event_class"]))
    for fact in store.policy_events():
        candidates.append((fact["event_id"], fact["title"], fact["kind"]))
    for event_id, title, klass in candidates:
        words = [w for w in re.split(r"[^a-z]+", title.lower()) if len(w) > 4]
        if any(w in low for w in words) or \
                klass.replace("_", " ") in low:
            named = f"policy event {event_id} ({title})"
            break
    return {
        "subject": segment[:96],
        "needed": pack.GAP_POLICY_NO_TRANSMISSION.format(event=named),
        "rule": "scenario:gap_policy_no_transmission",
    }


def _scan_scope(store, text: str):
    """The base a request speaks about: (kind, scope,
    notes, unknown_place). A district named means a demand
    fork over that district's estimate; no district means
    a supply fork over the product's projection. Season
    and crop year fall back to the stated defaults and the
    defaulting is recorded — never silent."""
    from .dashboard import _find_crop_year, _find_district, \
        _find_product, _find_season

    district, unknown = _find_district(store, text)
    product = _find_product(text.lower())
    season = _find_season(text.lower())
    crop_year = _find_crop_year(text)
    notes: list[str] = []
    if season is None:
        season = "kharif"
        notes.append("season defaulted to kharif (scenario grammar "
                     "default — the request names no season)")
    if crop_year is None:
        crop_year = CROP_YEARS[-1]
        notes.append(f"crop year defaulted to {crop_year} (latest "
                     "tracked — the request names no crop year)")
    if district is not None:
        return pack.KIND_DEMAND, {
            "district_id": district["district_id"], "product": product,
            "crop_year": crop_year, "season": season,
        }, notes, unknown
    return pack.KIND_PROJECTION, {
        "product": product, "crop_year": crop_year, "season": season,
    }, notes, unknown


scan_scope = _scan_scope


def _segment_levers(segment: str) -> tuple[list[dict], str | None]:
    """The lever specs one request segment states, and the
    keyword family it belongs to when it states none
    (drives the precise gap wording). Patterns are the
    grammar, stated here in code."""
    low = segment.lower()
    specs: list[dict] = []

    match = re.search(r"monsoon\s+shortfall\s+of\s+(\d+(?:\.\d+)?)", low)
    if match:
        specs.append({"lever": "monsoon_deviation_shift",
                      "value": -float(match.group(1))})
    match = re.search(
        r"monsoon(?:\s+deviation)?\s+(?:comes in\s+)?(\d+(?:\.\d+)?)"
        r"\s*points?\s+(lower|higher|weaker|stronger)", low)
    if match:
        sign = -1.0 if match.group(2) in ("lower", "weaker") else 1.0
        specs.append({"lever": "monsoon_deviation_shift",
                      "value": sign * float(match.group(1))})
    match = re.search(
        r"monsoon\s+deviation\s+shifts?\s+by\s+(-?\d+(?:\.\d+)?)", low)
    if match:
        specs.append({"lever": "monsoon_deviation_shift",
                      "value": float(match.group(1))})
    match = re.search(r"monsoon\s+deviation\s+of\s+(-?\d+(?:\.\d+)?)", low)
    if match:
        specs.append({"lever": "monsoon_deviation_shift",
                      "target_deviation": float(match.group(1))})
    if specs:
        return specs, "monsoon"

    match = re.search(r"elasticity\s+(?:of|at|to|set to)\s+"
                      r"(-?\d+(?:\.\d+)?)", low)
    if match:
        return [{"lever": "price_elasticity_override",
                 "value": float(match.group(1))}], "elasticity"
    match = re.search(
        r"prices?\s+(?:rise|rises|rising|climb|climbs|increase|"
        r"increases|up)\s+(?:by\s+)?(\d+(?:\.\d+)?)\s*(?:%|percent)",
        low)
    if match:
        return [{"lever": "price_level_shift_pct",
                 "value": float(match.group(1))}], "price"
    match = re.search(
        r"prices?\s+(?:fall|falls|falling|drop|drops|decline|"
        r"declines|down)\s+(?:by\s+)?(\d+(?:\.\d+)?)\s*(?:%|percent)",
        low)
    if match:
        return [{"lever": "price_level_shift_pct",
                 "value": -float(match.group(1))}], "price"

    id_match = re.search(r"\b([A-Za-z]{3}-[A-Za-z]{3,4}-\d{4})\b", segment)
    month_match = re.search(
        r"\b(" + "|".join(_MONTH_NUMBERS) + r")\s+(?:shipment|vessel)",
        low)
    slip = re.search(r"(?:slips?|slipped|delayed|delays?|late)\s+"
                     r"(?:by\s+)?(\d+)\s*months?", low)
    advance = re.search(r"(?:arrives?|arriving|advances?|advanced)\s+"
                        r"(?:by\s+)?(\d+)\s*months?\s*(?:early|earlier)?",
                        low)
    generic = re.search(r"imports?\s+slip\s+(?:by\s+)?(\d+)\s*months?",
                        low)
    if id_match and (slip or advance):
        months = (int(slip.group(1)) if slip
                  else -int(advance.group(1)))
        return [{"lever": "import_arrival_shift_months",
                 "value": months,
                 "shipment_id": id_match.group(1).upper()}], "import"
    if month_match and (slip or advance):
        months = (int(slip.group(1)) if slip
                  else -int(advance.group(1)))
        return [{"lever": "import_arrival_shift_months",
                 "value": months,
                 "expected_month_name": month_match.group(1)}], "import"
    if generic:
        return [{"lever": "import_arrival_shift_months",
                 "value": int(generic.group(1))}], "import"
    if id_match or month_match or "vessel" in low or "shipment" in low:
        return [], "import"

    match = re.search(
        r"production\s+shortfall\s+of\s+(\d+(?:\.\d+)?)\s*(?:%|percent)",
        low)
    if match:
        return [{"lever": "production_shortfall_pct",
                 "value": float(match.group(1))}], "production"
    match = re.search(
        r"production\s+(?:falls?\s+short|drops?|falls?|short)\s+"
        r"(?:by\s+)?(\d+(?:\.\d+)?)\s*(?:%|percent)", low)
    if match:
        return [{"lever": "production_shortfall_pct",
                 "value": float(match.group(1))}], "production"

    for keyword, family in (("monsoon", "monsoon"), ("price", "price"),
                            ("elasticity", "elasticity"),
                            ("production", "production"),
                            ("import", "import")):
        if keyword in low:
            return [], family
    return [], None


_GAP_FOR_FAMILY = {
    "monsoon": ("a monsoon lever needs a stated shift — points "
                "lower/higher, a shortfall in points, or a target "
                "deviation; this part states none, so no monsoon "
                "figure was improvised"),
    "price": ("a price lever needs a stated percent rise or fall, "
              "or an elasticity value; this part states neither, "
              "so no price figure was improvised"),
    "elasticity": ("an elasticity lever needs a stated value "
                   "inside the catalogue bound; this part states "
                   "none"),
    "import": ("an import lever needs a named shipment (or a "
               "shipment's expected month) and a whole number of "
               "months to slip or advance; this part does not "
               "state both, so no arrival was re-timed"),
    "production": ("a production lever needs a stated shortfall "
                   "percent; this part states none, so no plan "
                   "figure was improvised"),
}


def parse_scenario_grammar(store, text: str, base: dict):
    """The offline profile's parse of a scenario request
    against its resolved base. Returns (kind, scope,
    records, gaps, parse): lever records resolved against
    the catalogue and the base, every unmappable or
    refused part a named gap. Raises ScenarioRefused when
    the request cannot produce a fork at all."""
    kind, scope, notes, unknown = _scan_scope(store, text)
    if scope.get("product") is None:
        raise ScenarioRefused(
            "the request names no tracked product — a scenario "
            "forks a product's estimate or projection, and no "
            "product was stated or could be inherited")
    if unknown is not None:
        tracked = ", ".join(d["name"] for d in store.list_districts())
        raise ScenarioRefused(
            f"district coverage: {unknown} is not one of the "
            f"tracked districts ({tracked}) — a scenario cannot "
            "fork an estimate the system does not hold")
    if kind == pack.KIND_DEMAND and base["estimate_id"] is None:
        raise ScenarioRefused("no base estimate could be resolved")

    specs: list[dict] = []
    gaps: list[dict] = []
    rules_used: list[str] = []
    for segment in _segments(text):
        low = segment.lower()
        if any(word in low for word in _POLICY_WORDS):
            gaps.append(_policy_gap(store, segment))
            rules_used.append("grammar:gap_policy_no_transmission")
            continue
        seg_specs, family = _segment_levers(segment)
        if seg_specs:
            specs.extend(seg_specs)
            rules_used.append(f"grammar:lever:{family}")
            continue
        if family is not None:
            gaps.append({
                "subject": segment[:96],
                "needed": _GAP_FOR_FAMILY[family],
                "rule": f"grammar:gap_{family}_unstated",
            })
            rules_used.append(f"grammar:gap_{family}_unstated")
            continue
        # A segment of pure scope/filler is the base being
        # named, not a request part — anything else left
        # over is an unmappable part and becomes a gap.
        from .dashboard import _find_district
        district, _u = _find_district(store, segment)
        leftovers = [
            w for w in re.findall(r"[a-z]+", low)
            if w not in _FILLER
            and w not in [p.lower() for p in PRODUCTS]
            and w not in _MONTH_NUMBERS
            and (district is None or w != district["name"].lower())
            and w not in ("kharif", "rabi", "scenario", "fork")
        ]
        if leftovers:
            gaps.append({
                "subject": segment[:96],
                "needed": pack.GAP_UNMAPPED_SEGMENT.format(
                    levers=", ".join(pack.LEVER_NAMES)),
                "rule": "grammar:gap_unmapped_segment",
            })
            rules_used.append("grammar:gap_unmapped_segment")

    records, refused = resolve_levers(
        store, kind, scope, base, specs, on_error="collect")
    gaps.extend(refused)
    parse = {
        "profile": "offline", "model": "offline",
        "rules": rules_used, "refusals": refused, "notes": notes,
    }
    if not records or not any(r["applied"] for r in records):
        reasons = "; ".join(g["needed"] for g in gaps) or \
            "the request states no lever from the catalogue"
        raise ScenarioRefused(
            "no lever in the request could be applied — " + reasons)
    return kind, scope, records, gaps, parse


_PROPOSAL_PROMPT = """You state scenario forks for a fertilizer \
market-intelligence system. Answer with ONLY a JSON object, no \
prose: {"kind": ..., "scope": {...}, "levers": [...]}. Fork kinds: \
demand_estimate (scope district_id, product, crop_year, season) \
and supply_projection (scope product, crop_year, season). The \
bounded lever catalogue — a lever outside it, or a value outside \
its bound, is refused: monsoon_deviation_shift (demand only, \
-30..30 points), price_level_shift_pct (demand only, -50..50), \
price_elasticity_override (demand only, -1..0), \
import_arrival_shift_months (projection only, whole months -6..6, \
names shipment_id), production_shortfall_pct (projection only, \
0..50). Products: UREA, DAP, NPK_10_26_26, MOP, GLYPHOSATE, \
CHLORPYRIFOS. Seasons: kharif, rabi. District ids look like \
DST-LUD. Policy events are never levers — this system states no \
numeric transmission for them.

Request: {question}"""


def parse_scenario_model(store, port, text: str, base: dict):
    """A hosted profile's parse: the port is asked for a
    fork proposal as JSON; the scope and every lever are
    validated against the governed schema and the
    catalogue. A lever that does not fit is refused and
    recorded as a gap; a reply that is not a governed
    proposal at all refuses the request — fail-closed."""
    reply = port.complete(_PROPOSAL_PROMPT.replace("{question}", text))
    raw = reply.text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?|\n?```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise ScenarioRefused(
            "the model profile returned no parseable fork "
            "proposal — the request was refused rather than "
            "guessed at")
    if not isinstance(data, dict) or data.get("kind") not in pack.FORK_KINDS:
        raise ScenarioRefused(
            "the model profile proposed no governed fork kind — "
            "the request was refused rather than guessed at")
    kind = data["kind"]
    scope = data.get("scope") or {}
    required = set(pack.SCOPE_KEYS[kind])
    if set(scope) != required:
        raise ScenarioRefused(
            f"the proposed {kind} scope must state exactly "
            f"{sorted(required)} — got {sorted(scope)}")
    district_ids = {d["district_id"] for d in store.list_districts()}
    if "district_id" in scope and scope["district_id"] not in district_ids:
        raise ScenarioRefused(
            f"district {scope['district_id']!r} is not tracked")
    if scope["product"] not in PRODUCTS:
        raise ScenarioRefused(f"product {scope['product']!r} is not tracked")
    if scope["season"] not in ("kharif", "rabi"):
        raise ScenarioRefused(f"season {scope['season']!r} is not tracked")
    if scope["crop_year"] not in CROP_YEARS:
        raise ScenarioRefused(
            f"crop year {scope['crop_year']!r} is not tracked")
    specs, gaps = [], []
    for entry in data.get("levers") or []:
        if isinstance(entry, dict) and "lever" in entry:
            specs.append(entry)
        else:
            gaps.append({
                "subject": str(entry)[:96],
                "needed": pack.GAP_REFUSED_LEVER.format(
                    reason="the proposed lever is not a governed "
                           "lever object"),
                "rule": "model:refused_lever",
            })
    # The base the service resolved is for the scanned
    # scope; a proposal over a different base cannot reuse
    # it for target resolution, so import targets resolve
    # against the proposal's own stored head when one is on
    # record — otherwise they refuse as gaps.
    resolve_base = base
    if kind == pack.KIND_PROJECTION:
        head = supply_engine.head_of(
            store.list_projections(scope["product"], scope["crop_year"],
                                   scope["season"]), "projection_id")
        if head is not None:
            resolve_base = head
    records, refused = resolve_levers(
        store, kind, scope, resolve_base, specs, on_error="collect")
    gaps.extend(refused)
    parse = {
        "profile": getattr(port, "profile", "hosted"),
        "model": getattr(port, "model", "unknown"),
        "rules": [f"model_proposal:{r['lever']}" for r in records],
        "refusals": refused, "notes": [],
    }
    if not records or not any(r["applied"] for r in records):
        reasons = "; ".join(g["needed"] for g in gaps) or \
            "the proposal states no applicable lever"
        raise ScenarioRefused(
            "no lever in the proposal could be applied — " + reasons)
    return kind, scope, records, gaps, parse
