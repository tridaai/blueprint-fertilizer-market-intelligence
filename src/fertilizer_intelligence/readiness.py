"""The season readiness plan (R14, roadmap F21-PO3).

One artefact per region and season: a pre-season
checklist whose four lines are scored from the record —
the published state of the head outlook, the supply
cover position, the open risks, the field coverage —
never self-declared. The plan reads ready only when
every line is complete, and it names on its face exactly
which lines block it and why:

- an outlook counts only behind its publication act
  (R10): the family's head act at the plan's date must
  name the head outlook;
- a product reading short, or with no gap struck,
  leaves the cover line incomplete, named with its gap
  figures;
- an alert still standing open, or a short gap whose
  queue item nobody has taken — no assign act in its
  fold, no close retiring it — is an open risk, named;
- a district with no confirmed field report for the
  season is uncovered, named.

Acts fold at the plan's as-of date (the map's signal
layer discipline), so a plan keeps reading as it read at
its date. The plan is insert-only and content-addressed:
re-struck over a moved record it supersedes by link,
and :func:`verify_readiness` re-derives every line by a
second route — acts grouped first, then read — so a
line that drifted from the record is named.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from . import board as board_engine
from . import brief as brief_engine
from . import brief_rules as brief_pack
from . import field as field_engine
from . import field_rules as field_pack
from . import movements as movement_engine
from . import queue as queue_engine
from . import readiness_rules as pack
from . import supply as supply_engine
from .demand import head_of


class ReadinessRefused(RuntimeError):
    """A readiness candidate failed re-performance and
    was refused wholesale — nothing of it is stored but
    the refusal artefact that names the problems."""

    def __init__(self, problems: list[str], refusal_id: str | None = None):
        self.problems = problems
        self.refusal_id = refusal_id
        super().__init__("readiness refused: " + "; ".join(problems))


class SeasonReadiness(BaseModel):
    readiness_id: str
    fingerprint: str
    region: str
    crop_year: str
    season: str
    as_of: str
    struck_by: str
    rules_version: str
    district_ids: list[str]
    lines: list[dict]
    ready: bool
    blocking_lines: list[str]
    supersedes: str | None = None


class ReadinessRefusal(BaseModel):
    refusal_id: str
    fingerprint: str
    region: str
    crop_year: str
    season: str
    as_of: str
    struck_by: str
    rules_version: str
    problems: list[str]


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def region_districts(store, region: str) -> list[dict]:
    """The region's districts, in district order — the
    plan's population, from the register."""
    return sorted(
        (d for d in store.list_districts() if d["region"] == region),
        key=lambda d: d["district_id"])


# ---------------------------------------------------------------------------
# Line derivation (the builder's route)
# ---------------------------------------------------------------------------


def _line(key: str, complete: bool, detail: str,
          blockers: list[str], figures: dict) -> dict:
    return {
        "line": key, "title": pack.LINE_TITLES[key],
        "basis": pack.LINE_BASIS[key],
        "status": (pack.STATUS_COMPLETE if complete
                   else pack.STATUS_INCOMPLETE),
        "detail": detail, "blockers": blockers, "figures": figures,
    }


def _outlook_line(store, crop_year: str, season: str,
                  as_of: str) -> dict:
    outlook = head_of(store.list_outlooks(crop_year, season), "outlook_id")
    if outlook is None:
        return _line(
            pack.LINE_OUTLOOK, False,
            f"no season outlook has been struck for {season} "
            f"{crop_year}",
            [f"no season outlook artefact for {season} {crop_year}"],
            {"outlook_id": None})
    acts = sorted(
        (a for a in store.list_publication_acts()
         if a["published_at"] <= as_of),
        key=lambda a: (a["published_at"], a["act_id"]))
    state = brief_engine.publication_state(
        acts, brief_pack.KIND_OUTLOOK, outlook["outlook_id"])
    figures = {"outlook_id": outlook["outlook_id"],
               "outlook_status": outlook["status"],
               "publication": state}
    if state["status"] == "draft":
        return _line(
            pack.LINE_OUTLOOK, False,
            f"the head outlook {outlook['outlook_id']} is a "
            "draft at the plan's date",
            [f"the head outlook {outlook['outlook_id']} has no "
             f"publication act at {as_of} — an outlook counts "
             "only behind its act"],
            figures)
    if not state["is_current"]:
        return _line(
            pack.LINE_OUTLOOK, False,
            f"the published outlook at the plan's date is "
            f"{state.get('current_artefact_id')}, not the head "
            f"outlook {outlook['outlook_id']}",
            [f"the publication head at {as_of} names "
             f"{state.get('current_artefact_id')} — the head "
             f"outlook {outlook['outlook_id']} is not the "
             "published one"],
            figures)
    return _line(
        pack.LINE_OUTLOOK, True,
        f"the head outlook {outlook['outlook_id']} stands "
        f"published behind act {state['act_id']} "
        f"({state['published_by']}, {state['published_at']})",
        [], figures)


