"""Round 13 — the district map, the morning board and the
gap action queue.

The map's headline fixture is hand-computed: a district
whose estimate grew exactly twenty percent on the prior
year, a tight product gap and a strong confirmed signal
pressure composing — under the map pack's worse-of rule —
into a short district band. The board's lifecycle test
walks the planted spike alert out of the open lane by
acts alone. The queue's membership test is exact: the
queue holds the non-comfortable gap heads and nothing
else, and it follows the head when the head clears.
"""

from __future__ import annotations

import json

import pytest

from fertilizer_intelligence import board as board_engine
from fertilizer_intelligence import field as field_engine
from fertilizer_intelligence import market_map as map_engine
from fertilizer_intelligence import queue_rules as queue_pack
from fertilizer_intelligence.queue import QueueStateError
from rawdb import raw_connect

AS_OF = "2026-03-01"


# -- fixture artefacts ---------------------------------------------------


def _insert_estimate(store, estimate_id, district, product, total,
                     year="2025-26", season="kharif", status="complete",
                     missing=None, as_of="2026-03-01"):
    store.insert_estimate({
        "estimate_id": estimate_id, "district_id": district,
        "product": product, "crop_year": year, "season": season,
        "status": status, "base_tonnes": total,
        "total_tonnes": total, "missing_drivers": missing or [],
        "rules_version": "2026.10.1",
        "rate_table_version": "2026.10.1",
        "fact_fingerprint": f"fixture-{estimate_id}",
        "as_of": as_of, "supersedes": None,
    }, [])
    return store.get_estimate(estimate_id)


def _insert_gap(store, gap_id, product, band, gap_pct=-4.0, cover=80.0,
                year="2025-26", season="kharif"):
    store.insert_supply_gap({
        "gap_id": gap_id, "product": product, "crop_year": year,
        "season": season, "as_of": "2026-03-01",
        "as_of_month": "2026-03",
        "demand_tonnes": 10000.0, "demand_outlook_id": "OUT-FIX",
        "opening_stock_tonnes": 0.0,
        "production_actual_tonnes": 0.0, "arrivals_tonnes": 0.0,
        "scheduled_imports_tonnes": 0.0, "due_imports_tonnes": 0.0,
        "credited_imports_tonnes": 0.0, "slipped_tonnes": 0.0,
        "programme_cover_pct": cover,
        "available_tonnes": 9600.0, "gap_tonnes": -400.0,
        "gap_pct_of_demand": gap_pct, "band": band,
        "band_basis": "import_programme_cover",
        "position_months": [], "uncovered_months": [],
        "rules_version": "2026.10.1",
        "fact_fingerprint": f"fixture-{gap_id}", "supersedes": None,
    })
    return store.get_gap(gap_id)


def _insert_assessment(store, assessment_id, district, product,
                       adjustment_pct, estimate_id):
    store.insert_field_assessment({
        "assessment_id": assessment_id, "district_id": district,
        "product": product, "crop_year": "2025-26", "season": "kharif",
        "as_of": "2026-03-01", "estimate_id": estimate_id,
        "estimate_status": "complete", "base_tonnes": 1200.0,
        "lines": [], "excluded": [],
        "adjustment_pct": adjustment_pct,
        "adjustment_tonnes": 60.0, "adjusted_tonnes": 1260.0,
        "capped_report_ids": [], "rules_version": "2026.10.1",
        "fact_fingerprint": f"fixture-{assessment_id}",
        "supersedes": None,
    })
    return store.get_field_assessment(assessment_id)


def _land_report(store, submission_id, district="DST-LUD",
                 product="DAP", kind="stock_out",
                 observed_on="2025-08-15", landed_on="2026-02-20",
                 reporter="Field Officer A"):
    sub = {
        "submission_id": submission_id, "reporter": reporter,
        "district_id": district, "product": product,
        "signal_type": "planted_report", "signal_kind": kind,
        "observed_on": observed_on,
        "detail": "fixture report", "source": "field_survey",
    }
    report = field_engine.build_report(sub, landed_on, None)
    store.insert_field_report_artefact(report.model_dump())
    return store.get_field_report_artefact(report.report_id)


