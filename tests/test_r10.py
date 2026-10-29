"""Round 10: the weekly brief, report packs and the
publication gate.

The brief is assembled from artefacts only, every figure
carries lineage, one wrong figure refuses the brief
wholesale (with the refusal on record), packs export
figures that re-perform with a checksum manifest that
names a tampered file, and nothing renders as published
without a named act — the decision log re-derives
gaplessly from the acts.
"""

import json
import sqlite3

import pytest

from fertilizer_intelligence import brief as brief_engine
from fertilizer_intelligence import brief_rules as pack
from fertilizer_intelligence.modelport import ModelReply

WEEK = "2026-03-29"  # a Sunday inside rabi 2025-26


from rawdb import raw_connect


def _tamper(service, table, key_column, key, mutate):
    conn = raw_connect(service.settings)
    row = conn.execute(
        f"SELECT payload FROM {table} WHERE {key_column} = ?", (key,)
    ).fetchone()
    payload = json.loads(row[0])
    mutate(payload)
    conn.execute(
        f"UPDATE {table} SET payload = ? WHERE {key_column} = ?",
        (json.dumps(payload), key),
    )
    conn.commit()
    conn.close()
    return payload


class CorruptPort:
    """A model port whose draft invents one figure — the
    corrupted intermediate the brief must refuse."""

    profile_name = "corrupt"
    model_name = "corrupt-stub"

    def complete(self, system, prompt):
        return ModelReply(
            text=prompt + "\nTotal estimated demand is 999999.99 t.",
            profile=self.profile_name, model=self.model_name,
            input_tokens=0, output_tokens=0,
        )


# -- the pack's week and scope rules --------------------------------------


def test_week_arithmetic_and_scope_rule():
    assert pack.week_start_for("2026-03-29") == "2026-03-23"
    scope = pack.season_scope_for_month("2026-03")
    assert (scope["crop_year"], scope["season"]) == ("2025-26", "rabi")
    # November belongs to the season it opens: rabi.
    scope = pack.season_scope_for_month("2025-11")
    assert (scope["crop_year"], scope["season"]) == ("2025-26", "rabi")
    scope = pack.season_scope_for_month("2025-08")
    assert (scope["crop_year"], scope["season"]) == ("2025-26", "kharif")
    # The gap month after rabi closes reads the closing season.
    scope = pack.season_scope_for_month("2025-05")
    assert (scope["crop_year"], scope["season"]) == ("2024-25", "rabi")
    assert "closed" in scope["note"]


# -- assembly ----------------------------------------------------------------


def test_brief_assembly_sections_and_lineage(service):
    brief = service.weekly_brief(WEEK, "test desk")
    assert brief["week_start"] == "2026-03-23"
    assert brief["season_scope"]["season"] == "rabi"
    assert [s["key"] for s in brief["sections"]] == pack.SECTION_ORDER
    assert brief["publication"] == {"status": "draft"}
    for section in brief["sections"]:
        for figure in section["figures"]:
            assert figure["artefact_id"], figure
            assert figure["source_as_of"], figure
    demand = brief["sections"][0]
    assert demand["artefact_ids"]
    outlook = service.store.get_outlook(demand["artefact_ids"][0])
    total = next(f for f in demand["figures"]
                 if f["label"].startswith("Total estimated demand"))
    assert total["value"] == outlook["total_tonnes"]
    # The narrative's figures are the brief's figures.
    assert brief["narrative"]["figures"]
    assert service.verify_brief(brief["brief_id"]) == {
        "brief_id": brief["brief_id"], "verified": True, "problems": []}


def test_brief_compute_or_return(service):
    first = service.weekly_brief(WEEK, "test desk")
    second = service.weekly_brief(WEEK, "another desk")
    assert first["brief_id"] == second["brief_id"]
    assert len(service.store.list_weekly_briefs()) == 1


def test_brief_unnamed_assembly_refused(service):
    with pytest.raises(ValueError, match="names who assembled"):
        service.weekly_brief(WEEK, "  ")


def test_share_section_keeps_stale_badges(service):
    brief = service.weekly_brief(WEEK, "test desk")
    shares = next(s for s in brief["sections"]
                  if s["key"] == pack.SECTION_SHARES)
    assert shares["figures"]
    # R6's discipline survives into the brief. A movement
    # compares full-season readings, whose basis includes
    # stale months: every movement figure is badged stale
    # and the basis is named in the section notes — a
    # full-season change is never presented as current.
    movers = [f for f in shares["figures"] if f["unit"] == "pp"]
    assert movers
    assert all("stale" in f["badges"] for f in movers)
    assert any("full-season" in n and "stale" in n
               for n in shares["notes"])
    # And where a headline reading excludes stale
    # observations, the figure carries the dashboard's
    # badge and the exclusion is named in the notes.
    for figure in shares["figures"]:
        if "stale observations excluded" in figure["badges"]:
            assert any("stale" in n for n in shares["notes"])


