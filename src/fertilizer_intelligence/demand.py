"""The demand-estimation engine (R2).

An estimate is a stated function of stored facts plus the
versioned rule pack in :mod:`.demand_rules` — nothing else. For a
district × product × season the engine:

1. computes **base demand** from cropped area × the stored
   crop-mix application rates, recording every crop that went in
   and every crop excluded for want of a rate;
2. applies the pack's factor rules in a stated order — soil
   nutrient status, monsoon deviation, price elasticity against
   the product's own price series, carry-in stock where supply
   facts exist — each as a recorded contribution line carrying its
   input values and the fact ids they came from;
3. lands on a total that is exactly base + the line deltas.

Honesty rules, enforced here, not in prose:

- A required input that is not in the store makes the estimate
  **partial** and names the missing driver. Nothing is substituted
  — no national average, no silent 1.0.
- A driver that cannot apply (an agrochemical has no soil
  nutrient; MOP has no supply facts) is recorded
  ``not_applicable`` with its reason, factor null, delta zero.
- Every estimate carries the fingerprint of the exact fact set it
  was computed from. Recomputing over an unchanged fact set
  returns the stored artefact; recomputing over changed facts
  stores a new artefact that supersedes the old head by link.
  The old artefact is never edited, and :func:`verify_estimate`
  re-performs any artefact from its own recorded inputs, so a
  tampered line or total is detectable forever.

The outlook for a season is the full district × product grid as
one artefact whose rollups are sums of its member estimates —
computed from the estimates, never independently. The agent step
then drafts the outlook narrative through the model port, and a
figure verifier checks every figure in the draft against the
artefacts before the narrative may be stored; a wrong figure
refuses the draft wholesale.
"""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel

from . import demand_rules as rules
from .generator import PRODUCTS

DRIVER_BASE = "base_area_rates"
DRIVER_SOIL = "soil_nutrient_status"
DRIVER_MONSOON = "monsoon_deviation"
DRIVER_PRICE = "price_elasticity"
DRIVER_CARRY_IN = "carry_in_stock"

DRIVER_LABELS = {
    DRIVER_BASE: "cropped area and application rates",
    DRIVER_SOIL: "soil nutrient status",
    DRIVER_MONSOON: "monsoon deviation",
    DRIVER_PRICE: "price movement",
    DRIVER_CARRY_IN: "carry-in stock",
}

# Display names for narrative text: the product codes carry digits
# (NPK_10_26_26) that a figure extractor would misread as figures.
PRODUCT_DISPLAY = {
    "UREA": "Urea",
    "DAP": "DAP",
    "NPK_10_26_26": "NPK complex",
    "MOP": "MOP",
    "GLYPHOSATE": "Glyphosate",
    "CHLORPYRIFOS": "Chlorpyrifos",
}

# Tonnes are rounded to 3 decimals at every step (the same
# discipline the generator's derivation uses); comparisons allow
# for the rounding of summed parts.
TONNE_TOL = 0.002
FIGURE_TOL = 0.006


class ContributionLine(BaseModel):
    line_no: int
    driver: str
    status: str  # applied / missing / not_applicable
    factor: float | None
    delta_tonnes: float
    value_after_tonnes: float
    inputs: dict


class DemandEstimate(BaseModel):
    estimate_id: str
    district_id: str
    product: str
    crop_year: str
    season: str
    status: str  # complete / partial
    base_tonnes: float
    total_tonnes: float
    missing_drivers: list[str]
    contributions: list[ContributionLine]
    rules_version: str
    rate_table_version: str
    fact_fingerprint: str
    as_of: str
    supersedes: str | None = None


class SeasonOutlook(BaseModel):
    outlook_id: str
    crop_year: str
    season: str
    status: str  # complete / partial
    estimate_count: int
    partial_count: int
    total_tonnes: float
    product_rollups: dict[str, float]
    estimate_ids: list[str]
    rules_version: str
    fact_fingerprint: str
    as_of: str
    supersedes: str | None = None