def _review(store, report_id, act, reason, as_of="2026-02-25",
            actor="Reviewer R"):
    acts = store.list_field_review_acts(report_id)
    store.insert_field_review_act({
        "act_id": f"FRA-{report_id}-{len(acts) + 1:03d}",
        "report_id": report_id, "act": act, "actor": actor,
        "reason": reason, "note": None, "as_of": as_of,
    })


def _cell(cells, product, district):
    return next(c for c in cells
                if c["product"] == product
                and c["district_id"] == district)


# -- GS1: cell composition, hand-computed -------------------------------


def test_cell_composition_hand_computed(service):
    store = service.store
    _insert_estimate(store, "EST-CUR", "DST-LUD", "DAP", 1200.0)
    _insert_estimate(store, "EST-PRIOR", "DST-LUD", "DAP", 1000.0,
                     year="2024-25", as_of="2025-03-01")
    _insert_estimate(store, "EST-NOBASE", "DST-KAR", "UREA", 800.0)
    _insert_gap(store, "GAP-FIX-DAP", "DAP", "tight")
    _insert_assessment(store, "FSA-FIX", "DST-LUD", "DAP", 5.0, "EST-CUR")

    cells = map_engine.build_cells(store, "2025-26", "kharif", AS_OF)
    cell = _cell(cells, "DAP", "DST-LUD")
    # By hand: (1200 - 1000) / 1000 = +20.0% — growing.
    assert cell["change_pct"] == 20.0
    assert cell["outlook_band"] == "growing"
    assert cell["data_state"] == "complete"
    assert cell["product_gap_band"] == "tight"
    # By hand: an adjustment of +5.0% sits over the pack's
    # 4.0 short line — pressure short; the worse of tight
    # and short is short.
    assert cell["pressure_band"] == "short"
    assert cell["district_gap_band"] == "short"
    assert cell["district_gap_basis"] == "product_gap_and_district_signals"
    assert cell["estimate_id"] == "EST-CUR"
    assert cell["prior_estimate_id"] == "EST-PRIOR"
    assert cell["gap_id"] == "GAP-FIX-DAP"
    assert cell["assessment_id"] == "FSA-FIX"

    nobase = _cell(cells, "UREA", "DST-KAR")
    assert nobase["change_pct"] is None
    assert nobase["outlook_band"] == "no_baseline"
    # No gap artefact and no assessment for this cell:
    # the map states the absence instead of borrowing one.
    assert nobase["district_gap_band"] is None
    assert nobase["district_gap_basis"] == "no_gap_evidence"

    nodata = _cell(cells, "DAP", "DST-PAT")
    assert nodata["data_state"] == "no_data"
    assert nodata["demand_tonnes"] is None
    assert nodata["estimate_id"] is None


def test_partial_estimate_renders_partial_never_confident(service):
    store = service.store
    _insert_estimate(store, "EST-PART", "DST-KAR", "DAP", 500.0,
                     status="partial", missing=["price_elasticity"])
    artefact = map_engine.build_map(
        store, "2025-26", "kharif", AS_OF, "test desk").model_dump()
    cell = _cell(artefact["cells"], "DAP", "DST-KAR")
    assert cell["data_state"] == "partial"
    assert cell["missing_drivers"] == ["price_elasticity"]
    html = artefact["html"]
    assert "partial data" in html
    assert "price_elasticity" in html
    assert "tile partial" in html or " partial" in html
    nodata = _cell(artefact["cells"], "DAP", "DST-PAT")
    assert nodata["data_state"] == "no_data"
    assert "No data — no estimate artefact" in html
    # The page is read-only by construction.
    assert "<form" not in html
    assert "method=" not in html.lower()
    assert map_engine.verify_map(store, artefact) == []


def test_monsoon_layer_reperforms_from_facts(service):
    store = service.store
    artefact = map_engine.build_map(
        store, "2025-26", "kharif", AS_OF, "test desk").model_dump()
    facts = store.monsoon_facts("DST-LUD", "2025-26", "kharif")
    entry = next(m for m in artefact["monsoon"]
                 if m["district_id"] == "DST-LUD")
    assert entry["deviation_pct"] == facts[-1]["deviation_pct"]
    assert entry["fact_id"] == "monsoon_facts:DST-LUD|2025-26|kharif"
    assert entry["source"] == facts[-1]["source"]

    empty = map_engine.build_map(
        store, "2026-27", "kharif", AS_OF, "test desk").model_dump()
    assert all(m["band"] == "no_data" for m in empty["monsoon"])
    assert all(c["data_state"] == "no_data" for c in empty["cells"])
    assert map_engine.verify_map(store, empty) == []


