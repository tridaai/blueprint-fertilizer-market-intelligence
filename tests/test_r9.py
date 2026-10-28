"""Round 9 — scenario forks & planning options.

A scenario is a pinned fork of a head artefact: bounded
levers from a versioned catalogue, run through the SAME
engines as the base, reconciling exactly. Planning
options compare a base and its forks under stated ranking
criteria only, and adoption is a named planner's
insert-only act. Forks are hypothetical by construction —
the heads, the board, the policy notes and the dashboards
of record are byte-identical before and after fork work.
"""

import json
import sqlite3

import pytest

from fertilizer_intelligence import scenario as scenario_engine

EST_AS_OF = "2026-03-31"
PROJ_AS_OF = "2025-09-30"
DEMAND_SCOPE = {"district_id": "DST-LUD", "product": "DAP",
                "crop_year": "2025-26", "season": "kharif"}
PROJ_SCOPE = {"product": "DAP", "crop_year": "2025-26",
              "season": "rabi"}


def _base_estimate(service):
    return service.estimate_demand(
        "DST-LUD", "DAP", "2025-26", "kharif", EST_AS_OF)


def _base_projection(service):
    return service.supply_projection("DAP", "2025-26", "rabi", PROJ_AS_OF)


def _monsoon_fork(service, shift=-20, name="Monsoon shortfall"):
    _base_estimate(service)
    return service.create_scenario(
        "demand_estimate", DEMAND_SCOPE,
        [{"lever": "monsoon_deviation_shift", "value": shift}],
        "tests", name=name)


def _slip_fork(service, months=2, name="October vessel slips"):
    _base_projection(service)
    return service.create_scenario(
        "supply_projection", PROJ_SCOPE,
        [{"lever": "import_arrival_shift_months", "value": months,
          "shipment_id": "IMP-DAP-2510"}],
        "tests", name=name)


# -- forks through the same engines -----------------------------------


def test_monsoon_fork_reconciles_line_by_line(service):
    base = _base_estimate(service)
    fork = _monsoon_fork(service)
    assert fork["base_artefact_id"] == base["estimate_id"]
    assert fork["hypothetical"] is True
    assert fork["base_total_tonnes"] == 14091.569
    assert fork["fork_total_tonnes"] == 13133.889
    assert fork["delta_tonnes"] == -957.68
    lever_sum = round(sum(r["lever_delta_tonnes"]
                          for r in fork["reconciliation"]), 3)
    assert lever_sum == fork["delta_tonnes"]
    by_driver = {r["driver"]: r for r in fork["reconciliation"]}
    # The monsoon line carries the lever; the price and
    # carry-in lines moved as knock-ons of the changed
    # running total and are attributed to NO lever.
    assert by_driver["monsoon_deviation"]["attributed_levers"] == [
        "monsoon_deviation_shift"]
    assert by_driver["price_elasticity"]["lever_delta_tonnes"] != 0
    assert by_driver["price_elasticity"]["attributed_levers"] == []
    assert by_driver["carry_in_stock"]["attributed_levers"] == []
    assert service.verify_scenario(fork["fork_id"])["verified"]


def test_fork_creation_is_idempotent(service):
    first = _monsoon_fork(service)
    second = _monsoon_fork(service)
    assert first["fork_id"] == second["fork_id"]
    assert len(service.list_scenarios()) == 1


def test_slip_fork_reproduces_the_planted_delay_path(service):
    _base_projection(service)
    fork = _slip_fork(service)
    months = {r["month"]: r for r in fork["reconciliation"]}
    # The planted delay's own path: nothing in October or
    # November, the full 55,000 t landing in December.
    assert months["2025-10"]["fork_imports_tonnes"] == 0
    assert months["2025-11"]["fork_imports_tonnes"] == 0
    assert months["2025-12"]["fork_imports_tonnes"] == 55000
    assert months["2025-10"]["closing_delta_tonnes"] == -55000
    assert months["2025-12"]["closing_delta_tonnes"] == 0
    # The tonnage all arrives, just later: the horizon-end
    # delta is zero and says so.
    assert fork["delta_tonnes"] == 0
    assert service.verify_scenario(fork["fork_id"])["verified"]


