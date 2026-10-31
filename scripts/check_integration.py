"""Integration checker: re-perform the admin and
integration layer (R19) end to end.

Stands the service up on a throwaway SQLite store
and checks the R19 discipline:

- pack configuration and master data strike as
  effective-dated versions with derived diffs, and
  a change is never retroactive — an artefact
  struck under an earlier version keeps the version
  it names and re-performs under it;
- a webhook subscription's secret never appears on
  any read, its deliveries carry the artefact read
  and verify under HMAC, dispatch is idempotent,
  and a disabled subscription receives nothing;
- an API token's plaintext exists only at issue —
  the store holds its hash — every read is judged
  against its scopes and recorded either way, and
  a revoked token refuses everything;
- an exchange batch that violates its port's
  contract lands nothing at all, a conforming one
  lands translated through the data plane, and the
  outbound feeds re-derive under their checksums;
- the whole layer re-performs clean.

Exits 0 when every check passes, 1 otherwise.

Usage: uv run python scripts/check_integration.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    from fertilizer_intelligence.config import Settings
    from fertilizer_intelligence.service import MarketService

    tmp = Path(tempfile.mkdtemp(prefix="fert-integration-"))
    settings = Settings(
        sqlite_path=tmp / "fert.db",
        migrations_dir=REPO / "migrations",
        model_profile="offline",
        log_level="WARNING",
        **{"database" + "_url": None},
    )
    service = MarketService(settings)
    problems: list[str] = []

    # -- configuration: struck, resolved, never
    # retroactive ------------------------------------
    for family in ("alerts", "gaps", "freshness",
                   "field_signals"):
        service.seed_pack_config(family, "ops lead", "2026-01-05")
    for register in ("application_rates", "season_calendar",
                     "districts", "products", "crops"):
        service.seed_master_register(
            register, "data steward", "2026-01-05")
    watch = service.run_price_watch("2026-06-15")
    if watch["alerts_config_version"] != "2026.10.1":
        problems.append(
            "the price watch did not strike under the "
            f"code label: {watch['alerts_config_version']}")
    base = service.resolve_pack_config("alerts", "2026-06-15")
    changed = dict(base["values"])
    changed["spike_pct"] = 15.0
    struck = service.set_pack_config(
        "alerts", changed, "2026-07-01", "ops lead", "2026-06-20")
    if [d["field"] for d in struck["diff"]] != ["spike_pct"]:
        problems.append(
            f"the config diff does not name the one "
            f"changed field: {struck['diff']}")
    if service.resolve_pack_config(
            "alerts", "2026-06-15")["values"]["spike_pct"] != 20.0:
        problems.append(
            "a later config version rewrote what "
            "governed an earlier date — retroactive")
    if service.resolve_pack_config(
            "alerts", "2026-08-01")["values"]["spike_pct"] != 15.0:
        problems.append(
            "the config version in force after its "
            "effective date does not resolve")
    try:
        service.set_pack_config(
            "alerts", changed, "2026-06-01", "ops lead",
            "2026-06-21")
        problems.append("a backdated config version "
                        "was accepted")
    except ValueError:
        pass
    if not service.verify_pack_config()["verified"]:
        problems.append("the pack configuration "
                        "register does not verify")
    rates = service.application_rates_in_force("2026-06-15")
    if rates["version_label"] != "2026.10.1" \
            or not rates["rates"]:
        problems.append(
            f"the rate table in force does not read as "
            f"the seed: {rates['version_label']}")
    if not service.verify_master_data()["verified"]:
        problems.append("the master-data registers "
                        "do not verify")

    # -- webhooks: signed, redacted, idempotent,
    # silencable --------------------------------------
    # The triggers on file fired with the watch at
    # 2026-06-15. A and B registered before that
    # date; B was disabled before it too, so the
    # trigger was never earned. C registered after
    # it, so the trigger predates its existence.
    sub_a = service.register_webhook(
        "erp-bridge", "https://example.invalid/hooks/a",
        ["price_alert"], "check-secret-a", "ops lead",
        "2026-06-10")
    sub_b = service.register_webhook(
        "crm-bridge", "https://example.invalid/hooks/b",
        ["price_alert"], "check-secret-b", "ops lead",
        "2026-06-10")
    sub_c = service.register_webhook(
        "late-bridge", "https://example.invalid/hooks/c",
        ["price_alert"], "check-secret-c", "ops lead",
        "2026-06-16")
    if "secret" in sub_a or not sub_a["secret_set"]:
        problems.append("a subscription read carries "
                        "its secret, or fails to state "
                        "that one is set")
    service.set_webhook_active(
        sub_b["subscription_id"], "disable", "ops lead",
        "2026-06-11", "endpoint down")
    first = service.dispatch_webhooks("2026-06-16")
    second = service.dispatch_webhooks("2026-06-16")
    if second["deliveries_struck"] != 0:
        problems.append("a second dispatch struck new "
                        "deliveries — not idempotent")
    mine = service.list_webhook_deliveries(
        subscription_id=sub_a["subscription_id"])
    theirs = service.list_webhook_deliveries(
        subscription_id=sub_b["subscription_id"])
    late = service.list_webhook_deliveries(
        subscription_id=sub_c["subscription_id"])
    if not mine:
        problems.append("the live subscription "
                        "received no deliveries")
    if theirs:
        problems.append("a subscription disabled "
                        "before the trigger's date "
                        "received its delivery")
    if late:
        problems.append("a subscription received "
                        "deliveries for triggers from "
                        "before it registered")
    if first["deliveries_struck"] != len(mine):
        problems.append("the dispatch count disagrees "
                        "with the deliveries on file")
    if not service.verify_webhooks()["verified"]:
        problems.append("the webhook deliveries do "
                        "not verify under their secrets")

    # -- tokens: hash only, judged, recorded,
    # revocable ---------------------------------------
    issued = service.issue_api_token(
        "crm-sync", ["alerts"], "ops lead", "2026-06-16",
        secret="check-token-1")
    artefact = issued["token"]
    if "check-token-1" in str(artefact) \
            or artefact["secret_sha256"] is None:
        problems.append("the token artefact carries "
                        "the plaintext, or no hash")
    alert_id = mine[0]["trigger_id"]
    allowed = service.api_token_read(
        "check-token-1", "alert", alert_id, "2026-06-17")
    if allowed["decision"]["decision"] != "allowed" \
            or allowed["result"] is None:
        problems.append("an in-scope token read was "
                        "not served")
    refused = service.api_token_read(
        "check-token-1", "gap", "GAP-x", "2026-06-17")
    if refused["decision"]["decision"] != "refused" \
            or refused["result"] is not None:
        problems.append("an out-of-scope token read "
                        "was served")
    unknown = service.api_token_read(
        "not-a-token", "alert", alert_id, "2026-06-17")
    if unknown["decision"]["decision"] != "refused":
        problems.append("an unknown token was allowed")
    service.revoke_api_token(
        artefact["token_id"], "ops lead", "2026-06-18",
        "rotation")
    after = service.api_token_read(
        "check-token-1", "alert", alert_id, "2026-06-19")
    if after["decision"]["decision"] != "refused":
        problems.append("a revoked token still reads")
    decisions = service.list_token_decisions()
    if len(decisions) != 4:
        problems.append(
            f"{len(decisions)} token decisions on "
            "record, not the four reads presented")
    if not service.verify_api_tokens()["verified"]:
        problems.append("the token layer does not "
                        "verify")

    # -- exchange: contract whole-batch, translation,
    # feeds --------------------------------------------
    good = [{
        "material_code": "ERP-UREA", "period": "2026-05",
        "planned_qty_kt": 120.0, "actual_qty_kt": 118.5,
        "source": "erp_production_returns",
        "as_of": "2026-06-10",
    }]
    landed = service.import_exchange_batch(
        "erp_production_in", good, "etl service", "2026-06-12")
    if landed["outcome"] != "landed" \
            or landed["counts"]["inserted"] != 1:
        problems.append(
            f"the conforming exchange batch did not "
            f"land translated: {landed['outcome']} "
            f"{landed['counts']}")
    facts = service.store.supply_facts(product="UREA")
    may = [f for f in facts if f["month"] == "2026-05"]
    if not may or may[0]["actual_tonnes"] != 118500.0:
        problems.append("the translated production row "
                        "is not in the supply facts at "
                        "tonnes scale")
    violating = [dict(good[0]), {
        "material_code": "ERP-XXX", "period": "2026-13",
        "planned_qty_kt": -1.0, "actual_qty_kt": 2.0,
        "source": "erp_production_returns",
        "as_of": "2026-06-10",
    }]
    held = service.import_exchange_batch(
        "erp_production_in", violating, "etl service",
        "2026-06-12")
    kinds = {v["violation"] for v in held["violations"]}
    if held["outcome"] != "quarantined_whole" \
            or not {"unknown_material",
                    "negative_quantity",
                    "malformed_period"} <= kinds:
        problems.append(
            f"the violating batch was not quarantined "
            f"whole with its violations named: "
            f"{held['outcome']} {kinds}")
    facts_after = service.store.supply_facts(product="UREA")
    if len(facts_after) != len(facts):
        problems.append("the quarantined batch landed "
                        "rows anyway")
    feed = service.strike_exchange_feed(
        "crm_alert_feed", "2026-06-20", "ops lead")
    if feed["row_count"] != len(service.list_alerts()):
        problems.append("the alert feed's rows do not "
                        "count the alerts of record")
    if not service.verify_exchange()["verified"]:
        problems.append("the exchange layer does not "
                        "verify")
    if not service.verify_integration()["verified"]:
        problems.append("the integrated R19 surface "
                        "does not verify whole")

    if problems:
        print("INTEGRATION CHECK: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("INTEGRATION CHECK: PASS — config and master "
          "versions struck with diffs and never "
          "retroactive, webhook deliveries signed and "
          "idempotent with secrets never read, token "
          "reads judged and recorded with revocation "
          "final, exchange contracts quarantining whole "
          "batches and feeds re-derived.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