# -- GS2: the signal layer keeps its classes apart -----------------------


def test_signal_layer_separation(service):
    store = service.store
    confirmed = _land_report(store, "SUB-CONF")
    _land_report(store, "SUB-OPEN")
    queried = _land_report(store, "SUB-QUERY")
    rejected = _land_report(store, "SUB-REJ")
    _review(store, confirmed["report_id"], "confirm", "corroborated")
    _review(store, queried["report_id"], "query", "needs_quantity")
    _review(store, rejected["report_id"], "reject", "not_credible")
    _land_report(store, "SUB-LATE", landed_on="2026-03-05")

    signals = map_engine._signals_for(
        store, "DST-LUD", "DAP", "2025-26", "kharif", AS_OF)
    assert [e["report_id"] for e in signals["confirmed"]] == [
        confirmed["report_id"]]
    pending = {e["report_id"]: e["review_state"]
               for e in signals["pending"]}
    assert pending == {
        "FSR-SUB-OPEN": "unreviewed",
        "FSR-SUB-QUERY": "queried",
    }
    assert signals["rejected_count"] == 1
    # The classes are disjoint, and the late-landing report
    # is not on a map dated before it landed.
    confirmed_ids = {e["report_id"] for e in signals["confirmed"]}
    assert not confirmed_ids & set(pending)
    assert "FSR-SUB-LATE" not in confirmed_ids | set(pending)

    # Without a date bound, the late report joins pending.
    unbounded = map_engine._signals_for(
        store, "DST-LUD", "DAP", "2025-26", "kharif")
    assert "FSR-SUB-LATE" in {
        e["report_id"] for e in unbounded["pending"]}


# -- the map as a service surface -----------------------------------------


def test_map_service_flow(service):
    artefact = service.market_map("2025-26", "kharif", "test desk", AS_OF)
    assert len(artefact["cells"]) == 72
    assert service.verify_map(artefact["map_id"])["verified"]
    again = service.market_map("2025-26", "kharif", "test desk", AS_OF)
    assert again["map_id"] == artefact["map_id"]
    assert len(service.list_maps("2025-26", "kharif")) == 1
    mop = _cell(artefact["cells"], "MOP", "DST-LUD")
    assert mop["product_gap_band"] == "short"
    assert mop["district_gap_band"] == "short"
    gly = _cell(artefact["cells"], "GLYPHOSATE", "DST-LUD")
    assert gly["gap_id"] is None
    assert gly["product_gap_band"] is None
    assert gly["district_gap_basis"] == "district_signals_only"
    assert artefact["html"] == service.map_html(artefact["map_id"])


def test_map_delay_window_shows_dap_short(service):
    gap = service.supply_gap("DAP", "2025-26", "kharif", "2025-11-30")
    assert gap["band"] == "short"
    artefact = service.market_map(
        "2025-26", "kharif", "test desk", "2025-11-30")
    dap_cells = [c for c in artefact["cells"] if c["product"] == "DAP"]
    assert len(dap_cells) == 12
    assert all(c["product_gap_band"] == "short" for c in dap_cells)
    assert all(c["district_gap_band"] == "short" for c in dap_cells)
    assert service.verify_map(artefact["map_id"])["verified"]


def test_map_tamper_is_named(service, settings):
    artefact = service.market_map("2025-26", "kharif", "test desk", AS_OF)
    raw = raw_connect(settings)
    row = raw.execute(
        "SELECT payload FROM market_maps WHERE map_id = ?",
        (artefact["map_id"],)).fetchone()
    payload = json.loads(row[0])
    target = next(c for c in payload["cells"]
                  if c["product"] == "MOP"
                  and c["district_id"] == "DST-LUD")
    target["demand_tonnes"] += 1.0
    raw.execute(
        "UPDATE market_maps SET payload = ? WHERE map_id = ?",
        (json.dumps(payload), artefact["map_id"]))
    raw.commit()
    raw.close()
    result = service.verify_map(artefact["map_id"])
    assert not result["verified"]
    assert any("MOP/DST-LUD" in p for p in result["problems"])