def test_elasticity_override_rides_the_price_lines_own_inputs(service):
    _base_estimate(service)
    fork = service.create_scenario(
        "demand_estimate", DEMAND_SCOPE,
        [{"lever": "price_elasticity_override", "value": -0.10}],
        "tests")
    price_line = next(
        line for line in fork["result"]["contributions"]
        if line["driver"] == "price_elasticity")
    assert price_line["inputs"]["elasticity"] == -0.10
    assert price_line["inputs"]["elasticity_base"] == -0.30
    assert price_line["inputs"]["elasticity_source"] == "scenario_lever"
    assert price_line["factor"] == pytest.approx(0.991138, abs=1e-6)
    assert service.verify_scenario(fork["fork_id"])["verified"]


def test_price_shift_moves_only_the_current_window(service):
    base = _base_estimate(service)
    base_line = next(
        line for line in
        service.store.estimate_contributions(base["estimate_id"])
        if line["driver"] == "price_elasticity")
    fork = service.create_scenario(
        "demand_estimate", DEMAND_SCOPE,
        [{"lever": "price_level_shift_pct", "value": 10}],
        "tests")
    fork_line = next(
        line for line in fork["result"]["contributions"]
        if line["driver"] == "price_elasticity")
    for before, after in zip(base_line["inputs"]["current_points"],
                             fork_line["inputs"]["current_points"]):
        # Points are recorded as [month, price] pairs.
        assert after[0] == before[0]
        assert after[1] == round(before[1] * 1.1, 2)
    assert fork_line["inputs"]["prior_points"] == \
        base_line["inputs"]["prior_points"]
    assert service.verify_scenario(fork["fork_id"])["verified"]


def test_production_shortfall_scales_the_plan_only(service):
    _base_projection(service)
    fork = service.create_scenario(
        "supply_projection", PROJ_SCOPE,
        [{"lever": "production_shortfall_pct", "value": 25}],
        "tests")
    months = {r["month"]: r for r in fork["reconciliation"]}
    assert months["2025-10"]["production_delta_tonnes"] == -95000
    assert months["2026-01"]["production_delta_tonnes"] == -106400
    assert fork["delta_tonnes"] == -581400
    # The basis position and the actuals never move.
    assert fork["result"]["opening_tonnes"] == 6676784.451
    assert service.verify_scenario(fork["fork_id"])["verified"]


def test_lever_on_a_missing_driver_line_is_stated_not_applied(service):
    base = service.estimate_demand(
        "DST-IND", "MOP", "2024-25", "kharif", EST_AS_OF)
    assert "price_elasticity" in base["missing_drivers"]
    fork = service.create_scenario(
        "demand_estimate",
        {"district_id": "DST-IND", "product": "MOP",
         "crop_year": "2024-25", "season": "kharif"},
        [{"lever": "price_elasticity_override", "value": -0.3}],
        "tests")
    record = fork["levers"][0]
    assert record["applied"] is False
    assert "price line" in record["reason"]
    assert fork["delta_tonnes"] == 0
    assert service.verify_scenario(fork["fork_id"])["verified"]


# -- the catalogue's bounds -------------------------------------------


def test_out_of_bounds_levers_are_refused_naming_the_bound(service):
    _base_estimate(service)
    with pytest.raises(ValueError) as exc:
        service.create_scenario(
            "demand_estimate", DEMAND_SCOPE,
            [{"lever": "monsoon_deviation_shift", "value": -31}],
            "tests")
    assert "[-30, 30]" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        service.create_scenario(
            "demand_estimate", DEMAND_SCOPE,
            [{"lever": "price_elasticity_override", "value": 0.1}],
            "tests")
    assert "[-1, 0]" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        service.create_scenario(
            "demand_estimate", DEMAND_SCOPE,
            [{"lever": "monsoon_deviation_shift", "value": 0}],
            "tests")
    assert "moves nothing" in str(exc.value)