# -- fact ids -------------------------------------------------------------
# Every stored fact has a stable id built from its natural key, so
# a contribution line can name exactly the rows it consumed.


def _area_fact_id(district_id, crop_year, season, crop):
    return f"area_facts:{district_id}|{crop_year}|{season}|{crop}"


def _rate_fact_id(crop, product):
    return f"application_rates:{crop}|{product}"


def _soil_fact_id(district_id, nutrient):
    return f"soil_facts:{district_id}|{nutrient}"


def _monsoon_fact_id(district_id, crop_year, season):
    return f"monsoon_facts:{district_id}|{crop_year}|{season}"


def _price_fact_id(item, month):
    return f"price_points:product|{item}|{month}"


def _supply_fact_id(product, month):
    return f"supply_facts:{product}|{month}"


def _fingerprint(material) -> str:
    blob = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


# -- the engine -------------------------------------------------------------


def compute_estimate(store, district_id, product, crop_year, season, as_of,
                     elasticity_override=None) -> DemandEstimate:
    """Compute (but do not store) the estimate artefact for one
    district × product × season, from stored facts only.

    ``elasticity_override`` is the R9 scenario fork's stated
    lever: when given, the price line runs with that
    elasticity instead of the pack's, records the pack value
    as its base on the line inputs, and fingerprints the
    override — the estimate is then a fork's result, never a
    head. Base estimates pass no override and are computed
    exactly as before."""
    if product not in PRODUCTS:
        raise ValueError(f"unknown product: {product!r}")
    area_rows = store.area_facts(district_id, crop_year, season)
    if not area_rows:
        raise ValueError(
            f"no area facts for {district_id} {crop_year} {season}: unknown district-season"
        )
    rate_map = {
        (r["crop"], r["product"]): r["rate_kg_ha"] for r in store.application_rates()
    }
    consumed: list = [["triple", district_id, product, crop_year, season],
                      ["rules", rules.RULES_VERSION]]

    # -- base: cropped area x crop-mix application rates ----------------
    crop_lines, excluded = [], []
    base = 0.0
    for row in sorted(area_rows, key=lambda r: r["crop"]):
        crop = row["crop"]
        rate = rate_map.get((crop, product))
        area_id = _area_fact_id(district_id, crop_year, season, crop)
        if rate is None or rate <= 0:
            excluded.append({
                "crop": crop, "reason": "no_application_rate",
                "area_fact_id": area_id,
            })
            continue
        tonnes = row["area_ha"] * rate / 1000.0
        base += tonnes
        crop_lines.append({
            "crop": crop, "area_ha": row["area_ha"], "rate_kg_ha": rate,
            "tonnes": round(tonnes, 3),
            "area_fact_id": area_id, "rate_fact_id": _rate_fact_id(crop, product),
        })
        consumed.append([area_id, row["area_ha"], rate])
    base_tonnes = round(base, 3)
    lines: list[dict] = [{
        "line_no": 0, "driver": DRIVER_BASE, "status": "applied",
        "factor": None, "delta_tonnes": base_tonnes,
        "value_after_tonnes": base_tonnes,
        "inputs": {"crops": crop_lines, "excluded_crops": excluded},
    }]

    # -- soil nutrient status -------------------------------------------
    nutrient = rules.PRODUCT_NUTRIENT[product]
    if nutrient is None:
        lines.append({
            "line_no": 1, "driver": DRIVER_SOIL, "status": "not_applicable",
            "factor": None,
            "inputs": {"reason": "agrochemical products have no soil-nutrient driver"},
        })
    else:
        soil_rows = {r["nutrient"]: r for r in store.soil_facts(district_id)}
        soil = soil_rows.get(nutrient)
        if soil is None:
            lines.append({
                "line_no": 1, "driver": DRIVER_SOIL, "status": "missing",
                "factor": None,
                "inputs": {"nutrient": nutrient,
                           "reason": "no soil fact for this district and nutrient"},
            })
        else:
            fact_id = _soil_fact_id(district_id, nutrient)
            lines.append({
                "line_no": 1, "driver": DRIVER_SOIL, "status": "applied",
                "factor": rules.SOIL_FACTOR[soil["status"]],
                "inputs": {"nutrient": nutrient, "status": soil["status"],
                           "fact_id": fact_id},
            })
            consumed.append([fact_id, soil["status"]])

    # -- monsoon deviation ------------------------------------------------
    monsoon_rows = store.monsoon_facts(district_id, crop_year, season)
    if not monsoon_rows:
        lines.append({
            "line_no": 2, "driver": DRIVER_MONSOON, "status": "missing",
            "factor": None,
            "inputs": {"reason": "no monsoon fact for this district-season"},
        })
    else:
        deviation = monsoon_rows[0]["deviation_pct"]
        fact_id = _monsoon_fact_id(district_id, crop_year, season)
        lines.append({
            "line_no": 2, "driver": DRIVER_MONSOON, "status": "applied",
            "factor": rules.monsoon_factor(season, deviation),
            "inputs": {"season": season, "deviation_pct": deviation,
                       "fact_id": fact_id},
        })
        consumed.append([fact_id, deviation])

    # -- price elasticity ---------------------------------------------------
    price_map = {p["month"]: p["price"] for p in store.price_points("product", product)}
    cur_months = rules.season_price_window(crop_year, season)
    prior_months = rules.prior_price_window(crop_year, season)
    cur_points = [[m, price_map[m]] for m in cur_months if m in price_map]
    prior_points = [[m, price_map[m]] for m in prior_months if m in price_map]
    elasticity = rules.PRICE_ELASTICITY[product]
    if elasticity_override is not None:
        elasticity = elasticity_override
        consumed.append(["elasticity_override", elasticity_override])
    if len(cur_points) < rules.MIN_WINDOW_MONTHS or len(prior_points) < rules.MIN_WINDOW_MONTHS:
        lines.append({
            "line_no": 3, "driver": DRIVER_PRICE, "status": "missing",
            "factor": None,
            "inputs": {
                "elasticity": elasticity,
                "current_window": cur_months, "prior_window": prior_months,
                "current_months_present": [m for m, _ in cur_points],
                "prior_months_present": [m for m, _ in prior_points],
                "min_months_required": rules.MIN_WINDOW_MONTHS,
                "reason": "price history too short in at least one window",
            },
        })
    else:
        cur_mean = sum(v for _, v in cur_points) / len(cur_points)
        prior_mean = sum(v for _, v in prior_points) / len(prior_points)
        change = (cur_mean - prior_mean) / prior_mean
        lines.append({
            "line_no": 3, "driver": DRIVER_PRICE, "status": "applied",
            "factor": 1.0 + elasticity * change,
            "inputs": {
                "elasticity": elasticity,
                **({"elasticity_base": rules.PRICE_ELASTICITY[product],
                    "elasticity_source": "scenario_lever"}
                   if elasticity_override is not None else {}),
                "current_points": cur_points, "prior_points": prior_points,
                "current_mean": round(cur_mean, 4), "prior_mean": round(prior_mean, 4),
                "change_pct": round(change, 6),
                "fact_ids": [_price_fact_id(product, m) for m, _ in cur_points + prior_points],
            },
        })
        for month, value in cur_points + prior_points:
            consumed.append([_price_fact_id(product, month), value])

    # -- carry-in stock ------------------------------------------------------
    supply_map = {r["month"]: r for r in store.supply_facts(product)}
    if not supply_map:
        lines.append({
            "line_no": 4, "driver": DRIVER_CARRY_IN, "status": "not_applicable",
            "factor": None,
            "inputs": {"reason": "no supply facts exist for this product"},
        })
    else:
        window = rules.carry_in_window(crop_year, season)
        present = [[m, supply_map[m]["planned_tonnes"], supply_map[m]["actual_tonnes"]]
                   for m in window if m in supply_map]
        if len(present) < rules.CARRY_IN_WINDOW_MONTHS:
            lines.append({
                "line_no": 4, "driver": DRIVER_CARRY_IN, "status": "missing",
                "factor": None,
                "inputs": {
                    "window": window,
                    "months_present": [m for m, _, _ in present],
                    "months_missing": [m for m in window if m not in supply_map],
                    "reason": "supply history does not cover the full carry-in window",
                },
            })
            for month, planned, actual in present:
                consumed.append([_supply_fact_id(product, month), planned, actual])
        else:
            planned_total = sum(p for _, p, _ in present)
            actual_total = sum(a for _, _, a in present)
            share = (actual_total - planned_total) / planned_total
            lines.append({
                "line_no": 4, "driver": DRIVER_CARRY_IN, "status": "applied",
                "factor": rules.stock_factor(share),
                "inputs": {
                    "window_points": present,
                    "planned_tonnes": planned_total, "actual_tonnes": actual_total,
                    "surplus_share": round(share, 6),
                    "fact_ids": [_supply_fact_id(product, m) for m, _, _ in present],
                },
            })
            for month, planned, actual in present:
                consumed.append([_supply_fact_id(product, month), planned, actual])

    # -- apply the factors in the stated order ------------------------------
    value = base_tonnes
    missing: list[str] = []
    for line in lines[1:]:
        if line["status"] == "applied":
            new_value = round(value * line["factor"], 3)
            line["delta_tonnes"] = round(new_value - value, 3)
            value = new_value
        else:
            line["delta_tonnes"] = 0.0
            if line["status"] == "missing":
                missing.append(line["driver"])
        line["value_after_tonnes"] = value

    fingerprint = _fingerprint(consumed)
    estimate_id = (
        f"EST-{district_id}-{product}-{crop_year}-{season}-{fingerprint[:10]}"
    )
    return DemandEstimate(
        estimate_id=estimate_id,
        district_id=district_id, product=product,
        crop_year=crop_year, season=season,
        status="partial" if missing else "complete",
        base_tonnes=base_tonnes, total_tonnes=value,
        missing_drivers=missing,
        contributions=[ContributionLine(**line) for line in lines],
        rules_version=rules.RULES_VERSION,
        rate_table_version=rules.RATE_TABLE_VERSION,
        fact_fingerprint=fingerprint,
        as_of=as_of,
    )


