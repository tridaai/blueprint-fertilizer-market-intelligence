"""Round 14: regional rollups, territory packs & season
readiness — the rollup identity proven by hand (a region
total is the sum of its named member estimates, a missing
district is named and never a silent zero, a partial member
makes the rollup partial and is named on its face), the gap
line carried by reference to the head gap artefact with its
demand cross-checked against the rollup's own total, the
territory pack's figures exactly the rollup's (and its
manifest naming a tampered file), readiness scored from
artefacts — an unpublished outlook blocks even when the plan
is struck after the outlook exists, publishing flips exactly
that line, an unowned short gap blocks until an assign act
lands, the cover line names the short product with its
figures, field coverage flips when a confirmed report lands
— and a hand-built fixture region reading fully ready."""

import json

import pytest

from fertilizer_intelligence import readiness as readiness_engine
from fertilizer_intelligence import rollups as rollup_engine

from rawdb import raw_connect

AS_OF = "2026-03-01"
DESK = "test desk"
YEAR = "2025-26"


def _insert_estimate(store, estimate_id, district_id, product, total,
                     status="complete", missing=None, year="2099-00",
                     season="kharif"):
    store.insert_estimate({
        "estimate_id": estimate_id, "district_id": district_id,
        "product": product, "crop_year": year, "season": season,
        "status": status, "base_tonnes": total,
        "total_tonnes": total, "missing_drivers": missing or [],
        "rules_version": "2026.10.1",
        "rate_table_version": "2026.10.1",
        "fact_fingerprint": f"fixture-{estimate_id}",
        "as_of": "2099-01-01", "supersedes": None,
    }, [])


def _insert_outlook(store, outlook_id, estimate_ids, total, rollups,
                    year="2099-00", season="kharif"):
    store.insert_outlook({
        "outlook_id": outlook_id, "crop_year": year, "season": season,
        "status": "complete", "estimate_count": len(estimate_ids),
        "partial_count": 0, "total_tonnes": total,
        "product_rollups": rollups, "estimate_ids": estimate_ids,
        "rules_version": "2026.10.1", "fact_fingerprint": "fixture-out",
        "as_of": "2099-01-01", "supersedes": None,
    })


def _insert_gap(store, gap_id, product, demand, band, gap_tonnes,
                outlook_id, programme=0.0, year="2099-00",
                season="kharif"):
    store.insert_supply_gap({
        "gap_id": gap_id, "product": product, "crop_year": year,
        "season": season, "as_of": "2099-01-01",
        "as_of_month": "2099-01",
        "demand_tonnes": demand, "demand_outlook_id": outlook_id,
        "opening_stock_tonnes": 0.0,
        "production_actual_tonnes": 0.0, "arrivals_tonnes": 0.0,
        "scheduled_imports_tonnes": 0.0, "due_imports_tonnes": 0.0,
        "credited_imports_tonnes": 0.0, "slipped_tonnes": 0.0,
        "programme_cover_pct": programme,
        "available_tonnes": demand - gap_tonnes,
        "gap_tonnes": gap_tonnes,
        "gap_pct_of_demand": round(gap_tonnes / demand * 100, 4)
        if demand else 0.0,
        "band": band, "band_basis": "import_programme_cover",
        "position_months": [], "uncovered_months": [],
        "rules_version": "2026.10.1",
        "fact_fingerprint": f"fixture-{gap_id}", "supersedes": None,
    })


def _district_names(store):
    return {d["district_id"]: d for d in store.list_districts()}


# -- DR3: the rollup identity, proven by hand ------------------------


def _fixture_members(service):
    """Three UREA members over a fixture season: Ludhiana
    complete, Karnal partial, Guntur complete — every other
    district missing for UREA, every district missing for
    the other five products."""
    store = service.store
    _insert_estimate(store, "EST-FIX-LUD", "DST-LUD", "UREA", 1000.0)
    _insert_estimate(
        store, "EST-FIX-KAR", "DST-KAR", "UREA", 500.0,
        status="partial", missing=["soil_moisture_index"])
    _insert_estimate(store, "EST-FIX-GUN", "DST-GUN", "UREA", 250.0)
    _insert_outlook(
        store, "OUT-FIX-2099",
        ["EST-FIX-LUD", "EST-FIX-KAR", "EST-FIX-GUN"], 1750.0,
        {"UREA": 1750.0})


def _build_fixture_rollup(service):
    return rollup_engine.build_rollup(
        service.store, "2099-00", "kharif", "2099-02-01", DESK)


def _region(block, region):
    return next(r for r in block["regions"] if r["region"] == region)


