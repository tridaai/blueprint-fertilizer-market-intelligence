"""Runtime configuration, from the environment only.

Defaults are the local development profile: a SQLite market data
store in ``./data`` and the offline model profile. Setting
``DATABASE_URL`` selects the Postgres profile — Postgres 16 is the
system of record in the production-shaped deployment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    sqlite_path: Path
    migrations_dir: Path
    model_profile: str
    log_level: str

    @property
    def use_postgres(self) -> bool:
        return bool(self.database_url)


def _resolve(env_value: str | None, *candidates: Path) -> Path:
    """First existing candidate wins; env override always wins.

    The package may be imported from the repo (src layout) or from an
    installed wheel, so relative-to-CWD paths are tried before the
    path relative to this source file.
    """
    if env_value:
        return Path(env_value)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[2]
    return Settings(
        database_url=os.environ.get("DATABASE_URL") or None,
        sqlite_path=Path(os.environ.get("FERT_SQLITE_PATH", "./data/fert.db")),
        migrations_dir=_resolve(
            os.environ.get("FERT_MIGRATIONS_DIR"),
            Path("migrations"),
            repo_root / "migrations",
        ),
        model_profile=os.environ.get("FERT_MODEL_PROFILE", "offline"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
