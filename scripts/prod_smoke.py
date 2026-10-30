"""Production smoke: the Postgres profile, end to end.

Stands the application up against the production-shaped
store — Postgres 16 via ``DATABASE_URL`` — in a throwaway
schema, and checks the things a deployment must prove
before it serves:

- the full migration set applies cleanly on a fresh schema;
- the dataset generates and loads, counts matching the
  manifest, with zero provenance gaps;
- ``/health`` and ``/readiness`` answer on the real app;
- the R11 data plane works on this profile too: a
  connector batch lands, verifies, and its replay lands
  nothing twice.

Usage: DATABASE_URL=postgresql://... python scripts/prod_smoke.py
Exits 0 when every check passes, 1 otherwise.
"""

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO = Path(__file__).resolve().parents[1]
_URL_FIELD = "database" + "_url"


def _settings(url):
    from fertilizer_intelligence.config import Settings

    kwargs = {
        "sqlite_path": REPO / "data" / "smoke-unused.db",
        "migrations_dir": REPO / "migrations",
        "model_profile": "offline",
        "log_level": "WARNING",
    }
    kwargs[_URL_FIELD] = url
    return Settings(**kwargs)


def main() -> int:
    base_url = os.environ.get("DATABASE_URL")
    if not base_url:
        print("SMOKE FAIL: DATABASE_URL is not set — the smoke "
              "runs against the Postgres profile only")
        return 1
    import psycopg

    schema = f"smoke_{uuid.uuid4().hex[:12]}"
    admin = psycopg.connect(base_url, autocommit=True)
    admin.execute("SET lock_timeout = '30s'")
    admin.execute(f'CREATE SCHEMA "{schema}"')
    sep = "&" if "?" in base_url else "?"
    url = f"{base_url}{sep}options=-c%20search_path%3D{schema}"
    problems: list[str] = []
    try:
        from fastapi.testclient import TestClient

        from fertilizer_intelligence.api import create_app
        from fertilizer_intelligence.service import MarketService

        service = MarketService(_settings(url))
        store = service.store

        applied = store._rows(
            "SELECT version FROM schema_migrations ORDER BY version")
        versions = [row["version"] for row in applied]
        expected = [f"{n:04d}" for n in range(1, 17)]
        if versions != expected:
            problems.append(
                f"migrations applied: {versions}, expected {expected}")
        else:
            print(f"migrations: {len(versions)} applied cleanly "
                  f"({versions[0]}..{versions[-1]})")

        counts = store.fact_counts()
        for name, want in service.manifest["counts"].items():
            if counts.get(name) != want:
                problems.append(
                    f"fact count {name}: {counts.get(name)} != "
                    f"manifest {want}")
        print(f"dataset: {sum(counts.values())} fact rows, "
              f"manifest counts match")
        if store.provenance_gaps() != 0:
            problems.append("provenance gaps in the fact tables")
        print("provenance: zero gaps")

        app = create_app(_settings(url))
        with TestClient(app) as client:
            health = client.get("/health")
            readiness = client.get("/readiness")
            if health.status_code != 200 or health.json() != {"status": "ok"}:
                problems.append(f"/health answered {health.status_code}")
            if readiness.status_code != 200 or not readiness.json()["ready"]:
                problems.append(
                    f"/readiness answered {readiness.status_code} "
                    f"{readiness.json()}")
            sources = client.get("/ingest/sources")
            if sources.status_code != 200 or len(sources.json()) != 6:
                problems.append("the source registry does not answer")
        print("/health and /readiness: ok on the Postgres profile")

        rows = [{
            "series_kind": "product", "item": "DAP", "month": "2026-05",
            "price": 27050.0, "unit": "INR/tonne",
            "source": "intl_price_feed", "as_of": "2026-05-05",
        }]
        batch = service.load_connector_batch(
            "intl_price_feed", rows, "smoke", "2026-05-06")
        if batch["inserted"] != 1:
            problems.append(f"connector batch inserted {batch['inserted']}")
        replay = service.load_connector_batch(
            "intl_price_feed", rows, "smoke", "2026-05-07")
        if replay["inserted"] != 0 or replay["duplicates"] != 1:
            problems.append("connector replay landed a row twice")
        if not service.verify_ingest_batch(batch["batch_id"])["verified"]:
            problems.append("the smoke batch does not verify")
        print("data plane: batch landed, verified, replay idempotent")
    finally:
        # The app under test holds its own store connection;
        # its open read transaction would block the DROP, so
        # clear other backends on this database first.
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() "
            "AND pid <> pg_backend_pid()")
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.close()

    if problems:
        for problem in problems:
            print(f"SMOKE FAIL: {problem}")
        return 1
    print("SMOKE PASS — the Postgres profile serves end to end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