def head_of(rows: list[dict], id_key: str) -> dict | None:
    """The current artefact in a supersession chain: the one no
    other artefact in the group supersedes from."""
    superseded = {r["supersedes"] for r in rows if r.get("supersedes")}
    heads = [r for r in rows if r[id_key] not in superseded]
    return heads[0] if heads else None


# -- re-performance: the verifier ------------------------------------------


def _factor_from_inputs(driver: str, inputs: dict, season: str) -> float | None:
    """Re-derive an applied line's factor from its recorded inputs
    and the rule pack — the verifier's half of the engine."""
    if driver == DRIVER_SOIL:
        return rules.SOIL_FACTOR[inputs["status"]]
    if driver == DRIVER_MONSOON:
        return rules.monsoon_factor(season, inputs["deviation_pct"])
    if driver == DRIVER_PRICE:
        cur = [v for _, v in inputs["current_points"]]
        prior = [v for _, v in inputs["prior_points"]]
        change = (sum(cur) / len(cur) - sum(prior) / len(prior)) / (sum(prior) / len(prior))
        return 1.0 + inputs["elasticity"] * change
    if driver == DRIVER_CARRY_IN:
        planned = sum(p for _, p, _ in inputs["window_points"])
        actual = sum(a for _, _, a in inputs["window_points"])
        return rules.stock_factor((actual - planned) / planned)
    return None


