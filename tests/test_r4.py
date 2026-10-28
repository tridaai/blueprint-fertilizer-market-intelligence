"""Round 4: the import & supply-gap tracker — the position
identity over every product-month, the planted delay's dip and
recovery in the position chain, hand-computed gap bands for two
products, the projection's slip supersession with named changes,
tamper detection, and API/CLI parity.

Every pinned figure below was derived independently from the
stored facts (the supply pack's stated rules applied by hand to
the generator's record) before the engine was run against it.
"""

import json
import sqlite3

import pytest

from fertilizer_intelligence import supply as supply_engine

AS_OF = "2026-04-15"
POSITIONABLE = ("UREA", "DAP", "NPK_10_26_26", "MOP")

# First tracked crop year (2024-25) consumption totals, and the
# pack's derivation: total / 12 = the first month's opening.
INITIAL_OPENINGS = {
    "UREA": (602923.259, 50243.605),
    "DAP": (266365.476, 22197.123),
    "NPK_10_26_26": (172016.987, 14334.749),
    "MOP": (125961.882, 10496.824),
}

# The DAP chain around the planted delay (IMP-DAP-2510, 55,000 t,
# expected 2025-10, arrived 2025-12): month -> (production actual,
# imports, consumption, closing).
DAP_DELAY_MONTHS = {
    "2025-09": (423350.1, 0.0, 25211.399, 6676784.451),
    "2025-10": (386897.4, 0.0, 25211.399, 7038470.452),
    "2025-11": (354794.7, 0.0, 45512.684, 7347752.468),
    "2025-12": (343761.6, 55000.0, 20301.280, 7726212.788),
}


def line_of(position, component):
    return next(l for l in position["lines"] if l["component"] == component)


def test_position_chain_covers_the_tracked_period(service):
    months = supply_engine.tracked_months(service.store)
    assert months[0] == "2024-04" and months[-1] == "2026-03" and len(months) == 24
    for product in POSITIONABLE:
        chain = service.supply_positions(product, AS_OF)
        assert [p["month"] for p in chain] == months
        for position in chain:
            identity = (
                position["opening_tonnes"]
                + (position["production_actual_tonnes"] or 0.0)
                + position["imports_tonnes"]
                - position["consumption_tonnes"]
            )
            assert abs(identity - position["closing_tonnes"]) < 0.002
            assert [l["component"] for l in position["lines"]] == [
                "opening_stock", "domestic_production", "import_arrivals",
                "consumption", "closing_stock",
            ]
            assert service.verify_position(product, position["month"]) == []
        for prior, current in zip(chain, chain[1:]):
            assert current["opening_tonnes"] == prior["closing_tonnes"]
            opening = line_of(current, "opening_stock")
            assert opening["inputs"]["basis"] == "prior_position_closing"
            assert opening["inputs"]["prior_position_id"] == prior["position_id"]


def test_first_month_opening_is_the_stated_derivation(service):
    for product, (total, opening) in INITIAL_OPENINGS.items():
        chain = service.supply_positions(product, AS_OF)
        first = chain[0]
        assert first["month"] == "2024-04"
        assert first["opening_tonnes"] == opening
        line = line_of(first, "opening_stock")
        assert line["inputs"]["basis"] == "initial_stock_derivation"
        assert line["inputs"]["crop_year"] == "2024-25"
        assert line["inputs"]["crop_year_total_tonnes"] == total
        assert line["inputs"]["divisor_months"] == 12
        assert len(line["fact_ids"]) == 24  # 12 districts x 2 seasons


def test_planted_delay_dip_and_recovery_in_positions(service):
    chain = {p["month"]: p for p in service.supply_positions("DAP", AS_OF)}
    for month, (production, imports, consumption, closing) in DAP_DELAY_MONTHS.items():
        position = chain[month]
        assert position["production_actual_tonnes"] == production
        assert position["imports_tonnes"] == imports, month
        assert position["consumption_tonnes"] == consumption
        assert position["closing_tonnes"] == closing
    # The dip: October and November carry no DAP arrivals at all;
    # the recovery names the delayed vessel on December's line.
    for month in ("2025-10", "2025-11"):
        assert line_of(chain[month], "import_arrivals")["inputs"]["shipments"] == []
    december = line_of(chain["2025-12"], "import_arrivals")
    assert [s["shipment_id"] for s in december["inputs"]["shipments"]] == ["IMP-DAP-2510"]
    shipment = december["inputs"]["shipments"][0]
    assert shipment["expected_month"] == "2025-10"
    assert shipment["arrived_month"] == "2025-12"
    assert shipment["quantity_tonnes"] == 55000.0
    # The production line carries plan alongside actual.
    october = line_of(chain["2025-10"], "domestic_production")
    assert october["inputs"]["planned_tonnes"] == 380000.0
    assert october["inputs"]["actual_tonnes"] == 386897.4
    # The whole tracked DAP import record, by actual arrival month.
    landed = {
        p["month"]: p["imports_tonnes"] for p in chain.values() if p["imports_tonnes"]
    }
    assert landed == {
        "2024-07": 64000.0, "2024-11": 58000.0,
        "2025-07": 61000.0, "2025-12": 55000.0,
    }


