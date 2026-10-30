"""Field-report screening & reporter integrity
(R17, roadmap F21-AS2).

Two governed layers stand around the field book the
R7 intake built:

- **Screening.** When a field report lands, its
  free-text note is screened against the integrity
  pack and the verdict is struck as its own
  insert-only artefact, bound to the report and to a
  hash of the text screened. A held note is treated
  as absent everywhere the note could travel — the
  report views redact it, and the structuring context
  a model would be handed omits it, naming the
  omission — while the report's attribution, figures
  and weight proceed untouched: screening governs the
  prose, never the observation. A named reviewer who
  is not the reporter may release held text with a
  stated reason; the release is an act, the state is
  its fold, and nothing stored is ever edited.

- **Reporter integrity.** Over the landed book, a
  board artefact computes per reporter the signals a
  reviewer needs: landing volume against the pack's
  spike bar, duplicate-content clusters detected
  exactly, conflict involvement, and review outcomes
  folded from the acts. The board is advisory in the
  strong sense: it is struck from the record and
  writes nothing back — no signal moves a report's
  weight, review state or standing, and the
  assessments re-perform identically whether or not
  a board exists. That independence is graded, not
  asserted.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import date, timedelta

from pydantic import BaseModel

from . import integrity_rules as pack

__all__ = [
    "ScreeningError",
    "FieldScreening",
    "FieldScreeningAct",
    "IntegrityBoard",
    "screen_text",
    "build_screening",
    "screening_state",
    "screening_for",
    "build_release_act",
    "structuring_context",
    "duplicate_clusters",
    "build_integrity_board",
    "verify_integrity",
]


class ScreeningError(Exception):
    """A screening act the record refuses — a release
    against text that is not held, a second release,
    or a release attempted by the reporter."""


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _normalise_name(name: str) -> str:
    """Names compared folded: case and whitespace do
    not make a different person."""
    return " ".join(str(name).split()).casefold()


# ---------------------------------------------------------------------------
# The screen: the pack's rules over the note as
# written, and over anything the note encodes.
# ---------------------------------------------------------------------------


def _rule_matches(text: str) -> set[str]:
    return {
        rule_id
        for rule_id, pattern, _what in pack.SCREEN_RULES
        if re.search(pattern, text, flags=re.IGNORECASE)
    }


def _decoded_spans(text: str) -> list[str]:
    """The readable text inside the note's base64
    spans, if any: a span that does not decode to
    readable text is data, not prose, and screens as
    nothing."""
    decoded: list[str] = []
    for span in re.findall(pack.BASE64_SPAN, text):
        candidate = span.replace("-", "+").replace("_", "/")
        candidate += "=" * (-len(candidate) % 4)
        try:
            raw = base64.b64decode(candidate, validate=True)
            prose = raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if prose.strip():
            decoded.append(prose)
    return decoded


def screen_text(text: str | None) -> list[dict]:
    """Screen one note. Returns the matched rules as
    {rule, view} pairs in pack order — the raw view
    first, then the decoded view. An empty list is a
    clean note; screening reads, it never rewrites."""
    if not text:
        return []
    matched: list[dict] = []
    raw_hits = _rule_matches(text)
    for rule_id, _pattern, _what in pack.SCREEN_RULES:
        if rule_id in raw_hits and not any(
                m["rule"] == rule_id and m["view"] == pack.VIEW_RAW
                for m in matched):
            matched.append({"rule": rule_id, "view": pack.VIEW_RAW})
    decoded_hits: set[str] = set()
    for prose in _decoded_spans(text):
        decoded_hits |= _rule_matches(prose)
    for rule_id, _pattern, _what in pack.SCREEN_RULES:
        if rule_id in decoded_hits and not any(
                m["rule"] == rule_id and m["view"] == pack.VIEW_BASE64
                for m in matched):
            matched.append(
                {"rule": rule_id, "view": pack.VIEW_BASE64})
    return matched


def screen_report(report: dict) -> list[dict]:
    """Screen every prose field the pack names on one
    landed report, each match carrying its field."""
    matched: list[dict] = []
    for field in pack.SCREENED_FIELDS:
        for hit in screen_text(report.get(field)):
            matched.append({"field": field, **hit})
    return matched


# ---------------------------------------------------------------------------
# Screening artefacts & the release fold.
# ---------------------------------------------------------------------------


class FieldScreening(BaseModel):
    screening_id: str
    fingerprint: str
    report_id: str
    reporter: str
    district_id: str
    product: str
    verdict: str
    matched_rules: list[dict]
    text_sha256: str
    at: str
    rules_version: str


class FieldScreeningAct(BaseModel):
    act_id: str
    fingerprint: str
    screening_id: str
    report_id: str
    act: str
    actor: str
    reason: str
    as_of: str
    rules_version: str


def _text_sha256(report: dict) -> str:
    text = report.get("detail") or ""
    return hashlib.sha256(text.encode()).hexdigest()


def build_screening(report: dict) -> FieldScreening:
    """Strike (do not store) the screening verdict of
    one landed report: the pack's rules over its note,
    bound to the report's identity and to the hash of
    the exact text screened — a later edit of the note
    under the screening's back fails re-performance,
    because the hash will not match."""
    matched = screen_report(report)
    fingerprint = _fingerprint({
        "report_id": report["report_id"],
        "payload_hash": report["payload_hash"],
        "verdict": pack.VERDICT_HELD if matched
                   else pack.VERDICT_CLEAN,
        "matched_rules": matched,
        "text_sha256": _text_sha256(report),
        "at": report["as_of"],
        "pack": pack.RULES_VERSION,
    })
    return FieldScreening(
        screening_id=f"SCR-{fingerprint[:10]}",
        fingerprint=fingerprint,
        report_id=report["report_id"],
        reporter=report["reporter"],
        district_id=report["district_id"],
        product=report["product"],
        verdict=pack.VERDICT_HELD if matched
                else pack.VERDICT_CLEAN,
        matched_rules=matched,
        text_sha256=_text_sha256(report),
        at=report["as_of"],
        rules_version=pack.RULES_VERSION)


def screening_state(store, screening: dict) -> str:
    """The fold: a clean landing is clean; a held
    landing stands held until a release act exists
    against its screening, and released from then."""
    if screening["verdict"] == pack.VERDICT_CLEAN:
        return pack.STATE_CLEAN
    acts = store.list_field_screening_acts(
        screening["screening_id"])
    if any(act["act"] == pack.ACT_RELEASE for act in acts):
        return pack.STATE_RELEASED
    return pack.STATE_HELD


def screening_for(store, report: dict) -> dict | None:
    """One report's screening, with its folded state —
    the summary every field surface carries."""
    screening = store.get_field_screening_by_report(
        report["report_id"])
    if screening is None:
        return None
    return {
        "screening_id": screening["screening_id"],
        "verdict": screening["verdict"],
        "state": screening_state(store, screening),
        "matched_rules": screening["matched_rules"],
        "rules_version": screening["rules_version"],
    }


def build_release_act(screening: dict, actor: str,
                      reason: str, as_of: str) -> FieldScreeningAct:
    """Strike (do not store) one release act against a
    held screening. The vocabulary is the pack's; the
    state refusals (not held, already released, the
    reporter releasing their own text) are the
    service's to judge before this is built."""
    fingerprint = _fingerprint({
        "screening_id": screening["screening_id"],
        "report_id": screening["report_id"],
        "act": pack.ACT_RELEASE, "actor": actor,
        "reason": reason, "as_of": as_of,
        "pack": pack.RULES_VERSION,
    })
    return FieldScreeningAct(
        act_id=f"SCA-{fingerprint[:10]}",
        fingerprint=fingerprint,
        screening_id=screening["screening_id"],
        report_id=screening["report_id"],
        act=pack.ACT_RELEASE, actor=actor, reason=reason,
        as_of=as_of, rules_version=pack.RULES_VERSION)