def test_rollup_identity_hand_computed(service):
    _fixture_members(service)
    rollup = _build_fixture_rollup(service)
    urea = next(b for b in rollup.products if b["product"] == "UREA")
    north = _region(urea, "north")
    assert north["total_tonnes"] == 1500.0  # 1000 + 500, by hand
    assert north["estimate_count"] == 2
    assert north["status"] == "partial"
    assert north["partial_districts"] == ["Karnal"]
    assert north["missing_districts"] == ["Lucknow"]
    north_members = [m for m in urea["members"]
                     if m["region"] == "north"]
    assert [m["district_id"] for m in north_members] == [
        "DST-KAR", "DST-LUD"]
    assert [m["status"] for m in north_members] == [
        "partial", "complete"]
    south = _region(urea, "south")
    assert south["total_tonnes"] == 250.0
    assert south["missing_districts"] == ["Belagavi", "Warangal"]
    east = _region(urea, "east")
    assert east["total_tonnes"] == 0.0 and east["estimate_count"] == 0
    assert east["status"] == "partial"  # missing, never a silent zero
    assert east["missing_districts"] == ["Bardhaman", "Patna"]
    assert urea["national_tonnes"] == 1750.0
    assert urea["status"] == "partial"
    assert rollup.national_total_tonnes == 1750.0
    assert rollup.status == "partial"
    assert rollup.partial_districts == ["Karnal"]
    # the rollup face names every district missing for at
    # least one product — for the five unestimated products
    # that is all twelve districts, Ludhiana included
    assert set(rollup.missing_districts) == {
        "Ludhiana", "Karnal", "Lucknow", "Kota", "Rajkot",
        "Indore", "Nagpur", "Guntur", "Warangal", "Belagavi",
        "Patna", "Bardhaman"}
    assert rollup.outlook_id == "OUT-FIX-2099"
    member_ids = sorted(m["estimate_id"] for b in rollup.products
                        for m in b["members"])
    assert member_ids == [
        "EST-FIX-GUN", "EST-FIX-KAR", "EST-FIX-LUD"]
    assert rollup_engine.verify_rollup(
        service.store, rollup.model_dump()) == []


def test_rollup_gap_line_carried_by_reference(service):
    store = service.store
    _fixture_members(service)
    _insert_gap(store, "GAP-FIX-UREA", "UREA", 1750.0, "watch",
                -120.0, "OUT-FIX-2099", programme=55.0)
    rollup = _build_fixture_rollup(service)
    urea = next(b for b in rollup.products if b["product"] == "UREA")
    gap = urea["gap"]
    assert gap["gap_id"] == "GAP-FIX-UREA"
    assert gap["gap_tonnes"] == -120.0
    assert gap["programme_cover_pct"] == 55.0
    # the demand the gap was struck against IS this rollup's
    # national total, so the cross-check can be re-performed
    assert gap["demand_basis"] == "this_outlook"
    assert gap["demand_tonnes"] == urea["national_tonnes"]
    dap = next(b for b in rollup.products if b["product"] == "DAP")
    assert dap["gap"] is None  # no supply side, no line invented
    assert rollup_engine.verify_rollup(
        store, rollup.model_dump()) == []
    # an earlier-outlook gap: the figures still ride by
    # reference, the basis is named, and no cross-check is
    # claimed against this rollup's total
    _insert_gap(store, "GAP-FIX-MOP", "MOP", 900.0, "short",
                300.0, "OUT-OLDER-ELSEWHERE")
    rollup = _build_fixture_rollup(service)
    mop = next(b for b in rollup.products if b["product"] == "MOP")
    assert mop["gap"]["demand_basis"] == "earlier_outlook"
    assert mop["gap"]["demand_outlook_id"] == "OUT-OLDER-ELSEWHERE"
    assert rollup_engine.verify_rollup(
        store, rollup.model_dump()) == []


def test_rollup_service_flow_verifies_and_reperforms(service):
    rollup = service.regional_rollup(YEAR, "kharif", DESK, AS_OF)
    outlook = service.get_outlook(YEAR, "kharif")
    # the national total is the outlook's own total — the
    # rollup is a decomposition of it, never a rival figure
    assert rollup["national_total_tonnes"] == outlook["total_tonnes"]
    for block in rollup["products"]:
        assert block["national_tonnes"] == \
            outlook["product_rollups"][block["product"]]
        region_sum = sum(
            r["total_tonnes"] for r in block["regions"])
        assert region_sum == pytest.approx(block["national_tonnes"],
                                           abs=1e-6)
    assert rollup["status"] == "complete"
    assert rollup["missing_districts"] == []
    assert service.verify_rollup(rollup["rollup_id"])["verified"]
    again = service.regional_rollup(YEAR, "kharif", DESK, AS_OF)
    assert again["rollup_id"] == rollup["rollup_id"]
    assert again["supersedes"] is None
    with pytest.raises(ValueError):
        service.regional_rollup(YEAR, "kharif", "  ", AS_OF)


