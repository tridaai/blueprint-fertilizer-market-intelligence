"""Round 6: competitor & market-share intelligence — the 720
tracked points promoted to provenance-carrying observations
(a point without source or date refused), share arithmetic
hand-verified for two district-product-seasons against an
independent re-derivation from the stored facts, the stale
exclusion exact at a late read date (named on the artefact),
the all-stale `not_current` state, the no-observations state,
movement re-performance with provenance, tamper detection,
and API/CLI parity.

The re-derivation below states the share pack's rules again
from the stored facts alone — region observed structure over
the season window, Kaveri's home-market anchor as the
region's R2 demand total, the district's recorded market
distributed by the structure shares, Kaveri as the residual,
freshness at 200 days for field tracking — and compares the
artefact figure for figure.
"""

import json
import sqlite3
from datetime import date

import pytest

from fertilizer_intelligence import demand_rules
from fertilizer_intelligence.generator import CROP_YEARS, SEASONS
from fertilizer_intelligence.share import observation_from_point

AS_OF = "2026-04-15"
FRESHNESS_DAYS = 200


def _month_end(month):
    year, mon = int(month[:4]), int(month[5:7])
    if mon == 12:
        return f"{year}-12-31"
    from datetime import timedelta

    return (date(year, mon + 1, 1) - timedelta(days=1)).isoformat()


def _season_of(month):
    windows = [
        (cy, s, demand_rules.season_price_window(cy, s))
        for cy in CROP_YEARS for s in SEASONS
    ]
    opening = [(cy, s) for cy, s, w in windows if w[0] == month]
    if opening:
        return opening[0]
    containing = [(cy, s) for cy, s, w in windows if w[0] <= month <= w[-1]]
    return containing[0] if containing else (None, None)


def _spread(total, window):
    share = round(total / len(window), 3)
    return {
        m: (round(total - share * (len(window) - 1), 3) if i == len(window) - 1
            else share)
        for i, m in enumerate(window)
    }


def _head(rows, id_key):
    superseded = {r["supersedes"] for r in rows if r["supersedes"]}
    heads = [r for r in rows if r[id_key] not in superseded]
    return heads[0] if heads else None


def derive_share(service, district_id, product, crop_year, season, as_of):
    """The pack's construction, stated again from the facts."""
    store = service.store
    window = demand_rules.season_price_window(crop_year, season)
    region = next(
        d["region"] for d in store.list_districts()
        if d["district_id"] == district_id
    )
    region_districts = sorted(
        d["district_id"] for d in store.list_districts() if d["region"] == region
    )
    estimates = {
        d: _head(store.list_estimates(d, product, crop_year, season),
                 "estimate_id")["total_tonnes"]
        for d in region_districts
    }
    anchor = _spread(round(sum(estimates.values()), 3), window)
    consumption = next(
        r["quantity_tonnes"]
        for r in store.consumption_facts(district_id, crop_year, season, product)
    )
    market = _spread(consumption, window)
    demand = _spread(estimates[district_id], window)
    points = [
        p for p in store.competitor_points(region=region, product=product)
        if _season_of(p["month"]) == (crop_year, season)
    ]
    by_month = {}
    for point in points:
        by_month.setdefault(point["month"], []).append(point)

    months = {}
    for month in window:
        month_points = by_month.get(month, [])
        observed_region = round(
            sum(p["volume_tonnes"] for p in month_points) + anchor[month], 3)
        competitors = {}
        for point in month_points:
            structure = round(point["volume_tonnes"] / observed_region, 6)
            competitors[point["competitor"]] = round(
                market[month] * structure, 3)
        age_stale = any(
            (date.fromisoformat(as_of) - date.fromisoformat(p["as_of"])).days
            > FRESHNESS_DAYS
            for p in month_points
        )
        if _month_end(month) > as_of:
            status = "after_read_date"
        elif month_points and age_stale:
            status = "stale"
        elif not month_points:
            status = "no_observation"
        else:
            status = "fresh"
        months[month] = {
            "status": status,
            "competitors": competitors,
            "kaveri": round(market[month] - sum(competitors.values()), 3),
            "market": market[month],
            "demand": demand[month],
        }

    def reading(chosen):
        kaveri = round(sum(months[m]["kaveri"] for m in chosen), 3)
        observed = round(sum(months[m]["market"] for m in chosen), 3)
        demand_total = round(sum(months[m]["demand"] for m in chosen), 3)
        sellers = {"Kaveri Agro Inputs": kaveri}
        for point in points:
            sellers.setdefault(point["competitor"], 0.0)
        for month in chosen:
            for name, volume in months[month]["competitors"].items():
                sellers[name] = round(sellers.get(name, 0.0) + volume, 3)
        return {
            name: (
                volume,
                round(100.0 * volume / observed, 4),
                round(100.0 * volume / demand_total, 4),
            )
            for name, volume in sellers.items()
        }

    headline_months = [
        m for m in window if months[m]["status"] in ("fresh", "no_observation")
    ]
    full_months = [
        m for m in window if months[m]["status"] != "after_read_date"
    ]
    return {
        "months": months,
        "headline": reading(headline_months) if points and headline_months else None,
        "full_season": reading(full_months) if points else None,
        "headline_months": headline_months,
    }


