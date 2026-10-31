"""Round 19: integration & admin configuration
(F21-IA1 + F21-IA2 + F21-AD1 + F21-AD2) — signed
webhook deliveries of artefact reads under a secret
no read ever returns; scoped API tokens whose every
read is judged and recorded; ERP/CRM-shaped exchange
ports whose contract violations quarantine whole
batches while conforming batches land translated
through the data plane; and the administration
layer itself: pack thresholds and master data as
effective-dated, diff-carrying versions that govern
by date and never reach backwards — an artefact
struck under an earlier version keeps the version
it names and re-performs under it.
"""

import json

import pytest

from fertilizer_intelligence import configuration_rules as config_pack
from fertilizer_intelligence import integration_rules as integration_pack
from fertilizer_intelligence import movements as movement_engine

from rawdb import raw_connect

WATCH_AS_OF = "2026-06-15"
WEEK = "2026-03-29"  # a Sunday inside rabi 2025-26


def _seed_all_config(service):
    for family in config_pack.FAMILIES:
        service.seed_pack_config(family, "ops lead", "2026-01-05")


def _seed_all_master(service):
    for register in ("application_rates", "season_calendar",
                     "districts", "products", "crops"):
        service.seed_master_register(
            register, "data steward", "2026-01-05")


def _alerts_with_spike_changed(service, **over):
    values = dict(service.resolve_pack_config(
        "alerts", "2026-06-15")["values"])
    values.update(over)
    return values


# -- pack configuration (F21-AD2) --------------------


def test_config_resolution_falls_back_to_code(service):
    resolved = service.resolve_pack_config("alerts", WATCH_AS_OF)
    assert resolved["origin"] == "code"
    assert resolved["version_label"] == "2026.10.1"
    assert resolved["values"]["spike_pct"] == 20.0
    _seed_all_config(service)
    seeded = service.resolve_pack_config("alerts", WATCH_AS_OF)
    assert seeded["origin"] == "register"
    assert seeded["version_label"] == "2026.10.1"
    assert seeded["values"] == resolved["values"]
    assert service.verify_pack_config()["verified"]


def test_config_set_strikes_label_and_diff(service):
    _seed_all_config(service)
    struck = service.set_pack_config(
        "alerts", _alerts_with_spike_changed(service, spike_pct=15.0),
        "2026-07-01", "ops lead", "2026-06-20")
    assert struck["version_label"] == "2026.10.2"
    assert [d["field"] for d in struck["diff"]] == ["spike_pct"]
    assert struck["diff"][0]["from"] == 20.0
    assert struck["diff"][0]["to"] == 15.0
    seed = service.list_pack_config_versions(family="alerts")[0]
    assert struck["supersedes"] == seed["version_id"]
    assert service.verify_pack_config()["verified"]


def test_config_set_refusals(service):
    _seed_all_config(service)
    changed = _alerts_with_spike_changed(service, spike_pct=15.0)
    with pytest.raises(ValueError, match="backdated"):
        service.set_pack_config(
            "alerts", changed, "2026-06-01", "ops lead", "2026-06-20")
    service.set_pack_config(
        "alerts", changed, "2026-07-01", "ops lead", "2026-06-20")
    with pytest.raises(ValueError, match="strictly increase"):
        service.set_pack_config(
            "alerts", _alerts_with_spike_changed(
                service, spike_pct=12.0),
            "2026-07-01", "ops lead", "2026-06-21")
    with pytest.raises(ValueError, match="changes nothing"):
        service.set_pack_config(
            "alerts", service.resolve_pack_config(
                "alerts", "2026-08-01")["values"],
            "2026-09-01", "ops lead", "2026-08-15")
    with pytest.raises(ValueError, match="editor"):
        service.set_pack_config(
            "alerts", changed, "2026-09-01", "  ", "2026-08-15")
    broken = _alerts_with_spike_changed(service, spike_pct=-1.0)
    with pytest.raises(ValueError, match="invalid"):
        service.set_pack_config(
            "alerts", broken, "2026-09-01", "ops lead", "2026-08-15")


