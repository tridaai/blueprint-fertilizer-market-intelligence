"""Round 15: roles, approvals, collaboration — regional
role scopes with existence hiding (a regional reader's
district list holds only their region, an out-of-scope
competitor artefact reads exactly as absent, a viewer
is refused the competitor surface), the access audit
log (every guarded decision entered, export entries
reconciling one-to-one with the packs, a tampered
decision named), annotations pinned to exact artefact
versions and flagged — never moved — when a successor
takes the head, follow-up tasks whose state is a fold
of named acts (a closed fold refuses further acts, a
close speaks the pack's vocabulary), and the
publication review queue (membership is the
publication fold at its date, outlook diffs list
exactly the cells whose estimates superseded against
the published head, a pending artefact that does not
verify refuses the whole queue, and publishing from
the queue binds exactly the reviewed fingerprint).
"""

import json

import pytest

from fertilizer_intelligence import notes as notes_engine
from fertilizer_intelligence.review import ReviewRefused

from rawdb import raw_connect

AS_OF = "2026-04-24"
DESK = "test desk"
YEAR = "2025-26"
WEEK = "2026-03-29"  # a Sunday inside rabi 2025-26


# ---------------------------------------------------------------------------
# Access scopes (F21-AS1)
# ---------------------------------------------------------------------------


def test_regional_district_list_is_filtered_to_the_region(service):
    districts = service.store.list_districts()
    north = [d for d in districts if d["region"] == "north"]
    scoped = service.scoped_districts("D. Verma")
    assert [d["district_id"] for d in scoped] == \
        [d["district_id"] for d in north]
    # No other region is named, counted or hinted at.
    assert {d["region"] for d in scoped} == {"north"}
    assert len(scoped) < len(districts)
    # Strategy enumerates the whole register; an
    # unregistered name resolves to a viewer and still
    # enumerates districts (the list is a public
    # register — the scope bites on competitor reads).
    assert len(service.scoped_districts("A. Rao")) == len(districts)
    assert service.principal_scope("D. Verma")["role"] == "regional"
    assert service.principal_scope("Nobody Known")["role"] == "viewer"
    assert service.principal_scope("Nobody Known")["registered"] \
        is False


def test_competitor_reads_hide_out_of_scope_artefacts(service):
    service.build_competitor_observations()
    observations = service.store.list_competitor_observations()
    south = next(o for o in observations if o["region"] == "south")
    north = next(o for o in observations if o["region"] == "north")

    read = service.scoped_competitor_observation(
        "P. Nair", south["observation_id"], AS_OF)
    assert read is not None \
        and read["observation_id"] == south["observation_id"]
    # Out of region: exactly the absence shape, and the
    # same answer a missing id gets.
    assert service.scoped_competitor_observation(
        "P. Nair", north["observation_id"], AS_OF) is None
    assert service.scoped_competitor_observation(
        "P. Nair", "OBS-does-not-exist", AS_OF) is None
    # A viewer is refused the surface; strategy reads all.
    assert service.scoped_competitor_observation(
        "Guest Viewer", south["observation_id"], AS_OF) is None
    assert service.scoped_competitor_observation(
        "A. Rao", north["observation_id"], AS_OF) is not None

    entries = {(e["target"], e["principal"]): e["decision"]
               for e in service.access_log()}
    base = "competitor_observation:"
    assert entries[(base + south["observation_id"], "P. Nair")] \
        == "allowed"
    assert entries[(base + north["observation_id"], "P. Nair")] \
        == "hidden"
    assert entries[(base + south["observation_id"], "Guest Viewer")] \
        == "refused"
    assert service.verify_access_log()["verified"]

    # The list read filters the same way: P. Nair's list
    # holds only south observations.
    listed = service.scoped_competitor_observations(
        "P. Nair", AS_OF)
    assert listed and all(o["region"] == "south" for o in listed)
    assert len(listed) < len(observations)


def test_scoped_market_share_follows_role_remits(service):
    districts = service.store.list_districts()
    north = next(d for d in districts if d["region"] == "north")
    south = next(d for d in districts if d["region"] == "south")

    share = service.scoped_market_share(
        "D. Verma", north["district_id"], "UREA", YEAR,
        "kharif", AS_OF)
    assert share is not None
    assert share["district_id"] == north["district_id"]
    # The south head reads the north share fine; the
    # north head reading the south share reads absence.
    assert service.scoped_market_share(
        "P. Nair", north["district_id"], "UREA", YEAR,
        "kharif", AS_OF) is None
    assert service.scoped_market_share(
        "P. Nair", south["district_id"], "UREA", YEAR,
        "kharif", AS_OF) is not None
    # A product reader's remit is products, not places:
    # the UREA reader reads a south UREA share, and is
    # hidden from MOP anywhere.
    assert service.scoped_market_share(
        "R. Menon", south["district_id"], "UREA", YEAR,
        "kharif", AS_OF) is not None
    assert service.scoped_market_share(
        "R. Menon", south["district_id"], "MOP", YEAR,
        "kharif", AS_OF) is None
    assert service.verify_access_log()["verified"]


