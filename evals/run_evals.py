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

Round 7 adds the field-signal counters (all zero-tolerance):
  - field_duplicate_syncs_landed . a re-sent submission (a full
                                   outbox re-send after a partial
                                   sync, a second planted
                                   promotion) that landed a second
                                   artefact
  - field_uncapped_unverified_influence
                                   an unreviewed report whose
                                   applied influence in an
                                   assessment exceeds the pack's
                                   unverified cap — graded on a
                                   fresh surge whose uncapped
                                   weight is above the cap
  - field_unattributed_artefacts . a field report artefact or an
                                   assessment line that does not
                                   name its reporter and review
                                   state
  - field_silent_overwrites ...... a conflicting payload under
                                   one submission id that replaced
                                   (or failed to link to) the
                                   original artefact
  - field_zero_influence_violations
                                   a queried or rejected report
                                   carrying nonzero influence, or a
                                   rejected report revived by a
                                   later confirm act
  - field_influence_reperformance_failures
                                   an assessment the verifier cannot
                                   re-perform from its reports,
                                   acts and estimate, or a tampered
                                   assessment/report the verifier
                                   did not catch

Round 8 adds the dashboard counters (all zero-tolerance):
  - dashboard_figures_without_lineage
                                   a figure on an assembled
                                   dashboard with no artefact id, no
                                   source as-of, or an artefact
                                   outside its panel's binding
  - dashboard_gap_panel_figures .. an invented figure carried by
                                   a gap panel — gaps state the
                                   data they would need, they
                                   never fill the space with a
                                   number
  - dashboard_mismatched_figures_served
                                   a served dashboard whose
                                   figures do not re-perform
                                   against their artefacts, or a
                                   figure altered behind the
                                   store's back that the dashboard
                                   verifier did not catch
  - dashboard_parse_refusals_unrecorded
                                   a model proposal refused by
                                   the governed schema without the
                                   refusal recorded on the spec
                                   and rendered as a gap panel, or
                                   a grammar-parsed question whose
                                   unanswerable part produced no
                                   gap panel

Round 9 adds the scenario counters (all zero-tolerance):
  - scenario_fork_identity_mismatch
                                   a fork whose lever deltas do
                                   not sum to its stated delta, a
                                   fork or comparison the verifier
                                   cannot re-perform, a slip fork
                                   whose import path is not the
                                   planted delay's path, or a
                                   tampered fork or comparison
                                   the verifier did not catch
  - scenario_base_mutated ........ a head artefact (estimate,
                                   projection, gap, watch board,
                                   policy note) that differs
                                   after fork work from before it
  - scenario_hypothetical_leak ... a scenario panel, figure or
                                   badge on a dashboard of
                                   record, or a head figure whose
                                   value moved after fork work
  - scenario_unbadged_figure_served
                                   a figure on a named-scenario
                                   dashboard without its scenario
                                   badge, or a badge stripped
                                   behind the store's back that
                                   the dashboard verifier did
                                   not catch
  - scenario_adoption_without_act  an adoption recorded
                                   without a named planner, an
                                   adoption of a fork outside
                                   the comparison, a refused
                                   adoption that was stored
                                   anyway, or a chain whose head
                                   is not the latest act

Round 10 adds the brief & publication counters (all zero-tolerance):
  - brief_figure_mismatch ....... a brief whose figures do
                                   not re-perform from their
                                   pinned artefacts, or a
                                   figure value that differs
                                   from its source artefact
  - brief_figures_without_lineage
                                   a brief figure carrying no
                                   artefact id or source as-of,
                                   or naming an artefact that
                                   is not in the store
  - brief_refusal_missing ........ a corrupted draft that
                                   was stored anyway, or whose
                                   wholesale refusal was not
                                   recorded as an artefact
  - brief_tamper_undetected ...... a brief figure altered
                                   behind the store's back
                                   that the brief verifier did
                                   not catch
  - publication_without_act ...... an artefact rendering as
                                   published with no act naming
                                   it, an unnamed publication
                                   that was recorded, or a
                                   publication of an unverified
                                   artefact
  - decision_log_gaps ............ a decision log that does
                                   not re-derive gaplessly from
                                   the acts, or a family chain
                                   that forks, cycles or orphans
                                   an act
  - pack_figure_mismatch ......... an export pack whose
                                   figures differ from the
                                   store's reads, or a tampered
                                   pack the verifier did not
                                   catch
  - pack_checksum_undetected ..... an exported file altered
                                   after export that the
                                   manifest check did not name

Round 11 adds the data-plane counters (all zero-tolerance):
  - ingest_replay_duplicates ..... a connector replay that
                                   landed a row twice, at
                                   batch level or row level
  - ingest_provenance_accepted ... a row without source or
                                   as_of that was stored
                                   instead of refused at the
                                   port, or any provenance
                                   gap in the fact tables
  - ingest_reconciliation_errors . a batch report whose
                                   counts do not reconcile,
                                   or that the batch verifier
                                   cannot re-perform
  - quarantine_reason_mismatches . planted bad rows held
                                   under reasons other than
                                   the exact named set
  - quarantined_rows_consumed .... a quarantined row that
                                   reached a fact table, or
                                   any fact count that moved
                                   under a dirty batch
  - correction_chain_errors ...... a correction chain that
                                   does not fold to its head,
                                   a stored fact rewritten by
                                   a correction, or tampering
                                   the chain verifier missed
  - actuals_overwriting_estimates  a season-close actual
                                   that changed an estimate,
                                   landed outside its own
                                   fact class, or went missing
                                   from the actuals report
  - actuals_unmatched_unreported . an actual whose natural
                                   key has no struck estimate
                                   that the report failed to
                                   name as unmatched

