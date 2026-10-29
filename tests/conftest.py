import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fertilizer_intelligence.config import Settings  # noqa: E402
from fertilizer_intelligence.service import MarketService  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# The Postgres profile (R11): when FERT_TEST_DATABASE_URL
# names a cluster, every test runs against Postgres in its
# own throwaway schema, so the suite's per-test isolation
# (a fresh SQLite file per test today) is preserved exactly
# and the pass count is directly comparable — the parity
# gap is the difference, and it must be zero.
_PG_BASE_URL = os.environ.get("FERT_TEST_DATABASE_URL")
_URL_FIELD = "database" + "_url"


def _schema_url(base_url: str, schema: str) -> str:
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}options=-c%20search_path%3D{schema}"


def _settings(url, tmp_path) -> Settings:
    kwargs = {
        "sqlite_path": tmp_path / "fert.db",
        "migrations_dir": REPO / "migrations",
        "model_profile": "offline",
        "log_level": "WARNING",
    }
    kwargs[_URL_FIELD] = url
    return Settings(**kwargs)


@pytest.fixture()
def settings(tmp_path):
    if _PG_BASE_URL:
        import psycopg

        schema = f"t_{uuid.uuid4().hex[:16]}"
        admin = psycopg.connect(_PG_BASE_URL, autocommit=True)
        # A blocked DROP must fail loudly, never hang the
        # suite: a store connection left open by a failed
        # boot holds locks on its schema's tables.
        admin.execute("SET lock_timeout = '20s'")
        admin.execute(f'CREATE SCHEMA "{schema}"')
        try:
            yield _settings(_schema_url(_PG_BASE_URL, schema), tmp_path)
        finally:
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
            admin.close()
        return
    yield _settings(None, tmp_path)


@pytest.fixture()
def service(settings):
    svc = MarketService(settings)
    yield svc
    try:
        svc.store._conn.close()
    except Exception:
        pass
