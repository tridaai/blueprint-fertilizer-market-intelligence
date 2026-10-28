"""Demo: generate the dataset into a throwaway store and walk the
planted truth — the spike, the delay, the coverage, and one
consumption figure re-derived live from the stored inputs.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from .config import Settings
from .generator import derive_consumption
from .service import MarketService


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fert-demo-"))
    settings = Settings(
        database_url=None,
        sqlite_path=tmp / "fert.db",
        migrations_dir=Path(__file__).resolve().parents[2] / "migrations",
        model_profile="offline",
        log_level="WARNING",
    )
    service = MarketService(settings)
    manifest = service.manifest
    counts = service.store.fact_counts()
    print("Dataset generated and loaded (Kaveri Agro Inputs market data):")
    for name, n in counts.items():
        print(f"  {name:<20} {n}")

    spike = manifest["planted"]["price_spike"]
    dap = {p["month"]: p["price"] for p in service.store.price_points("product", "DAP")}
    print(f"\nPlanted price spike — DAP {spike['month']}: "
          f"trend {spike['baseline_price']} -> planted {spike['planted_price']} "
          f"(stored: {dap[spike['month']]})  match: {dap[spike['month']] == spike['planted_price']}")

    delay = manifest["planted"]["import_delay"]
    arrivals = {a["shipment_id"]: a for a in service.store.import_arrivals()}
    got = arrivals[delay["shipment_id"]]
    print(f"Planted import delay — {delay['shipment_id']}: expected {delay['expected_month']}, "
          f"arrived {got['arrived_month']}  match: {got['arrived_month'] == delay['arrived_month']}")

    view = service.demand_inputs("DST-GUN", "2025-26", "kharif")
    print(f"\nDemand inputs, Guntur 2025-26 kharif: {len(view['area'])} crops, "
          f"monsoon deviation {view['monsoon'][0]['deviation_pct']}%, "
          f"{len(view['consumption'])} consumption figures")

    derived = derive_consumption(
        service.store.area_facts(), service.store.application_rates(),
        service.store.soil_facts(), service.store.monsoon_facts(),
    )
    stored = {
        (c["district_id"], c["crop_year"], c["season"], c["product"]): c["quantity_tonnes"]
        for c in service.store.consumption_facts()
    }
    mismatches = sum(1 for k, v in stored.items() if abs(derived.get(k, 0.0) - v) > 0.01)
    print(f"Consumption re-derived from stored inputs: {len(stored)} figures, "
          f"{mismatches} mismatches")
    print("\nDemo complete — every figure above came out of the store.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