def test_import_only_product_states_no_production(service):
    chain = service.supply_positions("MOP", AS_OF)
    for position in chain:
        assert position["production_planned_tonnes"] is None
        assert position["production_actual_tonnes"] is None
        line = line_of(position, "domestic_production")
        assert line["status"] == "not_applicable"
        assert "import-only" in line["inputs"]["reason"]
    landed = {
        p["month"]: p["imports_tonnes"] for p in chain if p["imports_tonnes"]
    }
    assert landed == {"2024-08": 48000.0, "2025-02": 51000.0, "2025-11": 46000.0}


def test_consumption_spread_sums_back_to_the_season_totals(service):
    store = service.store
    for product in POSITIONABLE:
        monthly = supply_engine.monthly_consumption(store, product)
        facts = store.consumption_facts(product=product)
        for fact in facts:
            cells = [
                cell
                for entry in monthly.values()
                for cell in entry["cells"]
                if cell["fact_id"] == (
                    f"consumption_facts:{fact['district_id']}|{fact['crop_year']}"
                    f"|{fact['season']}|{product}"
                )
            ]
            assert len(cells) == 6
            assert abs(sum(c["share_tonnes"] for c in cells)
                       - fact["quantity_tonnes"]) < 0.002
        # November carries both seasons' shares (kharif residual +
        # rabi first share): the position line names cells from two
        # different seasons for the same month.
        service.supply_positions(product, AS_OF)
        november = service.get_position(product, "2025-11")
        seasons = {
            (c["crop_year"], c["season"])
            for c in line_of(november, "consumption")["inputs"]["cells"]
        }
        assert seasons == {("2025-26", "kharif"), ("2025-26", "rabi")}


def test_positions_refuse_products_with_no_supply_side(service):
    for product in ("GLYPHOSATE", "CHLORPYRIFOS"):
        with pytest.raises(ValueError, match="no supply position"):
            service.supply_positions(product, AS_OF)
    with pytest.raises(ValueError, match="unknown product"):
        service.supply_positions("NPK_19_19_19", AS_OF)


def test_gap_delay_reading_and_resolution(service):
    gap = service.supply_gap("DAP", "2025-26", "kharif", "2025-10-31")
    assert gap["demand_tonnes"] == 151664.295  # the R2 outlook rollup
    assert gap["scheduled_imports_tonnes"] == 116000.0
    assert gap["due_imports_tonnes"] == 116000.0
    assert gap["credited_imports_tonnes"] == 61000.0
    assert gap["slipped_tonnes"] == 55000.0
    assert gap["programme_cover_pct"] == 52.5862
    assert gap["available_tonnes"] == 7519322.147
    assert gap["gap_tonnes"] == 7367657.852
    assert gap["gap_pct_of_demand"] == 4857.8724
    # The level reading is deep in surplus; the programme reading
    # binds, and the artefact says so.
    assert gap["band"] == "short"
    assert gap["band_basis"] == "import_programme_cover"
    assert service.verify_gap("DAP", "2025-26", "kharif") == []

    still = service.supply_gap("DAP", "2025-26", "kharif", "2025-11-30")
    assert still["band"] == "short" and still["slipped_tonnes"] == 55000.0
    assert still["supersedes"] == gap["gap_id"]

    resolved = service.supply_gap("DAP", "2025-26", "kharif", "2025-12-31")
    assert resolved["credited_imports_tonnes"] == 116000.0
    assert resolved["slipped_tonnes"] == 0.0
    assert resolved["programme_cover_pct"] == 100.0
    assert resolved["available_tonnes"] == 7574322.147
    assert resolved["band"] == "comfortable"
    assert resolved["supersedes"] == still["gap_id"]
    assert service.verify_gap("DAP", "2025-26", "kharif") == []
    # Recomputing at the same as-of is idempotent.
    assert service.supply_gap("DAP", "2025-26", "kharif", "2025-12-31")["gap_id"] \
        == resolved["gap_id"]