def test_rollup_tamper_is_named(service, settings):
    rollup = service.regional_rollup(YEAR, "kharif", DESK, AS_OF)
    raw = raw_connect(settings)
    row = raw.execute(
        "SELECT payload FROM regional_rollups WHERE rollup_id = ?",
        (rollup["rollup_id"],)).fetchone()
    payload = json.loads(row[0])
    target = next(b for b in payload["products"]
                  if b["product"] == "UREA")
    north = next(r for r in target["regions"]
                 if r["region"] == "north")
    north["total_tonnes"] += 1.0
    raw.execute(
        "UPDATE regional_rollups SET payload = ? WHERE rollup_id = ?",
        (json.dumps(payload), rollup["rollup_id"]))
    raw.commit()
    raw.close()
    result = service.verify_rollup(rollup["rollup_id"])
    assert not result["verified"]
    assert any("UREA" in p and "north" in p
               for p in result["problems"])


# -- DR3: territory packs --------------------------------------------


def test_territory_pack_figures_are_the_rollups(service, tmp_path):
    pack = service.export_pack("territory", "south", DESK, AS_OF)
    # the pack renders the rollup for the season in scope at
    # its as-of (March sits in rabi's window) — the figures
    # must be exactly THAT rollup's, named on every row
    named = {row["rollup_id"] for row in pack["tables"]["rollup"]}
    assert len(named) == 1
    rollup = service.get_rollup(named.pop())
    blocks = {b["product"]: b for b in rollup["products"]}
    for row in pack["tables"]["rollup"]:
        if row["level"] == "national":
            assert row["total_tonnes"] == \
                blocks[row["product"]]["national_tonnes"]
            assert row["status"] == blocks[row["product"]]["status"]
        else:
            region = _region(blocks[row["product"]], row["region"])
            assert row["total_tonnes"] == region["total_tonnes"]
            assert row["estimate_count"] == region["estimate_count"]
            assert row["partial_count"] == region["partial_count"]
            assert row["status"] == region["status"]
        assert row["rollup_id"] == rollup["rollup_id"]
    # district rows cover only the pack's own region, and each
    # figure is the member estimate's own figure
    members = {
        m["estimate_id"]: m
        for b in rollup["products"] for m in b["members"]}
    assert {r["region"] for r in pack["tables"]["districts"]} == {
        "south"}
    assert len(pack["tables"]["districts"]) == sum(
        1 for b in rollup["products"] for m in b["members"]
        if m["region"] == "south")
    for row in pack["tables"]["districts"]:
        member = members[row["estimate_id"]]
        assert row["total_tonnes"] == member["total_tonnes"]
        assert row["status"] == member["status"]
    for row in pack["tables"]["gaps"]:
        gap = blocks[row["product"]]["gap"]
        assert row["gap_id"] == gap["gap_id"]
        assert row["gap_tonnes"] == gap["gap_tonnes"]
        assert row["demand_basis"] == gap["demand_basis"]
    assert service.verify_pack(pack["pack_id"])["verified"]
    out = tmp_path / "territory"
    service.write_pack(pack["pack_id"], str(out))
    districts_csv = out / "districts.csv"
    data = bytearray(districts_csv.read_bytes())
    # flip the first digit of the first data row's figure
    start = data.index(b"\n") + 1
    pos = next(i for i in range(start, len(data))
               if chr(data[i]).isdigit())
    data[pos] = ord("9") if data[pos] != ord("9") else ord("1")
    districts_csv.write_bytes(bytes(data))
    result = service.verify_pack_dir(pack["pack_id"], str(out))
    assert not result["verified"]
    assert any("districts.csv" in p for p in result["problems"])


# -- PO3: season readiness --------------------------------------------


def _lines(plan):
    return {line["line"]: line for line in plan["lines"]}