def test_wrong_kind_and_unknown_levers_are_refused(service):
    _base_projection(service)
    with pytest.raises(ValueError) as exc:
        service.create_scenario(
            "supply_projection", PROJ_SCOPE,
            [{"lever": "monsoon_deviation_shift", "value": -10}],
            "tests")
    assert "demand_estimate" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        service.create_scenario(
            "supply_projection", PROJ_SCOPE,
            [{"lever": "policy_event_apply", "value": 1}],
            "tests")
    assert "a numeric transmission" in str(exc.value)


def test_import_shift_refusals(service):
    _base_projection(service)
    with pytest.raises(ValueError) as exc:
        service.create_scenario(
            "supply_projection", PROJ_SCOPE,
            [{"lever": "import_arrival_shift_months", "value": 2.5,
              "shipment_id": "IMP-DAP-2510"}], "tests")
    assert "whole" in str(exc.value)
    # A shipment that already arrived is not scheduled in
    # the base and cannot be re-timed by a fork.
    with pytest.raises(ValueError) as exc:
        service.create_scenario(
            "supply_projection", PROJ_SCOPE,
            [{"lever": "import_arrival_shift_months", "value": 1,
              "shipment_id": "IMP-DAP-2507"}], "tests")
    assert "not scheduled" in str(exc.value)
    # Advancing the October vessel into the basis month
    # would rewrite the basis stock — refused.
    with pytest.raises(ValueError) as exc:
        service.create_scenario(
            "supply_projection", PROJ_SCOPE,
            [{"lever": "import_arrival_shift_months", "value": -1,
              "shipment_id": "IMP-DAP-2510"}], "tests")
    assert "basis" in str(exc.value)


# -- plain-language intake ---------------------------------------------


def test_grammar_monsoon_ask_matches_the_structured_fork(service):
    _base_estimate(service)
    asked = service.ask_scenario(
        "what if the monsoon comes in 20 points lower for dap "
        "in ludhiana, kharif 2025-26", "tests")
    assert asked["delta_tonnes"] == -957.68
    assert asked["gaps"] == []
    assert asked["parse"]["profile"] == "offline"


def test_grammar_import_ask_slips_the_named_vessel(service):
    _base_projection(service)
    asked = service.ask_scenario(
        "what if IMP-DAP-2510 slips by 2 months for dap supply, "
        "rabi 2025-26", "tests")
    months = {r["month"]: r for r in asked["reconciliation"]}
    assert months["2025-12"]["fork_imports_tonnes"] == 55000
    assert service.verify_scenario(asked["fork_id"])["verified"]


def test_grammar_policy_part_becomes_a_named_gap(service):
    _base_estimate(service)
    asked = service.ask_scenario(
        "what if the monsoon comes in 20 points lower for dap "
        "in ludhiana, kharif 2025-26, and the export "
        "restriction is lifted", "tests")
    assert asked["delta_tonnes"] == -957.68
    assert any("no numeric transmission" in g["needed"]
               for g in asked["gaps"])


def test_grammar_unmappable_part_becomes_a_named_gap(service):
    _base_estimate(service)
    asked = service.ask_scenario(
        "what if the monsoon comes in 20 points lower for dap "
        "in ludhiana, kharif 2025-26; if the railways strike",
        "tests")
    assert any(g["rule"] == "grammar:gap_unmapped_segment"
               for g in asked["gaps"])


def test_grammar_refusals(service):
    _base_estimate(service)
    with pytest.raises(ValueError) as exc:
        service.ask_scenario(
            "what if the monsoon comes in 45 points lower for "
            "dap in ludhiana, kharif 2025-26", "tests")
    assert "30" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        service.ask_scenario(
            "what if the monsoon comes in 20 points lower for "
            "dap in Anantapur, kharif 2025-26", "tests")
    assert "not one of the tracked districts" in str(exc.value)