# -- wholesale refusal ---------------------------------------------------------


def test_corrupt_draft_refuses_wholesale_and_records(service):
    with pytest.raises(brief_engine.BriefRefused) as caught:
        service.weekly_brief(WEEK, "test desk", port=CorruptPort())
    refusal_id = caught.value.refusal_id
    assert refusal_id
    assert service.store.list_weekly_briefs() == []
    refusals = service.list_brief_refusals(WEEK)
    assert [r["refusal_id"] for r in refusals] == [refusal_id]
    assert any("999999.99" in p or "not in the artefacts"
               in p or "figure" in p
               for p in refusals[0]["problems"])
    # A clean assembly for the same week supersedes the refusal.
    brief = service.weekly_brief(WEEK, "test desk")
    assert brief["supersedes_refusal"] == refusal_id
    assert service.verify_brief(brief["brief_id"])["verified"]


def test_tampered_brief_figure_is_detected(service):
    brief = service.weekly_brief(WEEK, "test desk")

    def mutate(payload):
        payload["sections"][0]["figures"][0]["value"] += 1.0

    _tamper(service, "weekly_briefs", "brief_id",
            brief["brief_id"], mutate)
    result = service.verify_brief(brief["brief_id"])
    assert not result["verified"]
    assert any("do not re-perform" in p or "does not match"
               in p for p in result["problems"])


def test_tampered_source_artefact_refuses_publication(service):
    brief = service.weekly_brief(WEEK, "test desk")
    outlook_id = brief["sections"][0]["artefact_ids"][0]
    # Corrupt the intermediate: the outlook's stored DAP
    # rollup no longer matches its member estimates.
    conn = raw_connect(service.settings)
    row = conn.execute(
        "SELECT product_rollups FROM season_outlooks "
        "WHERE outlook_id = ?", (outlook_id,)).fetchone()
    rollups = json.loads(row[0])
    rollups["DAP"] += 1000.0
    conn.execute(
        "UPDATE season_outlooks SET product_rollups = ? "
        "WHERE outlook_id = ?", (json.dumps(rollups), outlook_id))
    conn.commit()
    conn.close()
    result = service.verify_brief(brief["brief_id"])
    assert not result["verified"]
    assert any("outlook" in p for p in result["problems"])
    with pytest.raises(ValueError, match="cannot be published"):
        service.publish_artefact(
            "weekly_brief", brief["brief_id"], "P. Editor", WEEK)


# -- publication gate ------------------------------------------------------------


def test_publication_flow_and_decision_log(service):
    brief = service.weekly_brief(WEEK, "test desk")
    assert service.publication_state(
        "weekly_brief", brief["brief_id"]) == {"status": "draft"}
    page = service.brief_html(brief["brief_id"])
    assert pack.BADGE_DRAFT in page
    assert pack.BADGE_PUBLISHED not in page.replace(
        pack.BADGE_DRAFT, "")

    with pytest.raises(ValueError, match="names its publisher"):
        service.publish_artefact(
            "weekly_brief", brief["brief_id"], " ", WEEK)
    act = service.publish_artefact(
        "weekly_brief", brief["brief_id"], "P. Editor", "2026-03-30",
        note="week 13 brief")
    assert act["artefact_fingerprint"] == brief["fingerprint"]
    assert act["supersedes"] is None
    state = service.publication_state("weekly_brief", brief["brief_id"])
    assert state["status"] == "published"
    assert state["is_current"] is True
    page = service.brief_html(brief["brief_id"])
    assert pack.BADGE_PUBLISHED in page
    assert "P. Editor" in page

    log = service.decision_log()
    assert len(log) == 1
    assert log[0]["seq"] == 1
    assert log[0]["artefact_id"] == brief["brief_id"]
    assert log[0]["supersedes_artefact_id"] is None
    assert service.verify_decision_log()["verified"]

    # Publishing the season outlook chains a second family.
    outlook_id = brief["sections"][0]["artefact_ids"][0]
    service.publish_artefact(
        "season_outlook", outlook_id, "P. Editor", "2026-03-30")
    log = service.decision_log()
    assert len(log) == 2
    assert {e["family_key"] for e in log} == {
        f"weekly_brief:{WEEK}", "season_outlook:2025-26:rabi"}
    assert service.verify_decision_log()["verified"]


