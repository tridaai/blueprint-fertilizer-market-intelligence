"""Round 5: the policy & subsidy event registry — the six
recorded events registered under the pack (class, window,
stated effect), impact notes naming exactly the in-scope
artefacts for two hand-derived events, the hypothetical
separation (no note, no marker, listed apart, never flipped in
place), supersession, the no-observed-scope statement, board
markers that are never alert counts, tamper detection, and
API/CLI parity.

The hand-derived scopes below were worked out from the pack's
stated window rule and the demand pack's season calendar before
the registry was run: an event's demand cells are the districts
x the seasons whose six-month window overlaps the event window,
for the products it scopes to.
"""

import json
import sqlite3

import pytest

AS_OF = "2026-04-15"

# event_id -> (registry class, window, direction, driver)
EXPECTED_REGISTRATIONS = {
    "POL-2024-001": ("subsidy_rate_change", "2024-04", "2024-11", "up", "price"),
    "POL-2024-002": ("price_control", "2024-06", "2024-11", "none", "price"),
    "POL-2025-001": ("production_incentive", "2025-02", "2025-04", "up", "demand_rate"),
    "POL-2025-002": ("subsidy_rate_change", "2025-08", "2025-11", "none", "price"),
    "POL-2025-003": ("export_restriction", "2025-09", "2025-11", "down", "supply"),
    "POL-2026-001": ("subsidy_rate_change", "2026-01", "2026-04", "none", "price"),
}

HYP_SPEC = {
    "event_id": "POL-2026-HYP-001",
    "event_class": "import_duty_change",
    "title": "Proposed import duty revision on DAP (desk scenario)",
    "detail": "A duty revision under discussion.",
    "effective_from_month": "2025-09", "effective_to_month": "2025-11",
    "products": ["DAP"], "districts": [],
    "direction": "down",
    "mechanism": "A lower duty would move the landed cost of DAP arrivals down.",
    "source": "desk_scenario_register",
    "registered_by": "strategy.desk@kaveri.example",
}


from rawdb import raw_connect


def registered(service):
    service.register_policy_events(AS_OF)
    return {e["event_id"]: e for e in service.list_policy_events()}


def test_planted_events_register_under_the_pack(service):
    summary = service.register_policy_events(AS_OF)
    assert summary == {
        "as_of": AS_OF, "registered": 6, "already_registered": 0,
        "events_total": 6,
    }
    events = {e["event_id"]: e for e in service.list_policy_events()}
    assert set(events) == set(EXPECTED_REGISTRATIONS)
    facts = {f["event_id"]: f for f in service.store.policy_events()}
    for event_id, (klass, from_m, to_m, direction, driver) in \
            EXPECTED_REGISTRATIONS.items():
        event = events[event_id]
        fact = facts[event_id]
        assert event["event_class"] == klass
        assert event["fact_kind"] == fact["kind"]
        assert event["fact_event_id"] == event_id
        assert event["effective_from_month"] == from_m
        assert event["effective_to_month"] == to_m
        assert event["products"] == fact["impacted_products"]
        assert event["districts"] == []  # recorded market-wide
        assert event["hypothetical"] is False
        assert event["source"] == fact["source"]
        assert event["recorded_on"] == fact["as_of"]
        assert event["registered_by"] == "dataset"
        effect = event["stated_effect"]
        assert effect["direction"] == direction
        assert effect["driver"] == driver
        # The mechanism is the fact's recorded impact text,
        # carried verbatim — never rewritten commentary.
        assert effect["mechanism"] == fact["expected_impact"]
        assert service.verify_policy_event(event["registry_id"]) == []
    # The linkage names the engine surface each class touches.
    linkages = {e["event_class"]: e["stated_effect"]["linkage"]
                for e in events.values()}
    assert linkages["subsidy_rate_change"] == {
        "engine": "demand", "parameter": "price_elasticity"}
    assert linkages["price_control"] == {
        "engine": "price_watch", "target": "product_price_series"}
    assert linkages["export_restriction"] == {
        "engine": "supply", "line": "import_arrivals"}
    assert linkages["production_incentive"] == {
        "engine": "demand", "parameter": "application_rates"}
    # A second pass stores nothing.
    assert service.register_policy_events(AS_OF)["registered"] == 0
    assert len(service.store.list_policy_registrations()) == 6