def test_config_change_is_never_retroactive_for_alerts(service):
    _seed_all_config(service)
    first = service.run_price_watch(WATCH_AS_OF)
    assert first["alerts_config_version"] == "2026.10.1"
    service.set_pack_config(
        "alerts", _alerts_with_spike_changed(service, spike_pct=15.0),
        "2026-07-01", "ops lead", "2026-06-20")
    second = service.run_price_watch("2026-07-15")
    assert second["alerts_config_version"] == "2026.10.2"
    # Every alert on file — struck under either
    # version — re-performs under the version it
    # names.
    for alert in service.list_alerts():
        assert movement_engine.verify_alert(
            service.store, alert) == []
    labels = {a["rules_version"] for a in service.list_alerts()}
    assert labels == {"2026.10.1", "2026.10.2"}


def test_gaps_config_governs_by_date(service):
    _seed_all_config(service)
    early = service.supply_gap("DAP", "2025-26", "kharif", "2025-08-15")
    assert early["rules_version"] == "2026.10.1"
    values = dict(service.resolve_pack_config(
        "gaps", "2025-08-15")["values"])
    values["level_gap_tight_pct"] = -50.0
    service.set_pack_config(
        "gaps", values, "2025-09-01", "ops lead", "2025-08-20")
    later = service.supply_gap("DAP", "2025-26", "kharif", "2025-10-15")
    assert later["rules_version"] == "2026.10.2"
    assert service.verify_gap("DAP", "2025-26", "kharif") == []
    assert movement_engine is not None  # (import parity)
    from fertilizer_intelligence import supply as supply_engine
    assert supply_engine.verify_gap(service.store, early) == []


def test_field_cap_config_governs_by_strike(service):
    _seed_all_config(service)
    service.sync_field_reports([{
        "submission_id": "R19-CAP-1",
        "reporter": "T. Rao (field officer)",
        "district_id": "DST-LUD", "product": "DAP",
        "signal_type": "demand_signal", "direction": "up",
        "observed_on": "2025-10-28",
        "detail": "Wheat-belt DAP offtake surging.",
    }], "2025-11-02")
    first = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "kharif", "2025-11-02")
    assert first["rules_version"] == "2026.10.1"
    line = next(l for l in first["lines"] if l["capped"])
    assert line["applied_pct"] == 1.5
    service.set_pack_config(
        "field_signals", {"unverified_cap_pct": 0.5},
        "2025-11-01", "ops lead", "2025-10-30")
    second = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "kharif", "2025-11-02")
    assert second["rules_version"] == "2026.10.2"
    assert second["supersedes"] == first["assessment_id"]
    line = next(l for l in second["lines"] if l["capped"])
    assert line["applied_pct"] == 0.5
    from fertilizer_intelligence import field as field_engine
    assert field_engine.verify_assessment(
        service.store, first) == []
    assert field_engine.verify_assessment(
        service.store, second) == []


def test_freshness_config_governs_loads_and_boards(service):
    _seed_all_config(service)
    values = dict(service.resolve_pack_config(
        "freshness", "2026-04-01")["values"])
    values["windows_days"] = dict(values["windows_days"])
    values["windows_days"]["intl_price_feed"] = 60
    service.set_pack_config(
        "freshness", values, "2026-05-01", "ops lead", "2026-04-20")
    row = {
        "series_kind": "product", "item": "DAP",
        "month": "2026-05", "price": 27050.0,
        "unit": "INR/tonne", "source": "intl_price_feed",
        "as_of": "2026-05-05",
    }
    # Fifteen days old at load: stale under the code
    # pack's seven-day window, admissible under the
    # register's sixty.
    batch = service.load_connector_batch(
        "intl_price_feed", [row], "desk", "2026-05-20")
    assert batch["inserted"] == 1
    assert batch["quarantined"] == 0
    assert batch["freshness_version"] == "2026.10.2"
    board = service.strike_monitoring_board("2026-05-20")
    fresh = {r["source_id"]: r for r in board["freshness"]}
    assert fresh["intl_price_feed"]["window_days"] == 60
    assert fresh["intl_price_feed"]["state"] == "fresh"
    assert service.verify_monitoring("2026-05-20")["verified"]


def test_config_tamper_is_named(service, settings):
    _seed_all_config(service)
    assert service.verify_pack_config()["verified"]
    raw = raw_connect(settings)
    row = raw.execute(
        "SELECT payload FROM pack_config_versions "
        "WHERE family = 'alerts'").fetchone()
    payload = json.loads(row[0])
    payload["values"]["spike_pct"] = 99.0
    raw.execute(
        "UPDATE pack_config_versions SET payload = ? "
        "WHERE family = 'alerts'", (json.dumps(payload),))
    raw.commit()
    raw.close()
    problems = service.verify_pack_config()["problems"]
    assert any("alerts" in p or payload["version_id"] in p
               for p in problems)