# ---------------------------------------------------------------------------
# The structuring context: what a model would be
# handed for one report — and what it is never handed.
# ---------------------------------------------------------------------------


def structuring_context(store, report: dict) -> dict:
    """The payload a model port would receive to
    structure or summarise one field report. Built
    only from the report's screened surface: while
    the note stands held, the context carries the
    report's structured fields and a named omission
    where the note would go — the held text itself
    is not in the context, in any encoding this
    builder produces. A clean or released note rides
    byte-identically: screening never edits prose."""
    summary = screening_for(store, report)
    held = summary is not None \
        and summary["state"] == pack.STATE_HELD
    return {
        "report_id": report["report_id"],
        "submission_id": report["submission_id"],
        "reporter": report["reporter"],
        "district_id": report["district_id"],
        "product": report["product"],
        "signal_type": report["signal_type"],
        "signal_kind": report["signal_kind"],
        "observed_on": report["observed_on"],
        "quantity_tonnes": report["quantity_tonnes"],
        "price_inr_tonne": report["price_inr_tonne"],
        "direction": report["direction"],
        "detail": None if held else report["detail"],
        "detail_withheld": (
            {"screening_id": summary["screening_id"],
             "state": pack.STATE_HELD,
             "reason": "the note is held by screening "
                       "and never enters a model context"}
            if held else None),
        "screening": summary,
        "source": report["source"],
        "as_of": report["as_of"],
    }


