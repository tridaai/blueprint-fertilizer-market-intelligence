"""The import & supply-gap tracker (R4): positions, gaps,
projections.

Three artefacts, all computed in code from stored facts under
the supply rule pack (:mod:`.supply_rules`), all insert-only and
superseding by link like the rest of the store:

- A **supply position** states one product's stock for one
  month: opening + domestic production (actual, with the plan
  carried alongside) + import arrivals − consumption = closing.
  Every component is a recorded line pinned to its facts; the
  first tracked month's opening is the pack's stated derivation
  (one month of cover at the first tracked crop year's own
  consumption rate), and every later opening is the prior
  month's closing, so the chain is re-performable end to end and
  a tampered month is detectable from its neighbours as well as
  from its own inputs.

- A **supply gap** states one product's season against the R2
  demand outlook: the demand total, the season's supply on the
  position chain, and the season's import programme tested at
  the gap's as-of month — shipments due, credited once landed
  (to the season they were scheduled for), slipped tonnage
  named. The band is the more severe of the pack's two stated
  readings, and the artefact says which reading bound it.

- A **projected position** runs the actual position forward to
  a season's end on a pinned assumption set — production at
  plan, imports at their expected months, consumption by the
  stated spread. A shipment that slips is excluded and named,
  never silently re-dated; recomputing the projection after the
  slip (or after the vessel lands) stores a new artefact whose
  assumption changes are named against the version it
  supersedes.

Consumption enters positions and projections per month by the
pack's spread rule: a season's recorded consumption spread
evenly over its six application months, the final month
carrying the rounding residual, so the months sum back to the
season total exactly.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from . import configuration as config_engine
from . import demand_rules
from . import supply_rules as rules
from .generator import CROP_YEARS, PRODUCTS

LINE_OPENING = "opening_stock"
LINE_PRODUCTION = "domestic_production"
LINE_IMPORTS = "import_arrivals"
LINE_CONSUMPTION = "consumption"
LINE_CLOSING = "closing_stock"

TONNE_TOL = 0.002
PCT_TOL = 0.01


class PositionLine(BaseModel):
    line_no: int
    component: str
    status: str  # applied / not_applicable
    tonnes: float
    fact_ids: list[str]
    inputs: dict


class SupplyPosition(BaseModel):
    position_id: str
    product: str
    month: str
    opening_tonnes: float
    production_planned_tonnes: float | None
    production_actual_tonnes: float | None
    imports_tonnes: float
    consumption_tonnes: float
    closing_tonnes: float
    lines: list[PositionLine]
    rules_version: str
    fact_fingerprint: str
    as_of: str
    supersedes: str | None = None


class SupplyGap(BaseModel):
    gap_id: str
    product: str
    crop_year: str
    season: str
    as_of: str
    as_of_month: str
    demand_tonnes: float
    demand_outlook_id: str
    opening_stock_tonnes: float
    production_actual_tonnes: float
    arrivals_tonnes: float
    scheduled_imports_tonnes: float
    due_imports_tonnes: float
    credited_imports_tonnes: float
    slipped_tonnes: float
    programme_cover_pct: float | None
    available_tonnes: float
    gap_tonnes: float
    gap_pct_of_demand: float
    band: str  # comfortable / tight / short
    band_basis: str  # import_programme_cover / level_gap
    position_months: list[str]
    uncovered_months: list[str]
    rules_version: str
    fact_fingerprint: str
    supersedes: str | None = None


class ProjectedMonth(BaseModel):
    month: str
    projected: bool
    production_planned_tonnes: float | None
    imports_scheduled_tonnes: float
    consumption_tonnes: float
    closing_tonnes: float | None
    shipment_ids: list[str]
    fact_ids: list[str]


class SupplyProjection(BaseModel):
    projection_id: str
    product: str
    crop_year: str
    season: str
    basis_month: str
    as_of: str
    status: str  # complete / partial
    opening_tonnes: float
    closing_tonnes: float
    months: list[ProjectedMonth]
    assumption_set: dict
    assumption_changes: list[dict]
    rules_version: str
    fact_fingerprint: str
    supersedes: str | None = None


# -- fact ids ---------------------------------------------------------------


def _supply_fact_id(product, month):
    return f"supply_facts:{product}|{month}"


def _import_fact_id(shipment_id):
    return f"import_arrivals:{shipment_id}"


def _consumption_fact_id(district_id, crop_year, season, product):
    return f"consumption_facts:{district_id}|{crop_year}|{season}|{product}"


def _fingerprint(material) -> str:
    blob = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _shift_month(month: str, delta: int) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def head_of(rows: list[dict], id_key: str) -> dict | None:
    superseded = {r["supersedes"] for r in rows if r.get("supersedes")}
    heads = [r for r in rows if r[id_key] not in superseded]
    return heads[0] if heads else None


# -- the tracked calendar -----------------------------------------------------


def tracked_months(store) -> list[str]:
    """The tracked period: the months the supply facts cover,
    earliest to latest."""
    months = sorted({r["month"] for r in store.supply_facts()})
    if not months:
        raise ValueError("no supply facts in the store: no tracked period")
    return months


def positionable_products(store) -> set[str]:
    """Products a position can be stated for: those with domestic
    production facts, plus import-supplied products (arrivals but
    no production). A product with neither has no supply side to
    state, and the engine refuses rather than zero-filling one."""
    produced = {r["product"] for r in store.supply_facts()}
    imported = {a["product"] for a in store.import_arrivals()}
    return produced | imported


def _require_positionable(store, product: str) -> None:
    if product not in PRODUCTS:
        raise ValueError(f"unknown product: {product!r}")
    if product not in positionable_products(store):
        raise ValueError(
            f"no supply position can be stated for {product}: no supply facts "
            "and no import arrivals are tracked for it"
        )


# -- consumption, spread to months ---------------------------------------------


def monthly_consumption(store, product: str) -> dict[str, dict]:
    """The pack's spread rule, applied to the stored consumption
    facts: each district-season total spread evenly over the
    season's six application months, the final month carrying
    the rounding residual.

    Returns {month: {"tonnes": float, "cells": [cell, ...]}} where
    each cell records the district-season fact, its total, its
    window index and the share it contributes to that month — so
    a position's consumption line is re-performable cell by cell.
    """
    out: dict[str, dict] = {}
    facts = store.consumption_facts(product=product)
    for fact in facts:
        window = demand_rules.season_price_window(fact["crop_year"], fact["season"])
        total = fact["quantity_tonnes"]
        share = round(total / len(window), 3)
        fact_id = _consumption_fact_id(
            fact["district_id"], fact["crop_year"], fact["season"], product
        )
        for index, month in enumerate(window):
            value = round(total - share * (len(window) - 1), 3) if index == len(window) - 1 else share
            cell = {
                "district_id": fact["district_id"],
                "crop_year": fact["crop_year"],
                "season": fact["season"],
                "window_index": index,
                "season_total_tonnes": total,
                "share_tonnes": value,
                "fact_id": fact_id,
            }
            entry = out.setdefault(month, {"tonnes": 0.0, "cells": []})
            entry["cells"].append(cell)
            entry["tonnes"] = round(entry["tonnes"] + value, 3)
    for entry in out.values():
        entry["cells"].sort(key=lambda c: c["fact_id"])
    return out


def initial_stock(store, product: str) -> tuple[float, dict, list]:
    """The pack's stated derivation of the first tracked month's
    opening stock: the product's average monthly consumption over
    the first tracked crop year, from stored consumption facts.
    Returns (value, inputs for the opening line, fingerprint
    material)."""
    crop_year = CROP_YEARS[0]
    facts = store.consumption_facts(crop_year=crop_year, product=product)
    total = round(sum(f["quantity_tonnes"] for f in facts), 3)
    value = round(total / rules.INITIAL_STOCK_MONTHS_OF_COVER, 3)
    fact_ids = sorted(
        _consumption_fact_id(f["district_id"], f["crop_year"], f["season"], product)
        for f in facts
    )
    inputs = {
        "rule": "average monthly consumption over the first tracked crop year",
        "crop_year": crop_year,
        "crop_year_total_tonnes": total,
        "divisor_months": rules.INITIAL_STOCK_MONTHS_OF_COVER,
        "fact_ids": fact_ids,
    }
    material = sorted(
        [
            _consumption_fact_id(f["district_id"], f["crop_year"], f["season"], product),
            f["quantity_tonnes"],
        ]
        for f in facts
    )
    return value, inputs, material


# -- positions -------------------------------------------------------------------


def compute_position_chain(store, product: str, as_of: str) -> list[SupplyPosition]:
    """Compute (but do not store) the full position chain for one
    product, first tracked month to last."""
    _require_positionable(store, product)
    months = tracked_months(store)
    supply = {r["month"]: r for r in store.supply_facts(product)}
    has_production = bool(supply)
    by_arrived: dict[str, list[dict]] = {}
    for arrival in store.import_arrivals(product):
        by_arrived.setdefault(arrival["arrived_month"], []).append(arrival)
    consumption = monthly_consumption(store, product)
    init_value, init_inputs, init_material = initial_stock(store, product)

    chain: list[SupplyPosition] = []
    prev_closing = prev_fingerprint = prev_id = None
    for index, month in enumerate(months):
        consumed: list = [["triple", product, month], ["rules", rules.RULES_VERSION]]
        lines: list[dict] = []

        # -- opening ------------------------------------------------
        if index == 0:
            opening = init_value
            opening_inputs = {"basis": "initial_stock_derivation", **init_inputs}
            opening_fact_ids = list(init_inputs["fact_ids"])
            consumed.append(["initial_stock", init_material])
        else:
            opening = prev_closing
            opening_inputs = {
                "basis": "prior_position_closing",
                "prior_month": months[index - 1],
                "prior_position_id": prev_id,
            }
            opening_fact_ids = []
            consumed.append(["prior_position", prev_fingerprint])
        lines.append({
            "line_no": 0, "component": LINE_OPENING, "status": "applied",
            "tonnes": opening, "fact_ids": opening_fact_ids, "inputs": opening_inputs,
        })

        # -- domestic production -------------------------------------
        if not has_production:
            planned = actual = None
            lines.append({
                "line_no": 1, "component": LINE_PRODUCTION,
                "status": "not_applicable", "tonnes": 0.0, "fact_ids": [],
                "inputs": {
                    "reason": "no domestic production is tracked for this "
                              "product: its supply is import-only (no supply "
                              "facts exist)"
                },
            })
            consumed.append(["production", "not_applicable"])
        else:
            fact = supply.get(month)
            if fact is None:
                raise ValueError(
                    f"supply facts do not cover {month} for {product}: "
                    "a position cannot be stated over a hole in the record"
                )
            planned, actual = fact["planned_tonnes"], fact["actual_tonnes"]
            fact_id = _supply_fact_id(product, month)
            lines.append({
                "line_no": 1, "component": LINE_PRODUCTION, "status": "applied",
                "tonnes": actual, "fact_ids": [fact_id],
                "inputs": {
                    "fact_id": fact_id,
                    "planned_tonnes": planned, "actual_tonnes": actual,
                    "vs_plan_pct": (
                        round((actual - planned) / planned * 100.0, 4) if planned else None
                    ),
                },
            })
            consumed.append([fact_id, planned, actual])

        # -- import arrivals (actual months) --------------------------
        landed = sorted(by_arrived.get(month, []), key=lambda a: a["shipment_id"])
        imports_tonnes = round(sum(a["quantity_tonnes"] for a in landed), 3)
        lines.append({
            "line_no": 2, "component": LINE_IMPORTS, "status": "applied",
            "tonnes": imports_tonnes,
            "fact_ids": [_import_fact_id(a["shipment_id"]) for a in landed],
            "inputs": {
                "shipments": [
                    {
                        "shipment_id": a["shipment_id"],
                        "quantity_tonnes": a["quantity_tonnes"],
                        "origin": a["origin"],
                        "expected_month": a["expected_month"],
                        "arrived_month": a["arrived_month"],
                        "fact_id": _import_fact_id(a["shipment_id"]),
                    }
                    for a in landed
                ]
            },
        })
        for a in landed:
            consumed.append([
                _import_fact_id(a["shipment_id"]), a["quantity_tonnes"],
                a["expected_month"], a["arrived_month"],
            ])

        # -- consumption (the spread) ---------------------------------
        entry = consumption.get(month)
        cells = entry["cells"] if entry else []
        consumption_tonnes = entry["tonnes"] if entry else 0.0
        lines.append({
            "line_no": 3, "component": LINE_CONSUMPTION, "status": "applied",
            "tonnes": consumption_tonnes,
            "fact_ids": [c["fact_id"] for c in cells],
            "inputs": {
                "rule": "each season's recorded consumption spread evenly "
                        "over its six application months; the final month "
                        "carries the rounding residual",
                "cells": cells,
            },
        })
        for cell in cells:
            consumed.append([cell["fact_id"], cell["window_index"], cell["share_tonnes"]])

        # -- closing ----------------------------------------------------
        closing = round(opening + (actual or 0.0) + imports_tonnes - consumption_tonnes, 3)
        lines.append({
            "line_no": 4, "component": LINE_CLOSING, "status": "applied",
            "tonnes": closing, "fact_ids": [],
            "inputs": {
                "identity": "opening + production actual + import arrivals "
                            "- consumption"
            },
        })

        fingerprint = _fingerprint(consumed)
        position = SupplyPosition(
            position_id=f"POS-{product}-{month}-{fingerprint[:10]}",
            product=product, month=month,
            opening_tonnes=opening,
            production_planned_tonnes=planned,
            production_actual_tonnes=actual,
            imports_tonnes=imports_tonnes,
            consumption_tonnes=consumption_tonnes,
            closing_tonnes=closing,
            lines=[PositionLine(**line) for line in lines],
            rules_version=rules.RULES_VERSION,
            fact_fingerprint=fingerprint,
            as_of=as_of,
        )
        chain.append(position)
        prev_closing, prev_fingerprint, prev_id = closing, fingerprint, position.position_id
    return chain


def verify_position(store, position: dict, lines: list[dict]) -> list[str]:
    """Verify a stored position. Two grades of check:

    - From the artefact's own recorded inputs (so a superseded
      position stays provable): the identity over its lines, each
      line's inputs re-derived — production against the supply
      fact, import shipments against the arrival facts and their
      sum, consumption cells against the spread rule and their
      sum, the opening against its stated basis (the initial
      derivation re-performed, or the named prior position's
      closing).
    - When the artefact is the current head for its
      product-month, it must also equal what the engine computes
      from the store today, id included.
    """
    problems: list[str] = []
    if position["rules_version"] != rules.RULES_VERSION:
        return [f"position names unknown rule pack {position['rules_version']}"]
    by_component = {line["component"]: line for line in lines}
    expected = [LINE_OPENING, LINE_PRODUCTION, LINE_IMPORTS, LINE_CONSUMPTION, LINE_CLOSING]
    if [line["component"] for line in sorted(lines, key=lambda l: l["line_no"])] != expected:
        return ["position lines do not match the stated component order"]

    opening_line = by_component[LINE_OPENING]
    if abs(opening_line["tonnes"] - position["opening_tonnes"]) > TONNE_TOL:
        problems.append("opening line does not equal the position's opening")
    basis = opening_line["inputs"].get("basis")
    if basis == "initial_stock_derivation":
        value, _, _ = initial_stock(store, position["product"])
        if abs(value - position["opening_tonnes"]) > TONNE_TOL:
            problems.append(
                f"initial opening {position['opening_tonnes']} != re-derived {value}"
            )
    elif basis == "prior_position_closing":
        prior = store.get_position(opening_line["inputs"].get("prior_position_id"))
        if prior is None:
            problems.append("the named prior position is not in the store")
        elif abs(prior["closing_tonnes"] - position["opening_tonnes"]) > TONNE_TOL:
            problems.append(
                "opening does not equal the named prior position's closing "
                f"({prior['closing_tonnes']})"
            )
    else:
        problems.append(f"opening line carries an unknown basis: {basis!r}")

    production_line = by_component[LINE_PRODUCTION]
    if production_line["status"] == "applied":
        fact_id = _supply_fact_id(position["product"], position["month"])
        fact = next(
            (r for r in store.supply_facts(position["product"]) if r["month"] == position["month"]),
            None,
        )
        if fact is None:
            problems.append("production line is applied but no supply fact exists")
        else:
            inputs = production_line["inputs"]
            if inputs.get("planned_tonnes") != fact["planned_tonnes"] or \
                    inputs.get("actual_tonnes") != fact["actual_tonnes"]:
                problems.append("production line inputs do not match the supply fact")
            if production_line["fact_ids"] != [fact_id]:
                problems.append("production line does not name its supply fact")
        if position["production_planned_tonnes"] is None or \
                abs(production_line["tonnes"] - position["production_actual_tonnes"]) > TONNE_TOL:
            problems.append("production line tonnes do not equal the position's actual")
    elif production_line["status"] == "not_applicable":
        if position["production_planned_tonnes"] is not None or \
                position["production_actual_tonnes"] is not None:
            problems.append("a not_applicable production line with stated production figures")
        if production_line["tonnes"] != 0.0:
            problems.append("a not_applicable production line must carry tonnes 0")
    else:
        problems.append(f"unknown production line status {production_line['status']!r}")

    arrivals = {a["shipment_id"]: a for a in store.import_arrivals(position["product"])}
    imports_line = by_component[LINE_IMPORTS]
    shipped_total = 0.0
    for shipment in imports_line["inputs"].get("shipments", []):
        fact = arrivals.get(shipment["shipment_id"])
        if fact is None:
            problems.append(f"import line names unknown shipment {shipment['shipment_id']}")
            continue
        if fact["arrived_month"] != position["month"]:
            problems.append(
                f"shipment {shipment['shipment_id']} arrived {fact['arrived_month']}, "
                f"not in this position's month {position['month']}"
            )
        if shipment["quantity_tonnes"] != fact["quantity_tonnes"] or \
                shipment["expected_month"] != fact["expected_month"] or \
                shipment["arrived_month"] != fact["arrived_month"]:
            problems.append(f"shipment {shipment['shipment_id']} does not match its fact")
        shipped_total += shipment["quantity_tonnes"]
    landed_ids = {
        a["shipment_id"] for a in arrivals.values() if a["arrived_month"] == position["month"]
    }
    if {s["shipment_id"] for s in imports_line["inputs"].get("shipments", [])} != landed_ids:
        problems.append("the import line does not name every shipment that landed this month")
    if abs(shipped_total - position["imports_tonnes"]) > TONNE_TOL or \
            abs(imports_line["tonnes"] - position["imports_tonnes"]) > TONNE_TOL:
        problems.append("import line tonnes do not sum to the position's imports")

    consumption_line = by_component[LINE_CONSUMPTION]
    consumption_facts = {
        _consumption_fact_id(c["district_id"], c["crop_year"], c["season"], position["product"]): c
        for c in store.consumption_facts(product=position["product"])
    }
    cell_total = 0.0
    for cell in consumption_line["inputs"].get("cells", []):
        fact = consumption_facts.get(cell["fact_id"])
        if fact is None:
            problems.append(f"consumption cell names unknown fact {cell['fact_id']}")
            continue
        if abs(fact["quantity_tonnes"] - cell["season_total_tonnes"]) > TONNE_TOL:
            problems.append(f"cell {cell['fact_id']}: season total does not match its fact")
            continue
        window = demand_rules.season_price_window(cell["crop_year"], cell["season"])
        index = cell["window_index"]
        if index >= len(window) or window[index] != position["month"]:
            problems.append(
                f"cell {cell['fact_id']}: window index {index} is not this month"
            )
            continue
        share = round(fact["quantity_tonnes"] / len(window), 3)
        expected_share = (
            round(fact["quantity_tonnes"] - share * (len(window) - 1), 3)
            if index == len(window) - 1 else share
        )
        if abs(cell["share_tonnes"] - expected_share) > TONNE_TOL:
            problems.append(
                f"cell {cell['fact_id']}: share {cell['share_tonnes']} != spread "
                f"{expected_share}"
            )
        cell_total += cell["share_tonnes"]
    if abs(cell_total - position["consumption_tonnes"]) > TONNE_TOL or \
            abs(consumption_line["tonnes"] - position["consumption_tonnes"]) > TONNE_TOL:
        problems.append("consumption cells do not sum to the position's consumption")

    identity = (
        position["opening_tonnes"] + (position["production_actual_tonnes"] or 0.0)
        + position["imports_tonnes"] - position["consumption_tonnes"]
    )
    if abs(identity - position["closing_tonnes"]) > TONNE_TOL:
        problems.append(
            f"position identity fails: opening + production + imports - "
            f"consumption = {round(identity, 3)} != closing {position['closing_tonnes']}"
        )
    if abs(by_component[LINE_CLOSING]["tonnes"] - position["closing_tonnes"]) > TONNE_TOL:
        problems.append("closing line does not equal the position's closing")

    heads = store.list_positions(position["product"], position["month"])
    head = head_of(heads, "position_id")
    if head is not None and head["position_id"] == position["position_id"]:
        fresh = next(
            (p for p in compute_position_chain(store, position["product"], position["as_of"])
             if p.month == position["month"]),
            None,
        )
        if fresh is None or fresh.position_id != position["position_id"]:
            problems.append("head position does not re-perform from the stored facts")
        else:
            for field in ("opening_tonnes", "imports_tonnes",
                          "consumption_tonnes", "closing_tonnes"):
                if abs(getattr(fresh, field) - position[field]) > TONNE_TOL:
                    problems.append(f"head {field}: stored {position[field]} != re-performed")
    return problems


# -- gaps -------------------------------------------------------------------------


def compute_gap(store, product, crop_year, season, as_of, demand_tonnes,
                outlook_id, chain, band_values=None,
                version_label=None) -> SupplyGap:
    """Compute (but do not store) the season gap artefact. `chain`
    is the product's position chain (models), the demand figure
    and its outlook are the caller's — the gap records both.
    `band_values` is the gaps family's threshold snapshot (the
    code pack's by default, or the configuration register's
    version in force, R19); the gap names the version its bands
    were struck under in its rules_version and fingerprint."""
    _require_positionable(store, product)
    window = demand_rules.season_price_window(crop_year, season)
    as_of_month = as_of[:7]
    by_month = {p.month: p for p in chain}
    position_months = [m for m in window if m in by_month]
    uncovered = [m for m in window if m not in by_month]
    opening = by_month[window[0]].opening_tonnes if window[0] in by_month else 0.0
    production_actual = round(
        sum(by_month[m].production_actual_tonnes or 0.0 for m in position_months), 3
    )
    arrivals = round(sum(by_month[m].imports_tonnes for m in position_months), 3)

    shipments = [a for a in store.import_arrivals(product) if a["expected_month"] in window]
    scheduled = round(sum(a["quantity_tonnes"] for a in shipments), 3)
    due_rows = [a for a in shipments if a["expected_month"] <= as_of_month]
    due = round(sum(a["quantity_tonnes"] for a in due_rows), 3)
    credited_rows = [a for a in due_rows if a["arrived_month"] <= as_of_month]
    credited = round(sum(a["quantity_tonnes"] for a in credited_rows), 3)
    slipped = round(due - credited, 3)
    cover = round(credited / due * 100.0, 4) if due > 0 else None

    available = round(opening + production_actual + credited, 3)
    gap_tonnes = round(available - demand_tonnes, 3)
    gap_pct = round((available - demand_tonnes) / demand_tonnes * 100.0, 4) if demand_tonnes else 0.0
    if band_values is None:
        level = rules.level_band(gap_pct)
        programme_of = rules.programme_band
    else:
        level = rules.level_band(
            gap_pct, band_values["level_gap_comfortable_pct"],
            band_values["level_gap_tight_pct"])
        programme_of = lambda cover_pct: rules.programme_band(
            cover_pct,
            band_values["programme_cover_comfortable_pct"],
            band_values["programme_cover_tight_pct"])
    if due > 0:
        programme = programme_of(cover)
        band = rules.worse_band(programme, level)
        basis = "import_programme_cover" if rules.BAND_RANK[programme] >= rules.BAND_RANK[level] \
            else "level_gap"
    else:
        band, basis = level, "level_gap"

    label = version_label if version_label is not None \
        else rules.RULES_VERSION
    fingerprint = _fingerprint({
        "gap": [product, crop_year, season, as_of_month],
        "rules": label,
        "demand": [outlook_id, demand_tonnes],
        "positions": [by_month[m].position_id for m in position_months],
        "uncovered": uncovered,
        "shipments": [
            [_import_fact_id(a["shipment_id"]), a["expected_month"],
             a["arrived_month"], a["quantity_tonnes"]]
            for a in sorted(shipments, key=lambda a: a["shipment_id"])
        ],
    })
    return SupplyGap(
        gap_id=f"GAP-{product}-{crop_year}-{season}-{as_of_month}-{fingerprint[:10]}",
        product=product, crop_year=crop_year, season=season,
        as_of=as_of, as_of_month=as_of_month,
        demand_tonnes=demand_tonnes, demand_outlook_id=outlook_id,
        opening_stock_tonnes=opening,
        production_actual_tonnes=production_actual,
        arrivals_tonnes=arrivals,
        scheduled_imports_tonnes=scheduled,
        due_imports_tonnes=due,
        credited_imports_tonnes=credited,
        slipped_tonnes=slipped,
        programme_cover_pct=cover,
        available_tonnes=available,
        gap_tonnes=gap_tonnes,
        gap_pct_of_demand=gap_pct,
        band=band, band_basis=basis,
        position_months=position_months, uncovered_months=uncovered,
        rules_version=label,
        fact_fingerprint=fingerprint,
    )


def verify_gap(store, gap: dict) -> list[str]:
    """Re-perform a stored gap: the recorded outlook's rollup is
    the demand, the position chain is recomputed from the facts,
    and the programme test is re-run at the gap's as-of month.
    Every figure and the band must match."""
    problems: list[str] = []
    band_values = config_engine.values_for_label(
        store, "gaps", gap["rules_version"])
    if band_values is None:
        return [f"gap names unknown rule pack {gap['rules_version']}"]
    outlook = store.get_outlook(gap["demand_outlook_id"])
    if outlook is None:
        return ["the gap's demand outlook is not in the store"]
    demand = outlook["product_rollups"].get(gap["product"])
    if demand is None:
        return [f"the outlook carries no rollup for {gap['product']}"]
    if abs(demand - gap["demand_tonnes"]) > TONNE_TOL:
        problems.append(
            f"demand {gap['demand_tonnes']} != the outlook rollup {demand}"
        )
    chain = compute_position_chain(store, gap["product"], gap["as_of"])
    fresh = compute_gap(
        store, gap["product"], gap["crop_year"], gap["season"], gap["as_of"],
        demand, gap["demand_outlook_id"], chain,
        band_values=band_values, version_label=gap["rules_version"],
    )
    if fresh.gap_id != gap["gap_id"]:
        problems.append("gap id does not match the re-performed fingerprint")
    for field in ("opening_stock_tonnes", "production_actual_tonnes", "arrivals_tonnes",
                  "scheduled_imports_tonnes", "due_imports_tonnes",
                  "credited_imports_tonnes", "slipped_tonnes", "available_tonnes",
                  "gap_tonnes"):
        if abs(getattr(fresh, field) - gap[field]) > TONNE_TOL:
            problems.append(f"{field}: stored {gap[field]} != re-performed {getattr(fresh, field)}")
    if (fresh.programme_cover_pct is None) != (gap["programme_cover_pct"] is None) or (
        fresh.programme_cover_pct is not None
        and abs(fresh.programme_cover_pct - gap["programme_cover_pct"]) > PCT_TOL
    ):
        problems.append("programme cover does not match the re-performed test")
    if abs(fresh.gap_pct_of_demand - gap["gap_pct_of_demand"]) > PCT_TOL:
        problems.append("gap percentage does not match the re-performed figures")
    if fresh.band != gap["band"] or fresh.band_basis != gap["band_basis"]:
        problems.append(
            f"band: stored {gap['band']} ({gap['band_basis']}) != re-performed "
            f"{fresh.band} ({fresh.band_basis})"
        )
    if fresh.position_months != gap["position_months"] or \
            fresh.uncovered_months != gap["uncovered_months"]:
        problems.append("position coverage does not match the re-performed chain")
    return problems


# -- projections --------------------------------------------------------------------


def compute_projection(store, product, crop_year, season, as_of, chain) -> SupplyProjection:
    """Compute (but do not store) the projected position for one
    product-season, struck at the end of the as-of month on the
    pack's stated basis. Assumption changes are filled by the
    service when the artefact supersedes an earlier projection —
    they are a statement about the chain, not about the facts."""
    _require_positionable(store, product)
    basis_month = as_of[:7]
    months_tracked = tracked_months(store)
    if basis_month not in months_tracked:
        raise ValueError(
            f"no actual position covers {basis_month}: a projection needs a "
            "basis month inside the tracked period"
        )
    window = demand_rules.season_price_window(crop_year, season)
    season_end = window[-1]
    if basis_month >= season_end:
        raise ValueError(
            f"the {season} {crop_year} season has ended by {basis_month}: "
            "nothing left to project"
        )
    by_month = {p.month: p for p in chain}
    basis_position = by_month[basis_month]
    opening = basis_position.closing_tonnes

    supply = {r["month"]: r for r in store.supply_facts(product)}
    has_production = bool(supply)
    arrivals = store.import_arrivals(product)

    def landed(a):
        return a["arrived_month"] <= basis_month

    slipped = sorted(
        (a for a in arrivals if a["expected_month"] <= basis_month and not landed(a)),
        key=lambda a: a["shipment_id"],
    )
    arrivals_in_basis = sorted(
        (a for a in arrivals if landed(a)), key=lambda a: a["shipment_id"]
    )
    consumption = monthly_consumption(store, product)

    month_rows: list[ProjectedMonth] = []
    scheduled_entries: list[dict] = []
    plan_fact_ids: list[str] = []
    closing = opening
    month = _shift_month(basis_month, 1)
    while month <= season_end:
        entry = consumption.get(month)
        consumption_tonnes = entry["tonnes"] if entry else 0.0
        consumption_ids = [c["fact_id"] for c in entry["cells"]] if entry else []
        scheduled = sorted(
            (a for a in arrivals if a["expected_month"] == month and not landed(a)),
            key=lambda a: a["shipment_id"],
        )
        imports_tonnes = round(sum(a["quantity_tonnes"] for a in scheduled), 3)
        for a in scheduled:
            scheduled_entries.append({
                "shipment_id": a["shipment_id"],
                "expected_month": a["expected_month"],
                "quantity_tonnes": a["quantity_tonnes"],
            })
        fact = supply.get(month)
        if has_production and fact is None:
            month_rows.append(ProjectedMonth(
                month=month, projected=False,
                production_planned_tonnes=None,
                imports_scheduled_tonnes=imports_tonnes,
                consumption_tonnes=consumption_tonnes,
                closing_tonnes=None,
                shipment_ids=[a["shipment_id"] for a in scheduled],
                fact_ids=[_import_fact_id(a["shipment_id"]) for a in scheduled]
                + consumption_ids,
            ))
            month = _shift_month(month, 1)
            continue
        planned = fact["planned_tonnes"] if fact is not None else None
        fact_ids = ([_supply_fact_id(product, month)] if fact is not None else []) \
            + [_import_fact_id(a["shipment_id"]) for a in scheduled] + consumption_ids
        if fact is not None:
            plan_fact_ids.append(_supply_fact_id(product, month))
        closing = round(closing + (planned or 0.0) + imports_tonnes - consumption_tonnes, 3)
        month_rows.append(ProjectedMonth(
            month=month, projected=True,
            production_planned_tonnes=planned,
            imports_scheduled_tonnes=imports_tonnes,
            consumption_tonnes=consumption_tonnes,
            closing_tonnes=closing,
            shipment_ids=[a["shipment_id"] for a in scheduled],
            fact_ids=fact_ids,
        ))
        month = _shift_month(month, 1)

    beyond = [r.month for r in month_rows if not r.projected]
    assumption_set = {
        "basis_month": basis_month,
        "basis_position_id": basis_position.position_id,
        "production_basis": (
            "planned_tonnes from the supply facts; a horizon month with no "
            "plan on record is beyond the plan horizon and is not projected"
            if has_production else
            "no domestic production is tracked for this product (import-only)"
        ),
        "production_fact_ids": plan_fact_ids,
        "imports_basis": "scheduled at the expected month for shipments not "
                         "yet landed by the basis month; landed shipments "
                         "are in the basis stock; slipped shipments are "
                         "excluded and named, never re-dated",
        "scheduled_shipments": scheduled_entries,
        "slipped_shipments": [
            {
                "shipment_id": a["shipment_id"],
                "expected_month": a["expected_month"],
                "arrived_month": a["arrived_month"],
                "quantity_tonnes": a["quantity_tonnes"],
            }
            for a in slipped
        ],
        "arrivals_in_basis": [
            {
                "shipment_id": a["shipment_id"],
                "expected_month": a["expected_month"],
                "arrived_month": a["arrived_month"],
                "quantity_tonnes": a["quantity_tonnes"],
            }
            for a in arrivals_in_basis
        ],
        "consumption_basis": "recorded consumption facts spread evenly over "
                             "each season's six application months (supply pack)",
        "beyond_plan_months": beyond,
        "rules_version": rules.RULES_VERSION,
    }
    fingerprint = _fingerprint({
        "projection": [product, crop_year, season, basis_month],
        "rules": rules.RULES_VERSION,
        "basis_position": basis_position.position_id,
        "assumptions": {
            k: assumption_set[k]
            for k in ("production_fact_ids", "scheduled_shipments",
                      "slipped_shipments", "beyond_plan_months")
        },
        "months": [
            [r.month, r.projected, r.production_planned_tonnes,
             r.imports_scheduled_tonnes, r.consumption_tonnes, r.closing_tonnes]
            for r in month_rows
        ],
    })
    return SupplyProjection(
        projection_id=(
            f"PRJ-{product}-{crop_year}-{season}-{basis_month}-{fingerprint[:10]}"
        ),
        product=product, crop_year=crop_year, season=season,
        basis_month=basis_month, as_of=as_of,
        status="partial" if beyond else "complete",
        opening_tonnes=opening, closing_tonnes=closing,
        months=month_rows,
        assumption_set=assumption_set,
        assumption_changes=[],
        rules_version=rules.RULES_VERSION,
        fact_fingerprint=fingerprint,
    )


def diff_assumptions(old_set: dict, new_set: dict) -> list[dict]:
    """Name what changed between a superseded projection's
    assumption set and its successor's: the basis advancing, and
    the fate of every shipment the old projection assumed —
    landed into the basis stock, slipped and excluded, still
    scheduled, or newly scheduled since."""
    changes: list[dict] = []
    if old_set["basis_month"] != new_set["basis_month"]:
        changes.append({
            "kind": "basis_advanced",
            "shipment_id": None,
            "detail": (
                f"basis month moved {old_set['basis_month']} -> "
                f"{new_set['basis_month']}: the projection now stands on the "
                f"{new_set['basis_month']} actual position"
            ),
        })
    old_scheduled = {s["shipment_id"]: s for s in old_set["scheduled_shipments"]}
    new_scheduled = {s["shipment_id"]: s for s in new_set["scheduled_shipments"]}
    new_slipped = {s["shipment_id"]: s for s in new_set["slipped_shipments"]}
    in_basis = {a["shipment_id"]: a for a in new_set["arrivals_in_basis"]}
    for shipment_id in sorted(old_scheduled):
        entry = old_scheduled[shipment_id]
        if shipment_id in in_basis:
            landed = in_basis[shipment_id]
            changes.append({
                "kind": "landed",
                "shipment_id": shipment_id,
                "detail": (
                    f"expected {entry['expected_month']}; arrived "
                    f"{landed['arrived_month']} — its tonnes are in the "
                    "basis stock now, no longer a scheduled assumption"
                ),
            })
        elif shipment_id in new_slipped:
            changes.append({
                "kind": "slipped_unlanded",
                "shipment_id": shipment_id,
                "detail": (
                    f"expected {entry['expected_month']}; not arrived by "
                    f"the {new_set['basis_month']} basis — excluded from "
                    "the horizon and named, not re-dated"
                ),
            })
        elif shipment_id in new_scheduled:
            continue
        else:
            changes.append({
                "kind": "no_longer_scheduled",
                "shipment_id": shipment_id,
                "detail": (
                    f"expected {entry['expected_month']}; no longer in the "
                    "schedule and not in the basis stock"
                ),
            })
    for shipment_id in sorted(new_scheduled):
        if shipment_id not in old_scheduled:
            entry = new_scheduled[shipment_id]
            changes.append({
                "kind": "newly_scheduled",
                "shipment_id": shipment_id,
                "detail": (
                    f"scheduled since the previous projection: expected "
                    f"{entry['expected_month']}, {entry['quantity_tonnes']} tonnes"
                ),
            })
    old_slipped = {s["shipment_id"]: s for s in old_set["slipped_shipments"]}
    for shipment_id in sorted(old_slipped):
        if shipment_id in in_basis:
            landed = in_basis[shipment_id]
            changes.append({
                "kind": "landed_after_slip",
                "shipment_id": shipment_id,
                "detail": (
                    f"expected {old_slipped[shipment_id]['expected_month']}; "
                    f"arrived {landed['arrived_month']} after slipping past "
                    "the previous basis — its tonnes are in the basis "
                    "stock now"
                ),
            })
    return changes


def verify_projection(store, projection: dict) -> list[str]:
    """Re-perform a stored projection from the facts at its
    recorded as-of: the months, the assumption set and the
    closing must match, and its assumption changes must be
    exactly the named difference against the projection it
    supersedes (or empty, for the first in its chain)."""
    problems: list[str] = []
    if projection["rules_version"] != rules.RULES_VERSION:
        return [f"projection names unknown rule pack {projection['rules_version']}"]
    chain = compute_position_chain(store, projection["product"], projection["as_of"])
    fresh = compute_projection(
        store, projection["product"], projection["crop_year"],
        projection["season"], projection["as_of"], chain,
    )
    if fresh.projection_id != projection["projection_id"]:
        problems.append("projection id does not match the re-performed fingerprint")
    if fresh.status != projection["status"]:
        problems.append(f"status: stored {projection['status']} != re-performed {fresh.status}")
    for field in ("opening_tonnes", "closing_tonnes"):
        if abs(getattr(fresh, field) - projection[field]) > TONNE_TOL:
            problems.append(f"{field}: stored {projection[field]} != re-performed")
    fresh_months = [m.model_dump() for m in fresh.months]
    if len(fresh_months) != len(projection["months"]):
        problems.append("projected months do not match the re-performed horizon")
    else:
        for mine, theirs in zip(projection["months"], fresh_months):
            if mine["month"] != theirs["month"] or mine["projected"] != theirs["projected"]:
                problems.append(f"month {mine['month']}: horizon shape mismatch")
                continue
            for field in ("production_planned_tonnes", "closing_tonnes"):
                a, b = mine[field], theirs[field]
                if (a is None) != (b is None) or (a is not None and abs(a - b) > TONNE_TOL):
                    problems.append(f"month {mine['month']} {field}: stored {a} != re-performed {b}")
            for field in ("imports_scheduled_tonnes", "consumption_tonnes"):
                if abs(mine[field] - theirs[field]) > TONNE_TOL:
                    problems.append(f"month {mine['month']} {field}: stored != re-performed")
            if mine["shipment_ids"] != theirs["shipment_ids"]:
                problems.append(f"month {mine['month']}: scheduled shipments mismatch")
    if json.dumps(fresh.assumption_set, sort_keys=True) != \
            json.dumps(projection["assumption_set"], sort_keys=True):
        problems.append("assumption set does not match the re-performed set")
    if projection["supersedes"] is None:
        if projection["assumption_changes"]:
            problems.append("the first projection in a chain must carry no changes")
    else:
        old = store.get_projection(projection["supersedes"])
        if old is None:
            problems.append("the superseded projection is not in the store")
        else:
            expected = diff_assumptions(old["assumption_set"], projection["assumption_set"])
            if json.dumps(expected, sort_keys=True) != \
                    json.dumps(projection["assumption_changes"], sort_keys=True):
                problems.append(
                    "assumption changes do not match the named difference "
                    "against the superseded projection"
                )
    return problems