def _cover_line(store, crop_year: str, season: str) -> dict:
    positionable = sorted(supply_engine.positionable_products(store))
    rows, blockers = [], []
    for product in positionable:
        gap = head_of(store.list_gaps(product, crop_year, season),
                      "gap_id")
        if gap is None:
            blockers.append(
                f"no head supply gap has been struck for "
                f"{product} {season} {crop_year}")
            rows.append({"product": product, "gap_id": None,
                         "band": None, "gap_tonnes": None,
                         "programme_cover_pct": None})
            continue
        rows.append({
            "product": product, "gap_id": gap["gap_id"],
            "band": gap["band"], "gap_tonnes": gap["gap_tonnes"],
            "programme_cover_pct": gap["programme_cover_pct"],
        })
        if gap["band"] == "short":
            blockers.append(
                f"{product}'s head gap {gap['gap_id']} reads "
                f"short — {gap['gap_tonnes']} t "
                f"({gap['gap_pct_of_demand']}% of demand)")
    detail = (
        "cover struck for " + ", ".join(positionable)
        + "; products with no supply side carry no cover line")
    if blockers:
        detail += "; the line is incomplete as named"
    return _line(pack.LINE_COVER, not blockers, detail, blockers,
                 {"products": rows})


def _unowned_short_gaps(store, crop_year: str, season: str,
                        as_of: str) -> list[dict]:
    """The season's short gaps nobody has taken: the
    queue item's fold at the date holds no assign act
    (its owner is still the struck default) and no close
    has retired it."""
    out = []
    for gap in queue_engine.member_gaps(store):
        if gap["crop_year"] != crop_year or gap["season"] != season \
                or gap["band"] != "short":
            continue
        item = store.queue_item_for_gap(gap["gap_id"])
        if item is None:
            out.append({
                "gap_id": gap["gap_id"], "product": gap["product"],
                "item_id": None, "owner": None, "state": "unstruck",
            })
            continue
        acts = [a for a in store.list_queue_acts(item["item_id"])
                if a["as_of"] <= as_of]
        state = queue_engine.derive_state(acts)
        owned = any(a["act"] == "assign" for a in acts)
        if state != "closed" and not owned:
            out.append({
                "gap_id": gap["gap_id"], "product": gap["product"],
                "item_id": item["item_id"],
                "owner": item["default_owner"], "state": state,
            })
    return out


def _risks_line(store, crop_year: str, season: str,
                as_of: str) -> dict:
    open_alerts = board_engine.derive_open_alerts(store, as_of)
    unowned = _unowned_short_gaps(store, crop_year, season, as_of)
    blockers = [
        f"alert {row['alert_id']} ({row['series_kind']}/"
        f"{row['item']}, {row['rule_id']}, band {row['band']}) "
        "stands open"
        for row in open_alerts
    ]
    blockers += [
        f"the short {row['product']} gap's queue item "
        f"{row['item_id']} has no assign act at {as_of} — its "
        f"owner is still the struck default {row['owner']}"
        if row["item_id"] else
        f"the short {row['product']} gap {row['gap_id']} has "
        "no queue item struck"
        for row in unowned
    ]
    figures = {
        "open_alerts": [
            {"alert_id": row["alert_id"],
             "series_kind": row["series_kind"], "item": row["item"],
             "rule_id": row["rule_id"], "band": row["band"],
             "period_month": row["period_month"]}
            for row in open_alerts
        ],
        "unowned_short_gaps": unowned,
    }
    detail = (
        f"{len(open_alerts)} alert(s) standing open, "
        f"{len(unowned)} unowned short gap(s) at the plan's date")
    return _line(pack.LINE_RISKS, not blockers, detail, blockers,
                 figures)


def _review_state_at(store, report_id: str, as_of: str) -> str:
    acts = [a for a in store.list_field_review_acts(report_id)
            if a["as_of"] <= as_of]
    return field_engine.derive_review_state(acts)