def test_unnamed_map_build_is_refused(service):
    with pytest.raises(ValueError):
        service.market_map("2025-26", "kharif", "  ", AS_OF)


# -- OW1: the morning board ------------------------------------------------


def test_board_open_lane_follows_alert_acts(service):
    store = service.store
    service.run_price_watch(AS_OF)
    service.demand_outlook("2025-26", "kharif", AS_OF)
    board = board_engine.build_board(
        store, "regional_head", "2025-26", "kharif", AS_OF,
        "test desk").model_dump()
    lanes = {lane["lane"]: lane["rows"] for lane in board["lanes"]}
    open_rows = lanes["open_alerts"]
    spike = next(a for a in service.list_alerts()
                 if a["rule_id"] == "spike")
    assert spike["state"] == "open"
    assert open_rows[0]["alert_id"] == spike["alert_id"]
    assert open_rows[0]["band"] == "alert"
    open_ids = {r["alert_id"] for r in open_rows}
    assert open_ids == {
        a["alert_id"] for a in service.list_alerts()
        if a["state"] == "open"}

    service.acknowledge_alert(
        spike["alert_id"], "test desk", "seen — watching the unwind",
        AS_OF)
    rebuilt = board_engine.build_board(
        store, "regional_head", "2025-26", "kharif", AS_OF,
        "test desk").model_dump()
    lanes = {lane["lane"]: lane["rows"] for lane in rebuilt["lanes"]}
    assert spike["alert_id"] not in {
        r["alert_id"] for r in lanes["open_alerts"]}
    assert len(lanes["open_alerts"]) == len(open_rows) - 1
    assert board_engine.verify_board(store, rebuilt) == []

    leadership = board_engine.build_board(
        store, "leadership", "2025-26", "kharif", AS_OF,
        "test desk").model_dump()
    assert [lane["lane"] for lane in leadership["lanes"]] == [
        "open_alerts", "districts_trending_short",
        "pending_brief_approvals"]
    with pytest.raises(ValueError):
        board_engine.build_board(
            store, "nobody", "2025-26", "kharif", AS_OF, "test desk")


def test_board_service_flow_short_lane_and_pending_brief(service):
    board = service.morning_board(
        "regional_head", "2025-26", "kharif", "board desk", AS_OF)
    assert service.verify_board(board["board_id"])["verified"]
    lanes = {lane["lane"]: lane["rows"] for lane in board["lanes"]}
    short_rows = lanes["districts_trending_short"]
    assert len(short_rows) == 12
    assert all(r["product"] == "MOP" for r in short_rows)
    assert all(r["district_gap_band"] == "short" for r in short_rows)
    assert all(r["map_id"] is not None for r in short_rows)
    assert lanes["pending_brief_approvals"] == []

    brief = service.weekly_brief("2026-03-27", "board desk", "2026-03-27")
    rebuilt = service.morning_board(
        "regional_head", "2025-26", "kharif", "board desk", "2026-03-27")
    lanes = {lane["lane"]: lane["rows"] for lane in rebuilt["lanes"]}
    pending = lanes["pending_brief_approvals"]
    assert [r["brief_id"] for r in pending] == [brief["brief_id"]]
    # The brief carries the MOP short gap — the heaviest
    # severity class on the board.
    assert pending[0]["severity_class"] == "short_gap"
    assert pending[0]["short_gaps"] >= 1
    assert service.verify_board(rebuilt["board_id"])["verified"]

    service.publish_artefact(
        "weekly_brief", brief["brief_id"], "board desk", "2026-03-28")
    after = service.morning_board(
        "regional_head", "2025-26", "kharif", "board desk", "2026-03-28")
    lanes = {lane["lane"]: lane["rows"] for lane in after["lanes"]}
    assert lanes["pending_brief_approvals"] == []


# -- OW2: the gap action queue ----------------------------------------------


