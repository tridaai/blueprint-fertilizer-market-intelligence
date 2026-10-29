"""Round 11: the production data plane — connector loads
from a registered source registry, provenance refused at
the port, quarantine with exact named reasons, corrections
as linked new facts whose chains re-perform, and
season-close actuals as a distinct fact class whose
unmatched rows are reported, never dropped.
"""

import json

import pytest

from fertilizer_intelligence import ingest_rules as pack
from fertilizer_intelligence import models

from rawdb import raw_connect

LOAD_DATE = "2026-05-06"


def _price(item, month, price, **over):
    row = {
        "series_kind": "product", "item": item, "month": month,
        "price": price, "unit": "INR/tonne",
        "source": "intl_price_feed", "as_of": "2026-05-05",
    }
    row.update(over)
    return row


GOOD_PRICES = [
    _price("DAP", "2026-05", 27050.0),
    _price("UREA", "2026-05", 5910.0),
    _price("NATURAL_GAS", "2026-05", 3.41, series_kind="feedstock",
           unit="USD/MMBtu"),
]


def _actual(district="DST-GUN", product="UREA", kind="consumption",
            qty=45210.5, **over):
    row = {
        "district_id": district, "crop_year": "2025-26",
        "season": "rabi", "product": product, "actual_kind": kind,
        "quantity_tonnes": qty, "source": "state_dispatch_returns",
        "as_of": "2026-04-15",
    }
    row.update(over)
    return row


# -- the registry and the port --------------------------------------


def test_registry_covers_every_fact_class():
    by_class = {}
    for source_id, entry in pack.SOURCES.items():
        assert entry["cadence"] and entry["owner"]
        assert entry["freshness_days"] > 0
        assert entry["provenance_source"]
        by_class.setdefault(entry["fact_class"], []).append(source_id)
    assert set(by_class) == set(pack.FACT_CLASSES)


def test_unregistered_source_is_refused_before_any_row(service):
    with pytest.raises(ValueError, match="unregistered ingest source"):
        service.load_connector_batch(
            "carrier_pigeon", GOOD_PRICES, "desk", LOAD_DATE)
    assert service.list_ingest_batches() == []
    assert service.store.fact_counts()["price_points"] == 240


def test_batch_lands_and_reconciles(service):
    batch = service.load_connector_batch(
        "intl_price_feed", GOOD_PRICES, "desk", LOAD_DATE)
    assert batch["received"] == 3
    assert batch["inserted"] == 3
    assert batch["duplicates"] == 0
    assert batch["quarantined"] == 0
    assert batch["refused"] == 0
    assert batch["received"] == (
        batch["inserted"] + batch["duplicates"]
        + batch["quarantined"] + batch["refused"])
    assert len(service.store.price_points()) == 243
    result = service.verify_ingest_batch(batch["batch_id"])
    assert result["verified"] and result["problems"] == []


def test_replay_lands_nothing_twice(service):
    first = service.load_connector_batch(
        "intl_price_feed", GOOD_PRICES, "desk", LOAD_DATE)
    again = service.load_connector_batch(
        "intl_price_feed", GOOD_PRICES, "desk", LOAD_DATE)
    assert again["batch_id"] == first["batch_id"]
    assert len(service.store.price_points()) == 243
    # The same rows under a new batch are duplicates, row by row.
    replay = service.load_connector_batch(
        "intl_price_feed", GOOD_PRICES, "desk", "2026-05-07")
    assert replay["batch_id"] != first["batch_id"]
    assert replay["inserted"] == 0
    assert replay["duplicates"] == 3
    assert len(service.store.price_points()) == 243
    assert len(service.list_ingest_batches()) == 2


def test_row_without_provenance_is_refused_at_the_port(service):
    rows = [
        _price("MOP", "2026-05", 24100.0),
        {"series_kind": "product", "item": "MOP", "month": "2026-06",
         "price": 24200.0, "unit": "INR/tonne",
         "source": "intl_price_feed"},                      # no as_of
        {"series_kind": "product", "item": "MOP", "month": "2026-07",
         "price": 24300.0, "unit": "INR/tonne",
         "as_of": "2026-05-05"},                            # no source
        _price("MOP", "2026-08", 24400.0, source=""),       # empty source
    ]
    batch = service.load_connector_batch(
        "intl_price_feed", rows, "desk", LOAD_DATE)
    assert batch["inserted"] == 1
    assert batch["refused"] == 3
    assert batch["quarantined"] == 0
    assert all(r["reason"] == "missing_provenance"
               for r in batch["refusals"])
    assert {tuple(r["missing"]) for r in batch["refusals"]} == {
        ("as_of",), ("source",), ("source",)}
    assert len(service.store.price_points()) == 241
    assert service.store.provenance_gaps() == 0
    # The schema-level half of the refusal: the fact model
    # itself will not construct without provenance.
    with pytest.raises(Exception):
        models.PricePoint(series_kind="product", item="MOP",
                          month="2026-05", price=1.0, unit="INR/tonne")


