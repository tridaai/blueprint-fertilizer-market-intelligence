"""Round 12 — season-close estimate scoring and eval depth.

Head demand estimates are graded against the season-close
actuals (R11) per district × product × season: signed
error and bias computed in code from the stored artefacts,
the total error attributed across the estimate's own
contribution lines under the versioned scoring pack, and
every score re-performed by a second route. The headline
fixture is hand-computed: its most-wrong line and every
attributed error are exact numbers stated here, not values
copied out of a run.
"""

from __future__ import annotations

import json

import pytest

from fertilizer_intelligence import models
from fertilizer_intelligence import scoring_rules as pack
from fertilizer_intelligence.scoring import ScoringRefused
from rawdb import raw_connect

AS_OF = "2026-04-25"


def _lines(rows):
    """Contribution lines from (driver, status, delta)
    triples, with the value-after chain accumulated."""
    lines, value = [], 0.0
    for line_no, (driver, status, delta) in enumerate(rows):
        value = round(value + delta, 3)
        lines.append({
            "line_no": line_no, "driver": driver,
            "status": status,
            "factor": None if status != "applied" else 1.0,
            "delta_tonnes": delta, "value_after_tonnes": value,
            "inputs": {},
        })
    return lines


def _insert_estimate(store, estimate_id, district, product, lines,
                     status="complete", missing=None):
    total = lines[-1]["value_after_tonnes"]
    store.insert_estimate({
        "estimate_id": estimate_id, "district_id": district,
        "product": product, "crop_year": "2025-26",
        "season": "rabi", "status": status,
        "base_tonnes": lines[0]["delta_tonnes"],
        "total_tonnes": total, "missing_drivers": missing or [],
        "rules_version": "2026.10.1",
        "rate_table_version": "2026.10.1",
        "fact_fingerprint": f"fixture-{estimate_id}",
        "as_of": "2026-04-15", "supersedes": None,
    }, lines)
    return total


def _actual(district, product, kind, qty):
    return {"district_id": district, "crop_year": "2025-26",
            "season": "rabi", "product": product,
            "actual_kind": kind, "quantity_tonnes": qty,
            "source": "state_dispatch_returns",
            "as_of": "2026-04-15"}


# The headline fixture, computed by hand. Estimate: base
# 300, soil +400, monsoon 0 (rabi holds at factor 1.0),
# price −200, carry-in missing at 0 — total 500. Actual
# 750: error +250. Shares of the total: base 0.6, soil
# 0.8, price −0.4. Attributed: base +150, soil +200,
# price −100, the zero lines 0 — summing to +250 exactly.
# The soil line is the most wrong, at +200.
FIXTURE_A_LINES = [
    ("base_area_rates", "applied", 300.0),
    ("soil_nutrient_status", "applied", 400.0),
    ("monsoon_deviation", "applied", 0.0),
    ("price_elasticity", "applied", -200.0),
    ("carry_in_stock", "missing", 0.0),
]

# A second cell with a negative error: base 800, soil
# +150, price +50 — total 1000; actual 750, error −250;
# attributed base −200, soil −37.5, price −12.5; the
# base line is most wrong.
FIXTURE_B_LINES = [
    ("base_area_rates", "applied", 800.0),
    ("soil_nutrient_status", "applied", 150.0),
    ("monsoon_deviation", "applied", 0.0),
    ("price_elasticity", "applied", 50.0),
    ("carry_in_stock", "not_applicable", 0.0),
]


def _plant_fixtures(service):
    store = service.store
    _insert_estimate(store, "EST-FIX-A", "DST-FIX", "UREA",
                     _lines(FIXTURE_A_LINES))
    _insert_estimate(store, "EST-FIX-B", "DST-FIXB", "MOP",
                     _lines(FIXTURE_B_LINES))
    store.insert_season_actuals([
        models.SeasonActual(**_actual("DST-FIX", "UREA",
                                      "consumption", 750.0)),
        models.SeasonActual(**_actual("DST-FIXB", "MOP",
                                      "consumption", 750.0)),
    ])


# -- the hand-computed fixture --------------------------------------


