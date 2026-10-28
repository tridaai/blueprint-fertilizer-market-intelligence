"""FastAPI surface: health/readiness plus the market data reads.

Every response is built from stored facts — the API holds no
numbers of its own. A request-id middleware stamps each request so
the JSON logs can follow it end to end.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import Settings
from .demand import NarrativeRefused
from .logging_config import configure_logging, new_request_id, request_id_var
from .movements import AlertStateError
from .service import MarketService

log = logging.getLogger("fertilizer_intelligence.api")


class EstimateRequest(BaseModel):
    district_id: str
    product: str
    crop_year: str
    season: str
    as_of: str | None = None


class OutlookRequest(BaseModel):
    crop_year: str
    season: str
    as_of: str | None = None


class NarrativeRequest(BaseModel):
    as_of: str | None = None


class WatchRunRequest(BaseModel):
    as_of: str | None = None


class AcknowledgeRequest(BaseModel):
    actor: str
    note: str
    as_of: str | None = None


class CloseRequest(BaseModel):
    actor: str
    closing_reason: str
    as_of: str | None = None


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

    # -- demand engine (R2) ------------------------------------------

    @app.post("/estimates")
    def compute_estimate(body: EstimateRequest) -> dict:
        try:
            return service.estimate_demand(
                body.district_id, body.product, body.crop_year, body.season,
                body.as_of or date.today().isoformat(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/estimates")
    def list_estimates(
        district_id: str | None = None, product: str | None = None,
        crop_year: str | None = None, season: str | None = None,
    ) -> list[dict]:
        return service.store.list_estimates(district_id, product, crop_year, season)

    @app.get("/estimates/{estimate_id}")
    def get_estimate(estimate_id: str) -> dict:
        estimate = service.get_estimate(estimate_id)
        if estimate is None:
            raise HTTPException(status_code=404, detail=f"no such estimate: {estimate_id}")
        return estimate

    @app.get("/estimates/{estimate_id}/contributions")
    def get_contributions(estimate_id: str) -> list[dict]:
        if service.store.get_estimate(estimate_id) is None:
            raise HTTPException(status_code=404, detail=f"no such estimate: {estimate_id}")
        return service.store.estimate_contributions(estimate_id)

    @app.get("/estimates/{estimate_id}/verify")
    def verify_estimate(estimate_id: str) -> dict:
        if service.store.get_estimate(estimate_id) is None:
            raise HTTPException(status_code=404, detail=f"no such estimate: {estimate_id}")
        problems = service.verify_estimate(estimate_id)
        return {"estimate_id": estimate_id, "ok": not problems, "problems": problems}

    @app.post("/outlooks")
    def compute_outlook(body: OutlookRequest) -> dict:
        return service.demand_outlook(
            body.crop_year, body.season, body.as_of or date.today().isoformat()
        )

    @app.get("/outlooks/{crop_year}/{season}")
    def get_outlook(crop_year: str, season: str) -> dict:
        outlook = service.get_outlook(crop_year, season)
        if outlook is None:
            raise HTTPException(
                status_code=404, detail=f"no outlook computed for {crop_year} {season}"
            )
        return outlook

    @app.get("/outlooks/{crop_year}/{season}/verify")
    def verify_outlook(crop_year: str, season: str) -> dict:
        outlook = service.get_outlook(crop_year, season)
        if outlook is None:
            raise HTTPException(
                status_code=404, detail=f"no outlook computed for {crop_year} {season}"
            )
        problems = service.verify_outlook(outlook["outlook_id"])
        return {"outlook_id": outlook["outlook_id"], "ok": not problems, "problems": problems}

    @app.post("/outlooks/{crop_year}/{season}/narrative")
    def draft_narrative(crop_year: str, season: str, body: NarrativeRequest) -> dict:
        try:
            return service.draft_outlook_narrative(
                crop_year, season, body.as_of or date.today().isoformat()
            )
        except NarrativeRefused as exc:
            raise HTTPException(status_code=422, detail={"problems": exc.problems}) from exc

    # -- price watch (R3) --------------------------------------------

    @app.post("/watch/run")
    def run_watch(body: WatchRunRequest) -> dict:
        return service.run_price_watch(body.as_of or date.today().isoformat())

    @app.get("/movements")
    def list_movements(series_kind: str | None = None, item: str | None = None) -> list[dict]:
        return service.store.list_movements(series_kind, item)

    @app.get("/movements/{movement_id}")
    def get_movement(movement_id: str) -> dict:
        movement = service.store.get_movement(movement_id)
        if movement is None:
            raise HTTPException(status_code=404, detail=f"no such movement: {movement_id}")
        return movement

    @app.get("/movements/{movement_id}/verify")
    def verify_movement(movement_id: str) -> dict:
        if service.store.get_movement(movement_id) is None:
            raise HTTPException(status_code=404, detail=f"no such movement: {movement_id}")
        problems = service.verify_movement(movement_id)
        return {"movement_id": movement_id, "ok": not problems, "problems": problems}

    @app.get("/alerts")
    def list_alerts(
        series_kind: str | None = None, item: str | None = None,
        rule_id: str | None = None, state: str | None = None,
    ) -> list[dict]:
        return service.list_alerts(series_kind, item, rule_id, state)

    @app.get("/alerts/{alert_id}")
    def get_alert(alert_id: str) -> dict:
        alert = service.get_alert(alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail=f"no such alert: {alert_id}")
        return alert

    @app.get("/alerts/{alert_id}/verify")
    def verify_alert(alert_id: str) -> dict:
        if service.store.get_alert(alert_id) is None:
            raise HTTPException(status_code=404, detail=f"no such alert: {alert_id}")
        problems = service.verify_alert(alert_id)
        return {"alert_id": alert_id, "ok": not problems, "problems": problems}

    @app.post("/alerts/{alert_id}/acknowledge")
    def acknowledge_alert(alert_id: str, body: AcknowledgeRequest) -> dict:
        if service.store.get_alert(alert_id) is None:
            raise HTTPException(status_code=404, detail=f"no such alert: {alert_id}")
        try:
            return service.acknowledge_alert(
                alert_id, body.actor, body.note, body.as_of or date.today().isoformat()
            )
        except AlertStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/alerts/{alert_id}/close")
    def close_alert(alert_id: str, body: CloseRequest) -> dict:
        if service.store.get_alert(alert_id) is None:
            raise HTTPException(status_code=404, detail=f"no such alert: {alert_id}")
        try:
            return service.close_alert(
                alert_id, body.actor, body.closing_reason,
                body.as_of or date.today().isoformat(),
            )
        except AlertStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/watch")
    def watch_board() -> list[dict]:
        return service.watch_board()

    @app.get("/watch/{series_kind}/{item}")
    def series_watch(series_kind: str, item: str) -> dict:
        known = {(p["series_kind"], p["item"]) for p in service.store.price_points()}
        if (series_kind, item) not in known:
            raise HTTPException(
                status_code=404, detail=f"no such price series: {series_kind}/{item}"
            )
        return service.series_watch(series_kind, item)

    return app


app = create_app()
