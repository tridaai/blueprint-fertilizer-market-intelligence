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

Later rounds extend this gate: demand accuracy (R2), alert truth
(R3), supply gaps (R4), spike/delay grading depth (R12).
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

    print("Round 1 evals — fertilizer market intelligence")
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
