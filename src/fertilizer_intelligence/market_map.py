"""The district demand/gap map (R13, roadmap F21-GS1 +
F21-GS2).

The map is the surface a regional head actually opens:
every tracked district as a tile, coloured by its demand
outlook and its gap band, with product and season
switchers and two switchable layers — monsoon deviation
and field signals. It is built the way the R8 dashboard
assembler is built, because it carries the same risk: a
persuasive picture that quietly stops matching the
record. So the map is an artefact, not a query:

1. **Cells are composed from artefact heads, in the
   open.** Each cell binds the district's head demand
   estimate (and its prior-year counterpart), the
   product's head supply-gap artefact, the district's
   head field-signal assessment, the monsoon fact, and
   the district's field reports with their derived
   review states — every one named on the cell, so any
   figure on the map can be walked back to the artefact
   it came from.
2. **Composition follows the map pack.** The outlook
   band reads estimate against prior-year estimate; the
   gap band is the more severe of the product gap band
   and the district's signal-pressure band; partial
   estimates render partial and districts without an
   estimate render as no-data. The rules live in
   :mod:`.map_rules`, versioned.
3. **Verification before storage.** A candidate map is
   re-performed cell for cell by a second route before
   anything is stored: one mismatched cell refuses the
   WHOLE map, the refusal is recorded as its own
   artefact, and no partial map is ever stored. A stored
   map re-verifies the same way, plus a byte-exact
   re-render of its page.
4. **The page is static and read-only.** One HTML page,
   rendered from the artefact alone; the product and
   layer switchers only show and hide what was rendered
   — there is no form, no POST and no control verb
   anywhere on it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from . import field as field_engine
from . import map_rules as pack
from . import supply_rules as supply_pack
from .dashboard import _CSS, _esc, _fmt
from .demand import head_of
from .generator import PRODUCTS


class MapRefused(RuntimeError):
    """A cell did not re-perform against its artefacts at
    build time. The whole map is refused; nothing partial
    is stored."""

    def __init__(self, problems: list[str], refusal_id: str | None = None):
        self.problems = problems
        self.refusal_id = refusal_id
        super().__init__("market map refused: " + "; ".join(problems))


# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------


class MarketMap(BaseModel):
    map_id: str
    fingerprint: str
    crop_year: str
    season: str
    as_of: str
    built_by: str
    rules_version: str
    products: list[str]
    cells: list[dict]
    monsoon: list[dict]
    html: str
    supersedes: str | None = None


class MapRefusal(BaseModel):
    refusal_id: str
    fingerprint: str
    crop_year: str
    season: str
    as_of: str
    built_by: str
    rules_version: str
    problems: list[str]


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def prior_crop_year(crop_year: str) -> str:
    return f"{int(crop_year[:4]) - 1:04d}-{int(crop_year[5:]) - 1:02d}"


def tile_positions(districts: list[dict]) -> dict[str, dict]:
    """The schematic layout: region rows in the pack's
    stated order, districts by id within their region. A
    pure function of the district register."""
    positions: dict[str, dict] = {}
    for row, region in enumerate(pack.REGION_ORDER):
        members = sorted(
            (d for d in districts if d["region"] == region),
            key=lambda d: d["district_id"],
        )
        for col, district in enumerate(members):
            positions[district["district_id"]] = {"row": row, "col": col}
    return positions


# ---------------------------------------------------------------------------
# Cell composition (the builder's route)
# ---------------------------------------------------------------------------


def _head(rows: list[dict], id_key: str) -> dict | None:
    return head_of(rows, id_key)


def _review_state_at(store, report_id: str, as_of: str | None) -> str:
    """A report's review state at a date: the fold of its
    acts recorded on or before that date (all of them,
    when no date is given)."""
    acts = store.list_field_review_acts(report_id)
    if as_of is not None:
        acts = [a for a in acts if a["as_of"] <= as_of]
    return field_engine.derive_review_state(acts)


def _signals_for(store, district_id: str, product: str,
                 crop_year: str, season: str,
                 as_of: str | None = None) -> dict:
    """The field-signal layer for one cell: the district's
    reports attributed to this product and season that had
    landed by the map's date, split by derived review
    state at that date into the pack's classes. Confirmed
    and pending are separate lists, always."""
    confirmed: list[dict] = []
    pending: list[dict] = []
    rejected = 0
    reports = store.list_field_report_artefacts(
        district_id=district_id, product=product)
    for report in sorted(reports, key=lambda r: r["report_id"]):
        if report.get("crop_year") != crop_year \
                or report.get("season") != season:
            continue
        if as_of is not None and report["as_of"] > as_of:
            continue  # not yet landed at the map's date
        state = _review_state_at(store, report["report_id"], as_of)
        entry = {
            "report_id": report["report_id"],
            "signal_kind": report["signal_kind"],
            "reporter": report["reporter"],
            "observed_on": report["observed_on"],
        }
        if state == field_engine.pack.STATE_CONFIRMED:
            confirmed.append(entry)
        elif state == field_engine.pack.STATE_REJECTED:
            rejected += 1
        else:
            pending.append({**entry, "review_state": state})
    return {"confirmed": confirmed, "pending": pending,
            "rejected_count": rejected}


def _monsoon_cells(store, crop_year: str, season: str) -> list[dict]:
    """The monsoon layer: one entry per tracked district,
    from the monsoon facts — the latest fact per district
    when several as-of versions exist."""
    rows = store.monsoon_facts(crop_year=crop_year, season=season)
    latest: dict[str, dict] = {}
    for row in rows:
        current = latest.get(row["district_id"])
        if current is None or row["as_of"] >= current["as_of"]:
            latest[row["district_id"]] = row
    out = []
    for district in sorted(store.list_districts(),
                           key=lambda d: d["district_id"]):
        row = latest.get(district["district_id"])
        if row is None:
            out.append({
                "district_id": district["district_id"],
                "deviation_pct": None, "band": pack.MONSOON_NO_DATA,
                "fact_id": None, "source": None, "as_of": None,
            })
        else:
            out.append({
                "district_id": district["district_id"],
                "deviation_pct": row["deviation_pct"],
                "band": pack.monsoon_band(row["deviation_pct"]),
                "fact_id": (f"monsoon_facts:{district['district_id']}|"
                            f"{crop_year}|{season}"),
                "source": row["source"], "as_of": row["as_of"],
            })
    return out


def build_cells(store, crop_year: str, season: str,
                as_of: str | None = None) -> list[dict]:
    """Compose every cell of the map from the current
    artefact heads. Pure reads: building cells strikes
    nothing — the service ensures the underlying artefacts
    first, the way a dashboard assembly resolves heads.
    The signal layer is read as of the given date (all
    landed reports, when no date is given)."""
    districts = store.list_districts()
    positions = tile_positions(districts)
    prior_year = prior_crop_year(crop_year)
    gap_heads = {
        product: _head(store.list_gaps(product, crop_year, season), "gap_id")
        for product in PRODUCTS
    }
    cells: list[dict] = []
    for product in PRODUCTS:
        gap = gap_heads[product]
        for district in sorted(districts, key=lambda d: d["district_id"]):
            district_id = district["district_id"]
            estimate = _head(
                store.list_estimates(district_id, product, crop_year, season),
                "estimate_id")
            prior = _head(
                store.list_estimates(district_id, product, prior_year, season),
                "estimate_id")
            assessment = _head(
                store.list_field_assessments(
                    district_id, product, crop_year, season),
                "assessment_id")
            change_pct = None
            if estimate is not None and prior is not None \
                    and prior["total_tonnes"]:
                change_pct = round(
                    (estimate["total_tonnes"] - prior["total_tonnes"])
                    / prior["total_tonnes"] * 100.0, 4)
            pressure = pack.pressure_band(
                assessment["adjustment_pct"] if assessment else None)
            product_band = gap["band"] if gap else None
            readings = [b for b in (product_band, pressure) if b]
            if readings:
                district_band = readings[0]
                for band in readings[1:]:
                    district_band = supply_pack.worse_band(district_band, band)
            else:
                district_band = None
            if product_band is not None and pressure is not None:
                basis = pack.GAP_BASIS_PRODUCT_AND_SIGNALS
            elif product_band is not None:
                basis = pack.GAP_BASIS_PRODUCT_ONLY
            elif pressure is not None:
                basis = pack.GAP_BASIS_SIGNALS_ONLY
            else:
                basis = pack.GAP_BASIS_NONE
            if estimate is None:
                data_state = pack.DATA_NONE
            elif estimate["status"] == "partial":
                data_state = pack.DATA_PARTIAL
            else:
                data_state = pack.DATA_COMPLETE
            cells.append({
                "product": product,
                "district_id": district_id,
                "district_name": district["name"],
                "state": district["state"],
                "region": district["region"],
                "tile": positions[district_id],
                "data_state": data_state,
                "estimate_id": estimate["estimate_id"] if estimate else None,
                "estimate_status": estimate["status"] if estimate else None,
                "demand_tonnes": estimate["total_tonnes"] if estimate else None,
                "missing_drivers": (list(estimate["missing_drivers"])
                                    if estimate else []),
                "prior_estimate_id": prior["estimate_id"] if prior else None,
                "prior_tonnes": prior["total_tonnes"] if prior else None,
                "change_pct": change_pct,
                "outlook_band": pack.outlook_band(change_pct),
                "gap_id": gap["gap_id"] if gap else None,
                "product_gap_band": product_band,
                "gap_pct_of_demand": (gap["gap_pct_of_demand"]
                                      if gap else None),
                "programme_cover_pct": (gap["programme_cover_pct"]
                                        if gap else None),
                "assessment_id": (assessment["assessment_id"]
                                  if assessment else None),
                "adjustment_pct": (assessment["adjustment_pct"]
                                   if assessment else None),
                "pressure_band": pressure,
                "district_gap_band": district_band,
                "district_gap_basis": basis,
                "signals": _signals_for(
                    store, district_id, product, crop_year, season, as_of),
            })
    cells.sort(key=lambda c: (PRODUCTS.index(c["product"]),
                              c["tile"]["row"], c["tile"]["col"]))
    return cells


def build_map(store, crop_year: str, season: str, as_of: str,
              built_by: str) -> MarketMap:
    """Build (do not store) the candidate map artefact for
    one season, with its page rendered."""
    cells = build_cells(store, crop_year, season, as_of)
    monsoon = _monsoon_cells(store, crop_year, season)
    fingerprint = _fingerprint({
        "scope": [crop_year, season], "pack": pack.RULES_VERSION,
        "cells": cells, "monsoon": monsoon,
    })
    draft = MarketMap(
        map_id=f"MAP-{crop_year}-{season}-{fingerprint[:10]}",
        fingerprint=fingerprint,
        crop_year=crop_year, season=season, as_of=as_of,
        built_by=built_by, rules_version=pack.RULES_VERSION,
        products=list(PRODUCTS), cells=cells, monsoon=monsoon,
        html="",
    )
    return draft.model_copy(
        update={"html": render_map_html(draft.model_dump())})


def build_refusal(crop_year: str, season: str, as_of: str,
                  built_by: str, problems: list[str]) -> MapRefusal:
    fingerprint = _fingerprint({
        "scope": [crop_year, season], "as_of": as_of,
        "built_by": built_by, "problems": problems,
        "pack": pack.RULES_VERSION,
    })
    return MapRefusal(
        refusal_id=f"MRX-{fingerprint[:10]}", fingerprint=fingerprint,
        crop_year=crop_year, season=season, as_of=as_of,
        built_by=built_by, rules_version=pack.RULES_VERSION,
        problems=problems,
    )


# ---------------------------------------------------------------------------
# Re-performance: the verifier's second route
# ---------------------------------------------------------------------------


def _expected_cells(store, crop_year: str, season: str,
                    as_of: str | None = None) -> list[dict]:
    """Rebuild the expected cells from the store's rows by
    a separate pass: group first, then read each cell off
    the groups — never through the builder's per-cell
    lookups — so a defect in one route cannot hide in the
    other."""
    districts = {d["district_id"]: d for d in store.list_districts()}
    positions = tile_positions(list(districts.values()))
    prior_year = prior_crop_year(crop_year)

    def heads_by_cell(rows, key_fields, id_key):
        grouped: dict[tuple, list[dict]] = {}
        for row in rows:
            grouped.setdefault(
                tuple(row[f] for f in key_fields), []).append(row)
        return {key: head_of(group, id_key)
                for key, group in grouped.items()}

    estimates = heads_by_cell(
        store.list_estimates(crop_year=crop_year, season=season),
        ("district_id", "product"), "estimate_id")
    priors = heads_by_cell(
        store.list_estimates(crop_year=prior_year, season=season),
        ("district_id", "product"), "estimate_id")
    assessments = heads_by_cell(
        store.list_field_assessments(
            crop_year=crop_year, season=season),
        ("district_id", "product"), "assessment_id")
    gaps = {}
    for product in PRODUCTS:
        gaps[product] = head_of(
            store.list_gaps(product, crop_year, season), "gap_id")
    reports_by_cell: dict[tuple, list[dict]] = {}
    for report in store.list_field_report_artefacts():
        if report.get("crop_year") == crop_year \
                and report.get("season") == season \
                and (as_of is None or report["as_of"] <= as_of):
            reports_by_cell.setdefault(
                (report["district_id"], report["product"]), []).append(report)

    expected: list[dict] = []
    for product in PRODUCTS:
        gap = gaps[product]
        for district_id in sorted(districts):
            district = districts[district_id]
            estimate = estimates.get((district_id, product))
            prior = priors.get((district_id, product))
            assessment = assessments.get((district_id, product))
            change_pct = None
            if estimate is not None and prior is not None \
                    and prior["total_tonnes"]:
                change_pct = round(
                    (estimate["total_tonnes"] - prior["total_tonnes"])
                    / prior["total_tonnes"] * 100.0, 4)
            pressure = pack.pressure_band(
                assessment["adjustment_pct"] if assessment else None)
            product_band = gap["band"] if gap else None
            readings = [b for b in (product_band, pressure) if b]
            district_band = None
            for band in readings:
                district_band = band if district_band is None \
                    else supply_pack.worse_band(district_band, band)
            if product_band is not None and pressure is not None:
                basis = pack.GAP_BASIS_PRODUCT_AND_SIGNALS
            elif product_band is not None:
                basis = pack.GAP_BASIS_PRODUCT_ONLY
            elif pressure is not None:
                basis = pack.GAP_BASIS_SIGNALS_ONLY
            else:
                basis = pack.GAP_BASIS_NONE
            if estimate is None:
                data_state = pack.DATA_NONE
            elif estimate["status"] == "partial":
                data_state = pack.DATA_PARTIAL
            else:
                data_state = pack.DATA_COMPLETE
            confirmed, pending, rejected = [], [], 0
            cell_reports = sorted(
                reports_by_cell.get((district_id, product), []),
                key=lambda r: r["report_id"])
            for report in cell_reports:
                state = _review_state_at(store, report["report_id"], as_of)
                entry = {
                    "report_id": report["report_id"],
                    "signal_kind": report["signal_kind"],
                    "reporter": report["reporter"],
                    "observed_on": report["observed_on"],
                }
                if state == field_engine.pack.STATE_CONFIRMED:
                    confirmed.append(entry)
                elif state == field_engine.pack.STATE_REJECTED:
                    rejected += 1
                else:
                    pending.append({**entry, "review_state": state})
            expected.append({
                "product": product,
                "district_id": district_id,
                "district_name": district["name"],
                "state": district["state"],
                "region": district["region"],
                "tile": positions[district_id],
                "data_state": data_state,
                "estimate_id": estimate["estimate_id"] if estimate else None,
                "estimate_status": estimate["status"] if estimate else None,
                "demand_tonnes": estimate["total_tonnes"] if estimate else None,
                "missing_drivers": (list(estimate["missing_drivers"])
                                    if estimate else []),
                "prior_estimate_id": prior["estimate_id"] if prior else None,
                "prior_tonnes": prior["total_tonnes"] if prior else None,
                "change_pct": change_pct,
                "outlook_band": pack.outlook_band(change_pct),
                "gap_id": gap["gap_id"] if gap else None,
                "product_gap_band": product_band,
                "gap_pct_of_demand": (gap["gap_pct_of_demand"]
                                      if gap else None),
                "programme_cover_pct": (gap["programme_cover_pct"]
                                        if gap else None),
                "assessment_id": (assessment["assessment_id"]
                                  if assessment else None),
                "adjustment_pct": (assessment["adjustment_pct"]
                                   if assessment else None),
                "pressure_band": pressure,
                "district_gap_band": district_band,
                "district_gap_basis": basis,
                "signals": {"confirmed": confirmed, "pending": pending,
                            "rejected_count": rejected},
            })
    expected.sort(key=lambda c: (PRODUCTS.index(c["product"]),
                                 c["tile"]["row"], c["tile"]["col"]))
    return expected


def _expected_monsoon(store, crop_year: str, season: str) -> list[dict]:
    rows = store.monsoon_facts(crop_year=crop_year, season=season)
    latest: dict[str, dict] = {}
    for row in sorted(rows, key=lambda r: (r["district_id"], r["as_of"])):
        latest[row["district_id"]] = row
    out = []
    for district in sorted(store.list_districts(),
                           key=lambda d: d["district_id"]):
        row = latest.get(district["district_id"])
        if row is None:
            out.append({
                "district_id": district["district_id"],
                "deviation_pct": None, "band": pack.MONSOON_NO_DATA,
                "fact_id": None, "source": None, "as_of": None,
            })
        else:
            out.append({
                "district_id": district["district_id"],
                "deviation_pct": row["deviation_pct"],
                "band": pack.monsoon_band(row["deviation_pct"]),
                "fact_id": (f"monsoon_facts:{district['district_id']}|"
                            f"{crop_year}|{season}"),
                "source": row["source"], "as_of": row["as_of"],
            })
    return out


def build_problems(store, candidate: dict) -> list[str]:
    """The build-time gate: a candidate's cells must equal
    the current artefact heads, composed by the second
    route. This is the check that refuses a map at build
    time — a stored map is then verified archivally, by
    the artefacts it binds, so it stays verifiable after
    the record moves on."""
    problems: list[str] = []
    expected_cells = _expected_cells(
        store, candidate["crop_year"], candidate["season"],
        candidate["as_of"])
    mine = {(c["product"], c["district_id"]): c for c in candidate["cells"]}
    theirs = {(c["product"], c["district_id"]): c for c in expected_cells}
    if set(mine) != set(theirs):
        problems.append(
            f"cell set differs: candidate "
            f"{sorted(set(mine) - set(theirs))} extra, "
            f"{sorted(set(theirs) - set(mine))} missing")
    for key in sorted(set(mine) & set(theirs)):
        if mine[key] != theirs[key]:
            differing = [
                field for field in theirs[key]
                if mine[key].get(field) != theirs[key].get(field)]
            problems.append(
                f"cell {key[0]}/{key[1]}: fields differ: {differing}")
    if candidate["monsoon"] != _expected_monsoon(
            store, candidate["crop_year"], candidate["season"]):
        problems.append("monsoon layer does not re-perform from the facts")
    return problems


def verify_map(store, map_dict: dict) -> list[str]:
    """Re-perform a stored map archivally: every cell is
    checked against the artefacts it binds, fetched by
    id — the estimate and its prior-year counterpart, the
    gap, the assessment — with every derived reading
    (outlook, pressure, the composed band, the basis, the
    data state) recomputed from those artefacts under the
    pack. The signal layer is re-derived from the reports
    landed by the map's date, with review states folded
    at that date. The monsoon layer re-performs from the
    facts, the fingerprint from the cells, and the page
    re-renders byte for byte. A map therefore stays
    verifiable after newer artefacts supersede the ones
    it binds — and a tampered cell is named."""
    problems: list[str] = []
    if map_dict["rules_version"] != pack.RULES_VERSION:
        return [f"map names unknown rule pack {map_dict['rules_version']}"]
    crop_year, season = map_dict["crop_year"], map_dict["season"]
    districts = {d["district_id"]: d for d in store.list_districts()}
    positions = tile_positions(list(districts.values()))
    seen: set[tuple] = set()
    for cell in map_dict["cells"]:
        key = (cell["product"], cell["district_id"])
        seen.add(key)
        label = f"cell {key[0]}/{key[1]}"
        district = districts.get(cell["district_id"])
        if district is None:
            problems.append(f"{label}: unknown district")
            continue
        if cell["district_name"] != district["name"] \
                or cell["state"] != district["state"] \
                or cell["region"] != district["region"] \
                or cell["tile"] != positions[cell["district_id"]]:
            problems.append(f"{label}: district identity or tile "
                            "does not match the register")
        estimate = None
        if cell["estimate_id"] is not None:
            estimate = store.get_estimate(cell["estimate_id"])
            if estimate is None:
                problems.append(f"{label}: bound estimate "
                                f"{cell['estimate_id']} is not in the store")
            else:
                if (estimate["district_id"], estimate["product"],
                        estimate["crop_year"], estimate["season"]) != (
                        cell["district_id"], cell["product"],
                        crop_year, season):
                    problems.append(f"{label}: bound estimate is for "
                                    "another cell")
                if cell["demand_tonnes"] != estimate["total_tonnes"] \
                        or cell["estimate_status"] != estimate["status"] \
                        or cell["missing_drivers"] != list(
                            estimate["missing_drivers"]):
                    problems.append(f"{label}: demand figures do not "
                                    "match the bound estimate")
        elif cell["demand_tonnes"] is not None \
                or cell["estimate_status"] is not None:
            problems.append(f"{label}: figures carried with no bound "
                            "estimate")
        expected_state = pack.DATA_NONE if estimate is None else (
            pack.DATA_PARTIAL if estimate["status"] == "partial"
            else pack.DATA_COMPLETE)
        if cell["data_state"] != expected_state:
            problems.append(f"{label}: data state {cell['data_state']} "
                            f"!= re-derived {expected_state}")
        prior = None
        if cell["prior_estimate_id"] is not None:
            prior = store.get_estimate(cell["prior_estimate_id"])
            if prior is None:
                problems.append(f"{label}: bound prior estimate "
                                f"{cell['prior_estimate_id']} is not in "
                                "the store")
            elif cell["prior_tonnes"] != prior["total_tonnes"]:
                problems.append(f"{label}: prior tonnes do not match "
                                "the bound prior estimate")
        change_pct = None
        if estimate is not None and prior is not None \
                and prior["total_tonnes"]:
            change_pct = round(
                (estimate["total_tonnes"] - prior["total_tonnes"])
                / prior["total_tonnes"] * 100.0, 4)
        if cell["change_pct"] != change_pct \
                or cell["outlook_band"] != pack.outlook_band(change_pct):
            problems.append(f"{label}: outlook does not re-perform "
                            "from the bound estimates")
        gap = None
        if cell["gap_id"] is not None:
            gap = store.get_gap(cell["gap_id"])
            if gap is None:
                problems.append(f"{label}: bound gap {cell['gap_id']} "
                                "is not in the store")
            else:
                if (gap["product"], gap["crop_year"], gap["season"]) != (
                        cell["product"], crop_year, season):
                    problems.append(f"{label}: bound gap is for another "
                                    "scope")
                if cell["product_gap_band"] != gap["band"] \
                        or cell["gap_pct_of_demand"] != gap[
                            "gap_pct_of_demand"] \
                        or cell["programme_cover_pct"] != gap[
                            "programme_cover_pct"]:
                    problems.append(f"{label}: gap figures do not match "
                                    "the bound gap artefact")
        elif cell["product_gap_band"] is not None:
            problems.append(f"{label}: a gap band is carried with no "
                            "bound gap")
        assessment = None
        if cell["assessment_id"] is not None:
            assessment = store.get_field_assessment(cell["assessment_id"])
            if assessment is None:
                problems.append(f"{label}: bound assessment "
                                f"{cell['assessment_id']} is not in "
                                "the store")
            elif cell["adjustment_pct"] != assessment["adjustment_pct"]:
                problems.append(f"{label}: adjustment does not match "
                                "the bound assessment")
        elif cell["adjustment_pct"] is not None:
            problems.append(f"{label}: an adjustment is carried with "
                            "no bound assessment")
        pressure = pack.pressure_band(
            assessment["adjustment_pct"] if assessment else None)
        if cell["pressure_band"] != pressure:
            problems.append(f"{label}: pressure band does not "
                            "re-perform")
        product_band = gap["band"] if gap else None
        readings = [b for b in (product_band, pressure) if b]
        district_band = None
        for band in readings:
            district_band = band if district_band is None \
                else supply_pack.worse_band(district_band, band)
        if product_band is not None and pressure is not None:
            basis = pack.GAP_BASIS_PRODUCT_AND_SIGNALS
        elif product_band is not None:
            basis = pack.GAP_BASIS_PRODUCT_ONLY
        elif pressure is not None:
            basis = pack.GAP_BASIS_SIGNALS_ONLY
        else:
            basis = pack.GAP_BASIS_NONE
        if cell["district_gap_band"] != district_band \
                or cell["district_gap_basis"] != basis:
            problems.append(f"{label}: composed gap band or basis does "
                            "not re-perform")
        expected_signals = _signals_for(
            store, cell["district_id"], cell["product"], crop_year,
            season, map_dict["as_of"])
        if cell["signals"] != expected_signals:
            problems.append(f"{label}: signal layer does not "
                            "re-perform from the reports landed by "
                            "the map's date")
    expected_keys = {
        (product, district_id)
        for product in map_dict["products"] for district_id in districts}
    if seen != expected_keys:
        problems.append(
            f"cell set differs: stored {sorted(seen - expected_keys)} "
            f"extra, {sorted(expected_keys - seen)} missing")
    if map_dict["monsoon"] != _expected_monsoon(store, crop_year, season):
        problems.append("monsoon layer does not re-perform from the facts")
    fingerprint = _fingerprint({
        "scope": [crop_year, season], "pack": pack.RULES_VERSION,
        "cells": map_dict["cells"], "monsoon": map_dict["monsoon"],
    })
    if fingerprint != map_dict["fingerprint"]:
        problems.append("map fingerprint does not re-perform from its cells")
    if render_map_html(map_dict) != map_dict["html"]:
        problems.append("map page does not re-render byte for byte")
    return problems


# ---------------------------------------------------------------------------
# The page — static, read-only, rendered from the artefact alone
# ---------------------------------------------------------------------------

_MAP_CSS = """
.tilegrid { display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 10px; }
.tile { border: 1px solid var(--line); border-left: 6px solid var(--line);
  border-radius: 8px; padding: 10px; min-height: 96px; background: #FFFFFF; }
.tile .dname { font-weight: 700; font-size: 14px; }
.tile .dstate { color: var(--muted); font-size: 12px; }
.tile .fig { font-size: 15px; margin-top: 4px; }
.tile.band-comfortable { border-left-color: #1F9D66; }
.tile.band-tight { border-left-color: #DC6803; background: #FFFBF2; }
.tile.band-short { border-left-color: #D92D20; background: #FFF7F5; }
.tile.mon-deficit { border-left-color: #D92D20; background: #FFF7F5; }
.tile.mon-near_normal { border-left-color: #98A2B3; }
.tile.mon-surplus { border-left-color: #2E6BE6; background: #F5F8FF; }
.tile.partial { background-image: repeating-linear-gradient(
  45deg, rgba(10,10,10,0.07) 0 8px, transparent 8px 16px); }
.tile.nodata { border-style: dashed; color: var(--muted); }
.chip { display: inline-block; border-radius: 999px; padding: 0 7px;
  font-size: 11px; background: var(--lavender); color: var(--indigo-dark);
  margin: 2px 2px 0 0; }
.chip.short { background: #FDECEA; color: var(--bad); }
.chip.tight { background: #FEF3E2; color: var(--warn); }
.chip.comfortable { background: #E7F6EE; color: #146C43; }
.switcher { margin: 10px 0; }
.switcher button { font: inherit; font-size: 13px; margin-right: 6px;
  padding: 4px 12px; border-radius: 999px; border: 1px solid var(--line);
  background: var(--panel); color: var(--ink); cursor: pointer; }
.switcher button.on { background: var(--indigo); color: #FFFFFF;
  border-color: var(--indigo); }
.sig-confirmed { color: #146C43; }
.sig-pending { color: var(--warn); }
.hidden-view { display: none; }
"""

_SWITCH_JS = """
document.querySelectorAll("[data-switch-group]").forEach(function (group) {
  var buttons = group.querySelectorAll("button[data-target]");
  buttons.forEach(function (button) {
    button.addEventListener("click", function () {
      var scope = group.getAttribute("data-switch-scope");
      document.querySelectorAll(
        "[data-view='" + scope + "']").forEach(function (view) {
          view.classList.add("hidden-view");
        });
      buttons.forEach(function (b) { b.classList.remove("on"); });
      button.classList.add("on");
      document.querySelectorAll(
        "[data-view='" + scope + "'][data-view-key='" +
        button.getAttribute("data-target") + "']").forEach(
        function (view) { view.classList.remove("hidden-view"); });
    });
  });
});
"""


def _tile_gap(cell: dict) -> str:
    classes = ["tile"]
    if cell["district_gap_band"]:
        classes.append(f"band-{cell['district_gap_band']}")
    if cell["data_state"] == pack.DATA_PARTIAL:
        classes.append("partial")
    if cell["data_state"] == pack.DATA_NONE:
        classes.append("nodata")
    parts = [f'<div class="{" ".join(classes)}">']
    parts.append(
        f'<div class="dname">{_esc(cell["district_name"])}</div>')
    parts.append(f'<div class="dstate">{_esc(cell["state"])} · '
                 f'{_esc(cell["region"])}</div>')
    if cell["data_state"] == pack.DATA_NONE:
        parts.append(
            '<div class="fig">No data — no estimate artefact for this '
            "district and product</div>")
    else:
        parts.append(
            f'<div class="fig">{_fmt(cell["demand_tonnes"])} t demand</div>')
        if cell["change_pct"] is not None:
            parts.append(
                f'<div><span class="chip">{_esc(cell["outlook_band"])} '
                f'{cell["change_pct"]:+.1f}% vs prior year</span></div>')
        else:
            parts.append(
                '<div><span class="chip">no baseline — no prior-year '
                "estimate</span></div>")
        if cell["district_gap_band"]:
            parts.append(
                f'<div><span class="chip {cell["district_gap_band"]}">'
                f'gap: {_esc(cell["district_gap_band"])}</span></div>')
        else:
            parts.append(
                '<div><span class="chip">no gap evidence</span></div>')
        if cell["data_state"] == pack.DATA_PARTIAL:
            parts.append(
                '<div><span class="chip tight">partial data — missing: '
                f'{_esc(", ".join(cell["missing_drivers"]))}</span></div>')
    parts.append(
        f'<div class="lineage">estimate {_esc(cell["estimate_id"] or "—")} · '
        f'gap {_esc(cell["gap_id"] or "—")} · '
        f'{_esc(pack.GAP_BASIS_TEXT[cell["district_gap_basis"]])}</div>')
    parts.append("</div>")
    return "".join(parts)


def _tile_monsoon(cell: dict, monsoon: dict) -> str:
    band = monsoon["band"]
    parts = [f'<div class="tile mon-{band}">']
    parts.append(
        f'<div class="dname">{_esc(cell["district_name"])}</div>')
    parts.append(f'<div class="dstate">{_esc(cell["state"])} · '
                 f'{_esc(cell["region"])}</div>')
    if monsoon["deviation_pct"] is None:
        parts.append('<div class="fig">No monsoon fact for this district '
                     "and season</div>")
    else:
        parts.append(
            f'<div class="fig">{monsoon["deviation_pct"]:+.1f}% vs '
            "long-period average</div>")
        parts.append(
            f'<div><span class="chip">{_esc(band)}</span></div>')
    parts.append(
        f'<div class="lineage">fact {_esc(monsoon["fact_id"] or "—")} · '
        f'source {_esc(monsoon["source"] or "—")} · '
        f'as of {_esc(monsoon["as_of"] or "—")}</div>')
    parts.append("</div>")
    return "".join(parts)


def _tile_signals(cell: dict) -> str:
    signals = cell["signals"]
    parts = ['<div class="tile">']
    parts.append(
        f'<div class="dname">{_esc(cell["district_name"])}</div>')
    parts.append(f'<div class="dstate">{_esc(cell["state"])} · '
                 f'{_esc(cell["region"])}</div>')
    parts.append(
        f'<div class="fig sig-confirmed">● {len(signals["confirmed"])} '
        "confirmed</div>")
    for entry in signals["confirmed"]:
        parts.append(
            f'<div class="lineage sig-confirmed">{_esc(entry["signal_kind"])}'
            f' — {_esc(entry["reporter"])}, {_esc(entry["observed_on"])} '
            f'({_esc(entry["report_id"])})</div>')
    parts.append(
        f'<div class="fig sig-pending">○ {len(signals["pending"])} '
        "pending — not yet confirmed, never counted with the "
        "confirmed</div>")
    for entry in signals["pending"]:
        parts.append(
            f'<div class="lineage sig-pending">{_esc(entry["signal_kind"])}'
            f' — {_esc(entry["reporter"])}, {_esc(entry["observed_on"])} '
            f'({_esc(entry["report_id"])}, {_esc(entry["review_state"])})'
            "</div>")
    if signals["rejected_count"]:
        parts.append(
            f'<div class="lineage">{signals["rejected_count"]} rejected '
            "report(s) — excluded from both classes</div>")
    parts.append(
        f'<div class="lineage">assessment '
        f'{_esc(cell["assessment_id"] or "—")} · adjustment '
        f'{_fmt(cell["adjustment_pct"]) if cell["adjustment_pct"] is not None else "—"}'
        "</div>")
    parts.append("</div>")
    return "".join(parts)


def render_map_html(map_dict: dict) -> str:
    """The map's page — a pure function of the artefact, so
    a stored page re-renders byte for byte. Switchers only
    show and hide rendered views; nothing on the page can
    change any state anywhere."""
    monsoon_by_district = {m["district_id"]: m for m in map_dict["monsoon"]}
    products = map_dict["products"]
    out = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>District market map — {_esc(map_dict['season'])} "
        f"{_esc(map_dict['crop_year'])} — Kaveri Agro Inputs</title>",
        f"<style>{_CSS}{_MAP_CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        '<p class="lineage">Kaveri Agro Inputs · market intelligence</p>',
        f"<h1>District market map — {_esc(map_dict['season'])} "
        f"{_esc(map_dict['crop_year'])}</h1>",
        f'<p class="muted">As of {_esc(map_dict["as_of"])} · built by '
        f'{_esc(map_dict["built_by"])} · map {map_dict["map_id"]} · '
        f'map pack {map_dict["rules_version"]}. A schematic tile grid '
        "grouped by region — one tile per tracked district, not a "
        "geographic outline. Every tile is composed from named "
        "artefacts and re-performed before this page is served.</p>",
        '<div class="switcher" data-switch-group '
        'data-switch-scope="product">',
    ]
    for index, product in enumerate(products):
        on = " on" if index == 0 else ""
        out.append(
            f'<button type="button" class="sw{on}" data-target="{product}">'
            f"{_esc(product)}</button>")
    out.append("</div>")
    out.append("</header>")
    out.append("<main>")
    for index, product in enumerate(products):
        hidden = "" if index == 0 else " hidden-view"
        out.append(
            f'<section class="product-view{hidden}" data-view="product" '
            f'data-view-key="{product}">')
        out.append(f"<h2>{_esc(product)}</h2>")
        out.append(
            '<div class="switcher" data-switch-group '
            f'data-switch-scope="layer-{product}">')
        for layer_index, (layer_key, layer_label) in enumerate((
                ("gap", "Demand & gap"), ("monsoon", "Monsoon layer"),
                ("signals", "Field signals"))):
            on = " on" if layer_index == 0 else ""
            out.append(
                f'<button type="button" class="sw{on}" '
                f'data-target="{layer_key}">{layer_label}</button>')
        out.append("</div>")
        cells = [c for c in map_dict["cells"] if c["product"] == product]
        for layer_index, layer_key in enumerate(("gap", "monsoon", "signals")):
            hidden = "" if layer_index == 0 else " hidden-view"
            out.append(
                f'<div class="layer-view{hidden}" '
                f'data-view="layer-{product}" data-view-key="{layer_key}">')
            out.append('<div class="tilegrid">')
            for cell in cells:
                if layer_key == "gap":
                    out.append(_tile_gap(cell))
                elif layer_key == "monsoon":
                    out.append(_tile_monsoon(
                        cell, monsoon_by_district[cell["district_id"]]))
                else:
                    out.append(_tile_signals(cell))
            out.append("</div>")
            if layer_key == "signals":
                out.append(
                    '<p class="note">Confirmed signals are solid; pending '
                    "signals — unreviewed or queried — are shown in their "
                    "own labelled class and are never merged into the "
                    "confirmed count. Rejected reports appear in "
                    "neither.</p>")
            if layer_key == "gap":
                out.append(
                    '<p class="note">A hatched tile is partial data: its '
                    "estimate names the drivers it is missing, and it "
                    "never renders as a confident colour. A dashed tile "
                    "has no estimate at all — no data, which is a "
                    "different claim from zero.</p>")
            out.append("</div>")
        out.append("</section>")
    out += [
        "</main>",
        "<footer>",
        "<div>",
        '<div class="footer-brand">'
        '<img src="https://trida.ai/logos-rounded/trida-rounded.png" '
        'alt="Trida AI"><strong>Trida AI</strong></div>',
        '<p class="muted">Figures on this page are artefact figures '
        "re-performed cell for cell before serving. The map composes "
        "and renders; it does not compute a figure of its own, and it "
        "never invents one for a district the data cannot speak "
        "for.</p>",
        "</div>",
        '<div><a href="https://trida.ai/">Visit Trida AI →</a>'
        '<a href="https://github.com/tridaai">View all blueprints →</a>'
        "</div>",
        "</footer>",
        f"<script>{_SWITCH_JS}</script>",
        "</body>",
        "</html>",
    ]
    return "\n".join(out)