def test_republication_supersedes_within_family(service):
    brief = service.weekly_brief(WEEK, "test desk")
    first = service.publish_artefact(
        "weekly_brief", brief["brief_id"], "P. Editor", "2026-03-30")
    second = service.publish_artefact(
        "weekly_brief", brief["brief_id"], "Q. Editor", "2026-03-31")
    assert second["supersedes"] == first["act_id"]
    log = service.decision_log()
    assert [e["seq"] for e in log] == [1, 2]
    assert log[1]["supersedes_artefact_id"] == brief["brief_id"]
    assert service.verify_decision_log()["verified"]


def test_decision_log_detects_a_broken_chain(service):
    brief = service.weekly_brief(WEEK, "test desk")
    service.publish_artefact(
        "weekly_brief", brief["brief_id"], "P. Editor", "2026-03-30")
    second = service.publish_artefact(
        "weekly_brief", brief["brief_id"], "Q. Editor", "2026-03-31")

    def mutate(payload):
        payload["supersedes"] = None

    _tamper(service, "publication_acts", "act_id",
            second["act_id"], mutate)
    result = service.verify_decision_log()
    assert not result["verified"]
    assert any("chain" in p or "heads" in p for p in result["problems"])


# -- report packs -----------------------------------------------------------------


def test_product_pack_matches_reads_and_checksums(service, tmp_path):
    pack_row = service.export_pack("product", "DAP", "test desk", WEEK)
    assert set(pack_row["tables"]) == {"demand", "supply", "prices"}
    assert pack_row["tables"]["supply"], "DAP has a supply side"
    assert service.verify_pack(pack_row["pack_id"])["verified"]
    out_dir = tmp_path / "dap-pack"
    written = service.write_pack(pack_row["pack_id"], out_dir)
    assert set(written) == {
        "demand.csv", "supply.csv", "prices.csv",
        "appendix.md", "manifest.json"}
    assert service.verify_pack_dir(
        pack_row["pack_id"], out_dir)["verified"]
    # Flip a byte in an exported figure: the manifest names it.
    target = out_dir / "demand.csv"
    data = bytearray(target.read_bytes())
    data[20] = ord("9") if data[20] != ord("9") else ord("1")
    target.write_bytes(bytes(data))
    result = service.verify_pack_dir(pack_row["pack_id"], out_dir)
    assert not result["verified"]
    assert any("demand.csv" in p and "checksum" in p
               for p in result["problems"])


def test_region_pack_matches_reads(service):
    pack_row = service.export_pack("region", "north", "test desk", WEEK)
    assert set(pack_row["tables"]) == {"demand", "shares"}
    districts = {r["district_id"] for r in pack_row["tables"]["demand"]}
    assert districts == {"DST-LUD", "DST-KAR", "DST-LKO"}
    share_rows = pack_row["tables"]["shares"]
    assert {r["product"] for r in share_rows} == {"UREA", "DAP"}
    assert service.verify_pack(pack_row["pack_id"])["verified"]
    # Export figures match the reads exactly.
    estimate = service.estimate_demand(
        "DST-LUD", "DAP", "2025-26", "rabi", WEEK)
    row = next(r for r in pack_row["tables"]["demand"]
               if r["district_id"] == "DST-LUD"
               and r["product"] == "DAP")
    assert row["total_tonnes"] == estimate["total_tonnes"]
    assert row["estimate_id"] == estimate["estimate_id"]


def test_pack_tamper_is_detected(service):
    pack_row = service.export_pack("product", "UREA", "test desk", WEEK)

    def mutate(payload):
        payload["tables"]["demand"][0]["total_tonnes"] += 5.0

    _tamper(service, "export_packs", "pack_id",
            pack_row["pack_id"], mutate)
    result = service.verify_pack(pack_row["pack_id"])
    assert not result["verified"]


def test_pack_refusals(service):
    with pytest.raises(ValueError, match="not tracked"):
        service.export_pack("product", "WIDGET", "test desk", WEEK)
    with pytest.raises(ValueError, match="no tracked district"):
        service.export_pack("region", "nowhere", "test desk", WEEK)
    with pytest.raises(ValueError, match="names who exported"):
        service.export_pack("product", "DAP", " ", WEEK)