# -- master data (F21-AD1) ----------------------------


def test_master_seed_and_rates_resolution(service):
    before = service.application_rates_in_force(WATCH_AS_OF)
    assert before["version_label"] == "2026.10.1"
    stored = {(r["crop"], r["product"]): r["rate_kg_ha"]
              for r in service.store.application_rates()}
    assert {(r["crop"], r["product"]): r["rate_kg_ha"]
            for r in before["rates"]} == stored
    _seed_all_master(service)
    after = service.application_rates_in_force(WATCH_AS_OF)
    assert after == before
    assert service.verify_master_data()["verified"]


def test_master_rates_version_changes_new_estimates_only(service):
    _seed_all_master(service)
    cell = ("DST-LUD", "DAP", "2025-26", "rabi")
    first = service.estimate_demand(*cell, "2026-02-15")
    assert first["rate_table_version"] == "2026.10.1"
    content = service.resolve_master_data(
        "application_rates", "2026-02-15")["content"]
    changed = {"rates": [dict(r) for r in content["rates"]]}
    target = next(r for r in changed["rates"]
                  if r["product"] == "DAP")
    target["rate_kg_ha"] = target["rate_kg_ha"] * 2
    service.set_master_version(
        "application_rates", changed, "2026-03-01",
        "data steward", "2026-02-20")
    second = service.estimate_demand(*cell, "2026-03-15")
    assert second["rate_table_version"] == "2026.10.2"
    assert second["base_tonnes"] != first["base_tonnes"]
    assert service.verify_estimate(first["estimate_id"]) == []
    assert service.verify_estimate(second["estimate_id"]) == []
    assert service.verify_master_data()["verified"]


def test_master_set_refusals(service):
    _seed_all_master(service)
    content = service.resolve_master_data(
        "application_rates", "2026-02-15")["content"]
    with pytest.raises(ValueError, match="backdated"):
        service.set_master_version(
            "application_rates", content, "2026-01-01",
            "data steward", "2026-02-20")
    with pytest.raises(ValueError, match="changes nothing"):
        service.set_master_version(
            "application_rates", content, "2026-03-01",
            "data steward", "2026-02-20")
    broken = {"rates": [dict(r) for r in content["rates"]]}
    broken["rates"][0]["rate_kg_ha"] = -5.0
    with pytest.raises(ValueError, match="invalid"):
        service.set_master_version(
            "application_rates", broken, "2026-03-01",
            "data steward", "2026-02-20")


# -- webhooks (F21-IA1) -------------------------------


def _register(service, name, kinds, as_of, secret=None):
    return service.register_webhook(
        name, f"https://example.invalid/hooks/{name}",
        kinds, secret or f"secret-{name}", "ops lead", as_of)


def test_webhook_price_alert_delivery_and_redaction(service):
    service.run_price_watch(WATCH_AS_OF)
    sub = _register(service, "erp", ["price_alert"], "2026-06-10")
    assert "secret" not in sub
    assert sub["secret_set"] is True
    assert "secret-erp" not in json.dumps(
        service.list_webhook_subscriptions())
    result = service.dispatch_webhooks("2026-06-16")
    deliveries = service.list_webhook_deliveries(
        subscription_id=sub["subscription_id"])
    assert deliveries
    assert result["deliveries_struck"] == len(deliveries)
    spike = next(a for a in service.list_alerts()
                 if a["rule_id"] == "spike")
    delivery = next(d for d in deliveries
                    if d["trigger_id"] == spike["alert_id"])
    assert delivery["payload"]["alert_id"] == spike["alert_id"]
    assert delivery["payload"]["state"] == spike["state"]
    again = service.dispatch_webhooks("2026-06-16")
    assert again["deliveries_struck"] == 0
    assert service.verify_webhooks()["verified"]


