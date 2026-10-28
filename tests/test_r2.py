"""Round 2: the demand engine — hand-computed fixtures, the
contribution identity, partial-estimate honesty, supersession,
tamper detection, outlook rollups, narrative verification."""

import json
import sqlite3

import pytest

from fertilizer_intelligence import models
from fertilizer_intelligence.demand import NarrativeRefused, OutlookNarrator
from fertilizer_intelligence.modelport import ModelReply

AS_OF = "2026-04-15"


def _line(estimate, driver):
    return next(c for c in estimate["contributions"] if c["driver"] == driver)


def test_hand_computed_ludhiana_dap_kharif(service):
    """Worked by hand from the stored facts. Ludhiana, DAP, kharif
    2025-26: rice 116240.7 ha, maize 51305.8, cotton 29102.8,
    groundnut 56616.5, sugarcane 26377.4 (soybean is not grown in
    the north's kharif mix, so it has no area fact at all)."""
    store = service.store
    areas = {a["crop"]: a["area_ha"] for a in store.area_facts("DST-LUD", "2025-26", "kharif")}
    rates = {r["crop"]: r["rate_kg_ha"] for r in store.application_rates() if r["product"] == "DAP"}
    # 5230.832 (rice) + 2565.290 (maize) + 1455.140 (cotton)
    # + 2547.743 (groundnut) + 1846.418 (sugarcane), in tonnes.
    base = round(sum(areas[c] * rates[c] / 1000.0 for c in areas if c in rates), 3)
    assert base == 13645.422

    est = service.estimate_demand("DST-LUD", "DAP", "2025-26", "kharif", AS_OF)
    assert est["status"] == "complete" and est["missing_drivers"] == []
    assert est["base_tonnes"] == base
    # Soil: phosphorus status is medium -> factor 1.00, no movement.
    soil = _line(est, "soil_nutrient_status")
    assert soil["inputs"]["status"] == "medium" and soil["factor"] == 1.00
    assert soil["delta_tonnes"] == 0.0
    # Monsoon: kharif deviation +6.9% sits in the [5, 15) band -> 1.03.
    monsoon = _line(est, "monsoon_deviation")
    assert monsoon["inputs"]["deviation_pct"] == 6.9 and monsoon["factor"] == 1.03
    assert monsoon["value_after_tonnes"] == 14054.785
    # ...which is exactly the stored (derived) consumption figure:
    # base x soil x monsoon is the generator's own derivation.
    consumption = store.consumption_facts("DST-LUD", "2025-26", "kharif", "DAP")[0]
    assert consumption["quantity_tonnes"] == monsoon["value_after_tonnes"]
    # Price: season-window mean vs the same window a year earlier.
    prices = {p["month"]: p["price"] for p in store.price_points("product", "DAP")}
    cur = [prices[f"2025-{m:02d}"] for m in range(6, 12)]
    prior = [prices[f"2024-{m:02d}"] for m in range(6, 12)]
    change = (sum(cur) / 6 - sum(prior) / 6) / (sum(prior) / 6)
    price = _line(est, "price_elasticity")
    assert abs(price["factor"] - (1 - 0.30 * change)) < 1e-9
    assert price["value_after_tonnes"] == round(14054.785 * price["factor"], 3) == 13681.135
    # Carry-in: trailing-12m production ran 3.6% under plan -> the
    # deficit band, factor 1.03.
    supply = {r["month"]: r for r in store.supply_facts("DAP")}
    window = [f"2024-{m:02d}" for m in range(6, 13)] + [f"2025-{m:02d}" for m in range(1, 6)]
    planned = sum(supply[m]["planned_tonnes"] for m in window)
    actual = sum(supply[m]["actual_tonnes"] for m in window)
    assert (actual - planned) / planned <= -0.02
    carry = _line(est, "carry_in_stock")
    assert carry["factor"] == 1.03
    assert est["total_tonnes"] == round(13681.135 * 1.03, 3) == 14091.569
    assert service.verify_estimate(est["estimate_id"]) == []