# ---------------------------------------------------------------------------
# Reporter integrity: clusters, spikes, outcomes —
# computed from the record, advisory only.
# ---------------------------------------------------------------------------


def _observation_key(report: dict) -> tuple:
    """What makes two landings the same observation:
    the reporter, the cell, the kind, the observation
    date and the observed values, prose included.
    The submission envelope (its id, its channel) is
    not the observation."""
    return (
        report["reporter"], report["district_id"],
        report["product"], report["signal_kind"],
        report["observed_on"], report["quantity_tonnes"],
        report["price_inr_tonne"], report["detail"],
    )


def duplicate_clusters(reports: list[dict]) -> list[dict]:
    """Group one reporter's landed reports by
    observation content; a group carried by two or
    more *distinct submission ids* is a cluster. A
    re-send of one submission is the sync layer's
    duplicate and never appears here — it is one
    landing, not two. The cluster names its members
    and carries the note's hash, never the note: a
    held note stays held on this surface too."""
    by_key: dict[tuple, list[dict]] = {}
    for report in reports:
        by_key.setdefault(_observation_key(report), []).append(report)
    clusters: list[dict] = []
    for key, members in by_key.items():
        submission_ids = sorted({m["submission_id"] for m in members})
        if len(submission_ids) < pack.CLUSTER_MIN_SIZE:
            continue
        reporter, district_id, product, kind, observed_on, \
            quantity, price, detail = key
        clusters.append({
            "reporter": reporter,
            "district_id": district_id,
            "product": product,
            "signal_kind": kind,
            "observed_on": observed_on,
            "quantity_tonnes": quantity,
            "price_inr_tonne": price,
            "detail_sha256": hashlib.sha256(
                (detail or "").encode()).hexdigest(),
            "report_ids": sorted(m["report_id"] for m in members),
            "submission_ids": submission_ids,
            "size": len(submission_ids),
        })
    return sorted(clusters, key=lambda c: (
        c["reporter"], c["report_ids"][0]))


class IntegrityBoard(BaseModel):
    board_id: str
    fingerprint: str
    as_of: str
    rows: list[dict]
    totals: dict
    rules_version: str
    supersedes: str | None = None


