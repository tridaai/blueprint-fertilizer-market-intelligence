"""The market data store port.

One port, two dialects: SQLite for the local/offline profile,
Postgres 16 (via psycopg) when ``DATABASE_URL`` is set. The store is
**insert-only**: it exposes inserts and reads, and no update or
delete verb exists — a corrected figure is a new fact under a new
``as_of``, so history is never rewritten.

All facts carry provenance (``source``, ``as_of``) at the row level;
the models refuse a fact without them before it reaches the store.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import models
from .config import Settings
from .migrations import run_migrations

_FACT_TABLES = [
    "area_facts",
    "monsoon_facts",
    "soil_facts",
    "consumption_facts",
    "price_points",
    "import_arrivals",
    "supply_facts",
    "competitor_points",
    "policy_events",
    "field_reports",
]


class MarketStore:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._dialect = "postgres" if settings.use_postgres else "sqlite"
        self._paramstyle = "format" if settings.use_postgres else "qmark"
        self._ph = "%s" if settings.use_postgres else "?"
        self._conn = self._connect()
        run_migrations(
            self._conn, settings.migrations_dir, self._dialect, self._paramstyle
        )

    def _connect(self):
        if self._settings.use_postgres:
            import psycopg
            from psycopg.rows import dict_row

            return psycopg.connect(self._settings.database_url, row_factory=dict_row)
        path = Path(self._settings.sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # The API serves requests from a threadpool; the connection
        # is shared deliberately (single-process app, writes are
        # insert-only and serialized by the driver).
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # -- internal helpers -------------------------------------------------

    def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self._conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

    def _insert_many(self, table: str, columns: list[str], rows: list[tuple]) -> int:
        placeholders = ", ".join([self._ph] * len(columns))
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
        self._conn.executemany(sql, rows)
        self._conn.commit()
        return len(rows)

    # -- writes (insert-only) ----------------------------------------------

    def insert_districts(self, districts: list[models.District]) -> int:
        return self._insert_many(
            "districts",
            ["district_id", "name", "state", "region"],
            [(d.district_id, d.name, d.state, d.region) for d in districts],
        )

    def insert_area_facts(self, facts: list[models.AreaFact]) -> int:
        return self._insert_many(
            "area_facts",
            ["district_id", "crop_year", "season", "crop", "area_ha", "source", "as_of"],
            [(f.district_id, f.crop_year, f.season, f.crop, f.area_ha, f.source, f.as_of) for f in facts],
        )

    def insert_monsoon_facts(self, facts: list[models.MonsoonFact]) -> int:
        return self._insert_many(
            "monsoon_facts",
            ["district_id", "crop_year", "season", "deviation_pct", "source", "as_of"],
            [(f.district_id, f.crop_year, f.season, f.deviation_pct, f.source, f.as_of) for f in facts],
        )

    def insert_soil_facts(self, facts: list[models.SoilFact]) -> int:
        return self._insert_many(
            "soil_facts",
            ["district_id", "nutrient", "status", "source", "as_of"],
            [(f.district_id, f.nutrient, f.status, f.source, f.as_of) for f in facts],
        )

    def insert_application_rates(self, rates: list[models.ApplicationRate]) -> int:
        return self._insert_many(
            "application_rates",
            ["crop", "product", "rate_kg_ha"],
            [(r.crop, r.product, r.rate_kg_ha) for r in rates],
        )

    def insert_consumption_facts(self, facts: list[models.ConsumptionFact]) -> int:
        return self._insert_many(
            "consumption_facts",
            ["district_id", "crop_year", "season", "product", "quantity_tonnes", "source", "as_of"],
            [(f.district_id, f.crop_year, f.season, f.product, f.quantity_tonnes, f.source, f.as_of) for f in facts],
        )

    def insert_price_points(self, points: list[models.PricePoint]) -> int:
        return self._insert_many(
            "price_points",
            ["series_kind", "item", "month", "price", "unit", "source", "as_of"],
            [(p.series_kind, p.item, p.month, p.price, p.unit, p.source, p.as_of) for p in points],
        )

    def insert_import_arrivals(self, arrivals: list[models.ImportArrival]) -> int:
        return self._insert_many(
            "import_arrivals",
            ["shipment_id", "product", "expected_month", "arrived_month", "quantity_tonnes", "origin", "source", "as_of"],
            [(a.shipment_id, a.product, a.expected_month, a.arrived_month, a.quantity_tonnes, a.origin, a.source, a.as_of) for a in arrivals],
        )

    def insert_supply_facts(self, facts: list[models.SupplyFact]) -> int:
        return self._insert_many(
            "supply_facts",
            ["product", "month", "planned_tonnes", "actual_tonnes", "source", "as_of"],
            [(f.product, f.month, f.planned_tonnes, f.actual_tonnes, f.source, f.as_of) for f in facts],
        )

    def insert_competitor_points(self, points: list[models.CompetitorPoint]) -> int:
        return self._insert_many(
            "competitor_points",
            ["competitor", "region", "product", "month", "volume_tonnes", "price", "source", "as_of"],
            [(p.competitor, p.region, p.product, p.month, p.volume_tonnes, p.price, p.source, p.as_of) for p in points],
        )

    def insert_policy_events(self, events: list[models.PolicyEvent]) -> int:
        return self._insert_many(
            "policy_events",
            ["event_id", "date", "kind", "title", "detail", "expected_impact", "impacted_products", "source", "as_of"],
            [(e.event_id, e.date, e.kind, e.title, e.detail, e.expected_impact, json.dumps(e.impacted_products), e.source, e.as_of) for e in events],
        )

    def insert_field_reports(self, reports: list[models.FieldReport]) -> int:
        return self._insert_many(
            "field_reports",
            ["report_id", "reporter", "district_id", "date", "signal_kind", "product", "detail", "source", "as_of"],
            [(r.report_id, r.reporter, r.district_id, r.date, r.signal_kind, r.product, r.detail, r.source, r.as_of) for r in reports],
        )

    def put_manifest(self, manifest: dict, generator_version: str) -> None:
        self._conn.execute(
            f"INSERT INTO generator_manifest (id, manifest, generator_version) VALUES (1, {self._ph}, {self._ph})",
            (json.dumps(manifest, sort_keys=True), generator_version),
        )
        self._conn.commit()

    # -- reads ---------------------------------------------------------------

    def get_manifest(self) -> dict | None:
        rows = self._rows("SELECT manifest FROM generator_manifest WHERE id = 1")
        return json.loads(rows[0]["manifest"]) if rows else None

    def list_districts(self) -> list[dict]:
        return self._rows("SELECT * FROM districts ORDER BY district_id")

    def area_facts(self, district_id=None, crop_year=None, season=None) -> list[dict]:
        sql, params = "SELECT * FROM area_facts WHERE 1=1", []
        for column, value in (("district_id", district_id), ("crop_year", crop_year), ("season", season)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        return self._rows(sql + " ORDER BY district_id, crop_year, season, crop", tuple(params))

    def monsoon_facts(self, district_id=None, crop_year=None, season=None) -> list[dict]:
        sql, params = "SELECT * FROM monsoon_facts WHERE 1=1", []
        for column, value in (("district_id", district_id), ("crop_year", crop_year), ("season", season)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        return self._rows(sql + " ORDER BY district_id, crop_year, season", tuple(params))

    def soil_facts(self, district_id=None) -> list[dict]:
        sql, params = "SELECT * FROM soil_facts WHERE 1=1", []
        if district_id is not None:
            sql += f" AND district_id = {self._ph}"
            params.append(district_id)
        return self._rows(sql + " ORDER BY district_id, nutrient", tuple(params))

    def application_rates(self) -> list[dict]:
        return self._rows("SELECT * FROM application_rates ORDER BY crop, product")

    def consumption_facts(self, district_id=None, crop_year=None, season=None, product=None) -> list[dict]:
        sql, params = "SELECT * FROM consumption_facts WHERE 1=1", []
        for column, value in (("district_id", district_id), ("crop_year", crop_year), ("season", season), ("product", product)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        return self._rows(sql + " ORDER BY district_id, crop_year, season, product", tuple(params))

    def price_points(self, series_kind=None, item=None) -> list[dict]:
        sql, params = "SELECT * FROM price_points WHERE 1=1", []
        for column, value in (("series_kind", series_kind), ("item", item)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        return self._rows(sql + " ORDER BY series_kind, item, month", tuple(params))

    def import_arrivals(self, product=None) -> list[dict]:
        sql, params = "SELECT * FROM import_arrivals WHERE 1=1", []
        if product is not None:
            sql += f" AND product = {self._ph}"
            params.append(product)
        return self._rows(sql + " ORDER BY shipment_id", tuple(params))

    def supply_facts(self, product=None) -> list[dict]:
        sql, params = "SELECT * FROM supply_facts WHERE 1=1", []
        if product is not None:
            sql += f" AND product = {self._ph}"
            params.append(product)
        return self._rows(sql + " ORDER BY product, month", tuple(params))

    def competitor_points(self, competitor=None, region=None, product=None) -> list[dict]:
        sql, params = "SELECT * FROM competitor_points WHERE 1=1", []
        for column, value in (("competitor", competitor), ("region", region), ("product", product)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        return self._rows(sql + " ORDER BY competitor, region, product, month", tuple(params))

    def policy_events(self) -> list[dict]:
        rows = self._rows("SELECT * FROM policy_events ORDER BY date, event_id")
        for row in rows:
            row["impacted_products"] = json.loads(row["impacted_products"])
        return rows

    def field_reports(self, district_id=None, signal_kind=None) -> list[dict]:
        sql, params = "SELECT * FROM field_reports WHERE 1=1", []
        for column, value in (("district_id", district_id), ("signal_kind", signal_kind)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        return self._rows(sql + " ORDER BY date, report_id", tuple(params))

    # -- demand artefacts (R2, insert-only) ------------------------------
    # Estimates, outlooks and narratives are artefacts, not facts:
    # they are computed from facts and carry the fingerprint of the
    # fact set they were computed from. They are still insert-only —
    # a recomputation is a new row linked by supersedes.

    def insert_estimate(self, estimate: dict, contributions: list[dict]) -> None:
        self._conn.execute(
            f"INSERT INTO demand_estimates (estimate_id, district_id, product, "
            f"crop_year, season, status, base_tonnes, total_tonnes, missing_drivers, "
            f"rules_version, rate_table_version, fact_fingerprint, as_of, supersedes) "
            f"VALUES ({', '.join([self._ph] * 14)})",
            (
                estimate["estimate_id"], estimate["district_id"], estimate["product"],
                estimate["crop_year"], estimate["season"], estimate["status"],
                estimate["base_tonnes"], estimate["total_tonnes"],
                json.dumps(estimate["missing_drivers"]), estimate["rules_version"],
                estimate["rate_table_version"], estimate["fact_fingerprint"],
                estimate["as_of"], estimate["supersedes"],
            ),
        )
        self._conn.executemany(
            f"INSERT INTO demand_contributions (estimate_id, line_no, driver, status, "
            f"factor, delta_tonnes, value_after_tonnes, inputs) "
            f"VALUES ({', '.join([self._ph] * 8)})",
            [
                (
                    estimate["estimate_id"], line["line_no"], line["driver"],
                    line["status"], line["factor"], line["delta_tonnes"],
                    line["value_after_tonnes"], json.dumps(line["inputs"]),
                )
                for line in contributions
            ],
        )
        self._conn.commit()

    def _estimate_row(self, row: dict) -> dict:
        row["missing_drivers"] = json.loads(row["missing_drivers"])
        return row

    def get_estimate(self, estimate_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM demand_estimates WHERE estimate_id = {self._ph}",
            (estimate_id,),
        )
        return self._estimate_row(rows[0]) if rows else None

    def list_estimates(self, district_id=None, product=None, crop_year=None, season=None) -> list[dict]:
        sql, params = "SELECT * FROM demand_estimates WHERE 1=1", []
        for column, value in (
            ("district_id", district_id), ("product", product),
            ("crop_year", crop_year), ("season", season),
        ):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(sql + " ORDER BY district_id, product, crop_year, season, estimate_id", tuple(params))
        return [self._estimate_row(row) for row in rows]

    def estimate_contributions(self, estimate_id: str) -> list[dict]:
        rows = self._rows(
            f"SELECT * FROM demand_contributions WHERE estimate_id = {self._ph} ORDER BY line_no",
            (estimate_id,),
        )
        for row in rows:
            row["inputs"] = json.loads(row["inputs"])
        return rows

    def insert_outlook(self, outlook: dict) -> None:
        self._conn.execute(
            f"INSERT INTO season_outlooks (outlook_id, crop_year, season, status, "
            f"estimate_count, partial_count, total_tonnes, product_rollups, "
            f"estimate_ids, rules_version, fact_fingerprint, as_of, supersedes) "
            f"VALUES ({', '.join([self._ph] * 13)})",
            (
                outlook["outlook_id"], outlook["crop_year"], outlook["season"],
                outlook["status"], outlook["estimate_count"], outlook["partial_count"],
                outlook["total_tonnes"], json.dumps(outlook["product_rollups"]),
                json.dumps(outlook["estimate_ids"]), outlook["rules_version"],
                outlook["fact_fingerprint"], outlook["as_of"], outlook["supersedes"],
            ),
        )
        self._conn.commit()

    def _outlook_row(self, row: dict) -> dict:
        row["product_rollups"] = json.loads(row["product_rollups"])
        row["estimate_ids"] = json.loads(row["estimate_ids"])
        return row

    def get_outlook(self, outlook_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM season_outlooks WHERE outlook_id = {self._ph}",
            (outlook_id,),
        )
        return self._outlook_row(rows[0]) if rows else None

    def list_outlooks(self, crop_year=None, season=None) -> list[dict]:
        sql, params = "SELECT * FROM season_outlooks WHERE 1=1", []
        for column, value in (("crop_year", crop_year), ("season", season)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(sql + " ORDER BY crop_year, season, outlook_id", tuple(params))
        return [self._outlook_row(row) for row in rows]

    def insert_narrative(self, narrative: dict) -> None:
        self._conn.execute(
            f"INSERT INTO outlook_narratives (narrative_id, outlook_id, text, "
            f"model_profile, model_name, figures, as_of) "
            f"VALUES ({', '.join([self._ph] * 7)})",
            (
                narrative["narrative_id"], narrative["outlook_id"], narrative["text"],
                narrative["model_profile"], narrative["model_name"],
                json.dumps(narrative["figures"]), narrative["as_of"],
            ),
        )
        self._conn.commit()

    def get_narrative(self, narrative_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM outlook_narratives WHERE narrative_id = {self._ph}",
            (narrative_id,),
        )
        if not rows:
            return None
        row = rows[0]
        row["figures"] = json.loads(row["figures"])
        return row

    def list_narratives(self, outlook_id=None) -> list[dict]:
        sql, params = "SELECT * FROM outlook_narratives WHERE 1=1", []
        if outlook_id is not None:
            sql += f" AND outlook_id = {self._ph}"
            params.append(outlook_id)
        rows = self._rows(sql + " ORDER BY narrative_id", tuple(params))
        for row in rows:
            row["figures"] = json.loads(row["figures"])
        return rows

    # -- price watch artefacts (R3, insert-only) -----------------------
    # Movements and alerts are computed artefacts; alert state is a
    # fold of alert_acts and is never stored, so there is no update
    # path for it anywhere.

    def insert_movement(self, movement: dict) -> None:
        self._conn.execute(
            f"INSERT INTO price_movements (movement_id, series_kind, item, month, "
            f"price, prev_price, mom_pct, baseline_mean, baseline_pct, "
            f"baseline_months, fact_ids, rules_version, fact_fingerprint, as_of) "
            f"VALUES ({', '.join([self._ph] * 14)})",
            (
                movement["movement_id"], movement["series_kind"], movement["item"],
                movement["month"], movement["price"], movement["prev_price"],
                movement["mom_pct"], movement["baseline_mean"], movement["baseline_pct"],
                json.dumps(movement["baseline_months"]), json.dumps(movement["fact_ids"]),
                movement["rules_version"], movement["fact_fingerprint"], movement["as_of"],
            ),
        )
        self._conn.commit()

    def _movement_row(self, row: dict) -> dict:
        row["baseline_months"] = json.loads(row["baseline_months"])
        row["fact_ids"] = json.loads(row["fact_ids"])
        return row

    def get_movement(self, movement_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM price_movements WHERE movement_id = {self._ph}",
            (movement_id,),
        )
        return self._movement_row(rows[0]) if rows else None

    def list_movements(self, series_kind=None, item=None) -> list[dict]:
        sql, params = "SELECT * FROM price_movements WHERE 1=1", []
        for column, value in (("series_kind", series_kind), ("item", item)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(sql + " ORDER BY series_kind, item, month", tuple(params))
        return [self._movement_row(row) for row in rows]

    def insert_alert(self, alert: dict) -> None:
        self._conn.execute(
            f"INSERT INTO price_alerts (alert_id, series_kind, item, rule_id, band, "
            f"period_month, movement_ids, figures, rules_version, as_of) "
            f"VALUES ({', '.join([self._ph] * 10)})",
            (
                alert["alert_id"], alert["series_kind"], alert["item"],
                alert["rule_id"], alert["band"], alert["period_month"],
                json.dumps(alert["movement_ids"]), json.dumps(alert["figures"]),
                alert["rules_version"], alert["as_of"],
            ),
        )
        self._conn.commit()

    def _alert_row(self, row: dict) -> dict:
        row["movement_ids"] = json.loads(row["movement_ids"])
        row["figures"] = json.loads(row["figures"])
        return row

    def get_alert(self, alert_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM price_alerts WHERE alert_id = {self._ph}",
            (alert_id,),
        )
        return self._alert_row(rows[0]) if rows else None

    def list_alerts(self, series_kind=None, item=None, rule_id=None) -> list[dict]:
        sql, params = "SELECT * FROM price_alerts WHERE 1=1", []
        for column, value in (("series_kind", series_kind), ("item", item), ("rule_id", rule_id)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(
            sql + " ORDER BY series_kind, item, period_month, rule_id", tuple(params)
        )
        return [self._alert_row(row) for row in rows]

    def insert_alert_act(self, act: dict) -> None:
        self._conn.execute(
            f"INSERT INTO alert_acts (act_id, alert_id, act, actor, note, "
            f"closing_reason, as_of) VALUES ({', '.join([self._ph] * 7)})",
            (
                act["act_id"], act["alert_id"], act["act"], act["actor"],
                act["note"], act["closing_reason"], act["as_of"],
            ),
        )
        self._conn.commit()

    def list_alert_acts(self, alert_id: str) -> list[dict]:
        return self._rows(
            f"SELECT * FROM alert_acts WHERE alert_id = {self._ph} ORDER BY act_id",
            (alert_id,),
        )

    # -- Round 4: supply positions, gaps, projections -----------

    def insert_supply_position(self, position: dict, lines: list[dict]) -> None:
        self._insert_many(
            "supply_positions",
            ["position_id", "product", "month", "opening_tonnes",
             "production_planned_tonnes", "production_actual_tonnes",
             "imports_tonnes", "consumption_tonnes", "closing_tonnes",
             "rules_version", "fact_fingerprint", "as_of", "supersedes",
             "payload"],
            [(
                position["position_id"], position["product"], position["month"],
                position["opening_tonnes"], position["production_planned_tonnes"],
                position["production_actual_tonnes"], position["imports_tonnes"],
                position["consumption_tonnes"], position["closing_tonnes"],
                position["rules_version"], position["fact_fingerprint"],
                position["as_of"], position["supersedes"],
                json.dumps(position),
            )],
        )
        self._insert_many(
            "supply_position_lines",
            ["position_id", "line_no", "component", "status", "tonnes",
             "fact_ids", "inputs"],
            [(
                position["position_id"], line["line_no"], line["component"],
                line["status"], line["tonnes"], json.dumps(line["fact_ids"]),
                json.dumps(line["inputs"]),
            ) for line in lines],
        )

    def _position_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_position(self, position_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM supply_positions WHERE position_id = {self._ph}",
            (position_id,),
        )
        return self._position_row(rows[0]) if rows else None

    def list_positions(self, product=None, month=None) -> list[dict]:
        sql, params = "SELECT * FROM supply_positions WHERE 1=1", []
        for column, value in (("product", product), ("month", month)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(sql + " ORDER BY product, month, position_id", tuple(params))
        return [self._position_row(row) for row in rows]

    def position_lines(self, position_id: str) -> list[dict]:
        rows = self._rows(
            f"SELECT * FROM supply_position_lines WHERE position_id = {self._ph} "
            "ORDER BY line_no",
            (position_id,),
        )
        for row in rows:
            row["fact_ids"] = json.loads(row["fact_ids"])
            row["inputs"] = json.loads(row["inputs"])
        return rows

    def insert_supply_gap(self, gap: dict) -> None:
        self._insert_many(
            "supply_gaps",
            ["gap_id", "product", "crop_year", "season", "as_of", "as_of_month",
             "demand_tonnes", "demand_outlook_id", "available_tonnes",
             "gap_tonnes", "gap_pct_of_demand", "band", "band_basis",
             "rules_version", "fact_fingerprint", "supersedes", "payload"],
            [(
                gap["gap_id"], gap["product"], gap["crop_year"], gap["season"],
                gap["as_of"], gap["as_of_month"], gap["demand_tonnes"],
                gap["demand_outlook_id"], gap["available_tonnes"],
                gap["gap_tonnes"], gap["gap_pct_of_demand"], gap["band"],
                gap["band_basis"], gap["rules_version"],
                gap["fact_fingerprint"], gap["supersedes"], json.dumps(gap),
            )],
        )

    def _gap_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_gap(self, gap_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM supply_gaps WHERE gap_id = {self._ph}", (gap_id,)
        )
        return self._gap_row(rows[0]) if rows else None

    def list_gaps(self, product=None, crop_year=None, season=None) -> list[dict]:
        sql, params = "SELECT * FROM supply_gaps WHERE 1=1", []
        for column, value in (("product", product), ("crop_year", crop_year),
                              ("season", season)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(sql + " ORDER BY product, crop_year, season, as_of_month", tuple(params))
        return [self._gap_row(row) for row in rows]

    def insert_supply_projection(self, projection: dict) -> None:
        self._insert_many(
            "supply_projections",
            ["projection_id", "product", "crop_year", "season", "basis_month",
             "as_of", "status", "opening_tonnes", "closing_tonnes",
             "rules_version", "fact_fingerprint", "supersedes", "payload"],
            [(
                projection["projection_id"], projection["product"],
                projection["crop_year"], projection["season"],
                projection["basis_month"], projection["as_of"],
                projection["status"], projection["opening_tonnes"],
                projection["closing_tonnes"], projection["rules_version"],
                projection["fact_fingerprint"], projection["supersedes"],
                json.dumps(projection),
            )],
        )

    def _projection_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_projection(self, projection_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM supply_projections WHERE projection_id = {self._ph}",
            (projection_id,),
        )
        return self._projection_row(rows[0]) if rows else None

    def list_projections(self, product=None, crop_year=None, season=None) -> list[dict]:
        sql, params = "SELECT * FROM supply_projections WHERE 1=1", []
        for column, value in (("product", product), ("crop_year", crop_year),
                              ("season", season)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(sql + " ORDER BY product, crop_year, season, basis_month", tuple(params))
        return [self._projection_row(row) for row in rows]

    # -- Round 5: policy registry events, impact notes -----------
    # Registrations and notes are artefacts, not facts: computed
    # or recorded against the facts, insert-only, superseding by
    # link, the full artefact carried as a JSON payload.

    def insert_policy_registration(self, event: dict) -> None:
        self._insert_many(
            "policy_registry_events",
            ["registry_id", "event_id", "fact_event_id", "event_class",
             "fact_kind", "title", "effective_from_month",
             "effective_to_month", "products", "districts", "hypothetical",
             "source", "recorded_on", "registered_by", "rules_version",
             "fact_fingerprint", "as_of", "supersedes", "payload"],
            [(
                event["registry_id"], event["event_id"],
                event["fact_event_id"], event["event_class"],
                event["fact_kind"], event["title"],
                event["effective_from_month"], event["effective_to_month"],
                json.dumps(event["products"]), json.dumps(event["districts"]),
                int(event["hypothetical"]), event["source"],
                event["recorded_on"], event["registered_by"],
                event["rules_version"], event["fact_fingerprint"],
                event["as_of"], event["supersedes"], json.dumps(event),
            )],
        )

    def _policy_event_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_policy_registration(self, registry_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM policy_registry_events WHERE registry_id = {self._ph}",
            (registry_id,),
        )
        return self._policy_event_row(rows[0]) if rows else None

    def list_policy_registrations(self, event_id=None) -> list[dict]:
        sql, params = "SELECT * FROM policy_registry_events WHERE 1=1", []
        if event_id is not None:
            sql += f" AND event_id = {self._ph}"
            params.append(event_id)
        rows = self._rows(
            sql + " ORDER BY event_id, effective_from_month, registry_id",
            tuple(params),
        )
        return [self._policy_event_row(row) for row in rows]

    def insert_policy_impact_note(self, note: dict) -> None:
        self._insert_many(
            "policy_impact_notes",
            ["note_id", "registry_id", "event_id", "status", "demand_count",
             "price_point_count", "position_count", "rules_version",
             "fact_fingerprint", "as_of", "supersedes", "payload"],
            [(
                note["note_id"], note["registry_id"], note["event_id"],
                note["status"], len(note["demand_estimate_ids"]),
                sum(s["point_count"] for s in note["price_series"]),
                len(note["position_ids"]), note["rules_version"],
                note["fact_fingerprint"], note["as_of"], note["supersedes"],
                json.dumps(note),
            )],
        )

    def _impact_note_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_policy_impact_note(self, note_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM policy_impact_notes WHERE note_id = {self._ph}",
            (note_id,),
        )
        return self._impact_note_row(rows[0]) if rows else None

    def list_policy_impact_notes(self, registry_id=None) -> list[dict]:
        sql, params = "SELECT * FROM policy_impact_notes WHERE 1=1", []
        if registry_id is not None:
            sql += f" AND registry_id = {self._ph}"
            params.append(registry_id)
        rows = self._rows(sql + " ORDER BY registry_id, note_id", tuple(params))
        return [self._impact_note_row(row) for row in rows]

    # -- Round 6: competitor observations, shares, movements --
    # Observations are artefacts promoted from the tracked
    # points, carrying their provenance on their face; shares
    # and movements are computed artefacts. All insert-only,
    # superseding by link, the full artefact as a JSON payload.

    def insert_competitor_observation(self, observation: dict) -> None:
        self._insert_many(
            "competitor_observations",
            ["observation_id", "competitor", "region", "product", "month",
             "crop_year", "season", "volume_tonnes", "price", "source",
             "as_of", "payload"],
            [(
                observation["observation_id"], observation["competitor"],
                observation["region"], observation["product"],
                observation["month"], observation["crop_year"],
                observation["season"], observation["volume_tonnes"],
                observation["price"], observation["source"],
                observation["as_of"], json.dumps(observation),
            )],
        )

    def _observation_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_competitor_observation(self, observation_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM competitor_observations WHERE observation_id = {self._ph}",
            (observation_id,),
        )
        return self._observation_row(rows[0]) if rows else None

    def list_competitor_observations(
        self, competitor=None, region=None, product=None, season=None
    ) -> list[dict]:
        sql, params = "SELECT * FROM competitor_observations WHERE 1=1", []
        for column, value in (
            ("competitor", competitor), ("region", region),
            ("product", product), ("season", season),
        ):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(
            sql + " ORDER BY competitor, region, product, month", tuple(params)
        )
        return [self._observation_row(row) for row in rows]

    def insert_share(self, share: dict) -> None:
        self._insert_many(
            "market_shares",
            ["share_id", "district_id", "product", "crop_year", "season",
             "as_of", "status", "rules_version", "fact_fingerprint",
             "supersedes", "payload"],
            [(
                share["share_id"], share["district_id"], share["product"],
                share["crop_year"], share["season"], share["as_of"],
                share["status"], share["rules_version"],
                share["fact_fingerprint"], share["supersedes"],
                json.dumps(share),
            )],
        )

    def _share_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_share(self, share_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM market_shares WHERE share_id = {self._ph}",
            (share_id,),
        )
        return self._share_row(rows[0]) if rows else None

    def list_shares(
        self, district_id=None, product=None, crop_year=None, season=None,
        as_of=None,
    ) -> list[dict]:
        sql, params = "SELECT * FROM market_shares WHERE 1=1", []
        for column, value in (
            ("district_id", district_id), ("product", product),
            ("crop_year", crop_year), ("season", season), ("as_of", as_of),
        ):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(
            sql + " ORDER BY district_id, product, crop_year, season, as_of, share_id",
            tuple(params),
        )
        return [self._share_row(row) for row in rows]

    def insert_share_movement(self, movement: dict) -> None:
        self._insert_many(
            "share_movements",
            ["movement_id", "district_id", "product", "season",
             "from_crop_year", "to_crop_year", "biggest_mover",
             "rules_version", "fact_fingerprint", "as_of", "supersedes",
             "payload"],
            [(
                movement["movement_id"], movement["district_id"],
                movement["product"], movement["season"],
                movement["from_crop_year"], movement["to_crop_year"],
                movement["biggest_mover"]["seller"], movement["rules_version"],
                movement["fact_fingerprint"], movement["as_of"],
                movement["supersedes"], json.dumps(movement),
            )],
        )

    def _share_movement_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_share_movement(self, movement_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM share_movements WHERE movement_id = {self._ph}",
            (movement_id,),
        )
        return self._share_movement_row(rows[0]) if rows else None

    def list_share_movements(
        self, district_id=None, product=None, season=None
    ) -> list[dict]:
        sql, params = "SELECT * FROM share_movements WHERE 1=1", []
        for column, value in (
            ("district_id", district_id), ("product", product),
            ("season", season),
        ):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(
            sql + " ORDER BY district_id, product, season, movement_id",
            tuple(params),
        )
        return [self._share_movement_row(row) for row in rows]

    # -- Round 7: field signal reports, review acts, assessments --
    # Reports land from the mobile intake sync (or the planted
    # promotion) as artefacts keyed by their submission; review
    # acts are insert-only and the state is their fold, so no
    # state column exists here. Assessments are computed
    # artefacts. All insert-only, superseding by link, the full
    # artefact as a JSON payload.

    def insert_field_report_artefact(self, report: dict) -> None:
        self._insert_many(
            "field_signal_reports",
            ["report_id", "submission_id", "payload_hash", "reporter",
             "district_id", "product", "signal_type", "signal_kind",
             "observed_on", "crop_year", "season", "source", "as_of",
             "conflicts_with", "payload"],
            [(
                report["report_id"], report["submission_id"],
                report["payload_hash"], report["reporter"],
                report["district_id"], report["product"],
                report["signal_type"], report["signal_kind"],
                report["observed_on"], report["crop_year"],
                report["season"], report["source"], report["as_of"],
                report["conflicts_with"], json.dumps(report),
            )],
        )

    def _field_report_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_field_report_artefact(self, report_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM field_signal_reports WHERE report_id = {self._ph}",
            (report_id,),
        )
        return self._field_report_row(rows[0]) if rows else None

    def list_field_report_artefacts(
        self, submission_id=None, district_id=None, product=None
    ) -> list[dict]:
        sql, params = "SELECT * FROM field_signal_reports WHERE 1=1", []
        for column, value in (
            ("submission_id", submission_id), ("district_id", district_id),
            ("product", product),
        ):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(
            sql + " ORDER BY submission_id, report_id", tuple(params)
        )
        return [self._field_report_row(row) for row in rows]

    def insert_field_review_act(self, act: dict) -> None:
        self._insert_many(
            "field_review_acts",
            ["act_id", "report_id", "act", "actor", "reason", "note", "as_of"],
            [(
                act["act_id"], act["report_id"], act["act"], act["actor"],
                act["reason"], act["note"], act["as_of"],
            )],
        )

    def list_field_review_acts(self, report_id: str) -> list[dict]:
        return self._rows(
            f"SELECT * FROM field_review_acts WHERE report_id = {self._ph} "
            "ORDER BY act_id",
            (report_id,),
        )

    def insert_field_assessment(self, assessment: dict) -> None:
        self._insert_many(
            "field_signal_assessments",
            ["assessment_id", "district_id", "product", "crop_year",
             "season", "as_of", "estimate_id", "base_tonnes",
             "adjustment_pct", "adjusted_tonnes", "rules_version",
             "fact_fingerprint", "supersedes", "payload"],
            [(
                assessment["assessment_id"], assessment["district_id"],
                assessment["product"], assessment["crop_year"],
                assessment["season"], assessment["as_of"],
                assessment["estimate_id"], assessment["base_tonnes"],
                assessment["adjustment_pct"], assessment["adjusted_tonnes"],
                assessment["rules_version"], assessment["fact_fingerprint"],
                assessment["supersedes"], json.dumps(assessment),
            )],
        )

    def _field_assessment_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_field_assessment(self, assessment_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM field_signal_assessments WHERE assessment_id = {self._ph}",
            (assessment_id,),
        )
        return self._field_assessment_row(rows[0]) if rows else None

    def list_field_assessments(
        self, district_id=None, product=None, crop_year=None, season=None,
        as_of=None,
    ) -> list[dict]:
        sql, params = "SELECT * FROM field_signal_assessments WHERE 1=1", []
        for column, value in (
            ("district_id", district_id), ("product", product),
            ("crop_year", crop_year), ("season", season), ("as_of", as_of),
        ):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(
            sql + " ORDER BY district_id, product, crop_year, season, as_of, "
            "assessment_id",
            tuple(params),
        )
        return [self._field_assessment_row(row) for row in rows]

    # -- dashboard specs & assemblies (R8, insert-only) ---------------

    def insert_dashboard_spec(self, spec: dict) -> None:
        self._conn.execute(
            "INSERT INTO dashboard_specs (spec_id, fingerprint, question,"
            " asked_by, role, name, saved_by, as_of, rules_version, payload)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (spec["spec_id"], spec["fingerprint"], spec["question"],
             spec["asked_by"], spec.get("role"), spec.get("name"),
             spec.get("saved_by"), spec["as_of"], spec["rules_version"],
             json.dumps(spec, sort_keys=True)),
        )
        self._conn.commit()

    def _spec_row(self, row) -> dict | None:
        if row is None:
            return None
        record = dict(row)
        payload = json.loads(record.pop("payload"))
        payload.update(record)
        return payload

    def get_dashboard_spec(self, spec_id: str) -> dict | None:
        return self._spec_row(self._conn.execute(
            "SELECT * FROM dashboard_specs WHERE spec_id = ?", (spec_id,),
        ).fetchone())

    def dashboard_spec_by_fingerprint(self, fingerprint: str) -> dict | None:
        return self._spec_row(self._conn.execute(
            "SELECT * FROM dashboard_specs WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone())

    def dashboard_specs(self, name: str | None = None,
                        saved_by: str | None = None) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM dashboard_specs").fetchall()
        out = [self._spec_row(r) for r in rows]
        if name is not None:
            out = [s for s in out if s.get("name") == name]
        if saved_by is not None:
            out = [s for s in out if s.get("saved_by") == saved_by]
        return out

    def insert_dashboard_assembly(self, assembly: dict) -> None:
        self._conn.execute(
            "INSERT INTO dashboard_assemblies (assembly_id, fingerprint,"
            " spec_id, supersedes, assembled_on, payload)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (assembly["assembly_id"], assembly["fingerprint"],
             assembly["spec_id"], assembly.get("supersedes"),
             assembly["assembled_on"],
             json.dumps(assembly, sort_keys=True)),
        )
        self._conn.commit()

    def _assembly_row(self, row) -> dict | None:
        if row is None:
            return None
        record = dict(row)
        payload = json.loads(record.pop("payload"))
        payload.update(record)
        return payload

    def get_dashboard_assembly(self, assembly_id: str) -> dict | None:
        return self._assembly_row(self._conn.execute(
            "SELECT * FROM dashboard_assemblies WHERE assembly_id = ?",
            (assembly_id,),
        ).fetchone())

    def dashboard_assemblies(self, spec_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM dashboard_assemblies WHERE spec_id = ?"
            " ORDER BY assembled_on, assembly_id", (spec_id,),
        ).fetchall()
        return [self._assembly_row(r) for r in rows]

    # -- Round 9: scenario forks, planning options, adoptions --
    # Scenarios are hypothetical by construction and live only
    # in these tables: no head read (estimate, gap, board,
    # impact, dashboard of record) ever joins them. Forks and
    # options are computed artefacts; adoptions are insert-only
    # acts whose current state is the head of their supersedes
    # chain. All insert-only, the full artefact as a JSON
    # payload.

    def insert_scenario_fork(self, fork: dict) -> None:
        self._insert_many(
            "scenario_forks",
            ["fork_id", "fingerprint", "name", "kind",
             "base_artefact_id", "created_by", "as_of",
             "rules_version", "payload"],
            [(
                fork["fork_id"], fork["fingerprint"], fork["name"],
                fork["kind"], fork["base_artefact_id"],
                fork["created_by"], fork["as_of"],
                fork["rules_version"], json.dumps(fork),
            )],
        )

    def _scenario_fork_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_scenario_fork(self, fork_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM scenario_forks WHERE fork_id = {self._ph}",
            (fork_id,),
        )
        return self._scenario_fork_row(rows[0]) if rows else None

    def scenario_fork_by_fingerprint(self, fingerprint: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM scenario_forks WHERE fingerprint = {self._ph}",
            (fingerprint,),
        )
        return self._scenario_fork_row(rows[0]) if rows else None

    def scenario_fork_by_name(self, name: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM scenario_forks WHERE name = {self._ph}",
            (name,),
        )
        return self._scenario_fork_row(rows[0]) if rows else None

    def list_scenario_forks(self, kind=None, base_artefact_id=None) -> list[dict]:
        sql, params = "SELECT * FROM scenario_forks WHERE 1=1", []
        for column, value in (("kind", kind),
                              ("base_artefact_id", base_artefact_id)):
            if value is not None:
                sql += f" AND {column} = {self._ph}"
                params.append(value)
        rows = self._rows(sql + " ORDER BY kind, base_artefact_id, fork_id",
                          tuple(params))
        return [self._scenario_fork_row(row) for row in rows]

    def insert_planning_options(self, options: dict) -> None:
        self._insert_many(
            "planning_options",
            ["options_id", "fingerprint", "name", "kind",
             "base_artefact_id", "created_by", "as_of",
             "rules_version", "payload"],
            [(
                options["options_id"], options["fingerprint"],
                options["name"], options["kind"],
                options["base_artefact_id"], options["created_by"],
                options["as_of"], options["rules_version"],
                json.dumps(options),
            )],
        )

    def _planning_options_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_planning_options(self, options_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM planning_options WHERE options_id = {self._ph}",
            (options_id,),
        )
        return self._planning_options_row(rows[0]) if rows else None

    def planning_options_by_fingerprint(self, fingerprint: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM planning_options WHERE fingerprint = {self._ph}",
            (fingerprint,),
        )
        return self._planning_options_row(rows[0]) if rows else None

    def list_planning_options(self, base_artefact_id=None) -> list[dict]:
        sql, params = "SELECT * FROM planning_options WHERE 1=1", []
        if base_artefact_id is not None:
            sql += f" AND base_artefact_id = {self._ph}"
            params.append(base_artefact_id)
        rows = self._rows(sql + " ORDER BY base_artefact_id, options_id",
                          tuple(params))
        return [self._planning_options_row(row) for row in rows]

    def insert_planning_adoption(self, adoption: dict) -> None:
        self._insert_many(
            "planning_adoptions",
            ["adoption_id", "options_id", "fork_id", "adopted_by",
             "as_of", "supersedes", "payload"],
            [(
                adoption["adoption_id"], adoption["options_id"],
                adoption["fork_id"], adoption["adopted_by"],
                adoption["as_of"], adoption["supersedes"],
                json.dumps(adoption),
            )],
        )

    def _planning_adoption_row(self, row: dict) -> dict:
        payload = json.loads(row.pop("payload"))
        return {**row, **payload}

    def get_planning_adoption(self, adoption_id: str) -> dict | None:
        rows = self._rows(
            f"SELECT * FROM planning_adoptions WHERE adoption_id = {self._ph}",
            (adoption_id,),
        )
        return self._planning_adoption_row(rows[0]) if rows else None

    def list_planning_adoptions(self, options_id: str) -> list[dict]:
        rows = self._rows(
            f"SELECT * FROM planning_adoptions WHERE options_id = {self._ph} "
            "ORDER BY adoption_id",
            (options_id,),
        )
        return [self._planning_adoption_row(row) for row in rows]

    def fact_counts(self) -> dict[str, int]:
        counts = {"districts": self._rows("SELECT COUNT(*) AS n FROM districts")[0]["n"]}
        for table in _FACT_TABLES:
            counts[table] = self._rows(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]
        return counts

    def provenance_gaps(self) -> int:
        """Fact rows missing source or as_of — must always be 0."""
        gaps = 0
        for table in _FACT_TABLES:
            row = self._rows(
                f"SELECT COUNT(*) AS n FROM {table} "
                "WHERE source IS NULL OR source = '' OR as_of IS NULL OR as_of = ''"
            )[0]
            gaps += row["n"]
        return gaps