def verify_estimate(estimate: dict, contributions: list[dict]) -> list[str]:
    """Re-perform a stored estimate from its own recorded inputs.

    Returns the list of problems found (empty = the artefact is
    exactly what the engine would produce from those inputs).
    Because re-performance runs off the artefact itself, it keeps
    working after the underlying facts have moved on and the
    estimate has been superseded.
    """
    problems: list[str] = []
    lines = sorted(contributions, key=lambda line: line["line_no"])
    if [line["driver"] for line in lines] != [
        DRIVER_BASE, DRIVER_SOIL, DRIVER_MONSOON, DRIVER_PRICE, DRIVER_CARRY_IN,
    ]:
        return ["contribution lines do not match the stated driver order"]

    base_line = lines[0]
    recomputed_base = round(
        sum(c["area_ha"] * c["rate_kg_ha"] / 1000.0 for c in base_line["inputs"]["crops"]), 3
    )
    if abs(recomputed_base - estimate["base_tonnes"]) > TONNE_TOL:
        problems.append(
            f"base {estimate['base_tonnes']} != recomputed {recomputed_base} from recorded crops"
        )
    if abs(base_line["delta_tonnes"] - estimate["base_tonnes"]) > TONNE_TOL:
        problems.append("base line delta does not equal the estimate base")

    value = estimate["base_tonnes"]
    missing: list[str] = []
    for line in lines[1:]:
        if line["status"] == "applied":
            factor = _factor_from_inputs(line["driver"], line["inputs"], estimate["season"])
            if factor is None or line["factor"] is None or abs(factor - line["factor"]) > 1e-6:
                problems.append(
                    f"{line['driver']}: recorded factor {line['factor']} != re-derived {factor}"
                )
                continue
            new_value = round(value * factor, 3)
            if abs(line["delta_tonnes"] - round(new_value - value, 3)) > TONNE_TOL:
                problems.append(
                    f"{line['driver']}: delta {line['delta_tonnes']} != re-performed "
                    f"{round(new_value - value, 3)}"
                )
            if abs(line["value_after_tonnes"] - new_value) > TONNE_TOL:
                problems.append(
                    f"{line['driver']}: value_after {line['value_after_tonnes']} != {new_value}"
                )
            value = new_value
        else:
            if line["delta_tonnes"] != 0.0 or line["factor"] is not None:
                problems.append(
                    f"{line['driver']}: a {line['status']} line must carry factor null, delta 0"
                )
            if abs(line["value_after_tonnes"] - value) > TONNE_TOL:
                problems.append(f"{line['driver']}: value_after moved on a non-applied line")
            if line["status"] == "missing":
                missing.append(line["driver"])
    if abs(value - estimate["total_tonnes"]) > TONNE_TOL:
        problems.append(
            f"total {estimate['total_tonnes']} != base + deltas {round(value, 3)}"
        )
    if missing != list(estimate["missing_drivers"]):
        problems.append(
            f"missing_drivers {estimate['missing_drivers']} != missing lines {missing}"
        )
    expected_status = "partial" if missing else "complete"
    if estimate["status"] != expected_status:
        problems.append(f"status {estimate['status']} != {expected_status}")
    return problems