def build_integrity_board(store, as_of: str) -> IntegrityBoard:
    """Strike (do not store) the reporter-integrity
    board at a date: one row per reporter with a
    report landed by then — landing volume and its
    trailing-window count against the pack's spike
    bar, duplicate clusters, conflict involvement,
    and review outcomes folded from the acts at the
    board date. Every figure derives from the stored
    reports and acts alone, and the board writes
    nothing back."""
    from .field import derive_review_state  # the one fold

    landed = [r for r in store.list_field_report_artefacts()
              if r["as_of"] <= as_of]
    window_start = (date.fromisoformat(as_of)
                    - timedelta(days=pack.SPIKE_WINDOW_DAYS - 1)
                    ).isoformat()
    conflicted_ids: set[str] = set()
    for report in landed:
        if report["conflicts_with"]:
            conflicted_ids.add(report["report_id"])
            conflicted_ids.add(report["conflicts_with"])
    clusters = duplicate_clusters(landed)
    clusters_by_reporter: dict[str, list[dict]] = {}
    for cluster in clusters:
        clusters_by_reporter.setdefault(
            cluster["reporter"], []).append(cluster)
    rows: list[dict] = []
    act_ids: list[str] = []
    for reporter in sorted({r["reporter"] for r in landed}):
        mine = [r for r in landed if r["reporter"] == reporter]
        outcomes = {"unreviewed": 0, "confirmed": 0,
                    "queried": 0, "rejected": 0}
        for report in mine:
            acts = [a for a in store.list_field_review_acts(
                        report["report_id"])
                    if a["as_of"] <= as_of]
            act_ids.extend(a["act_id"] for a in acts)
            outcomes[derive_review_state(acts)] += 1
        window_count = sum(
            1 for r in mine
            if window_start <= r["as_of"] <= as_of)
        signals: list[str] = []
        if window_count >= pack.SPIKE_MIN_REPORTS:
            signals.append(pack.SIGNAL_VOLUME_SPIKE)
        if clusters_by_reporter.get(reporter):
            signals.append(pack.SIGNAL_DUPLICATE_CLUSTER)
        rows.append({
            "reporter": reporter,
            "reports_landed": len(mine),
            "window": {"days": pack.SPIKE_WINDOW_DAYS,
                       "landed": window_count},
            "signals": signals,
            "duplicate_clusters": clusters_by_reporter.get(
                reporter, []),
            "conflicts": sum(
                1 for r in mine
                if r["report_id"] in conflicted_ids),
            "review_outcomes": outcomes,
        })
    totals = {
        "reporters": len(rows),
        "reports": len(landed),
        "clusters": len(clusters),
        "spiking_reporters": sum(
            1 for row in rows
            if pack.SIGNAL_VOLUME_SPIKE in row["signals"]),
    }
    fingerprint = _fingerprint({
        "as_of": as_of, "rows": rows, "totals": totals,
        "inputs": {
            "reports": sorted(
                [r["report_id"], r["payload_hash"]]
                for r in landed),
            "review_acts": sorted(act_ids),
        },
        "pack": pack.RULES_VERSION,
    })
    return IntegrityBoard(
        board_id=f"RIB-{fingerprint[:10]}",
        fingerprint=fingerprint, as_of=as_of, rows=rows,
        totals=totals, rules_version=pack.RULES_VERSION)


# ---------------------------------------------------------------------------
# Verification: a second route over the raw store.
# ---------------------------------------------------------------------------


def _expected_clusters(reports: list[dict]) -> list[dict]:
    """The cluster set re-derived by the opposite
    walk: submission ids outer, payload identity
    compared pairwise — two landings cluster when
    they share a reporter and every observation field
    and arrived under different submission ids."""
    expected: list[dict] = []
    seen: set[tuple] = set()
    for report in reports:
        twins = [
            other for other in reports
            if other["submission_id"] != report["submission_id"]
            and other["reporter"] == report["reporter"]
            and all(other[field] == report[field] for field in (
                "district_id", "product", "signal_kind",
                "observed_on", "quantity_tonnes",
                "price_inr_tonne", "detail"))
        ]
        if not twins:
            continue
        members = sorted(
            {report["report_id"]} | {t["report_id"] for t in twins})
        marker = tuple(members)
        if marker in seen:
            continue
        seen.add(marker)
        expected.append({
            "reporter": report["reporter"],
            "report_ids": members,
            "size": len({report["submission_id"]}
                        | {t["submission_id"] for t in twins}),
        })
    return sorted(expected, key=lambda c: (
        c["reporter"], c["report_ids"][0]))


