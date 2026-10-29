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

    print("\n--- Round 4: the import & supply-gap tracker ---")
    chain = service.supply_positions("DAP", "2026-04-15")
    print(f"\nDAP supply position chain: {len(chain)} months computed "
          f"({chain[0]['month']} .. {chain[-1]['month']}); every month's "
          "opening is the prior month's closing, and every figure is a "
          "recorded line over named facts.")
    print("\nThe planted delay, as the position chain saw it "
          "(shipment IMP-DAP-2510, expected 2025-10):")
    for position in chain:
        if position["month"] in ("2025-09", "2025-10", "2025-11", "2025-12"):
            print(f"  {position['month']}: opening {position['opening_tonnes']:>13,.3f} t"
                  f"  production {position['production_actual_tonnes']:>10,.1f} t"
                  f"  imports {position['imports_tonnes']:>8,.0f} t"
                  f"  consumption {position['consumption_tonnes']:>10,.3f} t"
                  f"  closing {position['closing_tonnes']:>13,.3f} t")
    problems = service.verify_position("DAP", "2025-10")
    print(f"  October position verification problems: {problems} "
          "— the dip is real: no vessel landed, and the identity still holds.")

    gap_oct = service.supply_gap("DAP", "2025-26", "kharif", "2025-11-30")
    print(f"\nSupply gap, DAP kharif 2025-26 at 2025-11-30: band "
          f"{gap_oct['band']} ({gap_oct['band_basis']}) — the season's import "
          f"programme is {gap_oct['due_imports_tonnes']:,.0f} t due, "
          f"{gap_oct['credited_imports_tonnes']:,.0f} t credited, "
          f"{gap_oct['slipped_tonnes']:,.0f} t slipped; cover "
          f"{gap_oct['programme_cover_pct']:.2f}%.")
    gap_dec = service.supply_gap("DAP", "2025-26", "kharif", "2025-12-31")
    print(f"The same gap at 2025-12-31, after the vessel landed: band "
          f"{gap_dec['band']}, cover {gap_dec['programme_cover_pct']:.2f}%, "
          f"slipped {gap_dec['slipped_tonnes']:,.0f} t "
          f"(the new gap supersedes the old by link: {gap_dec['supersedes'] == gap_oct['gap_id']}).")
    gap_mop = service.supply_gap("MOP", "2025-26", "kharif", "2025-11-30")
    print(f"MOP kharif 2025-26 at 2025-11-30: band {gap_mop['band']} "
          f"({gap_mop['band_basis']}) — import-only, so the level reading "
          f"binds: available {gap_mop['available_tonnes']:,.3f} t against "
          f"demand {gap_mop['demand_tonnes']:,.3f} t "
          f"({gap_mop['gap_pct_of_demand']:.2f}%).")

    proj_first = service.supply_projection("DAP", "2025-26", "rabi", "2025-09-30")
    print(f"\nProjected DAP position for rabi 2025-26, struck at the end of "
          f"{proj_first['basis_month']}: status {proj_first['status']}, "
          f"projected closing {proj_first['closing_tonnes']:,.3f} t — the "
          "delayed vessel is a scheduled assumption at its expected month.")
    proj_slip = service.supply_projection("DAP", "2025-26", "rabi", "2025-11-30")
    print(f"Re-struck at the end of {proj_slip['basis_month']}, the "
          "projection supersedes by link and names its changes:")
    for change in proj_slip["assumption_changes"]:
        print(f"  - {change['kind']}: {change['detail']}")
    print(f"  projected closing now {proj_slip['closing_tonnes']:,.3f} t; "
          f"verification problems: "
          f"{service.verify_projection('DAP', '2025-26', 'rabi')}")

    print("\n--- Round 5: the policy & subsidy event registry ---")
    summary = service.register_policy_events("2026-04-15")
    print(f"\nRegistration pass over the recorded policy facts: "
          f"{summary['registered']} registered, "
          f"{summary['already_registered']} already current, "
          f"{summary['events_total']} events on the registry.")
    events = {e["event_id"]: e for e in service.list_policy_events()}
    for event in events.values():
        effect = event["stated_effect"]
        print(f"  {event['event_id']}  {event['event_class']:<22} "
              f"{event['effective_from_month']}..{event['effective_to_month']}  "
              f"driver {effect['driver']:<11} direction {effect['direction']:<5} "
              f"scope {', '.join(event['products'])}")
    again = service.register_policy_events("2026-04-15")
    print(f"Second pass: {again['registered']} new registrations — "
          "registration is idempotent.")

    restriction = events["POL-2025-003"]
    note = service.policy_impact(restriction["registry_id"], "2026-04-15")
    print(f"\nImpact note for the export restriction ({note['note_id']}, "
          f"status {note['status']}): the scope query names "
          f"{len(note['demand_estimate_ids'])} demand cells, "
          f"{sum(s['point_count'] for s in note['price_series'])} price "
          f"points across {len(note['price_series'])} series, and "
          f"{len(note['position_ids'])} supply positions — artefact ids, "
          "computed from the store, not prose:")
    for cell in note["demand_cells"][:2]:
        print(f"  demand  {cell['district_id']} {cell['product']} "
              f"{cell['crop_year']} {cell['season']} -> {cell['estimate_id']}")
    print(f"  ... and {len(note['demand_cells']) - 2} more cells")
    for series in note["price_series"]:
        print(f"  prices  {series['series_kind']}/{series['item']}: "
              f"months {', '.join(series['months'])}")
    for position in note["positions"]:
        print(f"  supply  {position['product']} {position['month']} "
              f"-> {position['position_id']}")
    print(f"  note verification problems: "
          f"{service.verify_policy_impact(restriction['registry_id'])}")

    proposal = service.register_policy_event({
        "event_id": "POL-2026-HYP-001",
        "event_class": "import_duty_change",
        "title": "Proposed import duty revision on DAP (desk scenario)",
        "detail": "A duty revision under discussion; registered as a "
                  "proposal so its stated effect is on record.",
        "effective_from_month": "2025-09", "effective_to_month": "2025-11",
        "products": ["DAP"], "districts": [],
        "direction": "down",
        "mechanism": "A lower duty would move the landed cost of DAP "
                     "arrivals down over the kharif window.",
        "hypothetical": True,
        "source": "desk_scenario_register",
        "registered_by": "strategy.desk@kaveri.example",
    }, "2026-04-15")
    print(f"\nA proposed duty change is registered as hypothetical "
          f"({proposal['registry_id']}): listed with the proposals "
          f"({len(service.list_policy_events(hypothetical=True))}), absent "
          f"from the real events "
          f"({len(service.list_policy_events(hypothetical=False))}).")
    try:
        service.policy_impact(proposal["registry_id"], "2026-04-15")
        print("  ERROR: a hypothetical earned an impact note")
    except ValueError as exc:
        print(f"  Its impact note is refused: {exc}")
    print(f"  Impact notes stored for it: "
          f"{len(service.store.list_policy_impact_notes(proposal['registry_id']))}")

    markers_before = {
        row["item"]: [m["event_id"] for m in row["policy_markers"]]
        for row in service.watch_board()
    }
    print(f"  Board markers stay with the real events only — DAP carries "
          f"{markers_before['DAP']}, NPK carries "
          f"{markers_before['NPK_10_26_26']} (the rabi subsidy revision, "
          "whose window is open at the board's reference month); the "
          "proposal marks nothing, and no marker is counted as an alert.")

    enacted = service.register_policy_event({
        "event_id": "POL-2026-HYP-001",
        "event_class": "import_duty_change",
        "title": "Import duty revision on DAP (registered as enacted)",
        "detail": "The duty revision is now on record as a real event; "
                  "this registration supersedes the proposal by link.",
        "effective_from_month": "2025-09", "effective_to_month": "2025-11",
        "products": ["DAP"], "districts": [],
        "direction": "down",
        "mechanism": "A lower duty moves the landed cost of DAP "
                     "arrivals down over the kharif window.",
        "hypothetical": False,
        "source": "desk_scenario_register",
        "registered_by": "strategy.desk@kaveri.example",
    }, "2026-04-16")
    print(f"\nRegistered again as a real event, it supersedes the proposal "
          f"by link (supersedes set: "
          f"{enacted['supersedes'] == proposal['registry_id']}); the "
          "proposal artefact itself is unchanged — registrations are "
          "insert-only, so a hypothetical flag is never flipped in place.")
    enacted_note = service.policy_impact(enacted["registry_id"], "2026-04-16")
    print(f"Now it earns an impact note: status {enacted_note['status']}, "
          f"{len(enacted_note['demand_estimate_ids'])} demand cells, "
          f"{len(enacted_note['position_ids'])} positions — the same "
          "window and product scope the restriction's note named.")

    print("\n--- Round 6: competitor & market-share intelligence ---")
    built = service.build_competitor_observations()
    print(f"\nObservation pass over the tracked competitor points: "
          f"{built['observations_stored']} stored, "
          f"{built['already_present']} already present, "
          f"{built['observations_total']} observations — every one "
          "carrying its source and observation date on its face.")
    again = service.build_competitor_observations()
    print(f"Second pass: {again['observations_stored']} new — the "
          "pass is idempotent.")

    share = service.market_share("DST-LUD", "DAP", "2025-26", "kharif")
    print(f"\nMarket share, Ludhiana DAP kharif 2025-26, read at the "
          f"season close {share['as_of']} ({share['share_id']}, status "
          f"{share['status']}): the district's recorded market is "
          "distributed by the north region's observed structure — "
          "tracked competitor volumes are whole-region figures, so "
          "raw tonnage is never allocated into a district.")
    headline = share["headline"]
    print(f"  {'seller':<22} {'volume t':>10}  {'of observed':>11}  "
          f"{'of demand':>9}")
    for seller in [headline["kaveri"]] + headline["competitors"]:
        print(f"  {seller['seller']:<22} {seller['volume_tonnes']:>10.3f}  "
              f"{seller['share_of_observed_market_pct']:>10.4f}%  "
              f"{seller['share_of_total_demand_pct']:>8.4f}%")
    print(f"  Kaveri's line is the residual the artefact names: "
          f"{share['kaveri_basis']}")
    print(f"  provenance: {len(share['provenance'])} observations in "
          f"scope; verification problems: "
          f"{service.verify_share(share['share_id'])}")

    late = service.market_share(
        "DST-LUD", "DAP", "2025-26", "kharif", "2026-03-31")
    print(f"\nThe same share read late, at 2026-03-31: "
          f"{late['headline_note']} — the June–August observations "
          "have aged past the pack's 200-day freshness window, so "
          "the headline is computed over September–November only "
          "and the exclusion is named on the artefact:")
    for entry in late["headline"]["excluded_observations"][:3]:
        print(f"  excluded {entry['observation_id']} "
              f"(observed {entry['as_of']}, {entry['age_days']} days old)")
    print(f"  ... and "
          f"{len(late['headline']['excluded_observations']) - 3} more; "
          f"the full-season reading rides alongside, labelled "
          f"'{late['full_season']['basis']}'.")

    stale = service.market_share(
        "DST-LUD", "DAP", "2024-25", "rabi", "2026-03-31")
    print(f"\nLudhiana DAP rabi 2024-25 read at the same late date: "
          f"status {stale['status']} — every month is stale, so the "
          "share reads not_current instead of presenting an old "
          "number as current.")

    movement = service.share_movement("DST-LUD", "DAP", "kharif", "2026-04-15")
    print(f"\nShare movement, Ludhiana DAP kharif, "
          f"{movement['from_crop_year']} -> {movement['to_crop_year']} "
          f"(basis {movement['basis']}):")
    for row in movement["rows"]:
        print(f"  {row['seller']:<22} {row['share_from_pct']:>7.4f}% -> "
              f"{row['share_to_pct']:>7.4f}%  ({row['change_pp']:+.4f} pp)")
    mover = movement["biggest_mover"]
    print(f"  biggest mover: {mover['seller']} ({mover['change_pp']:+.4f} "
          f"pp), carried on {len(mover['observation_ids_from'])} + "
          f"{len(mover['observation_ids_to'])} observations of "
          "provenance; verification problems: "
          f"{service.verify_share_movement(movement['movement_id'])}")

    print("\n--- Round 7: field signals & mobile intake ---")
    promoted = service.promote_planted_field_reports("2026-04-15")
    print(f"\nThe twelve planted field reports promote through the "
          f"intake's landing machinery: {promoted['landed']} landed, "
          f"{promoted['reports_total']} signal artefacts, all "
          f"unreviewed in the verification queue "
          f"({len(service.list_field_reports(state='unreviewed'))} waiting).")

    print("\nAn outbox from a field phone, queued offline — a DAP "
          "demand surge observed at Ludhiana on 2025-10-28:")
    outbox = [{
        "submission_id": "PHONE7-0001", "reporter": "T. Rao (field officer)",
        "district_id": "DST-LUD", "product": "DAP",
        "signal_type": "demand_signal", "direction": "up",
        "observed_on": "2025-10-28",
        "detail": "Wheat-belt DAP offtake surging ahead of rabi sowing.",
    }]
    first = service.sync_field_reports(outbox[:1], "2025-11-02")
    print(f"  first sync lands it: {first['receipt'][0]['outcome']} "
          f"as {first['receipt'][0]['report_id']}")
    retry = service.sync_field_reports(outbox, "2025-11-02")
    print(f"  the connection drops mid-sync and the phone re-sends "
          f"the whole outbox: {retry['receipt'][0]['outcome']} — "
          "exactly once, no duplicate artefact.")
    conflict = service.sync_field_reports(
        [dict(outbox[0], detail="Corrected wording from the phone.")],
        "2025-11-03",
    )
    print(f"  the same submission id with different words is a "
          f"{conflict['receipt'][0]['outcome']}: both artefacts are "
          "kept and linked, never silently overwritten.")

    capped = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "kharif", "2025-11-02")
    line = next(
        l for l in capped["lines"] if l["report_id"] == "FSR-PHONE7-0001")
    print(f"\nThe weighting assessment for Ludhiana DAP, kharif "
          f"2025-26: the unreviewed surge would move the estimate "
          f"by {line['uncapped_pct']:+.4f}% (its kind's stated "
          f"effect, freshness-decayed), but Law 5's cap binds it "
          f"to {line['applied_pct']:+.4f}% — base "
          f"{capped['base_tonnes']:.3f} t -> adjusted "
          f"{capped['adjusted_tonnes']:.3f} t, the report named "
          f"as {line['reporter']} ({line['review_state']}).")
    service.review_field_report(
        "FSR-PHONE7-0001", "confirm", "A. Reviewer (regional desk)",
        "corroborated", "2025-11-02",
    )
    confirmed = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "kharif", "2025-11-02")
    line = next(
        l for l in confirmed["lines"] if l["report_id"] == "FSR-PHONE7-0001")
    print(f"  a named reviewer confirms it, and the recomputation "
          f"carries its full decayed weight: {line['applied_pct']:+.4f}% "
          f"-> adjusted {confirmed['adjusted_tonnes']:.3f} t "
          f"(verification problems: "
          f"{service.verify_field_assessment(confirmed['assessment_id'])}).")

    print("\n--- Round 8: ask in plain language ---")
    question = (
        "How is DAP looking in Ludhiana this kharif, what's our share, "
        "and what's the monsoon outlook for groundnut in Anantapur?"
    )
    spec = service.ask_question(
        question, "demo desk", "2026-03-31", name="weekly desk question")
    print(f"\nThe desk asks: \"{question}\"")
    print(f"  it parses into spec {spec['spec_id']} — "
          f"{len(spec['panels'])} governed panels:")
    for panel in spec["panels"]:
        origin = panel["origin"]["rule"]
        print(f"    {panel['panel_no']}. [{panel['kind']}] "
              f"{panel['title']}  (via {origin})")
    assembly = service.assemble_dashboard(spec["spec_id"], "2026-03-31")
    figures = sum(len(p["figures"]) for p in assembly["panels"])
    print(f"  assembled dashboard {assembly['assembly_id']}: "
          f"{figures} figures, every one naming its artefact and "
          f"as-of; verification: "
          f"{service.verify_dashboard(assembly['assembly_id'])}.")
    gap = next(p for p in assembly["panels"] if p["kind"] == "gap")
    print(f"  the third part is a gap, not an invention — it states "
          f"what it would need:\n    {gap['notes'][0][:220]}...")

    print("\nA saved question, re-run against fresh field data:")
    field_spec = service.ask_question(
        "What do the field signals say for DAP in Ludhiana this kharif?",
        "demo desk", "2025-11-01", name="field watch")
    first = service.assemble_dashboard(field_spec["spec_id"], "2025-11-01")
    print(f"  first assembly {first['assembly_id']}: field-signal "
          f"adjustment "
          f"{first['panels'][0]['figures'][1]['value']:+.4f}%.")
    service.sync_field_reports([{
        "submission_id": "PHONE8-0001",
        "reporter": "T. Rao (field officer)", "district_id": "DST-LUD",
        "product": "DAP", "signal_type": "demand_signal",
        "direction": "up", "observed_on": "2025-11-20",
        "detail": "Queues at two dealers; offtake running ahead.",
    }], "2025-11-25")
    second = service.assemble_dashboard(field_spec["spec_id"], "2025-12-01")
    print(f"  a surge report lands from a field phone; re-assembly "
          f"{second['assembly_id']} supersedes the first.")
    for note in second["panels"][0]["notes"]:
        print(f"    note: {note}")
    for entry in second["diff"]:
        if entry["kind"] == "figure_changed":
            print(f"    diff: {entry['label']} "
                  f"{entry['before']} -> {entry['after']}")

    leadership = service.role_default_dashboard(
        "leadership", "demo desk", "2026-03-31")
    board = service.assemble_dashboard(leadership["spec_id"], "2026-03-31")
    print(f"\nThe leadership default is a spec like any other "
          f"({leadership['spec_id']}, "
          f"{len(leadership['panels'])} panels stated in the pack); "
          f"its dashboard verifies: "
          f"{service.verify_dashboard(board['assembly_id'])['verified']}.")

    print("\n--- Round 9: scenario forks & planning options ---")
    head_before = service.estimate_demand(
        "DST-LUD", "DAP", "2025-26", "kharif", "2026-03-31")
    gap_before = service.supply_gap("DAP", "2025-26", "kharif",
                                     "2025-10-31")
    print(f"\nHeads of record before any fork work: Ludhiana DAP "
          f"kharif demand {head_before['total_tonnes']:.3f} t; the "
          f"kharif gap band is {gap_before['band']} at "
          f"{gap_before['programme_cover_pct']}% programme cover.")

    monsoon_fork = service.ask_scenario(
        "what if the monsoon comes in 20 points lower for dap in "
        "ludhiana, kharif 2025-26",
        "demo desk", name="Monsoon shortfall")
    print(f"\nThe desk asks for a scenario in words; it forks the "
          f"head estimate as {monsoon_fork['fork_id']} "
          f"\"{monsoon_fork['name']}\" — hypothetical, pinned to "
          f"{monsoon_fork['base_artefact_id']}:")
    for row in monsoon_fork["reconciliation"]:
        if row["lever_delta_tonnes"]:
            via = (f"lever {', '.join(row['attributed_levers'])}"
                   if row["attributed_levers"]
                   else "knock-on of the changed running total — "
                        "attributed to no lever")
            print(f"    {row['driver']}: {row['base_delta_tonnes']:+.3f} "
                  f"-> {row['fork_delta_tonnes']:+.3f} t ({via})")
    print(f"    demand {monsoon_fork['base_total_tonnes']:.3f} -> "
          f"{monsoon_fork['fork_total_tonnes']:.3f} t "
          f"({monsoon_fork['delta_tonnes']:+.3f}); the driver deltas "
          f"sum to the fork delta exactly, and the fork verifies: "
          f"{service.verify_scenario(monsoon_fork['fork_id'])['verified']}.")

    slip_fork = service.create_scenario(
        "supply_projection",
        {"product": "DAP", "crop_year": "2025-26", "season": "rabi"},
        [{"lever": "import_arrival_shift_months", "value": 2,
          "shipment_id": "IMP-DAP-2510"}],
        "demo desk", name="October vessel slips", as_of="2025-09-30")
    moved = [r for r in slip_fork["reconciliation"]
             if r["imports_delta_tonnes"]]
    print(f"\nA second fork, stated structurally: the October DAP "
          f"vessel slips two months ({slip_fork['fork_id']}). Its "
          f"import path moves exactly as the planted delay did:")
    for row in moved:
        print(f"    {row['month']}: imports "
              f"{row['base_imports_tonnes']:.0f} -> "
              f"{row['fork_imports_tonnes']:.0f} t")

    demand_options = service.build_planning_options(
        monsoon_fork["base_artefact_id"], [monsoon_fork["fork_id"]],
        "demo desk", name="kharif demand options")
    supply_options = service.build_planning_options(
        slip_fork["base_artefact_id"], [slip_fork["fork_id"]],
        "demo desk", name="rabi supply options")
    for options in (demand_options, supply_options):
        print(f"\n  planning options {options['options_id']} "
              f"({options['kind']}), ranked only by the pack's "
              f"stated criteria:")
        for row in options["rows"]:
            label = "base view" if row["is_base"] else "scenario"
            shown = {k: v for k, v in row["criteria"].items()
                     if k != "artefact_id"}
            print(f"    rank {row['rank']}: {label} "
                  f"{row['artefact_id']} — criteria {shown}")
    adoption = service.adopt_option(
        supply_options["options_id"], slip_fork["fork_id"],
        "M. Krishnan (supply planner)", "2026-04-15",
        note="plan rabi procurement on the slipped arrival")
    print(f"\n  the supply planner adopts the slipped-arrival fork "
          f"by name ({adoption['adoption_id']}); adoption records "
          f"which fork the plan follows — it edits no artefact. "
          f"Current adoption: "
          f"{service.current_adoption(supply_options['options_id'])['adoption_id']}.")

    named = service.ask_question(
        "show me the monsoon shortfall scenario",
        "demo desk", "2026-03-31", name="scenario view")
    named_board = service.assemble_dashboard(named["spec_id"],
                                             "2026-03-31")
    scenario_panel = named_board["panels"][0]
    print(f"\nA dashboard renders the fork only because the question "
          f"names it — panel [{scenario_panel['kind']}] "
          f"{scenario_panel['title']}, every figure badged "
          f"{scenario_panel['figures'][0]['badges']}; the board "
          f"verifies: "
          f"{service.verify_dashboard(named_board['assembly_id'])['verified']}.")

    head_after = service.estimate_demand(
        "DST-LUD", "DAP", "2025-26", "kharif", "2026-03-31")
    gap_after = service.supply_gap("DAP", "2025-26", "kharif",
                                   "2025-10-31")
    print(f"\nHeads of record after all fork work: demand "
          f"{head_after['total_tonnes']:.3f} t, gap band "
          f"{gap_after['band']} at "
          f"{gap_after['programme_cover_pct']}% — byte-identical to "
          f"before: "
          f"{head_after == head_before and gap_after == gap_before}. "
          f"Hypotheticals live only in the fork artefacts.")

    print("\n--- Round 10: the weekly brief, packs & publication ---")
    from . import brief as brief_engine
    from .modelport import ModelReply

    class CorruptPort:
        profile_name = "corrupt"
        model_name = "corrupt-stub"

        def complete(self, system, prompt):
            return ModelReply(
                text=prompt + "\nTotal estimated demand is "
                              "999999.99 t.",
                profile=self.profile_name, model=self.model_name,
                input_tokens=0, output_tokens=0)

    week = "2026-03-29"
    try:
        service.weekly_brief(week, "demo desk", port=CorruptPort())
        print("\n  the corrupted draft was accepted — this must "
              "never print")
    except brief_engine.BriefRefused as refused:
        print(f"\nThe brief's first draft is corrupted at the "
              f"intermediate step — it invents a figure. The "
              f"verifier refuses the brief wholesale; nothing is "
              f"stored, and the refusal is on record as "
              f"{refused.refusal_id}:")
        for problem in refused.problems:
            print(f"    refused: {problem}")

    brief = service.weekly_brief(week, "demo desk")
    figures = sum(len(s["figures"]) for s in brief["sections"])
    print(f"\nAssembled clean, the brief {brief['brief_id']} for "
          f"the week {brief['week_start']} to {brief['week_ending']} "
          f"({brief['season_scope']['season']} "
          f"{brief['season_scope']['crop_year']} scope) carries "
          f"{figures} figures, each with its artefact lineage:")
    for section in brief["sections"]:
        print(f"    {section['title']:<28} "
              f"{len(section['figures']):>3} figures from "
              f"{len(section['artefact_ids'])} artefacts")
        for note in section["notes"][:1]:
            print(f"      note: {note}")
    print(f"  the clean brief supersedes the refusal by link "
          f"({brief['supersedes_refusal']}), and it verifies: "
          f"{service.verify_brief(brief['brief_id'])['verified']}.")

    print(f"\nBefore any act, the brief renders as a draft: "
          f"{brief['publication']}. A named publisher publishes "
          f"the exact version, bound by its fingerprint:")
    act = service.publish_artefact(
        "weekly_brief", brief["brief_id"],
        "A. Raman (head of strategy)", "2026-03-30",
        note="week ending 29 March, for the Monday meeting")
    outlook_act = service.publish_artefact(
        "season_outlook", brief["sections"][0]["artefact_ids"][0],
        "A. Raman (head of strategy)", "2026-03-30")
    state = service.publication_state("weekly_brief", brief["brief_id"])
    print(f"    {act['act_id']}: {act['artefact_id']} published by "
          f"{act['published_by']} — state now {state['status']}, "
          f"current: {state['is_current']}.")
    print(f"    the season outlook is published under its own "
          f"family ({outlook_act['family_key']}). The decision "
          f"log re-derives from the acts alone:")
    for entry in service.decision_log():
        print(f"    #{entry['seq']} {entry['published_at']} "
              f"{entry['published_by']} published "
              f"{entry['artefact_id']} ({entry['family_key']})")
    print(f"  the log verifies gapless: "
          f"{service.verify_decision_log()['verified']}.")

    pack_row = service.export_pack("product", "DAP", "demo desk",
                                   "2026-03-31")
    out_dir = tmp / "dap-pack"
    service.write_pack(pack_row["pack_id"], out_dir)
    print(f"\nThe DAP report pack {pack_row['pack_id']} exports "
          f"{len(pack_row['appendix'])} provenance entries over "
          f"{sorted(pack_row['manifest'])}; it verifies against "
          f"the store: "
          f"{service.verify_pack(pack_row['pack_id'])['verified']}.")
    target = out_dir / "demand.csv"
    data = bytearray(target.read_bytes())
    data[20] = ord("9") if data[20] != ord("9") else ord("1")
    target.write_bytes(bytes(data))
    caught = service.verify_pack_dir(pack_row["pack_id"], out_dir)
    print(f"  one byte flipped in the exported demand.csv — the "
          f"manifest names it:")
    for problem in caught["problems"]:
        print(f"    tamper: {problem}")

    print("\n--- Round 11: the production data plane ---")

    registry = service.ingest_sources()
    print(f"\nThe source registry admits {len(registry)} feeds — "
          f"each with a fact class, a cadence, an owner and a "
          f"freshness rule:")
    for source in registry:
        print(f"  {source['source_id']:<26} {source['fact_class']:<18} "
              f"{source['cadence']:<12} owner: {source['owner']}, "
              f"fresh within {source['freshness_days']} days")

    feed_rows = [
        {"series_kind": "product", "item": "DAP", "month": "2026-05",
         "price": 27050.0, "unit": "INR/tonne",
         "source": "intl_price_feed", "as_of": "2026-05-05"},
        {"series_kind": "product", "item": "UREA", "month": "2026-05",
         "price": 5910.0, "unit": "INR/tonne",
         "source": "intl_price_feed", "as_of": "2026-05-05"},
        {"series_kind": "feedstock", "item": "NATURAL_GAS",
         "month": "2026-05", "price": 3.41, "unit": "USD/MMBtu",
         "source": "intl_price_feed", "as_of": "2026-05-05"},
    ]
    batch = service.load_connector_batch(
        "intl_price_feed", feed_rows, "demo desk", "2026-05-06")
    prices_before = len(service.store.price_points())
    print(f"\nA price-feed batch lands ({batch['batch_id']}): "
          f"{batch['received']} received, {batch['inserted']} "
          f"inserted, {batch['duplicates']} duplicates, "
          f"{batch['quarantined']} quarantined, {batch['refused']} "
          f"refused — the counts reconcile, and the batch verifies: "
          f"{service.verify_ingest_batch(batch['batch_id'])['verified']}.")
    replay = service.load_connector_batch(
        "intl_price_feed", feed_rows, "demo desk", "2026-05-06")
    print(f"  replaying the identical batch returns the stored "
          f"report ({replay['batch_id']}) and lands nothing: "
          f"price points still {len(service.store.price_points())} "
          f"of {prices_before}.")

    dirty_rows = feed_rows + [
        {"series_kind": "product", "item": "DAP", "month": "2026-05",
         "price": 99999.0, "unit": "INR/tonne",
         "source": "intl_price_feed", "as_of": "2026-05-06"},
        {"series_kind": "product", "item": "POTASH_X",
         "month": "2026-05", "price": 1200.0, "unit": "INR/tonne",
         "source": "intl_price_feed", "as_of": "2026-05-06"},
        {"series_kind": "product", "item": "MOP", "month": "2026-05",
         "price": -10.0, "unit": "INR/tonne",
         "source": "intl_price_feed", "as_of": "2026-05-06"},
        {"series_kind": "product", "item": "MOP", "month": "2026-05",
         "price": 24100.0, "unit": "INR/tonne",
         "source": "intl_price_feed"},
    ]
    dirty = service.load_connector_batch(
        "intl_price_feed", dirty_rows, "demo desk", "2026-05-07")
    print(f"\nThe next day's batch repeats the three good rows and "
          f"carries four bad ones ({dirty['batch_id']}): "
          f"{dirty['duplicates']} duplicates, "
          f"{dirty['quarantined']} quarantined, {dirty['refused']} "
          f"refused at the port. The held rows, with their reasons:")
    for held in service.list_quarantine(batch_id=dirty["batch_id"]):
        print(f"  {held['quarantine_id']}: {held['reason']:<24} "
              f"{held['natural_key']} — {held['detail']}")
    for refusal in dirty["refusals"]:
        print(f"  row {refusal['row_index']}: refused at the port — "
              f"{refusal['reason']} (missing "
              f"{', '.join(refusal['missing'])})")
    print(f"  no bad row reached the fact table: price points "
          f"still {len(service.store.price_points())}.")

    first = service.submit_correction(
        "price_points",
        {"series_kind": "product", "item": "DAP", "month": "2026-05",
         "price": 27125.5, "unit": "INR/tonne",
         "source": "intl_price_feed", "as_of": "2026-05-08"},
        None, "demo desk")
    second = service.submit_correction(
        "price_points",
        {"series_kind": "product", "item": "DAP", "month": "2026-05",
         "price": 27130.0, "unit": "INR/tonne",
         "source": "intl_price_feed", "as_of": "2026-05-09"},
        first["correction_id"], "demo desk")
    dap_key = {"series_kind": "product", "item": "DAP",
               "month": "2026-05"}
    stored_dap = next(
        p for p in service.store.price_points("product", "DAP")
        if p["month"] == "2026-05")
    effective = service.effective_fact("price_points", dap_key)
    chain = service.verify_correction_chain("price_points", dap_key)
    print(f"\nThe feed corrects its DAP print twice "
          f"({first['correction_id']} then "
          f"{second['correction_id']}). The stored fact is never "
          f"rewritten — it still reads {stored_dap['price']} — "
          f"while the effective row folds the chain to "
          f"{effective['price']}. The chain re-performs: "
          f"{chain['verified']}.")

    service.estimate_demand("DST-GUN", "UREA", "2025-26", "rabi",
                            "2026-04-15")
    actual_rows = [
        {"district_id": "DST-GUN", "crop_year": "2025-26",
         "season": "rabi", "product": "UREA",
         "actual_kind": "consumption", "quantity_tonnes": 45210.5,
         "source": "state_dispatch_returns", "as_of": "2026-04-15"},
    ]
    actuals_batch = service.load_connector_batch(
        "state_dispatch_returns", actual_rows, "demo desk",
        "2026-04-20")
    report = service.actuals_report("2025-26", "rabi")
    print(f"\nSeason-close actuals land as their own fact class "
          f"({actuals_batch['batch_id']}: "
          f"{actuals_batch['inserted']} inserted) — the estimate "
          f"tables are untouched. The actuals report joins by "
          f"natural key: {report['matched_count']} matched against "
          f"a struck estimate.")
    prior_rows = [
        {"district_id": "DST-GUN", "crop_year": "2023-24",
         "season": "rabi", "product": "MOP",
         "actual_kind": "dispatch", "quantity_tonnes": 12340.0,
         "source": "state_dispatch_returns", "as_of": "2025-04-15"},
    ]
    service.load_connector_batch(
        "state_dispatch_returns", prior_rows, "demo desk",
        "2025-05-06")
    prior = service.actuals_report("2023-24", "rabi")
    print(f"  a late return for a season before the tracked "
          f"window — no estimate was ever struck for it — is "
          f"reported, not dropped: {prior['unmatched_count']} "
          f"unmatched:")
    for label in prior["unmatched"]:
        print(f"  unmatched: {label}")

    service.estimate_demand("DST-GUN", "DAP", "2025-26", "rabi",
                            "2026-04-15")
    run = service.score_season("2025-26", "rabi", "demo desk",
                               "2026-04-25")
    cell = run["cells"][0]
    print(f"\nSeason close: the struck estimates are graded "
          f"against the actuals ({run['score_id']}: "
          f"{run['scored_count']} cell scored, run bias "
          f"{run['bias_tonnes']} tonnes). Guntur urea was "
          f"estimated at {cell['estimate_tonnes']} tonnes and "
          f"closed at {cell['actual_tonnes']} — an error of "
          f"{cell['error_tonnes']} tonnes "
          f"({cell['error_pct']}%). The pack attributes the "
          f"error across the estimate's own lines; the most "
          f"wrong line is {cell['most_wrong_driver']} at "
          f"{cell['most_wrong_attributed_error_tonnes']} "
          f"tonnes of it.")
    print(f"  the run re-performs by the second route: "
          f"{service.verify_score_run(run['score_id'])['verified']}.")
    dap = next(u for u in run["unmatched_estimates"]
               if u["label"] == "DST-GUN/2025-26/rabi/DAP")
    print(f"  estimates with no actual on record are named, "
          f"not dropped — {len(run['unmatched_estimates'])} "
          f"of them, including the DAP estimate just struck: "
          f"{dap['label']} ({dap['estimate_id']})")
    prior_run = service.score_season("2023-24", "rabi",
                                     "demo desk", "2025-05-10")
    print(f"  the earlier season scores no cells — nothing "
          f"was ever struck for it — and its actual is named "
          f"unmatched on the run's face: "
          f"{prior_run['unmatched_actuals']}")

    print("\n--- Round 13: the map, the morning board, the queue ---")
    reports = service.list_field_reports()
    unreviewed = [r for r in reports
                  if r["review_state"] == "unreviewed"]
    target = unreviewed[0] if unreviewed else (
        reports[0] if reports else None)
    if unreviewed:
        service.review_field_report(
            target["report_id"], "confirm", "demo reviewer",
            "corroborated", "2026-04-20")
        print(f"  one unreviewed field report "
              f"({target['report_id']}) is confirmed by a named "
              f"reviewer; the map's signal layer keeps it apart "
              f"from the reports still awaiting review.")
    market_map = service.market_map(
        "2025-26", "kharif", "demo desk", "2026-04-20")
    mop_short = [c for c in market_map["cells"]
                 if c["product"] == "MOP"
                 and c["district_gap_band"] == "short"]
    print(f"  the district map ({market_map['map_id']}): "
          f"{len(market_map['cells'])} cells composed from "
          f"artefact heads; MOP reads short in "
          f"{len(mop_short)} of 12 districts on its level gap "
          f"({mop_short[0]['gap_pct_of_demand']}% of demand) — "
          f"the import-only product whose tracked consumption "
          f"outruns its arrivals.")
    gly = next(c for c in market_map["cells"]
               if c["product"] == "GLYPHOSATE"
               and c["district_id"] == "DST-LUD")
    print(f"  glyphosate has no supply side, so its tiles "
          f"carry no product gap — Ludhiana's gap reading "
          f"comes from its own field signals alone "
          f"({gly['district_gap_basis']}), and the cell says "
          f"so on its face.")
    if target is not None:
        cell = next(c for c in market_map["cells"]
                    if c["district_id"] == target["district_id"]
                    and c["product"] == target["product"])
        signals = cell["signals"]
        print(f"  the signal layer for "
              f"{cell['district_name']}/{target['product']}: "
              f"{len(signals['confirmed'])} confirmed, "
              f"{len(signals['pending'])} pending — confirmed "
              f"evidence is never merged with the unreviewed "
              f"reports beside it.")
    print(f"  the map re-performs cell for cell: "
          f"{service.verify_map(market_map['map_id'])['verified']}.")

    board = service.morning_board(
        "regional_head", "2025-26", "kharif", "demo desk",
        "2026-04-20")
    lanes = {lane["lane"]: lane["rows"] for lane in board["lanes"]}
    print(f"  the regional head's morning board "
          f"({board['board_id']}): "
          f"{len(lanes['open_alerts'])} open alerts, "
          f"{len(lanes['districts_trending_short'])} district "
          f"rows trending short, {len(lanes['stale_figures'])} "
          f"stale share figures, "
          f"{len(lanes['pending_brief_approvals'])} brief "
          f"approvals pending — every lane ranked by its "
          f"pack, not by recency.")
    print(f"  the board re-derives lane for lane: "
          f"{service.verify_board(board['board_id'])['verified']}.")

    queue = service.gap_queue("2026-04-20")
    print(f"  the gap action queue holds {len(queue)} "
          f"item(s) — exactly the non-comfortable gap heads:")
    for view in queue:
        print(f"    {view['product']} {view['season']} "
              f"{view['crop_year']}: {view['band']}, owned by "
              f"{view['owner']}, due {view['due_date']} "
              f"({view['due_state']}) — {view['item_id']}")
    if queue:
        item = queue[0]
        view = service.assign_queue_item(
            item["item_id"], "demo duty manager",
            "Demo Assignee — supply desk", "2026-04-21")
        print(f"  an assign act moves the first item to "
              f"{view['owner']}; its state is still "
              f"{view['state']} — ownership is a fold of "
              f"acts, not a field someone edits.")
    print(f"  the queue re-derives end to end: "
          f"{service.verify_queue('2026-04-21')['verified']}.")

    print("\n--- Round 14: rollups, territory packs, readiness ---")
    rollup = service.regional_rollup(
        "2025-26", "kharif", "demo desk", "2026-04-21")
    urea14 = next(b for b in rollup["products"]
                  if b["product"] == "UREA")
    regions_line = ", ".join(
        f"{r['region']} {r['total_tonnes']:,.1f} t"
        for r in urea14["regions"])
    mop14 = next(b for b in rollup["products"]
                 if b["product"] == "MOP")
    print(f"  the kharif rollup ({rollup['rollup_id']}) "
          f"decomposes the outlook's own "
          f"{rollup['national_total_tonnes']:,.1f} t — UREA by "
          f"region: {regions_line}.")
    print(f"  MOP's gap rides by reference to "
          f"{mop14['gap']['gap_id']}: {mop14['gap']['band']}, "
          f"{mop14['gap']['gap_tonnes']:,.1f} t, struck against "
          f"{mop14['gap']['demand_basis'].replace('_', ' ')}.")
    print(f"  the rollup re-performs member by member: "
          f"{service.verify_rollup(rollup['rollup_id'])['verified']}.")

    pack14 = service.export_pack(
        "territory", "south", "demo desk", "2026-04-21")
    print(f"  the south territory pack ({pack14['pack_id']}) "
          f"renders the rollup for the season in scope at its "
          f"date — {len(pack14['tables']['districts'])} district "
          f"lines, {len(pack14['tables']['gaps'])} gap lines, "
          f"every figure the rollup's own; it verifies: "
          f"{service.verify_pack(pack14['pack_id'])['verified']}.")

    plan = service.season_readiness(
        "south", "2025-26", "kharif", "demo desk", "2026-04-21")
    lines = {line["line"]: line for line in plan["lines"]}
    print(f"  the south's kharif readiness plan "
          f"({plan['readiness_id']}) reads ready: {plan['ready']} "
          f"— blocking lines: "
          f"{', '.join(plan['blocking_lines']) or 'none'}.")
    for line in plan["lines"]:
        print(f"    {line['line']}: {line['status']} — "
              f"{line['detail']}")
    outlook_line = lines["outlook_published"]
    if outlook_line["status"] != "complete":
        outlook_id = outlook_line["figures"]["outlook_id"]
        service.publish_artefact(
            "season_outlook", outlook_id,
            "A. Raman (head of strategy)", "2026-04-22")
        print(f"  the head outlook {outlook_id} is published "
              f"by a named act — the line can now be scored "
              f"from the record, not from anyone's say-so.")
    risks = lines["open_risks"]["figures"]
    for row in risks["unowned_short_gaps"]:
        if row["item_id"]:
            service.assign_queue_item(
                row["item_id"], "demo duty manager",
                "Demo Assignee — supply desk", "2026-04-22")
            print(f"  the short {row['product']} gap's item "
                  f"{row['item_id']} is assigned by act.")
    for row in risks["open_alerts"]:
        service.acknowledge_alert(
            row["alert_id"], "demo duty manager",
            "seen on the readiness walk", "2026-04-22")
    if risks["open_alerts"]:
        print(f"  {len(risks['open_alerts'])} open alert(s) "
              f"acknowledged by named acts.")
    uncovered = [r for r in
                 lines["field_coverage"]["figures"]["districts"]
                 if not r["covered"]]
    if uncovered:
        service.sync_field_reports([
            {"submission_id": f"DEMO-R14-{r['district_id']}",
             "reporter": "Demo Field Officer",
             "district_id": r["district_id"], "product": "UREA",
             "signal_type": "demand_signal", "direction": "up",
             "observed_on": "2025-10-20",
             "detail": "Pre-season coverage visit."}
            for r in uncovered], "2026-04-22")
        for view in service.list_field_reports(state="unreviewed"):
            if view["submission_id"].startswith("DEMO-R14-"):
                service.review_field_report(
                    view["report_id"], "confirm", "demo reviewer",
                    "corroborated", "2026-04-22")
        print(f"  confirmed field reports land for "
              f"{len(uncovered)} uncovered district(s) — "
              f"coverage is evidence, not a checkbox.")
    plan2 = service.season_readiness(
        "south", "2025-26", "kharif", "demo desk", "2026-04-23")
    flipped = [line["line"] for line in plan2["lines"]
               if line["status"] == "complete"
               and lines[line["line"]]["status"] != "complete"]
    print(f"  re-struck, the plan ({plan2['readiness_id']}) "
          f"supersedes the first by link; lines flipped to "
          f"complete: {', '.join(flipped) or 'none'}; still "
          f"blocking: {', '.join(plan2['blocking_lines']) or 'none'} "
          f"— a short position is a fact of the market, and "
          f"the plan keeps naming it rather than reading ready "
          f"over it.")
    print(f"  both plans re-derive from the record: "
          f"{service.verify_readiness(plan['readiness_id'])['verified']}"
          f" and "
          f"{service.verify_readiness(plan2['readiness_id'])['verified']}.")

    print("\nDemo complete — every figure above came out of the store.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