def test_hand_computed_guntur_mop_rabi(service):
    """Guntur, MOP, rabi 2025-26: potassium soil status is low
    (factor 1.10), rabi monsoon is held at 1.00, MOP prices eased
    year-on-year, and MOP has no supply facts at all."""
    store = service.store
    areas = {a["crop"]: a["area_ha"] for a in store.area_facts("DST-GUN", "2025-26", "rabi")}
    rates = {r["crop"]: r["rate_kg_ha"] for r in store.application_rates() if r["product"] == "MOP"}
    # 750.156 (groundnut) + 691.296 (maize) + 657.132 (vegetables)
    # + 1735.814 (wheat) = 3834.398 tonnes before rounding order.
    base_raw = sum(areas[c] * rates[c] / 1000.0 for c in areas if c in rates)
    assert abs(base_raw - 3834.3975) < 1e-6

    est = service.estimate_demand("DST-GUN", "MOP", "2025-26", "rabi", AS_OF)
    assert est["status"] == "complete"
    assert abs(est["base_tonnes"] - base_raw) <= 0.001
    soil = _line(est, "soil_nutrient_status")
    assert soil["inputs"]["nutrient"] == "potassium"
    assert soil["inputs"]["status"] == "low" and soil["factor"] == 1.10
    monsoon = _line(est, "monsoon_deviation")
    assert monsoon["factor"] == 1.00 and monsoon["delta_tonnes"] == 0.0
    # Price: the rabi window Nov-Apr has five of six months present
    # (the series ends 2026-03) — enough under the stated rule.
    price = _line(est, "price_elasticity")
    assert price["status"] == "applied"
    assert len(price["inputs"]["current_points"]) == 5
    assert abs(price["factor"] - 1.005266) < 1e-5
    assert abs(est["total_tonnes"] - 4240.048) <= 0.002
    carry = _line(est, "carry_in_stock")
    assert carry["status"] == "not_applicable" and carry["factor"] is None
    assert service.verify_estimate(est["estimate_id"]) == []


def test_total_is_base_plus_deltas(service):
    for district, product, year, season in (
        ("DST-KOT", "UREA", "2025-26", "kharif"),
        ("DST-PAT", "NPK_10_26_26", "2025-26", "rabi"),
        ("DST-NAG", "GLYPHOSATE", "2024-25", "kharif"),
        ("DST-BAR", "CHLORPYRIFOS", "2025-26", "kharif"),
    ):
        est = service.estimate_demand(district, product, year, season, AS_OF)
        total = est["base_tonnes"] + sum(
            c["delta_tonnes"] for c in est["contributions"] if c["driver"] != "base_area_rates"
        )
        assert abs(total - est["total_tonnes"]) <= 0.002
        assert service.verify_estimate(est["estimate_id"]) == []


def test_partial_estimates_name_their_missing_drivers(service):
    # The first crop year has no price history and no full carry-in
    # window: every estimate is partial and names what is missing.
    for product in ("UREA", "DAP", "NPK_10_26_26", "MOP", "GLYPHOSATE", "CHLORPYRIFOS"):
        est = service.estimate_demand("DST-IND", product, "2024-25", "kharif", AS_OF)
        assert est["status"] == "partial"
        assert "price_elasticity" in est["missing_drivers"]
    for product in ("UREA", "DAP", "NPK_10_26_26"):
        est = service.estimate_demand("DST-IND", product, "2024-25", "kharif", AS_OF)
        assert "carry_in_stock" in est["missing_drivers"]
    # MOP has no supply facts in any year: carry-in is
    # not_applicable, never "missing", and 2025-26 is complete.
    est = service.estimate_demand("DST-IND", "MOP", "2024-25", "kharif", AS_OF)
    assert "carry_in_stock" not in est["missing_drivers"]
    assert _line(est, "carry_in_stock")["status"] == "not_applicable"
    est = service.estimate_demand("DST-IND", "MOP", "2025-26", "kharif", AS_OF)
    assert est["status"] == "complete"


def test_excluded_crops_are_recorded_with_the_reason(service):
    # Chlorpyrifos has no rate for maize or sugarcane; Ludhiana
    # grows both, so both are excluded on the record.
    est = service.estimate_demand("DST-LUD", "CHLORPYRIFOS", "2025-26", "kharif", AS_OF)
    base = _line(est, "base_area_rates")
    excluded = {c["crop"]: c["reason"] for c in base["inputs"]["excluded_crops"]}
    assert excluded == {"maize": "no_application_rate", "sugarcane": "no_application_rate"}
    included = {c["crop"] for c in base["inputs"]["crops"]}
    assert included == {"rice", "cotton", "groundnut"}