# -- surfaces ------------------------------------------------------------------


def test_api_and_cli_surfaces(service, settings, tmp_path, capsys):
    import json as _json

    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app
    from fertilizer_intelligence.cli import main as cli_main

    app = create_app(settings)
    with TestClient(app) as client:
        made = client.post("/briefs", json={
            "week_ending": WEEK, "assembled_by": "api tester"})
        assert made.status_code == 200, made.text
        brief = made.json()
        assert brief["publication"]["status"] == "draft"
        assert client.get(
            f"/briefs/{brief['brief_id']}/verify"
        ).json()["verified"] is True
        page = client.get(f"/briefs/{brief['brief_id']}/html")
        assert page.status_code == 200
        assert pack.BADGE_PUBLISHED not in page.text.replace(
            pack.BADGE_DRAFT, "")
        refused = client.post("/briefs", json={
            "week_ending": WEEK, "assembled_by": " "})
        assert refused.status_code == 422
        act = client.post("/publications", json={
            "artefact_kind": "weekly_brief",
            "artefact_id": brief["brief_id"],
            "published_by": "api publisher",
            "published_at": "2026-03-30"})
        assert act.status_code == 200, act.text
        log = client.get("/publications")
        assert [e["act_id"] for e in log.json()] == [
            act.json()["act_id"]]
        assert client.get(
            "/publications/verify").json()["verified"] is True
        page = client.get(f"/briefs/{brief['brief_id']}/html")
        assert pack.BADGE_PUBLISHED in page.text
        made_pack = client.post("/packs", json={
            "pack_kind": "product", "pack_key": "DAP",
            "exported_by": "api tester", "as_of": WEEK})
        assert made_pack.status_code == 200, made_pack.text
        pack_row = made_pack.json()
        assert client.get(
            f"/packs/{pack_row['pack_id']}/verify"
        ).json()["verified"] is True
        files = client.get(f"/packs/{pack_row['pack_id']}/files")
        assert set(files.json()) >= {"demand.csv", "manifest.json"}

    def loads(out: str):
        starts = [i for i in (out.find("{\n"), out.find("[\n"))
                  if i >= 0]
        return _json.loads(out[min(starts):])

    db = tmp_path / "cli.db"
    common = ["--db", str(db), "--migrations",
              str(settings.migrations_dir)]
    assert cli_main(common + [
        "brief", "--week-ending", WEEK, "--by", "cli tester"]) == 0
    brief = loads(capsys.readouterr().out)
    assert cli_main(common + [
        "verify-brief", brief["brief_id"]]) == 0
    assert loads(capsys.readouterr().out)["verified"] is True
    assert cli_main(common + [
        "publish", "--kind", "weekly_brief",
        "--artefact", brief["brief_id"], "--by", "cli publisher",
        "--at", "2026-03-30"]) == 0
    capsys.readouterr()
    assert cli_main(common + ["decision-log"]) == 0
    assert len(loads(capsys.readouterr().out)) == 1
    assert cli_main(common + ["verify-decision-log"]) == 0
    assert loads(capsys.readouterr().out)["verified"] is True
    assert cli_main(common + ["get-brief", "NOPE"]) == 2


# -- hypothetical discipline -------------------------------------------------------


def test_brief_carries_no_unadopted_scenario_figures(service):
    fork = service.create_scenario(
        "demand_estimate",
        {"district_id": "DST-LUD", "product": "DAP",
         "crop_year": "2025-26", "season": "rabi"},
        [{"lever": "monsoon_deviation_shift", "value": -10}],
        "test desk", name="unadopted fork", as_of=WEEK)
    brief = service.weekly_brief(WEEK, "test desk")
    planning = next(s for s in brief["sections"]
                    if s["key"] == pack.SECTION_PLANNING)
    assert planning["figures"] == []
    assert fork["fork_id"] not in json.dumps(brief["sections"])
    # Once adopted by a named planner, the planning state shows.
    options = service.build_planning_options(
        fork["base_artefact_id"], [fork["fork_id"]], "test desk")
    service.adopt_option(options["options_id"], fork["fork_id"],
                         "T. Planner", WEEK)
    brief2 = service.weekly_brief("2026-04-05", "test desk")
    planning2 = next(s for s in brief2["sections"]
                     if s["key"] == pack.SECTION_PLANNING)
    assert [f["value"] for f in planning2["figures"]] == [fork["fork_id"]]
    assert service.verify_brief(brief2["brief_id"])["verified"]
