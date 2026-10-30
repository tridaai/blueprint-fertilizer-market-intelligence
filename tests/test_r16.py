"""Round 16: alert subscriptions & escalation, scheduled
digests — subscriptions as artefacts judged by the R15
access pack before they exist (a subscriber striking
outside their remit is refused at the door and the
refusal is in the log; only the subscriber or the
strategy desk strikes), deliveries derived from
notices × the subscription version in force when the
notice was struck × the register's remit (a fixture-
exact filter set; remit confines even a subscription
that asks for everything; policy notices are their
own class and never counted as price alerts),
escalation as a clock over the alert acts (levels at
the pack's windows, the ladder resolved from the
register, an acknowledgement stopping the clock,
follow-ups named by reference), scoped alert reads
with existence hiding, and digests that freeze a
subscription's derived set and supersede by link on
regeneration.
"""

from __future__ import annotations

import json

import pytest

from fertilizer_intelligence import notify as notify_engine
from fertilizer_intelligence import queue as queue_engine
from fertilizer_intelligence.notify import SubscriptionRefused

from rawdb import raw_connect

WATCH = "2026-01-05"
READ = "2026-04-24"


def _watch(service):
    return service.run_price_watch(WATCH)


def _insert_alert(store, alert_id, item, band, as_of,
                  kind="product"):
    store.insert_alert({
        "alert_id": alert_id, "series_kind": kind,
        "item": item, "rule_id": "mom_move", "band": band,
        "period_month": "2026-02", "movement_ids": [],
        "figures": {"mom_pct": 15.0},
        "rules_version": "2026.10.1", "as_of": as_of,
    })
    return store.get_alert(alert_id)


def _insert_gap(store, gap_id, product, band, as_of="2026-03-01"):
    store.insert_supply_gap({
        "gap_id": gap_id, "product": product,
        "crop_year": "2025-26", "season": "kharif",
        "as_of": as_of, "as_of_month": "2026-03",
        "demand_tonnes": 10000.0, "demand_outlook_id": "OUT-FIX",
        "opening_stock_tonnes": 0.0,
        "production_actual_tonnes": 0.0, "arrivals_tonnes": 0.0,
        "scheduled_imports_tonnes": 0.0, "due_imports_tonnes": 0.0,
        "credited_imports_tonnes": 0.0, "slipped_tonnes": 0.0,
        "programme_cover_pct": 80.0,
        "available_tonnes": 9600.0, "gap_tonnes": -400.0,
        "gap_pct_of_demand": -4.0, "band": band,
        "band_basis": "import_programme_cover",
        "position_months": [], "uncovered_months": [],
        "rules_version": "2026.10.1",
        "fact_fingerprint": f"fixture-{gap_id}",
        "supersedes": None,
    })
    return store.get_gap(gap_id)


def _insert_policy(store, registry_id, event_id, products,
                   districts, recorded_on, hypothetical=False):
    store.insert_policy_registration({
        "registry_id": registry_id, "event_id": event_id,
        "fact_event_id": None, "event_class": "subsidy",
        "fact_kind": None, "title": f"Fixture {event_id}",
        "detail": "fixture event",
        "effective_from_month": "2026-01",
        "effective_to_month": "2026-12",
        "products": products, "districts": districts,
        "stated_effect": {"direction": "up", "driver": "price",
                          "mechanism": "fixture", "linkage": {}},
        "hypothetical": hypothetical,
        "source": "fixture", "recorded_on": recorded_on,
        "registered_by": "fixture desk",
        "rules_version": "2026.10.1",
        "fact_fingerprint": f"fixture-{registry_id}",
        "as_of": recorded_on, "supersedes": None,
    })
    return store.get_policy_registration(registry_id) \
        if hasattr(store, "get_policy_registration") else None


# ---------------------------------------------------------------------------
# Subscriptions: judged strikes, supersession by link
# ---------------------------------------------------------------------------