def test_gap_level_reading_for_the_import_only_product(service):
    gap = service.supply_gap("MOP", "2025-26", "kharif", "2025-11-30")
    assert gap["demand_tonnes"] == 79325.253
    assert gap["scheduled_imports_tonnes"] == 46000.0
    assert gap["credited_imports_tonnes"] == 46000.0
    assert gap["programme_cover_pct"] == 100.0
    # No domestic production: the season's own arrivals do not
    # cover the outlook, so the level reading binds.
    assert gap["available_tonnes"] == 29534.942
    assert gap["gap_tonnes"] == -49790.311
    assert gap["gap_pct_of_demand"] == -62.7673
    assert gap["band"] == "short"
    assert gap["band_basis"] == "level_gap"
    assert service.verify_gap("MOP", "2025-26", "kharif") == []


def test_projection_slip_supersession_names_the_change(service):
    first = service.supply_projection("DAP", "2025-26", "rabi", "2025-09-30")
    assert first["basis_month"] == "2025-09"
    assert first["opening_tonnes"] == 6676784.451  # the September closing
    assert first["status"] == "partial"
    assert first["assumption_set"]["beyond_plan_months"] == ["2026-04"]
    assert first["assumption_set"]["slipped_shipments"] == []
    scheduled = first["assumption_set"]["scheduled_shipments"]
    assert [s["shipment_id"] for s in scheduled] == ["IMP-DAP-2510"]
    assert first["closing_tonnes"] == 8905455.248
    assert first["assumption_changes"] == []
    assert service.verify_projection("DAP", "2025-26", "rabi") == []

    slipped = service.supply_projection("DAP", "2025-26", "rabi", "2025-11-30")
    assert slipped["supersedes"] == first["projection_id"]
    assert slipped["opening_tonnes"] == 7347752.468
    assert slipped["closing_tonnes"] == 8832147.348
    assert [s["shipment_id"] for s in slipped["assumption_set"]["slipped_shipments"]] \
        == ["IMP-DAP-2510"]
    assert slipped["assumption_set"]["scheduled_shipments"] == []
    kinds = {(c["kind"], c["shipment_id"]) for c in slipped["assumption_changes"]}
    assert ("basis_advanced", None) in kinds
    assert ("slipped_unlanded", "IMP-DAP-2510") in kinds
    assert service.verify_projection("DAP", "2025-26", "rabi") == []

    landed = service.supply_projection("DAP", "2025-26", "rabi", "2025-12-31")
    assert landed["supersedes"] == slipped["projection_id"]
    assert landed["opening_tonnes"] == 7726212.788
    assert landed["closing_tonnes"] == 8850908.948
    assert landed["assumption_set"]["slipped_shipments"] == []
    kinds = {(c["kind"], c["shipment_id"]) for c in landed["assumption_changes"]}
    assert ("landed_after_slip", "IMP-DAP-2510") in kinds
    assert service.verify_projection("DAP", "2025-26", "rabi") == []
    # Idempotent at the same as-of.
    assert service.supply_projection("DAP", "2025-26", "rabi", "2025-12-31")["projection_id"] \
        == landed["projection_id"]


def test_projection_refusals(service):
    with pytest.raises(ValueError, match="nothing left to project"):
        service.supply_projection("DAP", "2025-26", "kharif", "2025-12-31")
    with pytest.raises(ValueError, match="no actual position covers"):
        service.supply_projection("DAP", "2025-26", "rabi", "2026-05-31")
    with pytest.raises(ValueError, match="no supply position"):
        service.supply_projection("GLYPHOSATE", "2025-26", "rabi", "2025-09-30")