def verify_integrity(store, as_of: str) -> list[str]:
    """Re-perform the whole integrity layer: every
    landed report carries exactly one screening and
    the screening rebuilds from the report as stored
    (a note edited under its screening, or a verdict
    that no longer matches the pack over the text,
    is named); every release act folds lawfully — a
    held screening, a stated reason, a releaser who
    is not the reporter, at most one; the structuring
    context of every held report carries no held
    text; and every integrity board re-performs,
    its clusters re-derived by the opposite walk and
    its supersedes chain in strike order."""
    problems: list[str] = []
    reports = store.list_field_report_artefacts()
    by_id = {r["report_id"]: r for r in reports}
    screenings = store.list_field_screenings()
    screened_ids = [s["report_id"] for s in screenings]
    for report in reports:
        if screened_ids.count(report["report_id"]) != 1:
            problems.append(
                f"field report {report['report_id']}: "
                f"{screened_ids.count(report['report_id'])} "
                "screening records name it, not one")
    for screening in screenings:
        report = by_id.get(screening["report_id"])
        if report is None:
            problems.append(
                f"screening {screening['screening_id']}: "
                f"names field report {screening['report_id']}, "
                "which is not in the store")
            continue
        rebuilt = build_screening(report)
        if any(rebuilt.model_dump()[field] != screening[field]
               for field in ("screening_id", "fingerprint",
                             "verdict", "matched_rules",
                             "text_sha256", "reporter",
                             "district_id", "product", "at",
                             "rules_version")):
            problems.append(
                f"screening {screening['screening_id']}: "
                "does not re-perform from its report — the "
                "note, the verdict or the matched rules "
                "disagree with the pack over the stored text")
        acts = store.list_field_screening_acts(
            screening["screening_id"])
        releases = [a for a in acts
                    if a["act"] == pack.ACT_RELEASE]
        for act in acts:
            rebuilt_act = build_release_act(
                screening, act["actor"], act["reason"],
                act["as_of"])
            if rebuilt_act.act_id != act["act_id"] \
                    or rebuilt_act.fingerprint != act["fingerprint"]:
                problems.append(
                    f"screening act {act['act_id']}: its "
                    "fingerprint does not match its fields")
            if act["reason"] not in \
                    pack.ACT_REASONS[pack.ACT_RELEASE]:
                problems.append(
                    f"screening act {act['act_id']}: reason "
                    f"{act['reason']!r} is outside the "
                    "release vocabulary")
            if _normalise_name(act["actor"]) == \
                    _normalise_name(report["reporter"]):
                problems.append(
                    f"screening act {act['act_id']}: the "
                    "reporter released their own held text")
        if len(releases) > 1:
            problems.append(
                f"screening {screening['screening_id']}: "
                f"{len(releases)} release acts fold it, "
                "not at most one")
        if releases and screening["verdict"] != pack.VERDICT_HELD:
            problems.append(
                f"screening {screening['screening_id']}: "
                "a release act stands against a screening "
                "that never held the text")
        if screening_state(store, screening) == pack.STATE_HELD:
            context = structuring_context(store, report)
            note = report["detail"]
            if note and context["detail"] is not None:
                problems.append(
                    f"field report {report['report_id']}: "
                    "held text stands in its structuring "
                    "context")
    boards = store.list_integrity_boards()
    ordered = sorted(boards, key=lambda b: (b["as_of"], b["board_id"]))
    for idx, board in enumerate(ordered):
        want = ordered[idx - 1]["board_id"] if idx else None
        if board["supersedes"] != want:
            problems.append(
                f"integrity board {board['board_id']}: "
                f"supersedes {board['supersedes']}, but the "
                f"strike order says {want}")
        rebuilt = build_integrity_board(store, board["as_of"])
        for field in ("board_id", "fingerprint", "rows", "totals"):
            if rebuilt.model_dump()[field] != board[field]:
                problems.append(
                    f"integrity board {board['board_id']}: "
                    f"its {field} does not re-perform from "
                    "the record at its date")
        landed = [r for r in reports if r["as_of"] <= board["as_of"]]
        expected = _expected_clusters(landed)
        actual = [
            {"reporter": c["reporter"],
             "report_ids": c["report_ids"], "size": c["size"]}
            for row in board["rows"]
            for c in row["duplicate_clusters"]
        ]
        actual.sort(key=lambda c: (c["reporter"], c["report_ids"][0]))
        if actual != expected:
            problems.append(
                f"integrity board {board['board_id']}: its "
                "duplicate clusters disagree with the "
                "pairwise re-derivation")
    return problems
