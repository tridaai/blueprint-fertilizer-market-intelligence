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
        else:  # pragma: no cover - argparse enforces the choices
            return 2
    except NarrativeRefused as exc:
        print(json.dumps({"refused": exc.problems}, indent=2), file=sys.stderr)
        return 2
    except AlertStateError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