def _assert_reading(actual, expected):
    assert actual is not None and expected is not None
    sellers = {s["seller"]: s for s in [actual["kaveri"]] + actual["competitors"]}
    assert set(sellers) == set(expected)
    for name, (volume, pct_observed, pct_demand) in expected.items():
        got = sellers[name]
        assert got["volume_tonnes"] == volume, name
        assert got["share_of_observed_market_pct"] == pct_observed, name
        assert got["share_of_total_demand_pct"] == pct_demand, name
    # The observed reading is a true share: it sums to 100.
    assert abs(sum(s["share_of_observed_market_pct"] for s in sellers.values())
               - 100.0) < 0.01


# -- observations ---------------------------------------------------------------


def test_observations_built_with_provenance(service):
    summary = service.build_competitor_observations()
    assert summary == {
        "observations_stored": 720, "already_present": 0,
        "observations_total": 720,
    }
    observations = service.list_competitor_observations()
    assert len(observations) == 720
    for observation in observations:
        assert observation["source"] == "competitor_field_tracking"
        assert observation["as_of"]  # the observation date is on its face
        assert observation["source_class"] == "field_tracking"
    by_key = {
        (o["competitor"], o["region"], o["product"], o["month"]): o
        for o in observations
    }
    # Unique attribution: November opens rabi; June opens
    # kharif; May belongs to no tracked season.
    nov = by_key[("Sagar Chemicals", "north", "DAP", "2025-11")]
    assert (nov["crop_year"], nov["season"]) == ("2025-26", "rabi")
    jun = by_key[("Sagar Chemicals", "north", "DAP", "2025-06")]
    assert (jun["crop_year"], jun["season"]) == ("2025-26", "kharif")
    may = by_key[("Sagar Chemicals", "north", "DAP", "2025-05")]
    assert may["crop_year"] is None and may["season"] is None
    # District coverage is the region's districts.
    assert nov["district_ids"] == ["DST-KAR", "DST-LKO", "DST-LUD"]
    # Re-performance and idempotency.
    assert service.verify_competitor_observation(nov["observation_id"]) == []
    assert service.build_competitor_observations()["observations_stored"] == 0


def test_observation_without_provenance_is_refused(service):
    point = {
        "competitor": "AgroNutrient Ltd", "region": "north",
        "product": "DAP", "month": "2025-09", "volume_tonnes": 100.0,
        "price": 27000.0, "source": "competitor_field_tracking",
        "as_of": "2025-09-30",
    }
    districts = service.store.list_districts()
    with pytest.raises(ValueError, match="without its source"):
        observation_from_point({**point, "source": ""}, districts)
    with pytest.raises(ValueError, match="without its source"):
        observation_from_point(
            {k: v for k, v in point.items() if k != "source"}, districts)
    with pytest.raises(ValueError, match="without its observation date"):
        observation_from_point({**point, "as_of": " "}, districts)
    with pytest.raises(ValueError, match="without its observation date"):
        observation_from_point(
            {k: v for k, v in point.items() if k != "as_of"}, districts)
    # Nothing was stored by the refused builds.
    assert service.store.list_competitor_observations() == []


# -- shares ---------------------------------------------------------------------