def test_load_report_reconciles_against_the_store(service):
    batch = service.load_connector_batch(
        "intl_price_feed", GOOD_PRICES, "desk", LOAD_DATE)
    stored = {(p["series_kind"], p["item"], p["month"])
              for p in service.store.price_points()}
    for label in batch["inserted_keys"]:
        series_kind, item, month = label.split("/")
        assert (series_kind, item, month) in stored
    # Tamper with a fact the batch inserted: the batch
    # verifier must name it.
    conn = raw_connect(service.settings)
    conn.execute(
        "UPDATE price_points SET price = price + 1 "
        "WHERE series_kind = ? AND item = ? AND month = ?",
        ("product", "DAP", "2026-05"))
    conn.commit()
    conn.close()
    result = service.verify_ingest_batch(batch["batch_id"])
    assert not result["verified"]
    assert any("product/DAP/2026-05" in p for p in result["problems"])


# -- quarantine: exact reasons, and engines never see the rows -------


def _dirty_batch_rows():
    return [
        # a different DAP print for a month the feed already landed
        _price("DAP", "2026-05", 99999.0, as_of="2026-05-06"),
        # a product nobody tracks
        _price("POTASH_X", "2026-05", 1200.0, as_of="2026-05-06"),
        # a kind nobody tracks
        _price("DAP", "2026-06", 27000.0, series_kind="spot",
               as_of="2026-05-06"),
        # a negative price
        _price("MOP", "2026-05", -10.0, as_of="2026-05-06"),
        # another feed's provenance under this feed's batch
        _price("MOP", "2026-06", 24100.0, source="rival_feed",
               as_of="2026-05-06"),
        # older than the 7-day freshness rule at the load date
        _price("MOP", "2026-07", 24100.0, as_of="2026-04-20"),
        # dated after the load date
        _price("MOP", "2026-08", 24100.0, as_of="2026-05-09"),
        # a required field missing entirely
        {"series_kind": "product", "item": "MOP", "month": "2026-09",
         "unit": "INR/tonne", "source": "intl_price_feed",
         "as_of": "2026-05-06"},
    ]


def test_quarantine_reasons_are_exact(service):
    service.load_connector_batch(
        "intl_price_feed", GOOD_PRICES, "desk", LOAD_DATE)
    counts_before = service.store.fact_counts()
    batch = service.load_connector_batch(
        "intl_price_feed", _dirty_batch_rows(), "desk", "2026-05-07")
    assert batch["received"] == 8
    assert batch["inserted"] == 0
    assert batch["quarantined"] == 8
    assert batch["refused"] == 0
    reasons = [h["reason"] for h in batch["quarantine"]]
    assert sorted(reasons) == sorted([
        "conflicts_with_stored", "unknown_product", "unknown_kind",
        "non_positive_price", "source_mismatch",
        "stale_beyond_freshness", "future_as_of", "malformed_row",
    ])
    assert set(reasons) <= set(pack.QUARANTINE_REASONS)
    held = service.list_quarantine(batch_id=batch["batch_id"])
    assert len(held) == 8
    assert {h["quarantine_id"] for h in held} == {
        h["quarantine_id"] for h in batch["quarantine"]}
    # Nothing held reached a fact table, and no count moved.
    assert service.store.fact_counts() == counts_before
    result = service.verify_ingest_batch(batch["batch_id"])
    assert result["verified"]


def test_quarantined_rows_never_reach_the_engines(service):
    service.load_connector_batch(
        "intl_price_feed", GOOD_PRICES, "desk", LOAD_DATE)
    clean = service.estimate_demand(
        "DST-GUN", "DAP", "2025-26", "kharif", "2026-04-15")
    service.load_connector_batch(
        "intl_price_feed", _dirty_batch_rows(), "desk", "2026-05-07")
    after = service.estimate_demand(
        "DST-GUN", "DAP", "2025-26", "kharif", "2026-04-15")
    assert after["estimate_id"] == clean["estimate_id"]
    assert after["fact_fingerprint"] == clean["fact_fingerprint"]
    movements = service.run_price_watch("2026-05-07")
    assert movements["movements_stored"] >= 0  # the watch ran on facts
    months = {m["month"] for m in service.store.list_movements(
        series_kind="product", item="MOP")}
    assert "2026-08" not in months  # the future-dated row never landed