def test_recompute_is_idempotent_then_supersedes_on_new_facts(service, settings):
    first = service.estimate_demand("DST-LUD", "DAP", "2025-26", "kharif", AS_OF)
    again = service.estimate_demand("DST-LUD", "DAP", "2025-26", "kharif", "2026-04-16")
    assert again["estimate_id"] == first["estimate_id"]
    assert len(service.store.list_estimates("DST-LUD", "DAP", "2025-26", "kharif")) == 1

    # A new fact the estimate consumes: Ludhiana starts growing
    # soybean in kharif (DAP rate 60 kg/ha). The recomputation is
    # a new artefact linked to the old head; the old one stands.
    service.store.insert_area_facts([models.AreaFact(
        district_id="DST-LUD", crop_year="2025-26", season="kharif",
        crop="soybean", area_ha=5000.0,
        source="district_crop_statistics", as_of="2025-10-31",
    )])
    second = service.estimate_demand("DST-LUD", "DAP", "2025-26", "kharif", "2026-04-17")
    assert second["estimate_id"] != first["estimate_id"]
    assert second["supersedes"] == first["estimate_id"]
    assert abs(second["base_tonnes"] - (first["base_tonnes"] + 300.0)) <= 0.001
    assert service.get_estimate(first["estimate_id"])["total_tonnes"] == first["total_tonnes"]
    assert service.verify_estimate(first["estimate_id"]) == []
    assert service.verify_estimate(second["estimate_id"]) == []


def test_tampered_artefacts_are_detected(service, settings):
    est = service.estimate_demand("DST-LUD", "DAP", "2025-26", "kharif", AS_OF)
    raw = sqlite3.connect(settings.sqlite_path)
    raw.execute(
        "UPDATE demand_contributions SET delta_tonnes = delta_tonnes + 50 "
        "WHERE estimate_id = ? AND driver = 'price_elasticity'",
        (est["estimate_id"],),
    )
    raw.commit()
    problems = service.verify_estimate(est["estimate_id"])
    assert problems and any("price_elasticity" in p for p in problems)
    raw.execute(
        "UPDATE demand_contributions SET delta_tonnes = delta_tonnes - 50 "
        "WHERE estimate_id = ? AND driver = 'price_elasticity'",
        (est["estimate_id"],),
    )
    raw.execute(
        "UPDATE demand_estimates SET total_tonnes = total_tonnes + 1 WHERE estimate_id = ?",
        (est["estimate_id"],),
    )
    raw.commit()
    raw.close()
    assert service.verify_estimate(est["estimate_id"]) != []


def test_pre_price_value_tracks_stored_consumption(service):
    # Base x soil x monsoon is the generator's derivation; the
    # engine's value after the monsoon line must track the stored
    # consumption figure for the same cell (rounding order aside).
    for district, product, season in (
        ("DST-KAR", "UREA", "kharif"), ("DST-RAJ", "DAP", "kharif"),
        ("DST-WAR", "MOP", "rabi"), ("DST-BEL", "NPK_10_26_26", "kharif"),
    ):
        est = service.estimate_demand(district, product, "2025-26", season, AS_OF)
        pre_price = _line(est, "monsoon_deviation")["value_after_tonnes"]
        stored = service.store.consumption_facts(district, "2025-26", season, product)[0]
        assert abs(pre_price - stored["quantity_tonnes"]) <= 0.05


def test_price_line_shows_the_planted_spike(service):
    # The September 2025 DAP spike sits inside the kharif 2025-26
    # price window: the mean is up year-on-year and the elasticity
    # factor drags demand below the pre-price value.
    est = service.estimate_demand("DST-LUD", "DAP", "2025-26", "kharif", AS_OF)
    price = _line(est, "price_elasticity")
    months = [m for m, _ in price["inputs"]["current_points"]]
    assert "2025-09" in months
    assert price["inputs"]["current_mean"] > price["inputs"]["prior_mean"]
    assert price["factor"] < 1.0 and price["delta_tonnes"] < 0


def test_outlook_rollup_equals_sum_of_parts(service):
    outlook = service.demand_outlook("2025-26", "kharif", AS_OF)
    assert outlook["estimate_count"] == 72 and outlook["partial_count"] == 0
    estimates = service.store.list_estimates(crop_year="2025-26", season="kharif")
    assert {e["estimate_id"] for e in estimates} == set(outlook["estimate_ids"])
    for product, rolled in outlook["product_rollups"].items():
        parts = sum(e["total_tonnes"] for e in estimates if e["product"] == product)
        assert abs(rolled - parts) <= 0.01
    assert abs(outlook["total_tonnes"] - sum(outlook["product_rollups"].values())) <= 0.01
    assert service.verify_outlook(outlook["outlook_id"]) == []
    # Recomputing the same outlook over unchanged facts is the
    # same artefact, not a second one.
    assert service.demand_outlook("2025-26", "kharif", "2026-04-16")["outlook_id"] == outlook["outlook_id"]
    # The first crop year's outlook is honestly partial throughout.
    first_year = service.demand_outlook("2024-25", "rabi", AS_OF)
    assert first_year["status"] == "partial" and first_year["partial_count"] == 72