def _field_line(store, region: str, crop_year: str, season: str,
                as_of: str) -> dict:
    rows, blockers = [], []
    for district in region_districts(store, region):
        confirmed = []
        for report in store.list_field_report_artefacts(
                district_id=district["district_id"]):
            if report.get("crop_year") != crop_year \
                    or report.get("season") != season \
                    or report["as_of"] > as_of:
                continue
            if _review_state_at(store, report["report_id"],
                                as_of) == field_pack.STATE_CONFIRMED:
                confirmed.append(report["report_id"])
        rows.append({
            "district_id": district["district_id"],
            "district_name": district["name"],
            "confirmed_reports": len(confirmed),
            "report_ids": sorted(confirmed),
            "covered": bool(confirmed),
        })
        if not confirmed:
            blockers.append(
                f"no confirmed field report for "
                f"{district['name']} ({district['district_id']}) "
                f"in {season} {crop_year} at {as_of}")
    covered = sum(1 for r in rows if r["covered"])
    return _line(
        pack.LINE_FIELD, not blockers,
        f"{covered} of {len(rows)} districts in {region} "
        "carry a confirmed field report for the season",
        blockers, {"districts": rows})


def derive_lines(store, region: str, crop_year: str, season: str,
                 as_of: str) -> list[dict]:
    """The plan's four lines, in the pack's stated order,
    derived from the record."""
    return [
        _outlook_line(store, crop_year, season, as_of),
        _cover_line(store, crop_year, season),
        _risks_line(store, crop_year, season, as_of),
        _field_line(store, region, crop_year, season, as_of),
    ]


def build_readiness(store, region: str, crop_year: str, season: str,
                    as_of: str, struck_by: str) -> SeasonReadiness:
    """Build (do not store) the candidate readiness plan
    for one region and season."""
    districts = region_districts(store, region)
    if not districts:
        raise ValueError(
            f"no tracked district sits in region {region!r} — "
            f"the tracked regions are "
            f"{sorted({d['region'] for d in store.list_districts()})}")
    lines = derive_lines(store, region, crop_year, season, as_of)
    blocking = [line["line"] for line in lines
                if line["status"] == pack.STATUS_INCOMPLETE]
    fingerprint = _fingerprint({
        "scope": [region, crop_year, season], "as_of": as_of,
        "lines": lines, "pack": pack.RULES_VERSION,
    })
    return SeasonReadiness(
        readiness_id=(
            f"RDY-{region}-{crop_year}-{season}-{fingerprint[:10]}"),
        fingerprint=fingerprint,
        region=region, crop_year=crop_year, season=season,
        as_of=as_of, struck_by=struck_by,
        rules_version=pack.RULES_VERSION,
        district_ids=[d["district_id"] for d in districts],
        lines=lines, ready=not blocking, blocking_lines=blocking,
    )


def build_refusal(region: str, crop_year: str, season: str,
                  as_of: str, struck_by: str,
                  problems: list[str]) -> ReadinessRefusal:
    fingerprint = _fingerprint({
        "scope": [region, crop_year, season], "as_of": as_of,
        "struck_by": struck_by, "problems": problems,
        "pack": pack.RULES_VERSION,
    })
    return ReadinessRefusal(
        refusal_id=f"RDX-{fingerprint[:10]}", fingerprint=fingerprint,
        region=region, crop_year=crop_year, season=season,
        as_of=as_of, struck_by=struck_by,
        rules_version=pack.RULES_VERSION, problems=problems,
    )


# ---------------------------------------------------------------------------
# Re-performance: the verifier's second route
# ---------------------------------------------------------------------------