@pytest.mark.parametrize("district,product,crop_year,season", [
    ("DST-LUD", "DAP", "2025-26", "kharif"),
    ("DST-GUN", "UREA", "2024-25", "rabi"),
])
def test_share_arithmetic_hand_verified(service, district, product, crop_year, season):
    share = service.market_share(district, product, crop_year, season)
    assert share["status"] == "current"
    assert share["headline_note"] == ""
    expected = derive_share(service, district, product, crop_year, season,
                            share["as_of"])
    _assert_reading(share["headline"], expected["headline"])
    _assert_reading(share["full_season"], expected["full_season"])
    # At the season close nothing is stale: headline == full season.
    assert share["headline"]["months"] == share["full_season"]["months"]
    assert share["headline"]["excluded_observations"] == []
    # Provenance panel: every observation in scope, with source + date.
    assert share["provenance"]
    assert all(p["source"] and p["as_of"] for p in share["provenance"])
    assert share["kaveri_basis"].startswith("residual:")
    assert service.verify_share(share["share_id"]) == []
    # Compute-or-return: a second call stores nothing new.
    assert service.market_share(district, product, crop_year, season)["share_id"] \
        == share["share_id"]
    assert len(service.store.list_shares(district, product, crop_year, season)) == 1


def test_stale_exclusion_exact_and_named(service):
    share = service.market_share(
        "DST-LUD", "DAP", "2025-26", "kharif", "2026-03-31")
    assert share["status"] == "current"
    # June–August 2025 have aged past the 200-day window at
    # 2026-03-31; September–November are fresh; the exclusion
    # is the nine observations of the three stale months.
    expected_ids = {
        f"OBS-{slug}-north-DAP-2025-{month}"
        for slug in ("AGRONUTRIENT-LTD", "BHARATFERT-CORP", "SAGAR-CHEMICALS")
        for month in ("06", "07", "08")
    }
    excluded = share["headline"]["excluded_observations"]
    assert {e["observation_id"] for e in excluded} == expected_ids
    assert all(e["reason"] == "stale" for e in excluded)
    assert share["headline_note"] == "headline excludes 9 stale observations"
    assert share["headline"]["stale_note"] == share["headline_note"]
    assert share["headline"]["months"] == ["2025-09", "2025-10", "2025-11"]
    # The excluded months are badged stale on the artefact;
    # the full-season reading still carries them, labelled.
    statuses = {m["month"]: m["status"] for m in share["months"]}
    assert statuses == {
        "2025-06": "stale", "2025-07": "stale", "2025-08": "stale",
        "2025-09": "fresh", "2025-10": "fresh",
        "2025-11": "no_observation",
    }
    assert share["full_season"]["basis"] == "full_season_including_stale"
    assert share["full_season"]["months"] == [
        "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11"]
    expected = derive_share(
        service, "DST-LUD", "DAP", "2025-26", "kharif", "2026-03-31")
    _assert_reading(share["headline"], expected["headline"])
    _assert_reading(share["full_season"], expected["full_season"])
    # The stale-exclusion read serves exactly the same named set.
    read = service.share_stale_exclusions(
        "DST-LUD", "DAP", "2025-26", "kharif", "2026-03-31")
    assert read["stale_count"] == 9
    assert {e["observation_id"] for e in read["excluded_observations"]} \
        == expected_ids
    assert service.verify_share(share["share_id"]) == []


def test_all_stale_reads_not_current(service):
    share = service.market_share(
        "DST-LUD", "DAP", "2024-25", "rabi", "2026-03-31")
    assert share["status"] == "not_current"
    assert share["headline"] is None
    assert all(m["status"] == "stale" for m in share["months"])
    # The full-season figures are still there to inspect —
    # labelled as including stale, never presented as the
    # current share.
    assert share["full_season"]["basis"] == "full_season_including_stale"
    assert service.verify_share(share["share_id"]) == []
    # Read at its own season close, the same cell is current.
    close = service.market_share("DST-LUD", "DAP", "2024-25", "rabi")
    assert close["status"] == "current" and close["headline"] is not None


def test_no_observations_is_a_named_state(service):
    share = service.market_share("DST-LUD", "GLYPHOSATE", "2025-26", "kharif")
    assert share["status"] == "no_observations"
    assert share["headline"] is None and share["full_season"] is None
    assert share["provenance"] == []
    assert service.verify_share(share["share_id"]) == []