def test_webhook_gap_band_and_brief_triggers(service):
    _register(service, "desk", ["gap_band", "brief_published"],
              "2025-08-01")
    first = service.supply_gap("DAP", "2025-26", "kharif",
                                "2025-08-15")
    assert first["band"] == "comfortable"
    service.dispatch_webhooks("2025-08-16")
    assert service.list_webhook_deliveries() == []
    worsened = service.supply_gap("DAP", "2025-26", "kharif",
                                  "2025-10-15")
    assert worsened["band"] == "short"
    brief = service.weekly_brief(WEEK, "test desk")
    service.publish_artefact(
        "weekly_brief", brief["brief_id"], "A. Rao", "2026-03-30")
    service.dispatch_webhooks("2026-03-30")
    kinds = {(d["event_kind"], d["trigger_id"])
             for d in service.list_webhook_deliveries()}
    assert ("gap_band", worsened["gap_id"]) in kinds
    assert ("brief_published", brief["brief_id"]) in kinds
    assert service.verify_webhooks()["verified"]


def test_webhook_disable_silences_from_its_date(service):
    early = _register(service, "early", ["price_alert"],
                      "2026-06-10")
    service.set_webhook_active(
        early["subscription_id"], "disable", "ops lead",
        "2026-06-11", "endpoint down")
    service.run_price_watch(WATCH_AS_OF)
    service.dispatch_webhooks("2026-06-16")
    assert service.list_webhook_deliveries(
        subscription_id=early["subscription_id"]) == []
    service.set_webhook_active(
        early["subscription_id"], "enable", "ops lead",
        "2026-06-16", "endpoint restored")
    # Re-enabling after the trigger's date does not
    # rewrite it either: the fold is at the trigger,
    # which fired on 2026-06-15 while the
    # subscription stood disabled.
    service.dispatch_webhooks("2026-06-16")
    assert service.list_webhook_deliveries(
        subscription_id=early["subscription_id"]) == []
    assert service.verify_webhooks()["verified"]


def test_webhook_delivery_tamper_is_named(service, settings):
    service.run_price_watch(WATCH_AS_OF)
    sub = _register(service, "erp", ["price_alert"], "2026-06-10")
    service.dispatch_webhooks("2026-06-16")
    delivery = service.list_webhook_deliveries(
        subscription_id=sub["subscription_id"])[0]
    raw = raw_connect(settings)
    row = raw.execute(
        "SELECT payload FROM webhook_deliveries "
        "WHERE delivery_id = ?",
        (delivery["delivery_id"],)).fetchone()
    payload = json.loads(row[0])
    payload["signature"] = "0" * 64
    raw.execute(
        "UPDATE webhook_deliveries SET payload = ? "
        "WHERE delivery_id = ?",
        (json.dumps(payload), delivery["delivery_id"]))
    raw.commit()
    raw.close()
    problems = service.verify_webhooks()["problems"]
    assert any(delivery["delivery_id"] in p for p in problems)


# -- scoped tokens (F21-IA1) --------------------------


def test_token_lifecycle_and_decision_record(service):
    service.run_price_watch(WATCH_AS_OF)
    issued = service.issue_api_token(
        "crm-sync", ["alerts"], "ops lead", "2026-06-16",
        secret="tok-r19")
    artefact = issued["token"]
    assert issued["plaintext"] == "tok-r19"
    assert "tok-r19" not in json.dumps(artefact)
    assert artefact["secret_sha256"] == \
        integration_pack.secret_hash("tok-r19")
    alert = service.list_alerts()[0]
    allowed = service.api_token_read(
        "tok-r19", "alert", alert["alert_id"], "2026-06-17")
    assert allowed["decision"]["decision"] == "allowed"
    assert allowed["result"]["alert_id"] == alert["alert_id"]
    refused = service.api_token_read(
        "tok-r19", "brief", "BRF-x", "2026-06-17")
    assert refused["decision"]["decision"] == "refused"
    assert refused["result"] is None
    unknown = service.api_token_read(
        "tok-unknown", "alert", alert["alert_id"], "2026-06-17")
    assert unknown["decision"]["decision"] == "refused"
    assert unknown["decision"]["token_id"] is None
    service.revoke_api_token(
        artefact["token_id"], "ops lead", "2026-06-18",
        "rotation")
    after = service.api_token_read(
        "tok-r19", "alert", alert["alert_id"], "2026-06-19")
    assert after["decision"]["decision"] == "refused"
    assert len(service.list_token_decisions()) == 4
    assert service.verify_api_tokens()["verified"]
    # Same-day discipline: a read judged before a
    # revocation struck on the same date stays
    # honestly allowed on re-judgement — the entry
    # binds the acts it saw — while a read after it
    # refuses, and the whole record still verifies.
    second = service.issue_api_token(
        "crm-sync-2", ["alerts"], "ops lead", "2026-06-20",
        secret="tok-r19-b")
    morning = service.api_token_read(
        "tok-r19-b", "alert", alert["alert_id"], "2026-06-20")
    assert morning["decision"]["decision"] == "allowed"
    assert morning["decision"]["acts_seen"] == []
    service.revoke_api_token(
        second["token"]["token_id"], "ops lead",
        "2026-06-20", "same-day rotation")
    evening = service.api_token_read(
        "tok-r19-b", "alert", alert["alert_id"], "2026-06-20")
    assert evening["decision"]["decision"] == "refused"
    assert evening["decision"]["acts_seen"] != []
    assert service.verify_api_tokens()["verified"]


