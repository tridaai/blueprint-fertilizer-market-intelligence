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
