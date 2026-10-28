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

Round 3 adds the price-watch counters (all zero-tolerance):
  - missed_planted_alerts ........ a firing in the hand-derived
                                   truth set that the watch missed
  - false_alerts ................. a stored alert outside the
                                   truth set, or one the verifier
                                   cannot re-perform from its
                                   movements
  - duplicate_alerts ............. a second firing pass that stored
                                   or fired anything new, or two
                                   alerts for the same series, rule
                                   and period
  - state_edits_outside_acts ..... an alert row altered by an act
                                   (state lives only in the acts),
                                   or a state column on the alerts
                                   table at all
  - alert_without_movement ....... an alert whose triggering
                                   movements are missing or absent
                                   from the store

Round 4 adds the supply-tracker counters (all zero-tolerance):
  - position_identity_violations . a stored position whose
                                   identity fails, whose opening
                                   is not the prior month's
                                   closing, or that the verifier
                                   cannot re-perform line by line
  - planted_delay_dip_mismatch ... the planted delay's dip and
                                   recovery months in the DAP
                                   position chain != the record
  - gap_band_mismatches .......... a supply gap whose band,
                                   basis or programme figures miss
                                   the hand-computed fixtures for
                                   two products, or that the
                                   verifier cannot re-perform
  - projection_supersession_failures
                                   the slip-driven projection
                                   chain: a broken supersedes link,
                                   an unnamed slip, a wrong
                                   projected closing, or a
                                   projection the verifier cannot
                                   re-perform
  - position_tamper_undetected ... a stored position (or one of
                                   its lines) altered behind the
                                   store's back that the verifier
                                   did not catch

Round 5 adds the policy-registry counters (all zero-tolerance):
  - policy_registration_mismatches
                                   a planted event registered
                                   under the wrong class, window
                                   or stated effect, a second
                                   registration pass that stored
                                   anything, or a registration the
                                   verifier cannot re-perform
  - policy_impact_scope_mismatches
                                   an impact note whose members
                                   miss the hand-derived scope of
                                   two planted events, a note the
                                   verifier cannot re-perform, or
                                   a future-window event whose
                                   no-observed-scope statement is
                                   wrong
  - hypothetical_policy_leaks .... a hypothetical proposal that
                                   earned an impact note, marked
                                   the watch board, or listed
                                   among the real events
  - policy_supersession_failures . the hypothetical-to-real
                                   chain: a broken supersedes
                                   link, a proposal artefact
                                   altered by its supersession,
                                   or a head that did not move
  - policy_board_marker_mismatches
                                   board markers that are not
                                   exactly the open-window real
                                   events per series, or markers
                                   inflating the alert counts

Round 6 adds the competitor & share counters (all zero-tolerance):
  - share_arithmetic_mismatches .. a share whose observed-market
                                   reading does not sum to its
                                   own denominator, whose demand
                                   reading disagrees with the R2
                                   estimate, or that the verifier
                                   cannot re-perform — graded on
                                   two district-product-seasons
  - provenance_refusals_missing .. a competitor observation
                                   stored without its source or
                                   its observation date, or a
                                   provenance-less build the
                                   engine accepted
  - stale_exclusion_mismatches ... at a late read date, the
                                   excluded set is not exactly
                                   the aged-out observations, the
                                   exclusion is not named on the
                                   artefact, or stale months leak
                                   into the headline
  - not_current_mismatches ....... an all-stale cell that does
                                   not read `not_current`, or a
                                   product with no observations
                                   that does not read
                                   `no_observations`
  - movement_reperformance_failures
                                   a movement row that is not
                                   the difference of the two
                                   seasons' full-season readings,
                                   a biggest mover without its
                                   observation provenance, or a
                                   movement the verifier cannot
                                   re-perform
  - share_tamper_undetected ...... a stored share figure altered
                                   behind the store's back that
                                   the verifier did not catch