def test_subscriber_receives_exactly_their_filter_set(service):
    _watch(service)
    sub = service.subscribe(
        "R. Menon", "R. Menon", "2026-01-01", ["price"],
        products=["UREA"])
    assert sub["floors"] == {"price": "watch"}
    expected = {a["alert_id"] for a in service.store.list_alerts()
                if a["item"] == "UREA"}
    assert expected  # the generated record has UREA alerts
    mine = service.deliveries(READ, "R. Menon")
    assert {d["notice_id"] for d in mine} == expected
    assert all(d["subscription_id"] == sub["subscription_id"]
               for d in mine)
    # The floor bites: v2, struck 2026-01-02 at the
    # alert floor, governs every notice struck from
    # that date — all the generated alerts (2026-01-05)
    # among them — so only UREA's alert-band subset
    # still arrives.
    service.subscribe(
        "R. Menon", "R. Menon", "2026-01-02", ["price"],
        products=["UREA"], floors={"price": "alert"})
    mine = service.deliveries(READ, "R. Menon")
    assert {d["notice_id"] for d in mine} == {
        a["alert_id"] for a in service.store.list_alerts()
        if a["item"] == "UREA" and a["band"] == "alert"}


def test_version_in_force_governs_each_notice(service):
    store = service.store
    _insert_alert(store, "ALR-FIX-A1", "UREA", "watch",
                  "2026-02-10")
    _insert_alert(store, "ALR-FIX-A2", "UREA", "alert",
                  "2026-03-10")
    v1 = service.subscribe(
        "R. Menon", "R. Menon", "2026-02-01", ["price"],
        products=["UREA"])
    v2 = service.subscribe(
        "R. Menon", "R. Menon", "2026-03-01", ["price"],
        products=["UREA"], floors={"price": "alert"})
    assert v2["supersedes"] == v1["subscription_id"]
    mine = service.deliveries("2026-03-15", "R. Menon")
    by_notice = {d["notice_id"]: d["subscription_id"]
                 for d in mine}
    # A1 was struck under v1 (watch floor: delivered);
    # A2 under v2 (alert floor: delivered).
    assert by_notice == {"ALR-FIX-A1": v1["subscription_id"],
                         "ALR-FIX-A2": v2["subscription_id"]}
    # A third version dropping the price class before
    # a later alert leaves that alert undelivered.
    _insert_alert(store, "ALR-FIX-A3", "UREA", "alert",
                  "2026-03-20")
    v3 = service.subscribe(
        "R. Menon", "R. Menon", "2026-03-15", ["gap"])
    assert v3["supersedes"] == v2["subscription_id"]
    mine = service.deliveries("2026-03-25", "R. Menon")
    assert {d["notice_id"] for d in mine} == \
        {"ALR-FIX-A1", "ALR-FIX-A2"}
    assert service.verify_subscriptions("2026-03-25")["verified"]


def test_strike_judged_by_the_access_pack(service):
    # A product reader reaching outside their remit.
    with pytest.raises(SubscriptionRefused):
        service.subscribe(
            "R. Menon", "R. Menon", "2026-01-01", ["price"],
            products=["DAP"])
    assert service.list_subscriptions("R. Menon") == []
    refused = [e for e in service.access_log()
               if e["surface"] == "subscription"
               and e["decision"] == "refused"]
    assert refused and refused[-1]["principal"] == "R. Menon"
    # A colleague may not strike for someone else.
    with pytest.raises(SubscriptionRefused):
        service.subscribe(
            "S. Iyer", "R. Menon", "2026-01-01", ["price"])
    # The strategy desk may strike for a reader.
    sub = service.subscribe(
        "S. Iyer", "A. Rao", "2026-01-01", ["price"],
        products=["DAP"])
    assert sub["struck_by"] == "A. Rao"
    # Viewers and unregistered names hold no subscriptions.
    with pytest.raises(SubscriptionRefused):
        service.subscribe(
            "Guest Viewer", "Guest Viewer", "2026-01-01",
            ["price"])
    with pytest.raises(SubscriptionRefused):
        service.subscribe(
            "Nobody Known", "A. Rao", "2026-01-01", ["price"])
    # A regional reader reaching outside their regions.
    with pytest.raises(SubscriptionRefused):
        service.subscribe(
            "D. Verma", "D. Verma", "2026-01-01", ["policy"],
            regions=["south"])
    ok = service.subscribe(
        "D. Verma", "D. Verma", "2026-01-01", ["policy"],
        regions=["north"])
    assert ok["regions"] == ["north"]
    # Every decision above re-decides from the pack.
    assert service.verify_access_log()["verified"]


