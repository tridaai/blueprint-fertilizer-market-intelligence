"""Round 7: field signals & mobile intake — the planted R1
reports promoted through the intake's landing machinery,
exactly-once sync (a killed-mid-sync re-send lands nothing
twice), conflicts kept both and linked, intake validation
naming the missing attribution fields, the verification
queue with its act vocabulary and terminal rejection, and
the weighting assessment graded numerically: an unreviewed
report that would move the estimate by 5.345394% is capped
at exactly the pack's 1.5, a confirmed report carries its
full decayed weight, queried and rejected reports carry
zero, an expired report is named at zero — every figure
re-derived independently in the tests from the pack's stated
rules, plus tamper detection and API/CLI parity.
"""

import json
import sqlite3
from datetime import date

import pytest

from fertilizer_intelligence.field import FieldReviewError

AS_OF = "2026-04-15"
REVIEWER = "A. Reviewer (regional desk)"

# The graded cap case: a fresh demand surge at Ludhiana for
# DAP, observed 2025-10-28 (kharif's window, by the unique
# attribution rule), assessed five days later.
CAP_SUB = {
    "submission_id": "DEV-CAP-1",
    "reporter": "T. Rao (field officer)",
    "district_id": "DST-LUD",
    "product": "DAP",
    "signal_type": "demand_signal",
    "direction": "up",
    "observed_on": "2025-10-28",
    "detail": "Wheat-belt DAP offtake surging.",
}
CAP_AS_OF = "2025-11-02"
CAP_DECAY = round(0.5 ** (5 / 30), 6)          # 0.890899
CAP_UNCAPPED = round(6.0 * CAP_DECAY, 6)       # 5.345394
CAP_PCT = 1.5                                  # the pack's unverified cap


from rawdb import raw_connect


def _promote(service):
    return service.promote_planted_field_reports(AS_OF)


def test_planted_promotion_lands_twelve_attributed(service):
    receipt = _promote(service)
    assert receipt["landed"] == 12
    assert receipt["duplicates"] == 0
    assert receipt["reports_total"] == 12
    queue = service.list_field_reports(state="unreviewed")
    assert len(queue) == 12
    facts = {f["report_id"]: f for f in service.store.field_reports()}
    for view in queue:
        fact = facts[view["submission_id"]]
        assert view["reporter"] == fact["reporter"]
        assert view["district_id"] == fact["district_id"]
        assert view["observed_on"] == fact["date"]
        assert view["signal_kind"] == fact["signal_kind"]
        assert view["review_state"] == "unreviewed"
        assert view["acts"] == []
        assert service.verify_field_report(view["report_id"]) == []
    again = _promote(service)
    assert again["landed"] == 0
    assert again["duplicates"] == 12
    assert again["reports_total"] == 12


def test_intake_validation_names_missing_fields(service):
    bad = {"submission_id": "BAD-1", "district_id": "DST-LUD", "product": "DAP"}
    with pytest.raises(ValueError) as excinfo:
        service.sync_field_reports([bad], AS_OF)
    message = str(excinfo.value)
    for field in ("reporter", "signal_type", "observed_on"):
        assert field in message
    assert service.store.list_field_report_artefacts() == []

    unknown = dict(CAP_SUB, submission_id="BAD-2", district_id="DST-XXX")
    with pytest.raises(ValueError, match="unknown district"):
        service.sync_field_reports([unknown], AS_OF)

    no_direction = dict(CAP_SUB, submission_id="BAD-3")
    del no_direction["direction"]
    with pytest.raises(ValueError, match="direction"):
        service.sync_field_reports([no_direction], AS_OF)

    bad_type = dict(CAP_SUB, submission_id="BAD-4", signal_type="rumour")
    with pytest.raises(ValueError, match="signal type"):
        service.sync_field_reports([bad_type], AS_OF)


def test_sync_exactly_once_and_partial_retry(service):
    batch = [
        dict(CAP_SUB, submission_id=f"DEV-B{i}", observed_on="2025-10-28")
        for i in range(3)
    ]
    first = service.sync_field_reports(batch[:1], CAP_AS_OF)
    assert [r["outcome"] for r in first["receipt"]] == ["landed"]
    # The connection drops; the phone re-sends the whole outbox.
    retry = service.sync_field_reports(batch, CAP_AS_OF)
    assert [r["outcome"] for r in retry["receipt"]] == [
        "duplicate", "landed", "landed",
    ]
    assert retry["reports_total"] == 3
    again = service.sync_field_reports(batch, CAP_AS_OF)
    assert [r["outcome"] for r in again["receipt"]] == ["duplicate"] * 3
    assert len(service.store.list_field_report_artefacts()) == 3