def test_export_entries_reconcile_one_to_one(service, settings):
    first = service.export_pack("product", "UREA", DESK, AS_OF)
    second = service.export_pack("region", "south", DESK, AS_OF)
    # A repeated export of the same pack is the same
    # pack and the same entry — never a second entry.
    assert service.export_pack(
        "product", "UREA", DESK, AS_OF)["pack_id"] \
        == first["pack_id"]
    entries = [e for e in service.access_log()
               if e["surface"] == "export_pack"]
    assert {e["target"] for e in entries} == \
        {first["pack_id"], second["pack_id"]}
    assert service.verify_access_log() == {
        "entries": len(service.access_log()),
        "verified": True, "problems": []}

    # Tamper: rewrite one entry's recorded decision —
    # the verifier re-decides and names it.
    conn = raw_connect(settings)
    row = conn.execute(
        "SELECT payload FROM access_entries WHERE entry_id = ?",
        (entries[0]["entry_id"],)).fetchone()
    payload = json.loads(row[0])
    payload["decision"] = "hidden"
    conn.execute(
        "UPDATE access_entries SET payload = ? WHERE entry_id = ?",
        (json.dumps(payload), entries[0]["entry_id"]))
    conn.commit()
    conn.close()
    result = service.verify_access_log()
    assert not result["verified"]
    assert any(entries[0]["entry_id"] in p
               for p in result["problems"])


# ---------------------------------------------------------------------------
# Annotations & follow-ups (F21-CA2)
# ---------------------------------------------------------------------------


def _insert_estimate(store, estimate_id, district_id, total,
                     supersedes=None, year="2099-00"):
    store.insert_estimate({
        "estimate_id": estimate_id, "district_id": district_id,
        "product": "UREA", "crop_year": year, "season": "kharif",
        "status": "complete", "base_tonnes": total,
        "total_tonnes": total, "missing_drivers": [],
        "rules_version": "2026.10.1",
        "rate_table_version": "2026.10.1",
        "fact_fingerprint": f"fixture-{estimate_id}",
        "as_of": "2099-01-01", "supersedes": supersedes,
    }, [])


def test_annotation_flags_superseded_pin_and_never_moves(service):
    districts = service.store.list_districts()
    district_id = districts[0]["district_id"]
    _insert_estimate(service.store, "EST-FIX-OLD", district_id, 100.0)
    _insert_estimate(service.store, "EST-FIX-NEW", district_id, 130.0,
                     supersedes="EST-FIX-OLD")

    pinned = service.annotate(
        "demand_estimate", "EST-FIX-OLD", "P. Nair", AS_OF,
        "Check the successor before quoting this.")
    assert pinned["pinned_to_superseded"] is True
    assert pinned["target_matches_pin"] is True
    current = service.annotate(
        "demand_estimate", "EST-FIX-NEW", "P. Nair", AS_OF,
        "This is the current reading.")
    assert current["pinned_to_superseded"] is False

    # The pin stays on the old version: listing by the
    # new version does not carry the old comment.
    assert [a["annotation_id"] for a in service.list_annotations(
        target_id="EST-FIX-NEW")] == [current["annotation_id"]]
    with pytest.raises(ValueError):
        service.annotate(
            "demand_estimate", "EST-NOPE", "P. Nair", AS_OF, "x")
    with pytest.raises(ValueError):
        service.annotate(
            "season_outlook", "EST-FIX-OLD", "P. Nair", AS_OF, "x")
    assert service.verify_notes()["verified"]


def test_annotation_on_alert_is_never_flagged_superseded(service):
    service.run_price_watch(AS_OF)
    alert = service.list_alerts()[0]
    pinned = service.annotate(
        "price_alert", alert["alert_id"], DESK, AS_OF,
        "Watching this one for the desk.")
    # Alerts fold state; they do not supersede — the
    # pack states the difference.
    assert pinned["pinned_to_superseded"] is False
    assert pinned["target_matches_pin"] is True


