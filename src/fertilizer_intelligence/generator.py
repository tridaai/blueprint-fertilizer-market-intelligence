"""The dataset generator — gold by construction.

The dataset for Kaveri Agro Inputs is generated in this repo by a
deterministic, seeded generator. That is a deliberate design choice,
stated here once: there is no openly licensed Indian district-level
fertilizer dataset with the provenance this blueprint needs, so the
data is built — and because it is built, every planted fact is known
truth. The generator plants:

- **one price spike** (DAP, September 2025, +38% over its trend value,
  decaying the following month),
- **one import delay** (a DAP shipment expected October 2025 that
  arrives December 2025),
- a fixed set of **policy events** and **field reports**,

and records all of them in a **manifest**. Later rounds' engines and
the eval gate grade against the manifest, never against expectations
re-derived by hand.

Consumption is *derived*, not invented: for each district × season ×
product it is computed from stored inputs alone — cropped area,
stated application rates (kg/ha), the district's soil nutrient
status, and the season's monsoon deviation — by the stated rules in
:func:`derive_consumption`. The eval gate re-derives consumption
from the store and compares, so the numbers are provable from the
generator's inputs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date

from . import models
from .demand_rules import PRODUCT_NUTRIENT, SOIL_FACTOR, monsoon_factor

GENERATOR_VERSION = "1.0.0"
SEED = 20261027

CROP_YEARS = ["2024-25", "2025-26"]
SEASONS = ["kharif", "rabi"]
MONTHS = [f"{y}-{m:02d}" for y, ms in ((2024, range(4, 13)), (2025, range(1, 13)), (2026, range(1, 4))) for m in ms]

# district_id, name, state, region, gross cropped area (ha, stated scale)
DISTRICTS = [
    ("DST-LUD", "Ludhiana", "Punjab", "north", 298_000),
    ("DST-KAR", "Karnal", "Haryana", "north", 262_000),
    ("DST-LKO", "Lucknow", "Uttar Pradesh", "north", 231_000),
    ("DST-KOT", "Kota", "Rajasthan", "west", 244_000),
    ("DST-RAJ", "Rajkot", "Gujarat", "west", 287_000),
    ("DST-IND", "Indore", "Madhya Pradesh", "central", 276_000),
    ("DST-NAG", "Nagpur", "Maharashtra", "central", 318_000),
    ("DST-GUN", "Guntur", "Andhra Pradesh", "south", 254_000),
    ("DST-WAR", "Warangal", "Telangana", "south", 229_000),
    ("DST-BEL", "Belagavi", "Karnataka", "south", 266_000),
    ("DST-PAT", "Patna", "Bihar", "east", 218_000),
    ("DST-BAR", "Bardhaman", "West Bengal", "east", 249_000),
]

KHARIF_CROPS = ["rice", "maize", "soybean", "cotton", "groundnut", "sugarcane"]
RABI_CROPS = ["wheat", "mustard", "chickpea", "maize", "groundnut", "vegetables"]

# Crops a region does not grow at scale — keeps crop mixes plausible.
REGION_EXCLUDES = {
    "north": {"soybean"},
    "west": set(),
    "central": set(),
    "south": {"mustard", "chickpea"},
    "east": {"soybean", "cotton"},
}

PRODUCTS = ["UREA", "DAP", "NPK_10_26_26", "MOP", "GLYPHOSATE", "CHLORPYRIFOS"]
FEEDSTOCKS = ["NATURAL_GAS", "AMMONIA", "PHOSPHORIC_ACID", "SULPHUR"]
COMPETITORS = ["AgroNutrient Ltd", "BharatFert Corp", "Sagar Chemicals"]
REGIONS = ["north", "south", "east", "west", "central"]

# Stated application rates, kg of product per hectare by crop.
RATES = {
    #            UREA   DAP   NPK    MOP   GLYPH  CHLOR
    "rice":      (120,   45,   30,    20,   0,     0.8),
    "wheat":     (130,   55,   20,    15,   0,     0),
    "maize":     (140,   50,   35,    20,   1.2,   0),
    "soybean":   (25,    60,   40,    25,   1.5,   0),
    "cotton":    (110,   50,   30,    30,   1.5,   1.2),
    "groundnut": (30,    45,   35,    30,   0,     1.0),
    "sugarcane": (220,   70,   50,    45,   1.0,   0),
    "mustard":   (70,    40,   20,    15,   0,     0),
    "chickpea":  (20,    45,   25,    15,   0,     0),
    "vegetables":(150,   60,   60,    40,   0,     1.0),
}

# The soil factors, the product->nutrient map and the monsoon
# response rule live in demand_rules.py — the versioned rule pack
# the R2 demand engine also computes from, so the generator and
# the engine can never drift onto two statements of the same rule.
# They are imported at the top of this module and re-exported here
# for the derivation below.


def derive_consumption(area_facts, rates, soil_facts, monsoon_facts) -> dict:
    """Re-derive consumption from stored inputs alone.

    Returns {(district_id, crop_year, season, product): tonnes}.
    This is the single stated derivation; the generator uses it to
    produce consumption facts and the eval gate uses it to prove
    them. Rounding: 3 decimals, applied once per output cell.
    """
    rate_map = {(r["crop"], r["product"]): r["rate_kg_ha"] for r in rates}
    soil_map = {(s["district_id"], s["nutrient"]): s["status"] for s in soil_facts}
    monsoon_map = {
        (m["district_id"], m["crop_year"], m["season"]): m["deviation_pct"]
        for m in monsoon_facts
    }
    out: dict[tuple, float] = {}
    for area in area_facts:
        key_base = (area["district_id"], area["crop_year"], area["season"])
        m_factor = monsoon_factor(area["season"], monsoon_map[key_base])
        for product in PRODUCTS:
            rate = rate_map.get((area["crop"], product), 0.0)
            if rate <= 0:
                continue
            nutrient = PRODUCT_NUTRIENT[product]
            s_factor = SOIL_FACTOR[soil_map[(area["district_id"], nutrient)]] if nutrient else 1.0
            tonnes = area["area_ha"] * rate / 1000.0 * s_factor * m_factor
            key = key_base + (product,)
            out[key] = out.get(key, 0.0) + tonnes
    return {key: round(value, 3) for key, value in out.items()}


@dataclass
class Dataset:
    districts: list[models.District] = field(default_factory=list)
    area_facts: list[models.AreaFact] = field(default_factory=list)
    monsoon_facts: list[models.MonsoonFact] = field(default_factory=list)
    soil_facts: list[models.SoilFact] = field(default_factory=list)
    application_rates: list[models.ApplicationRate] = field(default_factory=list)
    consumption_facts: list[models.ConsumptionFact] = field(default_factory=list)
    price_points: list[models.PricePoint] = field(default_factory=list)
    import_arrivals: list[models.ImportArrival] = field(default_factory=list)
    supply_facts: list[models.SupplyFact] = field(default_factory=list)
    competitor_points: list[models.CompetitorPoint] = field(default_factory=list)
    policy_events: list[models.PolicyEvent] = field(default_factory=list)
    field_reports: list[models.FieldReport] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)


def _month_end(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    if mon == 12:
        return f"{year}-12-31"
    from datetime import timedelta

    return (date(year, mon + 1, 1) - timedelta(days=1)).isoformat()


def generate_dataset() -> Dataset:
    rng = random.Random(SEED)
    ds = Dataset()

    # -- districts, area, crop mix -------------------------------------
    districts = [
        models.District(district_id=d[0], name=d[1], state=d[2], region=d[3])
        for d in DISTRICTS
    ]
    ds.districts = districts
    region_of = {d[0]: d[3] for d in DISTRICTS}
    gross_area = {d[0]: d[4] for d in DISTRICTS}

    for d_id, _name, _state, region, gross in DISTRICTS:
        for year_idx, year in enumerate(CROP_YEARS):
            for season, crops in (("kharif", KHARIF_CROPS), ("rabi", RABI_CROPS)):
                grown = [c for c in crops if c not in REGION_EXCLUDES.get(region, set())]
                weights = {c: rng.uniform(0.4, 1.6) for c in grown}
                # Anchor crops dominate, as they do in the field.
                anchor = "rice" if season == "kharif" else "wheat"
                if anchor in weights:
                    weights[anchor] = rng.uniform(2.2, 3.0)
                total_w = sum(weights.values())
                season_area = gross * (0.92 if season == "kharif" else 0.74)
                year_factor = 1.0 + 0.02 * year_idx
                for crop in grown:
                    area = season_area * weights[crop] / total_w * year_factor
                    ds.area_facts.append(models.AreaFact(
                        district_id=d_id, crop_year=year, season=season, crop=crop,
                        area_ha=round(area, 1),
                        source="district_crop_statistics",
                        as_of=f"{year[:4]}-{'10-31' if season == 'kharif' else '04-30'}",
                    ))

    # -- monsoon ---------------------------------------------------------
    region_base = {"north": -2.0, "south": 4.0, "east": 7.0, "west": -6.0, "central": 1.0}
    for d_id, _n, _s, region, _g in DISTRICTS:
        for year_idx, year in enumerate(CROP_YEARS):
            for season in SEASONS:
                base = region_base[region] + (3.0 if year_idx == 1 and season == "kharif" else 0.0)
                if season == "rabi":
                    base = base / 3.0
                deviation = round(base + rng.uniform(-6.0, 6.0), 1)
                ds.monsoon_facts.append(models.MonsoonFact(
                    district_id=d_id, crop_year=year, season=season,
                    deviation_pct=deviation,
                    source="rainfall_grid_estimate",
                    as_of=f"{year[:4]}-{'09-30' if season == 'kharif' else '02-28'}",
                ))

    # -- soil ------------------------------------------------------------
    statuses = ["low", "medium", "high"]
    for idx, (d_id, *_rest) in enumerate(DISTRICTS):
        for n_idx, nutrient in enumerate(("nitrogen", "phosphorus", "potassium")):
            # Deterministic pattern: nitrogen short almost everywhere,
            # phosphorus mixed, potassium better in the west/south.
            status = statuses[(idx + n_idx) % 3] if nutrient != "nitrogen" else ("low" if idx % 3 else "medium")
            ds.soil_facts.append(models.SoilFact(
                district_id=d_id, nutrient=nutrient, status=status,
                source="soil_health_card_survey", as_of="2024-03-31",
            ))

    # -- application rates (stored as data) ------------------------------
    for crop, row in RATES.items():
        for product, rate in zip(PRODUCTS, row):
            if rate > 0:
                ds.application_rates.append(models.ApplicationRate(
                    crop=crop, product=product, rate_kg_ha=float(rate)))

    # -- consumption, derived from the inputs above ----------------------
    derived = derive_consumption(
        [f.model_dump() for f in ds.area_facts],
        [r.model_dump() for r in ds.application_rates],
        [f.model_dump() for f in ds.soil_facts],
        [f.model_dump() for f in ds.monsoon_facts],
    )
    for (d_id, year, season, product), tonnes in sorted(derived.items()):
        ds.consumption_facts.append(models.ConsumptionFact(
            district_id=d_id, crop_year=year, season=season, product=product,
            quantity_tonnes=tonnes,
            source="consumption_estimate_from_area_rates",
            as_of=f"{year[:4]}-{'11-30' if season == 'kharif' else '05-31'}",
        ))

    # -- prices ------------------------------------------------------------
    product_base = {
        "UREA": (5920.0, "INR/tonne"), "DAP": (27000.0, "INR/tonne"),
        "NPK_10_26_26": (29400.0, "INR/tonne"), "MOP": (34000.0, "INR/tonne"),
        "GLYPHOSATE": (385000.0, "INR/tonne"), "CHLORPYRIFOS": (310000.0, "INR/tonne"),
    }
    feedstock_base = {
        "NATURAL_GAS": (12.50, "USD/MMBtu"), "AMMONIA": (520.0, "USD/tonne"),
        "PHOSPHORIC_ACID": (1050.0, "USD/tonne"), "SULPHUR": (165.0, "USD/tonne"),
    }
    spike = {"series_kind": "product", "item": "DAP", "month": "2025-09",
             "magnitude_pct": 38.0, "decay_month": "2025-10", "decay_pct": 18.0}
    for kind, table in (("product", product_base), ("feedstock", feedstock_base)):
        for item, (base_price, unit) in table.items():
            price = base_price
            for month in MONTHS:
                price = price * (1 + rng.uniform(-0.012, 0.014))
                value = round(price, 2)
                if kind == "product" and item == spike["item"] and month == spike["month"]:
                    spike["baseline_price"] = value
                    value = round(value * (1 + spike["magnitude_pct"] / 100.0), 2)
                    spike["planted_price"] = value
                elif kind == "product" and item == spike["item"] and month == spike["decay_month"]:
                    value = round(value * (1 + spike["decay_pct"] / 100.0), 2)
                ds.price_points.append(models.PricePoint(
                    series_kind=kind, item=item, month=month, price=value, unit=unit,
                    source="market_price_tracking", as_of=_month_end(month),
                ))

    # -- imports, with one planted delay ----------------------------------
    shipments = [
        # shipment_id, product, expected, arrived, tonnes, origin
        ("IMP-UREA-2406", "UREA", "2024-06", "2024-06", 82000, "Oman"),
        ("IMP-DAP-2407", "DAP", "2024-07", "2024-07", 64000, "Morocco"),
        ("IMP-MOP-2408", "MOP", "2024-08", "2024-08", 48000, "Canada"),
        ("IMP-DAP-2411", "DAP", "2024-11", "2024-11", 58000, "Saudi Arabia"),
        ("IMP-MOP-2502", "MOP", "2025-02", "2025-02", 51000, "Belarus"),
        ("IMP-UREA-2505", "UREA", "2025-05", "2025-05", 77000, "Qatar"),
        ("IMP-DAP-2507", "DAP", "2025-07", "2025-07", 61000, "Morocco"),
        ("IMP-DAP-2510", "DAP", "2025-10", "2025-12", 55000, "Jordan"),  # planted delay
        ("IMP-MOP-2511", "MOP", "2025-11", "2025-11", 46000, "Canada"),
        ("IMP-UREA-2601", "UREA", "2026-01", "2026-01", 80000, "Oman"),
    ]
    for sid, product, expected, arrived, tonnes, origin in shipments:
        ds.import_arrivals.append(models.ImportArrival(
            shipment_id=sid, product=product, expected_month=expected,
            arrived_month=arrived, quantity_tonnes=float(tonnes), origin=origin,
            source="port_arrival_records", as_of=_month_end(arrived),
        ))
    delay = {"shipment_id": "IMP-DAP-2510", "product": "DAP",
             "expected_month": "2025-10", "arrived_month": "2025-12",
             "quantity_tonnes": 55000.0}

    # -- domestic production vs plan ---------------------------------------
    plan_base = {"UREA": 2_350_000, "DAP": 380_000, "NPK_10_26_26": 720_000, "MOP": 0}
    for product, base in plan_base.items():
        if base == 0:
            continue
        for i, month in enumerate(MONTHS):
            planned = base * (1 + 0.12 * ((i % 12) in (4, 5, 9)))  # pre-season build-up
            actual = planned * rng.uniform(0.90, 1.02)
            ds.supply_facts.append(models.SupplyFact(
                product=product, month=month,
                planned_tonnes=round(planned, 1), actual_tonnes=round(actual, 1),
                source="industry_production_returns", as_of=_month_end(month),
            ))

    # -- competitors ---------------------------------------------------------
    for comp in COMPETITORS:
        for region in REGIONS:
            for product in ("UREA", "DAP"):
                volume = rng.uniform(18_000, 60_000)
                price = product_base[product][0] * rng.uniform(0.97, 1.05)
                for month in MONTHS:
                    volume = volume * (1 + rng.uniform(-0.05, 0.06))
                    price = price * (1 + rng.uniform(-0.008, 0.009))
                    ds.competitor_points.append(models.CompetitorPoint(
                        competitor=comp, region=region, product=product, month=month,
                        volume_tonnes=round(volume, 1), price=round(price, 2),
                        source="competitor_field_tracking", as_of=_month_end(month),
                    ))

    # -- policy events -------------------------------------------------------
    ds.policy_events = [
        models.PolicyEvent(event_id="POL-2024-001", date="2024-04-01", kind="subsidy_change",
            title="Nutrient-based subsidy rates revised for kharif",
            detail="Per-nutrient subsidy rates for P and K revised upward for the kharif season.",
            expected_impact="DAP and MOP retail prices held; manufacturer realisation improves on P&K grades.",
            impacted_products=["DAP", "MOP", "NPK_10_26_26"],
            source="policy_gazette_watch", as_of="2024-04-01"),
        models.PolicyEvent(event_id="POL-2024-002", date="2024-06-15", kind="mrp_notification",
            title="Urea MRP notification unchanged",
            detail="Statutory urea MRP retained at the prevailing level for the season.",
            expected_impact="No urea retail price movement expected from policy this season.",
            impacted_products=["UREA"], source="policy_gazette_watch", as_of="2024-06-15"),
        models.PolicyEvent(event_id="POL-2025-001", date="2025-02-01", kind="state_scheme",
            title="State top-up scheme for soil-health-linked purchases",
            detail="One large state announces a top-up incentive on complex fertilizers bought against soil health cards.",
            expected_impact="NPK demand in the state's districts expected to firm during rabi sowing.",
            impacted_products=["NPK_10_26_26"], source="policy_gazette_watch", as_of="2025-02-01"),
        models.PolicyEvent(event_id="POL-2025-002", date="2025-08-20", kind="subsidy_change",
            title="Special subsidy package on DAP imports",
            detail="A special package is announced to hold DAP retail prices despite high import costs.",
            expected_impact="DAP MRP expected to remain capped even if import parity rises.",
            impacted_products=["DAP"], source="policy_gazette_watch", as_of="2025-08-20"),
        models.PolicyEvent(event_id="POL-2025-003", date="2025-09-05", kind="import_policy",
            title="Export restrictions tighten in a major DAP-origin country",
            detail="A key origin country restricts fertilizer exports for the quarter.",
            expected_impact="Spot DAP prices expected to spike; import arrivals expected to slip.",
            impacted_products=["DAP", "PHOSPHORIC_ACID"], source="policy_gazette_watch", as_of="2025-09-05"),
        models.PolicyEvent(event_id="POL-2026-001", date="2026-01-10", kind="subsidy_change",
            title="Nutrient-based subsidy rates revised for rabi",
            detail="Rabi NBS rates published; sulphur nutrient rate adjusted.",
            expected_impact="Complex grades containing sulphur see a small realisation change.",
            impacted_products=["NPK_10_26_26", "DAP"], source="policy_gazette_watch", as_of="2026-01-10"),
    ]

    # -- field reports ---------------------------------------------------------
    reporters = ["A. Verma (field officer)", "S. Iyer (field officer)",
                 "R. Patil (dealer network lead)", "M. Khan (field officer)"]
    report_specs = [
        ("FR-001", 0, "DST-GUN", "2025-07-14", "pest_outbreak", "CHLORPYRIFOS", "Fall armyworm pressure reported across maize belts; demand for control sprays rising."),
        ("FR-002", 1, "DST-NAG", "2025-08-02", "stock_out", "DAP", "Two of five tracked dealers report DAP stocked out ahead of kharif top-dressing."),
        ("FR-003", 2, "DST-RAJ", "2025-08-19", "discounting", "UREA", "Competitor-linked dealers discounting urea bundles by 3-4% in the groundnut belt."),
        ("FR-004", 3, "DST-BAR", "2025-09-09", "stock_out", "DAP", "DAP unavailable at block level during the price spike week; farmers substituting NPK."),
        ("FR-005", 0, "DST-IND", "2025-09-21", "demand_surge", "GLYPHOSATE", "Pre-sowing burndown demand for glyphosate up sharply in soybean districts."),
        ("FR-006", 1, "DST-LUD", "2025-10-05", "demand_slump", "UREA", "Wheat sowing delayed by late paddy harvest; urea offtake slower than season norm."),
        ("FR-007", 2, "DST-KOT", "2025-10-18", "discounting", "NPK_10_26_26", "Aggressive complex-grade discounting reported near the state border districts."),
        ("FR-008", 3, "DST-PAT", "2025-11-03", "stock_out", "MOP", "Potash stocks thin at district warehouses ahead of rabi vegetables."),
        ("FR-009", 0, "DST-WAR", "2025-11-22", "pest_outbreak", "CHLORPYRIFOS", "Pink bollworm incidence reported in cotton; spray demand expected to rise."),
        ("FR-010", 1, "DST-KAR", "2025-12-08", "demand_surge", "DAP", "Wheat belt DAP offtake strong on good soil moisture."),
        ("FR-011", 2, "DST-BEL", "2026-01-12", "demand_slump", "MOP", "Sugarcane belt potash application deferred on cane-price uncertainty."),
        ("FR-012", 3, "DST-LKO", "2026-02-02", "stock_out", "UREA", "Rabi top-dress urea tight at two district depots."),
    ]
    for rid, r_idx, d_id, day, kind, product, detail in report_specs:
        ds.field_reports.append(models.FieldReport(
            report_id=rid, reporter=reporters[r_idx], district_id=d_id, date=day,
            signal_kind=kind, product=product, detail=detail,
            source="field_officer_report", as_of=day,
        ))

    # -- manifest: the planted truth ------------------------------------------
    ds.manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "crop_years": CROP_YEARS,
        "districts": [d[0] for d in DISTRICTS],
        "planted": {
            "price_spike": spike,
            "import_delay": delay,
        },
        "policy_event_ids": [e.event_id for e in ds.policy_events],
        "field_report_ids": [r.report_id for r in ds.field_reports],
        "counts": {
            "districts": len(ds.districts),
            "area_facts": len(ds.area_facts),
            "monsoon_facts": len(ds.monsoon_facts),
            "soil_facts": len(ds.soil_facts),
            "consumption_facts": len(ds.consumption_facts),
            "price_points": len(ds.price_points),
            "import_arrivals": len(ds.import_arrivals),
            "supply_facts": len(ds.supply_facts),
            "competitor_points": len(ds.competitor_points),
            "policy_events": len(ds.policy_events),
            "field_reports": len(ds.field_reports),
        },
    }
    return ds


def load_dataset(store) -> dict:
    """Insert the generated dataset into the store (insert-only).

    Returns the manifest. Refuses if a manifest is already stored —
    a second generation into the same store would rewrite history,
    which this store does not do.
    """
    if store.get_manifest() is not None:
        raise RuntimeError("dataset already loaded: the store is insert-only")
    ds = generate_dataset()
    store.insert_districts(ds.districts)
    store.insert_area_facts(ds.area_facts)
    store.insert_monsoon_facts(ds.monsoon_facts)
    store.insert_soil_facts(ds.soil_facts)
    store.insert_application_rates(ds.application_rates)
    store.insert_consumption_facts(ds.consumption_facts)
    store.insert_price_points(ds.price_points)
    store.insert_import_arrivals(ds.import_arrivals)
    store.insert_supply_facts(ds.supply_facts)
    store.insert_competitor_points(ds.competitor_points)
    store.insert_policy_events(ds.policy_events)
    store.insert_field_reports(ds.field_reports)
    store.put_manifest(ds.manifest, GENERATOR_VERSION)
    return ds.manifest
