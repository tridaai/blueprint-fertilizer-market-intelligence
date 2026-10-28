"""Round 1: generator truth, store discipline, model port, API."""

import sqlite3

import pytest

from fertilizer_intelligence import models
from fertilizer_intelligence.generator import (
    derive_consumption,
    generate_dataset,
    load_dataset,
)
from fertilizer_intelligence.modelport import ProfileNotConfigured, get_model_port


def test_generator_is_deterministic():
    first = generate_dataset()
    second = generate_dataset()
    assert first.manifest == second.manifest
    assert [p.model_dump() for p in first.price_points] == [
        p.model_dump() for p in second.price_points
    ]
    assert [c.model_dump() for c in first.consumption_facts] == [
        c.model_dump() for c in second.consumption_facts
    ]


def test_planted_spike_and_delay():
    ds = generate_dataset()
    spike = ds.manifest["planted"]["price_spike"]
    dap = {p.month: p.price for p in ds.price_points if p.item == "DAP"}
    assert dap[spike["month"]] == spike["planted_price"]
    assert spike["planted_price"] == round(
        spike["baseline_price"] * (1 + spike["magnitude_pct"] / 100.0), 2
    )
    delay = ds.manifest["planted"]["import_delay"]
    late = [a for a in ds.import_arrivals if a.arrived_month > a.expected_month]
    assert [a.shipment_id for a in late] == [delay["shipment_id"]]
    assert late[0].expected_month == "2025-10"
    assert late[0].arrived_month == "2025-12"


def test_coverage_is_complete():
    ds = generate_dataset()
    area_cells = {(a.district_id, a.crop_year, a.season) for a in ds.area_facts}
    assert len(area_cells) == 12 * 2 * 2
    assert len(ds.districts) == 12
    products = {c.product for c in ds.consumption_facts}
    assert products == {"UREA", "DAP", "NPK_10_26_26", "MOP", "GLYPHOSATE", "CHLORPYRIFOS"}


def test_every_fact_carries_provenance():
    ds = generate_dataset()
    fact_lists = [
        ds.area_facts, ds.monsoon_facts, ds.soil_facts, ds.consumption_facts,
        ds.price_points, ds.import_arrivals, ds.supply_facts,
        ds.competitor_points, ds.policy_events, ds.field_reports,
    ]
    for facts in fact_lists:
        assert facts, "a fact list is empty"
        for fact in facts:
            assert fact.source and fact.as_of


def test_consumption_rederivable_from_stored_inputs(service):
    store = service.store
    derived = derive_consumption(
        store.area_facts(), store.application_rates(),
        store.soil_facts(), store.monsoon_facts(),
    )
    stored = {
        (c["district_id"], c["crop_year"], c["season"], c["product"]): c["quantity_tonnes"]
        for c in store.consumption_facts()
    }
    assert set(derived) == set(stored)
    for key, value in stored.items():
        assert abs(derived[key] - value) <= 0.01


def test_store_is_insert_only(service):
    store = service.store
    # No update/delete verbs exist on the port at all.
    verbs = [name for name in dir(store) if name.startswith(("update_", "delete_", "remove_"))]
    assert verbs == []
    # A duplicate insert is an error, never an overwrite.
    with pytest.raises(Exception):
        store.insert_districts([models.District(
            district_id="DST-LUD", name="Duplicate", state="X", region="north")])
    with pytest.raises(RuntimeError):
        load_dataset(store)


def test_manifest_counts_match_store(service):
    counts = service.store.fact_counts()
    for name, expected in service.manifest["counts"].items():
        assert counts[name] == expected


def test_model_port_fail_closed(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "NIM_BASE_URL", "NIM_API_KEY", "NIM_MODEL",
                "BEDROCK_MODEL_ID", "AWS_REGION"):
        monkeypatch.delenv(var, raising=False)
    assert get_model_port("offline").profile_name == "offline"
    for profile in ("anthropic", "nim", "bedrock"):
        with pytest.raises(ProfileNotConfigured):
            get_model_port(profile)
    with pytest.raises(ProfileNotConfigured):
        get_model_port("no-such-profile")


def test_migrations_run_once(settings):
    from fertilizer_intelligence.store import MarketStore

    MarketStore(settings)
    store = MarketStore(settings)  # second open: no re-apply, no error
    assert store.get_manifest() is None  # migrations only; no dataset


def test_api_surface(settings):
    import httpx

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    with httpx.Client(transport=transport, base_url="http://test") as client:
        assert client.get("/health").json() == {"status": "ok"}
        readiness = client.get("/readiness")
        assert readiness.status_code == 200
        assert readiness.json()["ready"] is True
        assert len(client.get("/districts").json()) == 12
        dap = client.get("/prices", params={"series_kind": "product", "item": "DAP"}).json()
        assert len(dap) == 24
        view = client.get(
            "/districts/DST-GUN/demand-inputs",
            params={"crop_year": "2025-26", "season": "kharif"},
        ).json()
        assert view["area"] and view["monsoon"] and view["consumption"]
        manifest = client.get("/manifest").json()
        assert manifest["planted"]["import_delay"]["shipment_id"] == "IMP-DAP-2510"
        reports = client.get("/field-reports", params={"signal_kind": "stock_out"}).json()
        assert reports and all(r["reporter"] for r in reports)