class _WrongFigureModel:
    profile_name = "stub"
    model_name = "stub-wrong-figure"

    def complete(self, system, prompt):
        return ModelReply(
            text="Total estimated demand is 999999.99 tonnes.",
            profile=self.profile_name, model=self.model_name,
            input_tokens=0, output_tokens=0,
        )


def test_narrative_is_verified_and_a_wrong_figure_is_refused(service):
    narrative = service.draft_outlook_narrative("2025-26", "kharif", AS_OF)
    assert narrative["figures"]
    assert service.verify_narrative(narrative["narrative_id"]) == []

    outlook = service.get_outlook("2025-26", "kharif")
    before = len(service.store.list_narratives(outlook["outlook_id"]))
    narrator = OutlookNarrator(service.store, _WrongFigureModel())
    with pytest.raises(NarrativeRefused):
        narrator.draft(outlook, AS_OF)
    assert len(service.store.list_narratives(outlook["outlook_id"])) == before


def test_unknown_triple_is_refused(service):
    with pytest.raises(ValueError):
        service.estimate_demand("DST-XXX", "DAP", "2025-26", "kharif", AS_OF)
    with pytest.raises(ValueError):
        service.estimate_demand("DST-LUD", "NOT_A_PRODUCT", "2025-26", "kharif", AS_OF)


def test_api_r2_surface(settings):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        resp = client.post("/estimates", json={
            "district_id": "DST-LUD", "product": "DAP",
            "crop_year": "2025-26", "season": "kharif", "as_of": AS_OF,
        })
        assert resp.status_code == 200
        est = resp.json()
        assert est["total_tonnes"] == 14091.569 and est["contributions"]
        got = client.get(f"/estimates/{est['estimate_id']}")
        assert got.status_code == 200 and got.json()["estimate_id"] == est["estimate_id"]
        lines = client.get(f"/estimates/{est['estimate_id']}/contributions").json()
        assert [line["driver"] for line in lines][0] == "base_area_rates"
        assert client.get(f"/estimates/{est['estimate_id']}/verify").json()["ok"] is True
        outlook = client.post("/outlooks", json={
            "crop_year": "2025-26", "season": "kharif", "as_of": AS_OF,
        }).json()
        assert outlook["estimate_count"] == 72
        assert client.get("/outlooks/2025-26/kharif").json()["outlook_id"] == outlook["outlook_id"]
        assert client.get("/outlooks/2025-26/kharif/verify").json()["ok"] is True
        narrative = client.post("/outlooks/2025-26/kharif/narrative", json={"as_of": AS_OF})
        assert narrative.status_code == 200 and narrative.json()["figures"]
        assert client.get("/estimates/EST-nope").status_code == 404
        assert client.get("/outlooks/2025-26/monsoon").status_code == 404


def test_cli_r2_surface(settings, tmp_path, capsys):
    from fertilizer_intelligence.cli import main as cli_main

    db = tmp_path / "cli.db"
    common = ["--db", str(db), "--migrations", str(settings.migrations_dir)]
    assert cli_main(common + [
        "estimate", "--district", "DST-LUD", "--product", "DAP",
        "--crop-year", "2025-26", "--season", "kharif", "--as-of", AS_OF,
    ]) == 0
    est = json.loads(capsys.readouterr().out)
    assert est["total_tonnes"] == 14091.569
    assert cli_main(common + ["contributions", "--estimate-id", est["estimate_id"]]) == 0
    lines = json.loads(capsys.readouterr().out)
    assert len(lines) == 5 and lines[0]["driver"] == "base_area_rates"
    assert cli_main(common + [
        "outlook", "--crop-year", "2025-26", "--season", "kharif", "--as-of", AS_OF,
    ]) == 0
    outlook = json.loads(capsys.readouterr().out)
    assert outlook["estimate_count"] == 72
    assert cli_main(common + [
        "narrative", "--crop-year", "2025-26", "--season", "kharif", "--as-of", AS_OF,
    ]) == 0
    narrative = json.loads(capsys.readouterr().out)
    assert narrative["figures"] and "tonnes" in narrative["text"]