def test_impact_note_names_exactly_the_restriction_scope(service):
    events = registered(service)
    event = events["POL-2025-003"]
    note = service.policy_impact(event["registry_id"], AS_OF)
    assert note["status"] == "computed"
    # Demand: DAP in the two seasons whose windows overlap
    # 2025-09..2025-11 (kharif 2025-26 and rabi 2025-26),
    # all twelve districts — and nothing else.
    cells = {(c["district_id"], c["crop_year"], c["season"])
             for c in note["demand_cells"]}
    districts = {d["district_id"] for d in service.store.list_districts()}
    assert cells == {
        (d, y, s) for d in districts
        for (y, s) in (("2025-26", "kharif"), ("2025-26", "rabi"))
    }
    assert len(note["demand_estimate_ids"]) == 24
    assert all(c["product"] == "DAP" for c in note["demand_cells"])
    # Prices: the DAP product series and the phosphoric-acid
    # feedstock series, three window months each.
    series = {(s["series_kind"], s["item"]): s["months"]
              for s in note["price_series"]}
    assert series == {
        ("product", "DAP"): ["2025-09", "2025-10", "2025-11"],
        ("feedstock", "PHOSPHORIC_ACID"): ["2025-09", "2025-10", "2025-11"],
    }
    # Positions: the DAP heads for the three window months.
    assert [(p["product"], p["month"]) for p in note["positions"]] == [
        ("DAP", "2025-09"), ("DAP", "2025-10"), ("DAP", "2025-11")]
    assert note["position_ids"] == [
        service.get_position("DAP", m)["position_id"]
        for m in ("2025-09", "2025-10", "2025-11")
    ]
    assert service.verify_policy_impact(event["registry_id"]) == []
    # Compute-or-return: a second call stores nothing new.
    assert service.policy_impact(event["registry_id"], AS_OF)["note_id"] \
        == note["note_id"]
    assert len(service.store.list_policy_impact_notes()) == 1


def test_impact_note_names_exactly_the_mrp_scope(service):
    events = registered(service)
    event = events["POL-2024-002"]
    note = service.policy_impact(event["registry_id"], AS_OF)
    assert note["status"] == "computed"
    # Window 2024-06..2024-11 overlaps kharif 2024-25 and (at
    # November) rabi 2024-25: UREA cells for both, 12 districts.
    cells = {(c["district_id"], c["crop_year"], c["season"])
             for c in note["demand_cells"]}
    districts = {d["district_id"] for d in service.store.list_districts()}
    assert cells == {
        (d, y, s) for d in districts
        for (y, s) in (("2024-25", "kharif"), ("2024-25", "rabi"))
    }
    assert all(c["product"] == "UREA" for c in note["demand_cells"])
    series = {(s["series_kind"], s["item"]): s["months"]
              for s in note["price_series"]}
    assert series == {
        ("product", "UREA"): ["2024-06", "2024-07", "2024-08",
                              "2024-09", "2024-10", "2024-11"],
    }
    assert [p["month"] for p in note["positions"]] == [
        "2024-06", "2024-07", "2024-08", "2024-09", "2024-10", "2024-11"]
    assert service.verify_policy_impact(event["registry_id"]) == []


def test_district_scoped_event_names_only_its_districts(service):
    registered(service)
    event = service.register_policy_event({
        **HYP_SPEC,
        "event_id": "POL-2026-DST-001",
        "event_class": "environmental_rule",
        "title": "Application timing rule in two districts",
        "detail": "A stated rule scoping two districts.",
        "products": ["GLYPHOSATE"],
        "districts": ["DST-GUN", "DST-NAG"],
        "direction": "down",
        "mechanism": "Application windows narrow in the named districts.",
        "hypothetical": False,
    }, AS_OF)
    note = service.policy_impact(event["registry_id"], AS_OF)
    districts = {c["district_id"] for c in note["demand_cells"]}
    assert districts == {"DST-GUN", "DST-NAG"}
    # Glyphosate has no supply side: no positions are named.
    assert note["position_ids"] == []
    assert note["status"] == "computed"
    assert service.verify_policy_impact(event["registry_id"]) == []