def test_conflict_keeps_both_linked(service):
    service.sync_field_reports([CAP_SUB], CAP_AS_OF)
    changed = dict(CAP_SUB, detail="Corrected wording from the phone.")
    receipt = service.sync_field_reports([changed], "2025-11-03")
    assert receipt["receipt"][0]["outcome"] == "conflict"
    conflict_id = receipt["receipt"][0]["report_id"]
    assert conflict_id != "FSR-DEV-CAP-1"
    original = service.get_field_report("FSR-DEV-CAP-1")
    conflicting = service.get_field_report(conflict_id)
    assert original["has_conflict"] is True
    assert original["conflict_report_ids"] == [conflict_id]
    assert conflicting["has_conflict"] is True
    assert conflicting["conflict_report_ids"] == ["FSR-DEV-CAP-1"]
    assert conflicting["conflicts_with"] == "FSR-DEV-CAP-1"
    # The original's words were never overwritten.
    assert original["detail"] == CAP_SUB["detail"]
    assert conflicting["detail"] == "Corrected wording from the phone."
    assert service.verify_field_report("FSR-DEV-CAP-1") == []
    assert service.verify_field_report(conflict_id) == []
    # Re-sending the conflict is a duplicate, not a third copy.
    again = service.sync_field_reports([changed], "2025-11-03")
    assert again["receipt"][0]["outcome"] == "duplicate"
    assert len(service.store.list_field_report_artefacts()) == 2


def test_review_acts_states_and_terminal_reject(service):
    _promote(service)
    view = service.review_field_report(
        "FSR-FR-001", "query", REVIEWER, "needs_quantity", AS_OF)
    assert view["review_state"] == "queried"
    assert view["acts"][0]["actor"] == REVIEWER
    assert view["acts"][0]["reason"] == "needs_quantity"
    view = service.review_field_report(
        "FSR-FR-001", "confirm", REVIEWER, "corroborated", AS_OF)
    assert view["review_state"] == "confirmed"
    assert len(service.list_field_reports(state="confirmed")) == 1
    with pytest.raises(FieldReviewError, match="already confirmed"):
        service.review_field_report(
            "FSR-FR-001", "confirm", REVIEWER, "corroborated", AS_OF)
    with pytest.raises(ValueError, match="reason must be one of"):
        service.review_field_report(
            "FSR-FR-002", "confirm", REVIEWER, "needs_quantity", AS_OF)
    with pytest.raises(ValueError, match="named reviewer"):
        service.review_field_report(
            "FSR-FR-002", "confirm", "  ", "corroborated", AS_OF)
    rejected = service.review_field_report(
        "FSR-FR-002", "reject", REVIEWER, "not_credible", AS_OF)
    assert rejected["review_state"] == "rejected"
    with pytest.raises(FieldReviewError, match="terminal"):
        service.review_field_report(
            "FSR-FR-002", "confirm", REVIEWER, "corroborated", AS_OF)
    with pytest.raises(ValueError, match="no such field report"):
        service.review_field_report(
            "FSR-FR-999", "confirm", REVIEWER, "corroborated", AS_OF)


def test_unverified_cap_is_exact(service):
    service.sync_field_reports([CAP_SUB], CAP_AS_OF)
    assessment = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "kharif", CAP_AS_OF)
    estimate = service.estimate_demand(
        "DST-LUD", "DAP", "2025-26", "kharif", CAP_AS_OF)
    assert assessment["estimate_id"] == estimate["estimate_id"]
    assert assessment["base_tonnes"] == estimate["total_tonnes"] == 14091.569
    assert len(assessment["lines"]) == 1
    line = assessment["lines"][0]
    assert line["reporter"] == "T. Rao (field officer)"
    assert line["review_state"] == "unreviewed"
    assert line["age_days"] == 5
    assert line["decay"] == CAP_DECAY
    assert line["effect_pct"] == 6.0
    assert line["uncapped_pct"] == CAP_UNCAPPED
    assert line["uncapped_pct"] > CAP_PCT  # it WOULD move it further
    assert line["applied_pct"] == CAP_PCT  # exactly the cap
    assert line["capped"] is True
    assert assessment["capped_report_ids"] == ["FSR-DEV-CAP-1"]
    assert assessment["adjustment_pct"] == CAP_PCT
    assert assessment["adjusted_tonnes"] == round(14091.569 * 1.015, 3)
    assert assessment["excluded"] == []
    assert service.verify_field_assessment(assessment["assessment_id"]) == []
    # The estimate itself was never mutated by the consumer.
    assert service.get_estimate(estimate["estimate_id"])["total_tonnes"] == 14091.569