def _strike_queue_gaps(service):
    service.supply_gap("MOP", "2025-26", "kharif", "2026-03-31")
    service.supply_gap("MOP", "2025-26", "rabi", "2026-03-31")
    service.supply_gap("DAP", "2025-26", "kharif", "2026-03-31")


def test_queue_membership_is_exactly_the_noncomfortable_heads(service):
    _strike_queue_gaps(service)
    dap = service.get_gap("DAP", "2025-26", "kharif")
    assert dap["band"] == "comfortable"
    views = service.gap_queue(AS_OF)
    # Membership order is the queue's stated one: worst
    # band first, then the furthest under demand — rabi's
    # level gap (-170.6% of demand) sits further under
    # than kharif's (-62.8%), so rabi's item leads.
    assert [(v["product"], v["season"]) for v in views] == [
        ("MOP", "rabi"), ("MOP", "kharif")]
    item = views[0]
    assert item["band"] == "short"
    assert item["owner"] == queue_pack.DEFAULT_OWNERS["MOP"]
    assert item["state"] == "open"
    assert item["due_date"] == "2026-03-08"
    assert item["due_state"] == "within_term"
    assert item["scenario_fork_id"] is None
    assert service.verify_queue(AS_OF)["verified"]
    # Reading the queue again strikes nothing twice.
    assert service.gap_queue(AS_OF)[0]["item_id"] == item["item_id"]
    assert len(service.store.list_queue_items()) == 2


def test_queue_acts_fold_and_vocabulary(service):
    _strike_queue_gaps(service)
    views = service.gap_queue(AS_OF)
    mop_kharif = next(v for v in views if v["season"] == "kharif")
    mop_rabi = next(v for v in views if v["season"] == "rabi")

    view = service.assign_queue_item(
        mop_kharif["item_id"], "duty manager", "T. Rao — potash desk",
        "2026-03-02")
    assert view["owner"] == "T. Rao — potash desk"
    assert view["state"] == "open"
    view = service.start_queue_item(
        mop_kharif["item_id"], "T. Rao", "2026-03-02")
    assert view["state"] == "in_progress"
    with pytest.raises(QueueStateError):
        service.start_queue_item(
            mop_kharif["item_id"], "T. Rao", "2026-03-02")
    with pytest.raises(ValueError):
        service.close_queue_item(
            mop_kharif["item_id"], "T. Rao", "sorted_properly",
            "2026-03-03")
    with pytest.raises(ValueError):
        service.link_queue_scenario(
            mop_kharif["item_id"], "T. Rao", "SCN-nope", "2026-03-03")

    fork = service.create_scenario(
        "demand_estimate",
        {"district_id": "DST-LUD", "product": "MOP",
         "crop_year": "2025-26", "season": "kharif"},
        [{"lever": "monsoon_deviation_shift", "value": -10}],
        "test desk", as_of=AS_OF)
    view = service.link_queue_scenario(
        mop_kharif["item_id"], "T. Rao", fork["fork_id"], "2026-03-03")
    assert view["scenario_fork_id"] == fork["fork_id"]
    view = service.close_queue_item(
        mop_kharif["item_id"], "T. Rao", "scenario_adopted", "2026-03-04")
    assert view["state"] == "closed"
    assert view["due_state"] == "closed"
    with pytest.raises(QueueStateError):
        service.assign_queue_item(
            mop_kharif["item_id"], "duty manager", "Someone Else",
            "2026-03-05")

    overdue = service.queue_item(mop_rabi["item_id"], "2026-03-09")
    assert overdue["state"] == "open"
    assert overdue["due_state"] == "overdue"
    due_today = service.queue_item(mop_rabi["item_id"], "2026-03-08")
    assert due_today["due_state"] == "due_today"
    assert service.verify_queue("2026-03-09")["verified"]


def test_queue_membership_follows_the_gap_head(service):
    gap = service.supply_gap("DAP", "2025-26", "kharif", "2025-11-30")
    assert gap["band"] == "short"
    views = service.gap_queue("2025-12-01")
    dap_items = [v for v in views if v["product"] == "DAP"]
    assert len(dap_items) == 1
    assert dap_items[0]["gap_id"] == gap["gap_id"]
    assert dap_items[0]["due_date"] == "2025-12-08"

    cleared = service.supply_gap("DAP", "2025-26", "kharif", "2026-03-31")
    assert cleared["band"] == "comfortable"
    views = service.gap_queue("2026-03-31")
    assert [v for v in views if v["product"] == "DAP"] == []
    # The old item stays on record — it simply leaves the
    # queue view when its gap's head clears.
    assert service.store.queue_item_for_gap(gap["gap_id"]) is not None
    assert service.verify_queue("2026-03-31")["verified"]