# -- the outlook -------------------------------------------------------------


def build_outlook(estimates: list[dict], crop_year: str, season: str, as_of: str) -> SeasonOutlook:
    """Assemble the season outlook from its member estimates. The
    rollups are sums of the estimates — there is no second,
    independent aggregation anywhere."""
    product_rollups: dict[str, float] = {}
    for estimate in estimates:
        product_rollups[estimate["product"]] = round(
            product_rollups.get(estimate["product"], 0.0) + estimate["total_tonnes"], 3
        )
    total = round(sum(product_rollups.values()), 3)
    partial_count = sum(1 for e in estimates if e["status"] == "partial")
    fingerprint = _fingerprint({
        "season": [crop_year, season],
        "rules": rules.RULES_VERSION,
        "estimates": sorted(e["estimate_id"] for e in estimates),
    })
    return SeasonOutlook(
        outlook_id=f"OUT-{crop_year}-{season}-{fingerprint[:10]}",
        crop_year=crop_year, season=season,
        status="partial" if partial_count else "complete",
        estimate_count=len(estimates), partial_count=partial_count,
        total_tonnes=total, product_rollups=product_rollups,
        estimate_ids=[e["estimate_id"] for e in estimates],
        rules_version=rules.RULES_VERSION,
        fact_fingerprint=fingerprint,
        as_of=as_of,
    )