def test_confirmed_carries_full_decayed_weight(service):
    service.sync_field_reports([CAP_SUB], CAP_AS_OF)
    capped = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "kharif", CAP_AS_OF)
    service.review_field_report(
        "FSR-DEV-CAP-1", "confirm", REVIEWER, "corroborated", CAP_AS_OF)
    confirmed = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "kharif", CAP_AS_OF)
    assert confirmed["supersedes"] == capped["assessment_id"]
    line = confirmed["lines"][0]
    assert line["review_state"] == "confirmed"
    assert line["capped"] is False
    assert line["applied_pct"] == CAP_UNCAPPED
    assert confirmed["adjustment_pct"] == round(CAP_UNCAPPED, 4)
    assert confirmed["adjusted_tonnes"] == round(
        14091.569 * (1 + round(CAP_UNCAPPED, 4) / 100), 3)
    assert service.verify_field_assessment(confirmed["assessment_id"]) == []
    # Compute-or-return: the same inputs again store nothing new.
    again = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "kharif", CAP_AS_OF)
    assert again["assessment_id"] == confirmed["assessment_id"]


def test_queried_and_rejected_carry_zero(service):
    subs = [
        {"submission_id": "DEV-Z1", "reporter": "M. Khan (field officer)",
         "district_id": "DST-GUN", "product": "UREA",
         "signal_type": "demand_signal", "direction": "up",
         "observed_on": "2025-08-10"},
        {"submission_id": "DEV-Z2", "reporter": "M. Khan (field officer)",
         "district_id": "DST-GUN", "product": "UREA",
         "signal_type": "stock_observed", "observed_on": "2025-08-12",
         "quantity_tonnes": 40.0},
    ]
    service.sync_field_reports(subs, "2025-08-20")
    service.review_field_report(
        "FSR-DEV-Z1", "query", REVIEWER, "needs_quantity", "2025-08-20")
    service.review_field_report(
        "FSR-DEV-Z2", "reject", REVIEWER, "duplicate", "2025-08-20")
    assessment = service.field_signal_assessment(
        "DST-GUN", "UREA", "2025-26", "kharif", "2025-09-01")
    assert assessment["adjustment_pct"] == 0.0
    assert assessment["adjusted_tonnes"] == assessment["base_tonnes"]
    by_id = {l["report_id"]: l for l in assessment["lines"]}
    assert by_id["FSR-DEV-Z1"]["applied_pct"] == 0.0
    assert by_id["FSR-DEV-Z1"]["zero_reason"] == "queried"
    assert by_id["FSR-DEV-Z1"]["uncapped_pct"] != 0.0  # it had weight to lose
    assert by_id["FSR-DEV-Z2"]["applied_pct"] == 0.0
    assert by_id["FSR-DEV-Z2"]["zero_reason"] == "rejected"
    # Re-confirming the queried report restores its decayed weight.
    service.review_field_report(
        "FSR-DEV-Z1", "confirm", REVIEWER, "reporter_verified", "2025-09-01")
    restored = service.field_signal_assessment(
        "DST-GUN", "UREA", "2025-26", "kharif", "2025-09-01")
    line = next(l for l in restored["lines"] if l["report_id"] == "FSR-DEV-Z1")
    age = (date(2025, 9, 1) - date(2025, 8, 10)).days
    assert line["applied_pct"] == round(6.0 * round(0.5 ** (age / 30), 6), 6)
    assert line["applied_pct"] > 0
    assert service.verify_field_assessment(restored["assessment_id"]) == []