def test_token_decision_tamper_is_named(service, settings):
    service.run_price_watch(WATCH_AS_OF)
    service.issue_api_token(
        "crm-sync", ["alerts"], "ops lead", "2026-06-16",
        secret="tok-r19")
    alert = service.list_alerts()[0]
    entry = service.api_token_read(
        "tok-r19", "gap", "GAP-x", "2026-06-17")["decision"]
    assert entry["decision"] == "refused"
    raw = raw_connect(settings)
    row = raw.execute(
        "SELECT payload FROM token_decisions "
        "WHERE decision_id = ?",
        (entry["decision_id"],)).fetchone()
    payload = json.loads(row[0])
    payload["decision"] = "allowed"
    raw.execute(
        "UPDATE token_decisions SET payload = ? "
        "WHERE decision_id = ?",
        (json.dumps(payload), entry["decision_id"]))
    raw.commit()
    raw.close()
    problems = service.verify_api_tokens()["problems"]
    assert any(entry["decision_id"] in p for p in problems)


# -- exchange ports (F21-IA2) -------------------------


def _production_row(**over):
    row = {
        "material_code": "ERP-UREA", "period": "2026-05",
        "planned_qty_kt": 120.0, "actual_qty_kt": 118.5,
        "source": "erp_production_returns",
        "as_of": "2026-06-10",
    }
    row.update(over)
    return row


def test_exchange_production_lands_translated(service):
    batch = service.import_exchange_batch(
        "erp_production_in", [_production_row()],
        "etl service", "2026-06-12")
    assert batch["outcome"] == "landed"
    assert batch["counts"] == {
        "received": 1, "inserted": 1, "duplicates": 0,
        "quarantined": 0, "refused": 0}
    facts = [f for f in service.store.supply_facts(product="UREA")
             if f["month"] == "2026-05"]
    assert len(facts) == 1
    assert facts[0]["planned_tonnes"] == 120000.0
    assert facts[0]["actual_tonnes"] == 118500.0
    ingest = service.store.get_ingest_batch(
        batch["ingest_batch_id"])
    assert ingest["source_id"] == "erp_production_in"
    again = service.import_exchange_batch(
        "erp_production_in", [_production_row()],
        "etl service", "2026-06-12")
    assert again["batch_id"] == batch["batch_id"]
    assert service.verify_exchange()["verified"]
    # The monitoring board's source set is unchanged:
    # the ports keep their own registry.
    assert service.verify_monitoring("2026-06-12")["verified"]


def test_exchange_dispatch_lands_season_actuals(service):
    district = service.store.list_districts()[0]["district_id"]
    row = {
        "district_code": district, "crop_year": "2025-26",
        "season": "rabi", "material_code": "ERP-DAP",
        "dispatched_qty_kt": 12.25,
        "source": "erp_dispatch_returns", "as_of": "2026-06-10",
    }
    batch = service.import_exchange_batch(
        "erp_dispatch_in", [row], "etl service", "2026-06-12")
    assert batch["outcome"] == "landed"
    actuals = [a for a in service.store.season_actuals()
               if a["district_id"] == district
               and a["actual_kind"] == "dispatch"]
    assert len(actuals) == 1
    assert actuals[0]["quantity_tonnes"] == 12250.0
    assert service.verify_exchange()["verified"]


