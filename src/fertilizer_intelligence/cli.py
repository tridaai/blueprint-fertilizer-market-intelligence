"""Command-line surface — the same reads and acts as the API,
for an operator at a terminal.

    python -m fertilizer_intelligence.cli estimate \
        --district DST-LUD --product DAP --crop-year 2025-26 --season kharif
    python -m fertilizer_intelligence.cli outlook --crop-year 2025-26 --season kharif
    python -m fertilizer_intelligence.cli contributions --estimate-id EST-...
    python -m fertilizer_intelligence.cli narrative --crop-year 2025-26 --season kharif
    python -m fertilizer_intelligence.cli watch-run
    python -m fertilizer_intelligence.cli alerts --item DAP
    python -m fertilizer_intelligence.cli watch
    python -m fertilizer_intelligence.cli positions --product DAP
    python -m fertilizer_intelligence.cli gap --product DAP --crop-year 2025-26 --season kharif
    python -m fertilizer_intelligence.cli projection --product DAP --crop-year 2025-26 --season rabi
    python -m fertilizer_intelligence.cli policy-register
    python -m fertilizer_intelligence.cli policy-events --actual
    python -m fertilizer_intelligence.cli policy-impact --registry-id POLREG-...
    python -m fertilizer_intelligence.cli observations-build
    python -m fertilizer_intelligence.cli share --district DST-LUD --product DAP --crop-year 2025-26 --season kharif
    python -m fertilizer_intelligence.cli share-movement --district DST-LUD --product DAP --season kharif

Everything prints as JSON. The CLI talks to the service layer
directly, so what it shows is exactly what the API serves.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .config import Settings
from .demand import NarrativeRefused
from .field import FieldReviewError
from .movements import AlertStateError
from .service import MarketService


def _service(args) -> MarketService:
    settings = Settings(
        database_url=None,
        sqlite_path=Path(args.db),
        migrations_dir=Path(args.migrations),
        model_profile="offline",
        log_level="WARNING",
    )
    return MarketService(settings)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="fert-agent",
        description="Fertilizer & Agrochemical Market Intelligence Agent — CLI",
    )
    parser.add_argument("--db", default="./data/fert.db",
                        help="SQLite store path (default ./data/fert.db)")
    parser.add_argument("--migrations", default="migrations",
                        help="migrations directory (default ./migrations)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("estimate", help="compute-or-return one demand estimate")
    p.add_argument("--district", required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("outlook", help="compute-or-return the season outlook")
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("contributions", help="the contribution breakdown of an estimate")
    p.add_argument("--estimate-id", required=True)

    p = sub.add_parser("narrative", help="draft (and figure-verify) the outlook narrative")
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("watch-run", help="run the price watch: compute movements, fire alerts")
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("movements", help="list computed price movements")
    p.add_argument("--series-kind", default=None)
    p.add_argument("--item", default=None)

    p = sub.add_parser("alerts", help="list fired alerts, with their derived state")
    p.add_argument("--series-kind", default=None)
    p.add_argument("--item", default=None)
    p.add_argument("--rule-id", default=None)
    p.add_argument("--state", default=None)

    p = sub.add_parser("alert", help="one alert with its acts and state")
    p.add_argument("--alert-id", required=True)

    p = sub.add_parser("acknowledge", help="acknowledge an open alert (named act)")
    p.add_argument("--alert-id", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--note", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("close", help="close an alert with a stated reason (named act)")
    p.add_argument("--alert-id", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("watch", help="the watch board: every series by band")

    p = sub.add_parser("watch-series", help="one series' watch read")
    p.add_argument("--series-kind", required=True)
    p.add_argument("--item", required=True)

    p = sub.add_parser("positions", help="compute-or-return a product's position chain")
    p.add_argument("--product", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("position", help="one product-month supply position (head)")
    p.add_argument("--product", required=True)
    p.add_argument("--month", required=True)

    p = sub.add_parser("verify-position", help="verify a stored position against its facts")
    p.add_argument("--product", required=True)
    p.add_argument("--month", required=True)

    p = sub.add_parser("gap", help="compute-or-return the season supply gap")
    p.add_argument("--product", required=True)
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("verify-gap", help="verify the stored supply gap")
    p.add_argument("--product", required=True)
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)

    p = sub.add_parser("projection", help="compute-or-return the projected season position")
    p.add_argument("--product", required=True)
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("verify-projection", help="verify the stored projection")
    p.add_argument("--product", required=True)
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)

    p = sub.add_parser("policy-register", help="register the recorded policy facts into the registry")
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("policy-events", help="list current policy registrations (chain heads)")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--hypothetical", action="store_true",
                       help="only the hypothetical proposals")
    group.add_argument("--actual", action="store_true",
                       help="only the real (non-hypothetical) events")
    p.add_argument("--event-class", default=None)

    p = sub.add_parser("policy-event", help="register one event stated at the desk")
    p.add_argument("--event-id", required=True)
    p.add_argument("--event-class", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--detail", required=True)
    p.add_argument("--from-month", required=True)
    p.add_argument("--to-month", required=True)
    p.add_argument("--products", required=True,
                   help="comma-separated scope items (products or feedstocks)")
    p.add_argument("--districts", default="",
                   help="comma-separated district ids (default: market-wide)")
    p.add_argument("--direction", required=True)
    p.add_argument("--driver", default=None)
    p.add_argument("--mechanism", required=True)
    p.add_argument("--hypothetical", action="store_true")
    p.add_argument("--source", required=True)
    p.add_argument("--recorded-on", default=None)
    p.add_argument("--registered-by", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("policy", help="one policy registration by registry id")
    p.add_argument("--registry-id", required=True)

    p = sub.add_parser("verify-policy", help="verify a stored policy registration")
    p.add_argument("--registry-id", required=True)

    p = sub.add_parser("policy-impact", help="compute-or-return a registration's impact note")
    p.add_argument("--registry-id", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("verify-policy-impact", help="verify a stored impact note")
    p.add_argument("--registry-id", required=True)

    p = sub.add_parser("observations-build", help="promote the tracked competitor points to observation artefacts")

    p = sub.add_parser("observations", help="list competitor observation artefacts")
    p.add_argument("--competitor", default=None)
    p.add_argument("--region", default=None)
    p.add_argument("--product", default=None)
    p.add_argument("--season", default=None)

    p = sub.add_parser("observation", help="one competitor observation by id")
    p.add_argument("--observation-id", required=True)

    p = sub.add_parser("verify-observation", help="verify a stored competitor observation")
    p.add_argument("--observation-id", required=True)

    p = sub.add_parser("share", help="compute-or-return one district-season market share")
    p.add_argument("--district", required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("verify-share", help="verify the stored head share")
    p.add_argument("--district", required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("share-stale", help="the stale-exclusion read for one share")
    p.add_argument("--district", required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("share-movement", help="compute-or-return the share movement between the crop years")
    p.add_argument("--district", required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--season", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("verify-share-movement", help="verify the stored share movement")
    p.add_argument("--district", required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--season", required=True)

    p = sub.add_parser("field-sync", help="land one mobile outbox batch (JSON file of submissions)")
    p.add_argument("--file", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("field-promote", help="promote the planted R1 field reports to signal artefacts")
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("field-reports", help="list landed field reports with their review state")
    p.add_argument("--state", default=None)
    p.add_argument("--district", default=None)
    p.add_argument("--product", default=None)

    p = sub.add_parser("field-report", help="one field report by id, with acts and state")
    p.add_argument("--report-id", required=True)

    p = sub.add_parser("verify-field-report", help="verify a landed field report")
    p.add_argument("--report-id", required=True)

    p = sub.add_parser("field-review", help="record a reviewer act (confirm / query / reject)")
    p.add_argument("--report-id", required=True)
    p.add_argument("--act", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--note", default=None)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("field-queue", help="the field-report verification queue (one review state)")
    p.add_argument("--state", default="unreviewed")

    p = sub.add_parser("field-assessment", help="compute-or-return one cell's field-signal assessment")
    p.add_argument("--district", required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("verify-field-assessment", help="verify the stored head field assessment")
    p.add_argument("--district", required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("ask", help="ask a plain-language question; returns the dashboard spec")
    p.add_argument("--question", required=True)
    p.add_argument("--asked-by", required=True)
    p.add_argument("--as-of", default=None)
    p.add_argument("--role", default=None)
    p.add_argument("--name", default=None)

    p = sub.add_parser("dashboards", help="list saved dashboard specs")
    p.add_argument("--name", default=None)
    p.add_argument("--saved-by", default=None)

    p = sub.add_parser("dashboard-spec", help="read one dashboard spec")
    p.add_argument("spec_id")

    p = sub.add_parser("assemble", help="assemble a spec into a verified dashboard")
    p.add_argument("spec_id")
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("dashboard", help="print a spec's current dashboard HTML")
    p.add_argument("spec_id")

    p = sub.add_parser("verify-dashboard", help="re-perform every figure on a stored assembly")
    p.add_argument("assembly_id")

    p = sub.add_parser("role-dashboard", help="build a role's default dashboard spec")
    p.add_argument("--role", required=True)
    p.add_argument("--asked-by", required=True)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("scenario", help="fork a head estimate/projection with stated levers")
    p.add_argument("--kind", required=True,
                   choices=["demand_estimate", "supply_projection"])
    p.add_argument("--district", default=None)
    p.add_argument("--product", required=True)
    p.add_argument("--crop-year", required=True)
    p.add_argument("--season", required=True)
    p.add_argument("--lever", action="append", required=True,
                   help="lever=value, or lever=months@SHIPMENT_ID for "
                        "an import shift; repeatable")
    p.add_argument("--by", required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--as-of", default=None)

    p = sub.add_parser("scenario-ask", help="fork from a plain-language scenario request")
    p.add_argument("--question", required=True)
    p.add_argument("--asked-by", required=True)
    p.add_argument("--name", default=None)

    p = sub.add_parser("scenarios", help="list stored scenario forks")
    p.add_argument("--base", default=None)

    p = sub.add_parser("verify-scenario", help="re-perform a stored scenario fork")
    p.add_argument("fork_id")

    p = sub.add_parser("planning-options", help="compare a base and its forks side by side")
    p.add_argument("--base", required=True)
    p.add_argument("--fork", action="append", required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--name", default=None)

    p = sub.add_parser("options", help="read one planning-options artefact")
    p.add_argument("options_id")

    p = sub.add_parser("verify-options", help="re-perform a stored comparison")
    p.add_argument("options_id")

    p = sub.add_parser("adopt", help="adopt one compared option by a named planner's act")
    p.add_argument("--options", required=True)
    p.add_argument("--fork", default=None,
                   help="the fork to adopt; omit to adopt the base view")
    p.add_argument("--by", required=True)
    p.add_argument("--as-of", default=None)
    p.add_argument("--note", default=None)

    p = sub.add_parser("adoption", help="the current adoption for a comparison")
    p.add_argument("options_id")

    p = sub.add_parser("verify-adoption", help="verify a stored adoption act")
    p.add_argument("adoption_id")

    args = parser.parse_args(argv)
    service = _service(args)
    as_of = getattr(args, "as_of", None) or date.today().isoformat()
    try:
        if args.command == "estimate":
            result = service.estimate_demand(
                args.district, args.product, args.crop_year, args.season, as_of
            )
        elif args.command == "outlook":
            result = service.demand_outlook(args.crop_year, args.season, as_of)
        elif args.command == "contributions":
            if service.store.get_estimate(args.estimate_id) is None:
                print(f"no such estimate: {args.estimate_id}", file=sys.stderr)
                return 2
            result = service.store.estimate_contributions(args.estimate_id)
        elif args.command == "narrative":
            result = service.draft_outlook_narrative(args.crop_year, args.season, as_of)
        elif args.command == "watch-run":
            result = service.run_price_watch(as_of)
        elif args.command == "movements":
            result = service.store.list_movements(args.series_kind, args.item)
        elif args.command == "alerts":
            result = service.list_alerts(args.series_kind, args.item, args.rule_id, args.state)
        elif args.command == "alert":
            result = service.get_alert(args.alert_id)
            if result is None:
                print(f"no such alert: {args.alert_id}", file=sys.stderr)
                return 2
        elif args.command == "acknowledge":
            result = service.acknowledge_alert(args.alert_id, args.actor, args.note, as_of)
        elif args.command == "close":
            result = service.close_alert(args.alert_id, args.actor, args.reason, as_of)
        elif args.command == "watch":
            result = service.watch_board()
        elif args.command == "watch-series":
            known = {(p["series_kind"], p["item"]) for p in service.store.price_points()}
            if (args.series_kind, args.item) not in known:
                print(f"no such price series: {args.series_kind}/{args.item}", file=sys.stderr)
                return 2
            result = service.series_watch(args.series_kind, args.item)
        elif args.command == "positions":
            result = service.supply_positions(args.product, as_of)
        elif args.command == "position":
            result = service.get_position(args.product, args.month)
            if result is None:
                print(
                    f"no supply position for {args.product} {args.month}",
                    file=sys.stderr,
                )
                return 2
        elif args.command == "verify-position":
            position = service.get_position(args.product, args.month)
            if position is None:
                print(
                    f"no supply position for {args.product} {args.month}",
                    file=sys.stderr,
                )
                return 2
            problems = service.verify_position(args.product, args.month)
            result = {
                "position_id": position["position_id"],
                "ok": not problems, "problems": problems,
            }
        elif args.command == "gap":
            result = service.supply_gap(args.product, args.crop_year, args.season, as_of)
        elif args.command == "verify-gap":
            gap = service.get_gap(args.product, args.crop_year, args.season)
            if gap is None:
                print(
                    f"no supply gap computed for {args.product} "
                    f"{args.crop_year} {args.season}",
                    file=sys.stderr,
                )
                return 2
            problems = service.verify_gap(args.product, args.crop_year, args.season)
            result = {"gap_id": gap["gap_id"], "ok": not problems, "problems": problems}
        elif args.command == "projection":
            result = service.supply_projection(
                args.product, args.crop_year, args.season, as_of
            )
        elif args.command == "verify-projection":
            projection = service.get_projection(args.product, args.crop_year, args.season)
            if projection is None:
                print(
                    f"no supply projection computed for {args.product} "
                    f"{args.crop_year} {args.season}",
                    file=sys.stderr,
                )
                return 2
            problems = service.verify_projection(
                args.product, args.crop_year, args.season
            )
            result = {
                "projection_id": projection["projection_id"],
                "ok": not problems, "problems": problems,
            }
        elif args.command == "policy-register":
            result = service.register_policy_events(as_of)
        elif args.command == "policy-events":
            hypothetical = True if args.hypothetical else (
                False if args.actual else None
            )
            result = service.list_policy_events(hypothetical, args.event_class)
        elif args.command == "policy-event":
            spec = {
                "event_id": args.event_id,
                "event_class": args.event_class,
                "title": args.title,
                "detail": args.detail,
                "effective_from_month": args.from_month,
                "effective_to_month": args.to_month,
                "products": [p.strip() for p in args.products.split(",") if p.strip()],
                "districts": [d.strip() for d in args.districts.split(",") if d.strip()],
                "direction": args.direction,
                "driver": args.driver,
                "mechanism": args.mechanism,
                "hypothetical": args.hypothetical,
                "source": args.source,
                "recorded_on": args.recorded_on,
                "registered_by": args.registered_by,
            }
            result = service.register_policy_event(spec, as_of)
        elif args.command == "policy":
            result = service.get_policy_event(args.registry_id)
            if result is None:
                print(f"no such policy registration: {args.registry_id}", file=sys.stderr)
                return 2
        elif args.command == "verify-policy":
            event = service.get_policy_event(args.registry_id)
            if event is None:
                print(f"no such policy registration: {args.registry_id}", file=sys.stderr)
                return 2
            problems = service.verify_policy_event(args.registry_id)
            result = {
                "registry_id": args.registry_id,
                "ok": not problems, "problems": problems,
            }
        elif args.command == "policy-impact":
            if service.get_policy_event(args.registry_id) is None:
                print(f"no such policy registration: {args.registry_id}", file=sys.stderr)
                return 2
            result = service.policy_impact(args.registry_id, as_of)
        elif args.command == "verify-policy-impact":
            note = service.get_policy_impact(args.registry_id)
            if note is None:
                print(
                    f"no impact note computed for registration {args.registry_id}",
                    file=sys.stderr,
                )
                return 2
            problems = service.verify_policy_impact(args.registry_id)
            result = {
                "note_id": note["note_id"],
                "ok": not problems, "problems": problems,
            }
        elif args.command == "observations-build":
            result = service.build_competitor_observations()
        elif args.command == "observations":
            result = service.list_competitor_observations(
                args.competitor, args.region, args.product, args.season
            )
        elif args.command == "observation":
            result = service.get_competitor_observation(args.observation_id)
            if result is None:
                print(
                    f"no such competitor observation: {args.observation_id}",
                    file=sys.stderr,
                )
                return 2
        elif args.command == "verify-observation":
            observation = service.get_competitor_observation(args.observation_id)
            if observation is None:
                print(
                    f"no such competitor observation: {args.observation_id}",
                    file=sys.stderr,
                )
                return 2
            problems = service.verify_competitor_observation(args.observation_id)
            result = {
                "observation_id": args.observation_id,
                "ok": not problems, "problems": problems,
            }
        elif args.command == "share":
            result = service.market_share(
                args.district, args.product, args.crop_year, args.season,
                args.as_of,
            )
        elif args.command == "verify-share":
            share = service.get_share(
                args.district, args.product, args.crop_year, args.season,
                args.as_of,
            )
            if share is None:
                print(
                    f"no market share computed for {args.district} "
                    f"{args.product} {args.crop_year} {args.season}",
                    file=sys.stderr,
                )
                return 2
            problems = service.verify_share(share["share_id"])
            result = {
                "share_id": share["share_id"],
                "ok": not problems, "problems": problems,
            }
        elif args.command == "share-stale":
            result = service.share_stale_exclusions(
                args.district, args.product, args.crop_year, args.season,
                args.as_of,
            )
        elif args.command == "share-movement":
            result = service.share_movement(
                args.district, args.product, args.season, as_of
            )
        elif args.command == "verify-share-movement":
            movement = service.get_share_movement(
                args.district, args.product, args.season
            )
            if movement is None:
                print(
                    f"no share movement computed for {args.district} "
                    f"{args.product} {args.season}",
                    file=sys.stderr,
                )
                return 2
            problems = service.verify_share_movement(movement["movement_id"])
            result = {
                "movement_id": movement["movement_id"],
                "ok": not problems, "problems": problems,
            }
        elif args.command == "field-sync":
            batch = json.loads(Path(args.file).read_text(encoding="utf-8"))
            submissions = batch["submissions"] if isinstance(batch, dict) else batch
            result = service.sync_field_reports(submissions, as_of)
        elif args.command == "field-promote":
            result = service.promote_planted_field_reports(as_of)
        elif args.command == "field-reports":
            result = service.list_field_reports(
                state=args.state, district_id=args.district, product=args.product
            )
        elif args.command == "field-report":
            report = service.get_field_report(args.report_id)
            if report is None:
                print(f"no such field report: {args.report_id}", file=sys.stderr)
                return 2
            result = report
        elif args.command == "verify-field-report":
            if service.get_field_report(args.report_id) is None:
                print(f"no such field report: {args.report_id}", file=sys.stderr)
                return 2
            problems = service.verify_field_report(args.report_id)
            result = {
                "report_id": args.report_id,
                "ok": not problems, "problems": problems,
            }
        elif args.command == "field-review":
            result = service.review_field_report(
                args.report_id, args.act, args.actor, args.reason,
                as_of, note=args.note,
            )
        elif args.command == "field-queue":
            result = service.list_field_reports(state=args.state)
        elif args.command == "field-assessment":
            result = service.field_signal_assessment(
                args.district, args.product, args.crop_year, args.season, as_of
            )
        elif args.command == "verify-field-assessment":
            assessment = service.get_field_assessment(
                args.district, args.product, args.crop_year, args.season,
                args.as_of,
            )
            if assessment is None:
                print(
                    f"no field assessment computed for {args.district} "
                    f"{args.product} {args.crop_year} {args.season}",
                    file=sys.stderr,
                )
                return 2
            problems = service.verify_field_assessment(assessment["assessment_id"])
            result = {
                "assessment_id": assessment["assessment_id"],
                "ok": not problems, "problems": problems,
            }
        elif args.command == "ask":
            result = service.ask_question(
                args.question, args.asked_by, as_of,
                role=args.role, name=args.name,
            )
        elif args.command == "dashboards":
            result = service.list_dashboard_specs(
                name=args.name, saved_by=args.saved_by)
        elif args.command == "dashboard-spec":
            result = service.get_dashboard_spec(args.spec_id)
            if result is None:
                print(f"no such dashboard spec: {args.spec_id}",
                      file=sys.stderr)
                return 2
        elif args.command == "assemble":
            result = service.assemble_dashboard(args.spec_id, as_of)
        elif args.command == "dashboard":
            page = service.dashboard_html(args.spec_id)
            if page is None:
                print(f"no such dashboard spec: {args.spec_id}",
                      file=sys.stderr)
                return 2
            print(page)
            return 0
        elif args.command == "verify-dashboard":
            result = service.verify_dashboard(args.assembly_id)
        elif args.command == "role-dashboard":
            result = service.role_default_dashboard(
                args.role, args.asked_by, as_of)
        elif args.command == "scenario":
            levers = []
            for raw in args.lever:
                spec, _, shipment = raw.partition("@")
                lever, _, value = spec.partition("=")
                entry = {"lever": lever.strip(),
                         "value": float(value)}
                if shipment:
                    entry["shipment_id"] = shipment.strip()
                levers.append(entry)
            scope = {"product": args.product,
                     "crop_year": args.crop_year, "season": args.season}
            if args.kind == "demand_estimate":
                if not args.district:
                    print("a demand fork names --district",
                          file=sys.stderr)
                    return 2
                scope = {"district_id": args.district, **scope}
            result = service.create_scenario(
                args.kind, scope, levers, args.by, name=args.name,
                as_of=args.as_of)
        elif args.command == "scenario-ask":
            result = service.ask_scenario(
                args.question, args.asked_by, name=args.name)
        elif args.command == "scenarios":
            result = service.list_scenarios(args.base)
        elif args.command == "verify-scenario":
            result = service.verify_scenario(args.fork_id)
        elif args.command == "planning-options":
            result = service.build_planning_options(
                args.base, args.fork, args.by, name=args.name)
        elif args.command == "options":
            result = service.get_planning_options(args.options_id)
            if result is None:
                print(f"no such planning options: {args.options_id}",
                      file=sys.stderr)
                return 2
        elif args.command == "verify-options":
            result = service.verify_planning_options(args.options_id)
        elif args.command == "adopt":
            result = service.adopt_option(
                args.options, args.fork, args.by, as_of, note=args.note)
        elif args.command == "adoption":
            result = service.current_adoption(args.options_id)
            if result is None:
                print(f"no adoption recorded for {args.options_id}",
                      file=sys.stderr)
                return 2
        elif args.command == "verify-adoption":
            result = service.verify_adoption(args.adoption_id)
        else:  # pragma: no cover - argparse enforces the choices
            return 2
    except NarrativeRefused as exc:
        print(json.dumps({"refused": exc.problems}, indent=2), file=sys.stderr)
        return 2
    except AlertStateError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except FieldReviewError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