def test_model_proposal_path_is_governed(service):
    base = _base_estimate(service)
    from types import SimpleNamespace

    class StubPort:
        profile = "anthropic"
        model = "tests-stub"

        def __init__(self, payload):
            self.payload = payload

        def complete(self, prompt, system=None):
            return SimpleNamespace(text=json.dumps(self.payload))

    good = StubPort({
        "kind": "demand_estimate", "scope": DEMAND_SCOPE,
        "levers": [{"lever": "monsoon_deviation_shift", "value": -20},
                   {"lever": "teleport_the_monsoon", "value": 3}]})
    kind, scope, records, gaps, parse = \
        scenario_engine.parse_scenario_model(
            service.store, good, "monsoon scenario", base)
    assert [r["lever"] for r in records] == ["monsoon_deviation_shift"]
    assert any("teleport_the_monsoon" in g["needed"] for g in gaps)

    bad = StubPort({"kind": "guess", "scope": {}, "levers": []})
    with pytest.raises(ValueError):
        scenario_engine.parse_scenario_model(
            service.store, bad, "guess", base)


# -- planning options & adoption ---------------------------------------


def test_demand_options_rank_by_the_pack_criteria_only(service):
    base = _base_estimate(service)
    down = _monsoon_fork(service, shift=-20, name="Monsoon shortfall")
    up = _monsoon_fork(service, shift=10, name="Monsoon surplus")
    options = service.build_planning_options(
        base["estimate_id"], [down["fork_id"], up["fork_id"]],
        "tests")
    ranks = {row["artefact_id"]: row["rank"] for row in options["rows"]}
    # Stated criterion: total demand, descending — the
    # surplus fork first, the base next, the shortfall last.
    assert ranks[up["fork_id"]] == 1
    assert ranks[base["estimate_id"]] == 2
    assert ranks[down["fork_id"]] == 3
    for row in options["rows"]:
        for figure in row["figures"]:
            assert figure["artefact_id"] == row["artefact_id"]
    assert service.verify_planning_options(
        options["options_id"])["verified"]


def test_projection_options_carry_gap_readings(service):
    base = _base_projection(service)
    slip = _slip_fork(service)
    options = service.build_planning_options(
        base["projection_id"], [slip["fork_id"]], "tests")
    for row in options["rows"]:
        assert row["gap_reading"]["band"] == "comfortable"
        labels = [f["label"] for f in row["figures"]]
        assert "Gap band (gap machinery over this view)" in labels
    assert service.verify_planning_options(
        options["options_id"])["verified"]


def test_options_refuse_foreign_and_empty_fork_sets(service):
    base = _base_estimate(service)
    other_base = service.estimate_demand(
        "DST-GUN", "DAP", "2025-26", "kharif", EST_AS_OF)
    foreign = service.create_scenario(
        "demand_estimate",
        {"district_id": "DST-GUN", "product": "DAP",
         "crop_year": "2025-26", "season": "kharif"},
        [{"lever": "monsoon_deviation_shift", "value": -10}],
        "tests")
    with pytest.raises(ValueError):
        service.build_planning_options(
            base["estimate_id"], [foreign["fork_id"]], "tests")
    with pytest.raises(ValueError):
        service.build_planning_options(base["estimate_id"], [], "tests")
    assert other_base["estimate_id"] != base["estimate_id"]