# -- movements --------------------------------------------------------------------


def test_movement_reperforms_with_provenance(service):
    movement = service.share_movement("DST-LUD", "DAP", "kharif", AS_OF)
    assert movement["from_crop_year"] == "2024-25"
    assert movement["to_crop_year"] == "2025-26"
    assert movement["basis"] == "full_season_including_stale"
    shares = {
        year: service.market_share("DST-LUD", "DAP", year, "kharif")
        for year in ("2024-25", "2025-26")
    }
    assert movement["share_ids"] == {
        year: shares[year]["share_id"] for year in shares
    }

    def observed_pct(share):
        reading = share["full_season"]
        out = {reading["kaveri"]["seller"]:
               reading["kaveri"]["share_of_observed_market_pct"]}
        for competitor in reading["competitors"]:
            out[competitor["seller"]] = competitor["share_of_observed_market_pct"]
        return out

    before, after = observed_pct(shares["2024-25"]), observed_pct(shares["2025-26"])
    rows = {r["seller"]: r for r in movement["rows"]}
    assert set(rows) == set(before) == set(after)
    for seller, row in rows.items():
        assert row["share_from_pct"] == before[seller]
        assert row["share_to_pct"] == after[seller]
        assert row["change_pp"] == round(after[seller] - before[seller], 4)
    biggest = max(rows.values(), key=lambda r: abs(r["change_pp"]))
    assert movement["biggest_mover"]["seller"] == biggest["seller"]
    assert movement["biggest_mover"]["change_pp"] == biggest["change_pp"]
    # Provenance carried: the mover's observation ids in both years.
    mover = movement["biggest_mover"]
    for year, key in (("2024-25", "observation_ids_from"),
                      ("2025-26", "observation_ids_to")):
        expected = sorted(
            p["observation_id"] for p in shares[year]["provenance"]
            if p["competitor"] == mover["seller"]
        )
        assert mover[key] == expected
    assert service.verify_share_movement(movement["movement_id"]) == []
    # Compute-or-return.
    assert service.share_movement(
        "DST-LUD", "DAP", "kharif", AS_OF)["movement_id"] == movement["movement_id"]
    assert len(service.store.list_share_movements("DST-LUD", "DAP", "kharif")) == 1


# -- tamper ---------------------------------------------------------------------


def test_share_tamper_is_detected(service, settings):
    share = service.market_share("DST-LUD", "DAP", "2025-26", "kharif")
    assert service.verify_share(share["share_id"]) == []
    db = sqlite3.connect(settings.sqlite_path)
    payload = json.loads(
        db.execute(
            "SELECT payload FROM market_shares WHERE share_id = ?",
            (share["share_id"],),
        ).fetchone()[0]
    )
    payload["headline"]["kaveri"]["volume_tonnes"] += 100.0
    db.execute(
        "UPDATE market_shares SET payload = ? WHERE share_id = ?",
        (json.dumps(payload), share["share_id"]),
    )
    db.commit()
    db.close()
    assert service.verify_share(share["share_id"]), \
        "a tampered share figure must fail verification"


def test_movement_tamper_is_detected(service, settings):
    movement = service.share_movement("DST-LUD", "DAP", "kharif", AS_OF)
    assert service.verify_share_movement(movement["movement_id"]) == []
    db = sqlite3.connect(settings.sqlite_path)
    payload = json.loads(
        db.execute(
            "SELECT payload FROM share_movements WHERE movement_id = ?",
            (movement["movement_id"],),
        ).fetchone()[0]
    )
    payload["rows"][0]["change_pp"] += 1.0
    db.execute(
        "UPDATE share_movements SET payload = ? WHERE movement_id = ?",
        (json.dumps(payload), movement["movement_id"]),
    )
    db.commit()
    db.close()
    assert service.verify_share_movement(movement["movement_id"])


# -- surfaces ---------------------------------------------------------------------


