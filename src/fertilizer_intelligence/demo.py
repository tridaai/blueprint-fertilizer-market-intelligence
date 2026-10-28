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

    print("\n--- Round 2: the demand engine ---")
    est = service.estimate_demand("DST-LUD", "DAP", "2025-26", "kharif", "2026-04-15")
    print(f"\nEstimate {est['estimate_id']} — Ludhiana DAP, kharif 2025-26 ({est['status']}):")
    for line in est["contributions"]:
        factor = f"x{line['factor']:.4f}" if line["factor"] is not None else "  —  "
        print(f"  {line['driver']:<22} {line['status']:<14} {factor}  "
              f"delta {line['delta_tonnes']:>10.3f}  -> {line['value_after_tonnes']:>10.3f} t")
    print(f"  total {est['total_tonnes']:.3f} t; re-performance problems: "
          f"{service.verify_estimate(est['estimate_id'])}")

    partial = service.estimate_demand("DST-LUD", "DAP", "2024-25", "kharif", "2026-04-15")
    print(f"\nThe same estimate for 2024-25 is {partial['status']}: missing drivers "
          f"{partial['missing_drivers']} — named, never substituted.")

    outlook = service.demand_outlook("2025-26", "kharif", "2026-04-15")
    print(f"\nOutlook {outlook['outlook_id']} — kharif 2025-26: {outlook['estimate_count']} "
          f"estimates, {outlook['partial_count']} partial, total {outlook['total_tonnes']:.3f} t")
    for product, tonnes in sorted(outlook["product_rollups"].items()):
        print(f"  {product:<14} {tonnes:>12.3f} t")
    print(f"  rollup verification problems: {service.verify_outlook(outlook['outlook_id'])}")

    narrative = service.draft_outlook_narrative("2025-26", "kharif", "2026-04-15")
    print(f"\nOutlook narrative ({narrative['model_profile']}/{narrative['model_name']}), "
          "figure-verified before it was stored:")
    print(narrative["text"])
    print("\nDemo complete — every figure above came out of the store.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
