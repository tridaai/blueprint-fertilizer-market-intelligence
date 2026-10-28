"""FastAPI surface: health/readiness plus the market data reads.

Every response is built from stored facts — the API holds no
numbers of its own. A request-id middleware stamps each request so
the JSON logs can follow it end to end.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .logging_config import configure_logging, new_request_id, request_id_var
from .service import MarketService

log = logging.getLogger("fertilizer_intelligence.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    service = MarketService(settings)
    configure_logging(service.settings.log_level)
    app = FastAPI(title="Fertilizer & Agrochemical Market Intelligence Agent")
    app.state.service = service

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("x-request-id") or new_request_id()
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["x-request-id"] = rid
        log.info("%s %s", request.method, request.url.path)
        return response

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/readiness")
    def readiness():
        ok = service.ready()
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"ready": ok, "counts": service.store.fact_counts()},
        )

    @app.get("/districts")
    def districts() -> list[dict]:
        return service.store.list_districts()

    @app.get("/districts/{district_id}/demand-inputs")
    def demand_inputs(
        district_id: str,
        crop_year: str = Query(...),
        season: str = Query(...),
    ) -> dict:
        return service.demand_inputs(district_id, crop_year, season)

    @app.get("/prices")
    def prices(series_kind: str | None = None, item: str | None = None) -> list[dict]:
        return service.store.price_points(series_kind, item)

    @app.get("/imports")
    def imports(product: str | None = None) -> list[dict]:
        return service.store.import_arrivals(product)

    @app.get("/supply")
    def supply(product: str | None = None) -> list[dict]:
        return service.store.supply_facts(product)

    @app.get("/competitors")
    def competitors(
        competitor: str | None = None, region: str | None = None, product: str | None = None
    ) -> list[dict]:
        return service.store.competitor_points(competitor, region, product)

    @app.get("/policy-events")
    def policy_events() -> list[dict]:
        return service.store.policy_events()

    @app.get("/field-reports")
    def field_reports(district_id: str | None = None, signal_kind: str | None = None) -> list[dict]:
        return service.store.field_reports(district_id, signal_kind)

    @app.get("/manifest")
    def manifest() -> dict:
        return service.manifest

    return app


app = create_app()
