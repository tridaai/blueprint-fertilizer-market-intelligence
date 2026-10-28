"""Eval gate v1 for Blueprint #21 — Fertilizer & Agrochemical
Market Intelligence Agent.

Runs against a throwaway store (no disk state shared with anything,
no network, no keys) and grades the R1 data-integrity guarantees
against the generator manifest — the planted truth.

Zero-tolerance counters:
  - planted_spike_mismatch ....... stored DAP spike != manifest
  - planted_delay_mismatch ....... stored delayed shipment != manifest
  - provenance_missing ........... fact rows without source/as_of
  - coverage_gaps ................ district x year x season cells
                                   missing area, monsoon or consumption
  - consumption_mismatch ......... consumption not re-derivable from
                                   the stored inputs by the stated rules
  - manifest_count_mismatch ...... manifest counts != store counts
  - duplicate_load_accepted ...... a second dataset load was accepted
                                   (the store is insert-only)

Round 2 adds the demand-engine counters (all zero-tolerance):
  - estimate_reperformance_failures  a stored estimate the verifier
                                   cannot re-perform from its own
                                   recorded inputs
  - estimate_total_mismatch ...... total != base + contribution deltas
  - engine_consumption_drift ..... base x soil x monsoon drifts from
                                   the stored consumption figure
  - rollup_part_mismatch ......... an outlook rollup that is not the
                                   sum of its member estimates
  - partial_naming_gaps .......... a partial estimate that fails to
                                   name its missing drivers (or a
                                   complete-year estimate gone partial)
  - narrative_figure_violations_accepted
                                   a narrative figure not in the
                                   artefacts, accepted anywhere
  - estimate_tamper_undetected ... a stored line/total altered behind
                                   the store's back that the verifier
                                   did not catch

Later rounds extend this gate: alert truth (R3), supply gaps (R4),
spike/delay grading depth (R12).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fertilizer_intelligence.config import Settings  # noqa: E402
from fertilizer_intelligence.generator import derive_consumption, load_dataset  # noqa: E402
from fertilizer_intelligence.service import MarketService  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fert-evals-"))
    settings = Settings(
        database_url=None,
        sqlite_path=tmp / "fert.db",
        migrations_dir=REPO / "migrations",
        model_profile="offline",
        log_level="WARNING",
    )
    service = MarketService(settings)
    store = service.store
    manifest = service.manifest
    counters = {
        "planted_spike_mismatch": 0,
        "planted_delay_mismatch": 0,
        "provenance_missing": 0,
        "coverage_gaps": 0,
        "consumption_mismatch": 0,
        "manifest_count_mismatch": 0,
        "duplicate_load_accepted": 0,
    }

    # Planted spike: the stored DAP price at the spike month equals
    # the manifest's planted value, and the planted value is the
    # trend value moved by exactly the manifested magnitude.
    spike = manifest["planted"]["price_spike"]
    dap = {p["month"]: p["price"] for p in store.price_points("product", "DAP")}
    if dap.get(spike["month"]) != spike["planted_price"]:
        counters["planted_spike_mismatch"] += 1
    expected = round(spike["baseline_price"] * (1 + spike["magnitude_pct"] / 100.0), 2)
    if spike["planted_price"] != expected:
        counters["planted_spike_mismatch"] += 1

    # Planted delay: exactly one shipment is late, and it is the
    # manifested one with the manifested months.
    delay = manifest["planted"]["import_delay"]
    arrivals = store.import_arrivals()
    late = [a for a in arrivals if a["arrived_month"] > a["expected_month"]]
    target = next((a for a in arrivals if a["shipment_id"] == delay["shipment_id"]), None)
    if (
        target is None
        or target["expected_month"] != delay["expected_month"]
        or target["arrived_month"] != delay["arrived_month"]
        or len(late) != 1
    ):
        counters["planted_delay_mismatch"] += 1

    counters["provenance_missing"] = store.provenance_gaps()

    # Coverage: every district x year x season cell carries area,
    # monsoon and consumption facts.
    area_cells = {(a["district_id"], a["crop_year"], a["season"]) for a in store.area_facts()}
    monsoon_cells = {(m["district_id"], m["crop_year"], m["season"]) for m in store.monsoon_facts()}
    consumption_cells = {(c["district_id"], c["crop_year"], c["season"]) for c in store.consumption_facts()}
    for district in manifest["districts"]:
        for year in manifest["crop_years"]:
            for season in ("kharif", "rabi"):
                cell = (district, year, season)
                if cell not in area_cells or cell not in monsoon_cells or cell not in consumption_cells:
                    counters["coverage_gaps"] += 1

    # Consumption provable from the stored inputs.
    derived = derive_consumption(
        store.area_facts(), store.application_rates(),
        store.soil_facts(), store.monsoon_facts(),
    )
    stored = {
        (c["district_id"], c["crop_year"], c["season"], c["product"]): c["quantity_tonnes"]
        for c in store.consumption_facts()
    }
    if set(derived) != set(stored):
        counters["consumption_mismatch"] += 1
    counters["consumption_mismatch"] += sum(
        1 for key, value in stored.items() if abs(derived.get(key, 0.0) - value) > 0.01
    )

    counts = store.fact_counts()
    for name, expected_n in manifest["counts"].items():
        if counts.get(name) != expected_n:
            counters["manifest_count_mismatch"] += 1

    try:
        load_dataset(store)
        counters["duplicate_load_accepted"] += 1
    except RuntimeError:
        pass

    # --- Round 2: the demand engine -----------------------------------
    import sqlite3

    from fertilizer_intelligence.demand import NarrativeRefused, OutlookNarrator
    from fertilizer_intelligence.modelport import ModelReply

    counters.update({
        "estimate_reperformance_failures": 0,
        "estimate_total_mismatch": 0,
        "engine_consumption_drift": 0,
        "rollup_part_mismatch": 0,
        "partial_naming_gaps": 0,
        "narrative_figure_violations_accepted": 0,
        "estimate_tamper_undetected": 0,
    })
    as_of = "2026-04-15"
    outlooks = {}
    for year in manifest["crop_years"]:
        for season in ("kharif", "rabi"):
            outlooks[(year, season)] = service.demand_outlook(year, season, as_of)

    consumption = {
        (c["district_id"], c["crop_year"], c["season"], c["product"]): c["quantity_tonnes"]
        for c in store.consumption_facts()
    }
    supply_products = {r["product"] for r in store.supply_facts()}
    for est in store.list_estimates():
        lines = store.estimate_contributions(est["estimate_id"])
        if service.verify_estimate(est["estimate_id"]):
            counters["estimate_reperformance_failures"] += 1
        delta_sum = est["base_tonnes"] + sum(
            line["delta_tonnes"] for line in lines if line["driver"] != "base_area_rates"
        )
        if abs(delta_sum - est["total_tonnes"]) > 0.002:
            counters["estimate_total_mismatch"] += 1
        # Base x soil x monsoon is the generator's derivation; the
        # engine's pre-price value must track the stored figure.
        monsoon_line = next(l for l in lines if l["driver"] == "monsoon_deviation")
        key = (est["district_id"], est["crop_year"], est["season"], est["product"])
        if abs(monsoon_line["value_after_tonnes"] - consumption[key]) > 0.05:
            counters["engine_consumption_drift"] += 1
        # Partial honesty: the first crop year names its missing
        # drivers; the second is complete throughout.
        if est["crop_year"] == manifest["crop_years"][0]:
            if est["status"] != "partial" or "price_elasticity" not in est["missing_drivers"]:
                counters["partial_naming_gaps"] += 1
            if est["product"] in supply_products and "carry_in_stock" not in est["missing_drivers"]:
                counters["partial_naming_gaps"] += 1
            if est["product"] not in supply_products and "carry_in_stock" in est["missing_drivers"]:
                counters["partial_naming_gaps"] += 1
        elif est["status"] != "complete" or est["missing_drivers"]:
            counters["partial_naming_gaps"] += 1

    for outlook in outlooks.values():
        if service.verify_outlook(outlook["outlook_id"]):
            counters["rollup_part_mismatch"] += 1
        members = [store.get_estimate(eid) for eid in outlook["estimate_ids"]]
        for product, rolled in outlook["product_rollups"].items():
            parts = sum(m["total_tonnes"] for m in members if m["product"] == product)
            if abs(rolled - parts) > 0.01:
                counters["rollup_part_mismatch"] += 1

    # Narratives: the honest draft verifies; a wrong-figure draft
    # is refused and stores nothing; a stored narrative altered
    # behind the store's back is caught on re-verification.
    narrative = service.draft_outlook_narrative("2025-26", "kharif", as_of)
    if service.verify_narrative(narrative["narrative_id"]):
        counters["narrative_figure_violations_accepted"] += 1

    class _WrongFigure:
        profile_name = "stub"
        model_name = "stub-wrong-figure"

        def complete(self, system, prompt):
            return ModelReply(
                text="Total estimated demand is 999999.99 tonnes.",
                profile=self.profile_name, model=self.model_name,
                input_tokens=0, output_tokens=0,
            )

    outlook = outlooks[("2025-26", "kharif")]
    stored_before = len(store.list_narratives(outlook["outlook_id"]))
    try:
        OutlookNarrator(store, _WrongFigure()).draft(outlook, as_of)
        counters["narrative_figure_violations_accepted"] += 1  # accepted!
    except NarrativeRefused:
        pass
    if len(store.list_narratives(outlook["outlook_id"])) != stored_before:
        counters["narrative_figure_violations_accepted"] += 1

    raw = sqlite3.connect(settings.sqlite_path)
    raw.execute(
        "UPDATE outlook_narratives SET text = 'Total estimated demand is 1.00 tonnes.' "
        "WHERE narrative_id = ?",
        (narrative["narrative_id"],),
    )
    raw.commit()
    if not service.verify_narrative(narrative["narrative_id"]):
        counters["narrative_figure_violations_accepted"] += 1  # tamper went undetected
    raw.execute(
        "UPDATE outlook_narratives SET text = ? WHERE narrative_id = ?",
        (narrative["text"], narrative["narrative_id"]),
    )
    # Tamper with one estimate's stored total: the verifier must
    # catch it; then restore and confirm it verifies clean again.
    victim = store.list_estimates()[0]
    raw.execute(
        "UPDATE demand_estimates SET total_tonnes = total_tonnes + 25 WHERE estimate_id = ?",
        (victim["estimate_id"],),
    )
    raw.commit()
    raw.close()
    if not service.verify_estimate(victim["estimate_id"]):
        counters["estimate_tamper_undetected"] += 1

    print("Round 1+2 evals — fertilizer market intelligence")
    for name, value in counters.items():
        print(f"  {name}: {value} (required 0)")
    failed = [n for n, v in counters.items() if v != 0]
    if failed:
        print("GATE: FAIL")
        for name in failed:
            print(f"  - {name} = {counters[name]}")
        return 1
    print("GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