def test_adoption_is_a_named_insert_only_act(service):
    base = _base_projection(service)
    slip = _slip_fork(service)
    options = service.build_planning_options(
        base["projection_id"], [slip["fork_id"]], "tests")
    with pytest.raises(ValueError):
        service.adopt_option(options["options_id"], slip["fork_id"],
                             "  ", "2026-04-15")
    with pytest.raises(ValueError):
        service.adopt_option(options["options_id"], "SCN-0000000000",
                             "A. Planner", "2026-04-15")
    first = service.adopt_option(
        options["options_id"], slip["fork_id"], "A. Planner",
        "2026-04-15")
    assert first["supersedes"] is None
    second = service.adopt_option(
        options["options_id"], None, "A. Planner", "2026-04-20",
        note="the vessel landed — back to the base view")
    assert second["supersedes"] == first["adoption_id"]
    assert service.current_adoption(
        options["options_id"])["adoption_id"] == second["adoption_id"]
    assert len(service.list_adoptions(options["options_id"])) == 2
    assert service.verify_adoption(first["adoption_id"])["verified"]
    assert service.verify_adoption(second["adoption_id"])["verified"]
    # Adoption edited nothing: the base and the fork read
    # back exactly as built.
    assert service.get_scenario(slip["fork_id"]) == slip
    assert service.store.get_projection(
        base["projection_id"])["closing_tonnes"] == 8905455.248


def test_tampered_artefacts_are_caught_by_their_verifiers(service,
                                                         settings):
    base = _base_projection(service)
    slip = _slip_fork(service)
    options = service.build_planning_options(
        base["projection_id"], [slip["fork_id"]], "tests")
    raw = sqlite3.connect(settings.sqlite_path)

    payload = json.loads(raw.execute(
        "SELECT payload FROM scenario_forks WHERE fork_id = ?",
        (slip["fork_id"],)).fetchone()[0])
    payload["delta_tonnes"] = 12345.0
    raw.execute("UPDATE scenario_forks SET payload = ? WHERE fork_id = ?",
                (json.dumps(payload), slip["fork_id"]))
    raw.commit()
    assert not service.verify_scenario(slip["fork_id"])["verified"]
    payload["delta_tonnes"] = 0.0
    raw.execute("UPDATE scenario_forks SET payload = ? WHERE fork_id = ?",
                (json.dumps(payload), slip["fork_id"]))
    raw.commit()
    assert service.verify_scenario(slip["fork_id"])["verified"]

    payload = json.loads(raw.execute(
        "SELECT payload FROM planning_options WHERE options_id = ?",
        (options["options_id"],)).fetchone()[0])
    payload["rows"][0]["figures"][1]["value"] += 500
    raw.execute(
        "UPDATE planning_options SET payload = ? WHERE options_id = ?",
        (json.dumps(payload), options["options_id"]))
    raw.commit()
    raw.close()
    assert not service.verify_planning_options(
        options["options_id"])["verified"]


# -- hypothetical discipline -------------------------------------------


def _head_snapshot(service):
    store = service.store
    estimates = store.list_estimates()
    return {
        "estimates": estimates,
        "contributions": {
            e["estimate_id"]: store.estimate_contributions(
                e["estimate_id"]) for e in estimates},
        "projections": store.list_projections(),
        "gap": service.supply_gap("DAP", "2025-26", "kharif",
                                   "2025-10-31"),
        "board": service.watch_board(),
        "registrations": service.list_policy_events(
            hypothetical=False),
    }


