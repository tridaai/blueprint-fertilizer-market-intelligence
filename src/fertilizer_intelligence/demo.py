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

    print("\n--- Round 3: the price & feedstock watch ---")
    summary = service.run_price_watch("2026-04-15")
    print(f"\nWatch pass (rule pack {summary['rules_version']}): "
          f"{summary['movements_total']} movements computed, "
          f"{summary['alerts_total']} alerts fired.")
    again = service.run_price_watch("2026-04-15")
    print(f"Second pass: {again['movements_stored']} new movements, "
          f"{again['alerts_fired']} new alerts — firing is idempotent.")

    spike_alerts = service.list_alerts("product", "DAP", "spike")
    spike_alert = spike_alerts[0]
    print(f"\nThe planted spike, as the watch saw it — {spike_alert['alert_id']}:")
    print(f"  DAP {spike_alert['period_month']}: month-on-month "
          f"{spike_alert['figures']['mom_pct']:+.2f}% -> band {spike_alert['band']}, "
          f"state {spike_alert['state']}")
    print(f"  triggered by movement {spike_alert['movement_ids'][0]}; "
          f"verification problems: {service.verify_alert(spike_alert['alert_id'])}")
    dap_spikes = [a for a in service.list_alerts("product", "DAP", "spike")]
    print(f"  spike alerts for DAP across the whole series: {len(dap_spikes)} "
          "(the October/November unwind is the same event — the pack's "
          "event window keeps the spike rule quiet there)")

    print("\nThe watch board (every series by band):")
    for row in service.watch_board():
        print(f"  {row['series_kind']:<10} {row['item']:<15} band {row['band']:<6} "
              f"open alerts {row['open_alert_count']:>2}  "
              f"latest {row['latest_month']} MoM {row['latest_mom_pct']:+.2f}%")

    acked = service.acknowledge_alert(
        spike_alert["alert_id"], actor="desk.lead@kaveri.example",
        note="Spike traced to the September import-parity jump; monitoring the unwind.",
        as_of="2026-04-15",
    )
    print(f"\nSpike alert acknowledged by {acked['acts'][-1]['actor']} "
          f"-> state {acked['state']}")
    closed = service.close_alert(
        spike_alert["alert_id"], actor="desk.lead@kaveri.example",
        closing_reason="explained_by_event", as_of="2026-04-16",
    )
    print(f"Then closed with reason '{closed['acts'][-1]['closing_reason']}' "
          f"-> state {closed['state']} (state is derived from the acts; "
          "the alert artefact itself was never edited)")
    print("\nDemo complete — every figure above came out of the store.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
