import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fertilizer_intelligence.config import Settings  # noqa: E402
from fertilizer_intelligence.service import MarketService  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=None,
        sqlite_path=tmp_path / "fert.db",
        migrations_dir=REPO / "migrations",
        model_profile="offline",
        log_level="WARNING",
    )


@pytest.fixture()
def service(settings) -> MarketService:
    return MarketService(settings)
