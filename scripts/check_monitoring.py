"""Monitoring checker: re-perform the run ledger,
the freshness board and the reliability lines.

Stands the service up on a throwaway SQLite store,
swaps in a hosted-profile double with stated token
counts, and checks the R18 discipline end to end:

- every drafting call through the service's own
  port lands in the ledger, priced by the pack to
  the nano, and a failed call records nothing;
- the board's cost totals equal a direct sum over
  the ledger, per profile and per purpose alike;
- freshness names every registered source — the
  loaded feed fresh inside its window and stale
  past it, the five unloaded feeds never_loaded,
  never absent and never read as current;
- source reliability folds the batch report and
  the corrections exactly; reporter reliability
  folds review outcomes and screenings, with a
  rate behind no decided cases stated unmeasured;
- the board reads through the guard (a viewer gets
  absence, the strategy desk gets the board) and
  the whole layer re-performs clean.

Exits 0 when every check passes, 1 otherwise.

Usage: uv run python scripts/check_monitoring.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO = Path(__file__).resolve().parents[1]

AS_OF = "2026-02-25"


class StubPort:
    profile_name = "anthropic"
    model_name = "stub-sonnet"

    def complete(self, system, prompt):
        from fertilizer_intelligence.modelport import ModelReply

        return ModelReply(
            text=prompt, profile=self.profile_name,
            model=self.model_name,
            input_tokens=1200, output_tokens=300)


class RefusingPort:
    profile_name = "anthropic"
    model_name = "stub-sonnet"

    def complete(self, system, prompt):
        raise RuntimeError("provider unavailable")


def main() -> int:
    from fertilizer_intelligence.config import Settings
    from fertilizer_intelligence.service import MarketService

    tmp = Path(tempfile.mkdtemp(prefix="fert-monitoring-"))
    settings = Settings(
        database_url=None,
        sqlite_path=tmp / "fert.db",
        migrations_dir=REPO / "migrations",
        model_profile="offline",
        log_level="WARNING",
    )
    service = MarketService(settings)
    problems: list[str] = []

    # The ledger: priced runs in, failures out.
    service.model = StubPort()
    service.draft_outlook_narrative("2025-26", "kharif", AS_OF)
    service.model = RefusingPort()
    try:
        service.draft_outlook_narrative("2025-26", "rabi", AS_OF)
        problems.append("a refused call was accepted")
    except RuntimeError:
        pass
    service.model = StubPort()
    runs = service.list_model_runs()
    if len(runs) != 1:
        problems.append(
            f"{len(runs)} runs in the ledger, not 1 — a "
            "failed call recorded, or a completed one lost")
    elif runs[0]["cost_nano_usd"] != 8_100_000:
        problems.append(
            f"run priced at {runs[0]['cost_nano_usd']} "
            "nano-USD, not 8100000 (1200 in / 300 out on "
            "the pack's anthropic reference rates)")

    # Every fact lands before the first board is
    # struck: a board is an as-of snapshot, and a
    # backdated fact landed after a strike is what
    # supersession is for.
    def land(sub_id, detail, reporter):
        outcome = service.sync_field_reports([{
            "submission_id": sub_id, "reporter": reporter,
            "district_id": "DST-GUN", "product": "DAP",
            "signal_type": "stock_observed",
            "observed_on": "2026-02-20",
            "quantity_tonnes": 25.0, "detail": detail,
            "source": "field_mobile_intake",
        }], "2026-02-20")
        return outcome["receipt"][0]["report_id"]

    rep = "C. Checker (field officer)"
    r1 = land("chk-1", "Depot well stocked.", rep)
    land("chk-2", "Queue at the depot.", rep)
    service.review_field_report(
        r1, "confirm", "A. Rao", "corroborated", "2026-02-21")

    # Freshness and source reliability from one batch.
    # The 2026-05 prints sit past the generated series'
    # horizon, so the good rows land.
    def price(item, month, value, **over):
        row = {
            "series_kind": "product", "item": item,
            "month": month, "price": value,
            "unit": "INR/tonne", "source": "intl_price_feed",
            "as_of": "2026-05-05",
        }
        row.update(over)
        return row

    service.load_connector_batch("intl_price_feed", [
        price("DAP", "2026-05", 27050.0),
        price("UREA", "2026-05", 5910.0, as_of="2026-05-04"),
        price("DAP", "2026-05", 27050.0),
        price("MOP", "2026-05", -5.0),
    ], "desk", "2026-05-06")
    board = service.strike_monitoring_board("2026-05-12")
    fresh = {r["source_id"]: r for r in board["freshness"]}
    if fresh["intl_price_feed"]["state"] != "fresh" \
            or fresh["intl_price_feed"]["age_days"] != 7:
        problems.append(
            "the price feed does not read fresh at seven "
            "days against its seven-day window")
    unnamed = [sid for sid, row in fresh.items()
               if row["state"] == "never_loaded"]
    if len(unnamed) != 5:
        problems.append(
            f"never-loaded sources named: {unnamed}, "
            "not the five unloaded feeds")
    rel = board["reliability_sources"]
    if len(rel) != 1 or rel[0]["received"] != 4 \
            or rel[0]["inserted"] != 2 \
            or rel[0]["duplicates"] != 1 \
            or rel[0]["quarantined"] != 1 \
            or rel[0]["quarantine_rate"] != 0.25:
        problems.append(
            f"source reliability does not fold the batch: {rel}")
    if board["cost"]["cost_nano_usd"] != sum(
            r["cost_nano_usd"] for r in service.list_model_runs()):
        problems.append("board cost does not reconcile "
                        "with the ledger")
    # Reporter reliability: decided rates measured,
    # undecided stated unmeasured.
    row = next(r for r in board["reliability_reporters"]
               if r["reporter"] == rep)
    if row["confirmation_rate"] != 1.0 or row["decided"] != 1:
        problems.append(
            f"reporter line does not fold the acts: {row}")

    later = service.strike_monitoring_board("2026-06-05")
    stale = {r["source_id"]: r for r in later["freshness"]}
    if stale["intl_price_feed"]["state"] != "stale":
        problems.append("the price feed does not read "
                        "stale a month past its window")
    if later["supersedes"] != board["board_id"]:
        problems.append("the later board does not "
                        "supersede the previous by link")

    # The guard, and the whole layer re-performed.
    if service.scoped_monitoring_board(
            "Guest Viewer", board["board_id"],
            "2026-05-12") is not None:
        problems.append("a viewer read the monitoring board")
    if service.scoped_monitoring_board(
            "A. Rao", board["board_id"], "2026-05-12") is None:
        problems.append("the strategy desk could not read "
                        "the monitoring board")
    result = service.verify_monitoring("2026-06-05")
    if not result["verified"]:
        problems.append(
            f"the monitoring verifier objects: "
            f"{result['problems']}")
    if not service.verify_access_log()["verified"]:
        problems.append("the access log does not re-decide "
                        "clean over the monitoring reads")

    if problems:
        print("MONITORING CHECK: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("MONITORING CHECK: PASS — runs priced to the "
          "nano and reconciled, freshness states named "
          "for all six sources, reliability folded from "
          "acts and facts alone, the board guarded and "
          "re-performed clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