def test_position_tamper_is_detected(service, settings):
    position = service.supply_position("DAP", "2025-10", AS_OF)
    assert service.verify_position("DAP", "2025-10") == []
    db = sqlite3.connect(settings.sqlite_path)
    payload = json.loads(
        db.execute(
            "SELECT payload FROM supply_positions WHERE position_id = ?",
            (position["position_id"],),
        ).fetchone()[0]
    )
    payload["closing_tonnes"] += 1000.0
    db.execute(
        "UPDATE supply_positions SET closing_tonnes = closing_tonnes + 1000, "
        "payload = ? WHERE position_id = ?",
        (json.dumps(payload), position["position_id"]),
    )
    db.commit()
    problems = service.verify_position("DAP", "2025-10")
    assert problems, "a tampered closing must fail verification"
    db.execute(
        "UPDATE supply_positions SET closing_tonnes = closing_tonnes - 1000, "
        "payload = ? WHERE position_id = ?",
        (json.dumps({**payload, "closing_tonnes": payload["closing_tonnes"] - 1000.0}),
         position["position_id"]),
    )
    db.commit()
    assert service.verify_position("DAP", "2025-10") == []
    # Tampering with a component line is caught the same way.
    db.execute(
        "UPDATE supply_position_lines SET tonnes = tonnes + 500 "
        "WHERE position_id = ? AND component = 'import_arrivals'",
        (position["position_id"],),
    )
    db.commit()
    assert service.verify_position("DAP", "2025-10")
    db.close()


def test_api_parity_round4(service, settings):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        chain = client.post("/positions", json={"product": "DAP", "as_of": AS_OF}).json()
        assert len(chain) == 24
        october = client.get("/positions/DAP/2025-10").json()
        assert october["imports_tonnes"] == 0.0
        assert october["position_id"] == chain[18]["position_id"]
        verify = client.get("/positions/DAP/2025-10/verify").json()
        assert verify["ok"] is True and verify["problems"] == []
        assert client.get("/positions/DAP/2027-01").status_code == 404
        refused = client.post("/positions", json={"product": "GLYPHOSATE"})
        assert refused.status_code == 422

        gap = client.post("/gaps", json={
            "product": "DAP", "crop_year": "2025-26", "season": "kharif",
            "as_of": "2025-11-30",
        }).json()
        assert gap["band"] == "short" and gap["slipped_tonnes"] == 55000.0
        assert client.get("/gaps/DAP/2025-26/kharif").json()["gap_id"] == gap["gap_id"]
        assert client.get("/gaps/DAP/2025-26/kharif/verify").json()["ok"] is True

        projection = client.post("/projections", json={
            "product": "DAP", "crop_year": "2025-26", "season": "rabi",
            "as_of": "2025-09-30",
        }).json()
        assert projection["status"] == "partial"
        assert projection["closing_tonnes"] == 8905455.248
        got = client.get("/projections/DAP/2025-26/rabi").json()
        assert got["projection_id"] == projection["projection_id"]
        assert client.get("/projections/DAP/2025-26/rabi/verify").json()["ok"] is True
        ended = client.post("/projections", json={
            "product": "DAP", "crop_year": "2025-26", "season": "kharif",
            "as_of": "2025-12-31",
        })
        assert ended.status_code == 422


def test_cli_parity_round4(service, settings, capsys, tmp_path):
    from fertilizer_intelligence import cli

    base = [
        "--db", str(settings.sqlite_path),
        "--migrations", str(settings.migrations_dir),
    ]
    service.supply_gap("DAP", "2025-26", "kharif", "2025-11-30")
    assert cli.main(base + ["position", "--product", "DAP", "--month", "2025-10"]) == 0
    position = json.loads(capsys.readouterr().out)
    assert position["imports_tonnes"] == 0.0
    assert position["closing_tonnes"] == 7038470.452

    assert cli.main(base + ["verify-position", "--product", "DAP", "--month", "2025-10"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert cli.main(base + [
        "gap", "--product", "DAP", "--crop-year", "2025-26", "--season", "kharif",
        "--as-of", "2025-12-31",
    ]) == 0
    gap = json.loads(capsys.readouterr().out)
    assert gap["band"] == "comfortable"

    # The first projection (struck before the slip) is what the
    # second one supersedes — compute it first, as the API flow does.
    assert cli.main(base + [
        "projection", "--product", "DAP", "--crop-year", "2025-26",
        "--season", "rabi", "--as-of", "2025-09-30",
    ]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["assumption_changes"] == []

    assert cli.main(base + [
        "projection", "--product", "DAP", "--crop-year", "2025-26",
        "--season", "rabi", "--as-of", "2025-11-30",
    ]) == 0
    projection = json.loads(capsys.readouterr().out)
    assert projection["closing_tonnes"] == 8832147.348
    kinds = {c["kind"] for c in projection["assumption_changes"]}
    assert "slipped_unlanded" in kinds

    assert cli.main(base + [
        "verify-projection", "--product", "DAP", "--crop-year", "2025-26",
        "--season", "rabi",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert cli.main(base + [
        "positions", "--product", "GLYPHOSATE",
    ]) == 2
    capsys.readouterr()