def test_expired_report_named_at_zero(service):
    sub = {"submission_id": "DEV-OLD-1", "reporter": "R. Patil (dealer network lead)",
           "district_id": "DST-LUD", "product": "UREA",
           "signal_type": "demand_signal", "direction": "up",
           "observed_on": "2025-06-05"}
    service.sync_field_reports([sub], "2025-06-06")
    assessment = service.field_signal_assessment(
        "DST-LUD", "UREA", "2025-26", "kharif", "2025-12-20")
    line = assessment["lines"][0]
    assert line["age_days"] == 198
    assert line["expired"] is True
    assert line["decay"] == 0.0
    assert line["applied_pct"] == 0.0
    assert line["zero_reason"] == "expired"
    assert assessment["adjustment_pct"] == 0.0


def test_not_yet_observable_reports_are_named_excluded(service):
    future = {"submission_id": "DEV-FUT-1", "reporter": "T. Rao (field officer)",
              "district_id": "DST-LUD", "product": "DAP",
              "signal_type": "stock_observed", "observed_on": "2025-10-20"}
    service.sync_field_reports([future], "2025-12-01")
    assessment = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "kharif", "2025-11-02")
    assert assessment["lines"] == []
    assert assessment["excluded"] == [{
        "report_id": "FSR-DEV-FUT-1",
        "reporter": "T. Rao (field officer)",
        "reason": "landed_after_as_of",
    }]
    later = dict(future, submission_id="DEV-FUT-2", observed_on="2025-12-15")
    service.sync_field_reports([later], "2025-12-16")
    rabi = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "rabi", "2025-12-10")
    # Observed 2025-12-15 but the assessment is struck 2025-12-10:
    # landed after is false (landed 12-16 > 12-10 too) — either way
    # it is excluded and named, never silently counted.
    assert all(l["report_id"] != "FSR-DEV-FUT-2" for l in rabi["lines"])
    assert any(
        e["report_id"] == "FSR-DEV-FUT-2" for e in rabi["excluded"])


def test_field_tamper_is_detected(service, settings):
    service.sync_field_reports([CAP_SUB], CAP_AS_OF)
    assessment = service.field_signal_assessment(
        "DST-LUD", "DAP", "2025-26", "kharif", CAP_AS_OF)
    raw = raw_connect(settings)
    payload = json.loads(raw.execute(
        "SELECT payload FROM field_signal_assessments WHERE assessment_id = ?",
        (assessment["assessment_id"],),
    ).fetchone()[0])
    payload["adjusted_tonnes"] += 100.0
    raw.execute(
        "UPDATE field_signal_assessments SET payload = ? WHERE assessment_id = ?",
        (json.dumps(payload), assessment["assessment_id"]),
    )
    raw.commit()
    assert service.verify_field_assessment(assessment["assessment_id"]) != []
    payload["adjusted_tonnes"] -= 100.0
    raw.execute(
        "UPDATE field_signal_assessments SET payload = ? WHERE assessment_id = ?",
        (json.dumps(payload), assessment["assessment_id"]),
    )
    raw.commit()
    assert service.verify_field_assessment(assessment["assessment_id"]) == []

    report_payload = json.loads(raw.execute(
        "SELECT payload FROM field_signal_reports WHERE report_id = ?",
        ("FSR-DEV-CAP-1",),
    ).fetchone()[0])
    report_payload["reporter"] = "Someone Else"
    raw.execute(
        "UPDATE field_signal_reports SET payload = ? WHERE report_id = ?",
        (json.dumps(report_payload), "FSR-DEV-CAP-1"),
    )
    raw.commit()
    raw.close()
    assert service.verify_field_report("FSR-DEV-CAP-1") != []