def test_hypothetical_separation(service):
    registered(service)
    proposal = service.register_policy_event(
        {**HYP_SPEC, "hypothetical": True}, AS_OF)
    assert proposal["hypothetical"] is True
    # Listed separately, either way the filter is pointed.
    assert [e["event_id"] for e in
            service.list_policy_events(hypothetical=True)] == ["POL-2026-HYP-001"]
    assert "POL-2026-HYP-001" not in [
        e["event_id"] for e in service.list_policy_events(hypothetical=False)]
    # No impact note: asking is refused and none is stored.
    with pytest.raises(ValueError, match="hypothetical"):
        service.policy_impact(proposal["registry_id"], AS_OF)
    assert service.store.list_policy_impact_notes(proposal["registry_id"]) == []
    assert service.get_policy_impact(proposal["registry_id"]) is None
    # And it marks nothing on the board.
    service.run_price_watch(AS_OF)
    for row in service.watch_board():
        assert "POL-2026-HYP-001" not in [
            m["event_id"] for m in row["policy_markers"]]


def test_hypothetical_becomes_real_only_by_supersession(service):
    registered(service)
    proposal = service.register_policy_event(
        {**HYP_SPEC, "hypothetical": True}, AS_OF)
    snapshot = service.get_policy_event(proposal["registry_id"])
    enacted = service.register_policy_event({
        **HYP_SPEC,
        "title": "Import duty revision on DAP (registered as enacted)",
        "detail": "The duty revision is now on record as a real event.",
        "mechanism": "A lower duty moves the landed cost of DAP arrivals down.",
        "hypothetical": False,
    }, "2026-04-16")
    assert enacted["registry_id"] != proposal["registry_id"]
    assert enacted["supersedes"] == proposal["registry_id"]
    assert enacted["hypothetical"] is False
    # The proposal artefact is byte-identical: the flag was not
    # flipped in place, because there is no update path.
    assert service.get_policy_event(proposal["registry_id"]) == snapshot
    assert service.get_policy_event(proposal["registry_id"])["hypothetical"] is True
    versions = service.policy_event_versions("POL-2026-HYP-001")
    assert [v["registry_id"] for v in versions] == [
        proposal["registry_id"], enacted["registry_id"]]
    head = service.list_policy_events(hypothetical=False)
    assert enacted["registry_id"] in [e["registry_id"] for e in head]
    # As a real event it now earns its note — the DAP scope of
    # 2025-09..2025-11, like the restriction's.
    note = service.policy_impact(enacted["registry_id"], "2026-04-16")
    assert note["status"] == "computed"
    assert len(note["demand_estimate_ids"]) == 24
    assert [(p["product"], p["month"]) for p in note["positions"]] == [
        ("DAP", "2025-09"), ("DAP", "2025-10"), ("DAP", "2025-11")]
    assert service.verify_policy_event(enacted["registry_id"]) == []
    assert service.verify_policy_impact(enacted["registry_id"]) == []
    # Registering the same content again is a no-op.
    repeat = service.register_policy_event({
        **HYP_SPEC,
        "title": "Import duty revision on DAP (registered as enacted)",
        "detail": "The duty revision is now on record as a real event.",
        "mechanism": "A lower duty moves the landed cost of DAP arrivals down.",
        "hypothetical": False,
    }, "2026-04-17")
    assert repeat["registry_id"] == enacted["registry_id"]
    assert len(service.policy_event_versions("POL-2026-HYP-001")) == 2


def test_no_observed_scope_is_stated_not_hidden(service):
    registered(service)
    event = service.register_policy_event({
        **HYP_SPEC,
        "event_id": "POL-2026-FUT-001",
        "event_class": "environmental_rule",
        "title": "Application rule announced for a future season",
        "detail": "A rule whose window sits beyond the tracked data.",
        "effective_from_month": "2026-05", "effective_to_month": "2026-06",
        "products": ["CHLORPYRIFOS"],
        "direction": "down",
        "mechanism": "Application of the active is restricted from May 2026.",
        "hypothetical": False,
    }, AS_OF)
    note = service.policy_impact(event["registry_id"], AS_OF)
    assert note["status"] == "no_observed_scope"
    assert note["demand_estimate_ids"] == []
    assert note["price_series"] == []
    assert note["position_ids"] == []
    assert service.verify_policy_impact(event["registry_id"]) == []