def test_remit_confines_a_subscription_that_asks_for_all(service):
    _watch(service)
    # The strategy desk strikes Bhatt (MOP remit) a
    # filter with no product restriction: the strike is
    # allowed, the deliveries are not — remit is the
    # harder line.
    service.subscribe(
        "K. Bhatt", "A. Rao", "2026-01-01",
        ["price", "gap", "policy"])
    mine = service.deliveries(READ, "K. Bhatt")
    expected = {a["alert_id"] for a in service.store.list_alerts()
                if a["item"] == "MOP"}
    assert {d["notice_id"] for d in mine
            if d["notice_class"] == "price"} == expected
    assert all("MOP" in d["products"] for d in mine)
    assert service.verify_subscriptions(READ)["verified"]


# ---------------------------------------------------------------------------
# Notices: gap heads, policy heads, classes kept apart
# ---------------------------------------------------------------------------


def test_gap_notices_are_member_heads_with_queue_reference(service):
    store = service.store
    _insert_gap(store, "GAP-FIX-TIGHT", "DAP", "tight")
    _insert_gap(store, "GAP-FIX-SHORT", "MOP", "short")
    _insert_gap(store, "GAP-FIX-CALM", "UREA", "comfortable")
    service.subscribe(
        "A. Rao", "A. Rao", "2026-02-01", ["gap"])
    mine = {d["notice_id"]: d
            for d in service.deliveries(READ, "A. Rao")}
    assert set(mine) == {"GAP-FIX-TIGHT", "GAP-FIX-SHORT"}
    gap = store.get_gap("GAP-FIX-SHORT")
    assert mine["GAP-FIX-SHORT"]["queue_item_id"] == \
        queue_engine.item_id_for(gap)
    assert mine["GAP-FIX-TIGHT"]["severity"] == "tight"
    # A floor at short, struck 2026-02-02, governs
    # both heads (struck 2026-03-01): only the short
    # head still arrives, now under v2.
    v2 = service.subscribe(
        "A. Rao", "A. Rao", "2026-02-02", ["gap"],
        floors={"gap": "short"})
    mine = service.deliveries(READ, "A. Rao")
    assert {d["notice_id"] for d in mine} == {"GAP-FIX-SHORT"}
    assert mine[0]["subscription_id"] == v2["subscription_id"]
    assert service.verify_subscriptions(READ)["verified"]


def test_policy_notices_regions_and_class_separation(service):
    store = service.store
    north = next(d for d in store.list_districts()
                 if d["region"] == "north")
    _insert_policy(store, "POLREG-FIX-NORTH", "EV-FIX-NORTH",
                   ["UREA"], [north["district_id"]], "2026-02-15")
    _insert_policy(store, "POLREG-FIX-WIDE", "EV-FIX-WIDE",
                   ["DAP"], [], "2026-02-15")
    _insert_policy(store, "POLREG-FIX-HYPO", "EV-FIX-HYPO",
                   ["UREA"], [north["district_id"]], "2026-02-15",
                   hypothetical=True)
    service.subscribe(
        "D. Verma", "D. Verma", "2026-02-01", ["policy"],
        regions=["north"])
    service.subscribe(
        "A. Rao", "A. Rao", "2026-02-01",
        ["price", "gap", "policy"])
    verma = service.deliveries(READ, "D. Verma")
    # The north-scoped event reaches the north reader;
    # the market-wide event carries no geography inside
    # his remit, and the hypothetical is not a notice.
    assert {d["notice_id"] for d in verma} == {"POLREG-FIX-NORTH"}
    rao = service.deliveries(READ, "A. Rao")
    assert {d["notice_id"] for d in rao
            if d["notice_class"] == "policy"} == \
        {"POLREG-FIX-NORTH", "POLREG-FIX-WIDE"}
    # Policy is never counted as price.
    counts = service.undelivered_counts(READ)
    assert counts["policy"] == 0
    assert all(d["notice_class"] == "policy" for d in verma)
    assert service.verify_subscriptions(READ)["verified"]


def test_undelivered_by_design_counts_per_class(service):
    _watch(service)
    total = len(service.store.list_alerts())
    service.subscribe(
        "R. Menon", "R. Menon", "2026-01-01", ["price"],
        products=["UREA"])
    urea = {a["alert_id"] for a in service.store.list_alerts()
            if a["item"] == "UREA"}
    counts = service.undelivered_counts(READ)
    assert counts["price"] == total - len(urea)
    assert counts["gap"] == 0 and counts["policy"] == 0