def test_readiness_blocks_then_flips_line_by_line(service):
    service.run_price_watch(AS_OF)
    plan = service.season_readiness("south", YEAR, "kharif", DESK, AS_OF)
    lines = _lines(plan)
    assert not plan["ready"]
    assert plan["blocking_lines"] == [
        "outlook_published", "supply_cover", "open_risks",
        "field_coverage"]
    assert any("no publication act" in b
               for b in lines["outlook_published"]["blockers"])
    assert any("MOP" in b and "short" in b
               for b in lines["supply_cover"]["blockers"])
    assert any("queue item" in b
               for b in lines["open_risks"]["blockers"])
    assert any("Guntur" in b
               for b in lines["field_coverage"]["blockers"])
    assert service.verify_readiness(plan["readiness_id"])["verified"]

    # flip three of the four lines with acts, never by editing
    outlook = service.get_outlook(YEAR, "kharif")
    service.publish_artefact(
        "season_outlook", outlook["outlook_id"], "test publisher",
        "2026-03-02")
    queue = service.gap_queue("2026-03-02")
    mop = next(v for v in queue
               if v["product"] == "MOP" and v["season"] == "kharif")
    service.assign_queue_item(
        mop["item_id"], DESK, "Named Owner", "2026-03-02")
    for alert in service.list_alerts(state="open"):
        service.acknowledge_alert(
            alert["alert_id"], DESK, "working it", "2026-03-02")
    landed = service.sync_field_reports([
        {"submission_id": f"R14-SOUTH-{d}",
         "reporter": "T. Rao (field officer)", "district_id": d,
         "product": "UREA", "signal_type": "demand_signal",
         "direction": "up", "observed_on": "2025-10-20",
         "detail": "Season check visit."}
        for d in ("DST-GUN", "DST-WAR", "DST-BEL")], "2026-03-02")
    assert landed["landed"] == 3
    for view in service.list_field_reports(state="unreviewed"):
        if view["submission_id"].startswith("R14-SOUTH-"):
            service.review_field_report(
                view["report_id"], "confirm", "A. Reviewer",
                "corroborated", "2026-03-02")

    plan2 = service.season_readiness(
        "south", YEAR, "kharif", DESK, "2026-03-05")
    lines2 = _lines(plan2)
    assert lines2["outlook_published"]["status"] == "complete"
    assert lines2["open_risks"]["status"] == "complete"
    assert lines2["field_coverage"]["status"] == "complete"
    # the cover line still blocks, and it is the ONLY blocker —
    # a short position cannot be argued away by the other lines
    assert lines2["supply_cover"]["status"] == "incomplete"
    assert plan2["blocking_lines"] == ["supply_cover"]
    assert not plan2["ready"]
    assert plan2["supersedes"] == plan["readiness_id"]
    assert service.verify_readiness(plan2["readiness_id"])["verified"]
    with pytest.raises(ValueError):
        service.season_readiness("south", YEAR, "kharif", "  ", AS_OF)
    with pytest.raises(ValueError):
        service.season_readiness("nowhere", YEAR, "kharif", DESK, AS_OF)


def test_readiness_fixture_region_reads_ready(service):
    """The hand-built east: published outlook, comfortable
    cover on the only product with a supply side, no alerts,
    no short gaps, a confirmed report in each district."""
    from fertilizer_intelligence import brief as brief_engine

    store = service.store
    _insert_estimate(store, "EST-FIX-PAT", "DST-PAT", "UREA", 1000.0)
    _insert_estimate(store, "EST-FIX-BAR", "DST-BAR", "UREA", 2000.0)
    _insert_outlook(store, "OUT-FIX-EAST",
                    ["EST-FIX-PAT", "EST-FIX-BAR"], 3000.0,
                    {"UREA": 3000.0})
    _insert_gap(store, "GAP-FIX-EAST", "UREA", 3000.0, "comfortable",
                -450.0, "OUT-FIX-EAST")
    # every product with a supply side needs its cover struck
    for product in ("DAP", "NPK_10_26_26", "MOP"):
        _insert_gap(store, f"GAP-FIX-EAST-{product}", product, 100.0,
                    "comfortable", -10.0, "OUT-FIX-EAST")
    outlook = store.get_outlook("OUT-FIX-EAST")
    act = brief_engine.build_publication_act(
        "season_outlook", outlook, "fixture publisher", "2099-01-10",
        None, None)
    store.insert_publication_act(act.model_dump())
    for district_id in ("DST-PAT", "DST-BAR"):
        store.insert_field_report_artefact({
            "report_id": f"FSR-FIX-{district_id}",
            "submission_id": f"FIX-{district_id}",
            "payload_hash": "fixture", "reporter": "Fixture Officer",
            "district_id": district_id, "product": "UREA",
            "signal_type": "demand_signal",
            "signal_kind": "demand_up", "observed_on": "2098-10-20",
            "quantity_tonnes": None, "price_inr_tonne": None,
            "direction": "up", "detail": "fixture visit",
            "photo_ref": None, "crop_year": "2099-00",
            "season": "kharif", "source": "fixture",
            "as_of": "2099-01-05", "conflicts_with": None,
            "submission": {}, "rules_version": "2026.10.1",
        })
        store.insert_field_review_act({
            "act_id": f"FRA-FIX-{district_id}",
            "report_id": f"FSR-FIX-{district_id}", "act": "confirm",
            "actor": "Fixture Reviewer", "reason": "corroborated",
            "note": None, "as_of": "2099-01-06",
        })
    plan = readiness_engine.build_readiness(
        store, "east", "2099-00", "kharif", "2099-02-01", DESK)
    assert plan.ready
    assert plan.blocking_lines == []
    assert all(line["status"] == "complete" for line in plan.lines)
    assert readiness_engine.verify_readiness(
        store, plan.model_dump()) == []