def test_board_markers_exact_and_never_alert_counts(service):
    registered(service)
    service.run_price_watch(AS_OF)
    alerts_before = len(service.list_alerts())
    board = {row["item"]: row for row in service.watch_board()}
    # Reference month 2026-03 (the latest tracked price month):
    # only the rabi subsidy revision's window (2026-01..2026-04)
    # is open, on the two series it scopes to.
    for item, row in board.items():
        expected = ["POL-2026-001"] if item in ("DAP", "NPK_10_26_26") else []
        assert [m["event_id"] for m in row["policy_markers"]] == expected, item
        assert row["policy_marker_count"] == len(expected)
    marker = board["DAP"]["policy_markers"][0]
    assert marker["event_class"] == "subsidy_rate_change"
    assert marker["effective_from_month"] == "2026-01"
    # Markers are not alerts: counts are untouched by them.
    total_open = sum(row["open_alert_count"] for row in board.values())
    assert total_open == len(
        [a for a in service.list_alerts() if a["state"] != "closed"])
    assert len(service.list_alerts()) == alerts_before == 18
    watch = service.series_watch("product", "DAP")
    assert [m["event_id"] for m in watch["policy_markers"]] == ["POL-2026-001"]


def test_desk_registration_validation(service):
    base = {**HYP_SPEC, "hypothetical": False}
    with pytest.raises(ValueError, match="unknown policy event class"):
        service.register_policy_event({**base, "event_class": "tax"}, AS_OF)
    with pytest.raises(ValueError, match="disagrees with the stated driver"):
        service.register_policy_event({**base, "driver": "price"}, AS_OF)
    with pytest.raises(ValueError, match="direction must be one of"):
        service.register_policy_event({**base, "direction": "sideways"}, AS_OF)
    with pytest.raises(ValueError, match="unknown scope products"):
        service.register_policy_event({**base, "products": ["NPK_19_19_19"]}, AS_OF)
    with pytest.raises(ValueError, match="unknown districts"):
        service.register_policy_event({**base, "districts": ["DST-XXX"]}, AS_OF)
    with pytest.raises(ValueError, match="closes before it opens"):
        service.register_policy_event({
            **base, "effective_from_month": "2025-11",
            "effective_to_month": "2025-09"}, AS_OF)
    with pytest.raises(ValueError, match="needs a stated registered_by"):
        service.register_policy_event({**base, "registered_by": " "}, AS_OF)
    # None of the refused registrations stored anything.
    assert service.store.list_policy_registrations() == []


def test_registration_tamper_is_detected(service, settings):
    events = registered(service)
    event = events["POL-2025-003"]
    assert service.verify_policy_event(event["registry_id"]) == []
    db = raw_connect(settings)
    payload = json.loads(
        db.execute(
            "SELECT payload FROM policy_registry_events WHERE registry_id = ?",
            (event["registry_id"],),
        ).fetchone()[0]
    )
    payload["stated_effect"]["direction"] = "up"
    db.execute(
        "UPDATE policy_registry_events SET payload = ? WHERE registry_id = ?",
        (json.dumps(payload), event["registry_id"]),
    )
    db.commit()
    problems = service.verify_policy_event(event["registry_id"])
    assert problems, "a tampered stated effect must fail verification"
    db.close()


def test_impact_note_tamper_is_detected(service, settings):
    events = registered(service)
    event = events["POL-2025-003"]
    note = service.policy_impact(event["registry_id"], AS_OF)
    assert service.verify_policy_impact(event["registry_id"]) == []
    db = raw_connect(settings)
    payload = json.loads(
        db.execute(
            "SELECT payload FROM policy_impact_notes WHERE note_id = ?",
            (note["note_id"],),
        ).fetchone()[0]
    )
    payload["position_ids"] = payload["position_ids"][:-1]
    payload["positions"] = payload["positions"][:-1]
    db.execute(
        "UPDATE policy_impact_notes SET payload = ? WHERE note_id = ?",
        (json.dumps(payload), note["note_id"]),
    )
    db.commit()
    assert service.verify_policy_impact(event["registry_id"])
    db.close()