# ---------------------------------------------------------------------------
# Escalation: the clock, the ladder, the stopped clock
# ---------------------------------------------------------------------------


def test_escalation_levels_and_ladder(service):
    store = service.store
    _insert_alert(store, "ALR-FIX-ESC", "DAP", "alert",
                  "2026-03-01")
    at = notify_engine.escalation_for(
        store, store.get_alert("ALR-FIX-ESC"), "2026-03-03")
    assert at["level"] == 0 and at["targets"] == []
    at = notify_engine.escalation_for(
        store, store.get_alert("ALR-FIX-ESC"), "2026-03-04")
    assert at["level"] == 1
    assert [t["principal"] for t in at["targets"]] == ["S. Iyer"]
    at = notify_engine.escalation_for(
        store, store.get_alert("ALR-FIX-ESC"), "2026-03-08")
    assert at["level"] == 2
    assert [t["principal"] for t in at["targets"]] == \
        ["S. Iyer", "A. Rao"]
    # An acknowledgement stops the clock from its date.
    service.acknowledge_alert(
        "ALR-FIX-ESC", "S. Iyer", "on it", "2026-03-09")
    at = notify_engine.escalation_for(
        store, store.get_alert("ALR-FIX-ESC"), "2026-03-20")
    assert at["level"] == 0 and at["state"] == "acknowledged"
    # Read before the acknowledgement, it still stood
    # escalated — the fold is taken at the read date.
    at = notify_engine.escalation_for(
        store, store.get_alert("ALR-FIX-ESC"), "2026-03-08")
    assert at["level"] == 2


def test_escalation_feedstock_fallback_and_followup_reference(service):
    store = service.store
    _insert_alert(store, "ALR-FIX-FEED", "AMMONIA", "alert",
                  "2026-03-01", kind="feedstock")
    at = notify_engine.escalation_for(
        store, store.get_alert("ALR-FIX-FEED"), "2026-03-05")
    assert at["level"] == 1
    # No product reader owns a feedstock: the ladder's
    # first rung falls back to the strategy principal.
    assert at["targets"][0]["principal"] == "A. Rao"
    assert at["targets"][0]["via"] == "strategy fallback"
    task = service.create_followup(
        "price_alert", "ALR-FIX-FEED", "A. Rao", "A. Rao",
        "2026-03-05", "Chase the feedstock alert.")
    at = notify_engine.escalation_for(
        store, store.get_alert("ALR-FIX-FEED"), "2026-03-05")
    assert at["followup_task_ids"] == [task["task_id"]]
    # A watch-band alert never escalates.
    _insert_alert(store, "ALR-FIX-WATCH", "DAP", "watch",
                  "2026-03-01")
    at = notify_engine.escalation_for(
        store, store.get_alert("ALR-FIX-WATCH"), "2026-03-20")
    assert at["level"] == 0


# ---------------------------------------------------------------------------
# Scoped alert reads: existence hiding on alerts
# ---------------------------------------------------------------------------


def test_scoped_alert_reads_hide_out_of_scope(service):
    _watch(service)
    urea = next(a for a in service.store.list_alerts()
                if a["item"] == "UREA")
    dap = next(a for a in service.store.list_alerts()
               if a["item"] == "DAP")
    mine = service.scoped_alert("R. Menon", urea["alert_id"], READ)
    assert mine is not None
    assert mine["alert_id"] == urea["alert_id"]
    assert "escalation" in mine
    assert service.scoped_alert(
        "R. Menon", dap["alert_id"], READ) is None
    assert service.scoped_alert(
        "Guest Viewer", urea["alert_id"], READ) is None
    assert service.scoped_alert(
        "A. Rao", "ALR-MISSING", READ) is None
    entries = [e for e in service.access_log()
               if e["surface"] == "alert_read"]
    assert len(entries) == 4
    assert service.verify_access_log()["verified"]


# ---------------------------------------------------------------------------
# Digests: frozen derivations, regeneration by link
# ---------------------------------------------------------------------------