def verify_outlook(store, outlook: dict) -> list[str]:
    """The rollup identity, graded: product rollups equal the sums
    of their member estimates, and the total equals the rollups."""
    problems: list[str] = []
    sums: dict[str, float] = {}
    partial = 0
    for estimate_id in outlook["estimate_ids"]:
        estimate = store.get_estimate(estimate_id)
        if estimate is None:
            problems.append(f"outlook member {estimate_id} is not in the store")
            continue
        sums[estimate["product"]] = sums.get(estimate["product"], 0.0) + estimate["total_tonnes"]
        partial += 1 if estimate["status"] == "partial" else 0
    for product, rolled in outlook["product_rollups"].items():
        if abs(rolled - round(sums.get(product, 0.0), 3)) > TONNE_TOL:
            problems.append(
                f"rollup {product} {rolled} != sum of estimates {round(sums.get(product, 0.0), 3)}"
            )
    if set(sums) != set(outlook["product_rollups"]):
        problems.append("rollup products do not match the member estimates' products")
    if abs(outlook["total_tonnes"] - round(sum(outlook["product_rollups"].values()), 3)) > TONNE_TOL:
        problems.append("outlook total != sum of product rollups")
    if outlook["estimate_count"] != len(outlook["estimate_ids"]):
        problems.append("estimate_count != number of member estimates")
    if outlook["partial_count"] != partial:
        problems.append("partial_count != number of partial member estimates")
    return problems


# -- figures: extraction and verification -------------------------------------

_DATE_LIKE = re.compile(r"\d{4}-\d{2}(-\d{2})?")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def extract_figures(text: str, strip_tokens=()) -> list[float]:
    """The numeric tokens in a piece of text, with dates, years and
    the caller's known non-figure tokens (product codes) removed."""
    cleaned = text
    for token in strip_tokens:
        cleaned = cleaned.replace(token, " ")
    cleaned = _DATE_LIKE.sub(" ", cleaned)
    cleaned = _YEAR.sub(" ", cleaned)
    return [float(m.group()) for m in _NUMBER.finditer(cleaned)]


def figure_universe(outlook: dict, estimates: list[dict]) -> list[float]:
    """Every figure a narrative about this outlook may state: the
    estimates' bases, totals and line movements, the rollups, the
    grand total, and the counts."""
    universe = {0.0, outlook["total_tonnes"], float(outlook["estimate_count"]),
                float(outlook["partial_count"])}
    universe.update(float(v) for v in outlook["product_rollups"].values())
    districts = set()
    for estimate in estimates:
        districts.add(estimate["district_id"])
        universe.add(estimate["base_tonnes"])
        universe.add(estimate["total_tonnes"])
        for line in estimate["contributions"]:
            universe.add(line["delta_tonnes"])
            universe.add(line["value_after_tonnes"])
    universe.add(float(len(districts)))
    universe.add(float(len(outlook["product_rollups"])))
    return sorted(universe)


def verify_figures(text: str, universe: list[float], strip_tokens=()) -> list[str]:
    problems = []
    for value in extract_figures(text, strip_tokens):
        if not any(abs(value - allowed) <= FIGURE_TOL for allowed in universe):
            problems.append(f"figure {value} is not in the artefacts' figure set")
    return problems