def test_api_parity_round5(service, settings):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        summary = client.post(
            "/policy-registry/register-facts", json={"as_of": AS_OF}).json()
        assert summary["registered"] == 6 and summary["events_total"] == 6
        events = client.get("/policy-registry/events").json()
        assert len(events) == 6
        by_id = {e["event_id"]: e for e in events}
        restriction = by_id["POL-2025-003"]
        assert restriction["event_class"] == "export_restriction"
        got = client.get(
            f"/policy-registry/events/{restriction['registry_id']}").json()
        assert got["registry_id"] == restriction["registry_id"]
        verify = client.get(
            f"/policy-registry/events/{restriction['registry_id']}/verify").json()
        assert verify["ok"] is True and verify["problems"] == []

        note = client.post(
            f"/policy-registry/events/{restriction['registry_id']}/impact",
            json={"as_of": AS_OF}).json()
        assert note["status"] == "computed"
        assert len(note["demand_estimate_ids"]) == 24
        fetched = client.get(
            f"/policy-registry/events/{restriction['registry_id']}/impact").json()
        assert fetched["note_id"] == note["note_id"]
        note_verify = client.get(
            f"/policy-registry/events/{restriction['registry_id']}/impact/verify"
        ).json()
        assert note_verify["ok"] is True

        proposal = client.post("/policy-registry/events", json={
            **HYP_SPEC, "hypothetical": True, "as_of": AS_OF,
        }).json()
        assert proposal["hypothetical"] is True
        refused = client.post(
            f"/policy-registry/events/{proposal['registry_id']}/impact",
            json={"as_of": AS_OF})
        assert refused.status_code == 422
        assert client.get(
            "/policy-registry/events", params={"hypothetical": True}).json()[0][
                "event_id"] == "POL-2026-HYP-001"
        assert client.get(
            "/policy-registry/events",
            params={"event_class": "subsidy_rate_change"}).json().__len__() == 3
        bad = client.post("/policy-registry/events", json={
            **HYP_SPEC, "event_id": "POL-BAD", "event_class": "tax",
            "as_of": AS_OF,
        })
        assert bad.status_code == 422
        assert client.get("/policy-registry/events/POLREG-nope").status_code == 404

        board = client.get("/watch").json()
        dap = next(r for r in board if r["item"] == "DAP")
        assert [m["event_id"] for m in dap["policy_markers"]] == ["POL-2026-001"]
        assert dap["policy_marker_count"] == 1


def test_cli_parity_round5(service, settings, capsys):
    from fertilizer_intelligence import cli

    base = [
        "--db", str(settings.sqlite_path),
        "--migrations", str(settings.migrations_dir),
    ]
    assert cli.main(base + ["policy-register", "--as-of", AS_OF]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["registered"] == 6

    assert cli.main(base + ["policy-events", "--actual"]) == 0
    events = json.loads(capsys.readouterr().out)
    assert len(events) == 6
    restriction = next(e for e in events if e["event_id"] == "POL-2025-003")

    assert cli.main(base + ["policy", "--registry-id", restriction["registry_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["event_class"] == "export_restriction"

    assert cli.main(base + [
        "policy-impact", "--registry-id", restriction["registry_id"],
        "--as-of", AS_OF,
    ]) == 0
    note = json.loads(capsys.readouterr().out)
    assert note["status"] == "computed" and len(note["demand_estimate_ids"]) == 24

    assert cli.main(base + [
        "verify-policy-impact", "--registry-id", restriction["registry_id"],
    ]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert cli.main(base + [
        "policy-event", "--event-id", "POL-2026-HYP-001",
        "--event-class", "import_duty_change",
        "--title", "Proposed import duty revision on DAP (desk scenario)",
        "--detail", "A duty revision under discussion.",
        "--from-month", "2025-09", "--to-month", "2025-11",
        "--products", "DAP", "--direction", "down",
        "--mechanism", "A lower duty would move the landed cost of DAP arrivals down.",
        "--hypothetical", "--source", "desk_scenario_register",
        "--registered-by", "strategy.desk@kaveri.example", "--as-of", AS_OF,
    ]) == 0
    proposal = json.loads(capsys.readouterr().out)
    assert proposal["hypothetical"] is True

    assert cli.main(base + ["policy-events", "--hypothetical"]) == 0
    proposals = json.loads(capsys.readouterr().out)
    assert [e["event_id"] for e in proposals] == ["POL-2026-HYP-001"]

    assert cli.main(base + [
        "policy-impact", "--registry-id", proposal["registry_id"],
        "--as-of", AS_OF,
    ]) == 2
    capsys.readouterr()

    assert cli.main(base + ["verify-policy", "--registry-id", "POLREG-nope"]) == 2
    capsys.readouterr()