def test_supply_and_import_quarantine_reasons(service):
    supply_rows = [
        {"product": "DAP", "month": "2026-05",
         "planned_tonnes": 410000.0, "actual_tonnes": 398000.0,
         "source": "plant_production_returns", "as_of": "2026-05-20"},
        {"product": "DAP", "month": "2026-06",
         "planned_tonnes": 400000.0, "actual_tonnes": -5.0,
         "source": "plant_production_returns", "as_of": "2026-05-20"},
        {"product": "POTASH_X", "month": "2026-06",
         "planned_tonnes": 1.0, "actual_tonnes": 1.0,
         "source": "plant_production_returns", "as_of": "2026-05-20"},
    ]
    batch = service.load_connector_batch(
        "plant_production_returns", supply_rows, "desk", "2026-05-21")
    assert batch["inserted"] == 1
    assert sorted(h["reason"] for h in batch["quarantine"]) == [
        "negative_quantity", "unknown_product"]
    import_rows = [
        {"shipment_id": "IMP-UREA-2605", "product": "UREA",
         "expected_month": "2026-05", "arrived_month": "2026-06",
         "quantity_tonnes": 52000.0, "origin": "Oman",
         "source": "port_import_manifests", "as_of": "2026-05-25"},
        {"shipment_id": "IMP-DAP-2510", "product": "DAP",
         "expected_month": "2025-10", "arrived_month": "2025-12",
         "quantity_tonnes": 99000.0, "origin": "Morocco",
         "source": "port_import_manifests", "as_of": "2026-05-25"},
    ]
    batch = service.load_connector_batch(
        "port_import_manifests", import_rows, "desk", "2026-05-26")
    # The planted delay shipment is already stored with its
    # true tonnage: the manifest's different figure conflicts
    # and is held, never overwritten.
    assert batch["inserted"] == 1
    assert [h["reason"] for h in batch["quarantine"]] == [
        "conflicts_with_stored"]
    stored = {a["shipment_id"]: a
              for a in service.store.import_arrivals()}
    assert stored["IMP-DAP-2510"]["quantity_tonnes"] != 99000.0


# -- corrections ------------------------------------------------------


def _dap_key():
    return {"series_kind": "product", "item": "DAP", "month": "2026-05"}


def _dap_row(price, as_of):
    return {"series_kind": "product", "item": "DAP",
            "month": "2026-05", "price": price, "unit": "INR/tonne",
            "source": "intl_price_feed", "as_of": as_of}


def test_correction_chain_folds_and_reperforms(service):
    service.load_connector_batch(
        "intl_price_feed", GOOD_PRICES, "desk", LOAD_DATE)
    first = service.submit_correction(
        "price_points", _dap_row(27125.5, "2026-05-08"), None, "desk")
    assert first["corrects_kind"] == "stored_fact"
    assert first["supersedes"] is None
    second = service.submit_correction(
        "price_points", _dap_row(27130.0, "2026-05-09"),
        first["correction_id"], "desk")
    assert second["supersedes"] == first["correction_id"]
    # Resubmitting the head correction returns it, unchanged.
    again = service.submit_correction(
        "price_points", _dap_row(27130.0, "2026-05-09"),
        first["correction_id"], "desk")
    assert again["correction_id"] == second["correction_id"]
    # The stored fact is never rewritten; the effective row
    # is the fold.
    stored = next(p for p in service.store.price_points("product", "DAP")
                  if p["month"] == "2026-05")
    assert stored["price"] == 27050.0
    assert service.effective_fact("price_points", _dap_key())["price"] \
        == 27130.0
    result = service.verify_correction_chain("price_points", _dap_key())
    assert result["verified"] and result["problems"] == []
    assert result["chain"] == [first["correction_id"],
                               second["correction_id"]]
    assert result["base_present"] is True