def test_api_parity_round6(service, settings):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        built = client.post("/competitor-observations/build").json()
        assert built["observations_stored"] == 720
        observations = client.get(
            "/competitor-observations",
            params={"region": "north", "product": "DAP", "season": "kharif"},
        ).json()
        assert observations and all(
            o["season"] == "kharif" for o in observations)
        one = observations[0]
        got = client.get(f"/competitor-observations/{one['observation_id']}").json()
        assert got["observation_id"] == one["observation_id"]
        assert got["source"] and got["as_of"]
        verify = client.get(
            f"/competitor-observations/{one['observation_id']}/verify").json()
        assert verify["ok"] is True
        assert client.get("/competitor-observations/OBS-nope").status_code == 404

        share = client.post("/shares", json={
            "district_id": "DST-LUD", "product": "DAP",
            "crop_year": "2025-26", "season": "kharif",
        }).json()
        assert share["status"] == "current"
        fetched = client.get("/shares/DST-LUD/DAP/2025-26/kharif").json()
        assert fetched["share_id"] == share["share_id"]
        share_verify = client.get(
            "/shares/DST-LUD/DAP/2025-26/kharif/verify").json()
        assert share_verify["ok"] is True

        late = client.get(
            "/shares/DST-LUD/DAP/2025-26/kharif",
            params={"as_of": "2026-03-31"},
        )
        assert late.status_code == 404  # not computed yet at that read date
        client.post("/shares", json={
            "district_id": "DST-LUD", "product": "DAP",
            "crop_year": "2025-26", "season": "kharif", "as_of": "2026-03-31",
        })
        stale = client.get(
            "/shares/DST-LUD/DAP/2025-26/kharif/stale",
            params={"as_of": "2026-03-31"},
        ).json()
        assert stale["stale_count"] == 9
        assert stale["headline_note"] == \
            "headline excludes 9 stale observations"

        movement = client.post("/share-movements", json={
            "district_id": "DST-LUD", "product": "DAP", "season": "kharif",
            "as_of": AS_OF,
        }).json()
        assert movement["biggest_mover"]["seller"]
        fetched_mv = client.get("/share-movements/DST-LUD/DAP/kharif").json()
        assert fetched_mv["movement_id"] == movement["movement_id"]
        mv_verify = client.get(
            "/share-movements/DST-LUD/DAP/kharif/verify").json()
        assert mv_verify["ok"] is True
        assert client.get("/shares/DST-LUD/DAP/2025-26/rabi").status_code in (200, 404)


def test_cli_parity_round6(service, settings, capsys):
    from fertilizer_intelligence import cli

    base = [
        "--db", str(settings.sqlite_path),
        "--migrations", str(settings.migrations_dir),
    ]
    assert cli.main(base + ["observations-build"]) == 0
    built = json.loads(capsys.readouterr().out)
    assert built["observations_stored"] == 720

    assert cli.main(base + [
        "observations", "--region", "north", "--product", "DAP",
        "--season", "rabi",
    ]) == 0
    observations = json.loads(capsys.readouterr().out)
    assert observations and all(o["season"] == "rabi" for o in observations)
    one = observations[0]

    assert cli.main(base + ["observation", "--observation-id", one["observation_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["observation_id"] == one["observation_id"]

    assert cli.main(base + ["verify-observation", "--observation-id", one["observation_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert cli.main(base + [
        "share", "--district", "DST-LUD", "--product", "DAP",
        "--crop-year", "2025-26", "--season", "kharif",
    ]) == 0
    share = json.loads(capsys.readouterr().out)
    assert share["status"] == "current"

    assert cli.main(base + [
        "verify-share", "--district", "DST-LUD", "--product", "DAP",
        "--crop-year", "2025-26", "--season", "kharif",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert cli.main(base + [
        "share-stale", "--district", "DST-LUD", "--product", "DAP",
        "--crop-year", "2025-26", "--season", "kharif", "--as-of", "2026-03-31",
    ]) == 0
    stale = json.loads(capsys.readouterr().out)
    assert stale["stale_count"] == 9

    assert cli.main(base + [
        "share-movement", "--district", "DST-LUD", "--product", "DAP",
        "--season", "kharif", "--as-of", AS_OF,
    ]) == 0
    movement = json.loads(capsys.readouterr().out)
    assert movement["biggest_mover"]["seller"]

    assert cli.main(base + [
        "verify-share-movement", "--district", "DST-LUD", "--product", "DAP",
        "--season", "kharif",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert cli.main(base + ["observation", "--observation-id", "OBS-nope"]) == 2
    capsys.readouterr()