def test_hand_computed_attribution_fixture(service):
    _plant_fixtures(service)
    run = service.score_season("2025-26", "rabi", "test desk", AS_OF)
    assert run["rules_version"] == pack.SCORING_VERSION
    assert run["attribution_method"] == pack.ATTRIBUTION_METHOD
    assert run["scored_count"] == 2
    cells = {(c["district_id"], c["product"]): c
             for c in run["cells"]}

    a = cells[("DST-FIX", "UREA")]
    assert a["estimate_id"] == "EST-FIX-A"
    assert a["estimate_tonnes"] == 500.0
    assert a["actual_tonnes"] == 750.0
    assert a["error_tonnes"] == 250.0
    assert a["abs_error_tonnes"] == 250.0
    assert a["error_pct"] == 33.3333
    attributed = {l["driver"]: l["attributed_error_tonnes"]
                  for l in a["lines"]}
    assert attributed == {
        "base_area_rates": 150.0,
        "soil_nutrient_status": 200.0,
        "monsoon_deviation": 0.0,
        "price_elasticity": -100.0,
        "carry_in_stock": 0.0,
    }
    assert sum(attributed.values()) == a["error_tonnes"]
    assert a["most_wrong_driver"] == "soil_nutrient_status"
    assert a["most_wrong_line_no"] == 1
    assert a["most_wrong_attributed_error_tonnes"] == 200.0

    b = cells[("DST-FIXB", "MOP")]
    assert b["error_tonnes"] == -250.0
    assert b["error_pct"] == -33.3333
    attributed_b = {l["driver"]: l["attributed_error_tonnes"]
                    for l in b["lines"]}
    assert attributed_b["base_area_rates"] == -200.0
    assert attributed_b["soil_nutrient_status"] == -37.5
    assert attributed_b["price_elasticity"] == -12.5
    assert sum(attributed_b.values()) == b["error_tonnes"]
    assert b["most_wrong_driver"] == "base_area_rates"

    # Bias is the mean signed error; the two cells cancel.
    assert run["bias_tonnes"] == 0.0
    assert run["mean_abs_error_pct"] == 33.3333
    assert run["unmatched_actuals"] == []
    assert run["unmatched_estimates"] == []


def test_partial_estimate_is_scored_as_struck(service):
    _insert_estimate(
        service.store, "EST-FIX-P", "DST-FIX", "DAP",
        _lines(FIXTURE_A_LINES), status="partial",
        missing=["carry_in_stock"])
    service.store.insert_season_actuals([
        models.SeasonActual(**_actual("DST-FIX", "DAP",
                                      "consumption", 500.0))])
    run = service.score_season("2025-26", "rabi", "test desk", AS_OF)
    cell = run["cells"][0]
    assert cell["estimate_status"] == "partial"
    assert cell["error_tonnes"] == 0.0
    assert cell["most_wrong_attributed_error_tonnes"] == 0.0


def test_zero_actual_names_no_percentage(service):
    _insert_estimate(service.store, "EST-FIX-Z", "DST-FIX",
                     "UREA", _lines(FIXTURE_A_LINES))
    service.store.insert_season_actuals([
        models.SeasonActual(**_actual("DST-FIX", "UREA",
                                      "dispatch", 0.0))])
    run = service.score_season("2025-26", "rabi", "test desk", AS_OF)
    cell = run["cells"][0]
    assert cell["zero_actual"] is True
    assert cell["error_pct"] is None
    assert cell["error_tonnes"] == -500.0
    assert run["mean_abs_error_pct"] is None


# -- re-performance and the refusal discipline -----------------------


def test_scores_reperform_and_tamper_is_detected(service, settings):
    _plant_fixtures(service)
    run = service.score_season("2025-26", "rabi", "test desk", AS_OF)
    result = service.verify_score_run(run["score_id"])
    assert result["verified"] and result["problems"] == []

    raw = raw_connect(settings)
    row = raw.execute(
        "SELECT payload FROM estimate_scores WHERE score_id = ?",
        (run["score_id"],)).fetchone()
    payload = json.loads(row[0])
    payload["cells"][0]["error_tonnes"] += 5.0
    raw.execute(
        "UPDATE estimate_scores SET payload = ? WHERE score_id = ?",
        (json.dumps(payload), run["score_id"]))
    raw.commit()
    raw.close()
    result = service.verify_score_run(run["score_id"])
    assert not result["verified"]
    assert any("error_tonnes" in p or "fingerprint" in p
               for p in result["problems"])