def test_followup_state_is_a_fold_of_acts(service, settings):
    gap = service.supply_gap("MOP", YEAR, "kharif", AS_OF)
    task = service.create_followup(
        "supply_gap", gap["gap_id"], "K. Bhatt", "P. Nair",
        AS_OF, "Confirm the berthing window.", due="2026-05-01")
    assert task["state"] == "open"
    assert task["owner"] == "K. Bhatt"

    service.record_followup_act(
        task["task_id"], "assign", "K. Bhatt", "2026-04-25",
        assignee="S. Iyer")
    view = service.get_followup(task["task_id"])
    assert view["state"] == "open"
    assert view["owner"] == "S. Iyer"

    with pytest.raises(ValueError):
        service.record_followup_act(
            task["task_id"], "close", "S. Iyer", "2026-04-26",
            reason="a shrug")
    service.record_followup_act(
        task["task_id"], "complete", "S. Iyer", "2026-04-26",
        note="Window confirmed.")
    view = service.get_followup(task["task_id"])
    assert view["state"] == "completed"
    assert view["acts"] == 2
    # A terminal fold refuses further acts.
    with pytest.raises(notes_engine.FollowupStateError):
        service.record_followup_act(
            task["task_id"], "assign", "S. Iyer", "2026-04-27",
            assignee="K. Bhatt")
    assert service.verify_notes()["verified"]

    # Tamper: an act's actor rewritten under it — the
    # fingerprint no longer matches its fields.
    act = service.store.list_followup_acts(task["task_id"])[0]
    conn = raw_connect(settings)
    row = conn.execute(
        "SELECT payload FROM followup_acts WHERE act_id = ?",
        (act["act_id"],)).fetchone()
    payload = json.loads(row[0])
    payload["actor"] = "Someone Else"
    conn.execute(
        "UPDATE followup_acts SET payload = ? WHERE act_id = ?",
        (json.dumps(payload), act["act_id"]))
    conn.commit()
    conn.close()
    result = service.verify_notes()
    assert not result["verified"]
    assert any(act["act_id"] in p for p in result["problems"])


# ---------------------------------------------------------------------------
# The review queue (F21-OW4) & the decision log (F21-CA1)
# ---------------------------------------------------------------------------


def _insert_outlook(store, outlook_id, estimate_ids, total, rollups,
                    fingerprint, partial=0):
    store.insert_outlook({
        "outlook_id": outlook_id, "crop_year": "2099-00",
        "season": "kharif", "status": "complete",
        "estimate_count": len(estimate_ids),
        "partial_count": partial, "total_tonnes": total,
        "product_rollups": rollups, "estimate_ids": estimate_ids,
        "rules_version": "2026.10.1",
        "fact_fingerprint": fingerprint,
        "as_of": "2099-01-01", "supersedes": None,
    })