def test_digest_freezes_the_derived_set(service):
    _watch(service)
    sub = service.subscribe(
        "A. Rao", "A. Rao", "2026-01-01",
        ["price", "gap", "policy"])
    digest = service.strike_digest(sub["subscription_id"], READ)
    derived = service.deliveries(READ, "A. Rao")
    assert digest["deliveries"] == derived
    assert digest["counts"]["price"] == len(
        [d for d in derived if d["notice_class"] == "price"])
    assert digest["counts"]["policy"] == len(
        [d for d in derived if d["notice_class"] == "policy"])
    text = service.digest_text(digest["digest_id"])
    assert digest["digest_id"] in text
    assert f"price {digest['counts']['price']}" in text
    # Regeneration at a later date is a new artefact
    # superseding this one — never an edit.
    again = service.strike_digest(sub["subscription_id"],
                                  "2026-04-25")
    assert again["digest_id"] != digest["digest_id"]
    assert again["supersedes"] == digest["digest_id"]
    # The same strike repeated is the same artefact.
    assert service.strike_digest(
        sub["subscription_id"], "2026-04-25")["digest_id"] == \
        again["digest_id"]
    assert service.verify_subscriptions(READ)["verified"]


def test_digest_tamper_is_named(service, settings):
    _watch(service)
    sub = service.subscribe(
        "A. Rao", "A. Rao", "2026-01-01", ["price"])
    digest = service.strike_digest(sub["subscription_id"], READ)
    assert service.verify_subscriptions(READ)["verified"]
    raw = raw_connect(settings)
    row = raw.execute(
        "SELECT payload FROM digests WHERE digest_id = ?",
        (digest["digest_id"],)).fetchone()
    payload = json.loads(row[0])
    payload["counts"]["price"] = 999
    raw.execute(
        "UPDATE digests SET payload = ? WHERE digest_id = ?",
        (json.dumps(payload), digest["digest_id"]))
    raw.commit()
    raw.close()
    problems = service.verify_subscriptions(READ)["problems"]
    assert any(digest["digest_id"] in p for p in problems)


def test_subscription_tamper_is_named(service, settings):
    sub = service.subscribe(
        "R. Menon", "R. Menon", "2026-01-01", ["price"],
        products=["UREA"])
    raw = raw_connect(settings)
    row = raw.execute(
        "SELECT payload FROM subscriptions "
        "WHERE subscription_id = ?",
        (sub["subscription_id"],)).fetchone()
    payload = json.loads(row[0])
    payload["products"] = ["DAP"]
    raw.execute(
        "UPDATE subscriptions SET payload = ? "
        "WHERE subscription_id = ?",
        (json.dumps(payload), sub["subscription_id"]))
    raw.commit()
    raw.close()
    problems = service.verify_subscriptions(READ)["problems"]
    assert any(sub["subscription_id"] in p for p in problems)


# ---------------------------------------------------------------------------
# The API surface
# ---------------------------------------------------------------------------


def test_api_subscriptions_deliveries_and_scoped_alert(
        service, settings):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    _watch(service)
    app = create_app(settings)
    with TestClient(app) as client:
        struck = client.post("/subscriptions", json={
            "principal": "R. Menon", "struck_by": "R. Menon",
            "at": "2026-01-01", "classes": ["price"],
            "products": ["UREA"]})
        assert struck.status_code == 200
        refused = client.post("/subscriptions", json={
            "principal": "R. Menon", "struck_by": "R. Menon",
            "at": "2026-01-01", "classes": ["price"],
            "products": ["DAP"]})
        assert refused.status_code == 403
        rows = client.get(
            "/deliveries", params={"as_of": READ,
                                   "principal": "R. Menon"})
        assert rows.status_code == 200
        assert rows.json()
        assert all("UREA" in d["products"]
                   for d in rows.json())
        alert_id = rows.json()[0]["notice_id"]
        ok = client.get(f"/scoped/alerts/{alert_id}", params={
            "principal": "R. Menon", "at": READ})
        assert ok.status_code == 200
        hidden = client.get(f"/scoped/alerts/{alert_id}",
                            params={"principal": "K. Bhatt",
                                    "at": READ})
        assert hidden.status_code == 404
        digest = client.post("/digests", json={
            "subscription_id": struck.json()["subscription_id"],
            "as_of": READ})
        assert digest.status_code == 200
        text = client.get(
            f"/digests/{digest.json()['digest_id']}/text")
        assert text.status_code == 200
        assert "DIGEST" in text.text