def test_readiness_tamper_is_named(service, settings):
    plan = service.season_readiness("south", YEAR, "kharif", DESK, AS_OF)
    raw = raw_connect(settings)
    row = raw.execute(
        "SELECT payload FROM season_readiness WHERE readiness_id = ?",
        (plan["readiness_id"],)).fetchone()
    payload = json.loads(row[0])
    payload["lines"][0]["status"] = "complete"
    raw.execute(
        "UPDATE season_readiness SET payload = ? "
        "WHERE readiness_id = ?",
        (json.dumps(payload), plan["readiness_id"]))
    raw.commit()
    raw.close()
    result = service.verify_readiness(plan["readiness_id"])
    assert not result["verified"]
    assert any("outlook_published" in p for p in result["problems"])


# -- surfaces ----------------------------------------------------------


def test_api_and_cli_surfaces(service, settings, tmp_path, capsys):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        resp = client.post("/rollups", json={
            "crop_year": YEAR, "season": "kharif",
            "built_by": "api desk", "as_of": AS_OF})
        assert resp.status_code == 200
        rollup = resp.json()
        listed = client.get("/rollups", params={
            "crop_year": YEAR, "season": "kharif"}).json()
        assert [r["rollup_id"] for r in listed] == [rollup["rollup_id"]]
        verified = client.get(
            f"/rollups/{rollup['rollup_id']}/verify").json()
        assert verified["verified"]
        assert client.get("/rollups/ROL-nope").status_code == 404

        resp = client.post("/readiness", json={
            "region": "south", "crop_year": YEAR, "season": "kharif",
            "struck_by": "api desk", "as_of": AS_OF})
        assert resp.status_code == 200
        plan = resp.json()
        assert plan["ready"] is False
        assert "outlook_published" in plan["blocking_lines"]
        verified = client.get(
            f"/readiness/{plan['readiness_id']}/verify").json()
        assert verified["verified"]
        assert client.get("/readiness/RDY-nope").status_code == 404

        resp = client.post("/packs", json={
            "pack_kind": "territory", "pack_key": "south",
            "exported_by": "api desk", "as_of": AS_OF})
        assert resp.status_code == 200
        assert resp.json()["pack_kind"] == "territory"

    from fertilizer_intelligence.cli import main as cli_main

    base = ["--db", str(tmp_path / "cli-r14.db"),
            "--migrations", "migrations"]
    rc = cli_main(base + [
        "rollup", "--crop-year", YEAR, "--season", "kharif",
        "--by", "cli desk", "--as-of", AS_OF])
    assert rc == 0
    out = capsys.readouterr().out
    rollup_cli, _ = json.JSONDecoder().raw_decode(out[out.index("{\n"):])
    rc = cli_main(base + ["verify-rollup", rollup_cli["rollup_id"]])
    assert rc == 0
    out = capsys.readouterr().out
    verified, _ = json.JSONDecoder().raw_decode(out[out.index("{\n"):])
    assert verified["verified"]
    rc = cli_main(base + [
        "readiness", "--region", "south", "--crop-year", YEAR,
        "--season", "kharif", "--by", "cli desk", "--as-of", AS_OF])
    assert rc == 0
    out = capsys.readouterr().out
    plan_cli, _ = json.JSONDecoder().raw_decode(out[out.index("{\n"):])
    assert plan_cli["blocking_lines"]
    rc = cli_main(base + [
        "pack", "--kind", "territory", "--key", "south",
        "--by", "cli desk", "--as-of", AS_OF])
    assert rc == 0