def test_review_queue_outlook_diff_is_exact(service):
    districts = service.store.list_districts()
    dist_a, dist_b = districts[0]["district_id"], \
        districts[1]["district_id"]
    _insert_estimate(service.store, "EST-CELL-1", dist_a, 100.0)
    _insert_estimate(service.store, "EST-CELL-2", dist_b, 50.0)
    # A DAP estimate in district A, for the removed cell.
    service.store.insert_estimate({
        "estimate_id": "EST-CELL-3", "district_id": dist_a,
        "product": "DAP", "crop_year": "2099-00",
        "season": "kharif", "status": "complete",
        "base_tonnes": 30.0, "total_tonnes": 30.0,
        "missing_drivers": [], "rules_version": "2026.10.1",
        "rate_table_version": "2026.10.1",
        "fact_fingerprint": "fixture-EST-CELL-3",
        "as_of": "2099-01-01", "supersedes": None,
    }, [])
    _insert_outlook(
        service.store, "OUT-FIX-PUBLISHED",
        ["EST-CELL-1", "EST-CELL-2", "EST-CELL-3"], 180.0,
        {"UREA": 150.0, "DAP": 30.0}, "fixture-out-published")
    service.publish_artefact(
        "season_outlook", "OUT-FIX-PUBLISHED", "A. Rao",
        "2099-02-01")

    _insert_estimate(service.store, "EST-CELL-1B", dist_a, 120.0)
    service.store.insert_estimate({
        "estimate_id": "EST-CELL-4", "district_id": dist_b,
        "product": "DAP", "crop_year": "2099-00",
        "season": "kharif", "status": "partial",
        "base_tonnes": 40.0, "total_tonnes": 40.0,
        "missing_drivers": ["soil_health"],
        "rules_version": "2026.10.1",
        "rate_table_version": "2026.10.1",
        "fact_fingerprint": "fixture-EST-CELL-4",
        "as_of": "2099-01-01", "supersedes": None,
    }, [])
    _insert_outlook(
        service.store, "OUT-FIX-PENDING",
        ["EST-CELL-1B", "EST-CELL-2", "EST-CELL-4"], 210.0,
        {"UREA": 170.0, "DAP": 40.0}, "fixture-out-pending",
        partial=1)

    queue = service.publication_review_queue(DESK, "2099-03-01")
    items = {i["artefact_id"]: i for i in queue["items"]}
    # The published outlook is not in its own queue.
    assert "OUT-FIX-PUBLISHED" not in items
    item = items["OUT-FIX-PENDING"]
    assert item["reviewed_fingerprint"] == "fixture-out-pending"
    summary = item["driver_summary"]
    assert summary["total_tonnes"] == 210.0
    assert summary["partial_districts"] == [dist_b]
    assert summary["top_cells"][0] == {
        "district_id": dist_a, "product": "UREA",
        "total_tonnes": 120.0}
    diff = item["diff"]
    assert diff["basis"] == "published_head"
    assert diff["published_outlook_id"] == "OUT-FIX-PUBLISHED"
    assert diff["changed_cells"] == [{
        "district_id": dist_a, "product": "UREA",
        "old_estimate_id": "EST-CELL-1",
        "new_estimate_id": "EST-CELL-1B",
        "old_tonnes": 100.0, "new_tonnes": 120.0}]
    assert diff["added_cells"] == [{
        "district_id": dist_b, "product": "DAP",
        "new_estimate_id": "EST-CELL-4", "new_tonnes": 40.0}]
    assert diff["removed_cells"] == [{
        "district_id": dist_a, "product": "DAP",
        "old_estimate_id": "EST-CELL-3", "old_tonnes": 30.0}]
    assert service.verify_review_queue(queue["queue_id"])[
        "verified"]

    # Publishing from the queue binds exactly the
    # reviewed fingerprint; the decision log carries
    # the act and re-derives gaplessly (F21-CA1).
    act = service.publish_artefact(
        "season_outlook", "OUT-FIX-PENDING", "A. Rao",
        "2099-03-02", note="From the review queue.")
    assert act["artefact_fingerprint"] == \
        item["reviewed_fingerprint"]
    log = service.decision_log()
    assert [e["artefact_id"] for e in log] == [
        "OUT-FIX-PUBLISHED", "OUT-FIX-PENDING"]
    assert log[1]["supersedes_artefact_id"] == "OUT-FIX-PUBLISHED"
    assert service.verify_decision_log()["verified"]
    # And the published outlook leaves the next queue.
    queue2 = service.publication_review_queue(DESK, "2099-03-03")
    assert "OUT-FIX-PENDING" not in {
        i["artefact_id"] for i in queue2["items"]}


def test_review_queue_refuses_an_unverifiable_pending(service):
    _insert_outlook(
        service.store, "OUT-FIX-BROKEN", [], 999.0,
        {"UREA": 1.0}, "fixture-out-broken")
    with pytest.raises(ReviewRefused) as refused:
        service.publication_review_queue(DESK, "2099-03-01")
    refusals = service.list_review_refusals()
    assert [r["refusal_id"] for r in refusals] == \
        [refused.value.refusal_id]
    assert service.list_review_queues() == []


def test_review_queue_holds_draft_briefs(service):
    brief = service.weekly_brief(WEEK, DESK)
    queue = service.publication_review_queue(DESK, AS_OF)
    items = {i["artefact_id"]: i for i in queue["items"]}
    item = items[brief["brief_id"]]
    assert item["artefact_kind"] == "weekly_brief"
    assert item["reviewed_fingerprint"] == brief["fingerprint"]
    assert item["diff"]["basis"] == "first_publication"
    assert item["driver_summary"]["sections"]
    assert service.verify_review_queue(queue["queue_id"])[
        "verified"]
    service.publish_artefact(
        "weekly_brief", brief["brief_id"], "A. Rao", "2026-04-25")
    queue2 = service.publication_review_queue(DESK, "2026-04-26")
    assert brief["brief_id"] not in {
        i["artefact_id"] for i in queue2["items"]}