def test_corrections_must_extend_the_head(service):
    service.load_connector_batch(
        "intl_price_feed", GOOD_PRICES, "desk", LOAD_DATE)
    first = service.submit_correction(
        "price_points", _dap_row(27125.5, "2026-05-08"), None, "desk")
    service.submit_correction(
        "price_points", _dap_row(27130.0, "2026-05-09"),
        first["correction_id"], "desk")
    # A correction aimed at the buried first link is refused.
    with pytest.raises(ValueError, match="not the head"):
        service.submit_correction(
            "price_points", _dap_row(1.0, "2026-05-10"),
            first["correction_id"], "desk")
    # So is an unlinked correction once a chain exists.
    with pytest.raises(ValueError, match="name its head"):
        service.submit_correction(
            "price_points", _dap_row(1.0, "2026-05-10"), None, "desk")
    # And a correction with nothing behind it at all.
    with pytest.raises(ValueError, match="nothing is stored"):
        service.submit_correction(
            "price_points",
            _price("MOP", "2027-01", 24000.0, as_of="2026-05-10"),
            None, "desk")
    # Provenance is refused on corrections too.
    row = _dap_row(1.0, "2026-05-10")
    del row["as_of"]
    with pytest.raises(ValueError, match="without provenance"):
        service.submit_correction(
            "price_points", row, None, "desk")


def test_correction_of_a_quarantined_row(service):
    dirty = [
        {"district_id": "DST-GUN", "crop_year": "2025-26",
         "season": "rabi", "product": "UREA",
         "actual_kind": "consumption", "quantity_tonnes": -3.0,
         "source": "state_dispatch_returns", "as_of": "2026-04-15"},
    ]
    batch = service.load_connector_batch(
        "state_dispatch_returns", dirty, "desk", "2026-04-20")
    held = batch["quarantine"][0]
    assert held["reason"] == "negative_quantity"
    fixed = dict(dirty[0], quantity_tonnes=45210.5,
                 as_of="2026-04-16")
    correction = service.submit_correction(
        "season_actuals", fixed, held["quarantine_id"], "state desk")
    assert correction["corrects_kind"] == "quarantine_record"
    key = {"district_id": "DST-GUN", "crop_year": "2025-26",
           "season": "rabi", "product": "UREA",
           "actual_kind": "consumption"}
    # The corrected row is the effective row at the key,
    # even though no fact ever landed there.
    assert service.store.season_actuals() == []
    effective = service.effective_fact("season_actuals", key)
    assert effective["quantity_tonnes"] == 45210.5
    result = service.verify_correction_chain("season_actuals", key)
    assert result["verified"] and result["base_present"] is False


def test_correction_tamper_is_detected(service):
    service.load_connector_batch(
        "intl_price_feed", GOOD_PRICES, "desk", LOAD_DATE)
    service.submit_correction(
        "price_points", _dap_row(27125.5, "2026-05-08"), None, "desk")
    conn = raw_connect(service.settings)
    row = conn.execute(
        "SELECT payload FROM fact_corrections").fetchone()
    payload = json.loads(row[0])
    payload["row"]["price"] = 1.0
    conn.execute(
        "UPDATE fact_corrections SET payload = ?",
        (json.dumps(payload),))
    conn.commit()
    conn.close()
    result = service.verify_correction_chain("price_points", _dap_key())
    assert not result["verified"]
    assert any("fingerprint mismatch" in p for p in result["problems"])


# -- season-close actuals ----------------------------------------------


def test_actuals_are_a_distinct_fact_class(service):
    service.estimate_demand("DST-GUN", "UREA", "2025-26", "rabi",
                            "2026-04-15")
    estimates_before = {
        e["estimate_id"]: e["fact_fingerprint"]
        for e in service.store.list_estimates()}
    consumption_before = service.store.fact_counts()["consumption_facts"]
    rows = [
        _actual(),                                        # Guntur UREA
        _actual(product="MOP", kind="dispatch", qty=12340.0),
        _actual(district="DST-LUD", qty=38900.0),
    ]
    batch = service.load_connector_batch(
        "state_dispatch_returns", rows, "desk", "2026-04-20")
    assert batch["fact_class"] == "season_actuals"
    assert batch["inserted"] == 3
    # Actuals landed in their own table only: the estimate
    # set is byte-identical and the consumption facts (the
    # R1 history the estimates derive from) did not move.
    assert service.store.fact_counts()["season_actuals"] == 3
    assert service.store.fact_counts()["consumption_facts"] \
        == consumption_before
    assert {e["estimate_id"]: e["fact_fingerprint"]
            for e in service.store.list_estimates()} \
        == estimates_before
    # Replaying the import lands nothing twice.
    replay = service.load_connector_batch(
        "state_dispatch_returns", rows, "desk", "2026-04-21")
    assert replay["inserted"] == 0 and replay["duplicates"] == 3
    assert service.store.fact_counts()["season_actuals"] == 3