def test_tampered_contribution_refuses_the_run_wholesale(
        service, settings):
    _plant_fixtures(service)
    raw = raw_connect(settings)
    raw.execute(
        "UPDATE demand_contributions SET delta_tonnes = ? "
        "WHERE estimate_id = ? AND line_no = ?",
        (450.0, "EST-FIX-A", 1))
    raw.commit()
    raw.close()
    with pytest.raises(ScoringRefused) as refused:
        service.score_season("2025-26", "rabi", "test desk", AS_OF)
    assert service.list_score_runs() == []
    refusals = service.list_score_refusals("2025-26", "rabi")
    assert len(refusals) == 1
    assert refusals[0]["refusal_id"] == refused.value.refusal_id
    assert refusals[0]["problems"]


def test_rerun_returns_the_stored_run(service):
    _plant_fixtures(service)
    first = service.score_season("2025-26", "rabi", "test desk",
                                 AS_OF)
    second = service.score_season("2025-26", "rabi", "test desk",
                                  AS_OF)
    assert second["score_id"] == first["score_id"]
    assert len(service.list_score_runs()) == 1


# -- the join names its unmatched in both directions ------------------


def test_unmatched_named_in_both_directions(service):
    _plant_fixtures(service)
    _insert_estimate(service.store, "EST-FIX-C", "DST-FIX",
                     "DAP", _lines(FIXTURE_B_LINES))
    service.store.insert_season_actuals([
        models.SeasonActual(**_actual("DST-NONE", "UREA",
                                      "consumption", 100.0))])
    run = service.score_season("2025-26", "rabi", "test desk", AS_OF)
    report = service.actuals_report("2025-26", "rabi")
    assert run["unmatched_actuals"] == report["unmatched"]
    assert run["unmatched_actuals"] == [
        "DST-NONE/2025-26/rabi/UREA/consumption"]
    unmatched = run["unmatched_estimates"]
    assert len(unmatched) == 1
    assert unmatched[0]["estimate_id"] == "EST-FIX-C"
    assert unmatched[0]["label"] == "DST-FIX/2025-26/rabi/DAP"


def test_score_run_names_the_actuals_batch(service):
    service.estimate_demand("DST-GUN", "UREA", "2025-26", "rabi",
                            "2026-04-15")
    batch = service.load_connector_batch(
        "state_dispatch_returns",
        [_actual("DST-GUN", "UREA", "consumption", 45210.5)],
        "test desk", "2026-04-20")
    run = service.score_season("2025-26", "rabi", "test desk", AS_OF)
    assert run["actual_batches"] == [batch["batch_id"]]
    assert run["scored_count"] == 1
    cell = run["cells"][0]
    estimate = service.store.get_estimate(cell["estimate_id"])
    assert cell["error_tonnes"] == round(
        45210.5 - estimate["total_tonnes"], 3)


# -- surfaces ----------------------------------------------------------


def test_api_and_cli_surfaces(service, settings, tmp_path, capsys):
    _plant_fixtures(service)
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        resp = client.post("/scores", json={
            "crop_year": "2025-26", "season": "rabi",
            "scored_by": "api desk", "as_of": AS_OF})
        assert resp.status_code == 200
        run = resp.json()
        assert run["scored_count"] == 2
        listed = client.get("/scores", params={
            "crop_year": "2025-26", "season": "rabi"}).json()
        assert [r["score_id"] for r in listed] == [run["score_id"]]
        got = client.get(f"/scores/{run['score_id']}").json()
        assert got["score_id"] == run["score_id"]
        verified = client.get(
            f"/scores/{run['score_id']}/verify").json()
        assert verified["verified"]
        missing = client.get("/scores/SCR-nope")
        assert missing.status_code == 404
        assert client.get("/score-refusals").json() == []

    from fertilizer_intelligence.cli import main as cli_main

    db = service.settings.sqlite_path
    base = ["--db", str(db), "--migrations", "migrations"]
    rc = cli_main(base + ["scores", "--crop-year", "2025-26",
                          "--season", "rabi"])
    assert rc == 0
    out = capsys.readouterr().out
    printed, _ = json.JSONDecoder().raw_decode(
        out[out.index("[\n"):])
    assert len(printed) == 1
    rc = cli_main(base + ["verify-score", printed[0]["score_id"]])
    assert rc == 0
    out = capsys.readouterr().out
    verified, _ = json.JSONDecoder().raw_decode(
        out[out.index("{\n"):])
    assert verified["verified"]