def test_review_queue_tamper_is_named(service, settings):
    service.weekly_brief(WEEK, DESK)
    queue = service.publication_review_queue(DESK, AS_OF)
    conn = raw_connect(settings)
    row = conn.execute(
        "SELECT payload FROM review_queues WHERE queue_id = ?",
        (queue["queue_id"],)).fetchone()
    payload = json.loads(row[0])
    payload["items"] = []
    conn.execute(
        "UPDATE review_queues SET payload = ? WHERE queue_id = ?",
        (json.dumps(payload), queue["queue_id"]))
    conn.commit()
    conn.close()
    result = service.verify_review_queue(queue["queue_id"])
    assert not result["verified"]
    assert result["problems"]


# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------


def test_api_and_cli_surfaces(service, settings, tmp_path, capsys):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        scope = client.get("/principals/D.%20Verma").json()
        assert scope["role"] == "regional"
        scoped = client.get(
            "/scoped/districts",
            params={"principal": "D. Verma"}).json()
        assert scoped and all(
            d["region"] == "north" for d in scoped)

        service.build_competitor_observations()
        observations = service.store.list_competitor_observations()
        north = next(o for o in observations
                     if o["region"] == "north")
        # Out of scope over HTTP is the same 404 as absent.
        resp = client.get(
            f"/scoped/competitor-observations/"
            f"{north['observation_id']}",
            params={"principal": "P. Nair", "at": AS_OF})
        assert resp.status_code == 404
        resp = client.get(
            "/scoped/competitor-observations/OBS-nope",
            params={"principal": "P. Nair", "at": AS_OF})
        assert resp.status_code == 404
        resp = client.get(
            f"/scoped/competitor-observations/"
            f"{north['observation_id']}",
            params={"principal": "A. Rao", "at": AS_OF})
        assert resp.status_code == 200

        log = client.get("/access-log").json()
        assert log and log[0]["seq"] == 1
        assert client.get("/access-log/verify").json()["verified"]

        gap = service.supply_gap("MOP", YEAR, "kharif", AS_OF)
        resp = client.post("/annotations", json={
            "target_kind": "supply_gap",
            "target_id": gap["gap_id"], "author": "P. Nair",
            "at": AS_OF, "text": "Chase the berthing window."})
        assert resp.status_code == 200
        annotation = resp.json()
        assert annotation["pinned_to_superseded"] is False
        listed = client.get(
            "/annotations",
            params={"target_id": gap["gap_id"]}).json()
        assert [a["annotation_id"] for a in listed] == \
            [annotation["annotation_id"]]

        resp = client.post("/followups", json={
            "target_kind": "supply_gap",
            "target_id": gap["gap_id"], "assignee": "K. Bhatt",
            "created_by": "P. Nair", "at": AS_OF,
            "text": "Confirm the window.", "due": "2026-05-01"})
        assert resp.status_code == 200
        task = resp.json()
        resp = client.post(
            f"/followups/{task['task_id']}/acts", json={
                "act": "complete", "actor": "K. Bhatt",
                "at": "2026-04-26", "note": "Confirmed."})
        assert resp.status_code == 200
        view = client.get(f"/followups/{task['task_id']}").json()
        assert view["state"] == "completed"
        assert client.get("/notes/verify").json()["verified"]

        resp = client.post("/review-queues", json={
            "struck_by": "api desk", "as_of": AS_OF})
        assert resp.status_code == 200
        queue = resp.json()
        verified = client.get(
            f"/review-queues/{queue['queue_id']}/verify").json()
        assert verified["verified"]
        assert client.get("/review-queues/RVQ-nope").status_code \
            == 404

    from fertilizer_intelligence.cli import main as cli_main

    base = ["--db", str(tmp_path / "cli-r15.db"),
            "--migrations", "migrations"]
    rc = cli_main(base + ["principal", "P. Nair"])
    assert rc == 0
    out = capsys.readouterr().out
    principal, _ = json.JSONDecoder().raw_decode(
        out[out.index("{\n"):])
    assert principal["regions"] == ["south"]

    rc = cli_main(base + [
        "review-queue", "--by", "cli desk", "--as-of", AS_OF])
    assert rc == 0
    out = capsys.readouterr().out
    queue_cli, _ = json.JSONDecoder().raw_decode(
        out[out.index("{\n"):])
    rc = cli_main(base + [
        "verify-review-queue", queue_cli["queue_id"]])
    assert rc == 0
    out = capsys.readouterr().out
    verified, _ = json.JSONDecoder().raw_decode(
        out[out.index("{\n"):])
    assert verified["verified"]

    rc = cli_main(base + ["verify-access-log"])
    assert rc == 0
    rc = cli_main(base + ["verify-notes"])
    assert rc == 0
