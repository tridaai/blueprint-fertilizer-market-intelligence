"""Local harness: exercise the real FastAPI app over HTTP semantics
in-process (ASGI transport — no sockets, no keys), the same surface
uvicorn serves in production.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tempfile

import httpx

from fertilizer_intelligence.api import create_app
from fertilizer_intelligence.config import Settings


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fert-harness-"))
    settings = Settings(
        database_url=None,
        sqlite_path=tmp / "fert.db",
        migrations_dir=Path(__file__).resolve().parents[1] / "migrations",
        model_profile="offline",
        log_level="WARNING",
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    with httpx.Client(transport=transport, base_url="http://harness") as client:
        for path in (
            "/health",
            "/readiness",
            "/districts",
            "/prices?series_kind=product&item=DAP",
            "/imports",
            "/policy-events",
            "/field-reports",
            "/manifest",
            "/districts/DST-GUN/demand-inputs?crop_year=2025-26&season=kharif",
        ):
            resp = client.get(path)
            body = resp.json()
            size = len(body) if isinstance(body, list) else len(body.keys())
            print(f"GET {path:<70} {resp.status_code}  ({size} items/keys)")
            assert resp.status_code == 200, path
    print("Harness OK — the full read surface answers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