def test_fork_work_leaves_every_head_byte_identical(service):
    _base_estimate(service)
    _base_projection(service)
    service.register_policy_events("2026-03-31")
    registrations = service.list_policy_events(hypothetical=False)
    note_before = service.policy_impact(
        registrations[0]["registry_id"], "2026-03-31")
    # Every head the fork machinery could touch is struck
    # BEFORE the snapshot — outlooks included — so nothing
    # in the fork work below strikes a new head artefact.
    service.demand_outlook("2025-26", "kharif", EST_AS_OF)
    service.demand_outlook("2025-26", "rabi", PROJ_AS_OF)
    leadership = service.role_default_dashboard(
        "leadership", "tests", EST_AS_OF)
    board_before = service.assemble_dashboard(
        leadership["spec_id"], EST_AS_OF)
    before = _head_snapshot(service)

    down = _monsoon_fork(service)
    slip = _slip_fork(service)
    demand_options = service.build_planning_options(
        down["base_artefact_id"], [down["fork_id"]], "tests")
    supply_options = service.build_planning_options(
        slip["base_artefact_id"], [slip["fork_id"]], "tests")
    service.adopt_option(supply_options["options_id"],
                         slip["fork_id"], "A. Planner", "2026-04-15")
    service.ask_question("show me the monsoon shortfall scenario",
                         "tests", EST_AS_OF)

    after = _head_snapshot(service)
    assert json.dumps(after, sort_keys=True, default=str) == \
        json.dumps(before, sort_keys=True, default=str)
    note_after = service.policy_impact(
        registrations[0]["registry_id"], "2026-03-31")
    assert note_after == note_before
    board_after = service.assemble_dashboard(
        leadership["spec_id"], "2026-04-01")
    values_before = [[(f["label"], f["value"]) for f in p["figures"]]
                     for p in board_before["panels"]]
    values_after = [[(f["label"], f["value"]) for f in p["figures"]]
                    for p in board_after["panels"]]
    assert values_after == values_before
    assert demand_options["options_id"].startswith("OPT-")


def test_no_scenario_artefact_enters_a_head_listing(service):
    _monsoon_fork(service)
    _slip_fork(service)
    for estimate in service.store.list_estimates():
        assert not estimate["estimate_id"].startswith(("SCN-", "OPT-"))
    for projection in service.store.list_projections():
        assert not projection["projection_id"].startswith(("SCN-", "OPT-"))


# -- dashboards: named only, badged always ------------------------------


def test_dashboard_renders_a_named_scenario_badged(service):
    _monsoon_fork(service)
    spec = service.ask_question(
        "show me the monsoon shortfall scenario", "tests", EST_AS_OF)
    assert [p["kind"] for p in spec["panels"]] == ["scenario"]
    assembly = service.assemble_dashboard(spec["spec_id"], EST_AS_OF)
    panel = assembly["panels"][0]
    assert panel["figures"]
    for figure in panel["figures"]:
        assert any(b.startswith("scenario:")
                   for b in figure["badges"])
    assert service.verify_dashboard(assembly["assembly_id"])["verified"]


def test_dashboard_of_record_carries_no_scenario(service):
    _monsoon_fork(service)
    spec = service.role_default_dashboard("leadership", "tests",
                                          EST_AS_OF)
    assembly = service.assemble_dashboard(spec["spec_id"], EST_AS_OF)
    for panel in assembly["panels"]:
        assert panel["kind"] != "scenario"
        for figure in panel["figures"]:
            assert not any(b.startswith("scenario:")
                           for b in figure["badges"])


def test_unnamed_scenario_request_becomes_a_gap(service):
    _monsoon_fork(service)
    spec = service.ask_question(
        "show me a scenario for dap", "tests", EST_AS_OF)
    assert spec["panels"][0]["kind"] == "gap"
    assert "names a stored fork" in \
        spec["panels"][0]["scope"]["needed_data"]


def test_unbadged_scenario_figure_fails_verification(service, settings):
    _monsoon_fork(service)
    spec = service.ask_question(
        "show me the monsoon shortfall scenario", "tests", EST_AS_OF)
    assembly = service.assemble_dashboard(spec["spec_id"], EST_AS_OF)
    raw = sqlite3.connect(settings.sqlite_path)
    payload = json.loads(raw.execute(
        "SELECT payload FROM dashboard_assemblies "
        "WHERE assembly_id = ?", (assembly["assembly_id"],)).fetchone()[0])
    payload["panels"][0]["figures"][0]["badges"] = []
    raw.execute(
        "UPDATE dashboard_assemblies SET payload = ? "
        "WHERE assembly_id = ?",
        (json.dumps(payload), assembly["assembly_id"]))
    raw.commit()
    raw.close()
    assert not service.verify_dashboard(
        assembly["assembly_id"])["verified"]