@pytest.mark.parametrize("rows,kind", [
    ([_production_row(material_code="ERP-XXX")],
     "unknown_material"),
    ([_production_row(planned_qty_kt=-1.0)],
     "negative_quantity"),
    ([_production_row(period="2026-13")],
     "malformed_period"),
    ([{k: v for k, v in _production_row().items()
       if k != "period"}], "missing_field"),
    ([_production_row(plant="north")], "unknown_field"),
    ([_production_row(source="someone_else")],
     "source_mismatch"),
    ([], "empty_batch"),
])
def test_exchange_violations_quarantine_whole(
        service, rows, kind):
    before = len(service.store.supply_facts(product="UREA"))
    batches_before = len(service.store.list_ingest_batches())
    batch = service.import_exchange_batch(
        "erp_production_in", rows, "etl service", "2026-06-12")
    assert batch["outcome"] == "quarantined_whole"
    assert kind in {v["violation"] for v in batch["violations"]}
    assert batch["ingest_batch_id"] is None
    assert len(service.store.supply_facts(
        product="UREA")) == before
    assert len(service.store.list_ingest_batches()) == \
        batches_before
    assert service.verify_exchange()["verified"]


def test_exchange_feeds_derive_from_artefacts(service):
    service.run_price_watch(WATCH_AS_OF)
    feed = service.strike_exchange_feed(
        "crm_alert_feed", "2026-06-20", "ops lead")
    assert feed["row_count"] == len(service.list_alerts())
    assert feed["checksum"] == integration_pack.checksum(
        feed["rows"])
    brief = service.weekly_brief(WEEK, "test desk")
    service.publish_artefact(
        "weekly_brief", brief["brief_id"], "A. Rao", "2026-03-30")
    brief_feed = service.strike_exchange_feed(
        "crm_brief_feed", "2026-06-20", "ops lead")
    assert [r["brief_id"] for r in brief_feed["rows"]] == \
        [brief["brief_id"]]
    assert brief_feed["rows"][0]["published_by"] == "A. Rao"
    assert service.verify_exchange()["verified"]


def test_exchange_feed_tamper_is_named(service, settings):
    service.run_price_watch(WATCH_AS_OF)
    feed = service.strike_exchange_feed(
        "crm_alert_feed", "2026-06-20", "ops lead")
    raw = raw_connect(settings)
    row = raw.execute(
        "SELECT payload FROM exchange_feeds WHERE feed_id = ?",
        (feed["feed_id"],)).fetchone()
    payload = json.loads(row[0])
    payload["rows"] = payload["rows"][:1]
    raw.execute(
        "UPDATE exchange_feeds SET payload = ? "
        "WHERE feed_id = ?",
        (json.dumps(payload), feed["feed_id"]))
    raw.commit()
    raw.close()
    problems = service.verify_exchange()["problems"]
    assert any(feed["feed_id"] in p for p in problems)


# -- the API surface -----------------------------------


def test_integration_api(service, settings):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        seeded = client.post("/pack-config/seed", json={
            "family": "alerts", "editor": "ops lead",
            "struck_on": "2026-01-05"})
        assert seeded.status_code == 200
        resolved = client.get(
            "/pack-config/resolve",
            params={"family": "alerts", "on": WATCH_AS_OF})
        assert resolved.json()["version_label"] == "2026.10.1"
        sub = client.post("/webhooks", json={
            "integration": "erp",
            "endpoint": "https://example.invalid/hooks/erp",
            "event_kinds": ["price_alert"],
            "secret": "api-secret", "registered_by": "ops lead",
            "as_of": "2026-06-10"})
        assert sub.status_code == 200
        assert "secret" not in sub.json()
        assert sub.json()["secret_set"] is True
        service.run_price_watch(WATCH_AS_OF)
        struck = client.post(
            "/webhooks/dispatch", json={"as_of": "2026-06-16"})
        assert struck.status_code == 200
        assert struck.json()["deliveries_struck"] > 0
        issued = client.post("/api-tokens", json={
            "integration": "crm-sync", "scopes": ["alerts"],
            "issued_by": "ops lead", "issued_at": "2026-06-16",
            "secret": "api-token"})
        assert issued.status_code == 200
        assert issued.json()["plaintext"] == "api-token"
        assert "api-token" not in json.dumps(
            issued.json()["token"])
        alert = service.list_alerts()[0]
        read = client.post("/token-reads", json={
            "token": "api-token", "kind": "alert",
            "target": alert["alert_id"], "at": "2026-06-17"})
        assert read.json()["decision"]["decision"] == "allowed"
        batch = client.post("/exchange/batches", json={
            "port": "erp_production_in",
            "rows": [_production_row()],
            "loaded_by": "etl service", "as_of": "2026-06-12"})
        assert batch.json()["outcome"] == "landed"
        verify = client.get("/integration/verify")
        assert verify.json()["verified"]
