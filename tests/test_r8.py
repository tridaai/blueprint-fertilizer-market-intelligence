"""Round 8 acceptance: ask-in-plain-language dashboards.

The graded claims of this round:

- A plain-language question parses into a GOVERNED dashboard
  spec: panels from the pack's vocabulary, each bound to a
  stated artefact query, with scope inherited across clauses
  and pack defaults recorded when applied.
- A question part that maps to no artefact family becomes a
  GAP panel naming the data it would need — never dropped,
  never improvised, and a gap panel carries no figures.
- Hosted-profile proposals are validated against the
  governed schema: an off-vocabulary proposal is refused,
  the refusal is recorded on the spec AND rendered as a gap;
  an unparseable reply refuses the question outright.
- The spec is an insert-only artefact, attributed to a
  named asker, compute-or-return on identical content.
- Assembly renders only from artefacts: every figure
  carries its artefact id and source as-of; a figure whose
  source superseded since the ask renders from the current
  head with the supersession noted; re-assembly diffs
  against the previous assembly.
- Verification is whole-dashboard: a tampered figure or a
  tampered page fails verification naming the panel and
  figure, and a figure that cannot re-perform at assembly
  time refuses the dashboard — nothing partial is stored.
- Role defaults are specs built from the pack's stated
  data, not code branches; an unknown role is refused.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from fertilizer_intelligence import dashboard as dash
from fertilizer_intelligence.dashboard import DashboardRefused, QuestionRefused

MIXED_QUESTION = (
    "How is DAP looking in Ludhiana this kharif, what's our share, "
    "and what's the monsoon outlook for groundnut in Anantapur?"
)
AS_OF = "2026-03-31"


from rawdb import raw_connect


class _StubPort:
    """A hosted-profile stand-in: returns a fixed reply text."""

    profile = "anthropic"
    model = "stub-model"

    def __init__(self, text: str):
        self._text = text

    def complete(self, prompt, system=None):
        return SimpleNamespace(text=self._text)


# -- the parse ---------------------------------------------------------------


def test_grammar_parse_of_the_mixed_question(service):
    spec = service.ask_question(MIXED_QUESTION, "test desk", AS_OF,
                                name="mixed demo")
    panels = spec["panels"]
    assert [p["kind"] for p in panels] == [
        "demand_estimate", "market_share", "gap"]
    # Scope is inherited: the share clause names nothing but
    # "our share" — district, product, season and crop year
    # come from the clause before it.
    assert panels[1]["scope"] == {
        "district_id": "DST-LUD", "product": "DAP",
        "crop_year": "2025-26", "season": "kharif"}
    assert panels[0]["origin"] == {
        "via": "grammar", "rule": "grammar:demand_estimate"}
    assert panels[1]["origin"]["rule"] == "grammar:market_share"
    # The gap names everything it would need: the unknown
    # district, the crop-vs-product mismatch, and the missing
    # artefact family. It carries no binding and no figures
    # are ever attached to it.
    gap = panels[2]
    needed = gap["scope"]["needed_data"]
    assert "Anantapur" in needed and "not one of the tracked districts" in needed
    assert "groundnut is a crop" in needed
    assert "monsoon outlook is not a computed view" in needed
    assert gap["binding_artefact_ids"] == []
    # Every governed panel resolved a binding at ask time.
    assert panels[0]["binding_artefact_ids"]
    assert panels[1]["binding_artefact_ids"]
    # The crop-year default is recorded, not silent.
    assert any("crop year defaulted" in n for n in spec["parse"]["notes"])


def test_spec_is_attributed_insert_only_and_compute_or_return(service):
    with pytest.raises(ValueError):
        service.ask_question("What is our DAP share in Ludhiana?", "", AS_OF)
    first = service.ask_question(MIXED_QUESTION, "test desk", AS_OF)
    second = service.ask_question(MIXED_QUESTION, "test desk", AS_OF)
    assert first["spec_id"] == second["spec_id"]
    rows = service.store.dashboard_specs()
    assert len(rows) == 1
    assert service.verify_dashboard_spec(first["spec_id"])["verified"]


def test_grammar_defaults_are_stated(service):
    spec = service.ask_question(
        "What's our share of DAP in Ludhiana?", "test desk", AS_OF)
    panel = spec["panels"][0]
    assert panel["kind"] == "market_share"
    assert panel["scope"]["season"] == "kharif"
    assert panel["scope"]["crop_year"] == "2025-26"
    notes = " ".join(spec["parse"]["notes"])
    assert "season defaulted" in notes and "crop year defaulted" in notes


# -- hosted profiles: governed validation ------------------------------------


def test_model_proposals_are_validated_against_the_pack(service):
    good = json.dumps([{
        "kind": "supply_gap",
        "scope": {"product": "DAP", "crop_year": "2025-26",
                  "season": "kharif"},
    }])
    spec = service.ask_question(
        "Will DAP run short?", "test desk", AS_OF,
        port=_StubPort(good))
    assert [p["kind"] for p in spec["panels"]] == ["supply_gap"]
    assert spec["panels"][0]["origin"]["via"] == "model"
    assert spec["parse"]["refusals"] == []

    refused = json.dumps([{"kind": "monsoon_forecast", "scope": {}}])
    spec = service.ask_question(
        "Forecast the monsoon", "test desk", AS_OF,
        port=_StubPort(refused))
    assert [p["kind"] for p in spec["panels"]] == ["gap"]
    assert len(spec["parse"]["refusals"]) == 1
    assert "not in the governed vocabulary" in \
        spec["parse"]["refusals"][0]["reason"]
    assert "refused" in spec["panels"][0]["scope"]["needed_data"]
    assert service.verify_dashboard_spec(spec["spec_id"])["verified"]

    with pytest.raises(QuestionRefused):
        service.ask_question(
            "Anything", "test desk", AS_OF,
            port=_StubPort("I cannot answer in JSON."))


# -- assembly & verification ---------------------------------------------------


def test_assembly_lineage_and_gap_discipline(service):
    spec = service.ask_question(MIXED_QUESTION, "test desk", AS_OF)
    assembly = service.assemble_dashboard(spec["spec_id"], AS_OF)
    assert assembly["diff"] == []
    for panel in assembly["panels"]:
        if panel["kind"] == "gap":
            assert panel["figures"] == []
            continue
        assert panel["figures"], panel["kind"]
        for figure in panel["figures"]:
            assert figure["artefact_id"] in panel["artefact_ids"]
            assert figure["source_as_of"]
    result = service.verify_dashboard(assembly["assembly_id"])
    assert result == {"assembly_id": assembly["assembly_id"],
                      "verified": True, "problems": []}
    page = assembly["html"]
    assert "Anantapur" in page and "cannot be answered" in page
    assert "Visit Trida AI" in page and "View all blueprints" in page
    # Compute-or-return: the same assembly at the same date
    # is the same artefact.
    again = service.assemble_dashboard(spec["spec_id"], AS_OF)
    assert again["assembly_id"] == assembly["assembly_id"]


def test_stale_share_figures_are_badged_never_presented_current(service):
    spec = service.ask_question(
        "What's our share of DAP in Ludhiana this kharif?",
        "test desk", AS_OF)
    assembly = service.assemble_dashboard(spec["spec_id"], AS_OF)
    panel = assembly["panels"][0]
    assert panel["figures"]
    # The R6 discipline at dashboard scale: stale observations
    # are excluded from the headline, the exclusion is named
    # on the panel, and the headline figures carry the badge —
    # no figure is ever badged as itself stale in the headline,
    # and none is presented without the exclusion stated.
    assert all("stale" != b for f in panel["figures"] for b in f["badges"])
    assert any("headline excludes" in n for n in panel["notes"])
    assert all("stale observations excluded" in f["badges"]
               for f in panel["figures"])

    # A product with no observations at all renders no
    # figures — the panel states the status instead of
    # filling the space.
    empty = service.ask_question(
        "What's our share of glyphosate in Ludhiana this kharif?",
        "test desk", AS_OF)
    empty_assembly = service.assemble_dashboard(empty["spec_id"], AS_OF)
    empty_panel = empty_assembly["panels"][0]
    assert empty_panel["figures"] == []
    assert any("no_observations" in n for n in empty_panel["notes"])
    assert service.verify_dashboard(
        empty_assembly["assembly_id"])["verified"]


def test_rerun_after_field_sync_shows_supersession_and_diff(service):
    question = ("What do the field signals say for DAP in Ludhiana "
                "this kharif?")
    spec = service.ask_question(question, "test desk", "2025-10-20",
                                name="field watch")
    first = service.assemble_dashboard(spec["spec_id"], "2025-10-20")
    assert first["panels"][0]["figures"][1]["value"] == 0.0

    service.sync_field_reports([{
        "submission_id": "PHONE-R8-1", "reporter": "T. Rao (field officer)",
        "district_id": "DST-LUD", "product": "DAP",
        "signal_type": "demand_signal", "direction": "up",
        "observed_on": "2025-10-28",
        "detail": "Queues at two dealers; offtake running ahead.",
    }], "2025-11-02")
    second = service.assemble_dashboard(spec["spec_id"], "2025-11-02")
    assert second["supersedes"] == first["assembly_id"]
    panel = second["panels"][0]
    assert any("superseded since the question was asked" in n
               for n in panel["notes"])
    changed = {(e["panel_no"], e["label"]): e
               for e in second["diff"] if e["kind"] == "figure_changed"}
    adjustment = changed[(1, "Field-signal adjustment")]
    assert adjustment["before"] == 0.0 and adjustment["after"] == 1.5
    assert any(e["kind"] == "artefacts_superseded"
               for e in second["diff"])
    assert "What changed since the previous assembly" in second["html"]
    assert service.verify_dashboard(second["assembly_id"])["verified"]


def test_dashboard_refused_when_a_figure_cannot_reperform(
        service, monkeypatch):
    spec = service.ask_question(
        "How is DAP looking in Ludhiana this kharif?", "test desk", AS_OF)
    original = dash.resolve_panel

    def corrupting(svc, panel, as_of):
        resolved = original(svc, panel, as_of)
        if resolved["figures"]:
            resolved["figures"][0]["value"] += 1
        return resolved

    monkeypatch.setattr(dash, "resolve_panel", corrupting)
    with pytest.raises(DashboardRefused):
        service.assemble_dashboard(spec["spec_id"], AS_OF)
    # Nothing partial was stored.
    assert service.store.dashboard_assemblies(spec["spec_id"]) == []


def test_tampered_assembly_is_caught(service, settings):
    spec = service.ask_question(MIXED_QUESTION, "test desk", AS_OF)
    assembly = service.assemble_dashboard(spec["spec_id"], AS_OF)
    raw = raw_connect(settings)
    payload = json.loads(raw.execute(
        "SELECT payload FROM dashboard_assemblies WHERE assembly_id = ?",
        (assembly["assembly_id"],),
    ).fetchone()[0])
    figure = payload["panels"][0]["figures"][0]
    figure["value"] += 1000
    raw.execute(
        "UPDATE dashboard_assemblies SET payload = ? WHERE assembly_id = ?",
        (json.dumps(payload), assembly["assembly_id"]),
    )
    raw.commit()
    result = service.verify_dashboard(assembly["assembly_id"])
    assert not result["verified"]
    assert any("panel 1" in p and figure["label"] in p
               for p in result["problems"])
    figure["value"] -= 1000
    payload["html"] = payload["html"].replace("14,091", "99,999")
    raw.execute(
        "UPDATE dashboard_assemblies SET payload = ? WHERE assembly_id = ?",
        (json.dumps(payload), assembly["assembly_id"]),
    )
    raw.commit()
    raw.close()
    result = service.verify_dashboard(assembly["assembly_id"])
    assert not result["verified"]
    assert any("HTML" in p for p in result["problems"])


# -- role defaults -------------------------------------------------------------


def test_role_defaults_are_pack_specs(service):
    expected = {
        "regional_head": ["watch_board", "supply_gap", "supply_gap",
                          "supply_gap", "market_share"],
        "national_planner": ["season_outlook", "supply_gap", "supply_gap",
                             "policy_events", "watch_board"],
        "leadership": ["season_outlook", "season_outlook", "watch_board",
                       "share_movement"],
    }
    for role, kinds in expected.items():
        spec = service.role_default_dashboard(role, "test desk", AS_OF)
        assert [p["kind"] for p in spec["panels"]] == kinds
        assert all(p["origin"]["rule"] == f"role_default:{role}"
                   for p in spec["panels"])
        assembly = service.assemble_dashboard(spec["spec_id"], AS_OF)
        assert service.verify_dashboard(assembly["assembly_id"])["verified"]
    saved = service.list_dashboard_specs(name="default:leadership")
    assert len(saved) == 1
    with pytest.raises(ValueError):
        service.role_default_dashboard("chief_everything", "test desk", AS_OF)


# -- surfaces ------------------------------------------------------------------


def test_api_and_cli_surfaces(service, settings, tmp_path, capsys):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app
    from fertilizer_intelligence.cli import main as cli_main

    app = create_app(settings)
    with TestClient(app) as client:
        asked = client.post("/dashboards/ask", json={
            "question": MIXED_QUESTION, "asked_by": "api tester",
            "as_of": AS_OF, "name": "api mixed",
        })
        assert asked.status_code == 200, asked.text
        spec = asked.json()
        assert [p["kind"] for p in spec["panels"]] == [
            "demand_estimate", "market_share", "gap"]
        assert client.get(
            f"/dashboards/specs/{spec['spec_id']}").status_code == 200
        assert client.get("/dashboards/specs/NOPE").status_code == 404
        anonymous = client.post("/dashboards/ask", json={
            "question": "share?", "asked_by": "", "as_of": AS_OF})
        assert anonymous.status_code == 422
        assembled = client.post(
            f"/dashboards/specs/{spec['spec_id']}/assemble",
            json={"assembled_on": AS_OF})
        assert assembled.status_code == 200, assembled.text
        assembly = assembled.json()
        verify = client.get(
            f"/dashboards/assemblies/{assembly['assembly_id']}/verify")
        assert verify.json()["verified"] is True
        page = client.get(
            f"/dashboards/assemblies/{assembly['assembly_id']}/html")
        assert page.status_code == 200
        assert "View all blueprints" in page.text
        role = client.get(
            "/dashboards/roles/leadership",
            params={"asked_by": "api tester", "as_of": AS_OF})
        assert role.status_code == 200
        assert client.get(
            "/dashboards/roles/nope",
            params={"asked_by": "api tester"}).status_code == 422

    def loads(out: str):
        # The service's JSON log lines precede the result on
        # stdout; the result itself is the pretty-printed
        # document starting with a bare "{" line.
        return json.loads(out[out.index("{\n"):])

    db = tmp_path / "cli.db"
    common = ["--db", str(db), "--migrations", str(settings.migrations_dir)]
    assert cli_main(common + [
        "ask", "--question", MIXED_QUESTION, "--asked-by", "cli tester",
        "--as-of", AS_OF, "--name", "cli mixed"]) == 0
    spec = loads(capsys.readouterr().out)
    assert cli_main(common + ["assemble", spec["spec_id"],
                              "--as-of", AS_OF]) == 0
    assembly = loads(capsys.readouterr().out)
    assert cli_main(common + ["verify-dashboard",
                              assembly["assembly_id"]]) == 0
    assert loads(capsys.readouterr().out)["verified"] is True
    assert cli_main(common + ["dashboard", spec["spec_id"]]) == 0
    assert "View all blueprints" in capsys.readouterr().out
    assert cli_main(common + ["dashboard-spec", "NOPE"]) == 2