class NarrativeRefused(RuntimeError):
    """A drafted narrative failed figure verification and was
    refused wholesale — nothing of it is stored."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("narrative refused: " + "; ".join(problems))


class OutlookNarrator:
    """The agent step: draft the outlook narrative through the
    model port, verify every figure, only then store."""

    def __init__(self, store, model):
        self.store = store
        self.model = model

    def _estimates_with_lines(self, outlook: dict) -> list[dict]:
        estimates = []
        for estimate_id in outlook["estimate_ids"]:
            estimate = self.store.get_estimate(estimate_id)
            estimate["contributions"] = self.store.estimate_contributions(estimate_id)
            estimates.append(estimate)
        return estimates

    def payload(self, outlook: dict, estimates: list[dict]) -> str:
        district_names = {d["district_id"]: d["name"] for d in self.store.list_districts()}
        by_product = "; ".join(
            f"{PRODUCT_DISPLAY.get(p, p)} {v:.2f} tonnes"
            for p, v in sorted(outlook["product_rollups"].items())
        )
        largest = max(estimates, key=lambda e: e["total_tonnes"])
        movement, movement_line = None, None
        for estimate in estimates:
            for line in estimate["contributions"]:
                if line["driver"] == DRIVER_BASE:
                    continue
                if movement is None or abs(line["delta_tonnes"]) > abs(movement_line["delta_tonnes"]):
                    movement, movement_line = estimate, line
        n_districts = len({e["district_id"] for e in estimates})
        lines = [
            f"Season outlook — {outlook['season']}, crop year {outlook['crop_year']}.",
            f"{outlook['estimate_count']} district-product demand estimates across "
            f"{n_districts} districts; {outlook['partial_count']} of them are partial, "
            "with the missing drivers named on the estimates themselves.",
            f"Total estimated demand is {outlook['total_tonnes']:.2f} tonnes.",
            f"By product: {by_product}.",
            f"Largest single estimate: {district_names.get(largest['district_id'], largest['district_id'])} "
            f"{PRODUCT_DISPLAY.get(largest['product'], largest['product'])} at "
            f"{largest['total_tonnes']:.2f} tonnes, from a base of {largest['base_tonnes']:.2f} tonnes.",
            f"Largest single driver movement: the {DRIVER_LABELS[movement_line['driver']]} adjustment "
            f"moved {district_names.get(movement['district_id'], movement['district_id'])} "
            f"{PRODUCT_DISPLAY.get(movement['product'], movement['product'])} by "
            f"{movement_line['delta_tonnes']:.2f} tonnes.",
        ]
        return "\n".join(lines)

    def draft(self, outlook: dict, as_of: str) -> dict:
        estimates = self._estimates_with_lines(outlook)
        payload = self.payload(outlook, estimates)
        reply = self.model.complete(
            "You draft market outlook narratives from computed figures. "
            "State only the figures you are given; never invent one.",
            payload,
        )
        universe = figure_universe(outlook, estimates)
        problems = verify_figures(reply.text, universe, strip_tokens=PRODUCTS)
        if problems:
            raise NarrativeRefused(problems)
        figures = extract_figures(reply.text, strip_tokens=PRODUCTS)
        narrative_id = "NAR-" + _fingerprint({
            "outlook": outlook["outlook_id"], "text": reply.text,
        })[:12]
        existing = self.store.get_narrative(narrative_id)
        if existing is not None:
            return existing
        row = {
            "narrative_id": narrative_id,
            "outlook_id": outlook["outlook_id"],
            "text": reply.text,
            "model_profile": reply.profile,
            "model_name": reply.model,
            "figures": figures,
            "as_of": as_of,
        }
        self.store.insert_narrative(row)
        return row

    def verify_stored(self, narrative: dict) -> list[str]:
        outlook = self.store.get_outlook(narrative["outlook_id"])
        if outlook is None:
            return ["narrative's outlook is not in the store"]
        estimates = self._estimates_with_lines(outlook)
        return verify_figures(
            narrative["text"], figure_universe(outlook, estimates), strip_tokens=PRODUCTS
        )
