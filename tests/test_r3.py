"""Round 3: the price & feedstock watch — hand-derived firing
truth, idempotent firing, the spike event window, alert
verification and tamper detection, the act-driven state machine,
and the watch views on both surfaces."""

import sqlite3

import pytest

from fertilizer_intelligence import movements as movement_engine
from fertilizer_intelligence.movements import AlertStateError

AS_OF = "2026-04-15"

# The whole alert set over the planted series, derived by hand
# from the stored prices and the pack's stated thresholds:
# DAP's September 2025 spike (+37.04% MoM) and its unwind, the
# post-shock baseline dislocation, and seven sustained drifts.
# Every other series stays inside the pack's quiet bands.
EXPECTED_ALERTS = {
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

QUIET_SERIES = [
    ("feedstock", "NATURAL_GAS"),
    ("feedstock", "PHOSPHORIC_ACID"),
    ("feedstock", "SULPHUR"),
    ("product", "CHLORPYRIFOS"),
]


@pytest.fixture()
def watched(service):
    service.run_price_watch(AS_OF)
    return service


def test_movement_computation_hand_checked(service):
    """DAP, September 2025: the movement is the stored September
    price against the stored August price, and against the mean
    of the six preceding months — recomputed here from the raw
    price facts, not from the engine."""
    store = service.store
    prices = {p["month"]: p["price"] for p in store.price_points("product", "DAP")}
    movements = {
        m.month: m.model_dump()
        for m in movement_engine.compute_movements(store, "product", "DAP", AS_OF)
    }
    sep = movements["2025-09"]
    expected_mom = round((prices["2025-09"] - prices["2025-08"]) / prices["2025-08"] * 100, 4)
    assert sep["mom_pct"] == expected_mom and sep["mom_pct"] > 37.0
    trailing = [prices[m] for m in ("2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08")]
    expected_base = round((prices["2025-09"] - sum(trailing) / 6) / (sum(trailing) / 6) * 100, 4)
    assert sep["baseline_pct"] == expected_base
    assert sep["baseline_months"] == ["2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08"]
    # The first month of the series states no movement; the second
    # and third state no baseline (fewer than three trailing).
    assert "2024-04" not in movements
    assert movements["2024-05"]["baseline_pct"] is None
    assert movements["2024-06"]["baseline_pct"] is None
    assert movements["2024-07"]["baseline_pct"] is not None


def test_firing_pass_is_idempotent(watched):
    summary = watched.run_price_watch(AS_OF)
    assert summary["movements_stored"] == 0 and summary["alerts_fired"] == 0
    assert summary["movements_total"] == 230  # 10 series x 23 months
    assert summary["alerts_total"] == len(EXPECTED_ALERTS)


def test_alert_set_matches_hand_derived_truth(watched):
    got = {
        (a["series_kind"], a["item"], a["rule_id"], a["period_month"], a["band"])
        for a in watched.list_alerts()
    }
    assert got == EXPECTED_ALERTS


def test_planted_spike_fires_once_at_alert_band(watched, service):
    spikes = service.list_alerts("product", "DAP", "spike")
    assert len(spikes) == 1
    spike = spikes[0]
    assert spike["period_month"] == "2025-09" and spike["band"] == "alert"
    # The spike figure is the planted move: the stored September
    # price is the manifest's planted price, 38% over trend.
    manifest_spike = service.manifest["planted"]["price_spike"]
    assert spike["figures"]["mom_pct"] > manifest_spike["magnitude_pct"] - 1.0
    # The unwind months fire no second spike: October and November
    # are the same event, inside the pack's event window.
    periods = {a["period_month"] for a in service.list_alerts("product", "DAP", "spike")}
    assert "2025-10" not in periods and "2025-11" not in periods


def test_spike_event_window_suppresses_synthetic_repeat():
    """The event window is load-bearing, not decorative: fed a
    synthetic series of four consecutive spike-sized months, the
    spike rule fires on the first and the fourth only — the two
    inside the window are the same event unwinding."""
    def mov(month, mom):
        return {
            "movement_id": f"MOV-x-{month}", "series_kind": "product",
            "item": "X", "month": month, "mom_pct": mom,
            "baseline_pct": None, "baseline_mean": None,
        }
    movements = [
        mov("2025-01", 25.0), mov("2025-02", 30.0), mov("2025-03", 28.0),
        mov("2025-04", 26.0), mov("2025-05", 1.0),
    ]
    fired = movement_engine.evaluate_movements(movements)
    spike_periods = [p["period_month"] for p in fired if p["rule_id"] == "spike"]
    assert spike_periods == ["2025-01", "2025-04"]


def test_quiet_series_fire_nothing(watched):
    for series_kind, item in QUIET_SERIES:
        assert watched.list_alerts(series_kind, item) == []
        watch = watched.series_watch(series_kind, item)
        assert watch["band"] == "none" and watch["open_alerts"] == []


def test_every_alert_carries_its_movements_and_verifies(watched):
    for alert in watched.list_alerts():
        assert alert["movement_ids"], "an alert without its triggering movement"
        for movement_id in alert["movement_ids"]:
            assert watched.store.get_movement(movement_id) is not None
        assert watched.verify_alert(alert["alert_id"]) == []
    for movement in watched.store.list_movements():
        assert watched.verify_movement(movement["movement_id"]) == []


def test_alert_without_movement_fails_verification(watched, settings):
    """A hand-forged alert row naming a movement that does not
    exist is caught by the verifier — alerts are only real when
    their triggering movements are."""
    raw = sqlite3.connect(settings.sqlite_path)
    raw.execute(
        "INSERT INTO price_alerts (alert_id, series_kind, item, rule_id, band, "
        "period_month, movement_ids, figures, rules_version, as_of) VALUES "
        "('ALR-forged', 'product', 'DAP', 'spike', 'alert', '2025-09', "
        "'[\"MOV-does-not-exist\"]', '{\"mom_pct\": 99.0}', '2026.10.1', '2026-04-15')"
    )
    raw.commit()
    raw.close()
    problems = watched.verify_alert("ALR-forged")
    assert any("not in the store" in p for p in problems)


def test_tampered_movement_and_alert_are_detected(watched, settings):
    movement = next(
        m for m in watched.store.list_movements("product", "DAP") if m["month"] == "2025-09"
    )
    alert = watched.list_alerts("product", "DAP", "spike")[0]
    raw = sqlite3.connect(settings.sqlite_path)
    raw.execute(
        "UPDATE price_movements SET mom_pct = 3.0 WHERE movement_id = ?",
        (movement["movement_id"],),
    )
    raw.commit()
    assert watched.verify_movement(movement["movement_id"]) != []
    assert watched.verify_alert(alert["alert_id"]) != []
    raw.execute(
        "UPDATE price_movements SET mom_pct = ? WHERE movement_id = ?",
        (movement["mom_pct"], movement["movement_id"]),
    )
    raw.execute(
        "UPDATE price_alerts SET band = 'watch' WHERE alert_id = ?",
        (alert["alert_id"],),
    )
    raw.commit()
    raw.close()
    assert watched.verify_movement(movement["movement_id"]) == []
    assert watched.verify_alert(alert["alert_id"]) != []


def test_alert_state_machine_via_acts_only(watched):
    alert = watched.list_alerts("product", "DAP", "spike")[0]
    alert_id = alert["alert_id"]
    assert alert["state"] == "open" and alert["acts"] == []
    raw_before = watched.store.get_alert(alert_id)

    acked = watched.acknowledge_alert(
        alert_id, actor="desk.lead@kaveri.example",
        note="Traced to the September import-parity jump.", as_of=AS_OF,
    )
    assert acked["state"] == "acknowledged"
    # The alert artefact itself is byte-identical: only an act was added.
    assert watched.store.get_alert(alert_id) == raw_before

    with pytest.raises(AlertStateError):
        watched.acknowledge_alert(alert_id, actor="a@kaveri.example", note="again", as_of=AS_OF)

    closed = watched.close_alert(
        alert_id, actor="desk.lead@kaveri.example",
        closing_reason="explained_by_event", as_of="2026-04-16",
    )
    assert closed["state"] == "closed"
    assert [a["act"] for a in closed["acts"]] == ["acknowledge", "close"]
    assert closed["acts"][1]["closing_reason"] == "explained_by_event"

    with pytest.raises(AlertStateError):
        watched.close_alert(alert_id, actor="a@kaveri.example",
                            closing_reason="passed_no_action", as_of=AS_OF)
    with pytest.raises(AlertStateError):
        watched.acknowledge_alert(alert_id, actor="a@kaveri.example", note="late", as_of=AS_OF)


def test_act_validation(watched):
    alert = watched.list_alerts("product", "DAP", "spike")[0]
    alert_id = alert["alert_id"]
    with pytest.raises(ValueError):
        watched.acknowledge_alert(alert_id, actor="  ", note="hi", as_of=AS_OF)
    with pytest.raises(ValueError):
        watched.acknowledge_alert(alert_id, actor="a@kaveri.example", note=" ", as_of=AS_OF)
    with pytest.raises(ValueError):
        watched.close_alert(alert_id, actor="a@kaveri.example",
                            closing_reason="whatever", as_of=AS_OF)
    with pytest.raises(AlertStateError):
        watched.acknowledge_alert("ALR-missing", actor="a@kaveri.example",
                                  note="hi", as_of=AS_OF)
    # Closing straight from open is a legal transition.
    closed = watched.close_alert(alert_id, actor="a@kaveri.example",
                                 closing_reason="passed_no_action", as_of=AS_OF)
    assert closed["state"] == "closed"


def test_watch_views(watched):
    dap = watched.series_watch("product", "DAP")
    assert dap["band"] == "alert" and len(dap["open_alerts"]) == 11
    assert dap["latest_movement"]["month"] == "2026-03"
    board = watched.watch_board()
    assert board[0]["item"] == "DAP" and board[0]["band"] == "alert"
    assert {r["item"] for r in board if r["band"] == "none"} == {
        "NATURAL_GAS", "PHOSPHORIC_ACID", "SULPHUR", "CHLORPYRIFOS",
    }
    # Closing every DAP alert takes the series off the board's top:
    # the band is derived from open alerts, not stored anywhere.
    for alert in list(dap["open_alerts"]):
        watched.close_alert(alert["alert_id"], actor="a@kaveri.example",
                            closing_reason="passed_no_action", as_of=AS_OF)
    assert watched.series_watch("product", "DAP")["band"] == "none"


def test_api_r3_surface(settings, watched):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        summary = client.post("/watch/run", json={"as_of": AS_OF}).json()
        assert summary["alerts_fired"] == 0 and summary["alerts_total"] == 18
        alerts = client.get("/alerts", params={"item": "DAP", "rule_id": "spike"}).json()
        assert len(alerts) == 1 and alerts[0]["state"] == "open"
        alert_id = alerts[0]["alert_id"]
        verify = client.get(f"/alerts/{alert_id}/verify").json()
        assert verify["ok"] is True
        acked = client.post(
            f"/alerts/{alert_id}/acknowledge",
            json={"actor": "desk.lead@kaveri.example", "note": "Seen.", "as_of": AS_OF},
        )
        assert acked.status_code == 200 and acked.json()["state"] == "acknowledged"
        again = client.post(
            f"/alerts/{alert_id}/acknowledge",
            json={"actor": "desk.lead@kaveri.example", "note": "Again.", "as_of": AS_OF},
        )
        assert again.status_code == 409
        bad_close = client.post(
            f"/alerts/{alert_id}/close",
            json={"actor": "desk.lead@kaveri.example", "closing_reason": "meh",
                  "as_of": AS_OF},
        )
        assert bad_close.status_code == 422
        closed = client.post(
            f"/alerts/{alert_id}/close",
            json={"actor": "desk.lead@kaveri.example",
                  "closing_reason": "explained_by_event", "as_of": AS_OF},
        )
        assert closed.status_code == 200 and closed.json()["state"] == "closed"
        board = client.get("/watch").json()
        assert board[0]["item"] == "DAP"
        series = client.get("/watch/product/DAP").json()
        assert series["latest_movement"]["month"] == "2026-03"
        assert client.get("/watch/product/NOPE").status_code == 404
        movements = client.get("/movements", params={"item": "DAP"}).json()
        assert len(movements) == 23
        open_alerts = client.get("/alerts", params={"state": "open"}).json()
        assert all(a["state"] == "open" for a in open_alerts)
        assert len(open_alerts) == 17  # the spike alert is closed now