def test_api_parity_round7(service, settings):
    from fastapi.testclient import TestClient

    from fertilizer_intelligence.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        promoted = client.post(
            "/field-signals/promote-planted", json={"as_of": AS_OF}).json()
        assert promoted["landed"] == 12
        queue = client.get("/field-review-queue").json()
        assert len(queue) == 12
        assert all(q["review_state"] == "unreviewed" for q in queue)
        assert client.get(
            "/field-review-queue", params={"state": "confirmed"}).json() == []

        synced = client.post("/field-signals/sync", json={
            "submissions": [CAP_SUB], "as_of": CAP_AS_OF,
        }).json()
        assert synced["receipt"][0]["outcome"] == "landed"
        got = client.get("/field-signals/FSR-DEV-CAP-1").json()
        assert got["reporter"] == "T. Rao (field officer)"
        assert got["review_state"] == "unreviewed"
        verify = client.get("/field-signals/FSR-DEV-CAP-1/verify").json()
        assert verify["ok"] is True
        assert client.get("/field-signals/FSR-nope").status_code == 404

        invalid = client.post("/field-signals/sync", json={
            "submissions": [{"submission_id": "BAD-9", "product": "DAP"}],
            "as_of": AS_OF,
        })
        assert invalid.status_code == 422
        assert "reporter" in invalid.json()["detail"]

        reviewed = client.post("/field-signals/FSR-DEV-CAP-1/review", json={
            "act": "confirm", "actor": REVIEWER, "reason": "corroborated",
            "as_of": CAP_AS_OF,
        }).json()
        assert reviewed["review_state"] == "confirmed"
        repeat = client.post("/field-signals/FSR-DEV-CAP-1/review", json={
            "act": "confirm", "actor": REVIEWER, "reason": "corroborated",
            "as_of": CAP_AS_OF,
        })
        assert repeat.status_code == 409

        assessment = client.post("/field-assessments", json={
            "district_id": "DST-LUD", "product": "DAP",
            "crop_year": "2025-26", "season": "kharif", "as_of": CAP_AS_OF,
        }).json()
        assert assessment["adjustment_pct"] == round(CAP_UNCAPPED, 4)
        fetched = client.get(
            "/field-assessments/DST-LUD/DAP/2025-26/kharif",
            params={"as_of": CAP_AS_OF},
        ).json()
        assert fetched["assessment_id"] == assessment["assessment_id"]
        averify = client.get(
            "/field-assessments/DST-LUD/DAP/2025-26/kharif/verify",
            params={"as_of": CAP_AS_OF},
        ).json()
        assert averify["ok"] is True
        assert client.get(
            "/field-assessments/DST-LUD/DAP/2024-25/kharif").status_code == 404

        client.post("/field-signals/FSR-FR-003/review", json={
            "act": "reject", "actor": REVIEWER, "reason": "duplicate",
            "as_of": AS_OF,
        })
        revive = client.post("/field-signals/FSR-FR-003/review", json={
            "act": "confirm", "actor": REVIEWER, "reason": "corroborated",
            "as_of": AS_OF,
        })
        assert revive.status_code == 409


def test_cli_parity_round7(service, settings, capsys, tmp_path):
    from fertilizer_intelligence import cli

    base = [
        "--db", str(settings.sqlite_path),
        "--migrations", str(settings.migrations_dir),
    ]
    assert cli.main(base + ["field-promote", "--as-of", AS_OF]) == 0
    assert json.loads(capsys.readouterr().out)["landed"] == 12

    outbox = tmp_path / "outbox.json"
    outbox.write_text(json.dumps([CAP_SUB]), encoding="utf-8")
    assert cli.main(base + [
        "field-sync", "--file", str(outbox), "--as-of", CAP_AS_OF,
    ]) == 0
    assert json.loads(capsys.readouterr().out)["landed"] == 1
    assert cli.main(base + [
        "field-sync", "--file", str(outbox), "--as-of", CAP_AS_OF,
    ]) == 0
    assert json.loads(capsys.readouterr().out)["duplicates"] == 1

    assert cli.main(base + ["field-queue"]) == 0
    queue = json.loads(capsys.readouterr().out)
    assert len(queue) == 13
    assert all(q["review_state"] == "unreviewed" for q in queue)

    assert cli.main(base + [
        "field-review", "--report-id", "FSR-DEV-CAP-1", "--act", "confirm",
        "--actor", REVIEWER, "--reason", "corroborated", "--as-of", CAP_AS_OF,
    ]) == 0
    assert json.loads(capsys.readouterr().out)["review_state"] == "confirmed"

    assert cli.main(base + [
        "field-assessment", "--district", "DST-LUD", "--product", "DAP",
        "--crop-year", "2025-26", "--season", "kharif", "--as-of", CAP_AS_OF,
    ]) == 0
    assessment = json.loads(capsys.readouterr().out)
    assert assessment["adjustment_pct"] == round(CAP_UNCAPPED, 4)

    assert cli.main(base + [
        "verify-field-assessment", "--district", "DST-LUD",
        "--product", "DAP", "--crop-year", "2025-26", "--season", "kharif",
        "--as-of", CAP_AS_OF,
    ]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert cli.main(base + [
        "verify-field-report", "--report-id", "FSR-DEV-CAP-1",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert cli.main(base + ["field-report", "--report-id", "FSR-nope"]) == 2
    capsys.readouterr()