# -- surfaces -----------------------------------------------------------------


def test_api_and_cli_surfaces(service, settings, tmp_path, capsys):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        resp = client.post("/maps", json={
            "crop_year": "2025-26", "season": "kharif",
            "built_by": "api desk", "as_of": AS_OF})
        assert resp.status_code == 200
        artefact = resp.json()
        listed = client.get("/maps", params={
            "crop_year": "2025-26", "season": "kharif"}).json()
        assert [m["map_id"] for m in listed] == [artefact["map_id"]]
        verified = client.get(
            f"/maps/{artefact['map_id']}/verify").json()
        assert verified["verified"]
        page = client.get(f"/maps/{artefact['map_id']}/html")
        assert page.status_code == 200
        assert "District market map" in page.text
        assert client.get("/maps/MAP-nope").status_code == 404

        resp = client.post("/boards", json={
            "role": "leadership", "crop_year": "2025-26",
            "season": "kharif", "built_by": "api desk",
            "as_of": AS_OF})
        assert resp.status_code == 200
        board = resp.json()
        assert [lane["lane"] for lane in board["lanes"]] == [
            "open_alerts", "districts_trending_short",
            "pending_brief_approvals"]
        verified = client.get(
            f"/boards/{board['board_id']}/verify").json()
        assert verified["verified"]

        queue = client.get("/queue", params={"as_of": AS_OF}).json()
        assert {v["product"] for v in queue} == {"MOP"}
        item = queue[0]
        resp = client.post(
            f"/queue/{item['item_id']}/acts",
            json={"act": "close", "actor": "api desk",
                  "as_of": "2026-03-05", "reason": "bogus_reason"})
        assert resp.status_code == 422
        resp = client.post(
            f"/queue/{item['item_id']}/acts",
            json={"act": "close", "actor": "api desk",
                  "as_of": "2026-03-05", "reason": "risk_accepted"})
        assert resp.status_code == 200
        assert resp.json()["state"] == "closed"
        verified = client.get(
            "/queue/verify", params={"as_of": AS_OF}).json()
        assert verified["verified"]

    from fertilizer_intelligence.cli import main as cli_main

    base = ["--db", str(tmp_path / "cli-r13.db"),
            "--migrations", "migrations"]
    rc = cli_main(base + [
        "map", "--crop-year", "2025-26", "--season", "kharif",
        "--by", "cli desk", "--as-of", AS_OF])
    assert rc == 0
    out = capsys.readouterr().out
    map_cli, _ = json.JSONDecoder().raw_decode(out[out.index("{\n"):])
    rc = cli_main(base + ["verify-map", map_cli["map_id"]])
    assert rc == 0
    out = capsys.readouterr().out
    verified, _ = json.JSONDecoder().raw_decode(out[out.index("{\n"):])
    assert verified["verified"]
    rc = cli_main(base + ["queue", "--as-of", AS_OF])
    assert rc == 0
    out = capsys.readouterr().out
    queue_cli, _ = json.JSONDecoder().raw_decode(out[out.index("[\n"):])
    assert {v["product"] for v in queue_cli} == {"MOP"}
    rc = cli_main(base + [
        "queue-act", queue_cli[0]["item_id"], "--act", "start",
        "--actor", "cli desk", "--as-of", "2026-03-02"])
    assert rc == 0
    out = capsys.readouterr().out
    acted, _ = json.JSONDecoder().raw_decode(out[out.index("{\n"):])
    assert acted["state"] == "in_progress"
    rc = cli_main(base + ["verify-queue", "--as-of", AS_OF])
    assert rc == 0
    out = capsys.readouterr().out
    verified, _ = json.JSONDecoder().raw_decode(out[out.index("{\n"):])
    assert verified["verified"]