Later rounds extend this gate: spike/delay grading depth (R12).
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

    # --- Round 3: the price watch --------------------------------------
    counters.update({
        "missed_planted_alerts": 0,
        "false_alerts": 0,
        "duplicate_alerts": 0,
        "state_edits_outside_acts": 0,
        "alert_without_movement": 0,
    })
    # The firing truth over the planted series, derived by hand
    # from the stored prices under the pack's stated thresholds:
    # the September 2025 DAP spike and its unwind, the post-shock
    # baseline dislocation, and seven sustained drifts. Every
    # other series sits inside the pack's quiet bands.
    expected_alerts = {
        ("feedstock", "AMMONIA", "sustained_move", "2024-10", "watch"),
        ("product", "DAP", "spike", "2025-09", "alert"),
        ("product", "DAP", "mom_move", "2025-09", "alert"),
        ("product", "DAP", "baseline_move", "2025-09", "alert"),
        ("product", "DAP", "mom_move", "2025-10", "alert"),
        ("product", "DAP", "baseline_move", "2025-10", "watch"),
        ("product", "DAP", "mom_move", "2025-11", "alert"),
        ("product", "DAP", "baseline_move", "2025-11", "watch"),
        ("product", "DAP", "baseline_move", "2025-12", "watch"),
        ("product", "DAP", "baseline_move", "2026-01", "watch"),
        ("product", "DAP", "baseline_move", "2026-02", "watch"),
        ("product", "DAP", "baseline_move", "2026-03", "watch"),
        ("product", "GLYPHOSATE", "sustained_move", "2025-09", "watch"),
        ("product", "MOP", "sustained_move", "2025-03", "watch"),
        ("product", "NPK_10_26_26", "sustained_move", "2024-10", "watch"),
        ("product", "NPK_10_26_26", "sustained_move", "2025-08", "watch"),
        ("product", "UREA", "sustained_move", "2025-01", "watch"),
        ("product", "UREA", "sustained_move", "2025-06", "watch"),
    }
    service.run_price_watch(as_of)
    fired = service.list_alerts()
    got_alerts = {
        (a["series_kind"], a["item"], a["rule_id"], a["period_month"], a["band"])
        for a in fired
    }
    counters["missed_planted_alerts"] += len(expected_alerts - got_alerts)
    counters["false_alerts"] += len(got_alerts - expected_alerts)
    for alert in fired:
        if service.verify_alert(alert["alert_id"]):
            counters["false_alerts"] += 1
        if not alert["movement_ids"] or any(
            store.get_movement(mid) is None for mid in alert["movement_ids"]
        ):
            counters["alert_without_movement"] += 1
    # The spike, specifically: one DAP spike alert, September 2025,
    # alert band — and the October decay fires no second spike.
    spikes = [a for a in fired if a["rule_id"] == "spike"]
    if len(spikes) != 1 or spikes[0]["period_month"] != "2025-09" or spikes[0]["band"] != "alert":
        counters["missed_planted_alerts"] += 1
    if any(a["rule_id"] == "spike" and a["period_month"] == "2025-10" for a in fired):
        counters["false_alerts"] += 1

    # Idempotency: a second pass over unchanged prices is a no-op,
    # and no (series, rule, period) carries two alerts.
    second = service.run_price_watch(as_of)
    if second["movements_stored"] or second["alerts_fired"]:
        counters["duplicate_alerts"] += 1
    keys = [(a["series_kind"], a["item"], a["rule_id"], a["period_month"]) for a in fired]
    counters["duplicate_alerts"] += len(keys) - len(set(keys))

    # State lives only in acts: the alerts table has no state
    # column, and recording acts leaves the alert row itself
    # byte-identical while the derived state moves.
    raw = sqlite3.connect(settings.sqlite_path)
    columns = [r[1] for r in raw.execute("PRAGMA table_info(price_alerts)")]
    raw.close()
    if "state" in columns:
        counters["state_edits_outside_acts"] += 1
    if spikes:
        spike_alert = spikes[0]
        row_before = store.get_alert(spike_alert["alert_id"])
        acked = service.acknowledge_alert(
            spike_alert["alert_id"], actor="eval.desk@kaveri.example",
            note="Eval pass: acknowledging the planted spike.", as_of=as_of,
        )
        if acked["state"] != "acknowledged" or store.get_alert(spike_alert["alert_id"]) != row_before:
            counters["state_edits_outside_acts"] += 1
        closed = service.close_alert(
            spike_alert["alert_id"], actor="eval.desk@kaveri.example",
            closing_reason="explained_by_event", as_of=as_of,
        )
        if closed["state"] != "closed" or store.get_alert(spike_alert["alert_id"]) != row_before:
            counters["state_edits_outside_acts"] += 1

    # --- Round 4: the supply tracker -----------------------------------
    counters.update({
        "position_identity_violations": 0,
        "planted_delay_dip_mismatch": 0,
        "gap_band_mismatches": 0,
        "projection_supersession_failures": 0,
        "position_tamper_undetected": 0,
    })
    positionable = ("UREA", "DAP", "NPK_10_26_26", "MOP")
    chains = {
        product: service.supply_positions(product, as_of) for product in positionable
    }
    for product, chain in chains.items():
        if [p["month"] for p in chain] != sorted(p["month"] for p in chain) \
                or len(chain) != 24:
            counters["position_identity_violations"] += 1
        for position in chain:
            identity = (
                position["opening_tonnes"]
                + (position["production_actual_tonnes"] or 0.0)
                + position["imports_tonnes"]
                - position["consumption_tonnes"]
            )
            if abs(identity - position["closing_tonnes"]) > 0.002:
                counters["position_identity_violations"] += 1
            if service.verify_position(product, position["month"]):
                counters["position_identity_violations"] += 1
        for prior, current in zip(chain, chain[1:]):
            if current["opening_tonnes"] != prior["closing_tonnes"]:
                counters["position_identity_violations"] += 1

    # The planted delay in the position chain: nothing lands for
    # DAP in the expected month or the month after; the delayed
    # vessel is the only December arrival, named on the line.
    dap = {p["month"]: p for p in chains["DAP"]}
    if dap["2025-10"]["imports_tonnes"] != 0.0 or dap["2025-11"]["imports_tonnes"] != 0.0:
        counters["planted_delay_dip_mismatch"] += 1
    if dap["2025-12"]["imports_tonnes"] != 55000.0:
        counters["planted_delay_dip_mismatch"] += 1
    december_lines = store.position_lines(dap["2025-12"]["position_id"])
    december_imports = next(
        l for l in december_lines if l["component"] == "import_arrivals"
    )
    named = [s["shipment_id"] for s in december_imports["inputs"]["shipments"]]
    if named != [delay["shipment_id"]]:
        counters["planted_delay_dip_mismatch"] += 1
    landed = {
        p["month"]: p["imports_tonnes"] for p in chains["DAP"] if p["imports_tonnes"]
    }
    if landed != {"2024-07": 64000.0, "2024-11": 58000.0,
                  "2025-07": 61000.0, "2025-12": 55000.0}:
        counters["planted_delay_dip_mismatch"] += 1

    # Gap fixtures, hand-computed for two products: DAP's kharif
    # programme runs short on the slipped tonnage and resolves
    # when the vessel lands; import-only MOP binds on the level
    # reading instead.
    gap_oct = service.supply_gap("DAP", "2025-26", "kharif", "2025-10-31")
    if not (
        gap_oct["band"] == "short"
        and gap_oct["band_basis"] == "import_programme_cover"
        and gap_oct["due_imports_tonnes"] == 116000.0
        and gap_oct["credited_imports_tonnes"] == 61000.0
        and gap_oct["slipped_tonnes"] == 55000.0
        and gap_oct["programme_cover_pct"] == 52.5862
        and gap_oct["available_tonnes"] == 7519322.147
    ):
        counters["gap_band_mismatches"] += 1
    gap_dec = service.supply_gap("DAP", "2025-26", "kharif", "2025-12-31")
    if not (
        gap_dec["band"] == "comfortable"
        and gap_dec["programme_cover_pct"] == 100.0
        and gap_dec["slipped_tonnes"] == 0.0
        and gap_dec["available_tonnes"] == 7574322.147
        and gap_dec["supersedes"] == gap_oct["gap_id"]
    ):
        counters["gap_band_mismatches"] += 1
    gap_mop = service.supply_gap("MOP", "2025-26", "kharif", "2025-11-30")
    if not (
        gap_mop["band"] == "short"
        and gap_mop["band_basis"] == "level_gap"
        and gap_mop["available_tonnes"] == 29534.942
        and gap_mop["gap_tonnes"] == -49790.311
        and gap_mop["gap_pct_of_demand"] == -62.7673
    ):
        counters["gap_band_mismatches"] += 1
    for product, year, season in (
        ("DAP", "2025-26", "kharif"), ("MOP", "2025-26", "kharif")
    ):
        if service.verify_gap(product, year, season):
            counters["gap_band_mismatches"] += 1

    # The projection chain over the delay: scheduled, then slipped
    # and named, then landed into the basis — each version
    # superseding by link and re-performable.
    proj_first = service.supply_projection("DAP", "2025-26", "rabi", "2025-09-30")
    if not (
        proj_first["closing_tonnes"] == 8905455.248
        and proj_first["status"] == "partial"
        and proj_first["assumption_set"]["beyond_plan_months"] == ["2026-04"]
        and proj_first["assumption_changes"] == []
    ):
        counters["projection_supersession_failures"] += 1
    proj_slip = service.supply_projection("DAP", "2025-26", "rabi", "2025-11-30")
    kinds = {(c["kind"], c["shipment_id"]) for c in proj_slip["assumption_changes"]}
    if not (
        proj_slip["supersedes"] == proj_first["projection_id"]
        and proj_slip["closing_tonnes"] == 8832147.348
        and ("slipped_unlanded", delay["shipment_id"]) in kinds
    ):
        counters["projection_supersession_failures"] += 1
    proj_landed = service.supply_projection("DAP", "2025-26", "rabi", "2025-12-31")
    kinds = {(c["kind"], c["shipment_id"]) for c in proj_landed["assumption_changes"]}
    if not (
        proj_landed["supersedes"] == proj_slip["projection_id"]
        and proj_landed["closing_tonnes"] == 8850908.948
        and ("landed_after_slip", delay["shipment_id"]) in kinds
    ):
        counters["projection_supersession_failures"] += 1
    if service.verify_projection("DAP", "2025-26", "rabi"):
        counters["projection_supersession_failures"] += 1

    # Tamper: a position's closing altered behind the store's
    # back (payload and column together) must fail verification;
    # restoring it must verify clean; a component line altered
    # the same way must fail too.
    import json as _json

    victim = dap["2025-10"]
    raw = sqlite3.connect(settings.sqlite_path)
    payload = _json.loads(
        raw.execute(
            "SELECT payload FROM supply_positions WHERE position_id = ?",
            (victim["position_id"],),
        ).fetchone()[0]
    )
    payload["closing_tonnes"] += 1000.0
    raw.execute(
        "UPDATE supply_positions SET closing_tonnes = closing_tonnes + 1000, "
        "payload = ? WHERE position_id = ?",
        (_json.dumps(payload), victim["position_id"]),
    )
    raw.commit()
    if not service.verify_position("DAP", "2025-10"):
        counters["position_tamper_undetected"] += 1
    payload["closing_tonnes"] -= 1000.0
    raw.execute(
        "UPDATE supply_positions SET closing_tonnes = closing_tonnes - 1000, "
        "payload = ? WHERE position_id = ?",
        (_json.dumps(payload), victim["position_id"]),
    )
    raw.execute(
        "UPDATE supply_position_lines SET tonnes = tonnes + 500 "
        "WHERE position_id = ? AND component = 'import_arrivals'",
        (victim["position_id"],),
    )
    raw.commit()
    if not service.verify_position("DAP", "2025-10"):
        counters["position_tamper_undetected"] += 1
    raw.execute(
        "UPDATE supply_position_lines SET tonnes = tonnes - 500 "
        "WHERE position_id = ? AND component = 'import_arrivals'",
        (victim["position_id"],),
    )
    raw.commit()
    raw.close()
    if service.verify_position("DAP", "2025-10"):
        counters["position_tamper_undetected"] += 1

    # --- Round 5: the policy registry ------------------------------
    counters.update({
        "policy_registration_mismatches": 0,
        "policy_impact_scope_mismatches": 0,
        "hypothetical_policy_leaks": 0,
        "policy_supersession_failures": 0,
        "policy_board_marker_mismatches": 0,
    })
    # Registration: the six recorded events under the pack —
    # class, window, direction and driver derived by hand from
    # the pack's mapping and window rule.
    expected_registrations = {
        "POL-2024-001": ("subsidy_rate_change", "2024-04", "2024-11", "up", "price"),
        "POL-2024-002": ("price_control", "2024-06", "2024-11", "none", "price"),
        "POL-2025-001": ("production_incentive", "2025-02", "2025-04", "up", "demand_rate"),
        "POL-2025-002": ("subsidy_rate_change", "2025-08", "2025-11", "none", "price"),
        "POL-2025-003": ("export_restriction", "2025-09", "2025-11", "down", "supply"),
        "POL-2026-001": ("subsidy_rate_change", "2026-01", "2026-04", "none", "price"),
    }
    summary = service.register_policy_events(as_of)
    if summary["registered"] != 6 or summary["events_total"] != 6:
        counters["policy_registration_mismatches"] += 1
    if service.register_policy_events(as_of)["registered"] != 0:
        counters["policy_registration_mismatches"] += 1
    facts_by_id = {f["event_id"]: f for f in store.policy_events()}
    events_by_id = {e["event_id"]: e for e in service.list_policy_events()}
    if set(events_by_id) != set(expected_registrations):
        counters["policy_registration_mismatches"] += 1
    for event_id, (klass, from_m, to_m, direction, driver) in \
            expected_registrations.items():
        event = events_by_id.get(event_id)
        if event is None:
            counters["policy_registration_mismatches"] += 1
            continue
        effect = event["stated_effect"]
        if not (
            event["event_class"] == klass
            and event["effective_from_month"] == from_m
            and event["effective_to_month"] == to_m
            and effect["direction"] == direction
            and effect["driver"] == driver
            and effect["mechanism"] == facts_by_id[event_id]["expected_impact"]
            and event["products"] == facts_by_id[event_id]["impacted_products"]
            and event["hypothetical"] is False
        ):
            counters["policy_registration_mismatches"] += 1
        if service.verify_policy_event(event["registry_id"]):
            counters["policy_registration_mismatches"] += 1

    # Impact scope, hand-derived for two events. The export
    # restriction (DAP + phosphoric acid, 2025-09..2025-11):
    # DAP cells in kharif + rabi 2025-26 across all districts,
    # three price months on each of the two series, the three
    # DAP position heads.
    districts = {d["district_id"] for d in store.list_districts()}
    note = service.policy_impact(events_by_id["POL-2025-003"]["registry_id"], as_of)
    cells = {(c["district_id"], c["crop_year"], c["season"])
             for c in note["demand_cells"]}
    if cells != {
        (d, y, s) for d in districts
        for (y, s) in (("2025-26", "kharif"), ("2025-26", "rabi"))
    } or len(note["demand_estimate_ids"]) != 24:
        counters["policy_impact_scope_mismatches"] += 1
    series = {(s["series_kind"], s["item"]): s["months"] for s in note["price_series"]}
    if series != {
        ("product", "DAP"): ["2025-09", "2025-10", "2025-11"],
        ("feedstock", "PHOSPHORIC_ACID"): ["2025-09", "2025-10", "2025-11"],
    }:
        counters["policy_impact_scope_mismatches"] += 1
    if note["position_ids"] != [
        service.get_position("DAP", m)["position_id"]
        for m in ("2025-09", "2025-10", "2025-11")
    ] or note["status"] != "computed":
        counters["policy_impact_scope_mismatches"] += 1
    if service.verify_policy_impact(note["registry_id"]):
        counters["policy_impact_scope_mismatches"] += 1
    # The urea MRP notification (2024-06..2024-11): UREA cells
    # in kharif + rabi 2024-25, six price months, six positions.
    note_mrp = service.policy_impact(events_by_id["POL-2024-002"]["registry_id"], as_of)
    cells = {(c["district_id"], c["crop_year"], c["season"])
             for c in note_mrp["demand_cells"]}
    if cells != {
        (d, y, s) for d in districts
        for (y, s) in (("2024-25", "kharif"), ("2024-25", "rabi"))
    } or len(note_mrp["price_series"]) != 1 \
            or note_mrp["price_series"][0]["point_count"] != 6 \
            or len(note_mrp["position_ids"]) != 6:
        counters["policy_impact_scope_mismatches"] += 1
    if service.verify_policy_impact(note_mrp["registry_id"]):
        counters["policy_impact_scope_mismatches"] += 1

    # A real event whose window sits beyond the tracked data:
    # the note must state no_observed_scope with empty members.
    future = service.register_policy_event({
        "event_id": "POL-EVAL-FUTURE", "event_class": "environmental_rule",
        "title": "Application rule announced for a future season",
        "detail": "A rule whose window sits beyond the tracked data.",
        "effective_from_month": "2026-05", "effective_to_month": "2026-06",
        "products": ["CHLORPYRIFOS"], "districts": [],
        "direction": "down",
        "mechanism": "Application of the active is restricted from May 2026.",
        "hypothetical": False,
        "source": "eval_event_register",
        "registered_by": "eval.desk@kaveri.example",
    }, as_of)
    future_note = service.policy_impact(future["registry_id"], as_of)
    if not (
        future_note["status"] == "no_observed_scope"
        and future_note["demand_estimate_ids"] == []
        and future_note["price_series"] == []
        and future_note["position_ids"] == []
    ) or service.verify_policy_impact(future["registry_id"]):
        counters["policy_impact_scope_mismatches"] += 1

    # Hypothetical separation, then the supersession into a real
    # event. The proposal shares the restriction's window and
    # product, so any leak would be visible on the board and in
    # the note tables.
    hyp_spec = {
        "event_id": "POL-EVAL-HYP", "event_class": "import_duty_change",
        "title": "Proposed import duty revision on DAP (eval scenario)",
        "detail": "A duty revision under discussion.",
        "effective_from_month": "2025-09", "effective_to_month": "2025-11",
        "products": ["DAP"], "districts": [],
        "direction": "down",
        "mechanism": "A lower duty would move the landed cost of DAP arrivals down.",
        "source": "eval_event_register",
        "registered_by": "eval.desk@kaveri.example",
    }
    proposal = service.register_policy_event({**hyp_spec, "hypothetical": True}, as_of)
    try:
        service.policy_impact(proposal["registry_id"], as_of)
        counters["hypothetical_policy_leaks"] += 1  # a note was computed!
    except ValueError:
        pass
    if store.list_policy_impact_notes(proposal["registry_id"]):
        counters["hypothetical_policy_leaks"] += 1
    if proposal["registry_id"] in [
        e["registry_id"] for e in service.list_policy_events(hypothetical=False)
    ]:
        counters["hypothetical_policy_leaks"] += 1
    if [e["event_id"] for e in service.list_policy_events(hypothetical=True)] != [
        "POL-EVAL-HYP"
    ]:
        counters["hypothetical_policy_leaks"] += 1
    board = {row["item"]: row for row in service.watch_board()}
    if any(
        m["event_id"] == "POL-EVAL-HYP"
        for row in board.values() for m in row["policy_markers"]
    ):
        counters["hypothetical_policy_leaks"] += 1

    # The chain: the proposal artefact must survive its
    # supersession byte-identical, the head must move, and the
    # real registration must earn the note the proposal could not.
    snapshot = service.get_policy_event(proposal["registry_id"])
    enacted = service.register_policy_event({
        **hyp_spec,
        "title": "Import duty revision on DAP (registered as enacted)",
        "detail": "The duty revision is now on record as a real event.",
        "mechanism": "A lower duty moves the landed cost of DAP arrivals down.",
        "hypothetical": False,
    }, as_of)
    if enacted["supersedes"] != proposal["registry_id"]:
        counters["policy_supersession_failures"] += 1
    if service.get_policy_event(proposal["registry_id"]) != snapshot:
        counters["policy_supersession_failures"] += 1
    versions = service.policy_event_versions("POL-EVAL-HYP")
    if [v["registry_id"] for v in versions] != [
        proposal["registry_id"], enacted["registry_id"]
    ]:
        counters["policy_supersession_failures"] += 1
    heads = {e["event_id"]: e for e in service.list_policy_events()}
    if heads["POL-EVAL-HYP"]["registry_id"] != enacted["registry_id"]:
        counters["policy_supersession_failures"] += 1
    enacted_note = service.policy_impact(enacted["registry_id"], as_of)
    if enacted_note["status"] != "computed" \
            or len(enacted_note["demand_estimate_ids"]) != 24 \
            or service.verify_policy_impact(enacted["registry_id"]):
        counters["policy_supersession_failures"] += 1

    # Board markers: at the reference month (2026-03, the latest
    # tracked price month) only the rabi subsidy revision's
    # window is open — on DAP and NPK — and the alert counts are
    # exactly the alert states, markers or no markers.
    board = {row["item"]: row for row in service.watch_board()}
    for item, row in board.items():
        expected = ["POL-2026-001"] if item in ("DAP", "NPK_10_26_26") else []
        if [m["event_id"] for m in row["policy_markers"]] != expected \
                or row["policy_marker_count"] != len(expected):
            counters["policy_board_marker_mismatches"] += 1
    open_alerts = len([a for a in service.list_alerts() if a["state"] != "closed"])
    if sum(r["open_alert_count"] for r in board.values()) != open_alerts:
        counters["policy_board_marker_mismatches"] += 1

    # --- Round 6: competitor & market-share intelligence -----------
    counters.update({
        "share_arithmetic_mismatches": 0,
        "provenance_refusals_missing": 0,
        "stale_exclusion_mismatches": 0,
        "not_current_mismatches": 0,
        "movement_reperformance_failures": 0,
        "share_tamper_undetected": 0,
    })

    from fertilizer_intelligence.share import observation_from_point

    built = service.build_competitor_observations()
    if built["observations_stored"] != 720 or built["observations_total"] != 720:
        counters["provenance_refusals_missing"] += 1
    if service.build_competitor_observations()["observations_stored"] != 0:
        counters["provenance_refusals_missing"] += 1
    observations = service.list_competitor_observations()
    if len(observations) != 720 or any(
        not o["source"] or not o["as_of"] for o in observations
    ):
        counters["provenance_refusals_missing"] += 1
    # Provenance is constitutive: a point without source or
    # without date is refused at the build, never stored bare.
    probe = {
        "competitor": "AgroNutrient Ltd", "region": "north",
        "product": "DAP", "month": "2025-09", "volume_tonnes": 100.0,
        "price": 27000.0, "source": "competitor_field_tracking",
        "as_of": "2025-09-30",
    }
    districts = store.list_districts()
    for broken in (
        {**probe, "source": ""},
        {k: v for k, v in probe.items() if k != "source"},
        {**probe, "as_of": ""},
        {k: v for k, v in probe.items() if k != "as_of"},
    ):
        try:
            observation_from_point(broken, districts)
            counters["provenance_refusals_missing"] += 1  # accepted!
        except ValueError:
            pass
    for observation in observations[:25]:
        if service.verify_competitor_observation(observation["observation_id"]):
            counters["provenance_refusals_missing"] += 1

    # Share arithmetic on two district-product-seasons: the
    # observed reading sums to its own denominator, the demand
    # reading's Kaveri line matches the R2 total independently,
    # and the verifier re-performs both.
    for district, product, crop_year, season in (
        ("DST-LUD", "DAP", "2025-26", "kharif"),
        ("DST-GUN", "UREA", "2025-26", "rabi"),
    ):
        share = service.market_share(district, product, crop_year, season)
        if share["status"] != "current" or service.verify_share(share["share_id"]):
            counters["share_arithmetic_mismatches"] += 1
            continue
        headline = share["headline"]
        sellers = [headline["kaveri"]] + headline["competitors"]
        if abs(sum(s["volume_tonnes"] for s in sellers)
               - headline["observed_market_tonnes"]) > 0.01:
            counters["share_arithmetic_mismatches"] += 1
        if abs(sum(s["share_of_observed_market_pct"] for s in sellers)
               - 100.0) > 0.01:
            counters["share_arithmetic_mismatches"] += 1
        estimate = service.estimate_demand(district, product, crop_year, season, as_of)
        kaveri = headline["kaveri"]
        if abs(kaveri["share_of_total_demand_pct"]
               - round(100.0 * kaveri["volume_tonnes"]
                       / estimate["total_tonnes"], 4)) > 0.0002:
            counters["share_arithmetic_mismatches"] += 1
        if headline["demand_tonnes"] != estimate["total_tonnes"]:
            counters["share_arithmetic_mismatches"] += 1

    # Staleness: at 2026-03-31 the kharif headline excludes
    # exactly the nine June–August observations, names the
    # exclusion, and keeps stale months out of the headline.
    late = service.market_share("DST-LUD", "DAP", "2025-26", "kharif", "2026-03-31")
    excluded = late["headline"]["excluded_observations"] if late["headline"] else []
    expected_excluded = {
        f"OBS-{slug}-north-DAP-2025-{month}"
        for slug in ("AGRONUTRIENT-LTD", "BHARATFERT-CORP", "SAGAR-CHEMICALS")
        for month in ("06", "07", "08")
    }
    if {e["observation_id"] for e in excluded} != expected_excluded:
        counters["stale_exclusion_mismatches"] += 1
    if late["headline_note"] != "headline excludes 9 stale observations":
        counters["stale_exclusion_mismatches"] += 1
    if not late["headline"] or late["headline"]["months"] != [
        "2025-09", "2025-10", "2025-11"
    ]:
        counters["stale_exclusion_mismatches"] += 1
    stale_read = service.share_stale_exclusions(
        "DST-LUD", "DAP", "2025-26", "kharif", "2026-03-31")
    if stale_read["stale_count"] != 9:
        counters["stale_exclusion_mismatches"] += 1
    if service.verify_share(late["share_id"]):
        counters["stale_exclusion_mismatches"] += 1

    # Named states: all-stale reads not_current; a product
    # with no tracked observations reads no_observations.
    old = service.market_share("DST-LUD", "DAP", "2024-25", "rabi", "2026-03-31")
    if old["status"] != "not_current" or old["headline"] is not None:
        counters["not_current_mismatches"] += 1
    none_share = service.market_share("DST-LUD", "GLYPHOSATE", "2025-26", "kharif")
    if none_share["status"] != "no_observations" \
            or none_share["headline"] is not None:
        counters["not_current_mismatches"] += 1

    # Movement: every row is the difference of the two
    # seasons' full-season readings, and the biggest mover
    # carries its observation provenance in both years.
    movement = service.share_movement("DST-LUD", "DAP", "kharif", as_of)
    if service.verify_share_movement(movement["movement_id"]):
        counters["movement_reperformance_failures"] += 1
    season_shares = {
        year: service.market_share("DST-LUD", "DAP", year, "kharif")
        for year in ("2024-25", "2025-26")
    }

    def _observed_pct(share):
        reading = share["full_season"]
        out = {reading["kaveri"]["seller"]:
               reading["kaveri"]["share_of_observed_market_pct"]}
        for competitor in reading["competitors"]:
            out[competitor["seller"]] = \
                competitor["share_of_observed_market_pct"]
        return out

    before = _observed_pct(season_shares["2024-25"])
    after = _observed_pct(season_shares["2025-26"])
    for row in movement["rows"]:
        if row["change_pp"] != round(after[row["seller"]] - before[row["seller"]], 4):
            counters["movement_reperformance_failures"] += 1
    mover = movement["biggest_mover"]
    for year, key in (("2024-25", "observation_ids_from"),
                      ("2025-26", "observation_ids_to")):
        expected_ids = sorted(
            p["observation_id"] for p in season_shares[year]["provenance"]
            if p["competitor"] == mover["seller"]
        )
        if mover[key] != expected_ids:
            counters["movement_reperformance_failures"] += 1

    # Tamper: a share figure altered behind the store's back
    # must fail verification; restoring it must pass again.
    import json as _json6
    import sqlite3 as _sqlite6

    victim = service.market_share("DST-LUD", "DAP", "2025-26", "kharif")
    raw = _sqlite6.connect(settings.sqlite_path)
    payload = _json6.loads(
        raw.execute(
            "SELECT payload FROM market_shares WHERE share_id = ?",
            (victim["share_id"],),
        ).fetchone()[0]
    )
    payload["headline"]["kaveri"]["volume_tonnes"] += 100.0
    raw.execute(
        "UPDATE market_shares SET payload = ? WHERE share_id = ?",
        (_json6.dumps(payload), victim["share_id"]),
    )
    raw.commit()
    if not service.verify_share(victim["share_id"]):
        counters["share_tamper_undetected"] += 1
    payload["headline"]["kaveri"]["volume_tonnes"] -= 100.0
    raw.execute(
        "UPDATE market_shares SET payload = ? WHERE share_id = ?",
        (_json6.dumps(payload), victim["share_id"]),
    )
    raw.commit()
    raw.close()
    if service.verify_share(victim["share_id"]):
        counters["share_tamper_undetected"] += 1

    print("Round 1+2+3+4+5+6 evals — fertilizer market intelligence")
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