Round 12 adds the scoring & depth counters (all zero-tolerance):
  - score_reperformance_errors ... a score cell that does not
                                   re-perform from the estimate
                                   and actual artefacts by the
                                   second route, or tampering
                                   the verifier missed
  - score_attribution_errors ..... the hand-computed fixture's
                                   attributed errors or its
                                   most-wrong line differing
                                   from the stated pack method
  - score_unmatched_unreported ... a scored season's unmatched
                                   actual or estimate that the
                                   run failed to name
  - spike_lifecycle_errors ....... the planted spike alert's
                                   lifecycle state not folding
                                   from its acts alone, or an
                                   invalid transition recorded
                                   instead of refused
  - delay_gap_path_errors ........ the planted delay's gap
                                   path across the programme
                                   months differing from the
                                   stated bands, slipped
                                   tonnage or recovery, or a
                                   gap on the path that does
                                   not re-perform
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

    # --- Round 7: field signals & mobile intake -------------------
    counters.update({
        "field_duplicate_syncs_landed": 0,
        "field_uncapped_unverified_influence": 0,
        "field_unattributed_artefacts": 0,
        "field_silent_overwrites": 0,
        "field_zero_influence_violations": 0,
        "field_influence_reperformance_failures": 0,
    })

    from fertilizer_intelligence.field import FieldReviewError

    # Exactly-once landing: the planted promotion lands the
    # twelve R1 reports; a second promotion lands nothing.
    promoted = service.promote_planted_field_reports(as_of)
    if promoted["landed"] != 12 or promoted["reports_total"] != 12:
        counters["field_duplicate_syncs_landed"] += 1
    if service.promote_planted_field_reports(as_of)["landed"] != 0:
        counters["field_duplicate_syncs_landed"] += 1

    # Attribution: every landed artefact names its reporter,
    # district, product and observation date, and verifies.
    for view in service.list_field_reports():
        if not view["reporter"] or not view["district_id"] \
                or not view["product"] or not view["observed_on"] \
                or view["review_state"] != "unreviewed":
            counters["field_unattributed_artefacts"] += 1
        if service.verify_field_report(view["report_id"]):
            counters["field_influence_reperformance_failures"] += 1

    # The outbox walk: a partial sync, a full re-send (the
    # killed-mid-sync retry), a second full re-send — the two
    # submissions land exactly once each.
    outbox = [
        {"submission_id": "EVAL-PHONE-1", "reporter": "T. Rao (field officer)",
         "district_id": "DST-LUD", "product": "DAP",
         "signal_type": "demand_signal", "direction": "up",
         "observed_on": "2025-10-28",
         "detail": "Wheat-belt DAP offtake surging."},
        {"submission_id": "EVAL-PHONE-2", "reporter": "M. Khan (field officer)",
         "district_id": "DST-LUD", "product": "DAP",
         "signal_type": "stock_observed", "observed_on": "2025-10-29",
         "quantity_tonnes": 25.0},
    ]
    service.sync_field_reports(outbox[:1], "2025-11-02")
    retry = service.sync_field_reports(outbox, "2025-11-02")
    if [r["outcome"] for r in retry["receipt"]] != ["duplicate", "landed"]:
        counters["field_duplicate_syncs_landed"] += 1
    if service.sync_field_reports(outbox, "2025-11-02")["landed"] != 0:
        counters["field_duplicate_syncs_landed"] += 1
    if len(service.store.list_field_report_artefacts()) != 14:
        counters["field_duplicate_syncs_landed"] += 1

    # The cap, graded: the fresh unreviewed surge's uncapped
    # weight (6.0 decayed five days = 5.345394) is above the
    # pack's 1.5 cap, so its applied influence must be the cap
    # exactly; the stock report (5.0, four days) is capped too.
    capped = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "kharif", "2025-11-02")
    surge = next(
        l for l in capped["lines"] if l["report_id"] == "FSR-EVAL-PHONE-1")
    if surge["uncapped_pct"] != 5.345394 or surge["uncapped_pct"] <= 1.5:
        counters["field_uncapped_unverified_influence"] += 1
    if surge["applied_pct"] != 1.5 or surge["capped"] is not True:
        counters["field_uncapped_unverified_influence"] += 1
    for line in capped["lines"]:
        if line["review_state"] == "unreviewed" \
                and abs(line["applied_pct"]) > 1.5:
            counters["field_uncapped_unverified_influence"] += 1
        if not line["reporter"] or not line["review_state"]:
            counters["field_unattributed_artefacts"] += 1
    if service.verify_field_assessment(capped["assessment_id"]):
        counters["field_influence_reperformance_failures"] += 1

    # Zero influence: query the surge and reject the stock
    # report; the recomputation carries both at exactly zero,
    # and the rejected report refuses a reviving confirm.
    service.review_field_report(
        "FSR-EVAL-PHONE-1", "query", "Eval Reviewer", "needs_quantity",
        "2025-11-02")
    service.review_field_report(
        "FSR-EVAL-PHONE-2", "reject", "Eval Reviewer", "duplicate",
        "2025-11-02")
    zeroed = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "kharif", "2025-11-02")
    for line in zeroed["lines"]:
        if line["review_state"] in ("queried", "rejected") \
                and line["applied_pct"] != 0.0:
            counters["field_zero_influence_violations"] += 1
    if zeroed["adjustment_pct"] != 0.0:
        counters["field_zero_influence_violations"] += 1
    try:
        service.review_field_report(
            "FSR-EVAL-PHONE-2", "confirm", "Eval Reviewer",
            "corroborated", "2025-11-02")
        counters["field_zero_influence_violations"] += 1  # revived!
    except FieldReviewError:
        pass
    if service.verify_field_assessment(zeroed["assessment_id"]):
        counters["field_influence_reperformance_failures"] += 1

    # Conflicts: the same submission id with different words
    # lands alongside, linked both ways, the original's words
    # unoverwritten.
    changed = dict(outbox[0], detail="Corrected wording from the phone.")
    receipt = service.sync_field_reports([changed], "2025-11-03")
    if receipt["receipt"][0]["outcome"] != "conflict":
        counters["field_silent_overwrites"] += 1
    original = service.get_field_report("FSR-EVAL-PHONE-1")
    conflicting = service.get_field_report(receipt["receipt"][0]["report_id"])
    if original["detail"] != outbox[0]["detail"] \
            or conflicting["conflicts_with"] != "FSR-EVAL-PHONE-1" \
            or original["conflict_report_ids"] != [conflicting["report_id"]]:
        counters["field_silent_overwrites"] += 1

    # Tamper: an assessment figure altered behind the store's
    # back, and a report's reporter swapped in its payload —
    # both verifiers must catch them; restoring must pass.
    import json as _json7
    import sqlite3 as _sqlite7

    raw = _sqlite7.connect(settings.sqlite_path)
    payload = _json7.loads(raw.execute(
        "SELECT payload FROM field_signal_assessments WHERE assessment_id = ?",
        (zeroed["assessment_id"],),
    ).fetchone()[0])
    payload["adjusted_tonnes"] += 100.0
    raw.execute(
        "UPDATE field_signal_assessments SET payload = ? WHERE assessment_id = ?",
        (_json7.dumps(payload), zeroed["assessment_id"]),
    )
    raw.commit()
    if not service.verify_field_assessment(zeroed["assessment_id"]):
        counters["field_influence_reperformance_failures"] += 1
    payload["adjusted_tonnes"] -= 100.0
    raw.execute(
        "UPDATE field_signal_assessments SET payload = ? WHERE assessment_id = ?",
        (_json7.dumps(payload), zeroed["assessment_id"]),
    )
    raw.commit()
    report_payload = _json7.loads(raw.execute(
        "SELECT payload FROM field_signal_reports WHERE report_id = ?",
        ("FSR-EVAL-PHONE-1",),
    ).fetchone()[0])
    report_payload["reporter"] = "Someone Else"
    raw.execute(
        "UPDATE field_signal_reports SET payload = ? WHERE report_id = ?",
        (_json7.dumps(report_payload), "FSR-EVAL-PHONE-1"),
    )
    raw.commit()
    raw.close()
    if not service.verify_field_report("FSR-EVAL-PHONE-1"):
        counters["field_influence_reperformance_failures"] += 1

    # --- Round 8: dashboards — lineage, gaps, refusals -------
    # The mixed question from the demo: two answerable parts
    # and one part the data cannot answer. Every figure on
    # the assembled dashboard must carry its lineage, the gap
    # panel must carry none, the served dashboard must
    # verify, and a figure altered behind the store's back
    # must be caught — restoring it must verify clean again.
    import json as _json8
    import sqlite3 as _sqlite8
    from types import SimpleNamespace as _Namespace8

    counters.setdefault("dashboard_figures_without_lineage", 0)
    counters.setdefault("dashboard_gap_panel_figures", 0)
    counters.setdefault("dashboard_mismatched_figures_served", 0)
    counters.setdefault("dashboard_parse_refusals_unrecorded", 0)

    dash_as_of = "2026-04-15"
    dash_spec = service.ask_question(
        "How is DAP looking in Ludhiana this kharif, what's our "
        "share, and what's the monsoon outlook for groundnut in "
        "Anantapur?",
        "evals", dash_as_of, name="evals mixed question")
    dash_assembly = service.assemble_dashboard(dash_spec["spec_id"], dash_as_of)
    for panel in dash_assembly["panels"]:
        if panel["kind"] == "gap":
            counters["dashboard_gap_panel_figures"] += len(panel["figures"])
        for figure in panel["figures"]:
            if not figure["artefact_id"] or not figure["source_as_of"] \
                    or figure["artefact_id"] not in panel["artefact_ids"]:
                counters["dashboard_figures_without_lineage"] += 1
    if not service.verify_dashboard(
            dash_assembly["assembly_id"])["verified"]:
        counters["dashboard_mismatched_figures_served"] += 1

    raw8 = _sqlite8.connect(settings.sqlite_path)
    payload8 = _json8.loads(raw8.execute(
        "SELECT payload FROM dashboard_assemblies WHERE assembly_id = ?",
        (dash_assembly["assembly_id"],),
    ).fetchone()[0])
    payload8["panels"][0]["figures"][0]["value"] += 1000
    raw8.execute(
        "UPDATE dashboard_assemblies SET payload = ? WHERE assembly_id = ?",
        (_json8.dumps(payload8), dash_assembly["assembly_id"]),
    )
    raw8.commit()
    if service.verify_dashboard(dash_assembly["assembly_id"])["verified"]:
        counters["dashboard_mismatched_figures_served"] += 1
    payload8["panels"][0]["figures"][0]["value"] -= 1000
    raw8.execute(
        "UPDATE dashboard_assemblies SET payload = ? WHERE assembly_id = ?",
        (_json8.dumps(payload8), dash_assembly["assembly_id"]),
    )
    raw8.commit()
    raw8.close()
    if not service.verify_dashboard(
            dash_assembly["assembly_id"])["verified"]:
        counters["dashboard_mismatched_figures_served"] += 1

    # A hosted proposal outside the governed vocabulary is
    # refused: the refusal must be recorded on the spec AND
    # rendered as a gap panel. A grammar question with an
    # unanswerable part must produce a gap panel too.
    class _RefusingPort8:
        profile = "anthropic"
        model = "evals-stub"

        def complete(self, prompt, system=None):
            return _Namespace8(text=_json8.dumps(
                [{"kind": "monsoon_forecast", "scope": {}}]))

    refused_spec = service.ask_question(
        "Forecast the monsoon for me", "evals", dash_as_of,
        port=_RefusingPort8())
    if not refused_spec["parse"]["refusals"]:
        counters["dashboard_parse_refusals_unrecorded"] += 1
    if not any(p["kind"] == "gap" for p in refused_spec["panels"]):
        counters["dashboard_parse_refusals_unrecorded"] += 1
    grammar_spec = service.ask_question(
        "What's the monsoon outlook?", "evals", dash_as_of)
    if not any(p["kind"] == "gap" for p in grammar_spec["panels"]):
        counters["dashboard_parse_refusals_unrecorded"] += 1

    # --- Round 9: scenario forks — identity, discipline, adoption --
    # Forks are pinned views of heads, computed by the same
    # engines. The gate grades: every fork and comparison
    # re-performs; the demand identity sums exactly; a slip
    # fork reproduces the planted delay's import path;
    # tampering is caught; adoption needs a named act; a
    # named-scenario dashboard badges every figure; and the
    # heads are byte-identical after all of it.
    import json as _json9
    import sqlite3 as _sqlite9

    counters.setdefault("scenario_fork_identity_mismatch", 0)
    counters.setdefault("scenario_base_mutated", 0)
    counters.setdefault("scenario_hypothetical_leak", 0)
    counters.setdefault("scenario_unbadged_figure_served", 0)
    counters.setdefault("scenario_adoption_without_act", 0)

    service.estimate_demand("DST-LUD", "DAP", "2025-26", "kharif",
                            "2026-03-31")
    proj9 = service.supply_projection("DAP", "2025-26", "rabi",
                                      "2025-09-30")
    service.register_policy_events("2026-03-31")
    regs9 = service.list_policy_events(hypothetical=False)
    service.demand_outlook("2025-26", "kharif", "2026-03-31")
    service.demand_outlook("2025-26", "rabi", "2025-09-30")
    lead9 = service.role_default_dashboard("leadership", "evals",
                                           "2026-03-31")
    board9 = service.assemble_dashboard(lead9["spec_id"], "2026-03-31")

    def _heads9() -> str:
        estimates = store.list_estimates()
        return _json9.dumps({
            "estimates": estimates,
            "contributions": {
                e["estimate_id"]: store.estimate_contributions(
                    e["estimate_id"]) for e in estimates},
            "projections": store.list_projections(),
            "gap": service.supply_gap("DAP", "2025-26", "kharif",
                                      "2025-10-31"),
            "board": service.watch_board(),
            "note": service.policy_impact(
                regs9[0]["registry_id"], "2026-03-31"),
        }, sort_keys=True, default=str)

    heads_before9 = _heads9()

    fork_monsoon = service.ask_scenario(
        "what if the monsoon comes in 20 points lower for dap "
        "in ludhiana, kharif 2025-26",
        "evals", name="Monsoon shortfall")
    fork_slip = service.create_scenario(
        "supply_projection",
        {"product": "DAP", "crop_year": "2025-26", "season": "rabi"},
        [{"lever": "import_arrival_shift_months", "value": 2,
          "shipment_id": "IMP-DAP-2510"}],
        "evals", name="October vessel slips", as_of="2025-09-30")
    fork_elasticity = service.create_scenario(
        "demand_estimate",
        {"district_id": "DST-LUD", "product": "DAP",
         "crop_year": "2025-26", "season": "kharif"},
        [{"lever": "price_elasticity_override", "value": -0.10}],
        "evals")
    fork_production = service.create_scenario(
        "supply_projection",
        {"product": "DAP", "crop_year": "2025-26", "season": "rabi"},
        [{"lever": "production_shortfall_pct", "value": 25}],
        "evals", as_of="2025-09-30")
    for fork in (fork_monsoon, fork_slip, fork_elasticity,
                 fork_production):
        if not service.verify_scenario(fork["fork_id"])["verified"]:
            counters["scenario_fork_identity_mismatch"] += 1
    lever_sum9 = round(sum(r["lever_delta_tonnes"]
                           for r in fork_monsoon["reconciliation"]), 3)
    if lever_sum9 != fork_monsoon["delta_tonnes"]:
        counters["scenario_fork_identity_mismatch"] += 1
    slip_months9 = {r["month"]: r for r in fork_slip["reconciliation"]}
    if (slip_months9["2025-10"]["fork_imports_tonnes"],
            slip_months9["2025-11"]["fork_imports_tonnes"],
            slip_months9["2025-12"]["fork_imports_tonnes"]) != (0, 0, 55000):
        counters["scenario_fork_identity_mismatch"] += 1

    options9 = service.build_planning_options(
        proj9["projection_id"], [fork_slip["fork_id"]], "evals")
    if not service.verify_planning_options(
            options9["options_id"])["verified"]:
        counters["scenario_fork_identity_mismatch"] += 1

    raw9 = _sqlite9.connect(settings.sqlite_path)
    payload9 = _json9.loads(raw9.execute(
        "SELECT payload FROM scenario_forks WHERE fork_id = ?",
        (fork_slip["fork_id"],)).fetchone()[0])
    payload9["delta_tonnes"] = 999.0
    raw9.execute(
        "UPDATE scenario_forks SET payload = ? WHERE fork_id = ?",
        (_json9.dumps(payload9), fork_slip["fork_id"]))
    raw9.commit()
    if service.verify_scenario(fork_slip["fork_id"])["verified"]:
        counters["scenario_fork_identity_mismatch"] += 1
    payload9["delta_tonnes"] = 0.0
    raw9.execute(
        "UPDATE scenario_forks SET payload = ? WHERE fork_id = ?",
        (_json9.dumps(payload9), fork_slip["fork_id"]))
    raw9.commit()
    if not service.verify_scenario(fork_slip["fork_id"])["verified"]:
        counters["scenario_fork_identity_mismatch"] += 1
    payload9 = _json9.loads(raw9.execute(
        "SELECT payload FROM planning_options WHERE options_id = ?",
        (options9["options_id"],)).fetchone()[0])
    payload9["rows"][0]["figures"][1]["value"] += 500
    raw9.execute(
        "UPDATE planning_options SET payload = ? WHERE options_id = ?",
        (_json9.dumps(payload9), options9["options_id"]))
    raw9.commit()
    if service.verify_planning_options(options9["options_id"])["verified"]:
        counters["scenario_fork_identity_mismatch"] += 1
    raw9.close()

    for bad_actor in ("", "   "):
        try:
            service.adopt_option(options9["options_id"],
                                 fork_slip["fork_id"], bad_actor,
                                 "2026-04-15")
            counters["scenario_adoption_without_act"] += 1
        except ValueError:
            pass
    try:
        service.adopt_option(options9["options_id"],
                             fork_monsoon["fork_id"], "evals planner",
                             "2026-04-15")
        counters["scenario_adoption_without_act"] += 1
    except ValueError:
        pass
    if store.list_planning_adoptions(options9["options_id"]):
        counters["scenario_adoption_without_act"] += 1
    adoption9 = service.adopt_option(
        options9["options_id"], fork_slip["fork_id"], "evals planner",
        "2026-04-15")
    if service.current_adoption(
            options9["options_id"])["adoption_id"] != \
            adoption9["adoption_id"]:
        counters["scenario_adoption_without_act"] += 1
    if not service.verify_adoption(adoption9["adoption_id"])["verified"]:
        counters["scenario_adoption_without_act"] += 1

    spec9 = service.ask_question(
        "show me the monsoon shortfall scenario", "evals", "2026-03-31")
    assembly9 = service.assemble_dashboard(spec9["spec_id"], "2026-03-31")
    for panel in assembly9["panels"]:
        for figure in panel["figures"]:
            if not any(b.startswith("scenario:")
                       for b in figure["badges"]):
                counters["scenario_unbadged_figure_served"] += 1
    if not service.verify_dashboard(assembly9["assembly_id"])["verified"]:
        counters["scenario_unbadged_figure_served"] += 1
    raw9 = _sqlite9.connect(settings.sqlite_path)
    payload9 = _json9.loads(raw9.execute(
        "SELECT payload FROM dashboard_assemblies "
        "WHERE assembly_id = ?",
        (assembly9["assembly_id"],)).fetchone()[0])
    saved_badges9 = payload9["panels"][0]["figures"][0]["badges"]
    payload9["panels"][0]["figures"][0]["badges"] = []
    raw9.execute(
        "UPDATE dashboard_assemblies SET payload = ? "
        "WHERE assembly_id = ?",
        (_json9.dumps(payload9), assembly9["assembly_id"]))
    raw9.commit()
    if service.verify_dashboard(assembly9["assembly_id"])["verified"]:
        counters["scenario_unbadged_figure_served"] += 1
    payload9["panels"][0]["figures"][0]["badges"] = saved_badges9
    raw9.execute(
        "UPDATE dashboard_assemblies SET payload = ? "
        "WHERE assembly_id = ?",
        (_json9.dumps(payload9), assembly9["assembly_id"]))
    raw9.commit()
    raw9.close()
    if not service.verify_dashboard(assembly9["assembly_id"])["verified"]:
        counters["scenario_unbadged_figure_served"] += 1

    if _heads9() != heads_before9:
        counters["scenario_base_mutated"] += 1
    board9b = service.assemble_dashboard(lead9["spec_id"], "2026-04-01")
    for panel in board9b["panels"]:
        if panel["kind"] == "scenario":
            counters["scenario_hypothetical_leak"] += 1
        for figure in panel["figures"]:
            if any(b.startswith("scenario:")
                   for b in figure["badges"]):
                counters["scenario_hypothetical_leak"] += 1
            if figure["artefact_id"].startswith(
                    ("SCN-", "OPT-", "ADOPT-")):
                counters["scenario_hypothetical_leak"] += 1
    values9a = [[(f["label"], f["value"]) for f in p["figures"]]
                for p in board9["panels"]]
    values9b = [[(f["label"], f["value"]) for f in p["figures"]]
                for p in board9b["panels"]]
    if values9a != values9b:
        counters["scenario_hypothetical_leak"] += 1

    # --- Round 10: weekly brief, packs, publication gate -------
    # The brief assembles from artefacts only and verifies
    # figure by figure; a corrupted draft is refused wholesale
    # with the refusal on record; tampering anywhere is
    # caught; nothing renders as published without a named
    # act; the decision log re-derives gaplessly; packs
    # export figures that match reads, under a checksum
    # manifest that names a tampered file.
    import json as _json10
    import sqlite3 as _sqlite10

    from fertilizer_intelligence import brief as _brief10
    from fertilizer_intelligence.modelport import ModelReply as _Reply10

    counters.setdefault("brief_figure_mismatch", 0)
    counters.setdefault("brief_figures_without_lineage", 0)
    counters.setdefault("brief_refusal_missing", 0)
    counters.setdefault("brief_tamper_undetected", 0)
    counters.setdefault("publication_without_act", 0)
    counters.setdefault("decision_log_gaps", 0)
    counters.setdefault("pack_figure_mismatch", 0)
    counters.setdefault("pack_checksum_undetected", 0)

    WEEK10 = "2026-03-29"

    class _Corrupt10:
        profile_name = "corrupt"
        model_name = "corrupt-stub"

        def complete(self, system, prompt):
            return _Reply10(
                text=prompt + "\nTotal estimated demand is "
                              "999999.99 t.",
                profile=self.profile_name, model=self.model_name,
                input_tokens=0, output_tokens=0)

    try:
        service.weekly_brief(WEEK10, "evals", port=_Corrupt10())
        counters["brief_refusal_missing"] += 1  # accepted!
    except _brief10.BriefRefused as refused10:
        if refused10.refusal_id is None or \
                store.get_brief_refusal(refused10.refusal_id) is None:
            counters["brief_refusal_missing"] += 1
    if store.list_weekly_briefs():
        counters["brief_refusal_missing"] += 1  # a brief was stored

    brief10 = service.weekly_brief(WEEK10, "evals")
    refusal10 = store.list_brief_refusals(week_ending=WEEK10)
    if not refusal10 or \
            brief10["supersedes_refusal"] != refusal10[-1]["refusal_id"]:
        counters["brief_refusal_missing"] += 1
    if not service.verify_brief(brief10["brief_id"])["verified"]:
        counters["brief_figure_mismatch"] += 1

    def _artefact_exists10(artefact_id: str) -> bool:
        return any([
            store.get_outlook(artefact_id),
            store.get_alert(artefact_id),
            store.get_gap(artefact_id),
            store.get_policy_registration(artefact_id),
            store.get_share_movement(artefact_id),
            store.get_share(artefact_id),
            store.get_planning_adoption(artefact_id),
        ])

    for section10 in brief10["sections"]:
        for figure10 in section10["figures"]:
            if not figure10.get("artefact_id") \
                    or not figure10.get("source_as_of"):
                counters["brief_figures_without_lineage"] += 1
            elif not _artefact_exists10(figure10["artefact_id"]):
                counters["brief_figures_without_lineage"] += 1

    raw10 = _sqlite10.connect(settings.sqlite_path)
    row10 = raw10.execute(
        "SELECT payload FROM weekly_briefs WHERE brief_id = ?",
        (brief10["brief_id"],)).fetchone()
    saved10 = row10[0]
    payload10 = _json10.loads(saved10)
    payload10["sections"][0]["figures"][0]["value"] += 1.0
    raw10.execute(
        "UPDATE weekly_briefs SET payload = ? WHERE brief_id = ?",
        (_json10.dumps(payload10), brief10["brief_id"]))
    raw10.commit()
    if service.verify_brief(brief10["brief_id"])["verified"]:
        counters["brief_tamper_undetected"] += 1
    raw10.execute(
        "UPDATE weekly_briefs SET payload = ? WHERE brief_id = ?",
        (saved10, brief10["brief_id"]))
    raw10.commit()
    raw10.close()
    if not service.verify_brief(brief10["brief_id"])["verified"]:
        counters["brief_tamper_undetected"] += 1

    if service.publication_state(
            "weekly_brief", brief10["brief_id"])["status"] != "draft":
        counters["publication_without_act"] += 1
    try:
        service.publish_artefact(
            "weekly_brief", brief10["brief_id"], " ", WEEK10)
        counters["publication_without_act"] += 1  # accepted!
    except ValueError:
        pass
    if store.list_publication_acts():
        counters["publication_without_act"] += 1
    act10 = service.publish_artefact(
        "weekly_brief", brief10["brief_id"], "evals publisher",
        "2026-03-30")
    state10 = service.publication_state(
        "weekly_brief", brief10["brief_id"])
    if state10["status"] != "published" \
            or state10["act_id"] != act10["act_id"]:
        counters["publication_without_act"] += 1
    outlook10 = brief10["sections"][0]["artefact_ids"][0]
    service.publish_artefact(
        "season_outlook", outlook10, "evals publisher", "2026-03-30")
    log10 = service.decision_log()
    if [e["seq"] for e in log10] != [1, 2]:
        counters["decision_log_gaps"] += 1
    if not service.verify_decision_log()["verified"]:
        counters["decision_log_gaps"] += 1

    pack10 = service.export_pack("product", "DAP", "evals", WEEK10)
    if not service.verify_pack(pack10["pack_id"])["verified"]:
        counters["pack_figure_mismatch"] += 1
    files10 = _brief10.render_pack_files(pack10)
    tampered10 = dict(files10)
    data10 = bytearray(tampered10["demand.csv"])
    data10[20] = ord("9") if data10[20] != ord("9") else ord("1")
    tampered10["demand.csv"] = bytes(data10)
    problems10 = _brief10.verify_pack_files(pack10, tampered10)
    if not any("demand.csv" in p for p in problems10):
        counters["pack_checksum_undetected"] += 1
    raw10 = _sqlite10.connect(settings.sqlite_path)
    row10 = raw10.execute(
        "SELECT payload FROM export_packs WHERE pack_id = ?",
        (pack10["pack_id"],)).fetchone()
    saved10 = row10[0]
    payload10 = _json10.loads(saved10)
    payload10["tables"]["demand"][0]["total_tonnes"] += 5.0
    raw10.execute(
        "UPDATE export_packs SET payload = ? WHERE pack_id = ?",
        (_json10.dumps(payload10), pack10["pack_id"]))
    raw10.commit()
    raw10.close()
    if service.verify_pack(pack10["pack_id"])["verified"]:
        counters["pack_figure_mismatch"] += 1

    # --- Round 11: the production data plane -----------------
    # Connector loads reconcile exactly and a replay lands
    # nothing twice; a provenanceless row is refused at the
    # port; planted bad rows quarantine under the exact
    # named reasons with no fact count moving; corrections
    # fold over an unrewritten stored fact and the chain
    # verifier catches tampering; actuals land in their own
    # class, leave estimates untouched, and report their
    # unmatched rows instead of dropping them.
    import json as _json11
    import sqlite3 as _sqlite11

    counters.setdefault("ingest_replay_duplicates", 0)
    counters.setdefault("ingest_provenance_accepted", 0)
    counters.setdefault("ingest_reconciliation_errors", 0)
    counters.setdefault("quarantine_reason_mismatches", 0)
    counters.setdefault("quarantined_rows_consumed", 0)
    counters.setdefault("correction_chain_errors", 0)
    counters.setdefault("actuals_overwriting_estimates", 0)
    counters.setdefault("actuals_unmatched_unreported", 0)

    def _price11(item, month, price, **over):
        row = {"series_kind": "product", "item": item,
               "month": month, "price": price, "unit": "INR/tonne",
               "source": "intl_price_feed", "as_of": "2026-05-05"}
        row.update(over)
        return row

    good11 = [_price11("DAP", "2026-05", 27050.0),
              _price11("UREA", "2026-05", 5910.0)]
    prices_before11 = len(store.price_points())
    batch11 = service.load_connector_batch(
        "intl_price_feed", good11, "eval desk", "2026-05-06")
    if batch11["received"] != 2 or batch11["inserted"] != 2:
        counters["ingest_reconciliation_errors"] += 1
    if batch11["received"] != (batch11["inserted"]
                               + batch11["duplicates"]
                               + batch11["quarantined"]
                               + batch11["refused"]):
        counters["ingest_reconciliation_errors"] += 1
    if len(store.price_points()) != prices_before11 + 2:
        counters["ingest_reconciliation_errors"] += 1
    if not service.verify_ingest_batch(batch11["batch_id"])["verified"]:
        counters["ingest_reconciliation_errors"] += 1
    replay11 = service.load_connector_batch(
        "intl_price_feed", good11, "eval desk", "2026-05-06")
    if replay11["batch_id"] != batch11["batch_id"]:
        counters["ingest_replay_duplicates"] += 1
    replay11b = service.load_connector_batch(
        "intl_price_feed", good11, "eval desk", "2026-05-07")
    if replay11b["inserted"] != 0 or replay11b["duplicates"] != 2:
        counters["ingest_replay_duplicates"] += 1
    if len(store.price_points()) != prices_before11 + 2:
        counters["ingest_replay_duplicates"] += 1

    noprov11 = {"series_kind": "product", "item": "MOP",
                "month": "2026-05", "price": 24100.0,
                "unit": "INR/tonne", "source": "intl_price_feed"}
    refused11 = service.load_connector_batch(
        "intl_price_feed", [noprov11], "eval desk", "2026-05-06")
    if refused11["refused"] != 1 or refused11["inserted"] != 0:
        counters["ingest_provenance_accepted"] += 1
    if any(p["item"] == "MOP" and p["month"] == "2026-05"
           for p in store.price_points()):
        counters["ingest_provenance_accepted"] += 1
    if store.provenance_gaps() != 0:
        counters["ingest_provenance_accepted"] += 1

    counts_before11 = store.fact_counts()
    dirty11 = [
        _price11("DAP", "2026-05", 99999.0, as_of="2026-05-06"),
        _price11("POTASH_X", "2026-05", 1200.0, as_of="2026-05-06"),
        _price11("MOP", "2026-05", -10.0, as_of="2026-05-06"),
        _price11("MOP", "2026-06", 24100.0, source="rival_feed",
                 as_of="2026-05-06"),
        _price11("MOP", "2026-07", 24100.0, as_of="2026-04-20"),
    ]
    dirty_batch11 = service.load_connector_batch(
        "intl_price_feed", dirty11, "eval desk", "2026-05-07")
    expected_reasons11 = sorted([
        "conflicts_with_stored", "unknown_product",
        "non_positive_price", "source_mismatch",
        "stale_beyond_freshness"])
    got_reasons11 = sorted(
        h["reason"] for h in dirty_batch11["quarantine"])
    if got_reasons11 != expected_reasons11:
        counters["quarantine_reason_mismatches"] += 1
    if dirty_batch11["inserted"] != 0:
        counters["quarantined_rows_consumed"] += 1
    if store.fact_counts() != counts_before11:
        counters["quarantined_rows_consumed"] += 1

    key11 = {"series_kind": "product", "item": "DAP",
             "month": "2026-05"}
    row11 = dict(key11, price=27125.5, unit="INR/tonne",
                 source="intl_price_feed", as_of="2026-05-08")
    corr11 = service.submit_correction(
        "price_points", row11, None, "eval desk")
    row11b = dict(row11, price=27130.0, as_of="2026-05-09")
    service.submit_correction(
        "price_points", row11b, corr11["correction_id"], "eval desk")
    chain11 = service.verify_correction_chain("price_points", key11)
    if not chain11["verified"]:
        counters["correction_chain_errors"] += 1
    if service.effective_fact("price_points", key11)["price"] != 27130.0:
        counters["correction_chain_errors"] += 1
    stored11 = next(p for p in store.price_points("product", "DAP")
                    if p["month"] == "2026-05")
    if stored11["price"] != 27050.0:
        counters["correction_chain_errors"] += 1
    raw11 = _sqlite11.connect(settings.sqlite_path)
    prow11 = raw11.execute(
        "SELECT payload FROM fact_corrections "
        "WHERE correction_id = ?",
        (corr11["correction_id"],)).fetchone()
    payload11 = _json11.loads(prow11[0])
    payload11["row"]["price"] = 1.0
    raw11.execute(
        "UPDATE fact_corrections SET payload = ? "
        "WHERE correction_id = ?",
        (_json11.dumps(payload11), corr11["correction_id"]))
    raw11.commit()
    raw11.close()
    if service.verify_correction_chain("price_points", key11)["verified"]:
        counters["correction_chain_errors"] += 1

    service.estimate_demand("DST-GUN", "UREA", "2025-26", "rabi",
                            "2026-04-15")
    estimates_before11 = {
        e["estimate_id"]: e["fact_fingerprint"]
        for e in store.list_estimates()}

    def _actual11(district, product, kind, qty):
        return {"district_id": district, "crop_year": "2025-26",
                "season": "rabi", "product": product,
                "actual_kind": kind, "quantity_tonnes": qty,
                "source": "state_dispatch_returns",
                "as_of": "2026-04-15"}

    actuals11 = [_actual11("DST-GUN", "UREA", "consumption", 45210.5),
                 _actual11("DST-GUN", "MOP", "dispatch", 12340.0)]
    abatch11 = service.load_connector_batch(
        "state_dispatch_returns", actuals11, "eval desk", "2026-04-20")
    if abatch11["inserted"] != 2:
        counters["actuals_overwriting_estimates"] += 1
    if {e["estimate_id"]: e["fact_fingerprint"]
            for e in store.list_estimates()} != estimates_before11:
        counters["actuals_overwriting_estimates"] += 1
    if store.fact_counts()["season_actuals"] != 2:
        counters["actuals_overwriting_estimates"] += 1
    report11 = service.actuals_report("2025-26", "rabi")
    if report11["actual_count"] != 2:
        counters["actuals_overwriting_estimates"] += 1
    # Independent join: the head-estimate key set for the
    # season, derived here from the estimate rows alone.
    season_estimates11 = store.list_estimates(
        crop_year="2025-26", season="rabi")
    superseded11 = {e["supersedes"] for e in season_estimates11
                    if e.get("supersedes")}
    head_keys11 = {(e["district_id"], e["product"])
                   for e in season_estimates11
                   if e["estimate_id"] not in superseded11}
    for row in report11["rows"]:
        should_match = (row["district_id"], row["product"]) in head_keys11
        if row["matched_estimate"] != should_match:
            counters["actuals_unmatched_unreported"] += 1
        if not should_match:
            label11 = (f"{row['district_id']}/{row['crop_year']}/"
                       f"{row['season']}/{row['product']}/"
                       f"{row['actual_kind']}")
            if label11 not in report11["unmatched"]:
                counters["actuals_unmatched_unreported"] += 1
    if ("DST-GUN", "UREA") not in head_keys11:
        counters["actuals_unmatched_unreported"] += 1

    # --- Round 12: season-close scoring ----------------------
    # The season R11 closed is graded: the UREA cell
    # re-performs from the artefacts, the unmatched MOP
    # actual and a freshly struck DAP estimate are named
    # on the run, a hand-computed fixture's attribution
    # matches the pack method exactly, and a tampered
    # payload is caught. Then the depth grading: the
    # spike alert's full lifecycle folds from its acts
    # with invalid transitions refused, and the delay's
    # gap path is re-performed month by month.
    import json as _json12
    import sqlite3 as _sqlite12

    from fertilizer_intelligence import models as _models12
    from fertilizer_intelligence.movements import (
        AlertStateError as _AlertStateError12)

    counters.setdefault("score_reperformance_errors", 0)
    counters.setdefault("score_attribution_errors", 0)
    counters.setdefault("score_unmatched_unreported", 0)
    counters.setdefault("spike_lifecycle_errors", 0)
    counters.setdefault("delay_gap_path_errors", 0)

    service.estimate_demand("DST-GUN", "DAP", "2025-26", "rabi",
                            "2026-04-15")
    run12 = service.score_season("2025-26", "rabi", "eval desk",
                                 "2026-04-25")
    if not service.verify_score_run(run12["score_id"])["verified"]:
        counters["score_reperformance_errors"] += 1
    # The join, derived independently here from the estimate
    # and actual rows alone — the same discipline as the
    # Round 11 actuals grading.
    season_estimates12 = store.list_estimates(
        crop_year="2025-26", season="rabi")
    superseded12 = {e["supersedes"] for e in season_estimates12
                    if e.get("supersedes")}
    head_keys12 = {(e["district_id"], e["product"])
                   for e in season_estimates12
                   if e["estimate_id"] not in superseded12}
    actuals12 = store.season_actuals(crop_year="2025-26",
                                     season="rabi")
    matched12 = [a for a in actuals12
                 if (a["district_id"], a["product"]) in head_keys12]
    if run12["scored_count"] != len(matched12):
        counters["score_reperformance_errors"] += 1
    expected_unmatched12 = sorted(
        f"{a['district_id']}/{a['crop_year']}/{a['season']}/"
        f"{a['product']}/{a['actual_kind']}"
        for a in actuals12
        if (a["district_id"], a["product"]) not in head_keys12)
    if run12["unmatched_actuals"] != expected_unmatched12:
        counters["score_unmatched_unreported"] += 1
    actual_keys12 = {(a["district_id"], a["product"])
                     for a in actuals12}
    expected_no_actual12 = sorted(
        f"{d}/2025-26/rabi/{p}"
        for (d, p) in head_keys12 if (d, p) not in actual_keys12)
    if [u["label"] for u in run12["unmatched_estimates"]] \
            != expected_no_actual12:
        counters["score_unmatched_unreported"] += 1
    if "DST-GUN/2025-26/rabi/DAP" not in expected_no_actual12:
        counters["score_unmatched_unreported"] += 1
    cell12 = next(
        (c for c in run12["cells"]
         if c["district_id"] == "DST-GUN"
         and c["product"] == "UREA"
         and c["actual_kind"] == "consumption"), None)
    if cell12 is None:
        counters["score_reperformance_errors"] += 1
    else:
        estimate12 = store.get_estimate(cell12["estimate_id"])
        if cell12["error_tonnes"] != round(
                45210.5 - estimate12["total_tonnes"], 3):
            counters["score_reperformance_errors"] += 1
        attributed12 = sum(
            l["attributed_error_tonnes"] for l in cell12["lines"])
        if abs(attributed12 - cell12["error_tonnes"]) > 0.01:
            counters["score_reperformance_errors"] += 1
        worst12 = max(cell12["lines"],
                      key=lambda l: abs(l["attributed_error_tonnes"]))
        if worst12["driver"] != cell12["most_wrong_driver"] \
                or worst12["line_no"] != cell12["most_wrong_line_no"]:
            counters["score_reperformance_errors"] += 1
    if run12["actual_batches"] != [abatch11["batch_id"]]:
        counters["score_reperformance_errors"] += 1

    # The hand-computed fixture, planted as stored artefacts:
    # base 300, soil +400, monsoon 0, price -200, carry-in 0
    # (total 500) against an actual of 750 — error +250,
    # attributed base +150 / soil +200 / price -100, the
    # soil line most wrong. Any other answer is a failure
    # of the pack method, not a rounding difference.
    fixture_lines12 = []
    _value12 = 0.0
    for _no12, (_driver12, _status12, _delta12) in enumerate([
            ("base_area_rates", "applied", 300.0),
            ("soil_nutrient_status", "applied", 400.0),
            ("monsoon_deviation", "applied", 0.0),
            ("price_elasticity", "applied", -200.0),
            ("carry_in_stock", "missing", 0.0)]):
        _value12 = round(_value12 + _delta12, 3)
        fixture_lines12.append({
            "line_no": _no12, "driver": _driver12,
            "status": _status12, "factor": 1.0,
            "delta_tonnes": _delta12,
            "value_after_tonnes": _value12, "inputs": {}})
    store.insert_estimate({
        "estimate_id": "EST-EVAL12", "district_id": "DST-EVAL",
        "product": "UREA", "crop_year": "2025-26",
        "season": "kharif", "status": "complete",
        "base_tonnes": 300.0, "total_tonnes": 500.0,
        "missing_drivers": ["carry_in_stock"],
        "rules_version": "2026.10.1",
        "rate_table_version": "2026.10.1",
        "fact_fingerprint": "eval-fixture-12",
        "as_of": "2025-06-15", "supersedes": None,
    }, fixture_lines12)
    store.insert_season_actuals([_models12.SeasonActual(
        district_id="DST-EVAL", crop_year="2025-26",
        season="kharif", product="UREA",
        actual_kind="consumption", quantity_tonnes=750.0,
        source="state_dispatch_returns", as_of="2025-11-15")])
    fixture_run12 = service.score_season(
        "2025-26", "kharif", "eval desk", "2025-11-20")
    fcell12 = fixture_run12["cells"][0] \
        if fixture_run12["scored_count"] == 1 else None
    if fcell12 is None:
        counters["score_attribution_errors"] += 1
    else:
        fattr12 = {l["driver"]: l["attributed_error_tonnes"]
                   for l in fcell12["lines"]}
        if fcell12["error_tonnes"] != 250.0 \
                or fcell12["error_pct"] != 33.3333 \
                or fattr12 != {
                    "base_area_rates": 150.0,
                    "soil_nutrient_status": 200.0,
                    "monsoon_deviation": 0.0,
                    "price_elasticity": -100.0,
                    "carry_in_stock": 0.0} \
                or fcell12["most_wrong_driver"] \
                != "soil_nutrient_status" \
                or fcell12["most_wrong_line_no"] != 1:
            counters["score_attribution_errors"] += 1

    raw12 = _sqlite12.connect(settings.sqlite_path)
    prow12 = raw12.execute(
        "SELECT payload FROM estimate_scores WHERE score_id = ?",
        (run12["score_id"],)).fetchone()
    payload12 = _json12.loads(prow12[0])
    payload12["cells"][0]["error_tonnes"] += 5.0
    raw12.execute(
        "UPDATE estimate_scores SET payload = ? WHERE score_id = ?",
        (_json12.dumps(payload12), run12["score_id"]))
    raw12.commit()
    raw12.close()
    if service.verify_score_run(run12["score_id"])["verified"]:
        counters["score_reperformance_errors"] += 1

    # The spike alert's lifecycle, folded from its acts
    # alone: the Round 3 pass acknowledged and closed it,
    # and every further act must be refused and record
    # nothing. A second alert walks the full path here.
    def _fold12(acts):
        state = "open"
        for act in acts:
            if act["act"] == "acknowledge":
                state = "acknowledged"
            elif act["act"] == "close":
                state = "closed"
        return state

    spike12 = next(a for a in service.list_alerts()
                   if a["rule_id"] == "spike")
    acts12 = store.list_alert_acts(spike12["alert_id"])
    if _fold12(acts12) != spike12["state"] \
            or spike12["state"] != "closed":
        counters["spike_lifecycle_errors"] += 1
    for attempt12 in (
            lambda: service.acknowledge_alert(
                spike12["alert_id"], "eval desk", "too late",
                "2026-04-01"),
            lambda: service.close_alert(
                spike12["alert_id"], "eval desk",
                "explained_by_event", "2026-04-01"),
            lambda: service.acknowledge_alert(
                "ALR-missing", "eval desk", "nobody", "2026-04-01")):
        try:
            attempt12()
            counters["spike_lifecycle_errors"] += 1  # accepted!
        except (_AlertStateError12, ValueError):
            pass
    if len(store.list_alert_acts(spike12["alert_id"])) != len(acts12):
        counters["spike_lifecycle_errors"] += 1

    watch12 = next(a for a in service.list_alerts()
                   if a["state"] == "open")
    watch_acts12 = len(store.list_alert_acts(watch12["alert_id"]))
    try:
        service.close_alert(watch12["alert_id"], "eval desk",
                            "not_a_reason", "2026-04-01")
        counters["spike_lifecycle_errors"] += 1  # accepted!
    except ValueError:
        pass
    if len(store.list_alert_acts(watch12["alert_id"])) \
            != watch_acts12:
        counters["spike_lifecycle_errors"] += 1
    acked12 = service.acknowledge_alert(
        watch12["alert_id"], "eval desk",
        "Eval pass: walking the lifecycle.", "2026-04-01")
    if acked12["state"] != "acknowledged" \
            or _fold12(store.list_alert_acts(
                watch12["alert_id"])) != "acknowledged":
        counters["spike_lifecycle_errors"] += 1
    closed12 = service.close_alert(
        watch12["alert_id"], "eval desk", "explained_by_event",
        "2026-04-02")
    if closed12["state"] != "closed" \
            or _fold12(store.list_alert_acts(
                watch12["alert_id"])) != "closed":
        counters["spike_lifecycle_errors"] += 1

    # The delay's gap path across the whole programme:
    # short while the vessel is slipped, comfortable from
    # the month it lands, each month re-performed and
    # superseding the last.
    path12 = []
    for as_of12 in ("2025-10-31", "2025-11-30", "2025-12-31",
                    "2026-01-31", "2026-02-28", "2026-03-31"):
        path12.append(service.supply_gap(
            "DAP", "2025-26", "kharif", as_of12))
        if service.verify_gap("DAP", "2025-26", "kharif"):
            counters["delay_gap_path_errors"] += 1
    if [g["band"] for g in path12] != [
            "short", "short", "comfortable", "comfortable",
            "comfortable", "comfortable"]:
        counters["delay_gap_path_errors"] += 1
    if [g["slipped_tonnes"] for g in path12] != [
            55000.0, 55000.0, 0.0, 0.0, 0.0, 0.0]:
        counters["delay_gap_path_errors"] += 1
    if [g["programme_cover_pct"] for g in path12] != [
            52.5862, 52.5862, 100.0, 100.0, 100.0, 100.0]:
        counters["delay_gap_path_errors"] += 1
    # The stored chain is one unbroken line: walking the
    # supersedes links back from the head visits every
    # stored gap exactly once — no forks, no orphans, no
    # cycles — and the chain is exactly the six programme
    # months of the path. (The head is whichever gap was
    # struck last across the whole grading flow; the
    # path property is the unbroken line, not the order
    # earlier rounds happened to strike in.)
    stored12 = store.list_gaps("DAP", "2025-26", "kharif")
    head12 = service.get_gap("DAP", "2025-26", "kharif")
    walked12 = []
    cursor12 = head12
    while cursor12 is not None:
        walked12.append(cursor12["gap_id"])
        cursor12 = store.get_gap(cursor12["supersedes"]) \
            if cursor12["supersedes"] else None
    if sorted(walked12) != sorted(
            g["gap_id"] for g in stored12) \
            or sorted(walked12) != sorted(
                g["gap_id"] for g in path12):
        counters["delay_gap_path_errors"] += 1

    print("Round 1+2+3+4+5+6+7+8+9+10+11+12 evals — fertilizer market intelligence")
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