def test_actuals_report_names_the_unmatched(service):
    service.estimate_demand("DST-GUN", "UREA", "2025-26", "rabi",
                            "2026-04-15")
    rows = [
        _actual(),
        _actual(product="MOP", kind="dispatch", qty=12340.0),
        _actual(district="DST-LUD", qty=38900.0),
    ]
    service.load_connector_batch(
        "state_dispatch_returns", rows, "desk", "2026-04-20")
    report = service.actuals_report("2025-26", "rabi")
    assert report["actual_count"] == 3
    assert report["matched_count"] == 1
    assert report["unmatched_count"] == 2
    # Unmatched rows are named by natural key — reported,
    # not dropped — and every actual is in the report.
    assert sorted(report["unmatched"]) == sorted([
        "DST-GUN/2025-26/rabi/MOP/dispatch",
        "DST-LUD/2025-26/rabi/UREA/consumption",
    ])
    matched = [r for r in report["rows"] if r["matched_estimate"]]
    assert len(matched) == 1
    assert matched[0]["district_id"] == "DST-GUN"
    assert matched[0]["estimate_id"].startswith("EST-")


def test_actuals_quarantine_reasons(service):
    rows = [
        _actual(district="DST-XXX"),                    # no such district
        _actual(product="POTASH_X"),                    # no such product
        _actual(kind="guesswork"),                      # no such kind
        _actual(qty=-1.0),                              # negative tonnes
        _actual(),                                      # the good row
    ]
    batch = service.load_connector_batch(
        "state_dispatch_returns", rows, "desk", "2026-04-20")
    assert batch["inserted"] == 1
    assert sorted(h["reason"] for h in batch["quarantine"]) == [
        "negative_quantity", "unknown_district", "unknown_kind",
        "unknown_product"]
    assert service.store.fact_counts()["season_actuals"] == 1


# -- surfaces ------------------------------------------------------------


def test_api_and_cli_surfaces(service, settings, tmp_path, capsys):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        sources = client.get("/ingest/sources").json()
        assert len(sources) == len(pack.SOURCES)
        resp = client.post("/ingest/batches", json={
            "source_id": "intl_price_feed", "rows": GOOD_PRICES,
            "loaded_by": "api desk", "load_date": LOAD_DATE})
        assert resp.status_code == 200
        batch = resp.json()
        assert batch["inserted"] == 3
        got = client.get(f"/ingest/batches/{batch['batch_id']}").json()
        assert got["batch_id"] == batch["batch_id"]
        verified = client.get(
            f"/ingest/batches/{batch['batch_id']}/verify").json()
        assert verified["verified"]
        bad = client.post("/ingest/batches", json={
            "source_id": "carrier_pigeon", "rows": [],
            "loaded_by": "api desk", "load_date": LOAD_DATE})
        assert bad.status_code == 422
        correction = client.post("/ingest/corrections", json={
            "fact_class": "price_points",
            "row": _dap_row(27125.5, "2026-05-08"),
            "corrects": None, "corrected_by": "api desk"})
        assert correction.status_code == 200
        effective = client.post("/ingest/effective", json={
            "fact_class": "price_points", "key": _dap_key()}).json()
        assert effective["price"] == 27125.5
        chain = client.post("/ingest/corrections/verify", json={
            "fact_class": "price_points", "key": _dap_key()}).json()
        assert chain["verified"]
        resp = client.post("/ingest/batches", json={
            "source_id": "state_dispatch_returns", "rows": [_actual()],
            "loaded_by": "api desk", "load_date": "2026-04-20"})
        assert resp.json()["inserted"] == 1
        report = client.get("/actuals/report", params={
            "crop_year": "2025-26", "season": "rabi"}).json()
        assert report["actual_count"] == 1
        held = client.get("/ingest/quarantine").json()
        assert held == []

    from fertilizer_intelligence.cli import main as cli_main

    rows_file = tmp_path / "rows.json"
    rows_file.write_text(json.dumps(GOOD_PRICES), encoding="utf-8")
    db = service.settings.sqlite_path
    rc = cli_main(["--db", str(db), "--migrations", "migrations",
                   "ingest-load", "--source", "intl_price_feed",
                   "--file", str(rows_file), "--loaded-by", "cli desk",
                   "--load-date", "2026-05-08"])
    assert rc == 0
    out = capsys.readouterr().out
    start = out.index('{\n  "batch_id"')
    printed, _ = json.JSONDecoder().raw_decode(out[start:])
    assert printed["source_id"] == "intl_price_feed"
    assert printed["received"] == 3
    assert printed["inserted"] + printed["duplicates"] == 3
    assert printed["quarantined"] == 0 and printed["refused"] == 0