def _expected_lines(store, plan: dict) -> list[dict]:
    """Re-derive the plan's lines from grouped raw rows:
    acts grouped by their target first, then each line
    read off the groups — never through the builder's
    per-target lookups."""
    region, crop_year = plan["region"], plan["crop_year"]
    season, as_of = plan["season"], plan["as_of"]
    districts = region_districts(store, region)

    # outlook line: the family's acts at the date, folded
    # by hand over the grouped acts.
    outlook = head_of(store.list_outlooks(crop_year, season),
                      "outlook_id")
    family = f"season_outlook:{crop_year}:{season}"
    acts = sorted(
        (a for a in store.list_publication_acts()
         if a["family_key"] == family and a["published_at"] <= as_of),
        key=lambda a: (a["published_at"], a["act_id"]))
    publication: dict = {"status": "draft"}
    if outlook is not None:
        mine = [a for a in acts
                if a["artefact_kind"] == brief_pack.KIND_OUTLOOK
                and a["artefact_id"] == outlook["outlook_id"]]
        if mine:
            head = head_of(acts, "act_id")
            publication = {
                "status": "published", "act_id": mine[-1]["act_id"],
                "published_by": mine[-1]["published_by"],
                "published_at": mine[-1]["published_at"],
                "is_current": bool(
                    head and head["act_id"] == mine[-1]["act_id"]),
            }
            if not publication["is_current"] and head is not None:
                publication["superseded_by_act"] = head["act_id"]
                publication["current_artefact_id"] = \
                    head["artefact_id"]
    lines = []
    if outlook is None:
        lines.append(_line(
            pack.LINE_OUTLOOK, False,
            f"no season outlook has been struck for {season} "
            f"{crop_year}",
            [f"no season outlook artefact for {season} {crop_year}"],
            {"outlook_id": None}))
    else:
        figures = {"outlook_id": outlook["outlook_id"],
                   "outlook_status": outlook["status"],
                   "publication": publication}
        if publication["status"] == "draft":
            lines.append(_line(
                pack.LINE_OUTLOOK, False,
                f"the head outlook {outlook['outlook_id']} is a "
                "draft at the plan's date",
                [f"the head outlook {outlook['outlook_id']} has "
                 f"no publication act at {as_of} — an outlook "
                 "counts only behind its act"], figures))
        elif not publication["is_current"]:
            lines.append(_line(
                pack.LINE_OUTLOOK, False,
                f"the published outlook at the plan's date is "
                f"{publication.get('current_artefact_id')}, not "
                f"the head outlook {outlook['outlook_id']}",
                [f"the publication head at {as_of} names "
                 f"{publication.get('current_artefact_id')} — "
                 f"the head outlook {outlook['outlook_id']} is "
                 "not the published one"], figures))
        else:
            lines.append(_line(
                pack.LINE_OUTLOOK, True,
                f"the head outlook {outlook['outlook_id']} "
                f"stands published behind act "
                f"{publication['act_id']} "
                f"({publication['published_by']}, "
                f"{publication['published_at']})", [], figures))

    # cover line: gap heads grouped by product.
    gap_heads: dict[str, dict] = {}
    for gap in store.list_gaps(crop_year=crop_year, season=season):
        gap_heads.setdefault(gap["product"], []).append(gap)
    positionable = sorted(supply_engine.positionable_products(store))
    rows, blockers = [], []
    for product in positionable:
        gap = head_of(gap_heads.get(product, []), "gap_id")
        if gap is None:
            blockers.append(
                f"no head supply gap has been struck for "
                f"{product} {season} {crop_year}")
            rows.append({"product": product, "gap_id": None,
                         "band": None, "gap_tonnes": None,
                         "programme_cover_pct": None})
            continue
        rows.append({
            "product": product, "gap_id": gap["gap_id"],
            "band": gap["band"], "gap_tonnes": gap["gap_tonnes"],
            "programme_cover_pct": gap["programme_cover_pct"],
        })
        if gap["band"] == "short":
            blockers.append(
                f"{product}'s head gap {gap['gap_id']} reads "
                f"short — {gap['gap_tonnes']} t "
                f"({gap['gap_pct_of_demand']}% of demand)")
    detail = (
        "cover struck for " + ", ".join(positionable)
        + "; products with no supply side carry no cover line")
    if blockers:
        detail += "; the line is incomplete as named"
    lines.append(_line(pack.LINE_COVER, not blockers, detail,
                       blockers, {"products": rows}))

    # risks line: alert folds and queue folds, grouped.
    # The open set is folded here from the acts; the rows
    # are then stated in the board pack's own order, the
    # order the builder's route reads them in.
    open_rows = []
    for alert in store.list_alerts():
        acts_at = [a for a in store.list_alert_acts(alert["alert_id"])
                   if a["as_of"] <= as_of]
        if movement_engine.derive_state(acts_at) == "open":
            open_rows.append(board_engine._alert_row(alert))
    open_rows.sort(key=board_engine.alert_sort_key)
    open_alerts = [
        {"alert_id": row["alert_id"],
         "series_kind": row["series_kind"], "item": row["item"],
         "rule_id": row["rule_id"], "band": row["band"],
         "period_month": row["period_month"]}
        for row in open_rows
    ]
    unowned = []
    items_by_gap = {item["gap_id"]: item
                    for item in store.list_queue_items()}
    for gap in queue_engine.member_gaps(store):
        if gap["crop_year"] != crop_year or gap["season"] != season \
                or gap["band"] != "short":
            continue
        item = items_by_gap.get(gap["gap_id"])
        if item is None:
            unowned.append({
                "gap_id": gap["gap_id"], "product": gap["product"],
                "item_id": None, "owner": None, "state": "unstruck"})
            continue
        acts_at = [a for a in store.list_queue_acts(item["item_id"])
                   if a["as_of"] <= as_of]
        state = "open"
        owned = False
        for act in acts_at:
            if act["act"] == "start":
                state = "in_progress"
            elif act["act"] == "close":
                state = "closed"
            elif act["act"] == "assign":
                owned = True
        if state != "closed" and not owned:
            unowned.append({
                "gap_id": gap["gap_id"], "product": gap["product"],
                "item_id": item["item_id"],
                "owner": item["default_owner"], "state": state})
    risk_blockers = [
        f"alert {row['alert_id']} ({row['series_kind']}/"
        f"{row['item']}, {row['rule_id']}, band {row['band']}) "
        "stands open"
        for row in open_alerts
    ]
    risk_blockers += [
        f"the short {row['product']} gap's queue item "
        f"{row['item_id']} has no assign act at {as_of} — its "
        f"owner is still the struck default {row['owner']}"
        if row["item_id"] else
        f"the short {row['product']} gap {row['gap_id']} has "
        "no queue item struck"
        for row in unowned
    ]
    lines.append(_line(
        pack.LINE_RISKS, not risk_blockers,
        f"{len(open_alerts)} alert(s) standing open, "
        f"{len(unowned)} unowned short gap(s) at the plan's date",
        risk_blockers,
        {"open_alerts": open_alerts, "unowned_short_gaps": unowned}))

    # field line: reports grouped by district, review
    # states folded from grouped acts.
    acts_by_report: dict[str, list[dict]] = {}
    for report in store.list_field_report_artefacts():
        acts_by_report[report["report_id"]] = \
            store.list_field_review_acts(report["report_id"])
    rows, blockers = [], []
    for district in districts:
        confirmed = []
        for report in store.list_field_report_artefacts(
                district_id=district["district_id"]):
            if report.get("crop_year") != crop_year \
                    or report.get("season") != season \
                    or report["as_of"] > as_of:
                continue
            acts_at = [a for a in acts_by_report[report["report_id"]]
                       if a["as_of"] <= as_of]
            if field_engine.derive_review_state(acts_at) == \
                    field_pack.STATE_CONFIRMED:
                confirmed.append(report["report_id"])
        rows.append({
            "district_id": district["district_id"],
            "district_name": district["name"],
            "confirmed_reports": len(confirmed),
            "report_ids": sorted(confirmed),
            "covered": bool(confirmed),
        })
        if not confirmed:
            blockers.append(
                f"no confirmed field report for "
                f"{district['name']} ({district['district_id']}) "
                f"in {season} {crop_year} at {as_of}")
    covered = sum(1 for r in rows if r["covered"])
    lines.append(_line(
        pack.LINE_FIELD, not blockers,
        f"{covered} of {len(rows)} districts in {region} "
        "carry a confirmed field report for the season",
        blockers, {"districts": rows}))
    return lines


