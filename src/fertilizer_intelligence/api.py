"""FastAPI surface: health/readiness plus the market data reads.

Every response is built from stored facts — the API holds no
numbers of its own. A request-id middleware stamps each request so
the JSON logs can follow it end to end.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .config import Settings
from .dashboard import DashboardRefused
from .demand import NarrativeRefused
from .field import FieldReviewError
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


class PositionRequest(BaseModel):
    product: str
    as_of: str | None = None


class GapRequest(BaseModel):
    product: str
    crop_year: str
    season: str
    as_of: str | None = None


class ProjectionRequest(BaseModel):
    product: str
    crop_year: str
    season: str
    as_of: str | None = None


class PolicyRegisterFactsRequest(BaseModel):
    as_of: str | None = None


class ShareRequest(BaseModel):
    district_id: str
    product: str
    crop_year: str
    season: str
    as_of: str | None = None


class ShareMovementRequest(BaseModel):
    district_id: str
    product: str
    season: str
    as_of: str | None = None


class FieldSyncRequest(BaseModel):
    submissions: list[dict]
    as_of: str | None = None


class FieldPromoteRequest(BaseModel):
    as_of: str | None = None


class FieldReviewRequest(BaseModel):
    act: str
    actor: str
    reason: str
    note: str | None = None
    as_of: str | None = None


class AskRequest(BaseModel):
    question: str
    asked_by: str
    as_of: str | None = None
    role: str | None = None
    name: str | None = None


class AssembleRequest(BaseModel):
    assembled_on: str | None = None


class FieldAssessmentRequest(BaseModel):
    district_id: str
    product: str
    crop_year: str
    season: str
    as_of: str | None = None


class PolicyEventRequest(BaseModel):
    event_id: str
    event_class: str
    title: str
    detail: str
    effective_from_month: str
    effective_to_month: str
    products: list[str]
    districts: list[str] = []
    direction: str
    driver: str | None = None
    mechanism: str
    hypothetical: bool = False
    source: str
    recorded_on: str | None = None
    registered_by: str
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

    # -- supply tracker (R4) -----------------------------------------

    @app.post("/positions")
    def compute_positions(body: PositionRequest) -> list[dict]:
        try:
            return service.supply_positions(
                body.product, body.as_of or date.today().isoformat()
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/positions")
    def list_positions(
        product: str | None = None, month: str | None = None
    ) -> list[dict]:
        return service.store.list_positions(product, month)

    @app.get("/positions/{product}/{month}")
    def get_position(product: str, month: str) -> dict:
        position = service.get_position(product, month)
        if position is None:
            raise HTTPException(
                status_code=404, detail=f"no supply position for {product} {month}"
            )
        return position

    @app.get("/positions/{product}/{month}/verify")
    def verify_position(product: str, month: str) -> dict:
        position = service.get_position(product, month)
        if position is None:
            raise HTTPException(
                status_code=404, detail=f"no supply position for {product} {month}"
            )
        problems = service.verify_position(product, month)
        return {
            "position_id": position["position_id"],
            "ok": not problems, "problems": problems,
        }

    @app.post("/gaps")
    def compute_gap(body: GapRequest) -> dict:
        try:
            return service.supply_gap(
                body.product, body.crop_year, body.season,
                body.as_of or date.today().isoformat(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/gaps/{product}/{crop_year}/{season}")
    def get_gap(product: str, crop_year: str, season: str) -> dict:
        gap = service.get_gap(product, crop_year, season)
        if gap is None:
            raise HTTPException(
                status_code=404,
                detail=f"no supply gap computed for {product} {crop_year} {season}",
            )
        return gap

    @app.get("/gaps/{product}/{crop_year}/{season}/verify")
    def verify_gap(product: str, crop_year: str, season: str) -> dict:
        gap = service.get_gap(product, crop_year, season)
        if gap is None:
            raise HTTPException(
                status_code=404,
                detail=f"no supply gap computed for {product} {crop_year} {season}",
            )
        problems = service.verify_gap(product, crop_year, season)
        return {"gap_id": gap["gap_id"], "ok": not problems, "problems": problems}

    @app.post("/projections")
    def compute_projection(body: ProjectionRequest) -> dict:
        try:
            return service.supply_projection(
                body.product, body.crop_year, body.season,
                body.as_of or date.today().isoformat(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/projections/{product}/{crop_year}/{season}")
    def get_projection(product: str, crop_year: str, season: str) -> dict:
        projection = service.get_projection(product, crop_year, season)
        if projection is None:
            raise HTTPException(
                status_code=404,
                detail=f"no supply projection computed for {product} {crop_year} {season}",
            )
        return projection

    @app.get("/projections/{product}/{crop_year}/{season}/verify")
    def verify_projection(product: str, crop_year: str, season: str) -> dict:
        projection = service.get_projection(product, crop_year, season)
        if projection is None:
            raise HTTPException(
                status_code=404,
                detail=f"no supply projection computed for {product} {crop_year} {season}",
            )
        problems = service.verify_projection(product, crop_year, season)
        return {
            "projection_id": projection["projection_id"],
            "ok": not problems, "problems": problems,
        }

    # -- policy registry (R5) --------------------------------------

    @app.post("/policy-registry/register-facts")
    def register_policy_facts(body: PolicyRegisterFactsRequest) -> dict:
        return service.register_policy_events(
            body.as_of or date.today().isoformat()
        )

    @app.post("/policy-registry/events")
    def register_policy_event(body: PolicyEventRequest) -> dict:
        spec = body.model_dump(exclude={"as_of"})
        try:
            return service.register_policy_event(
                spec, body.as_of or date.today().isoformat()
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/policy-registry/events")
    def list_policy_events(
        hypothetical: bool | None = None, event_class: str | None = None,
    ) -> list[dict]:
        return service.list_policy_events(hypothetical, event_class)

    @app.get("/policy-registry/events/{registry_id}")
    def get_policy_event(registry_id: str) -> dict:
        event = service.get_policy_event(registry_id)
        if event is None:
            raise HTTPException(
                status_code=404, detail=f"no such policy registration: {registry_id}"
            )
        return event

    @app.get("/policy-registry/events/{registry_id}/versions")
    def policy_event_versions(registry_id: str) -> list[dict]:
        event = service.get_policy_event(registry_id)
        if event is None:
            raise HTTPException(
                status_code=404, detail=f"no such policy registration: {registry_id}"
            )
        return service.policy_event_versions(event["event_id"])

    @app.get("/policy-registry/events/{registry_id}/verify")
    def verify_policy_event(registry_id: str) -> dict:
        if service.get_policy_event(registry_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no such policy registration: {registry_id}"
            )
        problems = service.verify_policy_event(registry_id)
        return {
            "registry_id": registry_id,
            "ok": not problems, "problems": problems,
        }

    @app.post("/policy-registry/events/{registry_id}/impact")
    def compute_policy_impact(registry_id: str, body: PolicyRegisterFactsRequest) -> dict:
        if service.get_policy_event(registry_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no such policy registration: {registry_id}"
            )
        try:
            return service.policy_impact(
                registry_id, body.as_of or date.today().isoformat()
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/policy-registry/events/{registry_id}/impact")
    def get_policy_impact(registry_id: str) -> dict:
        if service.get_policy_event(registry_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no such policy registration: {registry_id}"
            )
        note = service.get_policy_impact(registry_id)
        if note is None:
            raise HTTPException(
                status_code=404,
                detail=f"no impact note computed for registration {registry_id}",
            )
        return note

    @app.get("/policy-registry/events/{registry_id}/impact/verify")
    def verify_policy_impact(registry_id: str) -> dict:
        if service.get_policy_event(registry_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no such policy registration: {registry_id}"
            )
        note = service.get_policy_impact(registry_id)
        if note is None:
            raise HTTPException(
                status_code=404,
                detail=f"no impact note computed for registration {registry_id}",
            )
        problems = service.verify_policy_impact(registry_id)
        return {
            "note_id": note["note_id"],
            "ok": not problems, "problems": problems,
        }

    # -- competitor & share intelligence (R6) -------------------

    @app.post("/competitor-observations/build")
    def build_competitor_observations() -> dict:
        return service.build_competitor_observations()

    @app.get("/competitor-observations")
    def list_competitor_observations(
        competitor: str | None = None, region: str | None = None,
        product: str | None = None, season: str | None = None,
    ) -> list[dict]:
        return service.list_competitor_observations(
            competitor, region, product, season
        )

    @app.get("/competitor-observations/{observation_id}")
    def get_competitor_observation(observation_id: str) -> dict:
        observation = service.get_competitor_observation(observation_id)
        if observation is None:
            raise HTTPException(
                status_code=404,
                detail=f"no such competitor observation: {observation_id}",
            )
        return observation

    @app.get("/competitor-observations/{observation_id}/verify")
    def verify_competitor_observation(observation_id: str) -> dict:
        if service.get_competitor_observation(observation_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"no such competitor observation: {observation_id}",
            )
        problems = service.verify_competitor_observation(observation_id)
        return {
            "observation_id": observation_id,
            "ok": not problems, "problems": problems,
        }

    @app.post("/shares")
    def compute_share(body: ShareRequest) -> dict:
        try:
            return service.market_share(
                body.district_id, body.product, body.crop_year, body.season,
                body.as_of,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/shares/{district_id}/{product}/{crop_year}/{season}")
    def get_share(
        district_id: str, product: str, crop_year: str, season: str,
        as_of: str | None = None,
    ) -> dict:
        share = service.get_share(district_id, product, crop_year, season, as_of)
        if share is None:
            raise HTTPException(
                status_code=404,
                detail=f"no market share computed for {district_id} {product} "
                       f"{crop_year} {season}",
            )
        return share

    @app.get("/shares/{district_id}/{product}/{crop_year}/{season}/verify")
    def verify_share(
        district_id: str, product: str, crop_year: str, season: str,
        as_of: str | None = None,
    ) -> dict:
        share = service.get_share(district_id, product, crop_year, season, as_of)
        if share is None:
            raise HTTPException(
                status_code=404,
                detail=f"no market share computed for {district_id} {product} "
                       f"{crop_year} {season}",
            )
        problems = service.verify_share(share["share_id"])
        return {
            "share_id": share["share_id"],
            "ok": not problems, "problems": problems,
        }

    @app.get("/shares/{district_id}/{product}/{crop_year}/{season}/stale")
    def get_share_stale(
        district_id: str, product: str, crop_year: str, season: str,
        as_of: str | None = None,
    ) -> dict:
        try:
            return service.share_stale_exclusions(
                district_id, product, crop_year, season, as_of
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/share-movements")
    def compute_share_movement(body: ShareMovementRequest) -> dict:
        try:
            return service.share_movement(
                body.district_id, body.product, body.season,
                body.as_of or date.today().isoformat(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/share-movements/{district_id}/{product}/{season}")
    def get_share_movement(district_id: str, product: str, season: str) -> dict:
        movement = service.get_share_movement(district_id, product, season)
        if movement is None:
            raise HTTPException(
                status_code=404,
                detail=f"no share movement computed for {district_id} "
                       f"{product} {season}",
            )
        return movement

    @app.get("/share-movements/{district_id}/{product}/{season}/verify")
    def verify_share_movement(district_id: str, product: str, season: str) -> dict:
        movement = service.get_share_movement(district_id, product, season)
        if movement is None:
            raise HTTPException(
                status_code=404,
                detail=f"no share movement computed for {district_id} "
                       f"{product} {season}",
            )
        problems = service.verify_share_movement(movement["movement_id"])
        return {
            "movement_id": movement["movement_id"],
            "ok": not problems, "problems": problems,
        }

    # -- field signals & mobile intake (R7) -------------------

    @app.post("/field-signals/sync")
    def sync_field_signals(body: FieldSyncRequest) -> dict:
        try:
            return service.sync_field_reports(
                body.submissions, body.as_of or date.today().isoformat()
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/field-signals/promote-planted")
    def promote_planted_field_signals(body: FieldPromoteRequest) -> dict:
        return service.promote_planted_field_reports(
            body.as_of or date.today().isoformat()
        )

    @app.get("/field-signals")
    def list_field_signals(
        state: str | None = None, district_id: str | None = None,
        product: str | None = None,
    ) -> list[dict]:
        return service.list_field_reports(state, district_id, product)

    @app.get("/field-review-queue")
    def field_review_queue(state: str = "unreviewed") -> list[dict]:
        return service.list_field_reports(state=state)

    @app.get("/field-signals/{report_id}")
    def get_field_signal(report_id: str) -> dict:
        report = service.get_field_report(report_id)
        if report is None:
            raise HTTPException(
                status_code=404, detail=f"no such field report: {report_id}"
            )
        return report

    @app.get("/field-signals/{report_id}/verify")
    def verify_field_signal(report_id: str) -> dict:
        if service.get_field_report(report_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no such field report: {report_id}"
            )
        problems = service.verify_field_report(report_id)
        return {
            "report_id": report_id,
            "ok": not problems, "problems": problems,
        }

    @app.post("/field-signals/{report_id}/review")
    def review_field_signal(report_id: str, body: FieldReviewRequest) -> dict:
        if service.get_field_report(report_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no such field report: {report_id}"
            )
        try:
            return service.review_field_report(
                report_id, body.act, body.actor, body.reason,
                body.as_of or date.today().isoformat(), note=body.note,
            )
        except FieldReviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/field-assessments")
    def compute_field_assessment(body: FieldAssessmentRequest) -> dict:
        try:
            return service.field_signal_assessment(
                body.district_id, body.product, body.crop_year, body.season,
                body.as_of or date.today().isoformat(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/field-assessments/{district_id}/{product}/{crop_year}/{season}")
    def get_field_assessment(
        district_id: str, product: str, crop_year: str, season: str,
        as_of: str | None = None,
    ) -> dict:
        assessment = service.get_field_assessment(
            district_id, product, crop_year, season, as_of
        )
        if assessment is None:
            raise HTTPException(
                status_code=404,
                detail=f"no field assessment computed for {district_id} "
                       f"{product} {crop_year} {season}",
            )
        return assessment

    @app.get("/field-assessments/{district_id}/{product}/{crop_year}/{season}/verify")
    def verify_field_assessment(
        district_id: str, product: str, crop_year: str, season: str,
        as_of: str | None = None,
    ) -> dict:
        assessment = service.get_field_assessment(
            district_id, product, crop_year, season, as_of
        )
        if assessment is None:
            raise HTTPException(
                status_code=404,
                detail=f"no field assessment computed for {district_id} "
                       f"{product} {crop_year} {season}",
            )
        problems = service.verify_field_assessment(assessment["assessment_id"])
        return {
            "assessment_id": assessment["assessment_id"],
            "ok": not problems, "problems": problems,
        }

    # -- plain-language dashboards (R8) ------------------------

    @app.post("/dashboards/ask")
    def ask_dashboard(body: AskRequest) -> dict:
        try:
            return service.ask_question(
                body.question, body.asked_by,
                body.as_of or date.today().isoformat(),
                role=body.role, name=body.name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/dashboards/specs")
    def list_dashboard_specs(
        name: str | None = None, saved_by: str | None = None,
    ) -> list[dict]:
        return service.list_dashboard_specs(name=name, saved_by=saved_by)

    @app.get("/dashboards/specs/{spec_id}")
    def get_dashboard_spec(spec_id: str) -> dict:
        spec = service.get_dashboard_spec(spec_id)
        if spec is None:
            raise HTTPException(
                status_code=404, detail=f"no such dashboard spec: {spec_id}")
        return spec

    @app.get("/dashboards/specs/{spec_id}/verify")
    def verify_dashboard_spec(spec_id: str) -> dict:
        try:
            return service.verify_dashboard_spec(spec_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/dashboards/specs/{spec_id}/assemble")
    def assemble_dashboard(spec_id: str, body: AssembleRequest) -> dict:
        if service.get_dashboard_spec(spec_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no such dashboard spec: {spec_id}")
        try:
            return service.assemble_dashboard(
                spec_id, body.assembled_on or date.today().isoformat())
        except DashboardRefused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/dashboards/specs/{spec_id}/html")
    def dashboard_html(spec_id: str) -> HTMLResponse:
        page = service.dashboard_html(spec_id)
        if page is None:
            raise HTTPException(
                status_code=404, detail=f"no such dashboard spec: {spec_id}")
        return HTMLResponse(content=page)

    @app.get("/dashboards/assemblies/{assembly_id}")
    def get_dashboard_assembly(assembly_id: str) -> dict:
        assembly = service.get_dashboard_assembly(assembly_id)
        if assembly is None:
            raise HTTPException(
                status_code=404,
                detail=f"no such dashboard assembly: {assembly_id}")
        return assembly

    @app.get("/dashboards/assemblies/{assembly_id}/verify")
    def verify_dashboard_assembly(assembly_id: str) -> dict:
        try:
            return service.verify_dashboard(assembly_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/dashboards/assemblies/{assembly_id}/html")
    def dashboard_assembly_html(assembly_id: str) -> HTMLResponse:
        assembly = service.get_dashboard_assembly(assembly_id)
        if assembly is None:
            raise HTTPException(
                status_code=404,
                detail=f"no such dashboard assembly: {assembly_id}")
        return HTMLResponse(content=assembly["html"])

    @app.get("/dashboards/roles/{role}")
    def role_dashboard(
        role: str, asked_by: str, as_of: str | None = None,
    ) -> dict:
        try:
            return service.role_default_dashboard(
                role, asked_by, as_of or date.today().isoformat())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app


app = create_app()