def verify_readiness(store, plan: dict) -> list[str]:
    """Re-derive a stored plan's lines by the second
    route and compare them whole: a line that drifted
    from the record, a ready verdict that disagrees with
    its lines, or an identity that does not match its
    content is named."""
    problems: list[str] = []
    if plan["rules_version"] != pack.RULES_VERSION:
        return [f"plan names unknown readiness pack "
                f"{plan['rules_version']}"]
    districts = region_districts(store, plan["region"])
    if [d["district_id"] for d in districts] != plan["district_ids"]:
        problems.append("the plan's districts are not the "
                        "region's districts in the register")
    expected = _expected_lines(store, plan)
    stated = {line["line"]: line for line in plan["lines"]}
    if [line["line"] for line in plan["lines"]] != pack.LINE_ORDER:
        problems.append("the plan's lines are not in the pack's "
                        "stated order")
    for want in expected:
        got = stated.get(want["line"])
        if got is None:
            problems.append(f"line {want['line']} is missing")
        elif got != want:
            problems.append(
                f"line {want['line']} does not re-derive from "
                "the record")
    blocking = [line["line"] for line in expected
                if line["status"] == pack.STATUS_INCOMPLETE]
    if plan["blocking_lines"] != blocking:
        problems.append(
            f"blocking lines {plan['blocking_lines']} != "
            f"re-derived {blocking}")
    if plan["ready"] != (not blocking):
        problems.append("the plan's ready verdict disagrees "
                        "with its lines")
    fingerprint = _fingerprint({
        "scope": [plan["region"], plan["crop_year"],
                  plan["season"]],
        "as_of": plan["as_of"], "lines": plan["lines"],
        "pack": plan["rules_version"],
    })
    if fingerprint != plan["fingerprint"] \
            or plan["readiness_id"] != (
                f"RDY-{plan['region']}-{plan['crop_year']}-"
                f"{plan['season']}-{fingerprint[:10]}"):
        problems.append("the plan's id does not match its content")
    return problems
